"""Routes for Paycor Payroll Processing and Maconomy General Journal synchronization."""

import logging
from typing import Annotated, Any
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.features.auth.dependencies import require_api_key
from app.features.paycor_payroll_integration.constants import (
    DEFAULT_COMPANY_NUMBER,
    DEFAULT_LEGAL_ENTITY_ID,
    IntegrationAction,
    IntegrationStatus,
    PAYCOR_PAYROLL_ROUTER_PREFIX,
    PAYCOR_PAYROLL_TAG,
)
from app.features.paycor_payroll_integration.mappers.payroll_journal_mapper import (
    group_gl_records_by_department,
    map_paycor_gl_record_to_maconomy_line,
    map_paycor_gl_to_maconomy_card,
    resolve_entity_code,
)
from app.features.paycor_payroll_integration.services.integration_log_service import (
    create_integration_log,
)
from app.features.paycor_payroll_integration.services.maconomy_general_journal_service import (
    MaconomyGeneralJournalService,
    MaconomyGeneralJournalServiceError,
)
from app.features.paycor_payroll_integration.services.paycor_payroll_service import (
    PaycorPayrollService,
    PaycorPayrollServiceError,
)
from app.features.paycor_payroll_integration.services.payroll_mapping_service import (
    complete_mapping,
    create_pending_mapping,
)
from app.features.paycor_payroll_integration.validators.journal_validator import (
    validate_journal_payload,
)

LOGGER = logging.getLogger(__name__)

router = APIRouter(
    prefix=PAYCOR_PAYROLL_ROUTER_PREFIX,
    tags=[PAYCOR_PAYROLL_TAG],
    dependencies=[Depends(require_api_key)],
)


def get_paycor_payroll_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> PaycorPayrollService:
    """Dependency provider for PaycorPayrollService."""
    return PaycorPayrollService(settings=settings)


def get_maconomy_journal_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> MaconomyGeneralJournalService:
    """Dependency provider for MaconomyGeneralJournalService."""
    return MaconomyGeneralJournalService(settings=settings)


PaycorPayrollServiceDependency = Annotated[
    PaycorPayrollService,
    Depends(get_paycor_payroll_service),
]
MaconomyJournalServiceDependency = Annotated[
    MaconomyGeneralJournalService,
    Depends(get_maconomy_journal_service),
]


@router.get(
    "/payroll-processing/{legal_entity_id}",
    response_model=dict[str, Any],
    summary="Get Paycor payroll processing runs and GL records by legal entity", include_in_schema=False
)
async def get_payroll_processing(
    legal_entity_id: int,
    from_check_date: str | None = Query(
        default=None,
        alias="fromCheckDate",
        description="Filter from check date in format: YYYY-MM-DDTHH:MM:SS.",
    ),
    to_check_date: str | None = Query(
        default=None,
        alias="toCheckDate",
        description="Optional filter to check date in format: YYYY-MM-DDTHH:MM:SS.",
    ),
    include_other_payruns: str = Query(
        default="All",
        alias="includeOtherPayruns",
        description="Options: 'All', 'A' (Additional), 'J' (Adjustment).",
    ),
    continuation_token: str | None = Query(default=None, alias="continuationToken"),
    payroll_service: PaycorPayrollService = Depends(get_paycor_payroll_service),
) -> dict[str, Any]:
    """Retrieve payroll processing runs and fetch employee GL records for each planner ID."""
    try:
        payroll_processing_result = await payroll_service.get_payroll_processing(
            legal_entity_id=legal_entity_id,
            from_check_date=from_check_date,
            to_check_date=to_check_date,
            include_other_payruns=include_other_payruns,
            continuation_token=continuation_token,
        )

        records = (
            payroll_processing_result.get("records", [])
            if isinstance(payroll_processing_result, dict)
            else []
        )

        payruns_summary: list[dict[str, Any]] = []
        seen_planners: set[str] = set()

        for record in records:
            raw_planner_id = (
                record.get("plannerId")
                or record.get("plannerID")
                or record.get("id")
            )
            if not raw_planner_id:
                continue

            planner_id = str(raw_planner_id).strip()
            if planner_id in seen_planners:
                continue
            seen_planners.add(planner_id)

            payruns_summary.append({
                "plannerId": planner_id,
                "groupId": record.get("groupId") or record.get("groupID"),
                "runType": record.get("runType") or record.get("runtype"),
            })

        general_ledger_by_planner_id: dict[str, Any] = {}
        for item in payruns_summary:
            current_planner_id = item["plannerId"]
            gl_data = await payroll_service.get_general_ledger_with_employee(
                legal_entity_id=legal_entity_id,
                planner_id=current_planner_id,
            )
            general_ledger_by_planner_id[current_planner_id] = {
                "plannerId": current_planner_id,
                "groupId": item.get("groupId"),
                "runType": item.get("runType"),
                "records": (
                    gl_data.get("records", [])
                    if isinstance(gl_data, dict) and "records" in gl_data
                    else gl_data
                ),
            }

        return {
            "legalEntityId": legal_entity_id,
            "payrunsSummary": payruns_summary,
            "generalLedgerByPlannerId": general_ledger_by_planner_id,
        }

    except PaycorPayrollServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    except Exception as exc:
        LOGGER.exception("Unexpected error in get_payroll_processing: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {exc}",
        )


@router.get(
    "/general-ledger-with-employee/{legal_entity_id}",
    response_model=dict[str, Any],
    summary="Get Paycor GL records with employee details for a specific planner",include_in_schema=False
)
async def get_general_ledger_with_employee(
    legal_entity_id: int,
    planner_id: str = Query(..., alias="plannerId", description="Paycor Planner ID"),
    continuation_token: str | None = Query(default=None, alias="continuationToken"),
    payroll_service: PaycorPayrollService = Depends(get_paycor_payroll_service),
) -> dict[str, Any]:
    """Retrieve Paycor General Ledger entries with employee data for a single planner ID."""
    try:
        return await payroll_service.get_general_ledger_with_employee(
            legal_entity_id=legal_entity_id,
            planner_id=planner_id,
            continuation_token=continuation_token,
        )
    except PaycorPayrollServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    except Exception as exc:
        LOGGER.exception("Unexpected error in get_general_ledger_with_employee: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {exc}",
        )


@router.post(
    "/create-journal-for-planner/{legal_entity_id}/{planner_id}",
    response_model=dict[str, Any],
    summary="Create department-wise Maconomy General Journals for a single planner",include_in_schema=False
)
async def create_journal_for_planner(
    legal_entity_id: int,
    planner_id: str,
    group_id: str | None = Query(default=None, alias="groupId"),
    run_type: str | None = Query(default=None, alias="runType"),
    company_number: str = Query(default=DEFAULT_COMPANY_NUMBER, alias="companyNumber"),
    transaction_date: str | None = Query(default=None, alias="transactionDate"),
    description: str | None = Query(default=None),
    payroll_service: PaycorPayrollService = Depends(get_paycor_payroll_service),
    maconomy_service: MaconomyGeneralJournalService = Depends(get_maconomy_journal_service),
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Fetch Paycor GL data, group by department, and generate corresponding Maconomy journals."""
    try:
        gl_response = await payroll_service.get_general_ledger_with_employee(
            legal_entity_id=legal_entity_id,
            planner_id=planner_id,
        )

        records: list[dict[str, Any]] = (
            gl_response.get("records", [])
            if isinstance(gl_response, dict) and "records" in gl_response
            else gl_response
            if isinstance(gl_response, list)
            else []
        )

        if not records:
            await create_integration_log(
                session=db,
                settings=settings,
                status=IntegrationStatus.SKIPPED,
                action=IntegrationAction.CREATE,
                message=f"No GL records found for planner {planner_id}",
                paycor_planner_id=planner_id,
            )
            return {
                "plannerId": planner_id,
                "status": "SKIPPED",
                "message": f"No GL records found for planner {planner_id}",
            }

        emp_lookup = await payroll_service.get_employee_number_lookup(
            legal_entity_id=legal_entity_id
        )
        work_location_lookup = await payroll_service.get_employee_work_location_lookup(
            legal_entity_id=legal_entity_id
        )

        grouped = group_gl_records_by_department(records)

        journals_created: list[dict[str, Any]] = []
        department_errors: list[dict[str, Any]] = []

        for dept_name, dept_records in grouped.items():
            resolved_entity = resolve_entity_code(dept_name)
            mapping_record, _ = await create_pending_mapping(
                session=db,
                legal_entity_id=legal_entity_id,
                planner_id=planner_id,
                department=dept_name,
                entity_code=resolved_entity,
                lines_count=len(dept_records),
                run_type=run_type,
            )

            try:
                card_data = map_paycor_gl_to_maconomy_card(
                    planner_id=planner_id,
                    group_id=group_id,
                    run_type=run_type,
                    company_number=company_number,
                    transaction_date=transaction_date,
                    description=description,
                    department_description=dept_name,
                )

                raw_mapped_lines = [
                    map_paycor_gl_record_to_maconomy_line(
                        r,
                        employee_id_map=emp_lookup,
                        department_description=dept_name,
                        work_location_map=work_location_lookup,
                    )
                    for r in dept_records
                ]
                # Filter out lines that have 0 amount (both debit and credit are 0.0)
                non_zero_lines = [
                    line for line in raw_mapped_lines
                    if (line.get("debitbase") or 0.0) > 0 or (line.get("creditbase") or 0.0) > 0
                ]
                lines = non_zero_lines

                # Validate whether journal should be created
                validation = validate_journal_payload(card_data, lines)
                if not validation["should_create"]:
                    LOGGER.info(
                        "Skipping Maconomy journal creation for department '%s' in planner %s: %s",
                        dept_name,
                        planner_id,
                        validation["skip_reason"],
                    )
                    await create_integration_log(
                        session=db,
                        settings=settings,
                        status=IntegrationStatus.SKIPPED,
                        action=IntegrationAction.CREATE,
                        message=validation["skip_reason"],
                        paycor_planner_id=planner_id,
                        department=dept_name,
                        journal_mapping_log=mapping_record,
                    )
                    journals_created.append({
                        "department": dept_name,
                        "status": "SKIPPED",
                        "message": validation["skip_reason"],
                        "linesCount": 0,
                    })
                    continue

                creation_result = await maconomy_service.create_journal_with_lines(
                    card_data=validation["card_data"],
                    lines=validation["lines"],
                )

                # Persist completed mapping and success audit log
                mac_journal_number = str(creation_result.get("journalNumber") or "")
                mac_instance_id = str(creation_result.get("instanceId") or "")

                await complete_mapping(
                    session=db,
                    mapping=mapping_record,
                    maconomy_journal_number=mac_journal_number,
                    maconomy_instance_id=mac_instance_id,
                    lines_count=validation["lines_count"],
                )
                await create_integration_log(
                    session=db,
                    settings=settings,
                    status=IntegrationStatus.SUCCESS,
                    action=IntegrationAction.CREATE,
                    message=f"Created Maconomy journal {mac_journal_number}",
                    paycor_planner_id=planner_id,
                    department=dept_name,
                    journal_mapping_log=mapping_record,
                )

                journals_created.append({
                    "department": dept_name,
                    "status": "SUCCESS",
                    "linesCount": validation["lines_count"],
                    "maconomy": creation_result,
                })
            except Exception as dept_err:
                LOGGER.error(
                    "Failed to create journal for department '%s' in planner %s: %s",
                    dept_name,
                    planner_id,
                    dept_err,
                )
                await create_integration_log(
                    session=db,
                    settings=settings,
                    status=IntegrationStatus.FAILED,
                    action=IntegrationAction.CREATE,
                    message=str(dept_err),
                    paycor_planner_id=planner_id,
                    department=dept_name,
                    journal_mapping_log=mapping_record,
                )
                department_errors.append({
                    "department": dept_name,
                    "error": str(dept_err),
                })

        return {
            "status": "SUCCESS" if not department_errors else "PARTIAL_SUCCESS",
            "legalEntityId": legal_entity_id,
            "plannerId": planner_id,
            "departmentsProcessed": len(journals_created),
            "journals": journals_created,
            "errors": department_errors,
        }

    except (PaycorPayrollServiceError, MaconomyGeneralJournalServiceError) as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    except Exception as exc:
        LOGGER.exception("Error in create_journal_for_planner: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {exc}",
        )


@router.post(
    "/sync-payroll-to-maconomy",
    response_model=dict[str, Any],
    summary="Sync all Paycor payroll payruns into department-wise Maconomy General Journals",
)
async def sync_payroll_to_maconomy(
    company_number: str = Query(default=DEFAULT_COMPANY_NUMBER, alias="companyNumber"),
    from_check_date: str | None = Query(
        default=None,
        alias="fromCheckDate",
        description="Filter from check date in format: YYYY-MM-DDTHH:MM:SS. Defaults to current UTC date.",
    ),
    to_check_date: str | None = Query(
        default=None,
        alias="toCheckDate",
        description="Optional filter to check date in format: YYYY-MM-DDTHH:MM:SS.",
    ),
    include_other_payruns: str = Query(
        default="All",
        alias="includeOtherPayruns",
    ),
    payroll_service: PaycorPayrollService = Depends(get_paycor_payroll_service),
    maconomy_service: MaconomyGeneralJournalService = Depends(get_maconomy_journal_service),
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Execute end-to-end sync of all Paycor payruns into Maconomy journals segregated by department."""
    legal_entity_id = DEFAULT_LEGAL_ENTITY_ID
    try:
        payroll_processing_result = await payroll_service.get_payroll_processing(
            legal_entity_id=legal_entity_id,
            from_check_date=from_check_date,
            to_check_date=to_check_date,
            include_other_payruns=include_other_payruns,
        )

        records = (
            payroll_processing_result.get("records", [])
            if isinstance(payroll_processing_result, dict)
            else []
        )

        seen_planners: set[str] = set()
        journals_created: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []

        emp_lookup = await payroll_service.get_employee_number_lookup(
            legal_entity_id=legal_entity_id
        )
        work_location_lookup = await payroll_service.get_employee_work_location_lookup(
            legal_entity_id=legal_entity_id
        )

        for record in records:
            raw_planner_id = (
                record.get("plannerId")
                or record.get("plannerID")
                or record.get("id")
            )
            if not raw_planner_id:
                continue

            planner_id = str(raw_planner_id).strip()
            if planner_id in seen_planners:
                continue
            seen_planners.add(planner_id)

            group_id = record.get("groupId") or record.get("groupID")
            run_type = record.get("runType") or record.get("runtype")

            try:
                gl_data = await payroll_service.get_general_ledger_with_employee(
                    legal_entity_id=legal_entity_id,
                    planner_id=planner_id,
                )
                gl_records = (
                    gl_data.get("records", [])
                    if isinstance(gl_data, dict) and "records" in gl_data
                    else gl_data
                    if isinstance(gl_data, list)
                    else []
                )

                if not gl_records:
                    await create_integration_log(
                        session=db,
                        settings=settings,
                        status=IntegrationStatus.SKIPPED,
                        action=IntegrationAction.CREATE,
                        message="No GL records found for planner",
                        paycor_planner_id=planner_id,
                    )
                    journals_created.append({
                        "plannerId": planner_id,
                        "status": "SKIPPED",
                        "message": "No GL records found",
                    })
                    continue

                grouped = group_gl_records_by_department(gl_records)

                dept_journals: list[dict[str, Any]] = []
                dept_errors: list[dict[str, Any]] = []

                for dept_name, dept_records in grouped.items():
                    resolved_entity = resolve_entity_code(dept_name)
                    mapping_record, _ = await create_pending_mapping(
                        session=db,
                        legal_entity_id=legal_entity_id,
                        planner_id=planner_id,
                        department=dept_name,
                        entity_code=resolved_entity,
                        lines_count=len(dept_records),
                        run_type=run_type,
                    )

                    try:
                        card_data = map_paycor_gl_to_maconomy_card(
                            planner_id=planner_id,
                            group_id=group_id,
                            run_type=run_type,
                            company_number=company_number,
                            department_description=dept_name,
                        )
                        raw_mapped_lines = [
                            map_paycor_gl_record_to_maconomy_line(
                                r,
                                employee_id_map=emp_lookup,
                                department_description=dept_name,
                                work_location_map=work_location_lookup,
                            )
                            for r in dept_records
                        ]
                        # Filter out lines that have 0 amount (both debit and credit are 0.0)
                        non_zero_lines = [
                            line for line in raw_mapped_lines
                            if (line.get("debitbase") or 0.0) > 0 or (line.get("creditbase") or 0.0) > 0
                        ]
                        lines = non_zero_lines

                        # Validate whether journal should be created
                        validation = validate_journal_payload(card_data, lines)
                        if not validation["should_create"]:
                            LOGGER.info(
                                "Skipping Maconomy journal creation for department '%s' in planner %s: %s",
                                dept_name,
                                planner_id,
                                validation["skip_reason"],
                            )
                            await create_integration_log(
                                session=db,
                                settings=settings,
                                status=IntegrationStatus.SKIPPED,
                                action=IntegrationAction.CREATE,
                                message=validation["skip_reason"],
                                paycor_planner_id=planner_id,
                                department=dept_name,
                                journal_mapping_log=mapping_record,
                            )
                            dept_journals.append({
                                "department": dept_name,
                                "status": "SKIPPED",
                                "message": validation["skip_reason"],
                                "linesCount": 0,
                            })
                            continue

                        creation_res = await maconomy_service.create_journal_with_lines(
                            card_data=validation["card_data"],
                            lines=validation["lines"],
                        )

                        mac_journal_number = str(creation_res.get("journalNumber") or "")
                        mac_instance_id = str(creation_res.get("instanceId") or "")

                        await complete_mapping(
                            session=db,
                            mapping=mapping_record,
                            maconomy_journal_number=mac_journal_number,
                            maconomy_instance_id=mac_instance_id,
                            lines_count=validation["lines_count"],
                        )
                        await create_integration_log(
                            session=db,
                            settings=settings,
                            status=IntegrationStatus.SUCCESS,
                            action=IntegrationAction.CREATE,
                            message=f"Created Maconomy journal {mac_journal_number}",
                            paycor_planner_id=planner_id,
                            department=dept_name,
                            journal_mapping_log=mapping_record,
                        )

                        dept_journals.append({
                            "department": dept_name,
                            "status": "SUCCESS",
                            "linesCount": validation["lines_count"],
                            "maconomy": creation_res,
                        })
                    except Exception as dept_err:
                        LOGGER.error(
                            "Failed to create journal for department '%s' in planner %s: %s",
                            dept_name,
                            planner_id,
                            dept_err,
                        )
                        await create_integration_log(
                            session=db,
                            settings=settings,
                            status=IntegrationStatus.FAILED,
                            action=IntegrationAction.CREATE,
                            message=str(dept_err),
                            paycor_planner_id=planner_id,
                            department=dept_name,
                            journal_mapping_log=mapping_record,
                        )
                        dept_errors.append({
                            "department": dept_name,
                            "error": str(dept_err),
                        })

                journals_created.append({
                    "plannerId": planner_id,
                    "groupId": group_id,
                    "runType": run_type,
                    "status": "SUCCESS" if not dept_errors else "PARTIAL_SUCCESS",
                    "departmentsProcessed": len(dept_journals),
                    "journals": dept_journals,
                    "departmentErrors": dept_errors,
                })

            except Exception as planner_err:
                LOGGER.error(
                    "Failed to process planner %s: %s",
                    planner_id,
                    planner_err,
                )
                await create_integration_log(
                    session=db,
                    settings=settings,
                    status=IntegrationStatus.FAILED,
                    action=IntegrationAction.CREATE,
                    message=str(planner_err),
                    paycor_planner_id=planner_id,
                )
                errors.append({
                    "plannerId": planner_id,
                    "error": str(planner_err),
                })

        return {
            "legalEntityId": legal_entity_id,
            "totalPayrunsFound": len(seen_planners),
            "createdJournals": journals_created,
            "errors": errors,
        }

    except PaycorPayrollServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    except Exception as exc:
        LOGGER.exception("Unexpected error in sync_payroll_to_maconomy: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {exc}",
        )


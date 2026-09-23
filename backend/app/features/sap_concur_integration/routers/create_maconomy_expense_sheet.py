from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.features.sap_concur_integration.constants import (
    IntegrationAction,
    IntegrationStatus,
)
from app.db.session import get_db
from app.features.auth.dependencies import require_api_key
from app.features.sap_concur_integration.services.sap_concur_service import SAPConcurService
from app.features.sap_concur_integration.schemas.sap_concur import ExpenseReportEmailRequest
from app.features.sap_concur_integration.mappers import (
    map_expense_report_to_summary,
    map_expense_to_summary,
)
from app.features.sap_concur_integration.services import (
    MaconomyService,
    MaconomyServiceError,
    expensesheet_expensereport_mapping_service,
    integration_log_service,
)


router = APIRouter(
    prefix="/sap-concur",
    tags=["sap-concur-integration"],
    dependencies=[Depends(require_api_key)],
)
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]

@router.post(
    "/sap-concur-test", 
    response_model=dict[str, Any]
)
async def sap_concur():
    return {
        "message": "SAP Concur Integration"
    }

@router.post(
    "/get-employee-from-maconomy",
    response_model=list[dict[str, Any]],
)
async def get_employee(
) -> list[dict[str, Any]]:
    try:
        expense_reports = await MaconomyService().get_all_expense_sheets_from_maconomy() #get_all_employees_from_maconomy()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch expense reports from SAP Concur: {str(exc)}",
        ) from exc

    return expense_reports


@router.post(
    "/sync-sap-concur-expense-reports-with-maconomy",
    response_model=list[dict[str, Any]],
)
async def sync_todays_created_sap_concur_expense_reports_with_maconomy(
    session: DatabaseSession,
) -> list[dict[str, Any]]:

    results: list[dict[str, Any]] = []
    print("======== get_yesterday_and_todays_new_expense_reports_from_sap_concur ========")
    try:
        new_expense_reports = (
            await SAPConcurService().get_yesterday_and_todays_new_expense_reports_from_sap_concur()
        )
            # Guard: no new expense reports found — log and return early
        if not new_expense_reports:
            no_reports_message = "No new expense reports found in SAP Concur for the current sync window"
            print(no_reports_message)
            await _save_integration_log(
                session,
                report_id="N/A",
                action=IntegrationAction.CREATE,
                integration_status=IntegrationStatus.SKIPPED,
                message=no_reports_message,
            )
            return [
                {
                    "report_id": "N/A",
                    "status": "SKIPPED",
                    "message": no_reports_message,
                }
            ]

    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch new expense reports from SAP Concur: {str(exc)}",
        ) from exc

    try:
        print("Retrieving employees")
        employees = await MaconomyService().get_all_employees_from_maconomy()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch Maconomy employees: {str(exc)}",
        ) from exc

    # Fetch all existing expense sheets from Maconomy for duplicate detection
    try:
        print("Retrieving expense sheets")
        maconomy_expense_sheets = await MaconomyService().get_all_expense_sheets_from_maconomy()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch Maconomy expense sheets: {str(exc)}",
        ) from exc

    # Build a set of sap_report_id values already synced in Maconomy
    synced_report_ids = {
        sheet["sap_report_id"]
        for sheet in maconomy_expense_sheets
        if sheet.get("sap_report_id")
    }

    owner_employee_map = build_owner_employee_mapping(new_expense_reports, employees)
    print("For Loop")
    print("new_expense_reports:", new_expense_reports)
    for report in new_expense_reports:
        print("For Loop")
        expense_report_id = report.get("ID")
        expense_report_login_id = report.get("OwnerLoginID")
        if not expense_report_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="SAP Concur ReportID is required",
            )

        matched_employee = owner_employee_map.get(expense_report_id)
        print("matched_employee:", matched_employee)

        if matched_employee is None:
            skip_message = (
                f"No matching Maconomy employee found for OwnerLoginID: "
                f"{expense_report_login_id}"
            )
            results.append({
                "report_id": expense_report_id,
                "status": "SKIPPED",
                "message": skip_message,
            })
            await _save_integration_log(
                session,
                report_id=expense_report_id,
                action=IntegrationAction.CREATE,
                integration_status=IntegrationStatus.SKIPPED,
                message=skip_message,
                employeeemail=expense_report_login_id,
            )
            continue

        # Check if expense sheet already exists in Maconomy via sap_report_id
        if expense_report_id in synced_report_ids:
            skip_message = (
                "Expense sheet already exists in Maconomy (sap_report_id match)"
            )
            results.append({
                "report_id": expense_report_id,
                "status": "SKIPPED",
                "message": skip_message,
            })
            await _save_integration_log(
                session,
                report_id=expense_report_id,
                action=IntegrationAction.CREATE,
                integration_status=IntegrationStatus.SKIPPED,
                message=skip_message,
                employeeemail=expense_report_login_id,
            )
            continue

        employee_email = matched_employee["email"]
        employee_number = matched_employee["employeenumber"]

        try:
            print("create_maconomy_expense_sheets")
            result = await create_maconomy_expense_sheet(
                report_id=expense_report_id,
                login_id=expense_report_login_id,
                session=session,
                action_from="SYNCAPI",
                employee_email=employee_email,
                employee_number=employee_number,
            )

            results.append({
                "report_id": expense_report_id,
                "status": "SUCCESS",
                "message": "Maconomy expense sheet created successfully",
                "result": result,
            })

        except HTTPException as exc:
            await session.rollback()
            results.append({
                "report_id": expense_report_id,
                "status": "FAILED",
                "message": exc.detail,
            })

        except Exception as exc:
            await session.rollback()
            results.append({
                "report_id": expense_report_id,
                "status": "FAILED",
                "message": str(exc),
            })

    return results


@router.post(
    "/get-expense-reports-by-email",
    response_model=list[dict[str, Any]],
)
async def get_expense_reports_by_email(
    request: ExpenseReportEmailRequest,
) -> list[dict[str, Any]]:
    """
    Retrieve mapped SAP Concur expense report summaries and expense summaries for a given Email ID.
    
    Flow: Email ID -> Expense Report IDs -> SAP Concur User ID -> Mapped Report + Expense Summaries
    """
    email_id = request.email_id
    detailed_reports: list[dict[str, Any]] = []

    # Step 1: Get expense report IDs using Email ID
    try:
        expense_reports = await SAPConcurService().get_expense_reports_by_email_id_from_sap_concur(email_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch expense reports from SAP Concur: {str(exc)}",
        ) from exc

    if not expense_reports:
        return detailed_reports

    # Step 2: Get SAP Concur User ID using Email ID
    try:
        user_id = await SAPConcurService().get_user_id_by_login_id(owner_login_id=email_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch SAP Concur User ID: {str(exc)}",
        ) from exc

    # Step 3: Get detailed report and expenses for each Report ID
    for report in expense_reports:
        report_id = report.get("ID")
        if not report_id:
            continue

        try:
            report_detail = await SAPConcurService().get_report_by_id(
                report_id=report_id,
                user_id=user_id,
                context_type="TRAVELER",
            )
            if report_detail is None:
                continue
        except Exception as exc:
            print(f"Failed to fetch report {report_id}: {str(exc)}")
            continue

        # Step 4: Get expenses for this report
        try:
            expenses = await SAPConcurService().get_expenses_by_report_id(
                report_id=report_id,
                user_id=user_id,
                context_type="TRAVELER",
            )
        except Exception as exc:
            print(f"Failed to fetch expenses for report {report_id}: {str(exc)}")
            expenses = []

        # Step 5: Map report and expenses to summaries
        report_summary = map_expense_report_to_summary(report_detail)
        expense_summaries = [map_expense_to_summary(exp) for exp in expenses]

        detailed_reports.append({
            "report": report_summary,
            "expenses": expense_summaries,
        })

    return detailed_reports


async def create_maconomy_expense_sheet(
    report_id: str,
    login_id: str,
    session: AsyncSession,
    action_from: str = "CREATEAPI",
    employee_email: str | None = None,
    employee_number: str | None = None,
) -> dict[str, Any]:
    """Create Maconomy expense sheet + lines for a SAP Concur report.

    Guarantees at most ONE integration-log row per report:
    - Inner failure paths log exactly one FAILED/SKIPPED row, then raise
      HTTPException (outer handlers stay log-free).
    - Success/partial/all-lines-failed paths write one consolidated final row.
    - Defensive outer catch writes a single FAILED row only if an unexpected
      error escapes without any prior log.
    """
    try:
        return await _run_create_maconomy_expense_sheet(
            report_id=report_id,
            login_id=login_id,
            session=session,
            action_from=action_from,
            employee_email=employee_email,
            employee_number=employee_number,
        )
    except HTTPException:
        # Inner failure paths already wrote their single log row before raising.
        raise
    except Exception as exc:
        # Gap protection: unexpected error that bypassed all inner log paths.
        try:
            await _save_integration_log(
                session,
                report_id=report_id,
                action=IntegrationAction.CREATE,
                integration_status=IntegrationStatus.FAILED,
                message=f"Expense sheet processing failed: {exc}",
                employeeemail=employee_email,
            )
        except Exception as log_exc:
            print(
                f"Failed to write integration log for report {report_id}: {log_exc}"
            )
        raise


async def _run_create_maconomy_expense_sheet(
    report_id: str,
    login_id: str,
    session: AsyncSession,
    action_from: str = "CREATEAPI",
    employee_email: str | None = None,
    employee_number: str | None = None,
) -> dict[str, Any]:
    print("======= create_maconomy_expense_sheet ==========")

    try:
        user_id = await SAPConcurService().get_user_id_by_login_id(owner_login_id=login_id)
        report_detail = await SAPConcurService().get_report_by_id(report_id, user_id, context_type="TRAVELER")
    except Exception as e:
        message = f"Failed to fetch SAP Concur report details: {str(e)}"
        await _save_integration_log(
            session,
            report_id=report_id,
            action=IntegrationAction.CREATE,
            integration_status=IntegrationStatus.FAILED, 
            message=message,
            employeeemail=employee_email,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=message
        )

    if report_detail is None:
        message = "SAP Concur report not found"
        await _save_integration_log(
            session,
            report_id=report_id,
            action=IntegrationAction.CREATE,
            integration_status=IntegrationStatus.FAILED, 
            message=message,
            employeeemail=employee_email,
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=message
        )


    # Maconomy Service initiates
    maconomy_service = MaconomyService()
    mapping = None
    is_new_expensesheet = True
    expensesheet_was_reconciled = False

    print("======== Maconomy service initiated =========")

    if is_new_expensesheet:
        try:
            maconomy_result = await maconomy_service.create_expense_sheet(
                report_detail, employee_number=employee_number
            )
        except MaconomyServiceError as exc:
            message = f"Failed to create Maconomy expense sheet: {str(exc)}"
            await _raise_expense_sheet_creation_error(session, report_id, exc)
            # if not exc.reconciliation_allowed: 
            #     await _raise_expense_sheet_creation_error( session, report_id, exc, )

            # try:
            #     reconciled_expensesheet = await maconomy_service.get_expensesheet_by_expensesheetnumber(mapping.maconomy_expensesheet_no)
            # except MaconomyServiceError as e:
            #     await _raise_expense_sheet_creation_error(session, report_id, e)

            # if reconciled_expensesheet is None:
            #     await _raise_expense_sheet_creation_error(
            #         session, report_id, e
            #     )

        try:
            records = maconomy_result["panes"]["card"]["records"]
            expense_sheet_number = records[0]["data"]["expensesheetnumber"]
        except (KeyError, TypeError, IndexError) as exc:
            raise MaconomyServiceError("Invalid Maconomy expense sheet response") from exc

        if not isinstance(expense_sheet_number, str) or not expense_sheet_number.strip():
            raise MaconomyServiceError("Invalid Maconomy expense sheet response")

        maconomy_expense_sheet_result = {
            "expense_sheet_number": expense_sheet_number,
        }

        expensesheet_was_reconciled = True

        # except MaconomyServiceError as e:
        #     await _raise_expense_sheet_creation_error(session, report_id, e)

        mapping = await expensesheet_expensereport_mapping_service.create_mapping(
            session,
            sap_concur_expensereport_id=report_id,
            maconomy_expensesheet_no=maconomy_expense_sheet_result["expense_sheet_number"],
            maconomy_employee_number=employee_number,
        )


    # else:
    #     try:
    #         expense_sheet_detail = ( 

    #             await maconomy_service.get_expensesheet_by_expensesheetnumber( 
    #                 mapping.maconomy_expensesheet_no 
    #             ) 
    #         )
    #     except MaconomyServiceError as exc:
    #         await _save_integration_log(

    #             session, 
    #             report_id, 
    #             IntegrationAction.CREATE, 
    #             IntegrationStatus.FAILED, str(exc),
    #         )

    # --- Expense Line Items Creation ---
    try:
        concur_expenses = await SAPConcurService().get_expenses_by_report_id(
            report_id=report_id,
            user_id=user_id,
            context_type="TRAVELER",
        )
    except Exception as exc:
        message = f"Failed to retrieve SAP Concur expenses: {str(exc)}"
        await _save_integration_log(
            session,
            report_id=report_id,
            action=IntegrationAction.CREATE,
            integration_status=IntegrationStatus.FAILED,
            message=message,
            employeeemail=employee_email,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=message
        )

    # --- Expense Line Items Creation (fault-tolerant; structured results) ---
    line_results: dict[str, Any] = {
        "succeeded": [],
        "failed": [],
        "total": 0,
        "success_count": 0,
        "failure_count": 0,
    }

    if concur_expenses:
        try:
            line_results = await maconomy_service.create_expense_line_items(
                expense_sheet_number=expense_sheet_number,
                expense_data=concur_expenses,
                employee_number=employee_number,
                report_id=report_id,
                user_id=user_id,
                context_type="TRAVELER",
            )
            print("line_item_results:", line_results)

        except MaconomyServiceError as exc:
            # Report-level: shared setup failed before any line was processed.
            # Single FAILED row for this report, then raise (no second row).
            message = f"Failed to create Maconomy expense line items: {str(exc)}"
            await _save_integration_log(
                session,
                report_id=report_id,
                action=IntegrationAction.CREATE,
                integration_status=IntegrationStatus.FAILED,
                message=message,
                employeeemail=employee_email,
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY, detail=message
            )

        # Metadata from SUCCESSES only — expense_id-keyed (no positional
        # concur_expenses[idx] assumption).
        expense_line_metadata: dict[str, str] = {}
        for entry in line_results.get("succeeded", []):
            expense_id = str(entry.get("expense_id", ""))
            line_number = str(entry.get("line_number", ""))
            print("expense_id:", expense_id, "line_number:", line_number)
            if expense_id and line_number:
                expense_line_metadata[expense_id] = line_number

        if expense_line_metadata:
            try:
                await expensesheet_expensereport_mapping_service.update_mapping_metadata(
                    session,
                    mapping_id=mapping.id,
                    expense_line_metadata=expense_line_metadata,
                )
            except Exception as meta_exc:
                # Non-fatal: metadata failure must not fail a processed report
                # or create/duplicate a log row.
                print(
                    f"Failed to update expense line metadata for report "
                    f"{report_id} (non-fatal): {meta_exc}"
                )

    # --- Exactly ONE consolidated report-level log (Option B statuses) ---
    total = int(line_results.get("total", 0))
    success_count = int(line_results.get("success_count", 0))
    failure_count = int(line_results.get("failure_count", 0))

    base_message = (
        "SAP Concur Expense sheet and line items reconciled and synchronized successfully"
        if expensesheet_was_reconciled
        else "SAP Concur Expense Sheet and line items created successfully"
        if is_new_expensesheet
        else "Incomplete SAP Concur create workflow resumed successfully"
    )

    if total == 0 or failure_count == 0:
        # No lines, or all lines succeeded — preserve existing success behavior.
        final_status = IntegrationStatus.SUCCESS
        detail = f" ({success_count}/{total} lines succeeded)" if total else ""
        final_message = f"{base_message}{detail}"
    elif success_count == 0:
        # Sheet created but ALL expense lines failed.
        final_status = IntegrationStatus.FAILED
        final_message = (
            f"Expense sheet {expense_sheet_number} created but ALL "
            f"{total} expense lines failed.\n"
            f"{_format_line_results(line_results)}"
        )
    else:
        # Option B fallback: partial outcome → SUCCESS + PARTIAL: prefix
        # (no PARTIAL_SUCCESS enum; distinguishable via message text).
        final_status = IntegrationStatus.SUCCESS
        final_message = (
            f"PARTIAL: Expense sheet {expense_sheet_number} created; "
            f"{success_count}/{total} lines succeeded, "
            f"{failure_count} failed.\n"
            f"{_format_line_results(line_results)}"
        )

    try:
        await integration_log_service.create_log(
            session,
            mapping_id=mapping.id,
            report_id=report_id,
            status=final_status,
            action=IntegrationAction.CREATE,
            message=final_message,
            employeeemail=employee_email,
        )
    except Exception as log_exc:
        # Safe logging: a logging failure must not mask the processing outcome.
        print(
            f"Failed to write integration log for report {report_id}: {log_exc}"
        )

    return maconomy_expense_sheet_result


def _format_line_results(line_results: dict[str, Any]) -> str:
    """Render per-line success/failure detail for the consolidated log message,
    preserving original exception text for failed lines."""
    parts: list[str] = []
    for entry in line_results.get("succeeded", []):
        parts.append(
            f"[SUCCESS] {entry.get('expense_id', '')} -> Maconomy line "
            f"{entry.get('line_number', '')}"
        )
    for entry in line_results.get("failed", []):
        parts.append(
            f"[FAILED] {entry.get('expense_id', '')} -> "
            f"{entry.get('message', '')} ({entry.get('error_type', '')})"
        )
    return "\n".join(parts)


async def _save_integration_log(
    session: AsyncSession,
    report_id: str,
    action: IntegrationAction,
    integration_status: IntegrationStatus,
    message: str,
    employeeemail: str | None = None,
) -> None:
    
    mapping = await expensesheet_expensereport_mapping_service.get_mapping_by_report_id(
        session, report_id
    )
    mapping_id = mapping.id if mapping else None
    await integration_log_service.create_log(
        session,
        mapping_id=mapping_id,
        report_id=report_id,
        status=integration_status,
        action=action,
        message=message,
        employeeemail=employeeemail,
    )


async def _raise_expense_sheet_creation_error(
    session: AsyncSession,
    # expensesheet_number: str,
    report_id: str,
    exc: MaconomyServiceError,
) -> None:
    await _save_integration_log(
        session,
        report_id=report_id,
        action=IntegrationAction.CREATE,
        integration_status=IntegrationStatus.FAILED,
        message=str(exc),
    )
    # await _save_integration_log(
    #     session,
    #     IntegrationAction.CREATE,
    #     IntegrationStatus.FAILED,
    #     str(exc),
    #     # expensesheet_number=expensesheet_number,
    #     report_id
    # )
    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail="Unable to create or reconcile entity in CaseWare Cloud",
    ) from exc


def map_owner_to_maconomy_employee(
    owner_login_id: str, employees: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Map a SAP Concur OwnerLoginID to a Maconomy employee by matching email."""
    if not owner_login_id:
        return None
    owner_login_id_lower = owner_login_id.lower()
    for employee in employees:
        if employee.get("email", "").lower() == owner_login_id_lower:
            return {
                "email": employee["email"],
                "employeenumber": employee["employeenumber"],
                "employeename": employee.get("employeename", ""),
            }
    return None


def build_owner_employee_mapping(
    new_expense_reports: list[dict[str, Any]],
    employees: list[dict[str, Any]],
) -> dict[str, dict[str, Any] | None]:
    """Pre-compute the OwnerLoginID-to-Maconomy-employee mapping for all reports."""
    mapping: dict[str, dict[str, Any] | None] = {}
    
    for report in new_expense_reports:
        report_id = report.get("ID")
        owner_login_id = report.get("OwnerLoginID")
        if report_id:
            mapping[report_id] = map_owner_to_maconomy_employee(
                owner_login_id, employees
            )
    return mapping



# @router.post(
#     "/sync-sap-concur-report-into-maconomy-by-report-id",
#     response_model=list[dict[str, Any]],
# )
# async def s(
#     report_id: str,
# ) -> list[dict[str, Any]]:

    # # Check if the report is present in the sap concur or not
    # try:
    #     expense_reports = await SAPConcurService().get_yesterday_and_todays_new_expense_reports_from_sap_concur()
    # except Exception as exc:
    #     raise HTTPException(
    #         status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    #         detail=f"Failed to fetch expense reports from SAP Concur: {str(exc)}",
    #     ) from exc



    # Check if report is present in the retrieved report
    # for report in expense_reports:
    #     existing_report_id = report.get("reportId")

    return None


    # If no then stop the process and return that report does not exist in the sap concur

    # If yes then retrieve owner login id and check if employee matches with the maconomy email and it has vendor or not

    # If no then stop the process and return that employee not found

    # If yes then check if expense sheet is created for that report

        # If yes then check if all expense lines are created or not
        # If yes then then check if the expense line item in maconomy are present in the sap concur,stop the process and return that already sync
        # If not then create all the expense lines in maconomy

    # If no then create the expense sheet and expense line items
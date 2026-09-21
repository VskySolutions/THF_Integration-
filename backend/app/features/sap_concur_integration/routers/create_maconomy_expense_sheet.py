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
    "/sync-todays-created-sap-concur-expense-reports-with-maconomy",
    response_model=list[dict[str, Any]],
)
async def sync_todays_created_sap_concur_expense_reports_with_maconomy(
    session: DatabaseSession,
) -> list[dict[str, Any]]:

    results: list[dict[str, Any]] = []
    try:
        new_expense_reports = (
            await SAPConcurService().get_yesterday_and_todays_new_expense_reports_from_sap_concur()
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch new expense reports from SAP Concur: {str(exc)}",
        ) from exc
    

    for report in new_expense_reports:
        expense_report_id = report.get("ID")
        if not expense_report_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="SAP Concur ReportID is required",
            )

        try:
            result = await create_maconomy_expense_sheet(
                report_id=expense_report_id, session=session, action_from="SYNCAPI"
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



async def create_maconomy_expense_sheet(
    report_id: str,
    session: AsyncSession,
    action_from:str = "CREATEAPI"
) -> dict[str, Any]:

    existing_mapping = await expensesheet_expensereport_mapping_service.get_mapping_by_report_id(
        report_id, session
    )

    # If a mapping already exists for the given report_id, raise an HTTPException with a 400 status code and a message indicating that the mapping already exists.
    if existing_mapping:
        message = (
            "Maconomy expense sheet record is already created for this Maconomy Job "
            "number"
        )
        integration_status = (
            IntegrationStatus.FAILED
            if action_from == "CREATEAPI"
            else IntegrationStatus.SKIPPED
        )
        await integration_log_service.create_log(
            session,
            mapping_id=existing_mapping.id,
            expense_report_id=report_id,
            status=integration_status,
            action=IntegrationAction.CREATE,
            message=message,
        )
        if action_from == "CREATEAPI":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=message,
            )
        return None

    try:
        report_detail = await SAPConcurService().get_report_by_id(report_id)
    except Exception as e:
        message = f"Failed to fetch SAP Concur report details: {str(e)}"
        await _save_integration_log(
            session,
            report_id=report_id,
            action=IntegrationAction.CREATE,
            integration_status=IntegrationStatus.FAILED, 
            message=message,
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
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=message
        )

    # Maconomy Service initiates
    maconomy_service = MaconomyService()
    mapping = existing_mapping
    is_new_expensesheet = mapping is None
    expensesheet_was_reconciled = False

    if is_new_expensesheet:
        try:
            maconomy_result = await maconomy_service.create_expense_sheet(report_detail)
        except MaconomyServiceError as e:
            message = f"Failed to create Maconomy expense sheet: {str(e)}"

            try:
                reconciled_expensesheet = await maconomy_service.get_expensesheet_by_expensesheetnumber(report_id)
            except MaconomyServiceError as e:
                await _raise_expense_sheet_creation_error(session, report_id, e)

            if reconciled_expensesheet is None:
                await _raise_expense_sheet_creation_error(
                    session, report_id, e
                )

            maconomy_expense_sheet_result = {
                "expense_sheet_number": str(maconomy_result.get("expenseSheetNumber", "")),
            }

            expensesheet_was_reconciled = True

        except MaconomyServiceError as e:
            await _raise_expense_sheet_creation_error(session, report_id, e)

        mapping = await expensesheet_expensereport_mapping_service.create_mapping(
            session,
            sap_concur_expensereport_id=report_id,
            maconomy_expensesheet_no=maconomy_expense_sheet_result["expense_sheet_number"],
        )
        

    
    return maconomy_expense_sheet_result
    # {
    #     "report_detail": report_detail,
    #     "message": "Create Maconomy Expense Sheet" 
    # }
    

async def _save_integration_log(
    session: AsyncSession,
    report_id: str,
    action: IntegrationAction,
    integration_status: IntegrationStatus,
    message: str,
) -> None:
    
    mapping = await expensesheet_expensereport_mapping_service.get_mapping_by_report_id(
        session, report_id
    )
    mapping_id = mapping.id if mapping else None
    await integration_log_service.create_log(
        session,
        mapping_id=mapping_id,
        expensesheet_number=report_id,
        status=integration_status,
        action=action,
        message=message,
    )


async def _raise_expense_sheet_creation_error(
    session: AsyncSession,
    expensesheet_number: str,
    exc: MaconomyServiceError,
) -> None:
    await _save_integration_log(
        session,
        IntegrationAction.CREATE,
        IntegrationStatus.FAILED,
        str(exc),
        expensesheet_number=expensesheet_number,
    )
    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail="Unable to create or reconcile entity in CaseWare Cloud",
    ) from exc


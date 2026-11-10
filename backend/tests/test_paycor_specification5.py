"""Unit tests for MaconomySpecification5Service and Specification 5 sync flow."""

import asyncio
import json
import uuid
from unittest.mock import AsyncMock

from app.features.paycor_integration.constants import (
    IntegrationAction,
    IntegrationStatus,
    Spec5CreationStatus,
)
from app.features.paycor_integration.models.employee_mapping_log import (
    PaycorEmployeeMappingLog,
)
from app.features.paycor_integration.services.maconomy_specification5_service import (
    MaconomySpecification5Service,
    MaconomySpecification5ServiceError,
)
from app.features.paycor_integration.services.specification5_log_service import (
    Specification5LogService,
)


def run_async(coro):
    return asyncio.run(coro)


def test_build_spec5_payload_formats_correctly():
    service = MaconomySpecification5Service()
    initialized_mock = {
        "specification5name": "",
        "description": "",
        "blocked": True,
        "overwriteaccount": True,
        "statistic1": "",
    }

    payload = service._build_spec5_payload(
        initialized_data=initialized_mock,
        employee_number="222222",
        description="Sarvesh,VSKYTest",
    )

    print("\n" + "=" * 60)
    print("SPECIFICATION 5 SUBMIT PAYLOAD (to /data/panes/card):")
    print("=" * 60)
    submit_body = {"data": payload}
    print(json.dumps(submit_body, indent=2))
    print("=" * 60 + "\n")

    assert payload["specification5name"] == "222222"
    assert payload["description"] == "Sarvesh,VSKYTest"
    assert payload["blocked"] is False
    assert payload["statistic1"] == ""


def test_create_spec5_empty_employee_number_raises_error():
    service = MaconomySpecification5Service()

    async def _test():
        try:
            await service.create_specification5(
                employee_number="",
                description="Doe, John",
            )
            assert False, "Expected MaconomySpecification5ServiceError"
        except MaconomySpecification5ServiceError as exc:
            assert "Employee number is required" in str(exc)

    run_async(_test())


def test_specification5_log_service_success():
    async def _test():
        session = AsyncMock()
        mapping = PaycorEmployeeMappingLog(
            id=uuid.uuid4(),
            paycor_employee_id=uuid.uuid4(),
            paycor_legal_entity_id=101,
            paycor_employee_number="222222",
        )

        log_entry = await Specification5LogService.record_specification5_result(
            session,
            mapping=mapping,
            paycor_employee_id=mapping.paycor_employee_id,
            paycor_employee_number="222222",
            legal_entity_id=101,
            status=Spec5CreationStatus.SUCCESS,
            spec5_name="222222",
        )

        print("\n" + "=" * 60)
        print("DATABASE AUDIT LOG ENTRY (paycor_integration_logs):")
        print("=" * 60)
        log_dict = {
            "paycor_employee_id": str(log_entry.paycor_employee_id),
            "paycor_employee_number": log_entry.paycor_employee_number,
            "status": log_entry.status.value,
            "action": log_entry.action.value,
            "message": log_entry.message,
            "mapping.is_spec5_created": mapping.is_spec5_created.value,
            "mapping.maconomy_spec5_name": mapping.maconomy_spec5_name,
        }
        print(json.dumps(log_dict, indent=2))
        print("=" * 60 + "\n")

        assert mapping.is_spec5_created == Spec5CreationStatus.SUCCESS
        assert mapping.maconomy_spec5_name == "222222"
        assert log_entry.status == IntegrationStatus.SUCCESS
        assert log_entry.action == IntegrationAction.CREATE
        assert "created successfully" in log_entry.message
        session.add.assert_called_once()

    run_async(_test())


def test_specification5_log_service_failure():
    async def _test():
        session = AsyncMock()
        mapping = PaycorEmployeeMappingLog(
            id=uuid.uuid4(),
            paycor_employee_id=uuid.uuid4(),
            paycor_legal_entity_id=101,
            paycor_employee_number="222222",
        )

        log_entry = await Specification5LogService.record_specification5_result(
            session,
            mapping=mapping,
            paycor_employee_id=mapping.paycor_employee_id,
            paycor_employee_number="222222",
            legal_entity_id=101,
            status=Spec5CreationStatus.FAILURE,
            error_message="Maconomy HTTP 500 error",
        )

        print("\n" + "=" * 60)
        print("DATABASE FAILURE AUDIT LOG ENTRY (paycor_integration_logs):")
        print("=" * 60)
        log_dict = {
            "paycor_employee_id": str(log_entry.paycor_employee_id),
            "paycor_employee_number": log_entry.paycor_employee_number,
            "status": log_entry.status.value,
            "action": log_entry.action.value,
            "message": log_entry.message,
            "mapping.is_spec5_created": mapping.is_spec5_created.value,
        }
        print(json.dumps(log_dict, indent=2))
        print("=" * 60 + "\n")

        assert mapping.is_spec5_created == Spec5CreationStatus.FAILURE
        assert log_entry.status == IntegrationStatus.FAILED
        assert "Maconomy HTTP 500 error" in log_entry.message
        session.add.assert_called_once()

    run_async(_test())


if __name__ == "__main__":
    test_build_spec5_payload_formats_correctly()
    print("✓ test_build_spec5_payload_formats_correctly passed")

    test_create_spec5_empty_employee_number_raises_error()
    print("✓ test_create_spec5_empty_employee_number_raises_error passed")

    test_specification5_log_service_success()
    print("✓ test_specification5_log_service_success passed")

    test_specification5_log_service_failure()
    print("✓ test_specification5_log_service_failure passed")

    print("\nAll 4 tests passed successfully!")

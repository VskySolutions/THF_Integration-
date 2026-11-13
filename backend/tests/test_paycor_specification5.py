"""Unit tests for MaconomySpecification5Service, MaconomyPurposeService, and their sync/logging flows."""

import asyncio
import json
import uuid
from unittest.mock import AsyncMock

from app.features.paycor_integration.constants import (
    IntegrationAction,
    IntegrationStatus,
    PurposeCreationStatus,
    Spec5CreationStatus,
)
from app.features.paycor_integration.models.employee_mapping_log import (
    PaycorEmployeeMappingLog,
)
from app.features.paycor_integration.services.maconomy_purpose_service import (
    MaconomyPurposeService,
    MaconomyPurposeServiceError,
)
from app.features.paycor_integration.services.maconomy_specification5_service import (
    MaconomySpecification5Service,
    MaconomySpecification5ServiceError,
)
from app.features.paycor_integration.services.purpose_log_service import (
    PurposeLogService,
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
        employee_number="100028",
        description="Ferguson, Bill",
    )

    assert payload["specification5name"] == "100028"
    assert payload["description"] == "Ferguson, Bill"
    assert payload["blocked"] is False
    assert payload["statistic1"] == ""


def test_build_purpose_payload_formats_correctly():
    service = MaconomyPurposeService()
    initialized_mock = {
        "purposename": "",
        "description": "",
        "blocked": True,
        "overwriteaccount": True,
        "statistic1": "",
    }

    payload = service._build_purpose_payload(
        initialized_data=initialized_mock,
        employee_number="100028",
        description="Ferguson, Bill",
    )

    assert payload["purposename"] == "100028"
    assert payload["description"] == "Ferguson, Bill"
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


def test_create_purpose_empty_employee_number_raises_error():
    service = MaconomyPurposeService()

    async def _test():
        try:
            await service.create_purpose(
                employee_number="",
                description="Doe, John",
            )
            assert False, "Expected MaconomyPurposeServiceError"
        except MaconomyPurposeServiceError as exc:
            assert "Employee number is required" in str(exc)

    run_async(_test())


def test_specification5_log_service_success():
    async def _test():
        session = AsyncMock()
        mapping = PaycorEmployeeMappingLog(
            id=uuid.uuid4(),
            paycor_employee_id=uuid.uuid4(),
            paycor_legal_entity_id=101,
            paycor_employee_number="100028",
        )

        log_entry = await Specification5LogService.record_specification5_result(
            session,
            mapping=mapping,
            paycor_employee_id=mapping.paycor_employee_id,
            paycor_employee_number="100028",
            legal_entity_id=101,
            status=Spec5CreationStatus.SUCCESS,
            spec5_name="100028",
        )

        assert mapping.is_spec5_created == Spec5CreationStatus.SUCCESS
        assert mapping.maconomy_spec5_name == "100028"
        assert log_entry.status == IntegrationStatus.SUCCESS
        assert log_entry.action == IntegrationAction.CREATE
        assert "created successfully" in log_entry.message
        session.add.assert_called_once()

    run_async(_test())


def test_purpose_log_service_success():
    async def _test():
        session = AsyncMock()
        mapping = PaycorEmployeeMappingLog(
            id=uuid.uuid4(),
            paycor_employee_id=uuid.uuid4(),
            paycor_legal_entity_id=101,
            paycor_employee_number="100028",
        )

        log_entry = await PurposeLogService.record_purpose_result(
            session,
            mapping=mapping,
            paycor_employee_id=mapping.paycor_employee_id,
            paycor_employee_number="100028",
            legal_entity_id=101,
            status=PurposeCreationStatus.SUCCESS,
            purpose_name="100028",
        )

        assert mapping.is_purpose_created == PurposeCreationStatus.SUCCESS
        assert mapping.maconomy_purpose_name == "100028"
        assert log_entry.status == IntegrationStatus.SUCCESS
        assert log_entry.action == IntegrationAction.CREATE
        assert "created successfully" in log_entry.message
        session.add.assert_called_once()

    run_async(_test())


if __name__ == "__main__":
    test_build_spec5_payload_formats_correctly()
    print("✓ test_build_spec5_payload_formats_correctly passed")

    test_build_purpose_payload_formats_correctly()
    print("✓ test_build_purpose_payload_formats_correctly passed")

    test_create_spec5_empty_employee_number_raises_error()
    print("✓ test_create_spec5_empty_employee_number_raises_error passed")

    test_create_purpose_empty_employee_number_raises_error()
    print("✓ test_create_purpose_empty_employee_number_raises_error passed")

    test_specification5_log_service_success()
    print("✓ test_specification5_log_service_success passed")

    test_purpose_log_service_success()
    print("✓ test_purpose_log_service_success passed")

    print("\nAll 6 tests passed successfully!")

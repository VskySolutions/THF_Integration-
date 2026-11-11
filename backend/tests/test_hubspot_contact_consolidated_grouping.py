"""Unit tests for the consolidated contact grouping and mapping logic."""

import pytest

from app.features.hubspot_contact_consolidated_integration.constants import (
    CONTACT_MASTER_FIELD,
    CONTACT_PERSON_NUMBER_FIELD,
    PARENT_COMPANY_NAME_FIELD,
)
from app.features.hubspot_contact_consolidated_integration.mappers.contact_groups import (
    ContactConsolidator,
    ContactGroup,
)
from app.features.hubspot_contact_consolidated_integration.mappers.contact_mapper import (
    ContactMapper,
)
from app.features.hubspot_contact_consolidated_integration.services.sync_orchestrator import (
    ConsolidatedSyncService,
)
from app.features.hubspot_contact_consolidated_integration.services.integration_run_log_service import (
    sanitize_group_summaries,
)


def _contact(
    number: str,
    email: str = "shared@example.com",
    company: str = "10001",
    master: str | None = None,
) -> dict:
    record = {
        CONTACT_PERSON_NUMBER_FIELD: number,
        "electronicmailaddress": email,
        "contactcompanynumber": company,
    }
    if master is not None:
        record[CONTACT_MASTER_FIELD] = master
    return record


@pytest.fixture()
def consolidator() -> ContactConsolidator:
    return ContactConsolidator()


class TestGrouping:
    def test_groups_by_normalized_email(
        self, consolidator: ContactConsolidator
    ):
        grouped = consolidator.group_contacts(
            [
                _contact("1", "Shared@Example.com"),
                _contact("2", "shared@example.com"),
                _contact("3", "other@example.com"),
                _contact("4", ""),
            ]
        )
        assert set(grouped) == {"shared@example.com", "other@example.com"}
        assert len(grouped["shared@example.com"]) == 2
        assert _contact("4", "") not in grouped["shared@example.com"]

    def test_deduplicate_keeps_last_by_number(
        self, consolidator: ContactConsolidator
    ):
        deduplicated = consolidator.deduplicate(
            [_contact("1"), _contact("2"), _contact("1")]
        )
        numbers = {item[CONTACT_PERSON_NUMBER_FIELD] for item in deduplicated}
        assert numbers == {"1", "2"}
        assert len(deduplicated) == 2


class TestMasterResolution:
    def test_stamp_wins_over_changed_check(self, consolidator):
        group = consolidator.build_group(
            email="shared@example.com",
            members=[_contact("5", master="1")],
            changed_numbers={"5"},
        )
        assert group.master_number == "1"
        assert group.master_state == "known"
        assert group.action == "stamp_only"
        assert group.needs_back_query is False
        assert group.unresolved is False

    def test_stamp_master_changed_in_window_syncs(self, consolidator):
        group = consolidator.build_group(
            email="shared@example.com",
            members=[_contact("1", master="1")],
            changed_numbers={"1"},
        )
        assert group.action == "sync_master"
        assert group.master_record is not None

    def test_new_group_needs_back_query(self, consolidator):
        group = consolidator.build_group(
            email="shared@example.com",
            members=[_contact("4"), _contact("5")],
            changed_numbers={"4", "5"},
        )
        assert group.needs_back_query is True
        assert group.action == "stamp_only"

    def test_conflicting_stamps_request_back_query(self, consolidator):
        group = consolidator.build_group(
            email="shared@example.com",
            members=[_contact("1", master="1"), _contact("2", master="2")],
            changed_numbers={"1", "2"},
        )
        assert group.needs_back_query is True
        assert group.unresolved is False

    def test_elect_master_lowest_number(self, consolidator):
        elected = consolidator.elect_master(
            [_contact("3"), _contact("1"), _contact("2")]
        )
        assert elected == "1"


class TestBackQueryResolution:
    def test_no_stamps_elects_and_syncs(self, consolidator):
        group = ContactGroup(
            email="shared@example.com",
            members=[_contact("4"), _contact("5")],
        )
        resolved = consolidator.apply_back_query_results(
            group,
            records=[_contact("1"), _contact("2"), _contact("4")],
            changed_numbers={"4"},
        )
        assert resolved.master_number == "1"
        assert resolved.master_state == "elected"
        assert resolved.action == "sync_master"
        assert resolved.stamp_mode == "empty_only"
        assert resolved.re_election is False
        assert resolved.member_numbers() == {"1", "2", "4", "5"}

    def test_deleted_stamp_master_triggers_reelection_with_overwrite(
        self, consolidator
    ):
        group = ContactGroup(
            email="shared@example.com",
            members=[_contact("5", master="9")],
        )
        resolved = consolidator.apply_back_query_results(
            group,
            records=[
                _contact("2"),
                _contact("3"),
                _contact("5", master="9"),
            ],
            changed_numbers={"2"},
        )
        assert resolved.master_number == "2"
        assert resolved.master_state == "elected"
        assert resolved.re_election is True
        assert resolved.stamp_mode == "overwrite"
        assert resolved.action == "sync_master"

    def test_conflicting_union_stamps_re_elect(self, consolidator):
        group = ContactGroup(
            email="shared@example.com",
            members=[_contact("1", master="1"), _contact("2", master="2")],
        )
        resolved = consolidator.apply_back_query_results(
            group,
            records=[],
            changed_numbers={"1", "2"},
        )
        assert resolved.master_number == "1"
        assert resolved.master_state == "elected"
        assert resolved.re_election is True
        assert resolved.stamp_mode == "overwrite"
        assert resolved.needs_back_query is False

    def test_known_stamp_in_union_sync_or_stamp(self, consolidator):
        group = ContactGroup(
            email="shared@example.com",
            members=[_contact("5", master="1")],
        )
        changed = consolidator.apply_back_query_results(
            group, records=[_contact("1")], changed_numbers={"1"}
        )
        assert changed.master_state == "known"
        assert changed.action == "sync_master"
        assert changed.stamp_mode == "empty_only"

        unchanged = ContactGroup(
            email="shared@example.com",
            members=[_contact("5", master="1")],
        )
        stamp_only = consolidator.apply_back_query_results(
            unchanged, records=[_contact("1")], changed_numbers=set()
        )
        assert stamp_only.action == "stamp_only"
        assert stamp_only.unresolved is False

    def test_empty_union_is_unresolved(self, consolidator):
        group = ContactGroup(
            email="shared@example.com",
            members=[],
        )
        resolved = consolidator.apply_back_query_results(
            group, records=[], changed_numbers=set()
        )
        assert resolved.unresolved is True
        assert "no contact person records" in (resolved.conflict_reason or "")


class TestStampTargets:
    def test_empty_only_mode_targets_unstamped(self, consolidator):
        group = ContactGroup(
            email="e",
            members=[_contact("1", master="1"), _contact("2")],
        )
        group.stamp_mode = "empty_only"
        targets = [m[CONTACT_PERSON_NUMBER_FIELD] for m in group.members_to_stamp()]
        assert targets == ["2"]

    def test_overwrite_mode_targets_all(self, consolidator):
        group = ContactGroup(
            email="e",
            members=[_contact("1", master="9"), _contact("2", master="9")],
        )
        group.stamp_mode = "overwrite"
        targets = sorted(
            m[CONTACT_PERSON_NUMBER_FIELD] for m in group.members_to_stamp()
        )
        assert targets == ["1", "2"]


class TestCompanies:
    def test_parent_companies_are_unioned(self, consolidator):
        group = ContactGroup(
            email="e",
            members=[
                _contact("1", company="10001"),
                _contact("2", company="10002"),
                _contact("3", company=""),
            ],
        )
        assert group.parent_companies() == {"10001", "10002"}


class TestContactMapper:
    def test_payload_maps_fields_and_trace_id(self):
        payload = ContactMapper().build_upsert_payload(
            [
                {
                    "contactpersonnumber": "mac_con_per_1",
                    "contactcompanynumber": "cus_1",
                    "electronicmailaddress": "a@b.com",
                    "firstname": "First",
                    "lastname": "Last",
                }
            ]
        )
        assert len(payload["inputs"]) == 1
        item = payload["inputs"][0]
        assert item["idProperty"] == "maconomy_contact_person_number"
        assert item["id"] == "mac_con_per_1"
        assert item["objectWriteTraceId"] == "contact-mac_con_per_1"
        assert item["properties"]["maconomy_customer_number"] == "cus_1"
        assert item["properties"]["email"] == "a@b.com"

    def test_missing_number_is_skipped(self):
        payload = ContactMapper().build_upsert_payload([_contact("")])
        assert payload["inputs"] == []
        assert payload["skipped"][0]["reason"]

    def test_enrich_contact_sets_parent_name(self):
        enriched = ContactMapper().enrich_contact(
            _contact("1"),
            "Parent Co",
        )
        assert enriched[PARENT_COMPANY_NAME_FIELD] == "Parent Co"

    def test_enrich_contact_ignores_blank_parent(self):
        original = _contact("1")
        enriched = ContactMapper().enrich_contact(original, "  ")
        assert PARENT_COMPANY_NAME_FIELD not in enriched


class TestParentNameResolution:
    def test_prefers_customer_discovered_in_current_run(self):
        name = ConsolidatedSyncService._parent_name_for(
            _contact("1", company="10001"),
            {"10001": {"customernumber": "10001", "name1": "Current Co"}},
            {"10001": "Lookup Co"},
        )
        assert name == "Current Co"

    def test_uses_lookup_for_parent_outside_discovery_window(self):
        name = ConsolidatedSyncService._parent_name_for(
            _contact("1", company="10002"),
            {},
            {"10002": "Historical Co"},
        )
        assert name == "Historical Co"

    def test_returns_none_when_parent_name_is_unavailable(self):
        name = ConsolidatedSyncService._parent_name_for(
            _contact("1", company="10003"),
            {},
            {},
        )
        assert name is None


class TestRunLogPrivacy:
    def test_group_summary_keeps_contact_number_and_removes_email(self):
        summaries = sanitize_group_summaries(
            [
                {
                    "email": "must-not-be-stored@example.com",
                    "master": "CP-100",
                    "action": "sync_master",
                    "members": 3,
                    "upserted": True,
                    "stamped_members": 2,
                }
            ]
        )

        assert summaries == [
            {
                "master_contact_person_number": "CP-100",
                "action": "sync_master",
                "members": 3,
                "upserted": True,
                "stamped_members": 2,
            }
        ]
        assert "email" not in summaries[0]

    def test_group_summary_without_contact_number_is_not_persisted(self):
        summaries = sanitize_group_summaries(
            [{"email": "must-not-be-stored@example.com", "members": 1}]
        )
        assert summaries == []

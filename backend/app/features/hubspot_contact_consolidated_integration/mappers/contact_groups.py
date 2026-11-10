from dataclasses import dataclass, field
from typing import Any

from app.features.hubspot_contact_consolidated_integration.constants import (
    CONTACT_MASTER_FIELD,
    CONTACT_PERSON_NUMBER_FIELD,
    CONTACT_COMPANY_NUMBER_FIELD,
    EMAIL_FIELD,
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _normalized_email(record: dict[str, Any]) -> str:
    return _text(record.get(EMAIL_FIELD)).lower()


def _is_master_number(record: dict[str, Any], master: str) -> bool:
    return _text(record.get(CONTACT_PERSON_NUMBER_FIELD)) == master


@dataclass
class ContactGroup:
    """One consolidated Maconomy Contact Person group, keyed by email."""

    email: str
    members: list[dict[str, Any]] = field(default_factory=list)
    master_number: str | None = None
    master_state: str = "unknown"
    master_record: dict[str, Any] | None = None
    action: str = "stamp_only"
    needs_back_query: bool = False
    unresolved: bool = False
    conflict_reason: str | None = None
    errors: list[dict[str, Any]] = field(default_factory=list)
    associated_companies: list[str] = field(default_factory=list)
    re_election: bool = False
    stamp_mode: str = "empty_only"

    def member_numbers(self) -> set[str]:
        return {
            _text(member.get(CONTACT_PERSON_NUMBER_FIELD))
            for member in self.members
            if _text(member.get(CONTACT_PERSON_NUMBER_FIELD))
        }

    def members_to_stamp(self) -> list[dict[str, Any]]:
        """Members that receive the remark4 master stamp."""
        if self.stamp_mode == "overwrite":
            return list(self.members)
        return self.unstamped_members()

    def parent_companies(self) -> set[str]:
        return {
            _text(member.get(CONTACT_COMPANY_NUMBER_FIELD))
            for member in self.members
            if _text(member.get(CONTACT_COMPANY_NUMBER_FIELD))
        }

    def unstamped_members(self) -> list[dict[str, Any]]:
        return [
            member
            for member in self.members
            if not _text(member.get(CONTACT_MASTER_FIELD))
        ]

    def master_in_changed(self, changed_numbers: set[str]) -> bool:
        return self.master_number in changed_numbers


class ContactConsolidator:
    """Email de-duplication and MASTER resolution for contact persons."""

    def group_contacts(
        self,
        contacts: list[dict[str, Any]],
    ) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for contact in contacts:
            email = _normalized_email(contact)
            if not email:
                continue
            grouped.setdefault(email, []).append(contact)
        return grouped

    def deduplicate(self, contacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        indexed: dict[str, dict[str, Any]] = {
            _text(contact.get(CONTACT_PERSON_NUMBER_FIELD)): contact
            for contact in contacts
            if _text(contact.get(CONTACT_PERSON_NUMBER_FIELD))
        }
        return list(indexed.values())

    def stamp_candidates(
        self,
        members: list[dict[str, Any]],
    ) -> set[str]:
        """Distinct remark4 master stamps carried by the given records."""
        return {
            _text(member.get(CONTACT_MASTER_FIELD))
            for member in members
            if _text(member.get(CONTACT_MASTER_FIELD))
        }

    def resolve_master_number(
        self,
        members: list[dict[str, Any]],
    ) -> tuple[str | None, str | None]:
        """Return (master_number, conflict_reason) from existing remark4 stamps.

        A single stamp is master regardless of whether its record is part of
        this member list (unchanged masters are not discovered). Conflicting
        stamps require re-election against the live group."""
        candidates = self.stamp_candidates(members)
        if not candidates:
            return None, None
        if len(candidates) > 1:
            return None, "re-election required: group members carry different master numbers"
        return next(iter(candidates)), None

    def elect_master(
        self,
        members: list[dict[str, Any]],
    ) -> str | None:
        numbers = sorted(self.member_numbers(members))
        return numbers[0] if numbers else None

    def find_master_record(
        self,
        members: list[dict[str, Any]],
        master_number: str,
    ) -> dict[str, Any] | None:
        for member in members:
            if _is_master_number(member, master_number):
                return member
        return None

    @staticmethod
    def member_numbers(
        members: list[dict[str, Any]],
    ) -> set[str]:
        return {
            _text(record.get(CONTACT_PERSON_NUMBER_FIELD))
            for record in members
            if _text(record.get(CONTACT_PERSON_NUMBER_FIELD))
        }

    def build_group(
        self,
        email: str,
        members: list[dict[str, Any]],
        changed_numbers: set[str],
    ) -> ContactGroup:
        group = ContactGroup(email=email, members=members)
        master_number, conflict = self.resolve_master_number(members)

        if conflict is not None:
            group.conflict_reason = conflict
            group.needs_back_query = True
            return group

        if master_number is not None:
            group.master_number = master_number
            group.master_state = "known"
            group.master_record = self.find_master_record(
                members, master_number
            )
            if group.master_in_changed(changed_numbers):
                group.action = "sync_master"
            else:
                group.action = "stamp_only"
            return group

        group.needs_back_query = True
        return group

    def apply_back_query_results(
        self,
        group: ContactGroup,
        records: list[dict[str, Any]],
        changed_numbers: set[str],
    ) -> ContactGroup:
        union = self.deduplicate([*group.members, *records])
        group.members = union
        master_number, conflict = self.resolve_master_number(union)

        if master_number is None and conflict is None:
            master_number = self.elect_master(union)
            if master_number is None:
                group.unresolved = True
                group.conflict_reason = (
                    "email group has no contact person records"
                )
                group.errors.append(
                    {
                        "entity_type": "contact",
                        "stage": "master_resolution",
                        "email": group.email,
                        "message": "email group has no contact person records",
                    }
                )
                return group
            group.master_state = "elected"
        elif master_number is None and conflict is not None:
            group.re_election = True
            group.conflict_reason = conflict
            master_number = self.elect_master(union)
            if master_number is None:
                group.unresolved = True
                group.errors.append(
                    {
                        "entity_type": "contact",
                        "stage": "master_resolution",
                        "email": group.email,
                        "message": conflict,
                    }
                )
                return group
            group.master_state = "elected"
            group.stamp_mode = "overwrite"
            group.errors.append(
                {
                    "entity_type": "contact",
                    "stage": "master_resolution",
                    "email": group.email,
                    "message": (
                        f"re-election: {conflict}; elected master "
                        f"{master_number}"
                    ),
                }
            )
        else:
            if master_number in self.member_numbers(union):
                group.master_state = "known"
            else:
                group.re_election = True
                group.conflict_reason = (
                    f"stamped master {master_number} is not part of the "
                    "live email group; re-elected master"
                )
                master_number = self.elect_master(union) or master_number
                group.master_state = "elected"
                group.stamp_mode = "overwrite"
                group.errors.append(
                    {
                        "entity_type": "contact",
                        "stage": "master_resolution",
                        "email": group.email,
                        "message": group.conflict_reason or "",
                    }
                )

        group.master_number = master_number
        group.master_record = self.find_master_record(union, master_number)
        if group.master_state == "elected":
            group.action = "sync_master"
        else:
            group.action = (
                "sync_master" if group.master_in_changed(changed_numbers)
                else "stamp_only"
            )
        return group

    def needs_back_query_emails(
        self,
        groups: list[ContactGroup],
    ) -> list[str]:
        return [group.email for group in groups if group.needs_back_query]

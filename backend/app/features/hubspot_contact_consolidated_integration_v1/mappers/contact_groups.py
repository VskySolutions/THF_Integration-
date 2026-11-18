"""Resolve one HubSpot master Contact per normalized Maconomy email."""

from dataclasses import dataclass, field
from typing import Any


def _text(value: Any) -> str:
    return str(value or "").strip()


def _number(record: dict[str, Any]) -> str:
    return _text(record.get("contactpersonnumber"))


def _email(record: dict[str, Any]) -> str:
    return _text(record.get("electronicmailaddress")).lower()


@dataclass
class ContactGroup:
    email: str
    members: list[dict[str, Any]] = field(default_factory=list)
    master_number: str | None = None
    master_record: dict[str, Any] | None = None
    action: str = "unresolved"
    error: str | None = None

    def unstamped_members(self) -> list[dict[str, Any]]:
        return [
            member
            for member in self.members
            if not _text(member.get("remark4"))
        ]

    def parent_companies(self) -> set[str]:
        return {
            number
            for member in self.members
            if (number := _text(member.get("contactcompanynumber")))
        }

    def summary(self) -> dict[str, Any]:
        return {
            "email": self.email,
            "master_contact_person_number": self.master_number,
            "member_numbers": sorted(_number(item) for item in self.members),
            "action": self.action,
            "error": self.error,
        }


class ContactConsolidator:
    """Use existing remark4 routing, or elect the lowest contact number."""

    @staticmethod
    def deduplicate(contacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        indexed: dict[str, dict[str, Any]] = {}
        for contact in contacts:
            number = _number(contact)
            if number:
                indexed[number] = contact
        return list(indexed.values())

    @staticmethod
    def group_contacts(contacts: list[dict[str, Any]]) -> list[ContactGroup]:
        groups: dict[str, ContactGroup] = {}
        for contact in contacts:
            email = _email(contact)
            if email:
                groups.setdefault(email, ContactGroup(email=email)).members.append(
                    contact
                )
        return list(groups.values())

    @staticmethod
    def stamp_candidates(members: list[dict[str, Any]]) -> set[str]:
        return {
            _text(member.get("remark4"))
            for member in members
            if _text(member.get("remark4"))
        }

    @staticmethod
    def resolve(
        group: ContactGroup,
        changed_numbers: set[str],
        full_email_records: list[dict[str, Any]] | None = None,
    ) -> ContactGroup:
        if full_email_records is not None:
            group.members = ContactConsolidator.deduplicate(
                [*group.members, *full_email_records]
            )
        candidates = ContactConsolidator.stamp_candidates(group.members)
        if len(candidates) > 1:
            group.error = "conflicting remark4 master numbers; existing stamps preserved"
            return group

        numbers = {_number(member) for member in group.members if _number(member)}
        if candidates:
            master_number = next(iter(candidates))
            if full_email_records is not None and master_number not in numbers:
                group.error = "remark4 master is absent from the full email group"
                return group
            group.master_number = master_number
            group.action = (
                "sync_master" if master_number in changed_numbers else "stamp_only"
            )
        elif full_email_records is not None and numbers:
            group.master_number = min(numbers)
            group.action = "sync_master"
        else:
            group.error = "full email group is needed to elect a master"
            return group

        group.master_record = next(
            (item for item in group.members if _number(item) == group.master_number),
            None,
        )
        if group.action == "sync_master" and group.master_record is None:
            group.error = "master contact record is unavailable for HubSpot upsert"
            group.action = "unresolved"
        return group

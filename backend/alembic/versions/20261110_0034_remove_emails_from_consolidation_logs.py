"""Remove email addresses from consolidated HubSpot run logs.

Revision ID: 20261110_0034
Revises: 20261110_0033
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20261110_0034"
down_revision: str | None = "20261110_0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE hubspot_contact_consolidation_run_logs
        SET details = jsonb_set(
            details,
            '{group_summaries}',
            COALESCE(
                (
                    SELECT jsonb_agg(
                        (summary - 'email' - 'master')
                        || jsonb_build_object(
                            'master_contact_person_number',
                            summary -> 'master'
                        )
                    )
                    FROM jsonb_array_elements(
                        COALESCE(details -> 'group_summaries', '[]'::jsonb)
                    ) AS summary
                ),
                '[]'::jsonb
            ),
            false
        )
        WHERE details IS NOT NULL
          AND details ? 'group_summaries'
        """
    )


def downgrade() -> None:
    # Removed email addresses cannot and must not be reconstructed.
    pass

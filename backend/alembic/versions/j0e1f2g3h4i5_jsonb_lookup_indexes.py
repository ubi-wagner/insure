"""Add JSONB lookup indexes for matcher and lead list

Without these, every /api/validation/compare request and every leads-list
filter does a full JSONB scan across 8M+ entities and times out behind
the aggregator.

Indexes (all partial WHERE parent_id IS NULL where the matcher / lead
list only ever read masters; this keeps them ~10x smaller than full
indexes):

    ix_entities_chars_zip5_number  composite (LEFT(phy_zip,5), street_number)
                                   — matcher pass 1, the hot path
    ix_entities_chars_street_canon (street_canon)         — matcher pass 3
    ix_entities_chars_phy_city     (LOWER(phy_city))      — matcher pass 2
    ix_entities_chars_use_code     (dor_use_code)         — leads list filter
    ix_entities_chars_cream_tier   (cream_tier)           — leads list filter
    ix_entities_chars_cream_score  ((cream_score)::int)   — leads list sort
    ix_entities_pipeline_parent    (pipeline_stage, parent_id)
                                   — every "VETTED masters only" query

Uses CREATE INDEX CONCURRENTLY so it doesn't take an ACCESS EXCLUSIVE
lock and is safe to run while the aggregator is mid-flight. CONCURRENTLY
can't run inside a transaction — Alembic's autocommit_block handles that.

Revision ID: j0e1f2g3h4i5
Revises: i9d0e1f2g3h4
Create Date: 2026-05-07 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'j0e1f2g3h4i5'
down_revision: Union[str, Sequence[str], None] = 'i9d0e1f2g3h4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_INDEXES = [
    # name, body (everything after "ON entities ")
    (
        "ix_entities_chars_zip5_number",
        "(LEFT(characteristics->>'phy_zip', 5), (characteristics->>'street_number')) "
        "WHERE parent_id IS NULL",
    ),
    (
        "ix_entities_chars_street_canon",
        "((characteristics->>'street_canon')) WHERE parent_id IS NULL",
    ),
    (
        "ix_entities_chars_phy_city",
        "(LOWER(characteristics->>'phy_city')) WHERE parent_id IS NULL",
    ),
    (
        "ix_entities_chars_use_code",
        "((characteristics->>'dor_use_code'))",
    ),
    (
        "ix_entities_chars_cream_tier",
        "((characteristics->>'cream_tier'))",
    ),
    (
        "ix_entities_chars_cream_score",
        "(((characteristics->>'cream_score')::int)) "
        "WHERE characteristics->>'cream_score' IS NOT NULL",
    ),
    (
        "ix_entities_pipeline_parent",
        "(pipeline_stage, parent_id)",
    ),
]


def upgrade() -> None:
    with op.get_context().autocommit_block():
        for name, body in _INDEXES:
            op.execute(
                f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} ON entities {body}"
            )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        for name, _ in reversed(_INDEXES):
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")

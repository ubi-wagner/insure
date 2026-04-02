"""Convert lead_ledger action_type from enum to varchar

The initial migration created action_type as a Postgres ENUM with only
3 values. We now use dynamic action types for enrichments, stage changes,
etc. Convert to plain varchar.

Also fix FEMA NFHL layer number.

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-04-02 22:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'f6a7b8c9d0e1'
down_revision: Union[str, Sequence[str], None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Convert action_type from enum to varchar
    # Step 1: Add a temp varchar column
    op.add_column('lead_ledger', sa.Column('action_type_new', sa.String(), nullable=True))
    # Step 2: Copy data
    op.execute("UPDATE lead_ledger SET action_type_new = action_type::text")
    # Step 3: Drop old column
    op.drop_column('lead_ledger', 'action_type')
    # Step 4: Rename new column
    op.alter_column('lead_ledger', 'action_type_new', new_column_name='action_type', nullable=False)
    # Step 5: Drop the enum type
    op.execute("DROP TYPE IF EXISTS actiontype")


def downgrade() -> None:
    # Re-create the enum (won't contain new values, so this is lossy)
    op.execute("CREATE TYPE actiontype AS ENUM ('HUNT_FOUND', 'USER_THUMB_UP', 'USER_THUMB_DOWN')")
    op.add_column('lead_ledger', sa.Column('action_type_old', sa.Enum('HUNT_FOUND', 'USER_THUMB_UP', 'USER_THUMB_DOWN', name='actiontype'), nullable=True))
    op.execute("UPDATE lead_ledger SET action_type_old = action_type::actiontype WHERE action_type IN ('HUNT_FOUND', 'USER_THUMB_UP', 'USER_THUMB_DOWN')")
    op.drop_column('lead_ledger', 'action_type')
    op.alter_column('lead_ledger', 'action_type_old', new_column_name='action_type')

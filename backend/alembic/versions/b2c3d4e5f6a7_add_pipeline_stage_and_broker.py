"""Add pipeline_stage to entities and broker_profiles table

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-04-01 04:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add pipeline_stage column to entities
    op.add_column('entities', sa.Column('pipeline_stage', sa.String(), nullable=True))
    op.execute("UPDATE entities SET pipeline_stage = 'NEW' WHERE pipeline_stage IS NULL")
    op.alter_column('entities', 'pipeline_stage', nullable=False, server_default='NEW')

    # Create broker_profiles table
    op.create_table('broker_profiles',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('title', sa.String(), nullable=True),
        sa.Column('company', sa.String(), nullable=True),
        sa.Column('email', sa.String(), nullable=True),
        sa.Column('phone_office', sa.String(), nullable=True),
        sa.Column('phone_cell', sa.String(), nullable=True),
        sa.Column('address', sa.String(), nullable=True),
        sa.Column('signature_block', sa.Text(), nullable=True),
        sa.Column('preferences', postgresql.JSONB(), nullable=True),
        sa.Column('is_active', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_broker_profiles_id'), 'broker_profiles', ['id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_broker_profiles_id'), table_name='broker_profiles')
    op.drop_table('broker_profiles')
    op.drop_column('entities', 'pipeline_stage')

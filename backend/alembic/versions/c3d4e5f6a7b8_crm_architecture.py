"""CRM architecture: policies, engagements, entity nesting, contact fields

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-04-01 06:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Entity: add parent_id for nesting
    op.add_column('entities', sa.Column('parent_id', sa.Integer(), sa.ForeignKey('entities.id'), nullable=True))

    # Contact: add email, phone, is_primary
    op.add_column('contacts', sa.Column('email', sa.String(), nullable=True))
    op.add_column('contacts', sa.Column('phone', sa.String(), nullable=True))
    op.add_column('contacts', sa.Column('is_primary', sa.Integer(), server_default='0', nullable=False))

    # LeadLedger: add detail column, change action_type to String for flexibility
    op.add_column('lead_ledger', sa.Column('detail', sa.String(), nullable=True))
    # action_type is already stored as enum values which are strings in PG

    # Create policies table
    op.create_table('policies',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('entity_id', sa.Integer(), sa.ForeignKey('entities.id'), nullable=False),
        sa.Column('coverage_type', sa.String(), nullable=False),
        sa.Column('carrier', sa.String(), nullable=True),
        sa.Column('policy_number', sa.String(), nullable=True),
        sa.Column('premium', sa.Float(), nullable=True),
        sa.Column('tiv', sa.Float(), nullable=True),
        sa.Column('deductible', sa.String(), nullable=True),
        sa.Column('expiration', sa.String(), nullable=True),
        sa.Column('prior_premium', sa.Float(), nullable=True),
        sa.Column('premium_increase_pct', sa.Float(), nullable=True),
        sa.Column('is_active', sa.Integer(), server_default='1', nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_policies_id'), 'policies', ['id'], unique=False)
    op.create_index('ix_policies_entity_id', 'policies', ['entity_id'])

    # Create engagements table
    op.create_table('engagements',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('entity_id', sa.Integer(), sa.ForeignKey('entities.id'), nullable=False),
        sa.Column('broker_id', sa.Integer(), sa.ForeignKey('broker_profiles.id'), nullable=True),
        sa.Column('engagement_type', sa.String(), nullable=False),
        sa.Column('channel', sa.String(), server_default='EMAIL', nullable=False),
        sa.Column('status', sa.String(), server_default='DRAFT', nullable=False),
        sa.Column('subject', sa.String(), nullable=True),
        sa.Column('body', sa.Text(), nullable=True),
        sa.Column('style', sa.String(), nullable=True),
        sa.Column('sent_at', sa.DateTime(), nullable=True),
        sa.Column('responded_at', sa.DateTime(), nullable=True),
        sa.Column('follow_up_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_engagements_id'), 'engagements', ['id'], unique=False)
    op.create_index('ix_engagements_entity_id', 'engagements', ['entity_id'])


def downgrade() -> None:
    op.drop_index('ix_engagements_entity_id', table_name='engagements')
    op.drop_index(op.f('ix_engagements_id'), table_name='engagements')
    op.drop_table('engagements')
    op.drop_index('ix_policies_entity_id', table_name='policies')
    op.drop_index(op.f('ix_policies_id'), table_name='policies')
    op.drop_table('policies')
    op.drop_column('lead_ledger', 'detail')
    op.drop_column('contacts', 'is_primary')
    op.drop_column('contacts', 'phone')
    op.drop_column('contacts', 'email')
    op.drop_column('entities', 'parent_id')

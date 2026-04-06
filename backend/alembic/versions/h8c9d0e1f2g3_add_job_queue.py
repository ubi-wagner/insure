"""Add job_queue table for DB-backed enrichment pipeline

Revision ID: h8c9d0e1f2g3
Revises: g7b8c9d0e1f2
Create Date: 2026-04-06 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'h8c9d0e1f2g3'
down_revision: Union[str, Sequence[str], None] = 'g7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'job_queue',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('entity_id', sa.Integer(), sa.ForeignKey('entities.id'), nullable=False),
        sa.Column('enricher', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False, server_default='PENDING'),
        sa.Column('priority', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('depends_on', sa.String(), nullable=True),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('max_attempts', sa.Integer(), nullable=False, server_default='3'),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('locked_by', sa.String(), nullable=True),
        sa.Column('locked_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_job_queue_entity_id', 'job_queue', ['entity_id'])
    op.create_index('ix_job_queue_enricher', 'job_queue', ['enricher'])
    op.create_index('ix_job_queue_status', 'job_queue', ['status'])
    # Composite index for the consumer query: pick PENDING jobs ordered by priority
    op.create_index('ix_job_queue_status_priority', 'job_queue', ['status', 'priority'])
    # Unique constraint: one job per entity+enricher (prevent duplicates)
    op.create_index('uq_job_queue_entity_enricher', 'job_queue', ['entity_id', 'enricher'], unique=True)


def downgrade() -> None:
    op.drop_index('uq_job_queue_entity_enricher', table_name='job_queue')
    op.drop_index('ix_job_queue_status_priority', table_name='job_queue')
    op.drop_index('ix_job_queue_status', table_name='job_queue')
    op.drop_index('ix_job_queue_enricher', table_name='job_queue')
    op.drop_index('ix_job_queue_entity_id', table_name='job_queue')
    op.drop_table('job_queue')

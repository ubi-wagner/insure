"""Add service registry

Revision ID: a1b2c3d4e5f6
Revises: 87abf1ad5153
Create Date: 2026-04-01 02:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '87abf1ad5153'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('service_registry',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('last_heartbeat', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('capabilities', postgresql.JSONB(), nullable=True),
        sa.Column('version', sa.String(), nullable=True),
        sa.Column('detail', sa.String(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )
    op.create_index(op.f('ix_service_registry_id'), 'service_registry', ['id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_service_registry_id'), table_name='service_registry')
    op.drop_table('service_registry')

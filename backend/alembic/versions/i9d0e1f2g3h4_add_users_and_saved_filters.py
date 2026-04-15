"""Add users and user_saved_filters tables

Establishes the per-user data pattern: every future user-specific feature
(watchlist, notes, preferences, activity log, etc.) will follow the same
shape with user_uuid as the foreign key and optional is_shared flag.

Revision ID: i9d0e1f2g3h4
Revises: h8c9d0e1f2g3
Create Date: 2026-04-10 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'i9d0e1f2g3h4'
down_revision: Union[str, Sequence[str], None] = 'h8c9d0e1f2g3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('uuid', sa.String(length=36), nullable=False, unique=True),
        sa.Column('username', sa.String(length=64), nullable=False, unique=True),
        sa.Column('display_name', sa.String(length=128), nullable=False),
        sa.Column('password_hash', sa.String(length=256), nullable=True),
        sa.Column('role', sa.String(length=16), nullable=False, server_default='user'),
        sa.Column('email', sa.String(length=128), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('last_login', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_users_username', 'users', ['username'])
    op.create_index('ix_users_uuid', 'users', ['uuid'])

    op.create_table(
        'user_saved_filters',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_uuid', sa.String(length=36), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('filter_json', sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column('is_shared', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['user_uuid'], ['users.uuid'], ondelete='CASCADE'),
    )
    op.create_index('ix_user_saved_filters_user_uuid', 'user_saved_filters', ['user_uuid'])
    op.create_index('uq_user_saved_filters_user_name', 'user_saved_filters',
                    ['user_uuid', 'name'], unique=True)


def downgrade() -> None:
    op.drop_index('uq_user_saved_filters_user_name', table_name='user_saved_filters')
    op.drop_index('ix_user_saved_filters_user_uuid', table_name='user_saved_filters')
    op.drop_table('user_saved_filters')
    op.drop_index('ix_users_uuid', table_name='users')
    op.drop_index('ix_users_username', table_name='users')
    op.drop_table('users')

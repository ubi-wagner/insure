"""Add enrichment_sources to entities, source to contacts and lead_ledger

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-04-01 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Entity: add enrichment_sources JSONB to track where each piece of intel came from
    op.add_column('entities', sa.Column('enrichment_sources', postgresql.JSONB(), nullable=True))

    # Contact: add source field (e.g., "sunbiz", "property_appraiser", "user_upload", "manual")
    op.add_column('contacts', sa.Column('source', sa.String(), nullable=True))
    op.add_column('contacts', sa.Column('source_url', sa.String(), nullable=True))

    # LeadLedger: add source field for tracking enrichment provenance
    op.add_column('lead_ledger', sa.Column('source', sa.String(), nullable=True))
    op.add_column('lead_ledger', sa.Column('source_url', sa.String(), nullable=True))

    # EntityAsset: add source and uploaded_by fields
    op.add_column('entity_assets', sa.Column('source', sa.String(), nullable=True))
    op.add_column('entity_assets', sa.Column('filename', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('entity_assets', 'filename')
    op.drop_column('entity_assets', 'source')
    op.drop_column('lead_ledger', 'source_url')
    op.drop_column('lead_ledger', 'source')
    op.drop_column('contacts', 'source_url')
    op.drop_column('contacts', 'source')
    op.drop_column('entities', 'enrichment_sources')

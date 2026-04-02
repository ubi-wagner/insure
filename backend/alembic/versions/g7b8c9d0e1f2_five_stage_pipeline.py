"""Five-stage pipeline refactor

Simplify pipeline to 5 stages:
  TARGET: Raw NAL parcel, waiting for Overpass association
  LEAD: Associated, continuously enriching, scored cold/warm/hot
  OPPORTUNITY: User-promoted for CRM engagement
  CUSTOMER: Converted deal
  ARCHIVED: Dismissed

Revision ID: g7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-04-03 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'g7b8c9d0e1f2'
down_revision: Union[str, Sequence[str], None] = 'f6a7b8c9d0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add new Entity columns
    op.add_column('entities', sa.Column('heat_score', sa.String(), nullable=True))
    op.add_column('entities', sa.Column('folder_path', sa.String(), nullable=True))
    op.add_column('entities', sa.Column('osm_building_id', sa.Integer(), sa.ForeignKey('osm_buildings.id'), nullable=True))
    op.add_column('entities', sa.Column('enrichment_status', sa.String(), server_default='idle', nullable=False))

    # Migrate pipeline stages to 5-stage model
    op.execute("UPDATE entities SET pipeline_stage = 'TARGET' WHERE pipeline_stage IN ('NEW')")
    op.execute("UPDATE entities SET pipeline_stage = 'LEAD' WHERE pipeline_stage IN ('ENRICHED', 'INVESTIGATING', 'RESEARCHED', 'TARGETED', 'CANDIDATE')")
    op.execute("UPDATE entities SET pipeline_stage = 'ARCHIVED' WHERE pipeline_stage IN ('CHURNED', 'REJECTED')")
    # OPPORTUNITY, CUSTOMER, ARCHIVED stay as-is

    # Index for Overpass association lookups
    op.create_index('ix_entities_osm_building_id', 'entities', ['osm_building_id'])
    op.create_index('ix_entities_pipeline_stage', 'entities', ['pipeline_stage'])
    op.create_index('ix_entities_heat_score', 'entities', ['heat_score'])
    op.create_index('ix_entities_county', 'entities', ['county'])


def downgrade() -> None:
    op.drop_index('ix_entities_county', table_name='entities')
    op.drop_index('ix_entities_heat_score', table_name='entities')
    op.drop_index('ix_entities_pipeline_stage', table_name='entities')
    op.drop_index('ix_entities_osm_building_id', table_name='entities')
    op.drop_column('entities', 'enrichment_status')
    op.drop_column('entities', 'osm_building_id')
    op.drop_column('entities', 'folder_path')
    op.drop_column('entities', 'heat_score')
    # Note: stage data migration is lossy — cannot fully reverse
    op.execute("UPDATE entities SET pipeline_stage = 'NEW' WHERE pipeline_stage = 'TARGET'")
    op.execute("UPDATE entities SET pipeline_stage = 'TARGETED' WHERE pipeline_stage = 'LEAD'")

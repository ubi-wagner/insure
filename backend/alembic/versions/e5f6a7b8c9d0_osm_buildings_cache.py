"""Add osm_buildings cache table

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-04-02 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, Sequence[str], None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('osm_buildings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('osm_id', sa.BigInteger(), nullable=False),
        sa.Column('osm_type', sa.String(), nullable=False),  # way, relation
        sa.Column('lat', sa.Float(), nullable=False),
        sa.Column('lon', sa.Float(), nullable=False),
        sa.Column('name', sa.String(), nullable=True),
        sa.Column('address', sa.String(), nullable=True),
        sa.Column('county', sa.String(), nullable=True),
        sa.Column('building_type', sa.String(), nullable=True),  # apartments, condominium, etc.
        sa.Column('stories', sa.Integer(), nullable=True),
        sa.Column('construction_class', sa.String(), nullable=True),
        sa.Column('iso_class', sa.Integer(), nullable=True),
        sa.Column('tiv_estimate', sa.Float(), nullable=True),
        sa.Column('units_estimate', sa.Integer(), nullable=True),
        sa.Column('footprint_sqft', sa.Float(), nullable=True),
        sa.Column('tags', postgresql.JSONB(), nullable=True),  # All OSM tags
        sa.Column('raw_element', postgresql.JSONB(), nullable=True),  # Full Overpass element
        sa.Column('geocoded', sa.Integer(), server_default='0', nullable=False),
        sa.Column('promoted_entity_id', sa.Integer(), sa.ForeignKey('entities.id'), nullable=True),
        sa.Column('harvested_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_osm_buildings_osm_id', 'osm_buildings', ['osm_id'], unique=True)
    op.create_index('ix_osm_buildings_lat_lon', 'osm_buildings', ['lat', 'lon'])
    op.create_index('ix_osm_buildings_county', 'osm_buildings', ['county'])
    op.create_index('ix_osm_buildings_stories', 'osm_buildings', ['stories'])
    op.create_index('ix_osm_buildings_building_type', 'osm_buildings', ['building_type'])

    # Track which areas have been harvested so we don't re-query
    op.create_table('osm_harvest_areas',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=True),
        sa.Column('bbox_south', sa.Float(), nullable=False),
        sa.Column('bbox_north', sa.Float(), nullable=False),
        sa.Column('bbox_west', sa.Float(), nullable=False),
        sa.Column('bbox_east', sa.Float(), nullable=False),
        sa.Column('building_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('query_params', postgresql.JSONB(), nullable=True),
        sa.Column('harvested_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('osm_harvest_areas')
    op.drop_index('ix_osm_buildings_building_type', table_name='osm_buildings')
    op.drop_index('ix_osm_buildings_stories', table_name='osm_buildings')
    op.drop_index('ix_osm_buildings_county', table_name='osm_buildings')
    op.drop_index('ix_osm_buildings_lat_lon', table_name='osm_buildings')
    op.drop_index('ix_osm_buildings_osm_id', table_name='osm_buildings')
    op.drop_table('osm_buildings')

"""Add JSONB lookup indexes for matcher and lead list (lazy)

Without these, every /api/validation/compare request and every leads-list
filter does a full JSONB scan across 8M+ entities and times out behind
the aggregator.

This migration is INTENTIONALLY a no-op. The actual CREATE INDEX
CONCURRENTLY work happens in a daemon thread fired from the FastAPI
lifespan in main.py (see ``_kick_off_index_build``). Reason: building
seven partial expression indexes against an 8M-row table takes 20-40
minutes total; running that synchronously inside ``alembic upgrade
head`` blocks the Railway healthcheck (5-minute window) and the
deploy fails before the app ever serves a request.

The index definitions live in ``backend/routes/admin._JSONB_INDEXES``
which both:
  - the lifespan auto-build hook reads on startup, and
  - the ``/api/admin/indexes/build`` admin endpoint reads when the
    user clicks "Build Indexes" in the Ops dashboard.

Both paths use ``CREATE INDEX CONCURRENTLY IF NOT EXISTS`` and run
each statement on its own autocommit connection, so they're safe to
run while the aggregator (or anything else) is mid-flight.

Revision ID: j0e1f2g3h4i5
Revises: i9d0e1f2g3h4
Create Date: 2026-05-07 00:00:00.000000
"""
from typing import Sequence, Union


revision: str = 'j0e1f2g3h4i5'
down_revision: Union[str, Sequence[str], None] = 'i9d0e1f2g3h4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """No-op. Index creation runs lazily from the FastAPI lifespan."""
    pass


def downgrade() -> None:
    """No-op. Indexes can be dropped manually if needed."""
    pass

"""BOM V1 baseline schema.

Revision ID: 0001_v1
Revises: None
"""
from alembic import op

from backend.app.database import Base
from backend.app import models  # noqa: F401


revision = "0001_v1"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())
    op.execute("""
        CREATE TRIGGER IF NOT EXISTS audit_events_no_update
        BEFORE UPDATE ON audit_events
        BEGIN SELECT RAISE(ABORT, 'audit events are immutable'); END
    """)
    op.execute("""
        CREATE TRIGGER IF NOT EXISTS audit_events_no_delete
        BEFORE DELETE ON audit_events
        BEGIN SELECT RAISE(ABORT, 'audit events are immutable'); END
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_events_no_update")
    op.execute("DROP TRIGGER IF EXISTS audit_events_no_delete")
    Base.metadata.drop_all(bind=op.get_bind())

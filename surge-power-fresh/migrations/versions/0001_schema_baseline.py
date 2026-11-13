"""Create missing tables from the current ORM metadata.

This baseline is idempotent so it can initialize an empty database or add
workspace tables to an existing pre-migration database without replacing data.
Future column changes must be generated as explicit Alembic revisions.
"""
from alembic import op
from backend import db

revision = "0001_schema_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    db.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade():
    # The baseline is intentionally non-destructive; customer and invoice data
    # must never be removed by rolling this bootstrap revision back.
    pass

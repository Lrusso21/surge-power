"""Add operational preset and reversible batch records."""
from alembic import op
from backend import db
revision = '0002_operations'
down_revision = '0001_schema_baseline'
branch_labels = None
depends_on = None

def upgrade():
    for name in ['service_preset', 'bulk_change']:
        db.metadata.tables[name].create(bind=op.get_bind(), checkfirst=True)

def downgrade():
    pass  # Retain operational history; rollback application code separately.

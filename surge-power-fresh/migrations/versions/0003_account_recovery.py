"""Add hashed, single-use account recovery records."""
from alembic import op
from backend import db
revision = '0003_account_recovery'
down_revision = '0002_operations'
branch_labels = None
depends_on = None

def upgrade():
    db.metadata.tables['password_recovery'].create(bind=op.get_bind(), checkfirst=True)

def downgrade():
    pass

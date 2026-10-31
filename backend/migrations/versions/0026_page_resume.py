"""Bounded API-page reuse and complete public HTTP capture provenance."""
from alembic import op

from migrations.integrity import read_snapshot

revision = "0026_page_resume"
down_revision = "0025_knowledge_retention"
branch_labels = None
depends_on = None

def apply(direction):
    with op.get_bind().connection.driver_connection.cursor() as cursor:
        cursor.execute(read_snapshot(f"0026_{direction}.sql"), prepare=False)

def upgrade():
    apply("up")

def downgrade():
    apply("down")

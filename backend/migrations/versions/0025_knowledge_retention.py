"""Irreversible recycled-knowledge payload erasure and retention guard."""

from alembic import op
from migrations.integrity import read_snapshot

revision = "0025_knowledge_retention"
down_revision = "0024_knowledge_attribution"
branch_labels = None
depends_on = None


def apply(direction):
    with op.get_bind().connection.driver_connection.cursor() as cursor:
        cursor.execute(read_snapshot(f"0025_{direction}.sql"), prepare=False)


def upgrade():
    apply("up")


def downgrade():
    apply("down")

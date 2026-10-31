"""Nullable knowledge source and explanation, sealed with each revision."""

from alembic import op

from migrations.integrity import read_snapshot

revision = "0024_knowledge_attribution"
down_revision = "0023_knowledge_recycle"
branch_labels = None
depends_on = None


def apply(direction):
    with op.get_bind().connection.driver_connection.cursor() as cursor:
        cursor.execute(read_snapshot(f"0024_{direction}.sql"), prepare=False)


def upgrade():
    apply("up")


def downgrade():
    apply("down")

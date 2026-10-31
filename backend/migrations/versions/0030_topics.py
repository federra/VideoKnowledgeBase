"""Immutable topic/spark revisions and exact-version production handoffs."""

from alembic import op

from migrations.integrity import read_snapshot

revision = "0030_topics"
down_revision = "0029_model_config"
branch_labels = None
depends_on = None


def apply(direction):
    with op.get_bind().connection.driver_connection.cursor() as cursor:
        cursor.execute(read_snapshot(f"0030_{direction}.sql"), prepare=False)


def upgrade():
    apply("up")


def downgrade():
    apply("down")

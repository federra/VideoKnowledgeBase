"""Immutable research evidence package from sealed intelligence and feedback."""

from alembic import op

from migrations.integrity import read_snapshot

revision = "0012_handoffs"
down_revision = "0011_insight"
branch_labels = None
depends_on = None


def apply(direction):
    with op.get_bind().connection.driver_connection.cursor() as cursor:
        cursor.execute(read_snapshot(f"0012_{direction}.sql"), prepare=False)


def upgrade():
    apply("up")


def downgrade():
    apply("down")

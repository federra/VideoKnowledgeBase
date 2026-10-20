"""Collection reservation reads attempts under existing tenant mutex; no privilege changes."""

from alembic import op

from migrations.integrity import read_snapshot

revision = "0009_collection_lock"
down_revision = "0008_console"
branch_labels = None
depends_on = None


def apply(direction):
    with op.get_bind().connection.driver_connection.cursor() as cursor:
        cursor.execute(read_snapshot(f"0009_{direction}.sql"), prepare=False)


def upgrade():
    apply("up")


def downgrade():
    apply("down")

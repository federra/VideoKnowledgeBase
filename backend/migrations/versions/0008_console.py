"""S06.2 source archival; does not remove historical sources or paid evidence."""

from alembic import op

from migrations.integrity import read_snapshot

revision = "0008_console"
down_revision = "0007_tasks"
branch_labels = None
depends_on = None


def apply(direction):
    with op.get_bind().connection.driver_connection.cursor() as cursor:
        cursor.execute(read_snapshot(f"0008_{direction}.sql"), prepare=False)


def upgrade():
    apply("up")


def downgrade():
    apply("down")

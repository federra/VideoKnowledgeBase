"""Link research submissions to immutable intelligence evidence packages."""

from alembic import op

from migrations.integrity import read_snapshot

revision = "0013_research"
down_revision = "0012_handoffs"
branch_labels = None
depends_on = None


def apply(direction):
    with op.get_bind().connection.driver_connection.cursor() as cursor:
        cursor.execute(read_snapshot(f"0013_{direction}.sql"), prepare=False)


def upgrade():
    apply("up")


def downgrade():
    apply("down")

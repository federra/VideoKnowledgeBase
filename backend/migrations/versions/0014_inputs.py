"""Freeze successful parsed text sources in immutable input sets."""

from alembic import op

from migrations.integrity import read_snapshot

revision = "0014_inputs"
down_revision = "0013_research"
branch_labels = None
depends_on = None


def apply(direction):
    with op.get_bind().connection.driver_connection.cursor() as cursor:
        cursor.execute(read_snapshot(f"0014_{direction}.sql"), prepare=False)


def upgrade():
    apply("up")


def downgrade():
    apply("down")

"""Immutable one-feedback sample insight, with deferred task/parent verification."""

from alembic import op

from migrations.integrity import read_snapshot

revision = "0011_insight"
down_revision = "0010_comments"
branch_labels = None
depends_on = None


def apply(direction):
    with op.get_bind().connection.driver_connection.cursor() as cursor:
        cursor.execute(read_snapshot(f"0011_{direction}.sql"), prepare=False)


def upgrade():
    apply("up")


def downgrade():
    apply("down")

"""Preserve the comment author name captured with immutable original evidence."""

from alembic import op

from migrations.integrity import read_snapshot

revision = "0010_comments"
down_revision = "0009_collection_lock"
branch_labels = None
depends_on = None


def apply(direction):
    with op.get_bind().connection.driver_connection.cursor() as cursor:
        cursor.execute(read_snapshot(f"0010_{direction}.sql"), prepare=False)


def upgrade():
    apply("up")


def downgrade():
    apply("down")

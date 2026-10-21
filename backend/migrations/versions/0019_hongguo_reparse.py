"""Allow exact zero-I/O reparse provenance; completed external results remain immutable."""

from alembic import op

from migrations.integrity import read_snapshot

revision = "0019_hongguo_reparse"
down_revision = "0018_hongguo"
branch_labels = None
depends_on = None


def apply(direction):
    with op.get_bind().connection.driver_connection.cursor() as cursor:
        cursor.execute(read_snapshot(f"0019_{direction}.sql"), prepare=False)


def upgrade():
    apply("up")


def downgrade():
    apply("down")

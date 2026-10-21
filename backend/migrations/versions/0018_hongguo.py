"""Add the independent Hongguo platform; no tables or existing evidence changed."""

from alembic import op

from migrations.integrity import read_snapshot

revision = "0018_hongguo"
down_revision = "0017_browser_novels"
branch_labels = None
depends_on = None


def apply(direction):
    with op.get_bind().connection.driver_connection.cursor() as cursor:
        cursor.execute(read_snapshot(f"0018_{direction}.sql"), prepare=False)


def upgrade():
    apply("up")


def downgrade():
    apply("down")

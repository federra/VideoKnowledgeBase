"""Explicit owner-only legacy knowledge imports, without fabricated review records."""

from alembic import op

from migrations.integrity import read_snapshot

revision = "0021_legacy_failures"
down_revision = "0020_legacy_knowledge"
branch_labels = None
depends_on = None


def apply(direction):
    with op.get_bind().connection.driver_connection.cursor() as cursor:
        cursor.execute(read_snapshot(f"0021_{direction}.sql"), prepare=False)


def upgrade():
    apply("up")


def downgrade():
    apply("down")

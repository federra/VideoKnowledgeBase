"""Explicit owner-only legacy knowledge imports, without fabricated review records."""

from alembic import op

from migrations.integrity import read_snapshot

revision = "0022_legacy_payoffs"
down_revision = "0021_legacy_failures"
branch_labels = None
depends_on = None


def apply(direction):
    with op.get_bind().connection.driver_connection.cursor() as cursor:
        cursor.execute(read_snapshot(f"0022_{direction}.sql"), prepare=False)


def upgrade():
    apply("up")


def downgrade():
    apply("down")

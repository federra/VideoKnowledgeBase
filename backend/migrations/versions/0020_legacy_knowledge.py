"""Explicit owner-only legacy knowledge imports, without fabricated review records."""

from alembic import op

from migrations.integrity import read_snapshot

revision = "0020_legacy_knowledge"
down_revision = "0019_hongguo_reparse"
branch_labels = None
depends_on = None


def apply(direction):
    with op.get_bind().connection.driver_connection.cursor() as cursor:
        cursor.execute(read_snapshot(f"0020_{direction}.sql"), prepare=False)


def upgrade():
    apply("up")


def downgrade():
    apply("down")

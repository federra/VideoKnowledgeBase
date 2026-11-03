"""Reuse full global validation only for an unchanged protected transaction generation."""

from alembic import op

from migrations.integrity import read_snapshot

revision = "0037_write_validation"
down_revision = "0036_user_accounts"
branch_labels = None
depends_on = None


def apply(direction):
    with op.get_bind().connection.driver_connection.cursor() as cursor:
        cursor.execute(read_snapshot(f"0037_{direction}.sql"), prepare=False)


def upgrade():
    apply("up")


def downgrade():
    apply("down")

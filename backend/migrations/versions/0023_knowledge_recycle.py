"""Reversible knowledge recycling, without permanent cleanup."""

from alembic import op

from migrations.integrity import read_snapshot

revision = "0023_knowledge_recycle"
down_revision = "0022_legacy_payoffs"
branch_labels = None
depends_on = None


def apply(direction):
    with op.get_bind().connection.driver_connection.cursor() as cursor:
        cursor.execute(read_snapshot(f"0023_{direction}.sql"), prepare=False)


def upgrade():
    apply("up")


def downgrade():
    apply("down")

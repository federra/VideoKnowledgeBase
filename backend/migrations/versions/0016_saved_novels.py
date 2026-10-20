"""Permit bounded manual Qidian HTML provenance without inventing API calls."""

from alembic import op

from migrations.integrity import read_snapshot

revision = "0016_saved_novels"
down_revision = "0015_novels"
branch_labels = None
depends_on = None


def apply(direction):
    with op.get_bind().connection.driver_connection.cursor() as cursor:
        cursor.execute(read_snapshot(f"0016_{direction}.sql"), prepare=False)


def upgrade():
    apply("up")


def downgrade():
    apply("down")

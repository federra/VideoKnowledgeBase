"""Add official Qimao platform without changing existing data or privileges."""

from alembic import op

from migrations.integrity import read_snapshot

revision = "0028_qimao"
down_revision = "0027_provenance_planner"
branch_labels = None
depends_on = None


def apply(direction):
    with op.get_bind().connection.driver_connection.cursor() as cursor:
        cursor.execute(read_snapshot(f"0028_{direction}.sql"), prepare=False)


def upgrade():
    apply("up")


def downgrade():
    apply("down")

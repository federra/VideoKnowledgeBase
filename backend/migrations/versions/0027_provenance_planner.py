"""Bound provenance helper planning to its existing join order."""

from alembic import op

from migrations.integrity import read_snapshot

revision = "0027_provenance_planner"
down_revision = "0026_page_resume"
branch_labels = None
depends_on = None


def apply(direction):
    with op.get_bind().connection.driver_connection.cursor() as cursor:
        cursor.execute(read_snapshot(f"0027_{direction}.sql"), prepare=False)


def upgrade():
    apply("up")


def downgrade():
    apply("down")

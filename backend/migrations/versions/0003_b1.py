"""S04 frozen B1 migration 3; SQL is immutable after release."""

from alembic import op

from migrations.integrity import read_snapshot

revision = "0003_b1"
down_revision = "0002_b1"
branch_labels = None
depends_on = None


def apply(direction):
    sql = read_snapshot(f"0003_{direction}.sql")
    with op.get_bind().connection.driver_connection.cursor() as cursor:
        cursor.execute(sql, prepare=False)


def upgrade():
    apply("up")


def downgrade():
    apply("down")

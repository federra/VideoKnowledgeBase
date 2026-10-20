"""S04 frozen B1 migration 1; SQL is immutable after release."""

from alembic import op

from migrations.integrity import read_snapshot

revision = "0001_b1"
down_revision = None
branch_labels = None
depends_on = None


def apply(direction):
    sql = read_snapshot(f"0001_{direction}.sql")
    with op.get_bind().connection.driver_connection.cursor() as cursor:
        cursor.execute(sql, prepare=False)


def upgrade():
    apply("up")


def downgrade():
    apply("down")

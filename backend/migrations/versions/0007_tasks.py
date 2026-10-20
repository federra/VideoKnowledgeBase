"""S05.4 bounded task runtime migration; SQL is immutable after release."""

from alembic import op

from migrations.integrity import read_snapshot

revision = "0007_tasks"
down_revision = "0006_storage"
branch_labels = None
depends_on = None


def apply(direction):
    sql = read_snapshot(f"0007_{direction}.sql")
    with op.get_bind().connection.driver_connection.cursor() as cursor:
        cursor.execute(sql, prepare=False)


def upgrade():
    apply("up")


def downgrade():
    apply("down")

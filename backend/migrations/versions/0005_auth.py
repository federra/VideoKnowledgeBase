"""S05.2 frozen session and receipt migration; SQL is immutable after release."""

from alembic import op

from migrations.integrity import read_snapshot

revision = "0005_auth"
down_revision = "0004_b1"
branch_labels = None
depends_on = None


def apply(direction):
    sql = read_snapshot(f"0005_{direction}.sql")
    with op.get_bind().connection.driver_connection.cursor() as cursor:
        cursor.execute(sql, prepare=False)


def upgrade():
    apply("up")


def downgrade():
    apply("down")

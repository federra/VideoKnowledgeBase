"""S05.3 frozen file intake scope migration; SQL is immutable after release."""

from alembic import op

from migrations.integrity import read_snapshot

revision = "0006_storage"
down_revision = "0005_auth"
branch_labels = None
depends_on = None


def apply(direction):
    sql = read_snapshot(f"0006_{direction}.sql")
    with op.get_bind().connection.driver_connection.cursor() as cursor:
        cursor.execute(sql, prepare=False)


def upgrade():
    apply("up")


def downgrade():
    apply("down")

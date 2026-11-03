"""Keep deleted sparks as provenance and persist capsule colors."""

from alembic import op

from migrations.integrity import read_snapshot

revision = "0038_spark_capsules"
down_revision = "0037_write_validation"
branch_labels = None
depends_on = None


def apply(direction):
    with op.get_bind().connection.driver_connection.cursor() as cursor:
        cursor.execute(read_snapshot(f"0038_{direction}.sql"), prepare=False)


def upgrade():
    apply("up")


def downgrade():
    apply("down")

"""Versioned model console sources and business-stage bindings."""

from alembic import op

from migrations.integrity import read_snapshot

revision = "0029_model_config"
down_revision = "0028_qimao"
branch_labels = None
depends_on = None


def apply(direction):
    with op.get_bind().connection.driver_connection.cursor() as cursor:
        cursor.execute(read_snapshot(f"0029_{direction}.sql"), prepare=False)


def upgrade():
    apply("up")


def downgrade():
    apply("down")

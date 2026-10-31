"""Bind AI genre explanation addenda to exact published revisions and executions."""

from alembic import op

from migrations.integrity import read_snapshot

revision = "0033_genre_explanations"
down_revision = "0032_market_inference"
branch_labels = None
depends_on = None


def apply(direction):
    with op.get_bind().connection.driver_connection.cursor() as cursor:
        cursor.execute(read_snapshot(f"0033_{direction}.sql"), prepare=False)


def upgrade():
    apply("up")


def downgrade():
    apply("down")

"""Typed exact-sample audience feedback v2, preserving v1."""

from alembic import op

from migrations.integrity import read_snapshot

revision = "0034_audience_feedback_v2"
down_revision = "0033_genre_explanations"
branch_labels = None
depends_on = None


def apply(direction):
    with op.get_bind().connection.driver_connection.cursor() as cursor:
        cursor.execute(read_snapshot(f"0034_{direction}.sql"), prepare=False)


def upgrade():
    apply("up")


def downgrade():
    apply("down")

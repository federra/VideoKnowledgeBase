"""Immutable assessments bound to exact topic revision, task and execution."""
from alembic import op
from migrations.integrity import read_snapshot

revision = '0031_topic_assessments'
down_revision = '0030_topics'
branch_labels = None
depends_on = None


def apply(direction):
    with op.get_bind().connection.driver_connection.cursor() as cursor:
        cursor.execute(read_snapshot(f'0031_{direction}.sql'), prepare=False)


def upgrade():
    apply('up')


def downgrade():
    apply('down')

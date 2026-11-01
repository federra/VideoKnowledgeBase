"""One immutable local account installation; no business data ownership rewrite."""
from alembic import op

from migrations.integrity import read_snapshot

revision = '0036_user_accounts'
down_revision = '0035_feedback_batch'
branch_labels = None
depends_on = None


def apply(direction):
    with op.get_bind().connection.driver_connection.cursor() as cursor:
        cursor.execute(read_snapshot(f'0036_{direction}.sql'), prepare=False)


def upgrade():
    apply('up')


def downgrade():
    apply('down')

"""Initial project schema."""
from alembic import op
from app.db.models import Base

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    Base.metadata.create_all(bind=op.get_bind())


def downgrade():
    raise RuntimeError('Refusing automatic deletion of application data; restore a backup instead.')

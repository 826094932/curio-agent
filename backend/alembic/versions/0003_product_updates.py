"""Durable administrator review queue for web product updates."""
from alembic import op
import sqlalchemy as sa
from app.db.models import ProductUpdate

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade():
    # 0001 在首次建库时使用当前 metadata，兼容首次安装和已有数据库。
    bind = op.get_bind()
    if not sa.inspect(bind).has_table('product_updates'):
        ProductUpdate.__table__.create(bind)


def downgrade():
    raise RuntimeError('Refusing to delete saved product update history automatically.')

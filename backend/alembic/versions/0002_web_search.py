"""Add opt-in web evidence without changing product facts."""
from alembic import op
import sqlalchemy as sa

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade():
    # 0001 使用当前 metadata.create_all；首次建库可能已经创建这些对象。
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'web_search' not in {column['name'] for column in inspector.get_columns('chat_messages')}:
        op.add_column('chat_messages', sa.Column('web_search', sa.Boolean(), nullable=False, server_default=sa.false()))
    if not inspector.has_table('web_evidence'):
        op.create_table('web_evidence',
            sa.Column('id', sa.String(64), primary_key=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('user_id', sa.String(64), sa.ForeignKey('users.id'), nullable=False),
            sa.Column('url', sa.String(1024), nullable=False),
            sa.Column('title', sa.String(500), nullable=False),
            sa.Column('content', sa.Text(), nullable=False),
            sa.Column('content_hash', sa.String(64), nullable=False),
            sa.Column('category', sa.String(32), nullable=True),
            sa.Column('source_kind', sa.String(32), nullable=False),
            sa.Column('relevance_score', sa.Float(), nullable=False),
            sa.Column('published_at', sa.String(100), nullable=True),
            sa.Column('fetched_at', sa.DateTime(), nullable=False))
        op.create_index('ix_web_evidence_user_id', 'web_evidence', ['user_id'])
        op.create_index('ix_web_evidence_fetched_at', 'web_evidence', ['fetched_at'])
    if not inspector.has_table('web_search_cache'):
        op.create_table('web_search_cache',
            sa.Column('id', sa.String(64), primary_key=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('user_id', sa.String(64), sa.ForeignKey('users.id'), nullable=False),
            sa.Column('query_hash', sa.String(64), nullable=False),
            sa.Column('evidence_ids', sa.JSON(), nullable=False),
            sa.Column('expires_at', sa.DateTime(), nullable=False),
            sa.UniqueConstraint('user_id', 'query_hash', name='uq_web_search_owner_query'))


def downgrade():
    raise RuntimeError('Refusing to delete saved web evidence automatically.')

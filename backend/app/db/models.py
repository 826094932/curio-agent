from datetime import datetime, timezone
from ulid import ULID
from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, Index, false
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def uid():
    return str(ULID())


def now():
    # MySQL DATETIME 不带时区，统一存储 UTC。
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Entity:
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class User(Entity, Base):
    __tablename__ = 'users'
    email: Mapped[str] = mapped_column(String(255), unique=True)
    nickname: Mapped[str] = mapped_column(String(64))
    password_hash: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default='active')


class AuthSession(Entity, Base):
    __tablename__ = 'auth_sessions'
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    refresh_token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Preference(Entity, Base):
    __tablename__ = 'user_preferences'
    __table_args__ = (UniqueConstraint('user_id', 'category'),)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    category: Mapped[str] = mapped_column(String(32), default='general')
    preferences: Mapped[dict] = mapped_column(JSON, default=dict)
    consent_version: Mapped[str] = mapped_column(String(32), default='explicit-v1')


class Category(Base):
    __tablename__ = 'categories'
    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    spec_schema: Mapped[dict] = mapped_column(JSON, default=dict)
    scoring_config: Mapped[dict] = mapped_column(JSON, default=dict)


class Product(Entity, Base):
    __tablename__ = 'products'
    __table_args__ = (UniqueConstraint('category_code', 'brand', 'model'),)
    category_code: Mapped[str] = mapped_column(String(32), index=True)
    brand: Mapped[str] = mapped_column(String(64), index=True)
    model: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(String(255))
    summary: Mapped[str] = mapped_column(Text)
    specs: Mapped[dict] = mapped_column(JSON)
    source: Mapped[str] = mapped_column(String(64))
    source_url: Mapped[str] = mapped_column(String(1024))
    source_updated_at: Mapped[datetime] = mapped_column(DateTime)
    content_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default='active')
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)


class Price(Entity, Base):
    __tablename__ = 'product_prices'
    __table_args__ = (UniqueConstraint('product_id', 'channel', 'captured_at'),)
    product_id: Mapped[str] = mapped_column(ForeignKey('products.id'), index=True)
    channel: Mapped[str] = mapped_column(String(64))
    final_price: Mapped[float] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default='CNY')
    in_stock: Mapped[bool] = mapped_column(Boolean, default=True)
    product_url: Mapped[str] = mapped_column(String(1024))
    captured_at: Mapped[datetime] = mapped_column(DateTime, index=True)


class Review(Entity, Base):
    __tablename__ = 'product_reviews'
    product_id: Mapped[str] = mapped_column(ForeignKey('products.id'), index=True)
    content: Mapped[str] = mapped_column(Text)
    aspect: Mapped[str] = mapped_column(String(32))
    sentiment: Mapped[str] = mapped_column(String(16))
    source: Mapped[str] = mapped_column(String(64))
    source_url: Mapped[str] = mapped_column(String(1024))
    reviewed_at: Mapped[datetime] = mapped_column(DateTime)
    content_hash: Mapped[str] = mapped_column(String(64))


class ChatSession(Entity, Base):
    __tablename__ = 'chat_sessions'
    __table_args__ = (Index('ix_session_owner_time', 'user_id', 'last_message_at'),)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    title: Mapped[str] = mapped_column(String(255), default='新对话')
    status: Mapped[str] = mapped_column(String(20), default='active')
    last_message_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Message(Entity, Base):
    __tablename__ = 'chat_messages'
    session_id: Mapped[str] = mapped_column(ForeignKey('chat_sessions.id'), index=True)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    web_search: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())


class SessionContext(Base):
    __tablename__ = 'session_contexts'
    session_id: Mapped[str] = mapped_column(ForeignKey('chat_sessions.id'), primary_key=True)
    state: Mapped[dict] = mapped_column(JSON, default=dict)
    conversation_summary: Mapped[str] = mapped_column(Text, default='')
    summarized_until_message_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    state_version: Mapped[int] = mapped_column(Integer, default=0)
    active_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class AgentRun(Entity, Base):
    __tablename__ = 'agent_runs'
    request_id: Mapped[str] = mapped_column(String(64), unique=True)
    session_id: Mapped[str] = mapped_column(ForeignKey('chat_sessions.id'), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    message_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default='running')
    model: Mapped[str] = mapped_column(String(64))
    extracted_requirements: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ToolLog(Entity, Base):
    __tablename__ = 'tool_call_logs'
    run_id: Mapped[str] = mapped_column(ForeignKey('agent_runs.id'), index=True)
    tool_name: Mapped[str] = mapped_column(String(64))
    arguments_redacted: Mapped[dict] = mapped_column(JSON)
    result_summary: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20))
    latency_ms: Mapped[int] = mapped_column(Integer)


class Recommendation(Entity, Base):
    __tablename__ = 'recommendations'
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey('agent_runs.id'))
    answer: Mapped[str] = mapped_column(Text)
    requirements_snapshot: Mapped[dict] = mapped_column(JSON)
    evidence: Mapped[list] = mapped_column(JSON)


class RecommendationItem(Entity, Base):
    __tablename__ = 'recommendation_items'
    recommendation_id: Mapped[str] = mapped_column(ForeignKey('recommendations.id'), index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey('products.id'))
    rank_no: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JSON)


class Feedback(Entity, Base):
    __tablename__ = 'feedback'
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    recommendation_id: Mapped[str] = mapped_column(ForeignKey('recommendations.id'))
    rating: Mapped[int] = mapped_column(Integer)
    comment: Mapped[str] = mapped_column(String(1000), default='')


class ImportJob(Entity, Base):
    __tablename__ = 'import_jobs'
    job_type: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(20), default='running')
    total_count: Mapped[int] = mapped_column(Integer, default=0)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    error_report: Mapped[dict] = mapped_column(JSON, default=dict)


class WebEvidence(Entity, Base):
    __tablename__ = 'web_evidence'
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    url: Mapped[str] = mapped_column(String(1024))
    title: Mapped[str] = mapped_column(String(500))
    content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    category: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_kind: Mapped[str] = mapped_column(String(32))
    relevance_score: Mapped[float] = mapped_column(Float)
    published_at: Mapped[str | None] = mapped_column(String(100), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)


class WebSearchCache(Entity, Base):
    __tablename__ = 'web_search_cache'
    __table_args__ = (UniqueConstraint('user_id', 'query_hash', name='uq_web_search_owner_query'),)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    query_hash: Mapped[str] = mapped_column(String(64))
    evidence_ids: Mapped[list] = mapped_column(JSON, default=list)
    expires_at: Mapped[datetime] = mapped_column(DateTime)


class ProductUpdate(Entity, Base):
    """公开网页的入库审核记录；不包含提问、账号或 API 配置。"""
    __tablename__ = 'product_updates'
    source_url: Mapped[str] = mapped_column(String(1024))
    title: Mapped[str] = mapped_column(String(500))
    source_content: Mapped[str] = mapped_column(Text)
    source_hash: Mapped[str] = mapped_column(String(64))
    category: Mapped[str | None] = mapped_column(String(32), nullable=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(32), default='pending', index=True)
    version: Mapped[int] = mapped_column(Integer, default=0)
    page_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    page_text: Mapped[str] = mapped_column(Text, default='')
    draft: Mapped[dict] = mapped_column(JSON, default=dict)
    field_evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    events: Mapped[list] = mapped_column(JSON, default=list)
    timings: Mapped[dict] = mapped_column(JSON, default=dict)
    product_id: Mapped[str | None] = mapped_column(ForeignKey('products.id'), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey('users.id'), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    review_note: Mapped[str] = mapped_column(String(500), default='')
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)

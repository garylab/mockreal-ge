from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from pgvector.sqlalchemy import Vector


# =====================================================================
# SQLAlchemy Declarative Base
# =====================================================================

class Base(DeclarativeBase):
    pass


# =====================================================================
# Enums (shared by SQLAlchemy models and Pydantic schemas)
# =====================================================================

class ContentStatus(str, Enum):
    draft = "draft"
    approved = "approved"
    rejected = "rejected"
    published = "published"
    archived = "archived"


class Priority(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"
    discard = "discard"


class Platform(str, Enum):
    website = "website"
    medium = "medium"
    linkedin = "linkedin"
    facebook = "facebook"
    twitter = "twitter"
    wechat = "wechat"


class CtaVariant(str, Enum):
    A = "A"
    B = "B"


class TrackingEventType(str, Enum):
    impression = "impression"
    click = "click"
    page_view = "page_view"
    signup = "signup"
    share = "share"


# SA enum types referencing existing PostgreSQL enum types (never CREATE)
_t_content_status = SAEnum(ContentStatus, name="content_status", create_type=False)
_t_priority = SAEnum(Priority, name="priority_level", create_type=False)
_t_platform = SAEnum(Platform, name="platform_type", create_type=False)
_t_cta = SAEnum(CtaVariant, name="cta_variant", create_type=False)
_t_event = SAEnum(TrackingEventType, name="tracking_event", create_type=False)


# =====================================================================
# SQLAlchemy ORM Models (one per database table)
# =====================================================================

class TopicRow(Base):
    __tablename__ = "topics"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str | None] = mapped_column(Text)
    engagement: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sa_text("0"))
    viral_score: Mapped[Decimal] = mapped_column(Numeric(4, 1), nullable=False, server_default=sa_text("0"))
    subreddit: Mapped[str | None] = mapped_column(Text)
    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, server_default=sa_text("gen_random_uuid()"),
    )
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa_text("NOW()"),
    )


class FusedTopicRow(Base):
    __tablename__ = "fused_topics"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    embedding = mapped_column(Vector(1536), nullable=True)
    signal_types = mapped_column(ARRAY(Text), nullable=False, server_default=sa_text("'{}'"))
    reasoning: Mapped[str] = mapped_column(Text, nullable=False, server_default=sa_text("''"))
    suggested_angle: Mapped[str] = mapped_column(Text, nullable=False, server_default=sa_text("''"))
    angles = mapped_column(JSONB, nullable=False, server_default=sa_text("'{}'::jsonb"))
    source_urls = mapped_column(ARRAY(Text), nullable=False, server_default=sa_text("'{}'"))
    source_queries = mapped_column(ARRAY(Text), nullable=False, server_default=sa_text("'{}'"))
    ai_score: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    viral_score: Mapped[Decimal] = mapped_column(Numeric(4, 1), nullable=False, server_default=sa_text("0"))
    seo_potential: Mapped[Decimal] = mapped_column(Numeric(4, 1), nullable=False, server_default=sa_text("0"))
    decision: Mapped[str] = mapped_column(Text, nullable=False, server_default=sa_text("'IGNORE'"))
    cluster: Mapped[str | None] = mapped_column(Text)
    is_duplicate: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=sa_text("FALSE"))
    priority = mapped_column(_t_priority, server_default="medium")
    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, server_default=sa_text("gen_random_uuid()"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa_text("NOW()"),
    )


class ClusterRow(Base):
    __tablename__ = "clusters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa_text("NOW()"),
    )


class ContentRow(Base):
    __tablename__ = "content"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    content_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    fused_topic_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("fused_topics.id", ondelete="SET NULL"),
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    title_embedding = mapped_column(Vector(1536), nullable=True)
    article_html: Mapped[str | None] = mapped_column(Text)
    medium_article: Mapped[str | None] = mapped_column(Text)
    wechat_article: Mapped[str | None] = mapped_column(Text)
    outline = mapped_column(JSONB, nullable=False, server_default=sa_text("'[]'::jsonb"))
    social_posts = mapped_column(JSONB, nullable=False, server_default=sa_text("'{}'::jsonb"))
    social_posts_variant_b = mapped_column(JSONB, nullable=False, server_default=sa_text("'{}'::jsonb"))
    seo_keywords = mapped_column(JSONB, nullable=False, server_default=sa_text("'[]'::jsonb"))
    meta_description: Mapped[str | None] = mapped_column(Text)
    image_url: Mapped[str | None] = mapped_column(Text)
    score: Mapped[Decimal] = mapped_column(Numeric(4, 1), nullable=False, server_default=sa_text("0"))
    cluster: Mapped[str | None] = mapped_column(
        Text, ForeignKey("clusters.slug", ondelete="SET NULL"),
    )
    suggested_angle: Mapped[str | None] = mapped_column(Text)
    priority = mapped_column(_t_priority, nullable=False, server_default="medium")
    cta_variant_a: Mapped[str | None] = mapped_column(Text)
    cta_variant_b: Mapped[str | None] = mapped_column(Text)
    active_cta = mapped_column(_t_cta, nullable=False, server_default="A")
    status = mapped_column(_t_content_status, nullable=False, server_default="draft")
    iteration_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sa_text("0"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa_text("NOW()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa_text("NOW()"),
    )


class PublishLogRow(Base):
    __tablename__ = "publish_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    content_id: Mapped[str] = mapped_column(
        Text, ForeignKey("content.content_id", ondelete="CASCADE"), nullable=False,
    )
    platform = mapped_column(_t_platform, nullable=False)
    published_url: Mapped[str | None] = mapped_column(Text)
    post_body: Mapped[str | None] = mapped_column(Text)
    utm_source: Mapped[str | None] = mapped_column(Text)
    utm_medium: Mapped[str | None] = mapped_column(Text)
    utm_campaign: Mapped[str | None] = mapped_column(Text)
    utm_content: Mapped[str | None] = mapped_column(Text)
    cta_variant = mapped_column(_t_cta)
    response_data = mapped_column(JSONB, server_default=sa_text("'{}'::jsonb"))
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa_text("NOW()"),
    )


class TrackingEventRow(Base):
    __tablename__ = "tracking_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    content_id: Mapped[str] = mapped_column(Text, nullable=False)
    platform = mapped_column(_t_platform)
    event_type = mapped_column(_t_event, nullable=False)
    referrer: Mapped[str | None] = mapped_column(Text)
    user_agent: Mapped[str | None] = mapped_column(Text)
    ip_hash: Mapped[str | None] = mapped_column(Text)
    metadata_ = mapped_column("metadata", JSONB, server_default=sa_text("'{}'::jsonb"))
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa_text("NOW()"),
    )


class PerformanceRow(Base):
    __tablename__ = "performance"
    __table_args__ = (
        UniqueConstraint("content_id", "platform", "period_start", name="uq_perf_content_platform_period"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    content_id: Mapped[str] = mapped_column(
        Text, ForeignKey("content.content_id", ondelete="CASCADE"), nullable=False,
    )
    platform = mapped_column(_t_platform, nullable=False)
    impressions: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sa_text("0"))
    clicks: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sa_text("0"))
    ctr: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False, server_default=sa_text("0"))
    landing_visits: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sa_text("0"))
    signups: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sa_text("0"))
    conversion_rate: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False, server_default=sa_text("0"))
    likes: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sa_text("0"))
    shares: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sa_text("0"))
    comments: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sa_text("0"))
    cta_variant = mapped_column(_t_cta)
    period_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa_text("date_trunc('day', NOW())"),
    )
    period_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=sa_text("date_trunc('day', NOW()) + INTERVAL '1 day'"),
    )
    measured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa_text("NOW()"),
    )


class AbResultRow(Base):
    __tablename__ = "ab_results"
    __table_args__ = (
        UniqueConstraint("cluster", name="uq_ab_cluster"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cluster: Mapped[str] = mapped_column(
        Text, ForeignKey("clusters.slug", ondelete="CASCADE"), nullable=False,
    )
    variant_a_impressions: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sa_text("0"))
    variant_a_clicks: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sa_text("0"))
    variant_a_signups: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sa_text("0"))
    variant_b_impressions: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sa_text("0"))
    variant_b_clicks: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sa_text("0"))
    variant_b_signups: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sa_text("0"))
    winner = mapped_column(_t_cta)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), server_default=sa_text("0"))
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa_text("NOW()"),
    )


class DashboardSnapshotRow(Base):
    __tablename__ = "dashboard_snapshots"
    __table_args__ = (
        UniqueConstraint("snapshot_date", name="uq_snapshot_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False, server_default=sa_text("CURRENT_DATE"))
    total_content: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sa_text("0"))
    total_published: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sa_text("0"))
    total_clicks: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sa_text("0"))
    total_signups: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sa_text("0"))
    overall_ctr: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False, server_default=sa_text("0"))
    overall_conv: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False, server_default=sa_text("0"))
    top_cluster: Mapped[str | None] = mapped_column(Text)
    top_platform: Mapped[str | None] = mapped_column(Text)
    cluster_breakdown = mapped_column(JSONB, nullable=False, server_default=sa_text("'[]'::jsonb"))
    platform_breakdown = mapped_column(JSONB, nullable=False, server_default=sa_text("'[]'::jsonb"))
    ab_summary = mapped_column(JSONB, nullable=False, server_default=sa_text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa_text("NOW()"),
    )


# =====================================================================
# Pydantic models (pipeline data — NOT database rows)
# =====================================================================

class RawSignal(BaseModel):
    title: str
    source: str
    url: str = ""
    engagement: float = 0
    snippet: str = ""
    extra: dict[str, Any] = Field(default_factory=dict)


class ScoredTopic(BaseModel):
    title: str
    source: str = "fused"
    score: float = 0
    original_score: float = 0
    score_adjustment: float = 0
    reasoning: str = ""
    decision: str = "IGNORE"
    suggested_angle: str = ""
    cluster: str = "other"
    is_duplicate: bool = False
    viral_score: float = 0
    seo_potential: float = 0
    signal_types: list[str] = Field(default_factory=list)
    angles: dict[str, str] = Field(default_factory=dict)
    priority: Priority = Priority.medium
    source_urls: list[str] = Field(default_factory=list)
    source_queries: list[str] = Field(default_factory=list)
    derivation_strategy: str | None = None
    parent_title: str | None = None


class ContentPackage(BaseModel):
    content_id: str = ""
    topic: ScoredTopic | None = None
    article_title: str = ""
    outline: list[str] = Field(default_factory=list)
    article_html: str = ""
    medium_article: str = ""
    wechat_article: str = ""
    social_posts: dict[str, str] = Field(default_factory=dict)
    social_posts_variant_b: dict[str, str] = Field(default_factory=dict)
    seo_keywords: list[str] = Field(default_factory=list)
    meta_description: str = ""
    cta_variant_a: str = ""
    cta_variant_b: str = ""
    featured_image_url: str = ""
    section_images: list[dict[str, str]] = Field(default_factory=list)
    humanized: bool = False
    status: ContentStatus = ContentStatus.draft
    created_at: datetime = Field(default_factory=datetime.utcnow)


class PublishRecord(BaseModel):
    content_id: str
    platform: Platform
    url: str = ""
    cta_variant: str = "a"
    published_at: datetime = Field(default_factory=datetime.utcnow)


class PerformanceMetrics(BaseModel):
    content_id: str
    platform: Platform
    impressions: int = 0
    clicks: int = 0
    signups: int = 0
    ctr: float = 0
    conversion_rate: float = 0

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


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
    # Derived-topic fields
    derivation_strategy: str | None = None
    parent_title: str | None = None


class ContentPackage(BaseModel):
    content_id: str = ""
    topic: ScoredTopic | None = None
    article_title: str = ""
    outline: list[str] = Field(default_factory=list)
    article_html: str = ""
    medium_article: str = ""
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

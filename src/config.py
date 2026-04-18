from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    db_host: str = "localhost"
    db_port: int = 5432
    db_user: str = "postgres"
    db_pass: str = ""
    db_name: str = "mockreal_ge"

    # Timezone
    generic_timezone: str = "Asia/Dubai"

    # AI
    anthropic_api_key: str = ""
    openai_api_key: str = ""

    # Data sources
    serpapi_key: str = ""
    twitter_bearer_token: str = ""

    # Telegram
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # Publishing
    website_api_url: str = ""
    website_api_key: str = ""
    medium_api_token: str = ""
    medium_author_id: str = ""
    linkedin_access_token: str = ""
    linkedin_person_urn: str = ""
    facebook_page_id: str = ""
    facebook_access_token: str = ""

    # Images
    pexels_api_key: str = ""
    r2_endpoint: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket: str = ""
    r2_public_url: str = ""

    # Dashboard
    dashboard_webhook_url: str = ""

    # App
    app_port: int = 8000
    pipeline_interval_hours: int = 6
    metrics_hour: int = 3
    score_threshold: int = 7
    viral_threshold: int = 8

    # Rate limiting
    max_concurrent_api: int = 5
    max_concurrent_ai: int = 2

    # Topic blacklist (comma-separated keywords to exclude)
    topic_blacklist: str = ""

    # Publish scheduling (comma-separated hours in 24h format, e.g. "8,12,18")
    publish_hours: str = "8,12,18"

    @property
    def dsn(self) -> str:
        return f"postgresql://{self.db_user}:{self.db_pass}@{self.db_host}:{self.db_port}/{self.db_name}"


settings = Settings()

CLUSTERS = [
    "interview_prep", "career_transition", "ai_tools", "job_market",
    "resume_skills", "layoff_survival", "salary_negotiation",
    "remote_work", "tech_industry", "other",
]

def get_blacklist() -> list[str]:
    raw = settings.topic_blacklist.strip()
    if not raw:
        return []
    return [w.strip().lower() for w in raw.split(",") if w.strip()]


BANNED_PHRASES = [
    "in today's rapidly evolving", "it's worth noting", "let's dive in",
    "in this article we will", "landscape", "leverage", "navigate",
    "unlock", "empower", "delve", "tapestry", "holistic", "game-changer",
    "paradigm shift", "synergy", "cutting-edge", "state-of-the-art",
    "in conclusion", "to sum up", "in summary", "as we've seen",
    "it is important to note", "furthermore", "moreover", "certainly",
    "absolutely", "without a doubt", "at the end of the day",
    "when it comes to", "in order to", "the fact that",
]

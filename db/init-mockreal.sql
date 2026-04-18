CREATE SCHEMA IF NOT EXISTS mockreal;

-- ============================================================
-- ENUM-LIKE DOMAINS
-- ============================================================

DO $$ BEGIN
  CREATE TYPE mockreal.content_status AS ENUM (
    'draft', 'approved', 'rejected', 'published', 'archived'
  );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
  CREATE TYPE mockreal.priority_level AS ENUM (
    'high', 'medium', 'low', 'discard'
  );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
  CREATE TYPE mockreal.platform_type AS ENUM (
    'website', 'twitter', 'linkedin', 'medium', 'facebook'
  );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
  CREATE TYPE mockreal.cta_variant AS ENUM ('A', 'B');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
  CREATE TYPE mockreal.tracking_event AS ENUM (
    'impression', 'click', 'page_view', 'signup', 'share'
  );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ============================================================
-- TABLE: topics
-- Raw trending topics collected from all data sources.
-- ============================================================

CREATE TABLE IF NOT EXISTS mockreal.topics (
  id              BIGSERIAL       PRIMARY KEY,
  source          TEXT            NOT NULL,
  title           TEXT            NOT NULL,
  url             TEXT,
  engagement      INTEGER         NOT NULL DEFAULT 0,
  viral_score     NUMERIC(4,1)   NOT NULL DEFAULT 0,
  subreddit       TEXT,
  cluster         TEXT,
  is_duplicate    BOOLEAN         NOT NULL DEFAULT FALSE,
  ai_score        NUMERIC(4,1),
  score_adjustment INTEGER        NOT NULL DEFAULT 0,
  final_score     NUMERIC(4,1),
  decision        TEXT,
  suggested_angle TEXT,
  priority        mockreal.priority_level DEFAULT 'medium',
  batch_id        UUID            NOT NULL DEFAULT gen_random_uuid(),
  fetched_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
  scored_at       TIMESTAMPTZ
);

-- ============================================================
-- TABLE: clusters
-- Reference table for content clusters with performance memory.
-- ============================================================

CREATE TABLE IF NOT EXISTS mockreal.clusters (
  id              SERIAL          PRIMARY KEY,
  slug            TEXT            UNIQUE NOT NULL,
  label           TEXT            NOT NULL,
  avg_ctr         NUMERIC(6,2)   NOT NULL DEFAULT 0,
  avg_conversion  NUMERIC(6,2)   NOT NULL DEFAULT 0,
  total_posts     INTEGER         NOT NULL DEFAULT 0,
  score_boost     INTEGER         NOT NULL DEFAULT 0,
  updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

INSERT INTO mockreal.clusters (slug, label) VALUES
  ('interview_prep',     'Interview Preparation'),
  ('career_transition',  'Career Transition'),
  ('ai_tools',           'AI Tools & Productivity'),
  ('job_market',         'Job Market Trends'),
  ('resume_skills',      'Resume & Skills'),
  ('layoff_survival',    'Layoff Survival'),
  ('salary_negotiation', 'Salary Negotiation'),
  ('remote_work',        'Remote Work'),
  ('tech_industry',      'Tech Industry'),
  ('other',              'Other')
ON CONFLICT (slug) DO NOTHING;

-- ============================================================
-- TABLE: content
-- Generated articles + social posts + CTA variants.
-- ============================================================

CREATE TABLE IF NOT EXISTS mockreal.content (
  id                    BIGSERIAL                PRIMARY KEY,
  content_id            TEXT                     UNIQUE NOT NULL,
  topic_id              BIGINT                   REFERENCES mockreal.topics(id) ON DELETE SET NULL,
  title                 TEXT                     NOT NULL,
  article_html          TEXT,
  medium_article        TEXT,
  outline               JSONB                    NOT NULL DEFAULT '[]'::jsonb,
  social_posts          JSONB                    NOT NULL DEFAULT '{}'::jsonb,
  social_posts_variant_b JSONB                   NOT NULL DEFAULT '{}'::jsonb,
  seo_keywords          JSONB                    NOT NULL DEFAULT '[]'::jsonb,
  meta_description      TEXT,
  image_url             TEXT,
  score                 NUMERIC(4,1)             NOT NULL DEFAULT 0,
  viral_score           NUMERIC(4,1)             NOT NULL DEFAULT 0,
  source                TEXT,
  cluster               TEXT                     REFERENCES mockreal.clusters(slug) ON DELETE SET NULL,
  suggested_angle       TEXT,
  priority              mockreal.priority_level  NOT NULL DEFAULT 'medium',
  cta_variant_a         TEXT,
  cta_variant_b         TEXT,
  active_cta            mockreal.cta_variant     NOT NULL DEFAULT 'A',
  status                mockreal.content_status  NOT NULL DEFAULT 'draft',
  iteration_count       INTEGER                  NOT NULL DEFAULT 0,
  approved_by           TEXT,
  approved_at           TIMESTAMPTZ,
  created_at            TIMESTAMPTZ              NOT NULL DEFAULT NOW(),
  updated_at            TIMESTAMPTZ              NOT NULL DEFAULT NOW()
);

-- ============================================================
-- TABLE: publish_logs
-- One row per platform per content publish event.
-- ============================================================

CREATE TABLE IF NOT EXISTS mockreal.publish_logs (
  id              BIGSERIAL                PRIMARY KEY,
  content_id      TEXT                     NOT NULL REFERENCES mockreal.content(content_id) ON DELETE CASCADE,
  platform        mockreal.platform_type   NOT NULL,
  published_url   TEXT,
  post_body       TEXT,
  utm_source      TEXT,
  utm_medium      TEXT,
  utm_campaign    TEXT,
  utm_content     TEXT,
  cta_variant     mockreal.cta_variant,
  response_data   JSONB                    DEFAULT '{}'::jsonb,
  published_at    TIMESTAMPTZ              NOT NULL DEFAULT NOW()
);

-- ============================================================
-- TABLE: tracking_events
-- Raw inbound events from the tracking webhook (click, signup…).
-- Append-only log; aggregated into performance by the daily cron.
-- ============================================================

CREATE TABLE IF NOT EXISTS mockreal.tracking_events (
  id              BIGSERIAL                PRIMARY KEY,
  content_id      TEXT                     NOT NULL,
  platform        mockreal.platform_type,
  event_type      mockreal.tracking_event  NOT NULL,
  referrer        TEXT,
  user_agent      TEXT,
  ip_hash         TEXT,
  metadata        JSONB                    DEFAULT '{}'::jsonb,
  received_at     TIMESTAMPTZ              NOT NULL DEFAULT NOW()
);

-- ============================================================
-- TABLE: performance
-- Aggregated metrics per content × platform window.
-- ============================================================

CREATE TABLE IF NOT EXISTS mockreal.performance (
  id              BIGSERIAL       PRIMARY KEY,
  content_id      TEXT            NOT NULL REFERENCES mockreal.content(content_id) ON DELETE CASCADE,
  platform        mockreal.platform_type NOT NULL,
  impressions     INTEGER         NOT NULL DEFAULT 0,
  clicks          INTEGER         NOT NULL DEFAULT 0,
  ctr             NUMERIC(6,2)   NOT NULL DEFAULT 0,
  landing_visits  INTEGER         NOT NULL DEFAULT 0,
  signups         INTEGER         NOT NULL DEFAULT 0,
  conversion_rate NUMERIC(6,2)   NOT NULL DEFAULT 0,
  likes           INTEGER         NOT NULL DEFAULT 0,
  shares          INTEGER         NOT NULL DEFAULT 0,
  comments        INTEGER         NOT NULL DEFAULT 0,
  cta_variant     mockreal.cta_variant,
  period_start    TIMESTAMPTZ     NOT NULL DEFAULT date_trunc('day', NOW()),
  period_end      TIMESTAMPTZ     NOT NULL DEFAULT date_trunc('day', NOW()) + INTERVAL '1 day',
  measured_at     TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

  CONSTRAINT uq_perf_content_platform_period
    UNIQUE (content_id, platform, period_start)
);

-- ============================================================
-- TABLE: ab_results
-- CTA A/B test outcomes per cluster for the learning loop.
-- ============================================================

CREATE TABLE IF NOT EXISTS mockreal.ab_results (
  id              SERIAL          PRIMARY KEY,
  cluster         TEXT            NOT NULL REFERENCES mockreal.clusters(slug) ON DELETE CASCADE,
  variant_a_impressions INTEGER   NOT NULL DEFAULT 0,
  variant_a_clicks     INTEGER   NOT NULL DEFAULT 0,
  variant_a_signups    INTEGER   NOT NULL DEFAULT 0,
  variant_b_impressions INTEGER   NOT NULL DEFAULT 0,
  variant_b_clicks     INTEGER   NOT NULL DEFAULT 0,
  variant_b_signups    INTEGER   NOT NULL DEFAULT 0,
  winner          mockreal.cta_variant,
  confidence      NUMERIC(5,2)   DEFAULT 0,
  computed_at     TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

  CONSTRAINT uq_ab_cluster UNIQUE (cluster)
);

-- ============================================================
-- TABLE: dashboard_snapshots
-- Daily snapshots of growth metrics for trend analysis.
-- ============================================================

CREATE TABLE IF NOT EXISTS mockreal.dashboard_snapshots (
  id              BIGSERIAL       PRIMARY KEY,
  snapshot_date   DATE            NOT NULL DEFAULT CURRENT_DATE,
  total_content   INTEGER         NOT NULL DEFAULT 0,
  total_published INTEGER         NOT NULL DEFAULT 0,
  total_clicks    INTEGER         NOT NULL DEFAULT 0,
  total_signups   INTEGER         NOT NULL DEFAULT 0,
  overall_ctr     NUMERIC(6,2)   NOT NULL DEFAULT 0,
  overall_conv    NUMERIC(6,2)   NOT NULL DEFAULT 0,
  top_cluster     TEXT,
  top_platform    TEXT,
  cluster_breakdown JSONB         NOT NULL DEFAULT '[]'::jsonb,
  platform_breakdown JSONB        NOT NULL DEFAULT '[]'::jsonb,
  ab_summary      JSONB           NOT NULL DEFAULT '{}'::jsonb,
  created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

  CONSTRAINT uq_snapshot_date UNIQUE (snapshot_date)
);

-- ============================================================
-- INDEXES
-- ============================================================

-- topics
CREATE INDEX IF NOT EXISTS idx_topics_source       ON mockreal.topics (source);
CREATE INDEX IF NOT EXISTS idx_topics_batch         ON mockreal.topics (batch_id);
CREATE INDEX IF NOT EXISTS idx_topics_cluster       ON mockreal.topics (cluster);
CREATE INDEX IF NOT EXISTS idx_topics_fetched       ON mockreal.topics (fetched_at DESC);

-- content
CREATE INDEX IF NOT EXISTS idx_content_status       ON mockreal.content (status);
CREATE INDEX IF NOT EXISTS idx_content_cluster      ON mockreal.content (cluster);
CREATE INDEX IF NOT EXISTS idx_content_priority     ON mockreal.content (priority);
CREATE INDEX IF NOT EXISTS idx_content_created      ON mockreal.content (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_content_score        ON mockreal.content (score DESC);
CREATE INDEX IF NOT EXISTS idx_content_status_score ON mockreal.content (status, score DESC);

-- publish_logs
CREATE INDEX IF NOT EXISTS idx_publish_content      ON mockreal.publish_logs (content_id);
CREATE INDEX IF NOT EXISTS idx_publish_platform     ON mockreal.publish_logs (platform);
CREATE INDEX IF NOT EXISTS idx_publish_at           ON mockreal.publish_logs (published_at DESC);
CREATE INDEX IF NOT EXISTS idx_publish_content_plat ON mockreal.publish_logs (content_id, platform);

-- tracking_events
CREATE INDEX IF NOT EXISTS idx_track_content        ON mockreal.tracking_events (content_id);
CREATE INDEX IF NOT EXISTS idx_track_event          ON mockreal.tracking_events (event_type);
CREATE INDEX IF NOT EXISTS idx_track_received       ON mockreal.tracking_events (received_at DESC);
CREATE INDEX IF NOT EXISTS idx_track_content_event  ON mockreal.tracking_events (content_id, event_type);

-- performance
CREATE INDEX IF NOT EXISTS idx_perf_content         ON mockreal.performance (content_id);
CREATE INDEX IF NOT EXISTS idx_perf_platform        ON mockreal.performance (platform);
CREATE INDEX IF NOT EXISTS idx_perf_period          ON mockreal.performance (period_start DESC);
CREATE INDEX IF NOT EXISTS idx_perf_content_plat    ON mockreal.performance (content_id, platform);
CREATE INDEX IF NOT EXISTS idx_perf_ctr             ON mockreal.performance (ctr DESC);
CREATE INDEX IF NOT EXISTS idx_perf_conversion      ON mockreal.performance (conversion_rate DESC);

-- ============================================================
-- FUNCTION: auto-update updated_at on row modification
-- ============================================================

CREATE OR REPLACE FUNCTION mockreal.set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DO $$ BEGIN
  CREATE TRIGGER trg_content_updated
    BEFORE UPDATE ON mockreal.content
    FOR EACH ROW EXECUTE FUNCTION mockreal.set_updated_at();
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
  CREATE TRIGGER trg_clusters_updated
    BEFORE UPDATE ON mockreal.clusters
    FOR EACH ROW EXECUTE FUNCTION mockreal.set_updated_at();
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ============================================================
-- VIEW: content_with_performance
-- Joins content with its latest aggregated performance metrics.
-- ============================================================

CREATE OR REPLACE VIEW mockreal.content_with_performance AS
SELECT
  c.content_id,
  c.title,
  c.cluster,
  c.score,
  c.viral_score,
  c.priority,
  c.status,
  c.active_cta,
  c.iteration_count,
  c.created_at,
  COALESCE(SUM(p.impressions), 0)       AS total_impressions,
  COALESCE(SUM(p.clicks), 0)            AS total_clicks,
  COALESCE(SUM(p.signups), 0)           AS total_signups,
  CASE
    WHEN SUM(p.impressions) > 0
    THEN ROUND(SUM(p.clicks)::NUMERIC / SUM(p.impressions) * 100, 2)
    ELSE 0
  END                                    AS overall_ctr,
  CASE
    WHEN SUM(p.clicks) > 0
    THEN ROUND(SUM(p.signups)::NUMERIC / SUM(p.clicks) * 100, 2)
    ELSE 0
  END                                    AS overall_conversion
FROM mockreal.content c
LEFT JOIN mockreal.performance p ON c.content_id = p.content_id
GROUP BY c.content_id, c.title, c.cluster, c.score, c.viral_score,
         c.priority, c.status, c.active_cta, c.iteration_count, c.created_at;

-- ============================================================
-- VIEW: cluster_performance
-- Aggregated performance per cluster for the feedback loop.
-- ============================================================

CREATE OR REPLACE VIEW mockreal.cluster_performance AS
SELECT
  cl.slug                                AS cluster,
  cl.label,
  cl.score_boost,
  COUNT(DISTINCT c.content_id)           AS total_content,
  COALESCE(AVG(p.ctr), 0)               AS avg_ctr,
  COALESCE(AVG(p.conversion_rate), 0)    AS avg_conversion,
  COALESCE(SUM(p.signups), 0)           AS total_signups,
  cl.updated_at
FROM mockreal.clusters cl
LEFT JOIN mockreal.content c   ON cl.slug = c.cluster AND c.status IN ('approved', 'published')
LEFT JOIN mockreal.performance p ON c.content_id = p.content_id
GROUP BY cl.slug, cl.label, cl.score_boost, cl.updated_at;

-- ============================================================
-- VIEW: low_ctr_candidates
-- Content eligible for hook/CTA regeneration.
-- ============================================================

CREATE OR REPLACE VIEW mockreal.low_ctr_candidates AS
SELECT
  c.content_id,
  c.title,
  c.cluster,
  c.score,
  c.iteration_count,
  c.created_at,
  AVG(p.ctr)              AS avg_ctr,
  AVG(p.conversion_rate)  AS avg_conversion
FROM mockreal.content c
JOIN mockreal.performance p ON c.content_id = p.content_id
WHERE c.status IN ('approved', 'published')
  AND c.score >= 7
  AND c.iteration_count < 3
  AND c.created_at < NOW() - INTERVAL '48 hours'
GROUP BY c.content_id, c.title, c.cluster, c.score, c.iteration_count, c.created_at
HAVING AVG(p.ctr) < 2;

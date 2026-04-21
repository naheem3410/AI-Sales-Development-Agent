"""
schema.py
---------
Database schema definitions.
SQLite locally — Aurora PostgreSQL in production.
Identical schema in both environments.
Column types are written to be valid in both SQLite and PostgreSQL.
"""

# 
# SCHEMA SQL
# Execute these in order. Foreign keys enforced.
# 

SCHEMA_SQL = """

-- ── Users 
CREATE TABLE IF NOT EXISTS users (
    id                  TEXT PRIMARY KEY,
    email               TEXT NOT NULL UNIQUE,
    full_name           TEXT,
    stripe_customer_id  TEXT,
    plan                TEXT DEFAULT 'free',        -- free, starter, pro, enterprise
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

-- ── Campaigns 
-- One campaign = one ICP = one product brief = one outreach run
CREATE TABLE IF NOT EXISTS campaigns (
    id                  TEXT PRIMARY KEY,
    user_id             TEXT NOT NULL REFERENCES users(id),
    name                TEXT NOT NULL,              -- user-defined campaign name
    status              TEXT NOT NULL DEFAULT 'created',
    website_url         TEXT,                       -- source URL for onboarding
    company_name        TEXT,
    pipeline_version    TEXT DEFAULT '1.0.0',
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    completed_at        TEXT,
    paused_at           TEXT,
    failure_reason      TEXT                        -- populated if status=failed
);

CREATE INDEX IF NOT EXISTS idx_campaigns_user_id ON campaigns(user_id);
CREATE INDEX IF NOT EXISTS idx_campaigns_status ON campaigns(status);

-- ── ICP (Ideal Customer Profile) 
-- Belongs to a campaign. Editable by user after onboarding.
CREATE TABLE IF NOT EXISTS icps (
    id                  TEXT PRIMARY KEY,
    campaign_id         TEXT NOT NULL REFERENCES campaigns(id),
    user_id             TEXT NOT NULL REFERENCES users(id),
    target_type         TEXT NOT NULL,              -- business, individual, both
    industry            TEXT NOT NULL,              -- JSON array
    company_size_min    INTEGER,
    company_size_max    INTEGER,
    funding_status      TEXT,                       -- JSON array or null
    job_titles          TEXT NOT NULL,              -- JSON array
    seniority           TEXT,                       -- JSON array or null
    locations           TEXT NOT NULL,              -- JSON array
    tech_stack          TEXT,                       -- JSON array or null
    demographics        TEXT,
    confidence_score    REAL,
    missing_fields      TEXT,                       -- JSON array
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_icps_campaign_id ON icps(campaign_id);

-- ── Product Briefs 
CREATE TABLE IF NOT EXISTS product_briefs (
    id                          TEXT PRIMARY KEY,
    campaign_id                 TEXT NOT NULL REFERENCES campaigns(id),
    user_id                     TEXT NOT NULL REFERENCES users(id),
    product_name                TEXT NOT NULL,
    what_it_does                TEXT NOT NULL,
    who_it_is_for               TEXT NOT NULL,
    pain_it_solves              TEXT NOT NULL,
    key_differentiators         TEXT NOT NULL,      -- JSON array
    ideal_customer_description  TEXT NOT NULL,
    created_at                  TEXT NOT NULL,
    updated_at                  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_product_briefs_campaign_id ON product_briefs(campaign_id);

-- ── Orchestration State 
-- Ghost participant slot. Tracks orchestration decisions per campaign run.
-- Empty today. Populated when orchestration agent is activated.
CREATE TABLE IF NOT EXISTS orchestration_state (
    id                      TEXT PRIMARY KEY,
    campaign_id             TEXT NOT NULL REFERENCES campaigns(id),
    user_id                 TEXT NOT NULL REFERENCES users(id),
    provider_selected       TEXT,                   -- apollo or prospeo
    fetch_all               INTEGER,                -- 0 or 1
    enrich_mobile           INTEGER DEFAULT 0,      -- 0 or 1
    target_lead_count       INTEGER,
    batch_quality_score     REAL,
    filters_relaxed         INTEGER DEFAULT 0,      -- 0 or 1
    relaxed_fields          TEXT,                   -- JSON array
    retry_count             INTEGER DEFAULT 0,
    decision_log            TEXT,                   -- JSON array of decisions made
    notes                   TEXT,
    activated               INTEGER DEFAULT 0,      -- 0 = pass-through, 1 = active
    created_at              TEXT NOT NULL,
    updated_at              TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_orchestration_campaign_id ON orchestration_state(campaign_id);

-- ── Leads 
-- Every lead is scoped to a campaign and user.
CREATE TABLE IF NOT EXISTS leads (
    id                  TEXT PRIMARY KEY,
    campaign_id         TEXT NOT NULL REFERENCES campaigns(id),
    user_id             TEXT NOT NULL REFERENCES users(id),
    status              TEXT NOT NULL DEFAULT 'ingested',
    -- Identity
    name                TEXT,
    first_name          TEXT,
    last_name           TEXT,
    title               TEXT,
    seniority           TEXT,
    email               TEXT,
    email_status        TEXT,
    phone               TEXT,
    -- Company
    company             TEXT,
    company_size        INTEGER,
    industry            TEXT,
    -- Location
    location            TEXT,
    country             TEXT,
    -- Social
    linkedin            TEXT,
    -- Provider
    provider_id         TEXT,
    provider            TEXT,
    lead_type           TEXT,                       -- business, individual, both
    -- Timestamps
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_leads_campaign_id ON leads(campaign_id);
CREATE INDEX IF NOT EXISTS idx_leads_user_id ON leads(user_id);
CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status);
CREATE INDEX IF NOT EXISTS idx_leads_email ON leads(email);

-- ── Search Queries 
-- 5 queries generated per lead by query generator.
CREATE TABLE IF NOT EXISTS lead_queries (
    id                  TEXT PRIMARY KEY,
    lead_id             TEXT NOT NULL REFERENCES leads(id),
    campaign_id         TEXT NOT NULL REFERENCES campaigns(id),
    user_id             TEXT NOT NULL REFERENCES users(id),
    query_slot          INTEGER NOT NULL,           -- 1 through 5
    query_text          TEXT NOT NULL,
    created_at          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_lead_queries_lead_id ON lead_queries(lead_id);
CREATE INDEX IF NOT EXISTS idx_lead_queries_campaign_id ON lead_queries(campaign_id);

-- ── Enrichment Results 
CREATE TABLE IF NOT EXISTS enrichment_results (
    id                      TEXT PRIMARY KEY,
    lead_id                 TEXT NOT NULL REFERENCES leads(id),
    campaign_id             TEXT NOT NULL REFERENCES campaigns(id),
    user_id                 TEXT NOT NULL REFERENCES users(id),
    -- Identity
    identity_status         TEXT NOT NULL,          -- confirmed, ambiguous, not_found
    confidence_score        REAL NOT NULL,
    -- Enriched data
    current_title           TEXT,
    social_links            TEXT,                   -- JSON array
    company_signals         TEXT,                   -- JSON array of {key, value}
    notable_achievements    TEXT,                   -- JSON array
    -- Discrepancies
    discrepancies           TEXT,                   -- JSON array of DiscrepancyFlag
    -- Evidence
    raw_search_evidence     TEXT,                   -- JSON array (stored in S3 if large)
    raw_search_evidence_s3  TEXT,                   -- S3 key if offloaded
    evidence_used           TEXT,                   -- JSON array of URLs
    -- Coverage
    query_slot_coverage     TEXT,                   -- JSON array of {key, value}
    enrichment_summary      TEXT,
    created_at              TEXT NOT NULL,
    updated_at              TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_enrichment_lead_id ON enrichment_results(lead_id);
CREATE INDEX IF NOT EXISTS idx_enrichment_campaign_id ON enrichment_results(campaign_id);

-- ── Qualification Results 
CREATE TABLE IF NOT EXISTS qualification_results (
    id                  TEXT PRIMARY KEY,
    lead_id             TEXT NOT NULL REFERENCES leads(id),
    campaign_id         TEXT NOT NULL REFERENCES campaigns(id),
    user_id             TEXT NOT NULL REFERENCES users(id),
    decision            TEXT NOT NULL,              -- approved, review, rejected
    decision_reason     TEXT NOT NULL,
    icp_match_score     REAL NOT NULL,
    match_breakdown     TEXT,                       -- JSON array of DimensionScore
    blocking_issues     TEXT,                       -- JSON array
    review_flags        TEXT,                       -- JSON array
    recommended_angle   TEXT,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_qualification_lead_id ON qualification_results(lead_id);
CREATE INDEX IF NOT EXISTS idx_qualification_campaign_id ON qualification_results(campaign_id);
CREATE INDEX IF NOT EXISTS idx_qualification_decision ON qualification_results(decision);

-- ── Email Sequences 
CREATE TABLE IF NOT EXISTS email_sequences (
    id                  TEXT PRIMARY KEY,
    lead_id             TEXT NOT NULL REFERENCES leads(id),
    campaign_id         TEXT NOT NULL REFERENCES campaigns(id),
    user_id             TEXT NOT NULL REFERENCES users(id),
    lead_email          TEXT NOT NULL,
    -- Email 1
    email_1_subject     TEXT,
    email_1_body        TEXT,
    -- Email 2
    email_2_subject     TEXT,
    email_2_body        TEXT,
    -- Email 3
    email_3_subject     TEXT,
    email_3_body        TEXT,
    -- Meta
    sequence_notes      TEXT,
    -- Sending state (future)
    email_1_sent_at     TEXT,
    email_2_sent_at     TEXT,
    email_3_sent_at     TEXT,
    email_1_opened_at   TEXT,
    email_2_opened_at   TEXT,
    email_3_opened_at   TEXT,
    replied_at          TEXT,
    reply_content       TEXT,
    reply_classification TEXT,                      -- future: Reply Agent
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_email_sequences_lead_id ON email_sequences(lead_id);
CREATE INDEX IF NOT EXISTS idx_email_sequences_campaign_id ON email_sequences(campaign_id);

-- ── Pipeline Messages (audit log) 
-- Every message that passes through the queue is logged here.
-- This is the full audit trail of the pipeline.
CREATE TABLE IF NOT EXISTS pipeline_messages (
    id                          TEXT PRIMARY KEY,   -- message_id
    correlation_id              TEXT NOT NULL,
    user_id                     TEXT NOT NULL REFERENCES users(id),
    campaign_id                 TEXT NOT NULL REFERENCES campaigns(id),
    source_agent                TEXT NOT NULL,
    target_agent                TEXT NOT NULL,
    queue                       TEXT NOT NULL,
    status                      TEXT NOT NULL,
    campaign_status_on_send     TEXT NOT NULL,
    orchestration_metadata      TEXT,               -- JSON
    payload_summary             TEXT,               -- brief summary, not full payload
    payload_s3_key              TEXT,               -- S3 key for full payload if large
    retry_count                 INTEGER DEFAULT 0,
    last_error                  TEXT,               -- JSON
    pipeline_version            TEXT,
    created_at                  TEXT NOT NULL,
    processed_at                TEXT,
    completed_at                TEXT
);

CREATE INDEX IF NOT EXISTS idx_pipeline_messages_campaign_id ON pipeline_messages(campaign_id);
CREATE INDEX IF NOT EXISTS idx_pipeline_messages_correlation_id ON pipeline_messages(correlation_id);
CREATE INDEX IF NOT EXISTS idx_pipeline_messages_status ON pipeline_messages(status);

-- ── Pipeline Events (state change log) 
-- Every campaign status transition is recorded here.
CREATE TABLE IF NOT EXISTS pipeline_events (
    id              TEXT PRIMARY KEY,
    campaign_id     TEXT NOT NULL REFERENCES campaigns(id),
    user_id         TEXT NOT NULL REFERENCES users(id),
    agent           TEXT NOT NULL,
    from_status     TEXT,
    to_status       TEXT NOT NULL,
    notes           TEXT,
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_pipeline_events_campaign_id ON pipeline_events(campaign_id);

"""


# 
# FUTURE AGENT TABLES
# Provisioned as empty stubs. Fill in columns when agents are built.
# 

FUTURE_SCHEMA_SQL = """

-- ── Reply Tracking (future: Reply Agent) 
CREATE TABLE IF NOT EXISTS reply_tracking (
    id                      TEXT PRIMARY KEY,
    lead_id                 TEXT NOT NULL REFERENCES leads(id),
    campaign_id             TEXT NOT NULL REFERENCES campaigns(id),
    user_id                 TEXT NOT NULL REFERENCES users(id),
    email_sequence_id       TEXT REFERENCES email_sequences(id),
    reply_received_at       TEXT,
    reply_content           TEXT,
    reply_classification    TEXT,                   -- interested, not_interested, referral, oof
    next_action             TEXT,
    created_at              TEXT NOT NULL,
    updated_at              TEXT NOT NULL
);

-- ── Follow Up Tracking (future: Follow Up Agent) 
CREATE TABLE IF NOT EXISTS followup_tracking (
    id                      TEXT PRIMARY KEY,
    lead_id                 TEXT NOT NULL REFERENCES leads(id),
    campaign_id             TEXT NOT NULL REFERENCES campaigns(id),
    user_id                 TEXT NOT NULL REFERENCES users(id),
    email_sequence_id       TEXT REFERENCES email_sequences(id),
    followup_number         INTEGER,                -- 2 or 3
    scheduled_at            TEXT,
    sent_at                 TEXT,
    created_at              TEXT NOT NULL,
    updated_at              TEXT NOT NULL
);

-- ── Meeting Tracking (future: Meeting Agent) 
CREATE TABLE IF NOT EXISTS meeting_tracking (
    id                      TEXT PRIMARY KEY,
    lead_id                 TEXT NOT NULL REFERENCES leads(id),
    campaign_id             TEXT NOT NULL REFERENCES campaigns(id),
    user_id                 TEXT NOT NULL REFERENCES users(id),
    meeting_scheduled_at    TEXT,
    meeting_type            TEXT,
    calendar_link           TEXT,
    notes                   TEXT,
    created_at              TEXT NOT NULL,
    updated_at              TEXT NOT NULL
);

"""

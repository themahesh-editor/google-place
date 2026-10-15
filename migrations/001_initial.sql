CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, applied_at_utc TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS workflow_run (
    workflow_run_id TEXT PRIMARY KEY,
    started_at_utc TEXT NOT NULL,
    ended_at_utc TEXT,
    mode TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('RUNNING','SUCCESS','TARGET_NOT_REACHED','FAILED')),
    reset_state BOOLEAN NOT NULL DEFAULT FALSE,
    metrics_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS leads (
    lead_id TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    company TEXT NOT NULL,
    website TEXT NOT NULL,
    website_domain TEXT NOT NULL UNIQUE,
    city TEXT NOT NULL DEFAULT '',
    region TEXT NOT NULL DEFAULT '',
    country_code TEXT NOT NULL,
    timezone TEXT NOT NULL,
    lead_source TEXT NOT NULL,
    place_id TEXT NOT NULL UNIQUE,
    scale_class TEXT NOT NULL,
    qualification_confidence REAL NOT NULL CHECK (qualification_confidence >= 0 AND qualification_confidence <= 1),
    qualification_reason TEXT NOT NULL DEFAULT '',
    discovery_facts TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL CHECK (status IN ('ELIGIBLE','RESEARCHING','RESEARCHED','QUEUED','ACTIVE','REPLIED','BOUNCED','UNSUBSCRIBED','COMPLETED','MANUAL_STOP','REVIEW_NEEDED')),
    sender_id TEXT,
    created_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_leads_selection ON leads(status, created_at_utc);
CREATE INDEX IF NOT EXISTS idx_leads_email ON leads(email);
CREATE UNIQUE INDEX IF NOT EXISTS idx_leads_email_unique ON leads(lower(email));

CREATE TABLE IF NOT EXISTS lead_qualification (
    qualification_id TEXT PRIMARY KEY,
    lead_id TEXT NOT NULL REFERENCES leads(lead_id) ON DELETE CASCADE,
    workflow_run_id TEXT NOT NULL REFERENCES workflow_run(workflow_run_id) ON DELETE CASCADE,
    action TEXT NOT NULL CHECK (action IN ('KEEP','REJECT')),
    confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    reason TEXT NOT NULL DEFAULT '',
    evidence_urls_json TEXT NOT NULL DEFAULT '[]',
    created_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS discovery_candidate (
    candidate_id TEXT PRIMARY KEY,
    workflow_run_id TEXT NOT NULL REFERENCES workflow_run(workflow_run_id) ON DELETE CASCADE,
    place_id TEXT NOT NULL UNIQUE,
    website_domain TEXT NOT NULL,
    company TEXT NOT NULL,
    website TEXT NOT NULL,
    address TEXT NOT NULL,
    country_code TEXT NOT NULL,
    types_json TEXT NOT NULL DEFAULT '[]',
    query TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('SEEN','RETRYABLE','VERIFIED','REJECTED')),
    attempts INTEGER NOT NULL DEFAULT 0,
    next_retry_at_utc TEXT,
    last_reason TEXT,
    last_seen_at_utc TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_discovery_retry ON discovery_candidate(status, next_retry_at_utc);
CREATE INDEX IF NOT EXISTS idx_discovery_domain ON discovery_candidate(website_domain);

CREATE TABLE IF NOT EXISTS lead_research (
    research_id TEXT PRIMARY KEY,
    lead_id TEXT NOT NULL REFERENCES leads(lead_id) ON DELETE CASCADE,
    website_domain TEXT NOT NULL,
    canonical_url TEXT NOT NULL,
    company_identity TEXT NOT NULL,
    business_summary TEXT NOT NULL DEFAULT '',
    services_json TEXT NOT NULL DEFAULT '[]',
    business_facts_json TEXT NOT NULL DEFAULT '[]',
    locations_json TEXT NOT NULL DEFAULT '[]',
    specialties_json TEXT NOT NULL DEFAULT '[]',
    website_signals_json TEXT NOT NULL DEFAULT '[]',
    customer_journey_signals_json TEXT NOT NULL DEFAULT '[]',
    ai_opportunity_signals_json TEXT NOT NULL DEFAULT '[]',
    important_public_text TEXT NOT NULL DEFAULT '',
    evidence_json TEXT NOT NULL DEFAULT '[]',
    research_timestamp_utc TEXT NOT NULL,
    research_status TEXT NOT NULL CHECK (research_status IN ('RESEARCHED','FAILED','PARTIAL_LLM_FAILURE')),
    research_version TEXT NOT NULL,
    error TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    next_retry_at_utc TEXT,
    created_at_utc TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_research_lead ON lead_research(lead_id, research_timestamp_utc);

CREATE TABLE IF NOT EXISTS sender_daily_state (
    sender_id TEXT NOT NULL,
    date_key TEXT NOT NULL,
    initials INTEGER NOT NULL DEFAULT 0,
    followups INTEGER NOT NULL DEFAULT 0,
    total INTEGER NOT NULL DEFAULT 0,
    failures INTEGER NOT NULL DEFAULT 0,
    authentication_failures INTEGER NOT NULL DEFAULT 0,
    temporary_provider_failures INTEGER NOT NULL DEFAULT 0,
    cooldown_until_utc TEXT,
    health_state TEXT NOT NULL DEFAULT 'HEALTHY' CHECK (health_state IN ('HEALTHY','DEGRADED','STOPPED','COOLDOWN')),
    last_successful_send_utc TEXT,
    PRIMARY KEY (sender_id, date_key)
);

CREATE TABLE IF NOT EXISTS suppression (
    email TEXT PRIMARY KEY,
    lead_id TEXT REFERENCES leads(lead_id) ON DELETE SET NULL,
    reason TEXT NOT NULL,
    created_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS outreach_batches (
    batch_id TEXT PRIMARY KEY,
    workflow_run_id TEXT NOT NULL REFERENCES workflow_run(workflow_run_id) ON DELETE CASCADE,
    batch_number INTEGER NOT NULL,
    batch_type TEXT NOT NULL CHECK (batch_type IN ('INITIAL','FOLLOWUP')),
    scheduled_at_utc TEXT NOT NULL,
    started_at_utc TEXT,
    completed_at_utc TEXT,
    status TEXT NOT NULL CHECK (status IN ('SCHEDULED','RUNNING','COMPLETED','PARTIAL','FAILED')),
    target_count INTEGER NOT NULL,
    attempted_count INTEGER NOT NULL DEFAULT 0,
    successful_count INTEGER NOT NULL DEFAULT 0,
    failed_count INTEGER NOT NULL DEFAULT 0,
    created_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL,
    UNIQUE(workflow_run_id,batch_number,batch_type)
);

CREATE TABLE IF NOT EXISTS outreach (
    outreach_id TEXT PRIMARY KEY,
    workflow_run_id TEXT NOT NULL REFERENCES workflow_run(workflow_run_id) ON DELETE CASCADE,
    batch_id TEXT REFERENCES outreach_batches(batch_id) ON DELETE SET NULL,
    lead_id TEXT NOT NULL REFERENCES leads(lead_id) ON DELETE CASCADE,
    sequence_type TEXT NOT NULL CHECK (sequence_type IN ('INITIAL','FOLLOWUP_1','FOLLOWUP_2','FOLLOWUP_3')),
    sequence_number INTEGER NOT NULL CHECK (sequence_number >= 1 AND sequence_number <= 3),
    sender_id TEXT NOT NULL,
    sender_email TEXT NOT NULL,
    email TEXT NOT NULL,
    subject TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL CHECK (status IN ('DRAFT','VALIDATED','QUEUED','SCHEDULED','SENDING','SENT','FAILED_RETRYABLE','FAILED_TERMINAL','CANCELLED','REVIEW_NEEDED')),
    scheduled_at_utc TEXT,
    attempted_at_utc TEXT,
    sent_at_utc TEXT,
    message_id TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    next_retry_at_utc TEXT,
    last_error TEXT,
    evidence_urls_json TEXT NOT NULL DEFAULT '[]',
    personalization_confidence REAL NOT NULL DEFAULT 0,
    body_hash TEXT,
    in_reply_to TEXT,
    references_text TEXT,
    created_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL,
    CHECK (
        (sequence_type='INITIAL' AND sequence_number=1) OR
        (sequence_type='FOLLOWUP_1' AND sequence_number=1) OR
        (sequence_type='FOLLOWUP_2' AND sequence_number=2) OR
        (sequence_type='FOLLOWUP_3' AND sequence_number=3)
    ),
    UNIQUE(lead_id,sequence_type,sequence_number),
    UNIQUE(message_id),
    UNIQUE(batch_id,sender_id)
);

CREATE INDEX IF NOT EXISTS idx_outreach_due ON outreach(status, scheduled_at_utc, next_retry_at_utc);
CREATE INDEX IF NOT EXISTS idx_outreach_lead ON outreach(lead_id, sequence_type, sequence_number);
CREATE INDEX IF NOT EXISTS idx_outreach_run ON outreach(workflow_run_id, sequence_type, status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_outreach_body_hash_active ON outreach(body_hash) WHERE status NOT IN ('CANCELLED','FAILED_TERMINAL');

CREATE TABLE IF NOT EXISTS mailbox_state (
    sender_id TEXT PRIMARY KEY,
    mailbox_identifier TEXT NOT NULL DEFAULT 'INBOX',
    provider_type TEXT NOT NULL DEFAULT 'imap',
    uidvalidity TEXT,
    last_processed_uid INTEGER NOT NULL DEFAULT 0,
    last_checked_at_utc TEXT,
    health_state TEXT NOT NULL DEFAULT 'HEALTHY'
);

CREATE TABLE IF NOT EXISTS inbound_message (
    inbound_message_id TEXT PRIMARY KEY,
    sender_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    in_reply_to TEXT,
    references_text TEXT NOT NULL DEFAULT '',
    received_at_utc TEXT NOT NULL,
    lead_id TEXT REFERENCES leads(lead_id) ON DELETE SET NULL,
    outreach_id TEXT REFERENCES outreach(outreach_id) ON DELETE SET NULL,
    event_type TEXT NOT NULL CHECK (event_type IN ('REPLY','HARD_BOUNCE','SOFT_BOUNCE','UNSUBSCRIBED','UNCLASSIFIED','REVIEW_NEEDED')),
    classification_confidence REAL NOT NULL CHECK (classification_confidence >= 0 AND classification_confidence <= 1),
    processing_status TEXT NOT NULL,
    processed_at_utc TEXT NOT NULL,
    subject TEXT NOT NULL DEFAULT '',
    from_email TEXT NOT NULL DEFAULT '',
    UNIQUE(sender_id,message_id)
);

CREATE INDEX IF NOT EXISTS idx_inbound_sender_received ON inbound_message(sender_id,received_at_utc);

CREATE TABLE IF NOT EXISTS event_log (
    event_id TEXT PRIMARY KEY,
    event_timestamp_utc TEXT NOT NULL,
    event_type TEXT NOT NULL,
    workflow_run_id TEXT REFERENCES workflow_run(workflow_run_id) ON DELETE CASCADE,
    lead_id TEXT REFERENCES leads(lead_id) ON DELETE SET NULL,
    outreach_id TEXT REFERENCES outreach(outreach_id) ON DELETE SET NULL,
    sender_id TEXT,
    batch_id TEXT REFERENCES outreach_batches(batch_id) ON DELETE SET NULL,
    sequence_type TEXT,
    status TEXT,
    reason TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_event_run ON event_log(workflow_run_id,event_type);
CREATE INDEX IF NOT EXISTS idx_event_lead ON event_log(lead_id,event_timestamp_utc);

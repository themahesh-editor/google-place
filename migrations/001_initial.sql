CREATE TABLE IF NOT EXISTS workflow_run (
    workflow_run_id TEXT PRIMARY KEY,
    campaign_run_id TEXT,
    started_at_utc TIMESTAMPTZ NOT NULL,
    ended_at_utc TIMESTAMPTZ,
    mode TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('RUNNING','SUCCESS','TARGET_NOT_REACHED','DRY_RUN','PREP_ONLY','FAILED')),
    reset_state BOOLEAN NOT NULL DEFAULT FALSE,
    target_new_initials INTEGER NOT NULL,
    metrics_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS campaign_run (
    campaign_run_id TEXT PRIMARY KEY,
    workflow_run_id TEXT NOT NULL,
    target_new_initials INTEGER NOT NULL CHECK (target_new_initials > 0),
    successful_initials INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL CHECK (status IN ('ACTIVE','SUCCESS','BLOCKED')),
    last_block_reason TEXT,
    created_at_utc TIMESTAMPTZ NOT NULL,
    updated_at_utc TIMESTAMPTZ NOT NULL,
    FOREIGN KEY (workflow_run_id) REFERENCES workflow_run(workflow_run_id) ON DELETE RESTRICT
);


CREATE TABLE IF NOT EXISTS lead (
    lead_id TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    company TEXT NOT NULL,
    website TEXT NOT NULL,
    website_domain TEXT NOT NULL,
    place_id TEXT NOT NULL UNIQUE,
    city TEXT NOT NULL DEFAULT '',
    region TEXT NOT NULL DEFAULT '',
    country_code TEXT NOT NULL,
    timezone TEXT NOT NULL,
    lead_source TEXT NOT NULL,
    scale_class TEXT NOT NULL CHECK (scale_class IN ('LOCAL','REGIONAL')),
    qualification_confidence DOUBLE PRECISION NOT NULL CHECK (qualification_confidence >= 0 AND qualification_confidence <= 1),
    qualification_reason TEXT NOT NULL DEFAULT '',
    discovery_facts TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL CHECK (status IN ('ELIGIBLE','RESEARCHING','RESEARCHED','QUEUED','ACTIVE','REPLIED','BOUNCED','UNSUBSCRIBED','COMPLETED','MANUAL_STOP','REVIEW_NEEDED')),
    suppression_reason TEXT,
    research_attempts INTEGER NOT NULL DEFAULT 0,
    next_research_at_utc TIMESTAMPTZ,
    created_at_utc TIMESTAMPTZ NOT NULL,
    updated_at_utc TIMESTAMPTZ NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_lead_email_ci ON lead(lower(email));
CREATE INDEX IF NOT EXISTS idx_lead_selection ON lead(status,created_at_utc);
CREATE INDEX IF NOT EXISTS idx_lead_domain ON lead(website_domain);

CREATE TABLE IF NOT EXISTS discovery_candidate (
    candidate_id TEXT PRIMARY KEY,
    place_id TEXT NOT NULL UNIQUE,
    company TEXT NOT NULL,
    website TEXT NOT NULL,
    address TEXT NOT NULL,
    country_code TEXT NOT NULL,
    types_json TEXT NOT NULL DEFAULT '[]',
    query TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('DISCOVERED','RETRYABLE','VERIFIED','REJECTED')),
    attempts INTEGER NOT NULL DEFAULT 0,
    next_retry_at_utc TIMESTAMPTZ,
    last_reason TEXT,
    last_seen_at_utc TIMESTAMPTZ NOT NULL,
    created_at_utc TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_candidate_queue ON discovery_candidate(status,next_retry_at_utc,created_at_utc);

CREATE TABLE IF NOT EXISTS lead_qualification (
    qualification_id TEXT PRIMARY KEY,
    lead_id TEXT NOT NULL REFERENCES lead(lead_id) ON DELETE CASCADE,
    workflow_run_id TEXT NOT NULL REFERENCES workflow_run(workflow_run_id) ON DELETE CASCADE,
    action TEXT NOT NULL CHECK (action IN ('KEEP','REJECT')),
    confidence DOUBLE PRECISION NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    reason TEXT NOT NULL,
    evidence_urls_json TEXT NOT NULL DEFAULT '[]',
    created_at_utc TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS research_cache (
    cache_id TEXT PRIMARY KEY,
    canonical_url TEXT NOT NULL,
    research_version TEXT NOT NULL,
    pages_json TEXT NOT NULL DEFAULT '[]',
    research_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL CHECK (status IN ('RESEARCHED','PARTIAL_LLM_FAILURE','FAILED')),
    error TEXT,
    created_at_utc TIMESTAMPTZ NOT NULL,
    updated_at_utc TIMESTAMPTZ NOT NULL,
    UNIQUE(canonical_url,research_version)
);

CREATE TABLE IF NOT EXISTS lead_research (
    research_id TEXT PRIMARY KEY,
    lead_id TEXT NOT NULL REFERENCES lead(lead_id) ON DELETE CASCADE,
    cache_id TEXT NOT NULL REFERENCES research_cache(cache_id) ON DELETE CASCADE,
    research_version TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('RESEARCHED','FAILED_RETRYABLE','FAILED_TERMINAL')),
    error TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    created_at_utc TIMESTAMPTZ NOT NULL,
    updated_at_utc TIMESTAMPTZ NOT NULL,
    UNIQUE(lead_id,research_version)
);
CREATE INDEX IF NOT EXISTS idx_research_lead ON lead_research(lead_id,updated_at_utc);

CREATE TABLE IF NOT EXISTS personalization_draft (
    draft_id TEXT PRIMARY KEY,
    lead_id TEXT NOT NULL REFERENCES lead(lead_id) ON DELETE CASCADE,
    campaign_run_id TEXT NOT NULL REFERENCES campaign_run(campaign_run_id) ON DELETE CASCADE,
    outreach_id TEXT NOT NULL UNIQUE,
    sequence_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('IN_PROGRESS','VALIDATED','REVIEW_NEEDED','RETRYABLE')),
    validation_error TEXT,
    repair_attempts INTEGER NOT NULL DEFAULT 0,
    created_at_utc TIMESTAMPTZ NOT NULL,
    updated_at_utc TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS sender_day (
    sender_id TEXT NOT NULL,
    date_key DATE NOT NULL,
    initials INTEGER NOT NULL DEFAULT 0,
    followups INTEGER NOT NULL DEFAULT 0,
    total INTEGER NOT NULL DEFAULT 0,
    failures INTEGER NOT NULL DEFAULT 0,
    authentication_failures INTEGER NOT NULL DEFAULT 0,
    temporary_provider_failures INTEGER NOT NULL DEFAULT 0,
    cooldown_until_utc TIMESTAMPTZ,
    health_state TEXT NOT NULL DEFAULT 'HEALTHY' CHECK (health_state IN ('HEALTHY','DEGRADED','COOLDOWN','STOPPED')),
    last_successful_send_utc TIMESTAMPTZ,
    updated_at_utc TIMESTAMPTZ NOT NULL,
    PRIMARY KEY(sender_id,date_key)
);

CREATE TABLE IF NOT EXISTS suppression (
    email TEXT PRIMARY KEY,
    lead_id TEXT REFERENCES lead(lead_id) ON DELETE SET NULL,
    reason TEXT NOT NULL,
    created_at_utc TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS outreach_batch (
    batch_id TEXT PRIMARY KEY,
    workflow_run_id TEXT NOT NULL REFERENCES workflow_run(workflow_run_id) ON DELETE CASCADE,
    campaign_run_id TEXT NOT NULL REFERENCES campaign_run(campaign_run_id) ON DELETE CASCADE,
    batch_number INTEGER NOT NULL,
    batch_type TEXT NOT NULL CHECK (batch_type IN ('INITIAL','FOLLOWUP')),
    status TEXT NOT NULL CHECK (status IN ('SCHEDULED','RUNNING','COMPLETED','PARTIAL','FAILED')),
    target_count INTEGER NOT NULL,
    attempted_count INTEGER NOT NULL DEFAULT 0,
    successful_count INTEGER NOT NULL DEFAULT 0,
    failed_count INTEGER NOT NULL DEFAULT 0,
    started_at_utc TIMESTAMPTZ,
    completed_at_utc TIMESTAMPTZ,
    created_at_utc TIMESTAMPTZ NOT NULL,
    updated_at_utc TIMESTAMPTZ NOT NULL,
    UNIQUE(workflow_run_id,batch_number,batch_type)
);

CREATE TABLE IF NOT EXISTS outreach (
    outreach_id TEXT PRIMARY KEY,
    workflow_run_id TEXT NOT NULL REFERENCES workflow_run(workflow_run_id) ON DELETE CASCADE,
    campaign_run_id TEXT NOT NULL REFERENCES campaign_run(campaign_run_id) ON DELETE CASCADE,
    batch_id TEXT REFERENCES outreach_batch(batch_id) ON DELETE SET NULL,
    lead_id TEXT NOT NULL REFERENCES lead(lead_id) ON DELETE CASCADE,
    sequence_type TEXT NOT NULL CHECK (sequence_type IN ('INITIAL','FOLLOWUP_1','FOLLOWUP_2','FOLLOWUP_3')),
    sequence_number INTEGER NOT NULL CHECK (sequence_number BETWEEN 1 AND 3),
    sender_id TEXT NOT NULL DEFAULT '',
    sender_email TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL,
    subject TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL CHECK (status IN ('DRAFT','VALIDATED','QUEUED','WAITING_DUE','SCHEDULED','SENDING','SENT','FAILED_RETRYABLE','FAILED_TERMINAL','CANCELLED','REVIEW_NEEDED')),
    scheduled_at_utc TIMESTAMPTZ,
    attempted_at_utc TIMESTAMPTZ,
    sent_at_utc TIMESTAMPTZ,
    smtp_message_id TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    next_retry_at_utc TIMESTAMPTZ,
    last_error TEXT,
    evidence_urls_json TEXT NOT NULL DEFAULT '[]',
    personalization_confidence DOUBLE PRECISION NOT NULL DEFAULT 0,
    in_reply_to TEXT,
    references_text TEXT,
    created_at_utc TIMESTAMPTZ NOT NULL,
    updated_at_utc TIMESTAMPTZ NOT NULL,
    CHECK ((sequence_type='INITIAL' AND sequence_number=1) OR (sequence_type='FOLLOWUP_1' AND sequence_number=1) OR (sequence_type='FOLLOWUP_2' AND sequence_number=2) OR (sequence_type='FOLLOWUP_3' AND sequence_number=3)),
    UNIQUE(lead_id,sequence_type),
    UNIQUE(smtp_message_id)
);
CREATE INDEX IF NOT EXISTS idx_outreach_send_queue ON outreach(campaign_run_id,sequence_type,status,scheduled_at_utc,next_retry_at_utc,created_at_utc);
CREATE INDEX IF NOT EXISTS idx_outreach_due_followups ON outreach(sequence_type,status,scheduled_at_utc,next_retry_at_utc);

CREATE TABLE IF NOT EXISTS retry_attempt (
    retry_id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    attempt_number INTEGER NOT NULL,
    error_class TEXT NOT NULL,
    error_message TEXT NOT NULL,
    created_at_utc TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_retry_entity ON retry_attempt(entity_type,entity_id,created_at_utc);

CREATE TABLE IF NOT EXISTS mailbox_state (
    sender_id TEXT PRIMARY KEY,
    mailbox_identifier TEXT NOT NULL DEFAULT 'INBOX',
    provider_type TEXT NOT NULL DEFAULT 'imap',
    uidvalidity TEXT,
    last_processed_uid BIGINT NOT NULL DEFAULT 0,
    last_checked_at_utc TIMESTAMPTZ,
    health_state TEXT NOT NULL DEFAULT 'HEALTHY' CHECK (health_state IN ('HEALTHY','DEGRADED','STOPPED'))
);

CREATE TABLE IF NOT EXISTS inbound_message (
    inbound_message_id TEXT PRIMARY KEY,
    sender_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    in_reply_to TEXT NOT NULL DEFAULT '',
    references_text TEXT NOT NULL DEFAULT '',
    received_at_utc TIMESTAMPTZ NOT NULL,
    from_email TEXT NOT NULL DEFAULT '',
    subject TEXT NOT NULL DEFAULT '',
    event_type TEXT NOT NULL CHECK (event_type IN ('REPLY','HARD_BOUNCE','SOFT_BOUNCE','UNSUBSCRIBED','UNCLASSIFIED','REVIEW_NEEDED')),
    classification_confidence DOUBLE PRECISION NOT NULL CHECK (classification_confidence BETWEEN 0 AND 1),
    processing_status TEXT NOT NULL,
    processed_at_utc TIMESTAMPTZ NOT NULL,
    lead_id TEXT REFERENCES lead(lead_id) ON DELETE SET NULL,
    outreach_id TEXT REFERENCES outreach(outreach_id) ON DELETE SET NULL,
    UNIQUE(sender_id,message_id)
);
CREATE INDEX IF NOT EXISTS idx_inbound_sender_uidless ON inbound_message(sender_id,received_at_utc);

CREATE TABLE IF NOT EXISTS automation_cursor (
    cursor_key TEXT PRIMARY KEY,
    last_triggered_at_utc TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS event_log (
    event_id TEXT PRIMARY KEY,
    event_timestamp_utc TIMESTAMPTZ NOT NULL,
    event_type TEXT NOT NULL,
    workflow_run_id TEXT REFERENCES workflow_run(workflow_run_id) ON DELETE CASCADE,
    campaign_run_id TEXT REFERENCES campaign_run(campaign_run_id) ON DELETE CASCADE,
    lead_id TEXT REFERENCES lead(lead_id) ON DELETE SET NULL,
    outreach_id TEXT REFERENCES outreach(outreach_id) ON DELETE SET NULL,
    sender_id TEXT,
    batch_id TEXT REFERENCES outreach_batch(batch_id) ON DELETE SET NULL,
    sequence_type TEXT,
    status TEXT,
    reason TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_event_run ON event_log(workflow_run_id,event_type);
CREATE INDEX IF NOT EXISTS idx_event_lead ON event_log(lead_id,event_timestamp_utc);

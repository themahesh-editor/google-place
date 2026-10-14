CREATE SCHEMA IF NOT EXISTS attachai;
SET search_path TO attachai, public;
CREATE TABLE IF NOT EXISTS schema_version(version integer PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE campaign (
 id text PRIMARY KEY, target integer NOT NULL CHECK(target>0), kind text NOT NULL CHECK(kind IN ('real','dry')),
 status text NOT NULL CHECK(status IN ('active','blocked','complete','dry_run')), created_at timestamptz NOT NULL DEFAULT now(), completed_at timestamptz, reason text
);
CREATE UNIQUE INDEX one_active_real_campaign ON campaign(kind) WHERE kind='real' AND status IN ('active','blocked');
CREATE TABLE invocation (
 id text PRIMARY KEY, campaign_id text REFERENCES campaign(id), mode text NOT NULL, status text NOT NULL DEFAULT 'running',
 started_at timestamptz NOT NULL DEFAULT now(), finished_at timestamptz, metrics jsonb NOT NULL DEFAULT '{}', error text
);
CREATE TABLE sender (
 id text PRIMARY KEY, email text NOT NULL UNIQUE, health text NOT NULL DEFAULT 'HEALTHY' CHECK(health IN ('HEALTHY','DEGRADED','COOLDOWN','STOPPED')),
 cooldown_until timestamptz, last_error text, updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE candidate (
 id text PRIMARY KEY, place_id text NOT NULL UNIQUE, payload jsonb NOT NULL, status text NOT NULL DEFAULT 'new',
 attempts integer NOT NULL DEFAULT 0, next_retry timestamptz, lease_until timestamptz, last_error text,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE research_cache (
 id text PRIMARY KEY, website text NOT NULL, version text NOT NULL, payload jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(website,version)
);
CREATE TABLE lead (
 id text PRIMARY KEY, candidate_id text NOT NULL REFERENCES candidate(id), email text NOT NULL UNIQUE CHECK(email=lower(trim(email))),
 name text NOT NULL, website text NOT NULL, qualification jsonb NOT NULL, research_id text REFERENCES research_cache(id),
 status text NOT NULL DEFAULT 'new', attempts integer NOT NULL DEFAULT 0, next_retry timestamptz, lease_until timestamptz,
 last_error text, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE draft (
 id text PRIMARY KEY, lead_id text NOT NULL REFERENCES lead(id), sequence integer NOT NULL CHECK(sequence BETWEEN 0 AND 3),
 research_id text NOT NULL REFERENCES research_cache(id), payload jsonb NOT NULL, valid boolean NOT NULL, errors jsonb NOT NULL,
 attempts integer NOT NULL, created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(lead_id,sequence)
);
CREATE TABLE batch (
 id text PRIMARY KEY, invocation_id text NOT NULL REFERENCES invocation(id), number integer NOT NULL,
 kind text NOT NULL, planned integer NOT NULL CHECK(planned BETWEEN 1 AND 10), attempted integer NOT NULL DEFAULT 0,
 successful integer NOT NULL DEFAULT 0, failed integer NOT NULL DEFAULT 0, status text NOT NULL DEFAULT 'planned',
 started_at timestamptz NOT NULL DEFAULT now(), finished_at timestamptz, UNIQUE(invocation_id,number)
);
CREATE TABLE message (
 id text PRIMARY KEY, lead_id text NOT NULL REFERENCES lead(id), campaign_id text NOT NULL REFERENCES campaign(id),
 sequence integer NOT NULL CHECK(sequence BETWEEN 0 AND 3), predecessor_id text REFERENCES message(id),
 status text NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','sending','sent','retry','review','terminal','cancelled')),
 subject text, body text, sender_id text REFERENCES sender(id), message_id text UNIQUE, batch_id text REFERENCES batch(id),
 in_reply_to text, refs jsonb NOT NULL DEFAULT '[]', due_at timestamptz NOT NULL DEFAULT now(),
 attempts integer NOT NULL DEFAULT 0, draft_attempts integer NOT NULL DEFAULT 0, next_retry timestamptz, lease_until timestamptz, sent_at timestamptz,
 last_error text, error_kind text, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(lead_id,sequence), CHECK(sequence=0 OR predecessor_id IS NOT NULL),
 CHECK(status<>'sent' OR (sent_at IS NOT NULL AND sender_id IS NOT NULL AND message_id IS NOT NULL))
);
CREATE TABLE attempt (
 id bigserial PRIMARY KEY, message_id text NOT NULL REFERENCES message(id), number integer NOT NULL,
 sender_id text NOT NULL REFERENCES sender(id), status text NOT NULL, started_at timestamptz NOT NULL DEFAULT now(),
 finished_at timestamptz, error_kind text, error text, UNIQUE(message_id,number)
);
CREATE TABLE suppression (
 email text PRIMARY KEY, kind text NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE mailbox_cursor (
 sender_id text PRIMARY KEY REFERENCES sender(id), uidvalidity text NOT NULL, last_uid bigint NOT NULL,
 updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE inbound (
 id text PRIMARY KEY, sender_id text NOT NULL REFERENCES sender(id), event_key text NOT NULL, uidvalidity text NOT NULL, uid bigint NOT NULL,
 kind text NOT NULL, email text, message_ids jsonb NOT NULL, occurred_at timestamptz NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(sender_id,uidvalidity,uid), UNIQUE(sender_id,event_key)
);
CREATE TABLE schedule_slot (
 kind text NOT NULL, slot text NOT NULL, invocation_id text REFERENCES invocation(id), created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(kind,slot)
);
CREATE TABLE event (
 id bigserial PRIMARY KEY, invocation_id text REFERENCES invocation(id), kind text NOT NULL, payload jsonb NOT NULL DEFAULT '{}', created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE discovery_cursor (
 query text PRIMARY KEY, page_token text, exhausted boolean NOT NULL DEFAULT false, updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX candidate_queue ON candidate(status,next_retry);
CREATE INDEX lead_queue ON lead(status,next_retry);
CREATE INDEX message_queue ON message(status,due_at,next_retry);
CREATE INDEX message_campaign ON message(campaign_id,sequence,status);
CREATE INDEX inbound_correlation ON inbound USING gin(message_ids);
CREATE OR REPLACE FUNCTION enforce_sequence() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE p message;
BEGIN
 IF NEW.sequence>0 THEN
  SELECT * INTO p FROM message WHERE id=NEW.predecessor_id;
  IF p.id IS NULL OR p.lead_id<>NEW.lead_id OR p.campaign_id<>NEW.campaign_id OR p.sequence<>NEW.sequence-1 OR p.status<>'sent' OR p.sender_id IS DISTINCT FROM NEW.sender_id OR p.message_id IS DISTINCT FROM NEW.in_reply_to OR NEW.refs IS DISTINCT FROM (p.refs || jsonb_build_array(p.message_id)) THEN
   RAISE EXCEPTION 'Invalid outreach predecessor or sender';
  END IF;
 END IF;
 IF NEW.status='sending' AND EXISTS(SELECT 1 FROM suppression s JOIN lead l ON l.email=s.email WHERE l.id=NEW.lead_id) THEN
  RAISE EXCEPTION 'Suppressed lead cannot enter sending';
 END IF;
 IF TG_OP='UPDATE' AND OLD.status='sent' AND (NEW.status<>'sent' OR NEW.sender_id IS DISTINCT FROM OLD.sender_id OR NEW.message_id IS DISTINCT FROM OLD.message_id OR NEW.lead_id IS DISTINCT FROM OLD.lead_id OR NEW.sequence IS DISTINCT FROM OLD.sequence OR NEW.campaign_id IS DISTINCT FROM OLD.campaign_id OR NEW.sent_at IS DISTINCT FROM OLD.sent_at OR NEW.subject IS DISTINCT FROM OLD.subject OR NEW.body IS DISTINCT FROM OLD.body OR NEW.predecessor_id IS DISTINCT FROM OLD.predecessor_id OR NEW.in_reply_to IS DISTINCT FROM OLD.in_reply_to OR NEW.refs IS DISTINCT FROM OLD.refs) THEN
  RAISE EXCEPTION 'Successful delivery is immutable';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER message_sequence_guard BEFORE INSERT OR UPDATE ON message FOR EACH ROW EXECUTE FUNCTION enforce_sequence();
INSERT INTO schema_version(version) VALUES(1);

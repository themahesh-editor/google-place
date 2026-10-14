from __future__ import annotations

import json
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from .db import j
from .providers import ProviderError, normalize_email, normalize_url, stable_id, validate_draft


def log(kind, **payload):
    print(json.dumps({'milestone':kind, **payload}, default=str, sort_keys=True), flush=True)


class Engine:
    def __init__(self, config, store, secrets, discovery, research, llm, smtp, mailbox, sleep=time.sleep):
        self.c, self.db, self.secrets = config, store, secrets
        self.discovery, self.research, self.llm, self.smtp, self.mailbox = discovery,research,llm,smtp,mailbox
        self.sleep = sleep
        self.metrics = Counter()
        for key in ('raw_candidates','deduplicated_candidates','qualified','qualification_rejected','researched','research_failed','personalized','personalization_rejected','ready','queued','attempted','successful_initial_sends','retryable_failures','terminal_failures','followups_generated','followups_sent','followup_failures','replies','bounces','soft_bounces','unsubscribes','suppressed','mailbox_failures','places_requests'):
            self.metrics[key] = 0
        self.start_time = time.monotonic()
        self.iid = self.cid = None
        self.batch_no = 0
        self.exhausted = set()
        self.discovery_stop_reason = None

    @property
    def data(self):
        return self.c.data

    @property
    def delays(self):
        return self.data['followups']['delays_seconds']

    def run(self, reset=False, slots=None):
        # Caller holds session advisory lock before migration and every destructive operation.
        if not self.db.locked:
            raise RuntimeError('Execution requires database lock')
        if reset:
            self.db.reset()
        recovery = self.db.reconcile()
        self.db.register_senders(self.secrets.senders)
        # Reconcile successful stages independently, including crash after acceptance transaction.
        for row in self.db.all("SELECT * FROM message WHERE status='sent' AND sequence<3"):
            self.db.ensure_next(row,self.delays)
        real = self.c.send_enabled and not self.c.dry_run
        mode = 'FULL' if self.c.process_followups and self.c.process_new_outreach else 'FOLLOWUPS_ONLY' if self.c.process_followups else 'NEW_OUTREACH_ONLY' if self.c.process_new_outreach else 'RECOVERY'
        self.iid,campaign,resumed = self.db.start(self.c.target,real,mode,self.c.process_new_outreach)
        self.cid = campaign['id'] if campaign else None
        if slots:
            for kind,slot in slots.items():
                self.db.execute('INSERT INTO schedule_slot(kind,slot,invocation_id) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING', [kind,slot,self.iid])
        discovery_reset_count = 0
        if campaign and not resumed:
            self.db.execute('UPDATE discovery_cursor SET exhausted=false,page_token=NULL WHERE exhausted=true')
        elif campaign and resumed and real and self.c.process_new_outreach:
            # A blocked campaign must remain resumable after all pagination tokens
            # have been consumed. Restart a new discovery cycle only when every
            # currently configured query has a durable exhausted cursor. This
            # avoids both a zero-request dead-end and resetting partially paged
            # queries unnecessarily.
            queries = list(dict.fromkeys(self.data['discovery']['queries']))
            cursor_rows = self.db.all(
                'SELECT query, exhausted FROM discovery_cursor WHERE query = ANY(%s)',
                [queries],
            )
            cursor_state = {row['query']: row['exhausted'] for row in cursor_rows}
            if queries and all(cursor_state.get(query, False) for query in queries):
                reset_count = self.db.execute(
                    'UPDATE discovery_cursor SET exhausted=false,page_token=NULL,updated_at=now() '
                    'WHERE query = ANY(%s) AND exhausted=true',
                    [queries],
                ).rowcount
                if reset_count:
                    discovery_reset_count = reset_count
        log('START', invocation=self.iid,campaign=self.cid,resumed=resumed,target=self.c.target,mode=mode,send_enabled=real,recovery=recovery)
        self.db.event(self.iid,'start',{'resumed':resumed,'target':self.c.target,'mode':mode,'send_enabled':real})
        if discovery_reset_count:
            log('DISCOVERY_CYCLE_RESET', queries=discovery_reset_count,
                reason='resumed_campaign_all_queries_exhausted')
            self.db.event(self.iid, 'discovery_cycle_reset',
                          {'queries': discovery_reset_count, 'reason': 'resumed_campaign_all_queries_exhausted'})
        reason = None
        try:
            self.sync_mailbox()
            if self.c.process_followups:
                self.followups(real)
            if self.c.process_new_outreach:
                reason = self.initials(real)
            successful = self.db.count_sent(self.cid) if self.cid else 0
            if not real:
                status,code = 'DRY_RUN' if self.c.dry_run else 'PREPARED',0
                if self.cid:
                    self.db.execute("UPDATE campaign SET status='dry_run',completed_at=now(),reason=%s WHERE id=%s", [reason,self.cid])
            elif self.c.process_new_outreach and successful < self.c.target:
                status,code = 'TARGET_NOT_REACHED',2
                self.db.execute("UPDATE campaign SET status='blocked',reason=%s WHERE id=%s", [reason,self.cid])
            else:
                status,code = ('PARTIAL_FOLLOWUPS',2) if self.metrics['followup_failures'] else ('SUCCESS',0)
                if self.cid:
                    self.db.execute("UPDATE campaign SET status='complete',completed_at=now(),reason=NULL WHERE id=%s", [self.cid])
            result = {**dict(self.metrics),**self.db.metrics(self.cid),'remaining_target':max(0,self.c.target-successful) if self.cid and real else None,
                      'run_status':status,'reason':reason,'duration_seconds':round(time.monotonic()-self.start_time,3),'invocation_id':self.iid,'campaign_id':self.cid}
            self.db.execute('UPDATE invocation SET status=%s,finished_at=now(),metrics=%s WHERE id=%s', [status,j(result),self.iid])
            self.db.event(self.iid,'final',result)
            log('FINAL_SUMMARY',**result)
            return code,result
        except BaseException:
            # Never expose unexpected exception text (could contain credentials).
            self.db.execute("UPDATE invocation SET status='failed',finished_at=now(),error='Unexpected execution failure; see exception type in workflow' WHERE id=%s", [self.iid])
            raise

    def bounded_workers(self, items, fn):
        with ThreadPoolExecutor(max_workers=self.data['outreach']['max_concurrency']) as pool:
            futures = {pool.submit(fn,item):item for item in items}
            for f in as_completed(futures):
                item = futures[f]
                try:
                    yield item,f.result(),None
                except ProviderError as exc:
                    yield item,None,exc
                except Exception:
                    yield item,None,ProviderError('terminal','Unexpected provider adapter failure')

    def retry_delay(self, attempt):
        r = self.data['retry']
        return min(r['max_seconds'], r['base_seconds'] * 2**max(0,attempt-1))

    def fail_work(self, table, row, error):
        attempts = row['attempts']
        retry = (error.kind == 'temporary' or (table=='lead' and error.kind=='invalid')) and attempts < self.data['retry']['max_attempts']
        updates = {
            'candidate': "UPDATE candidate SET status=%s,next_retry=now()+(%s*interval '1 second'),lease_until=NULL,last_error=%s,updated_at=now() WHERE id=%s",
            'lead': "UPDATE lead SET status=%s,next_retry=now()+(%s*interval '1 second'),lease_until=NULL,last_error=%s,updated_at=now() WHERE id=%s",
        }
        if table not in updates:
            raise ValueError('Unsupported work table for failure handling')
        self.db.execute(
            updates[table],
            ['retry' if retry else 'rejected', self.retry_delay(attempts),
             error.safe_message, row['id']],
        )
        self.metrics['retryable_failures' if retry else 'terminal_failures'] += 1
        self.db.event(self.iid,table+'_failure',{'id':row['id'],'kind':error.kind,'retryable':retry,'error':error.safe_message})

    def sync_mailbox(self):
        if not self.data['mailbox']['enabled']:
            return
        for sender in self.secrets.senders:
            cursor = self.db.one('SELECT * FROM mailbox_cursor WHERE sender_id=%s', [sender.id])
            try:
                result = self.mailbox.sync(sender,cursor)
                with self.db.tx():
                    for ev in result['events']:
                        inserted = self.db.execute('INSERT INTO inbound(id,sender_id,event_key,uidvalidity,uid,kind,email,message_ids,occurred_at) '
                            'VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING id',
                            [stable_id('inbound',sender.id,ev['key']),sender.id,ev['key'],result['uidvalidity'],ev['uid'],ev['kind'],ev.get('email'),j(ev.get('message_ids',[])),ev['occurred_at']]).fetchone()
                        if not inserted:
                            continue
                        # Only suppress correlated outgoing conversations or a known direct opt-out/reply sender.
                        leads = self.db.all('SELECT DISTINCT l.email FROM lead l JOIN message m ON m.lead_id=l.id WHERE m.sender_id=%s AND m.message_id=ANY(%s)', [sender.id,ev.get('message_ids',[])])
                        if ev.get('email') and ev['kind'] in ('reply','unsubscribe'):
                            leads += self.db.all("SELECT DISTINCT l.email FROM lead l JOIN message m ON m.lead_id=l.id WHERE l.email=%s AND m.sender_id=%s AND m.status='sent'", [normalize_email(ev['email']),sender.id])
                        if ev['kind'] in ('reply','hard_bounce','unsubscribe'):
                            for email in {l['email'] for l in leads}:
                                self.db.suppress(email,ev['kind'])
                                self.metrics['suppressed'] += 1
                        self.metrics[{'reply':'replies','hard_bounce':'bounces','soft_bounce':'soft_bounces','unsubscribe':'unsubscribes'}.get(ev['kind'],'unknown_inbound')] += 1
                    self.db.execute('INSERT INTO mailbox_cursor(sender_id,uidvalidity,last_uid) VALUES(%s,%s,%s) '
                        'ON CONFLICT(sender_id) DO UPDATE SET uidvalidity=EXCLUDED.uidvalidity,last_uid=EXCLUDED.last_uid,updated_at=now()',
                        [sender.id,result['uidvalidity'],result['last_uid']])
                    self.db.execute("UPDATE sender SET health='HEALTHY',last_error=NULL WHERE id=%s AND health='DEGRADED'", [sender.id])
                log('MAILBOX_SYNC',sender=sender.id,events=len(result['events']),last_uid=result['last_uid'])
            except Exception:
                self.db.execute("UPDATE sender SET health='DEGRADED',last_error='Mailbox sync failed' WHERE id=%s AND health NOT IN ('STOPPED','COOLDOWN')", [sender.id])
                self.metrics['mailbox_failures'] += 1
                self.db.event(self.iid,'mailbox_failure',{'sender':sender.id})

    def followups(self, real):
        rows = self.db.all("SELECT m.* FROM message m WHERE m.sequence>0 AND m.status IN ('queued','retry') AND m.due_at<=now() AND (m.next_retry IS NULL OR m.next_retry<=now()) AND NOT EXISTS(SELECT 1 FROM suppression s JOIN lead l ON l.email=s.email WHERE l.id=m.lead_id) ORDER BY m.due_at LIMIT %s", [self.data['followups']['max_per_run']])
        # Snapshot IDs prevents newly unlocked stages from advancing in the same run.
        ids = [r['id'] for r in rows]
        while ids and self.within_runtime():
            pending = self.db.all("SELECT * FROM message WHERE id=ANY(%s) AND status IN ('queued','retry') AND (next_retry IS NULL OR next_retry<=now()) ORDER BY due_at",[ids])
            unprepared = [r for r in pending if not r['body']][:self.data['outreach']['max_concurrency']]
            work = []
            for row in unprepared:
                if row['draft_attempts']>=self.data['retry']['max_attempts']:
                    self.db.execute("UPDATE message SET status='review',last_error='Follow-up draft retry budget exhausted' WHERE id=%s",[row['id']])
                    continue
                row = self.db.one("UPDATE message SET draft_attempts=draft_attempts+1,lease_until=now()+interval '5 minutes' WHERE id=%s RETURNING *",[row['id']])
                row['_lead'] = self.db.one('SELECT * FROM lead WHERE id=%s',[row['lead_id']])
                row['_research'] = self.db.one('SELECT * FROM research_cache WHERE id=%s',[row['_lead']['research_id']])
                row['_history'] = self.db.all("SELECT subject,body,message_id,sequence,sent_at FROM message WHERE lead_id=%s AND status='sent' ORDER BY sequence",[row['lead_id']])
                work.append(row)
            def generate(row):
                if not row['_research']:
                    raise ProviderError('terminal','No cached research for follow-up')
                return self.llm.draft(row['_lead'],row['_research']['payload'],row['sequence'],row['_history'])
            for row,draft,error in self.bounded_workers(work,generate):
                if not error:
                    errors = validate_draft(draft,row['_research']['payload'])
                    self.save_draft(row['_lead'],row['_research'],row['sequence'],draft,errors,row['draft_attempts'])
                    if errors:
                        error = ProviderError('invalid','Follow-up draft failed grounded evidence validation')
                if error:
                    retry = error.kind in ('temporary','invalid') and row['draft_attempts']<self.data['retry']['max_attempts']
                    self.db.execute("UPDATE message SET status=%s,next_retry=now()+(%s*interval '1 second'),lease_until=NULL,last_error=%s,error_kind=%s WHERE id=%s",['retry' if retry else 'review',self.retry_delay(row['draft_attempts']),error.safe_message,error.kind,row['id']])
                    self.db.event(self.iid,'followup_draft_failure',{'message':row['id'],'kind':error.kind,'retryable':retry})
                else:
                    self.db.execute('UPDATE message SET subject=%s,body=%s,lease_until=NULL,next_retry=NULL,last_error=NULL WHERE id=%s',[draft['subject'],draft['body'],row['id']])
                    self.metrics['followups_generated'] += 1
            ready = self.db.all("SELECT * FROM message WHERE id=ANY(%s) AND status IN ('queued','retry') AND body IS NOT NULL AND (next_retry IS NULL OR next_retry<=now()) ORDER BY due_at",[ids])
            if ready and real:
                if self.send_batch(ready,'followup'):
                    continue
                if self.wait_for_sender():
                    continue
                # Unhealthy original senders do not block preparation of other due stages.
                if not unprepared:
                    break
            if unprepared:
                continue
            future = self.db.one("SELECT min(next_retry) AS at FROM message WHERE id=ANY(%s) AND status='retry' AND (body IS NULL OR %s)",[ids,real])['at']
            if future and self.wait_until(future):
                continue
            break
        if real:
            failed = self.db.one("SELECT count(*) AS n FROM message WHERE id=ANY(%s) AND status NOT IN ('sent','cancelled')",[ids])['n']
            self.metrics['followup_failures'] += failed
        log('FOLLOWUP_RESULTS',due=len(rows),sent=self.metrics['followups_sent'])

    def save_draft(self, lead, research, seq, draft, errors, attempts):
        self.db.execute('INSERT INTO draft(id,lead_id,sequence,research_id,payload,valid,errors,attempts) VALUES(%s,%s,%s,%s,%s,%s,%s,%s) '
            'ON CONFLICT(lead_id,sequence) DO UPDATE SET payload=EXCLUDED.payload,valid=EXCLUDED.valid,errors=EXCLUDED.errors,attempts=EXCLUDED.attempts',
            [stable_id('draft',lead['id'],seq),lead['id'],seq,research['id'],j(draft),not errors,j(errors),attempts])

    def within_runtime(self):
        return time.monotonic()-self.start_time < self.data['limits']['max_runtime_seconds']

    def initials(self, real):
        target = self.c.target
        dry_ready_target = target
        while self.within_runtime():
            remaining = target-self.db.count_sent(self.cid)
            if remaining<=0:
                return None
            # Reserve slots for unknown SMTP outcomes. They are NOT successes, but replacing
            # them could overshoot the exact target when an operator later confirms delivery.
            reviews = self.db.one("SELECT count(*) AS n FROM message WHERE campaign_id=%s AND sequence=0 AND status='review'",[self.cid])['n']
            send_capacity = max(0,remaining-reviews) if real else remaining
            if real and not send_capacity:
                return f'{reviews} ambiguous initial delivery(s) reserve remaining target slots; operator verification required'
            ready = self.db.all("SELECT * FROM message WHERE campaign_id=%s AND sequence=0 AND status IN ('queued','retry') AND (next_retry IS NULL OR next_retry<=now()) ORDER BY created_at LIMIT %s",[self.cid,min(10,send_capacity)])
            ready_total = self.db.one("SELECT count(*) AS n FROM message WHERE campaign_id=%s AND sequence=0 AND status IN ('queued','retry')",[self.cid])['n']
            if not real and ready_total>=dry_ready_target:
                return 'Prepared only; no messages sent'
            if ready and real:
                attempted = self.send_batch(ready,'initial')
                if attempted:
                    continue
                if self.wait_for_sender():
                    continue
                return 'No healthy eligible senders or configured sending limits/window prevent sends'

            need = max(1, send_capacity-ready_total)
            quantity = min(100,max(self.data['outreach']['batch_size'],int(need*self.data['discovery']['buffer_ratio'])))
            candidates = self.db.all("SELECT * FROM candidate WHERE status IN ('new','retry') AND (next_retry IS NULL OR next_retry<=now()) ORDER BY created_at LIMIT %s",[quantity])
            leads = self.db.all("SELECT * FROM lead WHERE status IN ('new','retry') AND (next_retry IS NULL OR next_retry<=now()) AND NOT EXISTS(SELECT 1 FROM message m WHERE m.lead_id=lead.id AND sequence=0) AND NOT EXISTS(SELECT 1 FROM suppression s WHERE s.email=lead.email) ORDER BY created_at LIMIT %s",[quantity])
            progress = False
            if candidates:
                self.prepare_candidates(candidates)
                progress = True
            if leads:
                self.prepare_leads(leads)
                progress = True
            if progress:
                continue
            if self.discover():
                continue
            # Once discovery exhausted, honor finite actual provider retries; never empty-spin.
            futures = self.db.one("SELECT min(at) AS at FROM (SELECT next_retry AS at FROM candidate WHERE status='retry' UNION ALL SELECT next_retry FROM lead WHERE status='retry' UNION ALL SELECT next_retry FROM message WHERE campaign_id=%s AND sequence=0 AND status='retry') x",[self.cid])['at']
            if futures and self.wait_until(futures):
                continue
            reviews = self.db.one("SELECT count(*) AS n FROM message WHERE campaign_id=%s AND status='review'",[self.cid])['n']
            stop_reason = self.discovery_stop_reason or 'No eligible new inventory was found'
            return f'{stop_reason}; {reviews} delivery(s) require review'
        return 'Configured runtime deadline reached; durable campaign will resume'

    def discover(self):
        cfg = self.data['discovery']
        self.discovery_stop_reason = None
        if self.metrics['places_requests'] >= cfg['max_requests_per_run']:
            self.discovery_stop_reason = 'Google Places per-run request budget exhausted'
            return False
        if self.metrics['raw_candidates'] >= cfg['max_candidates_per_run']:
            self.discovery_stop_reason = 'Google Places per-run candidate budget exhausted'
            return False
        had_eligible_query = False
        for query in dict.fromkeys(cfg['queries']):
            if query in self.exhausted:
                continue
            row = self.db.one('SELECT * FROM discovery_cursor WHERE query=%s',[query])
            if row and row['exhausted']:
                self.exhausted.add(query)
                continue
            had_eligible_query = True
            failures = 0
            while failures < self.data['retry']['max_attempts'] and self.within_runtime() and self.metrics['places_requests']<cfg['max_requests_per_run']:
                self.metrics['places_requests'] += 1
                try:
                    result = self.discovery.search(query,row['page_token'] if row else None)
                    token = result.get('next_page_token')
                    count = 0
                    with self.db.tx():
                        for item in result['candidates']:
                            if self.metrics['raw_candidates']>=cfg['max_candidates_per_run']:
                                break
                            self.metrics['raw_candidates'] += 1
                            # API queries may duplicate locations; business identity is Place ID, not domain.
                            if not item.get('place_id'):
                                continue
                            inserted = self.db.execute('INSERT INTO candidate(id,place_id,payload) VALUES(%s,%s,%s) ON CONFLICT(place_id) DO NOTHING RETURNING id',[stable_id('candidate',item['place_id']),item['place_id'],j(item)]).fetchone()
                            if inserted:
                                count += 1
                        self.db.execute('INSERT INTO discovery_cursor(query,page_token,exhausted) VALUES(%s,%s,%s) ON CONFLICT(query) DO UPDATE SET page_token=EXCLUDED.page_token,exhausted=EXCLUDED.exhausted,updated_at=now()', [query,token,not bool(token)])
                    self.metrics['deduplicated_candidates'] += count
                    self.db.event(self.iid,'discovery_progress',{'raw':len(result['candidates']),'new':count,'requests':self.metrics['places_requests']})
                    log('DISCOVERY_PROGRESS',raw=len(result['candidates']),new=count,requests=self.metrics['places_requests'])
                    if not token:
                        self.exhausted.add(query)
                    # A consumed page is progress even if duplicates: move to next page/query.
                    return True
                except ProviderError as exc:
                    failures += 1
                    self.db.event(self.iid,'discovery_failure',{'kind':exc.kind,'error':exc.safe_message,'attempt':failures})
                    if exc.kind == 'auth':
                        # Credentials are provider-wide; another text query cannot
                        # repair authorization, so fail fast and preserve cursors.
                        self.discovery_stop_reason = 'Google Places authorization failed'
                        return False
                    if exc.kind!='temporary':
                        break
                    if failures<self.data['retry']['max_attempts']:
                        self.sleep(self.retry_delay(failures))
            self.exhausted.add(query)
        if self.metrics['places_requests'] >= cfg['max_requests_per_run']:
            self.discovery_stop_reason = 'Google Places per-run request budget exhausted'
        elif self.metrics['raw_candidates'] >= cfg['max_candidates_per_run']:
            self.discovery_stop_reason = 'Google Places per-run candidate budget exhausted'
        elif not had_eligible_query:
            self.discovery_stop_reason = 'All configured Google Places queries are exhausted'
        else:
            self.discovery_stop_reason = 'All eligible Google Places queries failed after bounded retries'
        return False

    def prepare_candidates(self, rows):
        work = []
        for row in rows:
            payload = row['payload']
            cfg = self.data['discovery']
            if not payload.get('website') or (payload.get('rating') or 0)<cfg['min_rating'] or (payload.get('reviews') or 0)<cfg['min_reviews']:
                self.db.execute("UPDATE candidate SET status='rejected',last_error='Missing website or quality below configured thresholds' WHERE id=%s",[row['id']])
                self.metrics['qualification_rejected'] += 1
                continue
            claimed = self.db.one("UPDATE candidate SET status='working',attempts=attempts+1,lease_until=now()+interval '5 minutes' WHERE id=%s RETURNING *",[row['id']])
            work.append(claimed)
        # Group contacts/locations sharing a website, without collapsing their identities.
        # One network crawl per canonical site/version, even within the same concurrent wave.
        grouped = {}
        for row in work:
            try:
                url = normalize_url(row['payload']['website'])
            except ProviderError as exc:
                self.fail_work('candidate',row,exc)
                self.metrics['research_failed'] += 1
                continue
            grouped.setdefault(url,[]).append(row)
        tasks = []
        for url,members in grouped.items():
            cache = self.db.one('SELECT payload FROM research_cache WHERE website=%s AND version=%s',[url,self.data['research']['version']])
            tasks.append({'url':url,'members':members,'cache':cache['payload'] if cache else None})
        def crawl(task):
            return task['cache'] or self.research.crawl(task['members'][0]['payload']['website'])
        def completed():
            for task,payload,error in self.bounded_workers(tasks,crawl):
                for row in task['members']:
                    yield row,(task['url'],payload),error
        for row,result,error in completed():
            if error:
                self.fail_work('candidate',row,error)
                self.metrics['research_failed'] += 1
                continue
            url,payload = result
            rid = stable_id('research',url,self.data['research']['version'])
            with self.db.tx():
                self.db.execute('INSERT INTO research_cache(id,website,version,payload) VALUES(%s,%s,%s,%s) ON CONFLICT(website,version) DO NOTHING',[rid,url,self.data['research']['version'],j(payload)])
                valid = []
                for email in payload.get('emails',[])[:5]:
                    try:
                        email = normalize_email(email)
                    except (ValueError,ProviderError):
                        continue
                    if not email or self.db.one('SELECT 1 FROM suppression WHERE email=%s',[email]):
                        continue
                    inserted = self.db.execute('INSERT INTO lead(id,candidate_id,email,name,website,qualification,research_id) VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(email) DO NOTHING RETURNING id',
                        [stable_id('lead',email),row['id'],email,row['payload']['name'],url,j({'rating':row['payload'].get('rating'),'reviews':row['payload'].get('reviews')}),rid]).fetchone()
                    if inserted:
                        valid.append(email)
                self.db.execute('UPDATE candidate SET status=%s,lease_until=NULL,last_error=%s WHERE id=%s',['ready' if valid else 'rejected',None if valid else 'No new usable public email',row['id']])
            self.metrics['qualified'] += len(valid)
            self.metrics['researched'] += 1
        log('RESEARCH_PROGRESS',processed=len(rows),researched=self.metrics['researched'],failed=self.metrics['research_failed'])

    def prepare_leads(self, rows):
        work = []
        for row in rows:
            row = self.db.one("UPDATE lead SET status='working',attempts=attempts+1,lease_until=now()+interval '5 minutes' WHERE id=%s RETURNING *",[row['id']])
            row['_research'] = self.db.one('SELECT * FROM research_cache WHERE id=%s',[row['research_id']])
            work.append(row)
        def generate(row):
            return self.llm.draft(row,row['_research']['payload'],0,[])
        for row,draft,error in self.bounded_workers(work,generate):
            if error:
                self.fail_work('lead',row,error)
                continue
            research = row['_research']
            errors = validate_draft(draft,research['payload'])
            self.save_draft(row,research,0,draft,errors,row['attempts'])
            if errors:
                self.metrics['personalization_rejected'] += 1
                # Invalid output gets a bounded fresh draft retry, never blocks replacement discovery.
                self.fail_work('lead',row,ProviderError('temporary','Draft rejected by deterministic evidence validator'))
                continue
            with self.db.tx():
                self.db.execute('INSERT INTO message(id,lead_id,campaign_id,sequence,subject,body) VALUES(%s,%s,%s,0,%s,%s) ON CONFLICT(lead_id,sequence) DO NOTHING',
                    [stable_id('message',row['id'],0),row['id'],self.cid,draft['subject'],draft['body']])
                self.db.execute("UPDATE lead SET status='ready',lease_until=NULL,last_error=NULL WHERE id=%s",[row['id']])
            self.metrics['personalized'] += 1
            self.metrics['ready'] += 1
            self.metrics['queued'] += 1
        log('PERSONALIZATION_PROGRESS',processed=len(rows),ready=self.metrics['ready'],rejected=self.metrics['personalization_rejected'])

    def eligible_senders(self):
        self.db.execute("UPDATE sender SET health='HEALTHY',cooldown_until=NULL WHERE health='COOLDOWN' AND cooldown_until<=now()")
        states = {r['id']:r for r in self.db.all("SELECT * FROM sender WHERE health='HEALTHY'")}
        cfg = self.data['limits']
        if cfg['daily_total_enabled']:
            n = self.db.one("SELECT count(*) AS n FROM message WHERE status='sent' AND sent_at>=date_trunc('day',now())")['n']
            if n>=cfg['daily_total']:
                return []
        senders = []
        for sender in self.secrets.senders:
            if sender.id not in states:
                continue
            if cfg['daily_sender_enabled']:
                n = self.db.one("SELECT count(*) AS n FROM message WHERE status='sent' AND sender_id=%s AND sent_at>=date_trunc('day',now())",[sender.id])['n']
                if n>=cfg['daily_sender']:
                    continue
            senders.append(sender)
        return senders

    def send_batch(self, rows, kind):
        cfg = self.data['limits']
        if cfg['send_window_enabled']:
            local = datetime.now(ZoneInfo(cfg['timezone'])).strftime('%H:%M')
            start,end = cfg['window_start'],cfg['window_end']
            allowed = start<=local<end if start<end else local>=start or local<end
            if not allowed:
                return 0
        senders = self.eligible_senders()
        sender_map = {s.id:s for s in senders}
        available = list(senders)
        selected = []
        used = set()
        max_count = min(10,self.data['outreach']['batch_size'],self.data['outreach']['max_concurrency'])
        if cfg['daily_total_enabled']:
            sent_today = self.db.one("SELECT count(*) AS n FROM message WHERE status='sent' AND sent_at>=date_trunc('day',now())")['n']
            max_count = min(max_count,max(0,cfg['daily_total']-sent_today))
        for row in rows:
            if len(selected)>=max_count:
                break
            if self.db.one('SELECT 1 FROM suppression s JOIN lead l ON l.email=s.email WHERE l.id=%s',[row['lead_id']]):
                self.db.execute("UPDATE message SET status='cancelled' WHERE id=%s",[row['id']])
                continue
            if row['sequence']>0:
                sender = sender_map.get(row['sender_id'])
            else:
                sender = sender_map.get(row['sender_id'])
                if not sender or sender.id in used:
                    sender = next((s for s in available if s.id not in used),None)
            if not sender or sender.id in used:
                continue
            selected.append((row,sender)); used.add(sender.id)
        if not selected:
            return 0
        self.batch_no += 1
        bid = stable_id('batch',self.iid,self.batch_no)
        work = []
        with self.db.tx():
            self.db.execute('INSERT INTO batch(id,invocation_id,number,kind,planned) VALUES(%s,%s,%s,%s,%s)',[bid,self.iid,self.batch_no,kind,len(selected)])
            for row,sender in selected:
                mid = row['message_id'] or f"<attachai-{row['id']}@{sender.email.split('@')[1]}>"
                claimed = self.db.one("UPDATE message SET status='sending',sender_id=%s,message_id=%s,batch_id=%s,attempts=attempts+1,lease_until=now()+interval '5 minutes',updated_at=now() WHERE id=%s AND status IN ('queued','retry') RETURNING *",[sender.id,mid,bid,row['id']])
                if not claimed:
                    continue
                lead = self.db.one('SELECT email FROM lead WHERE id=%s',[row['lead_id']])
                self.db.execute("INSERT INTO attempt(message_id,number,sender_id,status) VALUES(%s,%s,%s,'sending')",[row['id'],claimed['attempts'],sender.id])
                claimed.update(email=lead['email'],attempt=claimed['attempts'],references=claimed['refs'])
                work.append((claimed,sender))
        started = time.monotonic()
        successful = failed = 0
        def send(item):
            return self.smtp.send(item[0],item[1])
        for item,result,error in self.bounded_workers(work,send):
            row,sender = item
            if error:
                # Unexpected failure around the SMTP call is conservative, not safe to retry.
                result = {'status':'review','kind':'ambiguous','error':'Unexpected SMTP adapter failure'}
            if result['status']=='sent':
                # Delivery acceptance, predecessor creation, and its durable event
                # commit together before any best-effort console logging.

                accepted = self.db.accept(
                    row['id'],
                    self.delays,
                    invocation_id=self.iid
                )
                
                if not accepted:
                    # SMTP may already have accepted the message.
                    # Mark it for manual review; never automatically resend it.
                    self.db.mark_delivery_ambiguous(
                        row['id'],
                        invocation_id=self.iid
                    )
                    raise RuntimeError(
                        'SMTP accepted a message but durable acceptance '
                        'could not be recorded; manual review is required'
                    )

                successful += 1
                self.metrics['followups_sent' if row['sequence'] else 'successful_initial_sends'] += 1
            else:
                failed += 1
                ek = result.get('kind') or 'terminal'
                retry = ek=='temporary' and row['attempts']<self.data['retry']['max_attempts']
                state = 'review' if result['status']=='review' or ek=='ambiguous' else 'retry' if retry else 'terminal'
                with self.db.tx():
                    self.db.execute("UPDATE message SET status=%s,error_kind=%s,last_error=%s,next_retry=now()+(%s*interval '1 second'),lease_until=NULL,updated_at=now() WHERE id=%s",[state,ek,result.get('error'),self.retry_delay(row['attempts']),row['id']])
                    self.db.execute('UPDATE attempt SET status=%s,finished_at=now(),error_kind=%s,error=%s WHERE message_id=%s AND number=%s',[state,ek,result.get('error'),row['id'],row['attempts']])
                    if ek=='auth':
                        self.db.execute("UPDATE sender SET health='STOPPED',last_error='SMTP authentication failed' WHERE id=%s",[sender.id])
                        # Safe rejected auth did not send; recover initial using another account.
                        if row['sequence']==0 and row['attempts']<self.data['retry']['max_attempts']:
                            self.db.execute("UPDATE message SET status='retry',next_retry=now(),sender_id=NULL WHERE id=%s",[row['id']])
                    elif ek=='temporary':
                        self.db.execute("UPDATE sender SET health='COOLDOWN',cooldown_until=now()+(%s*interval '1 second') WHERE id=%s",[self.data['retry']['sender_cooldown_seconds'],sender.id])
                    elif ek=='recipient':
                        self.db.suppress(row['email'],'hard_bounce')
                self.metrics['retryable_failures' if retry else 'terminal_failures'] += 1
            self.metrics['attempted'] += 1
            self.db.event(self.iid,'smtp_result',{'message':row['id'],'sender':sender.id,'status':result['status'],'kind':result.get('kind')})
            log('SMTP_RESULT',message=row['id'],sender=sender.id,status=result['status'],error_kind=result.get('kind'))
        self.db.execute("UPDATE batch SET attempted=%s,successful=%s,failed=%s,status='complete',finished_at=now() WHERE id=%s",[len(work),successful,failed,bid])
        log('BATCH_RESULT',batch_id=bid,batch_number=self.batch_no,planned=len(selected),attempted=len(work),successful=successful,failed=failed,senders=sorted(used),duration_seconds=round(time.monotonic()-started,3))
        if cfg['batch_gap_seconds']:
            self.sleep(cfg['batch_gap_seconds'])
        return len(work)

    def wait_until(self, at):
        delay = max(0,(at-datetime.now(timezone.utc)).total_seconds())
        runtime_left = self.data['limits']['max_runtime_seconds']-(time.monotonic()-self.start_time)
        if delay>self.data['retry']['max_seconds']+self.data['retry']['sender_cooldown_seconds'] or delay>=runtime_left or not self.within_runtime():
            return False
        self.sleep(max(.05,delay))
        return self.within_runtime()

    def wait_for_sender(self):
        at = self.db.one("SELECT min(cooldown_until) AS at FROM sender WHERE health='COOLDOWN'")['at']
        return bool(at and self.wait_until(at))

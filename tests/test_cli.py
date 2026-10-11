"""CLI wiring and fail-closed safety, with no database/provider network calls."""
import copy
import json
from datetime import datetime, timezone

import pytest
import yaml

from attachai import cli
from attachai.config import DEFAULTS


@pytest.fixture
def path(tmp_path):
    data = copy.deepcopy(DEFAULTS)
    data['llm']['postal_address'] = '123 Test Road, Austin TX 78701'
    p = tmp_path/'monitor.yaml'
    p.write_text(yaml.safe_dump(data))
    return p


class FakeStore:
    instances = []
    existing = set()
    failure = None

    def __init__(self,url):
        if self.failure:
            raise RuntimeError(self.failure)
        self.url,self.closed,self.migrated,self.locked = url,False,False,False
        self.reviewed = None
        self.instances.append(self)

    def acquire(self):
        self.locked = True

    def migrate(self):
        assert self.locked
        self.migrated = True

    def close(self):
        self.closed = True

    def one(self,query,args):
        return {'x':1} if tuple(args) in self.existing else None

    def reconcile(self):
        return {}

    def review(self,*args):
        self.reviewed = args


class FakeEngine:
    instances = []

    def __init__(self,config,store,secrets,*adapters):
        self.config,self.store,self.secrets = config,store,secrets
        self.instances.append(self)

    def run(self,**kwargs):
        self.kwargs = kwargs
        assert self.store.locked and self.store.migrated
        return 0,{}


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    FakeStore.instances,FakeStore.existing,FakeStore.failure = [],set(),None
    FakeEngine.instances = []
    monkeypatch.setattr(cli,'Store',FakeStore)
    monkeypatch.setattr(cli,'Engine',FakeEngine)
    for key in ('DATABASE_URL','GOOGLE_PLACES_API_KEY','LLM_API_KEY','SENDER_ACCOUNTS_JSON'):
        monkeypatch.delenv(key,raising=False)


def secrets(monkeypatch):
    monkeypatch.setenv('DATABASE_URL','postgresql://test:private-secret@db.example/test')
    monkeypatch.setenv('GOOGLE_PLACES_API_KEY','fake-places-key')
    monkeypatch.setenv('LLM_API_KEY','fake-llm-key')
    accounts = [{'id':f's{i}','email':f's{i}@sender.example','password':'fake-password',
                 'smtp_host':'smtp.example','smtp_port':465,'imap_host':'imap.example',
                 'imap_port':993,'tls_mode':'ssl'} for i in range(10)]
    monkeypatch.setenv('SENDER_ACCOUNTS_JSON',json.dumps(accounts))


def edit(path,fn):
    data = yaml.safe_load(path.read_text())
    fn(data)
    path.write_text(yaml.safe_dump(data))


def test_disabled_scheduled_needs_no_secrets_or_db(path,capsys):
    assert cli.main(['--config',str(path),'scheduled'])==0
    assert not FakeStore.instances and not FakeEngine.instances
    assert 'disabled' in capsys.readouterr().out


def test_emergency_stop_wins_over_real_dispatch_and_reset(path):
    edit(path,lambda d:d['safety'].update(emergency_stop=True))
    assert cli.main(['--config',str(path),'run','--send-enabled','true','--dry-run','false','--reset-state','true'])==0
    assert not FakeStore.instances and not FakeEngine.instances


def test_migrate_uses_database_secret_only(path,monkeypatch):
    monkeypatch.setenv('DATABASE_URL','postgresql://test:private-secret@db.example/test')
    assert cli.main(['--config',str(path),'migrate'])==0
    assert FakeStore.instances[0].migrated and FakeStore.instances[0].closed


def test_full_real_dispatch_reaches_both_phases_with_same_overrides(path,monkeypatch):
    secrets(monkeypatch)
    assert cli.main(['--config',str(path),'run','--send-enabled','true','--dry-run','false','--target-new-initials','100'])==0
    config = FakeEngine.instances[0].config
    assert config.send_enabled and not config.dry_run
    assert config.process_followups and config.process_new_outreach
    assert config.target==100
    assert FakeStore.instances[0].closed


def test_dispatch_dry_run_does_not_enable_send_path(path,monkeypatch):
    secrets(monkeypatch)
    assert cli.main(['--config',str(path),'run','--send-enabled','true','--dry-run','true'])==0
    assert FakeEngine.instances[0].config.dry_run


def test_followups_only_does_not_need_places_key(path,monkeypatch):
    secrets(monkeypatch)
    monkeypatch.delenv('GOOGLE_PLACES_API_KEY')
    assert cli.main(['--config',str(path),'run','--send-enabled','true','--dry-run','false','--process-new-outreach','false'])==0
    assert not FakeEngine.instances[0].config.process_new_outreach
    assert FakeEngine.instances[0].config.process_followups


def test_missing_secret_is_named_but_never_prints_values(path,capsys):
    assert cli.main(['--config',str(path),'run'])==1
    assert 'DATABASE_URL' in capsys.readouterr().out
    assert not FakeStore.instances


def test_driver_error_does_not_leak_database_password(path,monkeypatch,capsys):
    secrets(monkeypatch)
    FakeStore.failure = 'postgresql://test:private-secret@db.example/test fake-password fake-places-key'
    assert cli.main(['--config',str(path),'run'])==1
    out = capsys.readouterr().out
    assert 'private-secret' not in out and 'fake-password' not in out and 'fake-places-key' not in out


def test_scheduled_claim_is_filtered_under_lock(path,monkeypatch):
    secrets(monkeypatch)
    edit(path,lambda d:d['automation'].update(enabled=True))
    monkeypatch.setattr(cli,'due_slots',lambda d,now:{'outreach':'slot1','followups':'slot2'})
    FakeStore.existing = {('outreach','slot1')}
    assert cli.main(['--config',str(path),'scheduled'])==0
    e = FakeEngine.instances[0]
    assert not e.config.process_new_outreach and e.config.process_followups
    assert e.kwargs['slots']=={'followups':'slot2'}


def test_already_claimed_scheduled_slots_skip(path,monkeypatch):
    secrets(monkeypatch)
    edit(path,lambda d:d['automation'].update(enabled=True))
    monkeypatch.setattr(cli,'due_slots',lambda d,now:{'outreach':'slot1'})
    FakeStore.existing = {('outreach','slot1')}
    assert cli.main(['--config',str(path),'scheduled'])==0
    assert not FakeEngine.instances
    assert FakeStore.instances[0].closed


@pytest.mark.parametrize('extra',[[],['--confirm'],['--confirm','--sent-at','bad'],['--confirm','--sent-at','2026-10-11T00:00:00']])
def test_review_cannot_accept_without_valid_verified_time(path,monkeypatch,extra):
    monkeypatch.setenv('DATABASE_URL','postgresql://test:private-secret@db.example/test')
    assert cli.main(['--config',str(path),'review','--message-id','m1','--resolution','sent','--evidence','operator-proof',*extra])==1
    assert FakeStore.instances[0].reviewed is None


def test_review_passes_actual_time_and_evidence(path,monkeypatch):
    monkeypatch.setenv('DATABASE_URL','postgresql://test:private-secret@db.example/test')
    assert cli.main(['--config',str(path),'review','--message-id','m1','--resolution','sent','--evidence','operator-proof','--confirm','--sent-at','2020-01-01T00:00:00Z'])==0
    args = FakeStore.instances[0].reviewed
    assert args[3]==datetime(2020,1,1,tzinfo=timezone.utc)
    assert args[4]=='operator-proof'


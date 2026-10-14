"""Real CLI/state/ledger handoff with synthetic media; MCP and runner launches are mocked."""
import json
from pathlib import Path

import pytest

from slop import ledger, relay as R, update
from slop.gen import clips, hedra, store
from test_gen_hedra import ready
from test_gen_higgsfield import H, env, run  # noqa: F401

pytestmark = pytest.mark.skipif(not H.FFMPEG, reason="ffmpeg is required")


@pytest.fixture
def rig(env, tmp_path, monkeypatch):
    monkeypatch.setenv("SLOP_PROJECTS", str(env.parent))
    rd = R.relay_dir(); rd.mkdir(parents=True, exist_ok=True)
    R._write_json(rd / "config.json", {"engine": "claude"})
    monkeypatch.setattr(R, "_start_runner", lambda *a: {"id": "fake-runner"})
    monkeypatch.setattr(R, "_runner", lambda *a: {"alive": False})
    monkeypatch.setattr(R, "production", lambda *a: {"state": "idle", "summary": "idle"})
    monkeypatch.setattr(update, "reminder", lambda: None)
    cid = ready(env, tmp_path, "sung")
    return env, cid, rd


def command(rig, *args):
    rc, out = run(rig[0], *args)
    assert rc == 0, out
    return out


def quote(rig):
    out = command(rig, "relay", "job", "--kind", "hedra", "--what", "quote", "--clip", rig[1])
    jid = out["job"]
    command(rig, "relay", "hedra", jid, "--action", "quote", "--cost", ".5", "--currency", "USD")
    return jid


def generate(rig):
    quote(rig)
    command(rig, "clip", "submit", rig[1], "--yes", "--hedra-cost", ".5", "--hedra-currency", "USD")
    return command(rig, "relay", "job", "--kind", "hedra", "--what", "generate", "--clip", rig[1])["job"]


def test_quote_and_generation_handoff_resume_and_one_completion(rig, monkeypatch):
    pdir, cid, rd = rig
    out = command(rig, "relay", "job", "--kind", "hedra", "--what", "quote", "--clip", cid)
    jid = out["job"]
    assert command(rig, "relay", "job", "--kind", "hedra", "--what", "quote", "--clip", cid)["job"] == jid
    r = command(rig, "relay", "read")
    assert r["jobs"][0]["request_file"] and "never generate" in r["grok_next"].lower()
    assert not ledger.rows(pdir)
    report = command(rig, "relay", "hedra", jid, "--action", "quote", "--cost", ".5", "--currency", "USD")
    assert report["started"] and len(R._rows(rd / "inbox.jsonl")) == 1
    command(rig, "clip", "submit", cid, "--yes", "--hedra-cost", ".5", "--hedra-currency", "USD")
    gen = command(rig, "relay", "job", "--kind", "hedra", "--what", "generate", "--clip", cid)["job"]
    for action in ("done", "fail"):
        flags = ["--reason", "bad"] if action == "fail" else []
        assert run(pdir, "relay", action, gen, *flags)[0] != 0
    claim = command(rig, "relay", "hedra", gen, "--action", "start", "--cost", ".5", "--currency", "USD")
    assert claim["idempotency_key"] == store.load(pdir, cid)["takes"][-1]["idempotency_key"]
    assert run(pdir, "relay", "hedra", gen, "--action", "start", "--cost", ".5", "--currency", "USD")[0] != 0
    assert run(pdir, "relay", "cancel", gen)[0] != 0
    assert "Do not generate again" in command(rig, "relay", "read")["grok_next"]
    # Lost jobs.json state after start is recovered from the durable take.
    R._write_json(rd / "jobs.json", {})
    assert "Do not generate again" in command(rig, "relay", "read")["grok_next"]
    command(rig, "relay", "hedra", gen, "--action", "pending", "--job-id", "hedra-123")
    r = command(rig, "relay", "read")
    assert "hedra-123" in r["grok_next"] and "never generate again" in r["grok_next"]
    assert run(pdir, "relay", "hedra", gen, "--action", "pending", "--job-id", "other")[0] != 0
    monkeypatch.setattr(hedra.higgsfield, "fetch_result", lambda url, path, **kw: path.write_bytes(b"fake mp4"))
    monkeypatch.setattr(clips, "probe_duration", lambda p: 4)
    args = ("relay", "hedra", gen, "--action", "complete", "--job-id", "hedra-123", "--url",
            "https://result.test/a.mp4", "--cost", ".4", "--currency", "USD")
    assert command(rig, *args)["started"]
    count = len(R._rows(rd / "inbox.jsonl"))
    assert "already done" in command(rig, *args)["text"]
    assert len(R._rows(rd / "inbox.jsonl")) == count
    assert store.load(pdir, cid)["status"] == "delivered"
    assert ledger.spent_usd(pdir, "hedra") == .4
    assert "clip sync" in R._rows(rd / "inbox.jsonl")[-1]["text"]


@pytest.mark.parametrize("change", ["price", "currency", "input", "freeze", "cap"])
def test_start_refuses_stale_or_unapproved_generation(rig, change):
    pdir, cid, _ = rig
    jid = generate(rig)
    cost, currency = ".5", "USD"
    if change == "price": cost = ".6"
    if change == "currency": currency = "credits"
    if change == "input":
        c = store.load(pdir, cid); c["body"]["prompt"] += "changed"; store.save(pdir, c)
    if change in ("freeze", "cap"):
        p = json.loads((pdir / "project.json").read_text())
        p["budget"]["frozen" if change == "freeze" else "hedra_usd"] = "review" if change == "freeze" else .1
        (pdir / "project.json").write_text(json.dumps(p))
    assert run(pdir, "relay", "hedra", jid, "--action", "start", "--cost", cost, "--currency", currency)[0] != 0
    assert not store.load(pdir, cid)["takes"][-1].get("relay_attempted")
    assert ledger.spent_usd(pdir, "hedra") == .5


def test_cancel_unstarted_releases_reservation(rig):
    jid = generate(rig)
    command(rig, "relay", "cancel", jid, "--reason", "quote changed")
    assert ledger.spent_usd(rig[0], "hedra") == 0
    assert store.load(rig[0], rig[1])["status"] == "locked"


def test_quote_refuses_changed_inputs_and_generate_requires_matching_quote(rig):
    pdir, cid, _ = rig
    jid = command(rig, "relay", "job", "--kind", "hedra", "--what", "quote", "--clip", cid)["job"]
    command(rig, "clip", "set", cid, "--aspect-ratio", "9:16")
    assert run(pdir, "relay", "hedra", jid, "--action", "quote", "--cost", ".5", "--currency", "USD")[0] != 0
    command(rig, "relay", "cancel", jid)
    command(rig, "clip", "lock", cid)
    command(rig, "clip", "submit", cid, "--yes", "--hedra-cost", ".5", "--hedra-currency", "USD")
    assert run(pdir, "relay", "job", "--kind", "hedra", "--what", "generate", "--clip", cid)[0] != 0


def test_failure_keeps_estimate_without_confirmed_refund(rig):
    jid = generate(rig)
    command(rig, "relay", "hedra", jid, "--action", "start", "--cost", ".5", "--currency", "USD")
    assert run(rig[0], "relay", "hedra", jid, "--action", "failed", "--reason", "timeout")[0] != 0
    command(rig, "relay", "hedra", jid, "--action", "pending", "--job-id", "known-job")
    command(rig, "relay", "hedra", jid, "--action", "failed", "--job-id", "known-job", "--reason", "provider failed")
    assert ledger.spent_usd(rig[0], "hedra") == .5


def test_completion_recovers_if_notification_was_interrupted(rig, monkeypatch):
    jid = generate(rig)
    command(rig, "relay", "hedra", jid, "--action", "start", "--cost", ".5", "--currency", "USD")
    command(rig, "relay", "hedra", jid, "--action", "pending", "--job-id", "recovery-job")
    monkeypatch.setattr(hedra.higgsfield, "fetch_result", lambda url, path, **kw: path.write_bytes(b"fake mp4"))
    monkeypatch.setattr(clips, "probe_duration", lambda p: 4)
    # Video was ingested, but the process ended before notifying production.
    c = store.load(rig[0], rig[1])
    hedra.ingest(rig[0], c, url="https://result.test/a.mp4", job_id="recovery-job")
    out = command(rig, "relay", "hedra", jid, "--action", "complete", "--job-id", "recovery-job",
                  "--url", "https://result.test/a.mp4")
    assert out["started"] and len(store.load(rig[0], rig[1])["takes"]) == 1


def test_quote_without_runner_and_phase_conflict(rig, monkeypatch):
    pdir, cid, rd = rig
    (rd / 'config.json').unlink()
    monkeypatch.setattr(R, '_start_runner', lambda *a: pytest.fail('must not launch a runner'))
    jid = command(rig, 'relay', 'job', '--kind', 'hedra', '--what', 'quote', '--clip', cid)['job']
    rc, out = run(pdir, 'relay', 'job', '--kind', 'hedra', '--what', 'generate', '--clip', cid)
    assert rc != 0 and 'open quote job' in str(out)
    result = command(rig, 'relay', 'hedra', jid, '--action', 'quote', '--cost', '.5', '--currency', 'USD')
    assert result['ok'] and result['wake_pending'] and not result['started']
    assert not R._jobs(rd) and len(R._rows(rd / 'inbox.jsonl')) == 1
    command(rig, 'clip', 'submit', cid, '--yes', '--hedra-cost', '.5', '--hedra-currency', 'USD')
    gen = command(rig, 'relay', 'job', '--kind', 'hedra', '--what', 'generate', '--clip', cid)['job']
    assert gen != jid
    command(rig, 'relay', 'cancel', gen)
    assert not R._jobs(rd) and ledger.spent_usd(pdir, 'hedra') == 0


def test_missing_runner_does_not_lose_quote(rig, monkeypatch):
    from slop.config import SlopError
    def missing(*a):
        raise SlopError('Claude Code is not installed')
    monkeypatch.setattr(R, '_start_runner', missing)
    jid = command(rig, 'relay', 'job', '--kind', 'hedra', '--what', 'quote', '--clip', rig[1])['job']
    out = command(rig, 'relay', 'hedra', jid, '--action', 'quote', '--cost', '.5', '--currency', 'USD')
    assert out['ok'] and out['wake_pending'] and not R._jobs(rig[2])
    assert 'already done' in command(rig, 'relay', 'hedra', jid, '--action', 'quote', '--cost', '.5', '--currency', 'USD')['text']


def test_hedra_instructions_are_separate_steps(rig):
    command(rig, 'relay', 'job', '--kind', 'hedra', '--what', 'quote', '--clip', rig[1])
    text = command(rig, 'relay', 'read')['grok_next']
    assert text.startswith('1. ') and '\n2. ' in text


def test_full_handoff_without_claude_or_configuration(rig, monkeypatch):
    pdir, cid, rd = rig
    (rd / 'config.json').unlink()
    monkeypatch.setattr(R, '_start_runner', lambda *a: pytest.fail('no runner should start'))
    jid = generate(rig)
    command(rig, 'relay', 'hedra', jid, '--action', 'start', '--cost', '.5', '--currency', 'USD')
    command(rig, 'relay', 'hedra', jid, '--action', 'pending', '--job-id', 'runner-free')
    monkeypatch.setattr(hedra.higgsfield, 'fetch_result', lambda url, path, **kw: path.write_bytes(b'fake mp4'))
    monkeypatch.setattr(clips, 'probe_duration', lambda p: 4)
    out = command(rig, 'relay', 'hedra', jid, '--action', 'complete', '--job-id', 'runner-free',
                  '--url', 'https://result.test/a.mp4', '--cost', '.4', '--currency', 'USD')
    assert out['ok'] and out['wake_pending'] and not out['started']
    assert not R._jobs(rd) and len(R._rows(rd / 'inbox.jsonl')) == 2
    assert store.load(pdir, cid)['status'] == 'delivered'
    assert ledger.spent_usd(pdir, 'hedra') == .4


def test_cancel_stale_quote_without_setup(rig):
    jid = command(rig, 'relay', 'job', '--kind', 'hedra', '--what', 'quote', '--clip', rig[1])['job']
    (rig[2] / 'config.json').unlink()
    out = command(rig, 'relay', 'cancel', jid, '--reason', 'superseded by direct test')
    assert out['status'] == 'cancelled' and out['ok']
    assert not R._jobs(rig[2]) and not ledger.rows(rig[0])


def test_quote_status_amount_staleness_and_report_status(rig):
    pdir, cid, rd = rig
    jid = command(rig, 'relay', 'job', '--kind', 'hedra', '--what', 'quote', '--clip', cid)['job']
    out = command(rig, 'relay', 'hedra', jid, '--action', 'quote', '--cost', '.6', '--currency', 'USD')
    assert out['status'] == 'done'
    assert 'owner' in R._rows(rd / 'inbox.jsonl')[-1]['text']
    assert 'director' not in R._rows(rd / 'inbox.jsonl')[-1]['text']
    out = command(rig, 'clip', 'status', cid)
    assert out['quote']['cost'] == .6 and out['quote']['currency'] == 'USD'
    assert out['quote']['current'] and 'price unknown' not in out['text']
    assert command(rig, 'relay', 'hedra', jid, '--action', 'quote', '--cost', '.6', '--currency', 'USD')['status'] == 'done'
    command(rig, 'clip', 'set', cid, '--aspect-ratio', '1:1')
    out = command(rig, 'clip', 'status', cid)
    assert not out['quote']['current'] and 'inputs changed' in out['text']
    assert not ledger.rows(pdir)

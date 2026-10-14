"""Hedra MCP handoff, clip lifecycle and wallet isolation; all provider calls are mocked."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import requests

from slop import ledger
from slop.config import SlopError
from slop.gen import clips, hedra, store, templates as tpl
from test_gen_higgsfield import H, env, run  # noqa: F401

pytestmark = pytest.mark.skipif(not H.FFMPEG, reason="ffmpeg is required")


def ready(env, tmp_path, kind="motion"):
    rc, out = run(env, "clip", "new", "s004" if kind == "motion" else "s002", "--kind", kind,
                  "--provider", "hedra")
    assert rc == 0, out
    cid = out["clip_id"]
    c = store.load(env, cid)
    assert c["model"] == hedra.MODEL
    f = tmp_path / "prompt.txt"
    f.write_text(tpl.SLOT_RE.sub("she moves", c["body"]["prompt"]))
    assert run(env, "clip", "set", cid, "--prompt-file", str(f))[0] == 0
    rc, out = run(env, "clip", "lock", cid)
    assert rc == 0, out
    c = store.load(env, cid)
    c["hosted"] = {key: {"url": f"https://files.test/{key}", "sha1": store.file_sha1(src)}
                   for key, src, _ in clips.hosted_files(env, c)}
    store.save(env, c)
    return cid


def test_sung_dry_run_is_offline_and_uses_audio(env, tmp_path, monkeypatch):
    cid = ready(env, tmp_path, "sung")
    monkeypatch.setattr(requests.Session, "request", lambda *a, **kw: pytest.fail("network on dry run"))
    before = store.clip_file(env, cid).read_bytes()
    rc, out = run(env, "clip", "submit", cid, "--dry-run")
    assert rc == 0, out
    assert not out["lock_problems"]
    assert out["would_send"]["duration_ms"] == 4000
    assert out["would_send"]["reference_audio_urls"][0] == "<<HEDRA_UPLOAD:audio>>"
    assert out["mcp_request"]["reference_image_urls"] == ["<<HEDRA_UPLOAD:start>>"]
    assert out["estimate"]["generation_tool"] == "generate_video"
    assert "start_keyframe_url" not in out["would_send"]
    assert store.clip_file(env, cid).read_bytes() == before and not ledger.rows(env)


def test_quote_only_creates_no_take_or_charge(env, tmp_path, monkeypatch):
    cid = ready(env, tmp_path)
    monkeypatch.setattr(clips, "auto_host", lambda *a: [])
    rc, out = run(env, "clip", "submit", cid, "--quote-only")
    assert rc == 0, out
    req = json.loads(Path(out["request_file"]).read_text())
    assert req["estimate"]["input"] == req["request"]
    assert req["uploads"] and not ledger.rows(env) and not store.load(env, cid)["takes"]




@pytest.mark.parametrize("currency,cost,flag", [("USD", 1.2, "--cost-usd"), ("credits", 10, "--credits")])
def test_mcp_reservation_pending_delivery_and_settlement(env, tmp_path, monkeypatch, currency, cost, flag):
    cid = ready(env, tmp_path)
    monkeypatch.setattr(requests.Session, "request", lambda *a, **kw: pytest.fail("MCP CLI made a provider call"))
    rc, out = run(env, "clip", "submit", cid, "--yes",
                  "--hedra-cost", str(cost), "--hedra-currency", currency)
    assert rc == 0, out
    req = json.loads(Path(out["request_file"]).read_text())
    assert req["request"]["idempotency_key"]
    assert req["currency"] == currency and "get_generations" in " ".join(req["how_to_run"])
    assert run(env, "clip", "ingest", cid, "--pending", "--job-id", "mcp-job")[0] == 0
    rc, out = run(env, "clip", "poll", cid)
    assert rc == 0 and "get_generations" in out["text"] and "mcp-job" in out["text"]
    file = tmp_path / "result.mp4"; file.write_bytes(b"mock video")
    monkeypatch.setattr(clips, "probe_duration", lambda p: 5)
    rc, out = run(env, "clip", "ingest", cid, "--job-id", "mcp-job", "--file", str(file), flag, "0")
    assert rc == 0, out
    assert store.load(env, cid)["status"] == "delivered"
    assert ledger.spent_usd(env, "hedra") == ledger.spent_credits(env, "hedra") == 0
    assert run(env, "clip", "ingest", cid, "--job-id", "mcp-job", "--file", str(file))[0] == 0
    assert len(store.load(env, cid)["takes"]) == 1


def test_mcp_needs_price_unit_and_matching_settlement(env, tmp_path):
    cid = ready(env, tmp_path)
    assert run(env, "clip", "submit", cid, "--yes")[0] != 0
    assert not store.load(env, cid)["takes"] and not ledger.rows(env)
    assert run(env, "clip", "submit", cid, "--yes",
               "--hedra-cost", "10", "--hedra-currency", "credits")[0] == 0
    assert run(env, "clip", "ingest", cid, "--failed", "provider failed", "--cost-usd", "0")[0] != 0
    assert run(env, "clip", "ingest", cid, "--failed", "provider failed")[0] == 0
    assert ledger.spent_credits(env, "hedra") == 10  # no unsupported assumption of a refund
    assert run(env, "clip", "ingest", cid, "--credits", "0")[0] != 0  # reconcile by job id


@pytest.mark.parametrize("guard", ["free", "frozen", "cap", "approval"])
def test_guards_stop_mcp_reservation(env, tmp_path, monkeypatch, guard):
    cid = ready(env, tmp_path)
    project = json.loads((env / "project.json").read_text())
    if guard == "free":
        monkeypatch.setenv("SLOP_FREE_ONLY", "1")
    if guard == "frozen":
        project["budget"]["frozen"] = "review first"
    if guard == "cap":
        project["budget"]["hedra_usd"] = .1
    (env / "project.json").write_text(json.dumps(project))
    with pytest.raises(SlopError):
        clips.submit(env, cid, yes=guard != "approval", hedra_cost=.5, hedra_currency="USD")
    assert not store.load(env, cid)["takes"] and not ledger.rows(env)


def test_credit_wallets_are_isolated(env):
    ledger.record(env, provider="hedra", model=hedra.MODEL, kind="video", credits=999)
    ledger.check_budget(env, "higgsfield", add_credits=1, yes=True)
    assert ledger.spent_credits(env, "higgsfield") == 0
    project = json.loads((env / "project.json").read_text())
    project["budget"]["hedra_credits"] = 1000
    (env / "project.json").write_text(json.dumps(project))
    with pytest.raises(SlopError, match="Hedra credits cap"):
        ledger.check_budget(env, "hedra", add_credits=2, yes=True)


@pytest.mark.parametrize("cost,unit", [(float("nan"), "USD"), (-1, "USD"), (float("inf"), "credits"), (1, "EUR"), (True, "USD")])
def test_bad_prices(cost, unit):
    with pytest.raises(SlopError):
        hedra.price(cost, unit)


def test_missing_audio_and_unsupported_model_fail_before_upload(env, tmp_path):
    cid = ready(env, tmp_path, "sung")
    c = store.load(env, cid)
    with pytest.raises(SlopError, match="audio"):
        hedra.build(env, c, no_audio_ref=True)
    c["model"] = "other-model"
    with pytest.raises(SlopError, match="currently support"):
        hedra.build(env, c)




def test_onboarding_hedra_unlocks_video_without_other_providers(tmp_path, monkeypatch):
    from test_onboard_items import rep
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "home"))
    from slop.onboard import state
    state.update(lambda s: s["marks"].update(hedra={"state": "done"}))
    r = rep("studio", key={"present": False, "valid": False})
    video = next(x for x in r["items"] if x["id"] == "video")
    assert video["state"] == "done" and "Hedra" in video["data"]["via"]


def test_missing_public_urls_fail_without_reservation_or_false_quote(env, tmp_path, monkeypatch):
    cid = ready(env, tmp_path, "sung")
    c = store.load(env, cid); c["hosted"] = {}; store.save(env, c)
    monkeypatch.setattr(clips, "auto_host", lambda *a: [])
    for flags in (("--quote-only",), ("--yes", "--hedra-cost", ".5", "--hedra-currency", "USD")):
        rc, out = run(env, "clip", "submit", cid, *flags)
        assert rc != 0 and "missing public HTTPS URLs" in out["error"]
        assert not ledger.rows(env) and not store.load(env, cid)["takes"]
    assert not (store.clip_folder(env, cid) / "hedra-preflight.json").exists()
    rc, out = run(env, "clip", "submit", cid, "--dry-run")
    assert rc == 0 and not out["ready_to_upload"] and set(out["upload_problems"]) == {"start", "audio"}


def test_vertical_output_and_connector_next_step(env, tmp_path):
    cid = ready(env, tmp_path)
    assert store.load(env, cid)["body"]["aspect_ratio"] == "adaptive"
    assert run(env, "clip", "set", cid, "--aspect-ratio", "9:16")[0] == 0
    rc, out = run(env, "clip", "lock", cid)
    assert rc == 0 and "--kind hedra --what quote" in out["text"] and "--yes" not in out["text"]
    rc, out = run(env, "clip", "submit", cid, "--dry-run")
    assert rc == 0 and out["mcp_request"]["aspect_ratio"] == "9:16"


def test_male_lead_prompt_uses_configured_pronoun():
    lead = tpl.lead_words({"lead": {"pronoun": "he"}})
    prompt = tpl.sung_prompt(words="city lights", phrases=[], t0=0, duration=4,
                             shot={}, lead=lead, kicks=[], downbeats=[])
    assert "He lip-syncs" in prompt and "the man" in prompt.lower() and "she" not in prompt.lower()


def test_estimate_excludes_generation_idempotency_key(env, tmp_path):
    cid = ready(env, tmp_path)
    rc, out = run(env, 'clip', 'submit', cid, '--yes', '--hedra-cost', '.6', '--hedra-currency', 'USD')
    assert rc == 0, out
    req = json.loads(Path(out['request_file']).read_text())
    assert req['request']['idempotency_key']
    assert 'idempotency_key' not in req['estimate']['input']
    assert req['estimate']['input'] == {k: v for k, v in req['request'].items() if k != 'idempotency_key'}
    dry = run(env, 'clip', 'submit', cid, '--dry-run')[1]
    assert '--quote-only' not in dry['text'] and 'resume' in dry['text']


def test_reuse_start_opt_in_and_external_import(env, tmp_path):
    cid = ready(env, tmp_path)
    original = store.absp(env, store.load(env, cid)['start'])
    external = tmp_path / 'outside.png'
    external.write_bytes(original.read_bytes())
    args = ('clip', 'new', 's004', '--id', 'repeat', '--kind', 'motion', '--provider', 'hedra', '--start', str(external))
    assert run(env, *args)[0] != 0
    rc, out = run(env, *args, '--reuse-start')
    assert rc == 0, out
    saved = out['clip']['start']
    assert not Path(saved).is_absolute()
    external.unlink()
    assert (env / saved).read_bytes() == original.read_bytes()
    # set supports the same deliberate override.
    assert run(env, 'clip', 'set', 'repeat', '--start', str(original))[0] != 0
    assert run(env, 'clip', 'set', 'repeat', '--start', str(original), '--reuse-start')[0] == 0


def test_missing_links_dry_run_does_not_suggest_quote(env, tmp_path):
    cid = ready(env, tmp_path)
    c = store.load(env, cid); c['hosted'] = {}; store.save(env, c)
    out = run(env, 'clip', 'submit', cid, '--dry-run')[1]
    assert 'gen host' in out['text'] and '--quote-only' not in out['text']


def test_status_labels_uncapped_hedra(env, tmp_path):
    ready(env, tmp_path)
    rc, out = run(env, 'status')
    assert rc == 0, out
    assert 'USD cap: no cap (0 = unlimited)' in out['text']
    assert out['spend']['budget']['hedra_usd'] == 0


def test_json_budget_uncapped_flags_and_lead_fallback(env):
    p = json.loads((env / 'project.json').read_text())
    p['budget']['hedra_usd'] = 2
    p['budget']['hedra_credits'] = 0
    p['lead']['possessive'] = ''
    (env / 'project.json').write_text(json.dumps(p))
    rc, out = run(env, 'status')
    assert rc == 0
    b = out['spend']['budget']
    assert b['hedra_usd'] == 2 and b['uncapped']['hedra_usd'] is False
    assert b['hedra_credits'] == 0 and b['uncapped']['hedra_credits'] is True
    rc, out = run(env, 'lead', '--pronoun', 'he')
    assert rc == 0 and out['lead']['possessive'] == 'His'
    assert run(env, 'lead', '--pronoun', 'they')[1]['lead']['possessive'] == 'Their'
    assert run(env, 'lead', '--possessive', "the singer's")[1]['lead']['possessive'] == "the singer's"
    assert tpl.lead_words({'lead': {'pronoun': 'he', 'possessive': "the singer's"}})['possessive'] == "the singer's"


def test_allow_turn_closer_and_lock_warning(env, tmp_path):
    rc, out = run(env, 'clip', 'new', 's002', '--kind', 'sung', '--provider', 'hedra', '--allow-turn')
    assert rc == 0, out
    c = out['clip']; cid = c['id']
    assert tpl.SUNG_TURN_CLOSER in c['body']['prompt'] and tpl.SUNG_CLOSER not in c['body']['prompt']
    # A scaffold redraft must preserve the opt-in.
    assert run(env, 'clip', 'set', cid, '--duration', '5')[0] == 0
    assert tpl.SUNG_CLOSER not in store.load(env, cid)['body']['prompt']
    # Simulate a reviewed, filled prompt with a contradictory turn.
    c = store.load(env, cid)
    c['body']['prompt'] = tpl.head(c['words'], 'He') + '. He turns to face the camera. ' + tpl.SUNG_CLOSER
    store.save(env, c)
    rc, out = run(env, 'clip', 'lock', cid)
    assert rc == 0, out
    assert any("both 'no head turns'" in w for w in out['warnings'])
    rc, out = run(env, 'clip', 'set', cid, '--allow-turn')
    assert rc == 0, out
    c = store.load(env, cid)
    assert c['status'] == 'draft' and 'He turns to face the camera.' in c['body']['prompt']
    assert tpl.SUNG_CLOSER not in c['body']['prompt']
    assert not any("both 'no head turns'" in w for w in run(env, 'clip', 'lock', cid)[1]['warnings'])


def test_turn_warning_ignores_lyrics_and_negation():
    assert tpl.turn_warning(tpl.head('Turn around') + '. ' + tpl.SUNG_CLOSER) is None
    assert tpl.turn_warning('He does not turn. ' + tpl.SUNG_CLOSER) is None
    assert tpl.turn_warning('He is facing the camera. ' + tpl.SUNG_CLOSER) is None
    assert tpl.turn_warning('He turns to face the camera. ' + tpl.SUNG_CLOSER)


def test_confirmed_usd_counts_equal_estimate_repeat_and_refund(env, tmp_path):
    from slop.core_cli import ledger_summary
    cid = ready(env, tmp_path)
    assert run(env, 'clip', 'submit', cid, '--yes', '--hedra-cost', '.6', '--hedra-currency', 'USD')[0] == 0
    c = store.load(env, cid); tk = c['takes'][-1]
    project = json.loads((env / 'project.json').read_text())
    def totals():
        return ledger_summary(env, project)['by_provider']['hedra']
    assert totals()['real_usd'] == 0  # estimate is not confirmation
    hedra.settle_cost(env, c, tk, cost=.6, currency='USD'); store.save(env, c)
    assert totals()['real_usd'] == totals()['est_usd'] == .6 and totals()['calls'] == 1
    before = (env / 'ledger.jsonl').read_bytes()
    hedra.settle_cost(env, c, tk, cost=.6, currency='USD')
    assert (env / 'ledger.jsonl').read_bytes() == before
    hedra.settle_cost(env, c, tk, cost=.4, currency='USD'); store.save(env, c)
    assert totals()['real_usd'] == totals()['est_usd'] == .4
    hedra.settle_cost(env, c, tk, cost=0, currency='USD'); store.save(env, c)
    assert totals()['real_usd'] == totals()['est_usd'] == 0


def test_legacy_confirmed_costs_are_read_without_rewriting_or_double_counting(env, tmp_path):
    from slop.core_cli import ledger_summary
    cid = ready(env, tmp_path)
    assert run(env, 'clip', 'submit', cid, '--yes', '--hedra-cost', '.6', '--hedra-currency', 'USD')[0] == 0
    c = store.load(env, cid)
    c['takes'][0].update(cost_usd=.6, status='delivered')
    # Two pre-fix confirmed takes, each with an estimate row and cost on the take only.
    c['takes'].append({**c['takes'][0], 'n': 2})
    store.save(env, c)
    ledger.record(env, provider='hedra', model=hedra.MODEL, kind='video', est_usd=.6,
                  units={'clip': cid, 'take': 2})
    project = json.loads((env / 'project.json').read_text())
    before = (env / 'ledger.jsonl').read_bytes()
    totals = ledger_summary(env, project)['by_provider']['hedra']
    assert totals['real_usd'] == totals['est_usd'] == 1.2
    assert (env / 'ledger.jsonl').read_bytes() == before
    # A later explicit confirmation moves one take into the ledger path, without duplication.
    hedra.settle_cost(env, c, c['takes'][0], cost=.6, currency='USD')
    assert ledger_summary(env, project)['by_provider']['hedra']['real_usd'] == 1.2
    ledger.settle(env, provider='hedra', clip=cid, take=2, note='confirmed refund')
    assert ledger_summary(env, project)['by_provider']['hedra']['real_usd'] == .6
    out = run(env, 'spend')[1]
    assert 'Hedra confirmed USD from recorded takes: $0.60' in out['text']


def test_confirmed_credit_cost_is_not_usd(env, tmp_path):
    from slop.core_cli import ledger_summary
    cid = ready(env, tmp_path)
    assert run(env, 'clip', 'submit', cid, '--yes', '--hedra-cost', '10', '--hedra-currency', 'credits')[0] == 0
    c = store.load(env, cid)
    hedra.settle_cost(env, c, c['takes'][0], cost=8, currency='credits'); store.save(env, c)
    b = ledger_summary(env, json.loads((env / 'project.json').read_text()))['by_provider']['hedra']
    assert b['credits'] == 8 and b['real_usd'] == b['est_usd'] == 0

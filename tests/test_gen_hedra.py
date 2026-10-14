"""Hedra transports, clip lifecycle and wallet isolation; all provider calls are mocked."""
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
    return cid


class FakeHedra(hedra.Hedra):
    def __init__(self, pdir, *, cost=.5, error=None, result=None):
        self.pdir, self.cost, self.error, self.result = pdir, cost, error, result
        self.calls = []

    def upload(self, path):
        self.calls.append(("upload", path))
        return "https://files.hedra.test/" + Path(path).name

    def estimate(self, body):
        self.calls.append(("estimate", body))
        return {"cost": self.cost, "currency": "USD"}

    def submit(self, body, key):
        self.calls.append(("submit", body, key))
        c = store.all_clips(self.pdir)[0]
        assert c["status"] == "submitted" and c["takes"][-1]["status"] == "unknown"
        assert ledger.spent_usd(self.pdir, "hedra") == self.cost
        if self.error:
            raise self.error
        return {"job_id": "job-test", "status": "IN_QUEUE"}

    def get(self, job_id):
        self.calls.append(("get", job_id))
        return self.result or {"status": "IN_PROGRESS"}


def test_sung_dry_run_is_offline_and_uses_audio(env, tmp_path, monkeypatch):
    cid = ready(env, tmp_path, "sung")
    monkeypatch.setattr(requests.Session, "request", lambda *a, **kw: pytest.fail("network on dry run"))
    before = store.clip_file(env, cid).read_bytes()
    rc, out = run(env, "clip", "submit", cid, "--hedra-transport", "mcp", "--dry-run")
    assert rc == 0, out
    assert not out["lock_problems"]
    assert out["would_send"]["duration_ms"] == 4000
    assert out["would_send"]["audios"][0]["url"] == "<<HEDRA_UPLOAD:audio>>"
    assert out["mcp_request"]["reference_image_urls"] == ["<<HEDRA_UPLOAD:start>>"]
    assert out["estimate"]["generation_tool"] == "generate_video"
    assert "start_image" not in out["would_send"]
    assert store.clip_file(env, cid).read_bytes() == before and not ledger.rows(env)


def test_api_submit_poll_delivery_settles_and_never_regenerates(env, tmp_path, monkeypatch):
    cid = ready(env, tmp_path, "sung")
    client = FakeHedra(env, result={"status": "COMPLETED", "cost": .4, "currency": "USD",
                                  "outputs": [{"status": "COMPLETED", "content_type": "video/mp4",
                                               "url": "https://output.hedra.test/take.mp4"}]})
    out = clips.submit(env, cid, yes=True, client=client)
    assert out["job"] == "job-test"
    sent = next(x[1] for x in client.calls if x[0] == "submit")
    assert sent["audios"][0]["url"].startswith("https://files.hedra.test/")
    assert "<<" not in json.dumps(sent)
    monkeypatch.setattr(hedra.higgsfield, "fetch_result", lambda url, path, **kw: path.write_bytes(b"video"))
    monkeypatch.setattr(clips, "probe_duration", lambda path: 4)
    out = clips.poll(env, [cid], client=client)
    assert out["results"][0]["status"] == "delivered"
    c = store.load(env, cid)
    assert c["takes"][0]["ref_audio"] and "clip sync" in out["text"]
    assert ledger.spent_usd(env, "hedra") == .4
    clips.poll(env, [cid], client=client)
    assert sum(x[0] == "submit" for x in client.calls) == 1


def test_quote_only_api_and_mcp_create_no_take_or_charge(env, tmp_path, monkeypatch):
    cid = ready(env, tmp_path)
    client = FakeHedra(env)
    out = clips.submit(env, cid, quote_only=True, client=client)
    assert out["quote_only"] and out["cost"] == .5 and out["currency"] == "USD"
    assert not any(x[0] == "submit" for x in client.calls)
    monkeypatch.setattr(clips, "auto_host", lambda *a: [])
    rc, out = run(env, "clip", "submit", cid, "--hedra-transport", "mcp", "--quote-only")
    assert rc == 0, out
    req = json.loads(Path(out["request_file"]).read_text())
    assert req["estimate"]["input"] == req["request"]
    assert req["uploads"] and not ledger.rows(env) and not store.load(env, cid)["takes"]


def test_failed_api_job_uses_reported_net_cost(env, tmp_path):
    cid = ready(env, tmp_path)
    client = FakeHedra(env, result={"status": "FAILED", "cost": 0, "currency": "USD",
                                  "error": {"code": "MODERATION_FAILED"}})
    clips.submit(env, cid, yes=True, client=client)
    out = clips.poll(env, [cid], client=client)
    assert out["results"][0]["status"] == "failed"
    assert ledger.spent_usd(env, "hedra") == 0


def test_unknown_http_response_never_retries():
    class Session:
        calls = 0
        def request(self, *a, **kw):
            self.calls += 1
            raise requests.ReadTimeout("secret-key")
    session = Session()
    with pytest.raises(hedra.HedraError) as err:
        hedra.Hedra(session=session, key="secret-key").submit({}, "stable")
    assert err.value.unknown and session.calls == 1 and "secret-key" not in str(err.value)


@pytest.mark.parametrize("unknown", [False, True])
def test_api_errors_reserve_uncertain_spend(env, tmp_path, unknown):
    cid = ready(env, tmp_path)
    client = FakeHedra(env, error=hedra.HedraError("simulated", unknown=unknown))
    with pytest.raises(hedra.HedraError):
        clips.submit(env, cid, yes=True, client=client)
    assert ledger.spent_usd(env, "hedra") == (.5 if unknown else 0)
    c = store.load(env, cid)
    assert c["status"] == ("submitted" if unknown else "locked")
    if unknown:
        with pytest.raises(SlopError, match="do not resubmit"):
            clips.submit(env, cid, yes=True, client=client, resubmit_unknown=True)
        out = clips.poll(env, [cid], job_id="job-recovered", client=client)
        assert "IN_PROGRESS" in out["text"]
        assert store.load(env, cid)["takes"][-1]["id"] == "job-recovered"


@pytest.mark.parametrize("currency,cost,flag", [("USD", 1.2, "--cost-usd"), ("credits", 10, "--credits")])
def test_mcp_reservation_pending_delivery_and_settlement(env, tmp_path, monkeypatch, currency, cost, flag):
    cid = ready(env, tmp_path)
    monkeypatch.setattr(requests.Session, "request", lambda *a, **kw: pytest.fail("MCP CLI made a provider call"))
    rc, out = run(env, "clip", "submit", cid, "--yes", "--hedra-transport", "mcp",
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
    assert run(env, "clip", "submit", cid, "--yes", "--hedra-transport", "mcp")[0] != 0
    assert not store.load(env, cid)["takes"] and not ledger.rows(env)
    assert run(env, "clip", "submit", cid, "--yes", "--hedra-transport", "mcp",
               "--hedra-cost", "10", "--hedra-currency", "credits")[0] == 0
    assert run(env, "clip", "ingest", cid, "--failed", "provider failed", "--cost-usd", "0")[0] != 0
    assert run(env, "clip", "ingest", cid, "--failed", "provider failed")[0] == 0
    assert ledger.spent_credits(env, "hedra") == 10  # no unsupported assumption of a refund
    assert run(env, "clip", "ingest", cid, "--credits", "0")[0] != 0  # reconcile by job id


@pytest.mark.parametrize("guard", ["free", "frozen", "cap", "approval"])
def test_guards_stop_paid_api_post(env, tmp_path, monkeypatch, guard):
    cid = ready(env, tmp_path)
    project = json.loads((env / "project.json").read_text())
    if guard == "free":
        monkeypatch.setenv("SLOP_FREE_ONLY", "1")
    if guard == "frozen":
        project["budget"]["frozen"] = "review first"
    if guard == "cap":
        project["budget"]["hedra_usd"] = .1
    (env / "project.json").write_text(json.dumps(project))
    client = FakeHedra(env)
    with pytest.raises(SlopError):
        clips.submit(env, cid, yes=guard != "approval", client=client)
    assert not any(x[0] == "submit" for x in client.calls)


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


def test_http_contract_and_auth_never_follows_redirects(tmp_path):
    class Session:
        def request(self, method, url, **kw):
            assert url.startswith(hedra.BASE) and kw["allow_redirects"] is False
            assert kw["headers"] == {"Authorization": "Key test-key"}
            if url.endswith("/files"):
                assert kw["files"]["file"][1].read() == b"image"
                return H.FakeResp(200, {"url": "https://files.test/image"})
            assert kw["json"]["idempotency_key"] == "stable-key"
            return H.FakeResp(202, {"job_id": "job-1"})
    p = tmp_path / "image.png"; p.write_bytes(b"image")
    client = hedra.Hedra(session=Session(), key="test-key")
    assert client.upload(p) == "https://files.test/image"
    assert client.submit({"prompt": "test"}, "stable-key")["job_id"] == "job-1"


@pytest.mark.parametrize("status,unknown", [(401, False), (402, False), (422, False), (429, False), (500, True), (409, True)])
def test_http_errors_do_not_retry_paid_calls(status, unknown):
    class Session:
        calls = 0
        def request(self, *a, **kw):
            self.calls += 1
            return H.FakeResp(status, {"error": "secret-key must not be echoed"})
    session = Session()
    with pytest.raises(hedra.HedraError) as err:
        hedra.Hedra(session=session, key="secret-key").submit({}, "key")
    assert err.value.unknown is unknown and session.calls == 1
    assert "secret-key" not in str(err.value)


def test_onboarding_recognizes_hedra_key(monkeypatch):
    from slop.onboard import items
    ctx = items.Ctx.__new__(items.Ctx)
    ctx.env = {"HEDRA_API_KEY": True}
    assert items.route_ok(ctx, "hedra")


def test_onboarding_hedra_unlocks_video_without_other_providers():
    from test_onboard_items import rep
    r = rep("studio", env={"HEDRA_API_KEY": True}, key={"present": False, "valid": False})
    video = next(x for x in r["items"] if x["id"] == "video")
    assert video["state"] == "done" and "Hedra" in video["data"]["via"]

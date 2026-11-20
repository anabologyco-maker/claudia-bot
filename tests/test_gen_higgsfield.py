"""Higgsfield path: the request file the bot executes with its MCP connector, and result ingest."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest

_H = Path(__file__).parent / "fixtures" / "gen" / "helpers.py"
_spec = importlib.util.spec_from_file_location("gen_test_helpers", _H)
H = importlib.util.module_from_spec(_spec); sys.modules.setdefault("gen_test_helpers", H); _spec.loader.exec_module(H)

from slop import ledger  # noqa: E402
from slop.cli import main  # noqa: E402
from slop.gen import higgsfield as hf, store, templates as tpl  # noqa: E402

pytestmark = pytest.mark.skipif(not H.FFMPEG, reason="ffmpeg is required")


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)           # the Higgsfield path needs no key
    monkeypatch.delenv("SLOP_PROJECT", raising=False)
    H.write_cache(tmp_path / "home")
    return H.make_project(tmp_path / "projects")


def run(pdir, *argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(["--json", "--project", str(pdir), *argv])
    return rc, json.loads(buf.getvalue())


def ready(env, tmp_path, shot, kind, *extra):
    rc, out = run(env, "clip", "new", shot, "--kind", kind, "--provider", "higgsfield", *extra)
    cid = out["clip_id"]
    c = store.load(env, cid)
    f = tmp_path / f"{cid}.txt"; f.write_text(tpl.SLOT_RE.sub("she moves", c["body"]["prompt"]), encoding="utf-8")
    assert run(env, "clip", "set", cid, "--prompt-file", str(f))[0] == 0
    rc, out = run(env, "clip", "lock", cid)
    assert rc == 0, out
    return cid


def test_sung_request_shape(env, tmp_path):
    cid = ready(env, tmp_path, "s002", "sung")
    rc, out = run(env, "clip", "submit", cid, "--yes", "--res", "480p")
    assert rc == 0, out
    req = json.loads(Path(out["request_file"]).read_text())
    prm = req["request"]["params"]
    assert prm["model"] == "seedance_2_5" and prm["mode"] == "omni_reference" and prm["resolution"] == "480p"
    assert prm["draft"] is True and prm["duration"] == 4 and prm["aspect_ratio"] == "16:9"
    assert "generate_audio" not in prm                                 # sung: omitted (= true)
    assert [m["role"] for m in prm["medias"]] == ["image_references", "audio_references"]
    assert prm["medias"][0]["value"] == f"<<MEDIA_ID:{cid}__image_references__0>>"
    assert [u["type"] for u in req["uploads"]] == ["image", "audio"] and req["uploads"][1]["filename"].endswith(".mp3")
    assert req["estimate"] == {"tool": "estimate_video_cost", "params": prm} and req["expected_credits"] == 12
    assert any("generate_video_batch" in s for s in req["how_to_run"])
    assert any(s.startswith("PREFLIGHT (free): estimate_video_cost") for s in req["how_to_run"])
    _never_generate_video_with_get_cost(req)
    assert req["warnings"] and "late" in req["warnings"][0]            # the Higgsfield pre-roll tail warning
    c = store.load(env, cid)
    assert c["status"] == "submitted" and c["takes"][0]["status"] == "requested"
    row = ledger.rows(env)[-1]
    assert row["provider"] == "higgsfield" and row["credits"] == 12 and ledger.spent_credits(env) == 12


def test_motion_first_frame_request_and_renumbering(env, tmp_path):
    cid = ready(env, tmp_path, "s004", "motion", "--frame", "first")
    c = store.load(env, cid)
    c["refs"] = ["plates/cands/hall/1.png"]
    c["body"]["prompt"] = "Moving in time with @Audio1. The woman from @Image1 walks. No cuts."
    store.save(env, c)
    req = hf.build_request(env, store.load(env, cid), resolution="720p")
    prm = req["request"]["params"]
    assert [m["role"] for m in prm["medias"]] == ["start_image", "image_references", "audio_references"]
    assert prm["generate_audio"] is False and "draft" not in prm
    assert "@Image2" in prm["prompt"] and "@Image1" not in prm["prompt"] and req["prompt_note"]
    assert req["expected_credits"] == 7 * 5


def test_known_media_ids_skip_uploads(env, tmp_path):
    cid = ready(env, tmp_path, "s002", "sung")
    assert run(env, "gen", "host", cid, "--role", "start", "--media-id", "11111111-2222-4333-8444-555555555555")[0] == 0
    assert run(env, "gen", "host", cid, "--url", "https://d1.cloudfront.example/u/a.mp3", "--media-id",
               "66666666-2222-4333-8444-555555555555")[0] == 0
    req = hf.build_request(env, store.load(env, cid))
    assert [m["value"] for m in req["request"]["params"]["medias"]] == ["11111111-2222-4333-8444-555555555555",
                                                                        "66666666-2222-4333-8444-555555555555"]
    assert not req["uploads"]
    assert store.load(env, cid)["window"]["url"] == "https://d1.cloudfront.example/u/a.mp3"


def test_ingest_pending_url_and_failure(env, tmp_path, monkeypatch):
    cid = ready(env, tmp_path, "s002", "sung")
    run(env, "clip", "submit", cid, "--yes")
    rc, out = run(env, "clip", "ingest", cid, "--pending", "--job-id", "job-1")
    assert rc == 0 and store.load(env, cid)["takes"][0]["status"] == "pending"
    rc, out = run(env, "clip", "poll")
    assert "jobs_wait" in out["text"]
    take = H.make_mp4(tmp_path / "res.mp4", None, duration=2)
    s = H.FakeSession({("GET", "cloudfront"): H.FakeResp(200, content=take.read_bytes())})
    import requests
    monkeypatch.setattr(requests, "Session", lambda: s)
    rc, out = run(env, "clip", "ingest", cid, "--url", "https://d2.cloudfront.example/res.mp4", "--job-id", "job-1",
                  "--credits", "30")
    assert rc == 0, out
    assert "Authorization" not in s.calls[0]["headers"]                # public URL: no key is ever sent
    c = store.load(env, cid)
    assert c["status"] == "delivered" and c["takes"][0]["file"] == f"clips/{cid}/take-1.mp4" and c["takes"][0]["credits"] == 30
    assert ledger.spent_credits(env) == 30                               # 28 estimated + 2 adjustment
    rc, out = run(env, "clip", "ingest", cid, "--url", "https://d2.cloudfront.example/res.mp4", "--job-id", "job-1")
    assert rc == 0 and "already ingested" in out["text"] and len(store.load(env, cid)["takes"]) == 1
    # a second request that the silent input filter fails is refunded and goes back to locked
    run(env, "clip", "lock", cid)
    run(env, "clip", "submit", cid, "--yes")
    rc, out = run(env, "clip", "ingest", cid, "--failed", "failed with no reason (filter)")
    assert rc == 0 and "reword" in out["text"]
    assert store.load(env, cid)["status"] == "locked" and ledger.spent_credits(env) == 30


def test_duration_limits(env, tmp_path):
    cid = ready(env, tmp_path, "s004", "motion")
    c = store.load(env, cid); c["body"]["duration"] = 10; store.save(env, c)
    with pytest.raises(Exception, match="4–8 s"):
        hf.build_request(env, c)


# ------------------------------------------------------------------------------------------------ the price check
DRAFT_JOB = "0f8fad5b-d9cb-469f-a165-70867728950e"


def _never_generate_video_with_get_cost(req: dict) -> None:
    """The connector's generate_video no longer takes get_cost ("Price a request with estimate_video_cost"): no key,
    no params and no step of a request file asks for it; the steps name get_cost only to keep it out of the batch."""
    assert "get_cost" not in req and "get_cost" not in req["request"]["params"]
    assert req["estimate"]["tool"] == "estimate_video_cost" and req["estimate"]["params"] == req["request"]["params"]
    assert '"get_cost"' not in json.dumps(req)
    for s in req["how_to_run"]:
        assert "generate_video {" not in s and "generate_video(" not in s, s
        assert s.count("get_cost") == s.count("never add get_cost"), s


def test_the_request_prices_with_estimate_video_cost_never_get_cost(env, tmp_path):
    cid = ready(env, tmp_path, "s002", "sung")
    rc, out = run(env, "clip", "submit", cid, "--yes", "--res", "480p")
    assert rc == 0, out
    req = json.loads(Path(out["request_file"]).read_text())
    _never_generate_video_with_get_cost(req)
    pre = next(s for s in req["how_to_run"] if s.startswith("PREFLIGHT"))
    assert "estimate_video_cost {params: <request.params, unchanged>}" in pre and "submits nothing" in pre
    assert "expect about 12 credits" in pre and "never an https URL" in pre
    # the finalize request prices itself the same way
    c = store.load(env, cid)
    fin = hf.build_finalize(env, c, {"id": DRAFT_JOB, "n": 1, "body": dict(req["request"]["params"])})
    _never_generate_video_with_get_cost(fin)
    assert fin["how_to_run"][0].startswith("PREFLIGHT (free): estimate_video_cost")
    assert "REJECTED below" in fin["how_to_run"][0] and "estimate_video_cost is the truth" in fin["how_to_run"][0]


# a request file as 0.3.6 wrote it: the price from generate_video + get_cost (the connector refuses that flag now)
OLD_PREFLIGHT = ('PREFLIGHT (free): generate_video {params: <request.params plus "get_cost": true>} (= the `get_cost` '
                 'object in this file) — expect about 12 credits; stop and tell the user if it differs. medias[].value '
                 'must be a media_id (never an https URL).')
OLD_UNLIM = ('If the reply is an `unlim_choice` question instead of a job (the account holds free generations): ask the '
             'user, then send the same request again with use_unlim set to their answer. Never set use_unlim yourself. '
             'If the item is refused with a preset recommendation: resubmit only that item once with declined_preset_id '
             'set to that preset id. On a transport timeout: do NOT resubmit and do NOT record it as rejected; check '
             '`transactions` first (a charge or a job there: it ran, record that job id).')
OLD_REJECTED = ('REJECTED (an error instead of a price or a job id: get_cost or the batch refuses the request, or the '
                'balance is too low; NOT an unlim_choice question, the one preset resubmit above, or a timeout): nothing '
                'was charged. Stop, tell the user, and record it at once (the ledger then counts 0): slop -p demo clip '
                'ingest {cid} --failed "rejected: <the reply, verbatim>". The same when the user says not to send it '
                'after get_cost: --failed "rejected: not sent, <why>".')
OLD_FIN_PREFLIGHT = ('PREFLIGHT (free): generate_video {params: <request.params plus "get_cost": true>} (= the `get_cost` '
                     'object) - expect about 48 credits (finalize prices are not published: get_cost is the truth). If it '
                     'differs: stop and tell the user. If it refuses the finalize instead of a price (asks for medias, '
                     'refuses the draft_job_id, any error): do not invent other params and do not submit - REJECTED below.')
OLD_FIN_REJECTED = ('REJECTED (an error instead of a price or a job id: get_cost or the batch refuses the finalize, or the '
                    'balance is too low; NOT an unlim_choice question or a timeout): nothing was charged and the draft '
                    "stays the clip's take. Tell the user and record it at once, never leave it requested (the ledger then "
                    'counts 0, status shows it rejected): slop -p demo clip ingest {cid} --failed "rejected: <the reply, '
                    'verbatim>" (the user says not to send it after get_cost: --failed "rejected: not sent, <why>"). Then '
                    'stop: do not re-lock or resubmit the clip (any retry advice that command prints is for a new take, not '
                    'for a finalize).')


def _as_written_by_036(req: dict, cid: str) -> dict:
    old = json.loads(json.dumps(req))
    old["get_cost"] = {"params": {**old.pop("estimate")["params"], "get_cost": True}}
    was = {"PREFLIGHT": OLD_PREFLIGHT, "If the reply": OLD_UNLIM, "REJECTED": OLD_REJECTED.format(cid=cid)}
    old["how_to_run"] = [next((v for k, v in was.items() if s.startswith(k)), s) for s in old["how_to_run"]]
    return old


def test_an_old_request_file_with_get_cost_still_loads(env, tmp_path, monkeypatch):
    monkeypatch.setenv("SLOP_PROJECTS", str(env.parent))                # hint lines name the project: slop -p demo
    cid = ready(env, tmp_path, "s002", "sung")
    rc, out = run(env, "clip", "submit", cid, "--yes", "--res", "480p")
    assert rc == 0, out
    p = Path(out["request_file"])
    new = json.loads(p.read_text(encoding="utf-8"))
    assert hf.upgrade_request(json.loads(json.dumps(new))) == new                  # a current file: unchanged
    old = _as_written_by_036(new, cid)
    assert old["how_to_run"] != new["how_to_run"] and "get_cost" in old
    p.write_text(json.dumps(old, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    got = hf.read_request(p)                                                       # the old key, read as the quote
    assert got["estimate"] == new["estimate"] and "get_cost" not in got
    # its PREFLIGHT and REJECTED steps read as 0.3.7 writes them; every other step stays as it was written
    assert got["how_to_run"] == [n if n.startswith(("PREFLIGHT", "REJECTED")) else o
                                 for o, n in zip(old["how_to_run"], new["how_to_run"])]
    _never_generate_video_with_get_cost(got)
    # `gen host` fills a media id into both copies of an old file and rewrites it in the current shape
    ph = f"<<MEDIA_ID:{cid}__image_references__0>>"
    assert ph in json.dumps(old["get_cost"]["params"]["medias"])
    mid = "11111111-1111-4111-8111-111111111111"
    rc, out = run(env, "gen", "host", cid, "--role", "start", "--media-id", mid)
    assert rc == 0 and out["request_file"], out
    req = json.loads(p.read_text(encoding="utf-8"))
    assert [m["value"] for m in req["request"]["params"]["medias"]][0] == mid
    assert req["estimate"]["params"] == req["request"]["params"] and "get_cost" not in req
    _never_generate_video_with_get_cost(req)
    # an old finalize request: the same quote, and its PREFLIGHT and REJECTED steps as 0.3.7 writes them
    now = hf.build_finalize(env, store.load(env, cid), {"id": DRAFT_JOB, "n": 1, "body": dict(new["request"]["params"])})
    was = {"PREFLIGHT": OLD_FIN_PREFLIGHT, "REJECTED": OLD_FIN_REJECTED.format(cid=cid)}
    fin = json.loads(json.dumps(now))
    fin["get_cost"] = {"params": {**fin.pop("estimate")["params"], "get_cost": True}}
    fin["how_to_run"] = [next((v for k, v in was.items() if s.startswith(k)), s) for s in fin["how_to_run"]]
    assert fin["how_to_run"] != now["how_to_run"] and now["expected_credits"] == 48
    up = hf.upgrade_request(fin, env)
    assert up["estimate"] == now["estimate"] and up["how_to_run"] == now["how_to_run"] and "get_cost" not in up
    _never_generate_video_with_get_cost(up)
    # an old file without steps, and a missing file
    bare = hf.upgrade_request({"request": {"params": {"model": "m"}}, "get_cost": {"params": {"model": "m", "get_cost": 1}}})
    assert bare == {"request": {"params": {"model": "m"}}, "estimate": {"tool": "estimate_video_cost", "params": {"model": "m"}}}
    assert hf.read_request(tmp_path / "missing.json") is None

"""Fixes track (critic P1/P2 + phase-2 UX), gen side, offline: every gen hint line names the project (-p), the start
image goes on the tunnel for Higgsfield media_import_url (`gen host --role start --tunnel`, refreshing an open request
file), `clip submit` hosts the window / start itself while the tunnel runs, `clip submit --finalize-from TAKE` writes a
draft_job_id finalize request (estimate_video_cost first) and requires `clip sync` after, and a partial sync says
PARTIAL."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
import time
from pathlib import Path

import pytest

_H = Path(__file__).parent / "fixtures" / "gen" / "helpers.py"
_spec = importlib.util.spec_from_file_location("gen_test_helpers", _H)
H = importlib.util.module_from_spec(_spec); sys.modules.setdefault("gen_test_helpers", H); _spec.loader.exec_module(H)

from slop import ledger  # noqa: E402
from slop.cli import main  # noqa: E402
from slop.gen import clips, hints, hosting, store, templates as tpl  # noqa: E402
from slop.util import with_project_flag  # noqa: E402

KEY = "sk-or-v1-test-not-a-real-key"
needs_ffmpeg = pytest.mark.skipif(not H.FFMPEG, reason="ffmpeg is required")
DRAFT_JOB = "0f8fad5b-d9cb-469f-a165-70867728950e"
FINAL_JOB = "7c9e6679-7425-40de-944b-e07fc1f90ae7"
TUN = "https://brave-tiny-words-here.trycloudflare.com"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SLOP_PROJECTS", str(tmp_path / "projects"))
    monkeypatch.setenv("OPENROUTER_API_KEY", KEY)
    monkeypatch.delenv("SLOP_PROJECT", raising=False)
    H.write_cache(tmp_path / "home")
    return H.make_project(tmp_path / "projects", audio=bool(H.FFMPEG))


def run(pdir, *argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(["--json", "--project", str(pdir), *argv])
    return rc, json.loads(buf.getvalue())


def fake(monkeypatch, routes):
    s = H.FakeSession(routes)
    import requests
    monkeypatch.setattr(requests, "Session", lambda: s)
    return s


def tunnel(monkeypatch, running: bool = True, verified: bool = True) -> list[str]:
    """a fake running quick tunnel: publish() records the names it was given; its public URL answers unless
    verified=False (a new hostname that does not resolve yet)."""
    names: list[str] = []
    monkeypatch.setattr(hosting, "status", lambda: {"running": running, "url": TUN if running else None})
    monkeypatch.setattr(hosting, "ensure_verified", lambda wait_s=20.0: {"verified": True} if running and verified else
                        {"verified": False, "error": "Name or service not known"})

    def publish(path, name=None):
        if not running:
            raise AssertionError("published while the tunnel is down")
        names.append(name)
        return f"{TUN}/tok/{name}"
    monkeypatch.setattr(hosting, "publish", publish)
    monkeypatch.setattr(hosting, "start", lambda **kw: {"running": True, "url": TUN, "verified": True})
    return names


def sung_locked(env, tmp_path, cid="W01", shot="s002", *extra) -> dict:
    rc, out = run(env, "clip", "new", shot, "--kind", "sung", "--id", cid, *extra)
    assert rc == 0, out
    c = store.load(env, cid)
    f = tmp_path / f"{cid}.txt"; f.write_text(tpl.SLOT_RE.sub("she sings it softly", c["body"]["prompt"]), encoding="utf-8")
    assert run(env, "clip", "set", cid, "--prompt-file", str(f))[0] == 0
    rc, out = run(env, "clip", "lock", cid)
    assert rc == 0, out
    return store.load(env, cid)


# ------------------------------------------------------------------------------------------------ -p on every hint
def test_hint_lines_get_the_project_flag():
    assert with_project_flag("next: slop clip submit W01 --yes", "demo") == "next: slop -p demo clip submit W01 --yes"
    s = "run slop gen tunnel start, then `slop plates book`; python -m slop clip poll"
    assert with_project_flag(s, "demo") == ("run slop -p demo gen tunnel start, then `slop -p demo plates book`; "
                                            "python -m slop -p demo clip poll")
    for keep in ("slop -p other clip lock W01", "slop --project other clip lock W01", "claudia and slop.gen.serve",
                 "slop new NAME", "slop doctor"):
        assert with_project_flag(keep, "demo") == keep
    assert with_project_flag(with_project_flag("slop clip list", "a b"), "a b") == "slop -p a b clip list"
    out = hints.stamp({"text": "slop clip sync W01", "warnings": ["slop clip set W01 --recut"],
                       "results": [{"next": "slop clip poll W01"}]}, Path("/x/demo"))
    assert out["text"].startswith("slop -p ") and "clip sync W01" in out["text"]
    assert out["warnings"][0].startswith("slop -p ") and out["results"][0]["next"].startswith("slop -p ")


@needs_ffmpeg
def test_clip_hints_and_errors_name_the_project(env, tmp_path):
    rc, out = run(env, "clip", "new", "s002", "--kind", "sung")
    assert rc == 0 and "slop -p demo clip set W01 --prompt-file FILE" in out["text"]
    assert "slop clip " not in out["text"].replace("slop -p demo clip ", "")
    rc, out = run(env, "clip", "lock", "W01")                            # [[slots]] still open: an error with hints
    assert rc == 1 and "slop -p demo clip set W01 --prompt-file FILE" in out["error"]
    with pytest.raises(Exception, match="slop -p demo clip set W01"):
        clips.lock(env, "W01")


# ------------------------------------------------------------------------------------------------ hosting
@needs_ffmpeg
def test_openrouter_submit_hosts_the_window_itself_when_the_tunnel_runs(env, tmp_path, monkeypatch):
    sung_locked(env, tmp_path)
    tunnel(monkeypatch, running=False)
    rc, out = run(env, "clip", "submit", "W01", "--yes")
    assert rc == 1 and "slop -p demo gen tunnel start" in out["error"] and "If-None-Match: *" in out["error"]
    names = tunnel(monkeypatch, running=True)
    s = fake(monkeypatch, {("POST", "/videos"): H.FakeResp(202, {"id": "gen-vid-1", "status": "pending"})})
    rc, out = run(env, "clip", "submit", "W01", "--yes")
    assert rc == 0, out
    refs = s.calls[-1]["body"]["input_references"]
    audio = [r["audio_url"]["url"] for r in refs if r.get("type") == "audio_url"]
    assert audio == [f"{TUN}/tok/demo__W01.wav"] and names == ["demo__W01.wav"]
    assert any("hosted the window on the running tunnel" in w for w in out["warnings"])
    c = store.load(env, "W01")
    assert c["window"]["url_mode"] == "tunnel" and c["hosted"]["audio"]["sha1"] == store.file_sha1(env / c["window"]["wav"])
    assert "slop -p demo clip poll W01" in out["text"]


@needs_ffmpeg
def test_higgsfield_submit_hosts_start_and_window_for_media_import_url(env, tmp_path, monkeypatch):
    sung_locked(env, tmp_path, "W01", "s002", "--provider", "higgsfield")
    names = tunnel(monkeypatch, running=True)
    rc, out = run(env, "clip", "submit", "W01", "--yes", "--res", "480p")
    assert rc == 0, out
    req = json.loads((env / "clips" / "W01" / "higgsfield-request.json").read_text(encoding="utf-8"))
    ups = {u["hosted_key"]: u for u in req["uploads"]}
    assert set(ups) == {"start", "audio"} and all(u["method"] == "media_import_url" for u in ups.values())
    assert ups["start"]["https_url"] == f"{TUN}/tok/demo__W01__start.png" and ups["audio"]["https_url"].endswith(".wav")
    assert sorted(names) == ["demo__W01.wav", "demo__W01__start.png"]
    assert "media_import_url" in req["how_to_run"][0] and "If-None-Match: *" in req["how_to_run"][0]
    assert all("slop clip " not in step for step in req["how_to_run"])          # every hint names the project
    assert any("slop -p " in step and "clip ingest W01" in step for step in req["how_to_run"])
    assert "hosted start, audio on the running tunnel" in out["text"]
    c = store.load(env, "W01")
    assert c["hosted"]["start"]["sha1"] == store.file_sha1(env / c["start"])


@needs_ffmpeg
def test_without_a_tunnel_the_request_says_how_to_upload_and_gen_host_switches_it(env, tmp_path, monkeypatch):
    sung_locked(env, tmp_path, "W01", "s002", "--provider", "higgsfield")
    tunnel(monkeypatch, running=False)
    rc, out = run(env, "clip", "submit", "W01", "--yes", "--res", "480p")
    assert rc == 0, out
    p = env / "clips" / "W01" / "higgsfield-request.json"
    req = json.loads(p.read_text(encoding="utf-8"))
    assert all(u["method"] == "media_upload" and u["curl_header"] == "If-None-Match: *" and not u["https_url"]
               for u in req["uploads"])
    assert any("If-None-Match" in w and "--role start --tunnel" in w for w in out["warnings"])
    # the tunnel comes up later: gen host --role start --tunnel puts the plate on it and updates the open request
    names = tunnel(monkeypatch, running=True)
    rc, out = run(env, "gen", "host", "W01", "--role", "start", "--tunnel")
    assert rc == 0 and out["role"] == "start" and out["url"] == f"{TUN}/tok/demo__W01__start.png", out
    assert "media_import_url" in out["text"] and out["request_file"] == "clips/W01/higgsfield-request.json"
    req = json.loads(p.read_text(encoding="utf-8"))
    ups = {u["hosted_key"]: u for u in req["uploads"]}
    assert ups["start"]["method"] == "media_import_url" and ups["start"]["https_url"] == out["url"]
    assert ups["audio"]["method"] == "media_upload"
    # a media_id recorded afterwards goes straight into the request's medias
    mid = "11111111-1111-4111-8111-111111111111"
    rc, out = run(env, "gen", "host", "W01", "--role", "start", "--media-id", mid)
    req = json.loads(p.read_text(encoding="utf-8"))
    assert rc == 0 and [u["hosted_key"] for u in req["uploads"]] == ["audio"]
    assert any(m["value"] == mid for m in req["request"]["params"]["medias"])
    assert any(m["value"] == mid for m in req["estimate"]["params"]["medias"])   # the price check prices the same
    assert names == ["demo__W01__start.png"]


@needs_ffmpeg
def test_a_changed_start_image_is_not_imported_from_the_old_url(env, tmp_path, monkeypatch):
    from slop.gen import higgsfield as hf
    sung_locked(env, tmp_path, "W01", "s002", "--provider", "higgsfield")
    tunnel(monkeypatch, running=True)
    assert run(env, "gen", "host", "W01", "--role", "start", "--tunnel")[0] == 0
    c = store.load(env, "W01")
    req = hf.build_request(env, c, resolution="480p")
    assert {u["hosted_key"]: u["method"] for u in req["uploads"]}["start"] == "media_import_url"
    H.write_png(env / c["start"], (1, 2, 3))                              # the plate file changed after hosting
    req = hf.build_request(env, store.load(env, "W01"), resolution="480p")
    assert {u["hosted_key"]: u["method"] for u in req["uploads"]}["start"] == "media_upload"


# ------------------------------------------------------------------------------------------------ finalize
def _deliver(env, cid: str, job: str, credits: float, tmp_path: Path, n: int) -> dict:
    c = store.load(env, cid)
    mp4 = H.make_mp4(tmp_path / f"take{n}.mp4", env / c["window"]["wav"], duration=4,
                     size=f"{300 + 20 * n}x180")                       # distinct bytes per take
    assert run(env, "clip", "ingest", cid, "--job-id", job, "--pending")[0] == 0
    rc, out = run(env, "clip", "ingest", cid, "--file", str(mp4), "--job-id", job, "--credits", str(credits))
    assert rc == 0, out
    return out


@needs_ffmpeg
def test_finalize_a_kept_draft_then_sync_is_required(env, tmp_path, monkeypatch):
    sung_locked(env, tmp_path, "W01", "s002", "--provider", "higgsfield")
    tunnel(monkeypatch, running=False)
    assert run(env, "clip", "submit", "W01", "--yes", "--res", "480p")[0] == 0
    _deliver(env, "W01", DRAFT_JOB, 12, tmp_path, 1)
    rc, out = run(env, "clip", "submit", "W01", "--finalize-from", "1", "--yes")
    assert rc == 1 and "measure the draft first" in out["error"] and "slop -p demo clip sync W01 --take 1" in out["error"]
    c = store.load(env, "W01")
    c["takes"][0]["sync"] = {"mode": "none", "ncc": .05}
    store.save(env, c)
    rc, out = run(env, "clip", "submit", "W01", "--finalize-from", "1", "--yes")
    assert rc == 1 and "did not copy" in out["error"]
    c["takes"][0]["sync"] = {"mode": "copy", "ncc": .49, "lag_s": .475, "synced": [[10.0, 11.5]]}
    store.save(env, c)
    n_rows = len(ledger.rows(env))
    rc, out = run(env, "clip", "submit", "W01", "--finalize-from", "1", "--dry-run")
    assert rc == 0 and out["dry_run"] and out["would_send"]["draft_job_id"] == DRAFT_JOB, out
    assert out["would_send"]["resolution"] == "1080p" and "medias" not in out["would_send"]
    assert "slop -p demo clip submit W01 --provider higgsfield --finalize-from 1 --yes" in out["text"]
    assert len(ledger.rows(env)) == n_rows and not list((env / "clips/W01").glob("higgsfield-take-*-finalize-*.json"))
    rc, out = run(env, "clip", "submit", "W01", "--finalize-from", "1")
    assert rc == 1 and "--yes" in out["error"]
    rc, out = run(env, "clip", "submit", "W01", "--provider", "openrouter", "--finalize-from", "1", "--yes")
    assert rc == 1 and "--provider higgsfield" in out["error"]
    rc, out = run(env, "clip", "submit", "W01", "--provider", "higgsfield", "--finalize-from", "1", "--yes")
    assert rc == 0 and out["finalize_of"] == 1 and out["expected_credits"] == 48, out
    assert out["request_file"].endswith("higgsfield-take-2-finalize-of-1.json")
    req = json.loads((env / "clips/W01/higgsfield-take-2-finalize-of-1.json").read_text(encoding="utf-8"))
    prm = req["request"]["params"]
    assert prm["draft_job_id"] == DRAFT_JOB and prm["resolution"] == "1080p" and prm["mode"] == "omni_reference"
    assert "draft" not in prm and "medias" not in prm and "get_cost" not in req
    assert req["estimate"] == {"tool": "estimate_video_cost", "params": prm}
    assert req["how_to_run"][0].startswith("PREFLIGHT (free): estimate_video_cost {params: <request.params, unchanged>}")
    assert prm["prompt"] == c["takes"][0]["body"]["prompt"]                   # the draft's prompt, verbatim
    assert any(s.startswith("REQUIRED after the ingest: slop -p demo clip sync W01") for s in req["how_to_run"])
    row = ledger.rows(env)[-1]
    assert row["kind"] == "video-finalize" and row["credits"] == 48 and row["units"]["finalize_of"] == 1
    c = store.load(env, "W01")
    assert c["status"] == "submitted" and c["takes"][1]["finalize_of"] == 1 and c["takes"][1]["needs_sync"] is True
    # while it is in flight, and after it is delivered, the same draft is never finalized (paid) again by accident
    rc, again = run(env, "clip", "submit", "W01", "--finalize-from", "1", "--yes")
    assert rc == 1 and "already finalized as take 2" in again["error"] and "--again" in again["error"], again
    out = _deliver(env, "W01", FINAL_JOB, 48, tmp_path, 2)
    assert out["next"] == "slop -p demo clip sync W01 --take 2" and "REQUIRED next" in out["text"]
    assert "NO lag correction" in out["text"] and "keeps the measured draft" not in out["text"]
    assert not any("keeps using the measured draft" in x for x in req["how_to_run"])
    rc, st = run(env, "clip", "status", "W01")
    assert "(finalize of take 1) NEEDS SYNC" in st["text"]
    n_rows = len(ledger.rows(env))
    rc, again = run(env, "clip", "submit", "W01", "--finalize-from", "1", "--yes")
    assert rc == 1 and "already finalized as take 2 (delivered)" in again["error"], again
    assert "slop -p demo clip sync W01 --take 2" in again["error"] and len(ledger.rows(env)) == n_rows
    first = (env / "clips/W01/higgsfield-take-2-finalize-of-1.json").read_bytes()
    # only on the owner's word: --again opens take 3 with its OWN request file (take 2's file is untouched)
    rc, out3 = run(env, "clip", "submit", "W01", "--finalize-from", "1", "--again", "--yes")
    assert rc == 0 and out3["take"] == 3 and out3["request_file"].endswith("higgsfield-take-3-finalize-of-1.json"), out3
    assert (env / "clips/W01/higgsfield-take-2-finalize-of-1.json").read_bytes() == first
    assert store.load(env, "W01")["takes"][1]["request_file"] == "clips/W01/higgsfield-take-2-finalize-of-1.json"
    assert len(ledger.rows(env)) == n_rows + 1
    rc, bad = run(env, "clip", "submit", "W01", "--again", "--yes")
    assert rc == 1 and "--again only goes with --finalize-from" in bad["error"]
    assert run(env, "clip", "ingest", "W01", "--failed", "finalize refused")[0] == 0
    # a finalized take is never finalized again; an old draft is refused
    rc, out = run(env, "clip", "submit", "W01", "--finalize-from", "2", "--yes")
    assert rc == 1 and "already a finalized take" in out["error"]
    c = store.load(env, "W01")
    c["takes"][0]["submitted"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - 9 * 86400))
    store.save(env, c)
    rc, out = run(env, "clip", "submit", "W01", "--finalize-from", "1", "--yes")
    assert rc == 1 and "days old" in out["error"]


@needs_ffmpeg
def test_finalize_refuses_an_openrouter_take(env, tmp_path, monkeypatch):
    sung_locked(env, tmp_path)
    tunnel(monkeypatch, running=True)
    fake(monkeypatch, {("POST", "/videos"): H.FakeResp(202, {"id": "gen-vid-1", "status": "pending"})})
    assert run(env, "clip", "submit", "W01", "--yes")[0] == 0
    rc, out = run(env, "clip", "submit", "W01", "--finalize-from", "1", "--yes")
    assert rc == 1 and "only a Higgsfield draft" in out["error"]
    rc, out = run(env, "clip", "submit", "W01", "--finalize-from", "5", "--yes")
    assert rc == 1 and "has 1 take(s)" in out["error"]


# ------------------------------------------------------------------------------------------------ sync verdict
@needs_ffmpeg
def test_partial_sync_says_partial(env, tmp_path, monkeypatch):
    from slop.sync import avsync
    sung_locked(env, tmp_path)
    c = store.load(env, "W01")
    mp4 = H.make_mp4(tmp_path / "t.mp4", env / c["window"]["wav"], duration=4)
    assert run(env, "clip", "ingest", "W01", "--file", str(mp4), "--provider", "manual")[0] == 0
    spans = [[9.0, 11.0], [11.4, 13.5]]        # the needed span s002 = 10.0-12.6 s; one 0.34 s hole (under 0.6 s)
    monkeypatch.setattr(avsync, "check", lambda *a_, **k: {
        "lag_s": .1, "lag_ncc": .5, "spans_song": spans, "synced_from": .01, "synced_until_song": 13.5,
        "diverges": False, "diverge_at_song": None, "cut_eighth_song": None, "cut_beat_song": None, "dips": [],
        "words_at_divergence": None, "mode": "copy"})
    rc, out = run(env, "clip", "sync", "W01", "--no-png")
    assert rc == 0, out
    assert out["gaps"] == [] and .8 < out["share"] < .95, out
    assert "PARTIAL:" in out["text"] and "no cover needed" in out["text"] and "in sync for the needed" not in out["text"]


# ------------------------------------------------------------------------------------------------ review round 2
@needs_ffmpeg
def test_paid_openrouter_submit_waits_for_a_tunnel_that_answers(env, tmp_path, monkeypatch):
    sung_locked(env, tmp_path)
    tunnel(monkeypatch, running=True, verified=False)              # a new hostname that does not resolve yet
    s = fake(monkeypatch, {("POST", "/videos"): H.FakeResp(202, {"id": "gen-vid-1", "status": "pending"})})
    n_rows = len(ledger.rows(env))
    rc, out = run(env, "clip", "submit", "W01", "--yes")
    assert rc == 1 and "does not answer yet" in out["error"] and "Nothing was sent or spent" in out["error"], out
    assert "slop -p demo gen tunnel status --verify" in out["error"]
    assert not s.calls and len(ledger.rows(env)) == n_rows and not store.load(env, "W01").get("takes")
    assert store.load(env, "W01")["hosted"]["audio"]["url"].startswith(TUN)          # what was hosted is kept
    tunnel(monkeypatch, running=True, verified=True)
    rc, out = run(env, "clip", "submit", "W01", "--yes")
    assert rc == 0 and len(s.calls) == 1, out


@needs_ffmpeg
def test_higgsfield_request_warns_when_the_tunnel_does_not_answer(env, tmp_path, monkeypatch):
    sung_locked(env, tmp_path, "W01", "s002", "--provider", "higgsfield")
    tunnel(monkeypatch, running=True, verified=False)
    rc, out = run(env, "clip", "submit", "W01", "--yes", "--res", "480p")
    assert rc == 0 and any("does not answer yet" in w and "slop -p demo gen tunnel status --verify" in w
                           for w in out["warnings"]), out
    req = json.loads((env / "clips" / "W01" / "higgsfield-request.json").read_text(encoding="utf-8"))
    assert "gen tunnel status --verify" in req["how_to_run"][0]


def test_ensure_verified_probes_once_per_tunnel_url(tmp_path, monkeypatch):
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(hosting, "_alive", lambda pid: True)
    st = {"server_pid": 1, "tunnel_pid": 2, "url": TUN, "token": "tok", "share_dir": str(tmp_path / "share")}
    (tmp_path / "share").mkdir()
    hosting.state_file().write_text(json.dumps(st), encoding="utf-8")
    calls = []

    def probe(wait_s=20.0):
        calls.append(wait_s)
        hosting._remember_verified(TUN)
        return {"verified": True}
    monkeypatch.setattr(hosting, "probe", probe)
    assert hosting.status()["running"] and "verified" not in hosting.status()
    assert hosting.ensure_verified() == {"verified": True} and len(calls) == 1
    assert hosting.status()["verified"] is True
    assert hosting.ensure_verified() == {"verified": True} and len(calls) == 1          # remembered: no new probe
    hosting.state_file().write_text(json.dumps({**st, "url": "https://other-new-words.trycloudflare.com"}), encoding="utf-8")
    monkeypatch.setattr(hosting, "probe", lambda wait_s=20.0: {"verified": False, "error": "Name or service not known"})
    v = hosting.ensure_verified()
    assert v["verified"] is False and "Name or service" in hosting.unverified_msg(v["error"])


@needs_ffmpeg
def test_clip_new_tail_warning_names_the_clip(env, monkeypatch):
    monkeypatch.setattr(clips, "higgsfield_tail_warning",
                        lambda song, t0, dur: "may be cut off (slop clip set CLIP --duration 5)")
    rc, out = run(env, "clip", "new", "s002", "--kind", "sung", "--provider", "higgsfield")
    assert rc == 0, out
    hint_lines = [out["text"], *out.get("warnings", [])]
    assert any("slop -p demo clip set W01 --duration 5" in x for x in hint_lines), out
    assert not any(" CLIP " in x for x in hint_lines)

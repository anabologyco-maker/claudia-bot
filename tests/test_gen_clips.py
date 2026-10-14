"""clip lifecycle on a synthetic project: new -> set -> lock -> submit (fake OpenRouter) -> poll -> sync -> coverage -> cover."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pytest

_H = Path(__file__).parent / "fixtures" / "gen" / "helpers.py"
_spec = importlib.util.spec_from_file_location("gen_test_helpers", _H)
H = importlib.util.module_from_spec(_spec); sys.modules.setdefault("gen_test_helpers", H); _spec.loader.exec_module(H)

from slop import ledger  # noqa: E402
from slop.cli import main  # noqa: E402
from slop.config import SlopError  # noqa: E402
from slop.gen import clips, store, templates as tpl  # noqa: E402
from slop.gen.openrouter import OpenRouter  # noqa: E402
from slop.sync.songdata import SongData  # noqa: E402

pytestmark = pytest.mark.skipif(not H.FFMPEG, reason="ffmpeg is required")
KEY = "sk-or-v1-test-not-a-real-key"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SLOP_PROJECTS", str(tmp_path / "projects"))
    monkeypatch.setenv("OPENROUTER_API_KEY", KEY)
    monkeypatch.delenv("SLOP_PROJECT", raising=False)
    H.write_cache(tmp_path / "home")
    pdir = H.make_project(tmp_path / "projects")
    return pdir


def run(pdir, *argv):
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(["--json", "--project", str(pdir), *argv])
    return rc, json.loads(buf.getvalue())


def filled(prompt: str) -> str:
    return tpl.SLOT_RE.sub("she sings it softly", prompt)


# ------------------------------------------------------------------------------------------------ window maths
def test_song_window_rules():
    s = SongData(None, words=H.words_doc(), beats=H.beats_doc(), hits=H.hits_doc())
    assert s.gap_start(10.0, lead=.3) == 9.3                         # the gap midpoint before "Sit" (8.6 .. 10.0)
    assert s.words_in(9.3, 13.3) == "Sit up, darling, eyes out on the road."
    assert s.words_in(13.0, 17.0) == "Here we go now, here it comes so fast."
    assert s.words_in(9.3, 10.07) == ""                              # a word starting < .08 s before the end is out
    assert s.words_in(9.98, 11.0, lo=.05) == "up, darling,"             # clean rule: starts in [t0 + .05, t1 − .08)
    assert s.eighths()[:3] == [0.0, .25, .5]
    assert s.last_eighth_before(11.3) == 11.25


# ------------------------------------------------------------------------------------------------ new / lock
def test_new_sung_clip_drafts_window_words_and_prompt(env):
    rc, out = run(env, "clip", "new", "s002", "--kind", "sung", "--style", "screenplay")   # sung default: short
    assert rc == 0 and out["created"]
    c = out["clip"]
    assert c["id"] == "W01" and c["status"] == "draft" and c["frame"] == "ref"
    assert c["song_t0"] == 9.3 and c["body"]["duration"] == 4
    assert c["words"] == "Sit up, darling, eyes out on the road."
    assert c["window"]["mode"] == "clean" and (env / c["window"]["file"]).is_file() and (env / c["window"]["wav"]).is_file()
    p = c["body"]["prompt"]
    assert p.startswith('@Image1 sings @Audio1. She lip-syncs to @Audio1 exactly, every word in time: '
                        '"Sit up, darling, eyes out on the road.".')
    assert "One continuous shot, no cuts. No text, letters or logos." in p
    assert '\n0.7–1.25 s ("Sit up,"): [[' in p                       # clip-relative times on the real words
    assert '1.3–1.7 s ("darling,")' in p and '1.8–3.3 s ("eyes out on the road.")' in p
    assert tpl.slots(p)
    assert c["start"] == "plates/cands/hero-cu/1.png"
    # idempotent
    rc, out2 = run(env, "clip", "new", "s002", "--kind", "sung", "--style", "screenplay")
    assert rc == 0 and out2["created"] is False and out2["clip_id"] == "W01"


def test_two_clips_do_not_reuse_starts_without_override(env):
    run(env, "clip", "new", "s002", "--kind", "sung")
    rc, out = run(env, "clip", "new", "s003", "--kind", "sung")
    assert rc == 0
    assert out["clip"]["start"] == "plates/cands/hero-cu/2.png"      # the pick is taken: the next candidate
    assert any("candidate 2" in w for w in out["warnings"])
    with pytest.raises(SlopError, match="reuse is off by default"):
        clips.new(env, "s004", "motion", start=str(env / "plates/cands/hero-cu/1.png"))


def test_motion_clip_and_short_style(env):
    rc, out = run(env, "clip", "new", "s004", "--kind", "motion", "--style", "short")
    c = out["clip"]
    assert c["id"] == "M-s004" and c["song_t0"] == 16.5 and c["body"]["duration"] == 5 and c["window"]["mode"] == "mix"
    assert c["body"]["prompt"] == ("The scene from @Image1, moving in time with @Audio1. Full-length shot. The woman from "
                                   "@Image1 walks toward the camera down the hall. The camera moves back slowly. No cuts. "
                                   "Her mouth stays closed, face expressionless.")
    assert not tpl.slots(c["body"]["prompt"])


def test_sung_first_frame_is_refused(env):
    with pytest.raises(SlopError, match="reference mode"):
        clips.new(env, "s002", "sung", frame="first")


def window_json(env, cid="W01") -> dict:
    return json.loads((env / "audio" / "windows" / f"{cid}.json").read_text(encoding="utf-8"))


def test_lock_needs_written_prompt_and_exact_words(env, tmp_path):
    run(env, "clip", "new", "s002", "--kind", "sung")
    rc, out = run(env, "clip", "lock", "W01")
    assert rc == 1 and "slot" in out["error"]
    c = store.load(env, "W01")
    # the quote is the source of truth: a prompt quoting fewer (in-window, in-order) words keeps them, and the clean
    # window is re-cut to hold exactly those words (prompts.py apply)
    fewer = filled(c["body"]["prompt"]).replace("eyes out on the road.", "eyes out.")
    f = tmp_path / "p.txt"; f.write_text(fewer, encoding="utf-8")
    rc, out = run(env, "clip", "set", "W01", "--prompt-file", str(f))
    assert rc == 0, out
    c = store.load(env, "W01")
    assert tpl.quoted_words(c["body"]["prompt"]) == "Sit up, darling, eyes out." == c["words"]
    assert [w[2] for w in c["her_words"]] == ["sit", "up", "darling", "eyes", "out"]
    assert window_json(env)["quoted"] == "Sit up, darling, eyes out." and window_json(env)["sung"] == "sit up darling eyes out"
    rc, out = run(env, "clip", "lock", "W01")
    assert rc == 0 and out["status"] == "locked"
    # a quote with words not sung in the window is refused (nothing changes)
    f.write_text(filled(c["body"]["prompt"]).replace("Sit up, darling, eyes out.", "Sit up, darling, lift off."),
                 encoding="utf-8")
    rc, out = run(env, "clip", "set", "W01", "--prompt-file", str(f))
    assert rc == 1 and "not all sung" in out["error"] and "--requote" in out["error"]
    assert store.load(env, "W01")["status"] == "locked"
    # --requote: every word of the window, and the window is re-cut for all of them
    rc, out = run(env, "clip", "set", "W01", "--requote")
    assert rc == 0
    c = store.load(env, "W01")
    assert c["words"] == tpl.quoted_words(c["body"]["prompt"]) == "Sit up, darling, eyes out on the road."
    assert "her_words" not in c and window_json(env)["sung"] == "sit up darling eyes out on the road"
    assert run(env, "clip", "lock", "W01")[0] == 0


def test_her_words_window_from_the_audio_module(env, tmp_path):
    """the reviewer's reproduction: audio window --words, attach it, a prompt quoting those words, lock, move the window."""
    run(env, "clip", "new", "s002", "--kind", "sung", "--style", "screenplay")
    rc, out = run(env, "audio", "window", "W01", "--t0", "9.3", "--t1", "13.3", "--mode", "clean", "--words", "Sit up, darling")
    assert rc == 0, out
    rc, out = run(env, "clip", "set", "W01", "--audio", "audio/windows/W01.mp3", "--audio-mode", "clean")
    assert rc == 0, out
    c = store.load(env, "W01")
    assert c["words"] == "Sit up, darling" == tpl.quoted_words(c["body"]["prompt"])       # the window decides
    assert window_json(env)["quoted"] == "Sit up, darling"                                 # used as is, not re-cut
    assert "prompt scaffold" in out["changed"]                         # the unwritten scaffold is redrafted for her words
    assert '("Sit up,")' in c["body"]["prompt"] and "road" not in c["body"]["prompt"]
    f = tmp_path / "p.txt"
    f.write_text(filled(c["body"]["prompt"]), encoding="utf-8")
    rc, out = run(env, "clip", "set", "W01", "--prompt-file", str(f))
    assert rc == 0, out
    c = store.load(env, "W01")
    assert c["words"] == "Sit up, darling" and [w[2] for w in c["her_words"]] == ["sit", "up", "darling"]
    rc, out = run(env, "clip", "lock", "W01")
    assert rc == 0, out
    # moving the window keeps the restriction and re-cuts for it; the screenplay timestamps are flagged
    rc, out = run(env, "clip", "set", "W01", "--song-t0", "9.2")
    assert rc == 0, out
    c = store.load(env, "W01")
    assert c["words"] == "Sit up, darling" and tpl.quoted_words(c["body"]["prompt"]) == "Sit up, darling"
    wj = window_json(env)
    assert wj["t0"] == 9.2 and wj["quoted"] == "Sit up, darling"
    assert any("timestamped screenplay" in w for w in out["warnings"])
    rc, out = run(env, "clip", "lock", "W01")
    assert rc == 1 and "screenplay" in out["error"]
    run(env, "clip", "set", "W01", "--prompt-file", str(f))               # a rewritten prompt clears the flag
    assert run(env, "clip", "lock", "W01")[0] == 0
    # someone re-cuts the window for fewer words after lock: lock/submit refuse the quote the audio does not hold
    rc, out = run(env, "audio", "window", "W01", "--t0", "9.2", "--t1", "13.2", "--mode", "clean", "--words", "Sit up")
    assert rc == 0
    probs = clips.lock_problems(env, store.load(env, "W01"))
    assert any('holds "Sit up"' in p for p in probs)
    rc, out = run(env, "clip", "submit", "W01", "--yes")
    assert rc == 1 and "not ready" in out["error"] and 'holds "Sit up"' in out["error"]
    # a window cut for other times is refused too
    run(env, "audio", "window", "W01", "--t0", "9.0", "--t1", "13.0", "--mode", "clean", "--words", "Sit up, darling")
    assert any("was cut for 9.00" in p for p in clips.lock_problems(env, store.load(env, "W01")))


def test_words_flag_and_raw_windows(env):
    rc, out = run(env, "clip", "new", "s002", "--kind", "sung", "--words", "darling, eyes out", "--style", "screenplay")
    assert rc == 0, out
    c = out["clip"]
    assert c["words"] == "darling, eyes out" and tpl.quoted_words(c["body"]["prompt"]) == "darling, eyes out"
    assert '("darling,")' in c["body"]["prompt"] and "road" not in c["body"]["prompt"]   # scaffold: her words only
    assert window_json(env)["sung"] == "darling eyes out"
    assert clips.lock_problems(env, {**c, "body": {**c["body"], "prompt": filled(c["body"]["prompt"])}}) == []
    rc, out = run(env, "clip", "set", "W01", "--words", "up, darling")
    assert rc == 0 and store.load(env, "W01")["words"] == "up, darling" and window_json(env)["sung"] == "up darling"
    # a raw vocal window holds every word: a partial quote is refused
    rc, out = run(env, "clip", "set", "W01", "--audio-mode", "vocal")
    assert rc == 1 and "every word" in out["error"]
    rc, out = run(env, "clip", "set", "W01", "--audio-mode", "vocal", "--requote")
    assert rc == 0, out
    c = store.load(env, "W01")
    assert c["window"]["mode"] == "vocal" and c["words"] == "Sit up, darling, eyes out on the road."
    assert not (env / "audio" / "windows" / "W01.json").exists()          # the stale clean description is gone
    rc, out = run(env, "clip", "new", "s003", "--kind", "sung", "--words", "lift off")
    assert rc == 1 and "not all sung" in out["error"]


def test_written_screenplay_lines_must_stay_inside_the_quote(env, tmp_path):
    run(env, "clip", "new", "s002", "--kind", "sung", "--style", "screenplay")
    f = tmp_path / "p.txt"; f.write_text(filled(store.load(env, "W01")["body"]["prompt"]), encoding="utf-8")
    run(env, "clip", "set", "W01", "--prompt-file", str(f))               # written: all words, timed lines for all
    rc, out = run(env, "clip", "set", "W01", "--words", "Sit up, darling")
    assert rc == 0 and "prompt scaffold" not in out["changed"]          # a written prompt is never redrafted
    c = store.load(env, "W01")
    assert tpl.quoted_words(c["body"]["prompt"]) == "Sit up, darling" and '("eyes out on the road.")' in c["body"]["prompt"]
    rc, out = run(env, "clip", "lock", "W01")
    assert rc == 1 and "screenplay line(s) quote words" in out["error"] and "eyes out on the road." in out["error"]
    f.write_text(c["body"]["prompt"].replace('1.8–3.3 s ("eyes out on the road."): she sings it softly\n', ""),
                 encoding="utf-8")
    run(env, "clip", "set", "W01", "--prompt-file", str(f))
    assert run(env, "clip", "lock", "W01")[0] == 0


def test_clean_start_keeps_the_first_word():
    s = SongData(None, words=H.words_doc(), beats=H.beats_doc(), hits=H.hits_doc())
    # the gap darling (11.00) .. eyes (11.10): its midpoint 11.05 would mute "eyes" in a clean window
    assert s.gap_start(11.4, lead=.3) == 11.05
    assert s.words_in(11.05, 15.05, lo=.05).startswith("out")
    t0 = s.clean_start(11.05)
    assert t0 == 11.04 and s.words_in(t0, t0 + 4, lo=.05).startswith("eyes") and s.in_word(t0) is None
    assert s.clean_start(9.3) == 9.3                                     # a long gap needs no change


# ------------------------------------------------------------------------------------------------ spend gates
def locked_w01(env, tmp_path):
    run(env, "clip", "new", "s002", "--kind", "sung")
    f = tmp_path / "p.txt"; f.write_text(filled(store.load(env, "W01")["body"]["prompt"]), encoding="utf-8")
    run(env, "clip", "set", "W01", "--prompt-file", str(f))
    rc, out = run(env, "clip", "lock", "W01")
    assert rc == 0


def test_submit_gates(env, tmp_path, monkeypatch):
    run(env, "clip", "new", "s002", "--kind", "sung")
    rc, out = run(env, "clip", "submit", "W01", "--yes")
    assert rc == 1 and "not locked" in out["error"]
    locked_w01(env, tmp_path)
    rc, out = run(env, "clip", "submit", "W01")
    assert rc == 1 and "--yes" in out["error"]
    rc, out = run(env, "clip", "submit", "W01", "--yes")              # no HTTPS audio URL yet
    assert rc == 1 and "HTTPS" in out["error"] and "slop -p demo gen host W01" in out["error"]
    assert "slop -p demo gen tunnel start" in out["error"]                   # the tunnel first, then submit hosts it
    rc, out = run(env, "gen", "host", "W01", "--url", "http://insecure.example/a.wav")
    assert rc == 1 and "HTTPS" in out["error"]
    rc, out = run(env, "gen", "host", "W01", "--data-uri")
    assert rc == 1 and "rejected" in out["error"]
    # budget: cap below the estimate -> refused before any HTTP request
    proj = json.loads((env / "project.json").read_text()); proj["budget"]["openrouter_usd"] = .5
    (env / "project.json").write_text(json.dumps(proj))
    run(env, "gen", "host", "W01", "--url", "https://cdn.example.com/W01.wav")
    import requests
    monkeypatch.setattr(requests, "Session", lambda: H.FakeSession({}))  # any request would raise
    rc, out = run(env, "clip", "submit", "W01", "--yes")
    assert rc == 1 and "budget cap" in out["error"]


def make_take(env, c: dict, diverge_at: float, out: Path) -> Path:
    """a take whose audio copies the clip's window until `diverge_at` (clip time), then sings something else."""
    from slop.sync.avsync import load
    ref = load(env / c["window"]["wav"], 44100)
    other = H.babble(len(ref) / 44100, seed=7)
    k = int(diverge_at * 44100)
    take = np.r_[ref[:k], other[k:len(ref)]] if diverge_at < len(ref) / 44100 else ref
    H.write_wav(out.with_suffix(".wav"), take)
    return H.make_mp4(out, out.with_suffix(".wav"))


def test_openrouter_submit_poll_sync_cover(env, tmp_path, monkeypatch):
    locked_w01(env, tmp_path)
    run(env, "gen", "host", "W01", "--url", "https://cdn.example.com/W01.wav")
    c = store.load(env, "W01")
    take_mp4 = make_take(env, c, 2.0, tmp_path / "take.mp4")
    fake = H.FakeSession({
        ("POST", "/videos"): H.FakeResp(202, {"id": "gen-vid-1-test", "polling_url": "https://openrouter.ai/api/v1/videos/gen-vid-1-test",
                                              "status": "pending"}),
        ("GET", "/content?index=0"): H.FakeResp(200, content=take_mp4.read_bytes()),
        ("GET", "/videos/gen-vid-1-test"): [H.FakeResp(200, {"status": "in_progress"}),
                                           H.FakeResp(200, {"status": "completed", "usage": {"cost": 0.41}})],
    })
    import requests
    monkeypatch.setattr(requests, "Session", lambda: fake)
    rc, out = run(env, "clip", "submit", "W01", "--yes", "--res", "480p")
    assert rc == 0, out
    sent = fake.calls[-1]
    assert sent["headers"]["Authorization"] == f"Bearer {KEY}" and sent["headers"]["X-Title"] == "claudia"
    body = sent["body"]
    assert body["model"] == "bytedance/seedance-2.5" and body["resolution"] == "480p" and body["duration"] == 4
    assert "frame_images" not in body                                  # sung = reference mode
    refs = body["input_references"]
    assert refs[0]["type"] == "image_url" and refs[0]["image_url"]["url"].startswith("data:image/png;base64,")
    assert refs[-1] == {"type": "audio_url", "audio_url": {"url": "https://cdn.example.com/W01.wav"}}
    assert abs(out["est_usd"] - 97 / 24 * 0.1028) < .001              # Seedance bills round(s × 24) + 1 frames
    assert store.load(env, "W01")["body"]["resolution"] == "720p"     # --res applies to this take only
    assert store.load(env, "W01")["takes"][0]["body"]["resolution"] == "480p"
    rows = ledger.rows(env)
    assert rows[-1]["status"] == "submitted" and rows[-1]["request_id"] == "gen-vid-1-test"
    # second submit while in flight is refused
    rc, out = run(env, "clip", "submit", "W01", "--yes")
    assert rc == 1 and "in flight" in out["error"]
    # poll: rendering, then completed + download
    rc, out = run(env, "clip", "poll", "W01")
    assert out["results"][0]["job_status"] == "in_progress"
    rc, out = run(env, "clip", "poll")
    assert out["results"][0]["status"] == "delivered"
    c = store.load(env, "W01")
    assert c["status"] == "delivered" and (env / c["takes"][0]["file"]).is_file() and c["takes"][0]["cost_usd"] == .41
    assert abs(ledger.spent_usd(env, "openrouter") - .41) < 1e-6      # estimate settled to usage.cost
    # sync
    rc, out = run(env, "clip", "sync", "W01")
    assert rc == 0, out
    sy = out["sync"]
    assert sy["mode"] == "copy" and sy["diverges"] and 10.9 < sy["diverge_at"] < 11.9
    assert sy["cut_at"] <= sy["synced_until_song"] and (env / sy["png"]).is_file()
    assert out["gaps"] and out["share"] < .9
    # coverage + cover proposal
    rc, cov = run(env, "clip", "coverage")
    assert cov["clips"][0]["root"] == "W01" and cov["clips"][0]["gaps"]
    rc, pr = run(env, "clip", "cover", "W01")
    p0 = pr["proposals"][0]
    assert p0["id"] == "W01-c1" and 4 <= p0["duration"] <= 8 and p0["song_t0"] < p0["needed"][0]
    assert SongData(env).in_word(p0["song_t0"]) is None               # starts in a word gap
    rc, pr = run(env, "clip", "cover", "W01", "--make")
    assert rc == 0
    cv = store.load(env, "W01-c1")
    assert cv["parent"] == "W01" and cv["frame"] == "ref" and (env / cv["start"]).is_file()
    assert cv["start_frame"]["take_file"] == c["takes"][0]["file"]
    assert "road" in cv["words"] and tpl.quoted_words(cv["body"]["prompt"]) == cv["words"]
    assert store.load(env, "W01")["covers"] == ["W01-c1"]
    # the same gap is not proposed again while its cover waits for a take
    rc, pr2 = run(env, "clip", "cover", "W01")
    assert not pr2["proposals"] and pr2["pending_covers"][0]["covers"] == ["W01-c1"]


def test_cover_start_frame_steps_back_when_used(env, tmp_path, monkeypatch):
    locked_w01(env, tmp_path)
    c = store.load(env, "W01")
    take = make_take(env, c, 2.0, tmp_path / "t.mp4")
    rc, out = run(env, "clip", "ingest", "W01", "--file", str(take), "--provider", "openrouter")
    assert rc == 0
    run(env, "clip", "sync", "W01")
    from slop.sync.coverage import propose
    first = propose(env, store.load(env, "W01"), SongData(env))["proposals"][0]["start_frame"]
    dummy = {"id": "X1", "kind": "motion", "status": "draft", "song_t0": 0, "body": {}, "start_frame":
             {"take_file": first["take_file"], "frame": first["frame"]}}
    store.save(env, dummy)
    again = propose(env, store.load(env, "W01"), SongData(env))["proposals"][0]["start_frame"]
    assert again["frame"] == first["frame"] - 1 and again["stepped_back"] == 1


def test_decline_is_final_for_that_image_and_provider(env, tmp_path, monkeypatch):
    locked_w01(env, tmp_path)
    run(env, "gen", "host", "W01", "--url", "https://cdn.example.com/W01.wav")
    fake = H.FakeSession({("POST", "/videos"): H.FakeResp(400, {"error": {"code": 400, "message":
                          "InputImageSensitiveContentDetected.PrivacyInformation: the input image may contain real person"}})})
    import requests
    monkeypatch.setattr(requests, "Session", lambda: fake)
    rc, out = run(env, "clip", "submit", "W01", "--yes")
    assert rc == 1 and out["status"] == "declined" and "Never alter" in out["text"]
    c = store.load(env, "W01")
    assert c["status"] == "declined" and c["declined"][0]["provider"] == "openrouter"
    assert ledger.rows(env)[-1]["status"] == "declined" and ledger.spent_usd(env) == 0
    rc, out = run(env, "clip", "lock", "W01")
    assert rc == 1 and "declined this reference" in out["error"]
    rc, out = run(env, "clip", "set", "W01", "--provider", "higgsfield")
    rc, out = run(env, "clip", "lock", "W01")
    assert rc == 0
    rc, out = run(env, "clip", "submit", "W01", "--yes")
    assert rc == 0 and out["expected_credits"] == 28
    assert len(fake.calls) == 1                                        # Higgsfield path makes no HTTP call


def test_failed_job_is_refunded_and_relocked(env, tmp_path, monkeypatch):
    locked_w01(env, tmp_path)
    run(env, "gen", "host", "W01", "--url", "https://cdn.example.com/W01.wav")
    fake = H.FakeSession({
        ("POST", "/videos"): H.FakeResp(202, {"id": "gen-vid-2", "status": "pending"}),
        ("GET", "/videos/gen-vid-2"): H.FakeResp(200, {"status": "failed", "error":
                                                       "The request failed because the output audio may be related to copyright restrictions"}),
    })
    import requests
    monkeypatch.setattr(requests, "Session", lambda: fake)
    assert run(env, "clip", "submit", "W01", "--yes")[0] == 0
    assert ledger.spent_usd(env) > 0
    rc, out = run(env, "clip", "poll", "W01")
    assert "copyright" in out["text"] and "retry once" in out["text"].lower()     # the protocol's one next step
    c = store.load(env, "W01")
    assert c["status"] == "locked" and c["takes"][0]["status"] == "failed" and c["takes"][0]["error_class"] == "copyright"
    assert abs(ledger.spent_usd(env)) < 1e-9                           # failed jobs are not billed


def test_list_and_status(env):
    run(env, "clip", "new", "s002", "--kind", "sung")
    run(env, "clip", "new", "s004", "--kind", "motion")
    rc, out = run(env, "clip", "list")
    assert [r["id"] for r in out["clips"]] == ["W01", "M-s004"]
    assert out["expected_usd"] > 0 and out["expected_usd_with_covers"] > out["expected_usd"]
    rc, out = run(env, "clip", "status", "W01")
    assert out["lock_problems"] and "prompt:" in out["text"]


def test_motion_first_frame_sends_no_references(env, tmp_path):
    clips.new(env, "s004", "motion", frame="first", style="short")
    c = store.load(env, "M-s004")
    warns: list[str] = []
    from slop.gen import video
    b = video.build_body(env, c, model="bytedance/seedance-2.5", audio_url="https://x.example/a.wav", warnings=warns)
    assert b["frame_images"][0]["frame_type"] == "first_frame" and "input_references" not in b
    assert warns and "ignores input_references" in warns[0]
    assert b["prompt"].startswith("Moving in time with the music. ") and "@Audio1" not in b["prompt"]
    assert c["body"]["prompt"].startswith("Moving in time with @Audio1. ")   # the clip file keeps its prompt
    warns.clear()
    b2 = video.build_body(env, {**c, "frame": "ref"}, model="x-ai/grok-imagine-video", audio_url="https://x.example/a.wav",
                          warnings=warns)
    assert [r["type"] for r in b2["input_references"]] == ["image_url"] and any("Seedance 2+" in w for w in warns)
    assert "@Audio1" not in b2["prompt"]


def host_and_fake(env, monkeypatch, routes, cid="W01"):
    run(env, "gen", "host", cid, "--url", f"https://cdn.example.com/{cid}.wav")
    fake = H.FakeSession(routes)
    import requests
    monkeypatch.setattr(requests, "Session", lambda: fake)
    return fake


def test_motion_without_audio_ref_is_warned_on_submit(env, monkeypatch):
    clips.new(env, "s004", "motion", frame="first", style="short")
    assert run(env, "clip", "lock", "M-s004")[0] == 0
    fake = host_and_fake(env, monkeypatch, {("POST", "/videos"): H.FakeResp(202, {"id": "gen-m-1"})}, "M-s004")
    rc, out = run(env, "clip", "submit", "M-s004", "--yes")
    assert rc == 0, out
    assert out["warnings"] and "NOT conditioned on the song" in out["warnings"][0]
    body = fake.calls[-1]["body"]
    assert "frame_images" in body and "input_references" not in body
    assert body["prompt"].startswith("Moving in time with the music.")
    # reference mode + --no-audio-ref: warned the same way
    H.write_png(env / "plates" / "extra.png", (10, 200, 10))
    clips.new(env, "s001", "motion", style="short", start="plates/extra.png")
    clips.set_fields(env, "M-s001", prompt="The scene from @Image1, moving in time with @Audio1. Wide shot. She walks "
                                           "to the window. No cuts.")
    assert run(env, "clip", "lock", "M-s001")[0] == 0
    rc, out = run(env, "clip", "submit", "M-s001", "--yes", "--no-audio-ref")
    assert rc == 0 and any("NOT conditioned" in w for w in out["warnings"])
    body = fake.calls[-1]["body"]
    assert [r["type"] for r in body["input_references"]] == ["image_url"]
    assert body["prompt"].startswith("The scene from @Image1, moving in time with the music.")


def test_sung_clips_need_an_audio_reference_model(env, tmp_path):
    rc, out = run(env, "clip", "new", "s002", "--kind", "sung", "--model", "google/veo-3.1-lite")
    assert rc == 1 and "audio reference" in out["error"] and "seedance-2.5" in out["error"]
    proj = json.loads((env / "project.json").read_text()); proj["models"]["video"] = "google/veo-3.1-lite"
    (env / "project.json").write_text(json.dumps(proj))
    rc, out = run(env, "clip", "new", "s002", "--kind", "sung")           # Quick tier cheap default: sung falls back
    assert rc == 0 and out["clip"]["model"] == "bytedance/seedance-2.5"
    assert any("takes no audio reference" in w for w in out["warnings"])
    rc, out = run(env, "clip", "set", "W01", "--model", "google/veo-3.1-lite")
    assert rc == 1 and "audio reference" in out["error"]
    assert run(env, "clip", "new", "s004", "--kind", "motion")[1]["clip"]["model"] == "google/veo-3.1-lite"
    # a clip file edited by hand is still refused before any spend
    f = tmp_path / "p.txt"; f.write_text(filled(store.load(env, "W01")["body"]["prompt"]), encoding="utf-8")
    run(env, "clip", "set", "W01", "--prompt-file", str(f))
    assert run(env, "clip", "lock", "W01")[0] == 0
    c = store.load(env, "W01"); c["model"] = "google/veo-3.1-lite"; store.save(env, c)
    rc, out = run(env, "clip", "submit", "W01", "--yes")
    assert rc == 1 and "not ready" in out["error"] and "audio reference" in out["error"]
    # Higgsfield runs Seedance itself: allowed
    c["provider"] = "higgsfield"; store.save(env, c)
    assert clips.model_problem(c) is None


def test_unknown_outcome_is_never_resubmitted_blindly(env, tmp_path, monkeypatch):
    locked_w01(env, tmp_path)
    fake = host_and_fake(env, monkeypatch, {
        ("POST", "/videos"): [H.FakeResp(502, {"error": {"message": "upstream timeout"}}),
                              H.FakeResp(202, {"id": "gen-vid-9", "status": "pending"})],
        ("GET", "/videos/gen-vid-7"): H.FakeResp(200, {"status": "in_progress"}),
    })
    rc, out = run(env, "clip", "submit", "W01", "--yes")
    assert rc == 1 and out["status"] == "unknown" and "Do NOT submit again" in out["text"]
    assert "slop -p demo clip poll W01 --job-id" in out["text"] and "--resubmit-unknown" in out["text"]
    c = store.load(env, "W01")
    assert c["status"] == "submitted" and c["takes"][0]["status"] == "unknown" and c["takes"][0]["id"] is None
    est = c["takes"][0]["est_usd"]
    assert ledger.rows(env)[-1]["status"] == "submitted" and abs(ledger.spent_usd(env) - est) < 1e-6
    assert len([x for x in fake.calls if x["method"] == "POST"]) == 1
    # a plain re-run is refused; set/lock are refused; poll explains
    rc, out = run(env, "clip", "submit", "W01", "--yes")
    assert rc == 1 and "openrouter.ai/activity" in out["error"]
    assert run(env, "clip", "set", "W01", "--res", "480p")[0] == 1
    rc, out = run(env, "clip", "poll")
    assert out["results"][0]["job_status"] == "unknown" and "--job-id" in out["text"]
    assert len([x for x in fake.calls if x["method"] == "POST"]) == 1
    # found on the activity page: attach it, then it polls like any job
    rc, out = run(env, "clip", "poll", "W01", "--job-id", "gen-vid-7")
    assert rc == 0 and out["results"][0]["job_status"] == "in_progress"
    c = store.load(env, "W01")
    assert c["takes"][0]["id"] == "gen-vid-7" and c["takes"][0]["status"] == "submitted"
    assert abs(ledger.spent_usd(env) - est) < 1e-6                   # still counted once


def test_resubmit_unknown_after_checking(env, tmp_path, monkeypatch):
    locked_w01(env, tmp_path)
    fake = host_and_fake(env, monkeypatch, {
        ("POST", "/videos"): [H.FakeResp(503, {"error": {"message": "unavailable"}}), H.FakeResp(202, {"id": "gen-vid-10"})]})
    assert run(env, "clip", "submit", "W01", "--yes")[1]["status"] == "unknown"
    rc, out = run(env, "clip", "submit", "W01", "--resubmit-unknown")
    assert rc == 1 and "--yes" in out["error"]
    rc, out = run(env, "clip", "submit", "W01", "--yes", "--resubmit-unknown")
    assert rc == 0 and out["job"] == "gen-vid-10" and out["take"] == 2
    c = store.load(env, "W01")
    assert [t["status"] for t in c["takes"]] == ["abandoned", "submitted"]
    assert abs(ledger.spent_usd(env) - c["takes"][1]["est_usd"]) < 1e-6   # the abandoned estimate is refunded
    assert len([x for x in fake.calls if x["method"] == "POST"]) == 2


def test_ingest_file_is_idempotent_and_frame_command(env, tmp_path):
    locked_w01(env, tmp_path)
    c = store.load(env, "W01")
    take = make_take(env, c, 2.0, tmp_path / "t.mp4")
    rc, out = run(env, "clip", "ingest", "W01", "--file", str(take), "--provider", "openrouter")
    assert rc == 0 and out["take"] == 1
    rc, out = run(env, "clip", "ingest", "W01", "--file", str(take), "--provider", "openrouter")
    assert rc == 0 and out["take"] == 1 and "already ingested" in out["text"]
    assert len(store.load(env, "W01")["takes"]) == 1
    rc, out = run(env, "clip", "frame", "W01", "--at", "10.5")
    assert rc == 0, out
    assert (env / out["file"]).is_file() and out["frame"] == round((10.5 - 9.3) * 24) and "--start" in out["text"]
    rc, out = run(env, "clip", "frame", "W01")
    assert rc == 1 and "--at" in out["error"]                         # no sync yet: no last in-sync frame
    run(env, "clip", "sync", "W01")
    rc, out = run(env, "clip", "frame", "W01", "--out", "plates/continue.png")
    assert rc == 0 and out["file"] == "plates/continue.png" and out["song_t"] < 12.0
    rc, out = run(env, "clip", "new", "s003", "--kind", "sung", "--start", "plates/continue.png")
    assert rc == 0 and out["clip"]["start"] == "plates/continue.png"
    rc, out = run(env, "clip", "frame", "W01", "--at", "30")
    assert rc == 1 and "outside take" in out["error"]


def test_higgsfield_motion_defaults_to_first_frame(env):
    rc, out = run(env, "clip", "new", "s004", "--kind", "motion", "--provider", "higgsfield", "--style", "short")
    assert rc == 0 and out["clip"]["frame"] == "first"
    assert out["clip"]["body"]["prompt"].startswith("Moving in time with @Audio1.")
    assert run(env, "clip", "lock", "M-s004")[0] == 0
    rc, out = run(env, "clip", "submit", "M-s004", "--yes")
    assert rc == 0
    req = json.loads(Path(out["request_file"]).read_text(encoding="utf-8"))
    assert [m["role"] for m in req["request"]["params"]["medias"]] == ["start_image", "audio_references"]


def test_cover_proposal_words_match_the_cover_clip(env, tmp_path):
    locked_w01(env, tmp_path)
    c = store.load(env, "W01")
    take = make_take(env, c, 1.85, tmp_path / "t.mp4")                 # diverges inside "darling" (song 11.15)
    run(env, "clip", "ingest", "W01", "--file", str(take), "--provider", "openrouter")
    run(env, "clip", "sync", "W01")
    rc, pr = run(env, "clip", "cover", "W01")
    assert rc == 0 and pr["proposals"], pr
    p0 = pr["proposals"][0]
    rc, out = run(env, "clip", "cover", "W01", "--make")
    assert rc == 0
    cv = store.load(env, p0["id"])
    assert cv["words"] == p0["words"] == tpl.quoted_words(cv["body"]["prompt"])
    assert cv["song_t0"] == p0["song_t0"] and SongData(env).in_word(cv["song_t0"]) is None


def test_her_words_chain_covers_keep_her_words(env, tmp_path):
    rc, out = run(env, "clip", "new", "s002", "--kind", "sung", "--words", "Sit up, eyes out on the road")
    assert rc == 0, out
    c = store.load(env, "W01")
    assert [w[2] for w in c["her_words"]] == ["sit", "up", "eyes", "out", "on", "the", "road"]   # "darling" muted
    words, quoted, hw = clips.cover_words(SongData(env), c["her_words"], 11.04, 4, "clean")
    assert words == quoted == "eyes out on the road." and len(hw) == 5

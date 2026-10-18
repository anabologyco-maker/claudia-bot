"""0.3.6 relay: two runs of Grok (wake-ups) never do one job twice or fight over the browser; an old job is never run
unasked; the person's files go over as files; a quiet production is flagged as possibly stuck."""
from __future__ import annotations

import json
import time

from slop import relay

import test_relay as RT  # noqa: E402  (its fake engine and helpers)
K = RT.K


def _ready(tmp_path, monkeypatch):
    env = RT.setup(tmp_path, monkeypatch)
    assert K.run("relay", "setup")[0] == 0
    return env


def _job(kind="browser", **kw):
    args = ["relay", "job", "--kind", kind]
    if kind == "browser":
        args += ["--url", "https://example.com", "--note", kw.get("note", "x")]
    elif kind == "suno":
        args += ["--style", "synth pop", "--instrumental"]
    rc, out = K.run(*args)
    assert rc == 0, out
    return out["job"]


def test_a_job_is_claimed_once_and_one_at_a_time(tmp_path, monkeypatch):
    env = _ready(tmp_path, monkeypatch)
    a, b = _job("suno"), _job("browser")
    rc, out = K.run("relay", "claim", a)
    assert rc == 0 and out["status"] == "claimed" and out["token"] in out["text"], out
    token = out["token"]
    rc, out = K.run("relay", "claim", a)                       # a second run of Grok: never the same song twice
    assert rc == 1 and "already being run" in out["error"] and token not in out["error"]
    assert K.run("relay", "claim", a, "--token", "nope00")[0] == 1
    rc, out = K.run("relay", "claim", a, "--token", token)     # the same chat after "continue": its job again
    assert rc == 0 and out["token"] == token, out
    assert token not in json.dumps(K.run("relay", "read")[1])  # a wake-up run never sees it
    rc, out = K.run("relay", "claim", b)                       # one browser job at a time
    assert rc == 1 and "one browser job at a time" in out["error"]
    nxt = K.run("relay", "read")[1]["grok_next"]
    assert f"job {a.lower()} is being run" in nxt.lower() and f"claim job {b.lower()}" not in nxt.lower()
    rc, out = K.run("relay", "fail", a, "--reason", "out of credits")
    assert rc == 0
    assert K.run("relay", "claim", b)[0] == 0                  # free again once the first one is closed
    jobs = json.loads((env["rd"] / "jobs.json").read_text())
    jobs[b]["claimed_ts"] = time.time() - relay.CLAIM_TTL_S - 1    # a run that died holding a claim
    (env["rd"] / "jobs.json").write_text(json.dumps(jobs))
    assert K.run("relay", "claim", b)[0] == 0, "an expired claim is free again"


def test_a_person_job_needs_no_claim_and_blocks_nothing(tmp_path, monkeypatch):
    _ready(tmp_path, monkeypatch)
    rc, out = K.run("relay", "job", "--kind", "person", "--text", "send me your demo", "--expect", "demo.wav")
    assert rc == 0, out
    rc, c = K.run("relay", "claim", out["job"])
    assert rc == 0 and c["status"] == "queued" and "needs no claim" in c["text"], c
    b = _job("browser")
    assert K.run("relay", "claim", b)[0] == 0                  # the browser job is not held up by the person job


def test_an_old_job_is_never_run_unasked(tmp_path, monkeypatch):
    env = _ready(tmp_path, monkeypatch)
    jid = _job("browser", note="the Melee rip download")
    rows = [json.loads(x) for x in (env["rd"] / "outbox.jsonl").read_text().splitlines() if x.strip()]
    rows[-1]["t"] = time.time() - relay.JOB_STALE_S - 60
    (env["rd"] / "outbox.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    r = K.run("relay", "read")[1]
    assert "never run it unasked" in r["grok_next"] and f"claim job {jid}" not in r["grok_next"]
    rc, out = K.run("relay", "claim", jid)
    assert rc == 1 and "still wanted?" in out["error"]
    assert K.run("relay", "claim", jid, "--stale-ok")[0] == 0


def test_the_persons_files_go_over_as_files(tmp_path, monkeypatch):
    env = _ready(tmp_path, monkeypatch)
    f = tmp_path / "their-song.wav"
    f.write_bytes(b"RIFF")
    rc, out = K.run("relay", "send", "here is my song", "--attach", str(f))
    assert rc == 0 and out["attached"] == [str(f.resolve())], out
    msg = [json.loads(x) for x in (env["rd"] / "inbox.jsonl").read_text().splitlines() if x.strip()][-1]
    assert msg["text"] == f"here is my song\n[attached file] {f.resolve()}"
    rc, out = K.run("relay", "send", "and this", "--attach", str(tmp_path / "nope.png"))
    assert rc == 1 and "no such file" in out["error"]


def test_a_quiet_production_is_flagged(tmp_path, monkeypatch):
    env = _ready(tmp_path, monkeypatch)
    rd = env["rd"]
    (rd / "runner.json").write_text(json.dumps({"state": "running", "pid": __import__("os").getpid()}))
    (rd / "turn.json").write_text(json.dumps({"state": "running", "n": 3, "last": "bash: render frames",
                                              "started_ts": time.time() - 7 * 3600,
                                              "last_ts": time.time() - 6 * 3600}))
    monkeypatch.setattr(relay, "_alive", lambda pid, start=None: True)
    p = relay.production(rd)
    assert p["state"] == "working" and p.get("stalled") and "No progress for" in p["summary"], p
    assert "relay log" in p["summary"]


def test_no_wake_up_while_a_run_of_grok_is_busy(tmp_path, monkeypatch):
    env = _ready(tmp_path, monkeypatch)
    rd = env["rd"]
    relay._grok_touch(rd)
    assert relay._grok_busy(rd)
    (rd / "grok-active.json").write_text(json.dumps({"t_m": time.monotonic() - relay.GROK_ACTIVE_S - 5}))
    assert not relay._grok_busy(rd)
    jid = _job("browser")
    assert K.run("relay", "claim", jid)[0] == 0
    (rd / "grok-active.json").write_text(json.dumps({"t_m": 0}))
    assert relay._grok_busy(rd), "a claimed job means a run is still working"


def test_midjourney_downloads_get_their_extension_and_carry_their_prompt(tmp_path, monkeypatch):
    from PIL import Image
    _ready(tmp_path, monkeypatch)
    rc, out = K.run("relay", "job", "--kind", "midjourney", "--text", "a sequinned diamanté gown --ar 16:9",
                    "--plate", "gown-ms")
    from pathlib import Path
    save = Path(out["save"])
    Image.new("RGB", (8, 8)).save(save / "gown-ms-1", format="PNG")      # saved without its extension
    rc, done = K.run("relay", "done", out["job"], "--file", "gown-ms-1", "--model", "V8.1")
    assert rc == 0 and done["files"] == [str(save / "gown-ms-1.png")], done
    meta = Image.open(save / "gown-ms-1.png").text
    assert meta["Claudia-Prompt"] == "a sequinned diamanté gown --ar 16:9" and meta["Claudia-Model"] == "V8.1"
    assert meta["Claudia-Plate"] == "gown-ms"


def test_a_prompt_goes_on_the_clipboard_never_typed(tmp_path, monkeypatch):
    env = _ready(tmp_path, monkeypatch)
    monkeypatch.setenv("PATH", str(tmp_path / "no-tools"))               # no xclip here: the file way
    rc, out = K.run("relay", "job", "--kind", "midjourney", "--text", "first --ar 16:9", "--text", "a diamanté bag")
    rc, c = K.run("relay", "copy", out["job"], "--k", "2")
    assert rc == 0 and c["copied"] is False and "file://" in c["text"], c
    from pathlib import Path
    assert Path(c["file"]).read_text(encoding="utf-8") == "a diamanté bag"
    assert K.run("relay", "copy", out["job"], "--k", "3")[0] == 1


def test_a_video_too_big_for_drive_is_never_posted(tmp_path, monkeypatch):
    env = _ready(tmp_path, monkeypatch)
    big = env["wd"] / "film" / "out" / "film.mp4"
    big.parent.mkdir(parents=True)
    with open(big, "wb") as f:
        f.truncate(relay.DRIVE_MAX_B + 1)                             # sparse: no disk used
    monkeypatch.setattr(relay, "_video_issue", lambda p: None)
    rc, out = K.run("relay", "say", "the film", "--show", str(big))
    assert rc == 1 and "over the 100 MB Drive upload limit" in out["error"] and "encode --share" in out["error"], out
    assert K.run("relay", "say", "the film", "--show", str(big), "--as-is")[0] == 0
    nxt = K.run("relay", "read")[1]["grok_next"]
    assert "over Drive's 100 MB upload limit: never upload it" in nxt and "share copy under 95 MB" in nxt, nxt


def test_a_clip_saved_without_its_extension_gets_it(tmp_path):
    clip, mov, kept = tmp_path / "take-1", tmp_path / "take-2", tmp_path / "take-3.m4v"
    clip.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"\x00" * 64)
    mov.write_bytes(b"\x00\x00\x00\x14ftypqt  " + b"\x00" * 64)
    kept.write_bytes(b"\x00\x00\x00\x18ftypM4V " + b"\x00" * 64)
    assert relay._with_real_ext(clip).name == "take-1.mp4" and relay._with_real_ext(mov).name == "take-2.mov"
    assert relay._with_real_ext(kept) == kept                       # any video name is fine for a video

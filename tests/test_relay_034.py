"""0.3.4: what Grok found after 0.3.3. A job is cancelled, not failed; Midjourney images record the prompt, plate and
model that made them; an over-long Midjourney prompt is flagged; a video phones play badly is never shown; Drive
uploads videos as .mov."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

import test_relay as RT  # noqa: E402  (its fake engine and helpers)
K = RT.K
ROOT = Path(__file__).resolve().parents[1]


def _ready(tmp_path, monkeypatch):
    env = RT.setup(tmp_path, monkeypatch)
    assert K.run("relay", "setup")[0] == 0
    return env


def test_a_job_is_cancelled_not_failed(tmp_path, monkeypatch):
    env = _ready(tmp_path, monkeypatch)
    rc, out = K.run("relay", "job", "--kind", "browser", "--url", "https://example.com", "--note", "x")
    jid = out["job"]
    monkeypatch.setenv("SLOP_RELAY_TURN", "3")                    # the production cancels its own job: no message
    rc, out = K.run("relay", "cancel", jid, "--reason", "replaced by a new job")
    assert rc == 0 and out["status"] == "cancelled", out
    jobs = json.loads((env["rd"] / "jobs.json").read_text(encoding="utf-8"))
    assert jobs[jid]["status"] == "cancelled" and jobs[jid]["reason"] == "replaced by a new job"
    assert not (env["rd"] / "inbox.jsonl").is_file() or jid not in (env["rd"] / "inbox.jsonl").read_text()
    assert K.run("relay", "cancel", jid)[0] == 1, "a closed job cannot be cancelled again"
    monkeypatch.delenv("SLOP_RELAY_TURN")
    rc, out = K.run("relay", "job", "--kind", "browser", "--url", "https://example.com", "--note", "y")
    rc, out = K.run("relay", "cancel", out["job"], "--reason", "the person said never mind")   # Grok: Opus hears it
    assert rc == 0 and "cancelled: the person said never mind" in (env["rd"] / "inbox.jsonl").read_text()


def test_midjourney_images_record_what_made_them(tmp_path, monkeypatch):
    env = _ready(tmp_path, monkeypatch)
    rc, out = K.run("relay", "job", "--kind", "midjourney", "--text", "a red door --ar 16:9", "--plate", "door-ms",
                    "--text", "a city at night --ar 16:9", "--plate", "city-ws", "--personalize", "off")
    save = Path(out["save"])
    for name in ("door-ms-1.png", "city-ws-3.png"):
        (save / name).write_bytes(b"png")
    rc, done = K.run("relay", "done", out["job"], "--file", "door-ms-1.png", "--file", "city-ws-3.png",
                     "--model", "V8.1")
    assert rc == 0, done
    idx = json.loads((save / "midjourney-prompts.json").read_text(encoding="utf-8"))
    assert idx["door-ms-1.png"]["prompt"] == "a red door --ar 16:9" and idx["door-ms-1.png"]["plate"] == "door-ms"
    assert idx["city-ws-3.png"]["k"] == 2 and idx["city-ws-3.png"]["model"] == "V8.1"
    assert idx["city-ws-3.png"]["personalize"] is False
    msgs = [json.loads(x) for x in (env["rd"] / "inbox.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    assert "\nmodel: V8.1" in msgs[-1]["text"]


def test_an_over_long_midjourney_prompt_is_flagged(tmp_path, monkeypatch):
    _ready(tmp_path, monkeypatch)
    rc, out = K.run("relay", "job", "--kind", "midjourney", "--text", "word " * 200 + "--ar 16:9")
    assert rc == 1 and "prompt 1 is 999 characters" in out["error"], out
    rc, out = K.run("relay", "job", "--kind", "midjourney", "--text", "word " * 200 + "--ar 16:9", "--long")
    assert rc == 0


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
def test_a_video_phones_play_badly_is_never_shown(tmp_path, monkeypatch):
    _ready(tmp_path, monkeypatch)
    good, bad = tmp_path / "good.mp4", tmp_path / "bad.mp4"
    for f, pix in ((good, "yuv420p"), (bad, "yuvj420p")):
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=duration=1:size=160x120:rate=12",
                        "-pix_fmt", pix, "-c:v", "libx264", str(f)], check=True)
    rc, out = K.run("relay", "say", "the excerpt", "--show", str(bad))
    assert rc == 1 and "full range" in out["error"] and "out_range=tv" in out["error"], out
    assert K.run("relay", "say", "the excerpt", "--show", str(good))[0] == 0
    assert K.run("relay", "say", "as it is", "--show", str(bad), "--as-is")[0] == 0


def test_drive_uploads_videos_as_mov_and_the_brief_names_the_video_spec():
    drive = (ROOT / "skills/drive/SKILL.md").read_text(encoding="utf-8")
    assert "as .mov, never .mp4" in drive and "application/mp4" in drive and "claudia-drive-test.mov" in drive
    brief = (ROOT / "templates/production-brief.md").read_text(encoding="utf-8")
    assert "yuv420p, limited (tv) range" in brief and "slop relay cancel JOB" in brief

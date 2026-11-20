"""0.3.1: the routing audit's fixes. The production (Claude Code or Codex) gets the toolkit's keys because it is the
spender; relay setup picks the engine the person has; Midjourney jobs are one prompt each, with the plate it is for;
Grok's text view of a job has every field; a changed brief is read again; an update keeps the model; the scorer runs
without the cmudict package; login shells load env.sh."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from slop import relay, update

import test_relay as RT  # noqa: E402  (its fake engine and helpers)
K = RT.K
ROOT = Path(__file__).resolve().parents[1]
FAKE_OR = "sk-or-v1-" + "0" * 64


@pytest.mark.parametrize("engine", ["claude", "codex"])
def test_the_production_gets_the_toolkits_keys(tmp_path, monkeypatch, engine):
    env = RT.setup(tmp_path, monkeypatch, logged=(engine,))
    monkeypatch.setenv("OPENROUTER_API_KEY", FAKE_OR)
    assert K.run("relay", "setup", "--engine", engine)[0] == 0
    K.run("relay", "send", "hello")
    RT.collect(lambda it, r: any("heard #1" in i["text"] for i in it) and r["production"]["state"] == "idle")
    call = [c for c in K.calls(env["state"], engine) if c.get("relay")][-1]
    assert "OPENROUTER_API_KEY" in call["env_present"], "the spender needs the key"
    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        assert k not in call["env_present"], "the engine itself still runs on the person's plan"
    if engine == "codex":
        assert "shell_environment_policy.ignore_default_excludes=true" in call["argv"]


def test_setup_picks_the_engine_the_person_has(tmp_path, monkeypatch):
    RT.setup(tmp_path, monkeypatch, logged=("codex",))
    K.run("onboard", "set", "coding-agents", "codex")
    rc, out = K.run("relay", "setup")
    assert rc == 0 and out["engine"] == "codex", out
    rc, out = K.run("relay", "setup")                       # a plain re-run keeps it
    assert rc == 0 and out["engine"] == "codex"


def test_midjourney_jobs_are_one_prompt_each_with_its_plate(tmp_path, monkeypatch):
    RT.setup(tmp_path, monkeypatch)
    assert K.run("relay", "setup")[0] == 0
    rc, out = K.run("relay", "job", "--kind", "midjourney", "--text", "{a\\, x, b\\, y} --ar 16:9 --raw")
    assert rc == 1 and "permutation" in out["error"]
    rc, out = K.run("relay", "job", "--kind", "midjourney", "--text", "a red door, at night --ar 16:9", "--text",
                    "a city --ar 16:9", "--plate", "hall-ms")
    assert rc == 1 and "one per --text" in out["error"]
    rc, out = K.run("relay", "job", "--kind", "midjourney", "--text", "a red door, at night --ar 16:9", "--plate",
                    "hall-ms", "--text", "a city {at night} --ar 16:9", "--plate", "city-ws")
    assert rc == 0, out
    rc, r = K.run("relay", "read")
    j = next(j for j in r["jobs"] if j["job_kind"] == "midjourney")
    assert j["plates"] == ["hall-ms", "city-ws"] and j["expect_count"] == 8
    assert "plates: hall-ms, city-ws" in r["text"]


def test_grok_sees_every_field_of_a_job(tmp_path, monkeypatch):
    RT.setup(tmp_path, monkeypatch)
    assert K.run("relay", "setup")[0] == 0
    K.run("relay", "job", "--kind", "browser", "--url", "https://example.com/page", "--note", "read the title")
    K.run("relay", "job", "--kind", "suno", "--title", "Hook", "--style", "glassy synth pop", "--exclude", "metal",
          "--lyrics", "[Verse]\nla la")
    rc, r = K.run("relay", "read")
    assert "your browser at https://example.com/page" in r["grok_next"]
    for want in ("url: https://example.com/page", "title: Hook", "style: glassy synth pop", "exclude: metal",
                 "lyrics:\n[Verse]\nla la"):
        assert want in r["text"], want


@pytest.mark.parametrize("route", ["browser", "native"])
def test_done_reports_each_files_real_size(tmp_path, monkeypatch, route):
    """grok.com's button can show the highest resolution and still render lower: the production learns each file's
    real size, and on the browser route Grok is warned about a file that came out smaller than the rest (by area, so a
    portrait still is no warning). Grok's own tool has no such button: the sizes go to the production, no warning."""
    from PIL import Image
    env = RT.setup(tmp_path, monkeypatch)
    assert K.run("relay", "setup")[0] == 0
    job = (("--what", "clip", "--res", "1080p") if route == "browser" else ("--what", "still"))
    rc, out = K.run("relay", "job", "--kind", "grok-imagine", *job, "--prompt", "her on a rooftop")
    assert rc == 0, out
    save = Path(out["save"])
    for name, size in (("a.png", (1280, 704)), ("b.png", (704, 1280)), ("c.png", (736, 400))):
        Image.new("RGB", size, (20, 20, 20)).save(save / name)
    rc, done = K.run("relay", "done", out["job"], "--file", "a.png", "--file", "b.png", "--file", "c.png")
    assert rc == 0, done
    assert done["sizes"] == {str(save / "a.png"): "1280x704", str(save / "b.png"): "704x1280",
                             str(save / "c.png"): "736x400"}
    if route == "browser":
        assert "c.png" in done["warn"] and "a.png" not in done["warn"] and "b.png" not in done["warn"]
    else:
        assert "warn" not in done, done
    msg = [json.loads(x) for x in (env["rd"] / "inbox.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()][-1]
    assert "\nsizes: a.png 1280x704, b.png 704x1280, c.png 736x400" in msg["text"]


def test_a_save_path_from_the_projects_folder_is_not_doubled(tmp_path, monkeypatch):
    env = RT.setup(tmp_path, monkeypatch)
    assert K.run("new", "announce")[0] == 0
    assert K.run("relay", "setup")[0] == 0
    proj = env["wd"] / "announce"
    for save, want in (("announce/inbox/hd", proj / "inbox" / "hd"), ("inbox/hd2", proj / "inbox" / "hd2"),
                       (str(tmp_path / "abs"), tmp_path / "abs")):
        rc, out = K.run("-p", "announce", "relay", "job", "--kind", "grok-imagine", "--what", "still", "--prompt",
                        "x", "--save", save)
        assert rc == 0 and Path(out["save"]) == want.absolute(), (save, out["save"])
    rc, out = K.run("-p", "announce", "relay", "job", "--kind", "person", "--text", "x", "--expect",
                    "announce/song/take.wav")
    rc, r = K.run("relay", "read")
    assert r["jobs"][-1]["expect"] == [str((proj / "song" / "take.wav").absolute())]


def test_videos_and_big_files_go_by_drive_link(tmp_path, monkeypatch):
    env = RT.setup(tmp_path, monkeypatch)
    clip = tmp_path / "v1-excerpt.mp4"
    clip.write_bytes(b"\0" * 1000)
    monkeypatch.setenv("FAKE_RELAY_SHOW", str(clip))
    assert K.run("relay", "setup")[0] == 0
    K.run("relay", "send", "the excerpt please")
    items, r = RT.collect(lambda it, r: any(i.get("files") for i in it))
    r = K.run("relay", "read", "--all")[1]
    assert "send v1-excerpt.mp4 as Google Drive links: skill drive" in r["grok_next"], r["grok_next"]
    assert relay._by_link(str(clip)) and not relay._by_link(str(tmp_path / "sheet.jpg"))


def test_a_changed_brief_is_read_again(tmp_path, monkeypatch):
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "home"))
    (tmp_path / "home" / "relay").mkdir(parents=True)
    wd = tmp_path / "work"
    wd.mkdir()
    (wd / "CLAUDE.md").write_text("brief one\n", encoding="utf-8")
    first = relay._prompt(wd, {"engine": "claude"}, 1, [], None)
    assert "read it now if this session has not" in first
    assert "read it now if this session has not" in relay._prompt(wd, {"engine": "claude"}, 2, [], None)
    (wd / "CLAUDE.md").write_text("brief two\n", encoding="utf-8")
    assert "it changed since you last read it: read it again now" in relay._prompt(wd, {"engine": "claude"}, 3, [],
                                                                                    None)


def test_an_update_keeps_the_persons_model(tmp_path, monkeypatch):
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "home"))
    rd = tmp_path / "home" / "relay"
    rd.mkdir(parents=True)
    (rd / "config.json").write_text(json.dumps({"engine": "claude", "model": "opus-custom"}), encoding="utf-8")
    seen = {}

    def run(argv, **kw):
        seen["argv"] = argv
        return subprocess.CompletedProcess(argv, 0, json.dumps({"ok": True}), "")
    monkeypatch.setattr(update.subprocess, "run", run)
    assert update._refresh_brief() == {"ok": True}
    assert seen["argv"][-4:] == ["--engine", "claude", "--model", "opus-custom"]


def test_the_scorer_runs_without_the_cmudict_package(tmp_path):
    code = ("import sys, runpy; sys.modules['cmudict'] = None; "
            f"sys.argv = ['scansion.py', 'line', 'hello there my friend', '--mode', 'sung']; "
            f"runpy.run_path({str(ROOT / 'tools' / 'scansion.py')!r}, run_name='__main__')")
    env = {**os.environ, "SLOP_HOME": str(tmp_path), "SLOP_OFFLINE": "1"}
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=120)
    assert "Traceback" not in r.stderr, r.stderr[-800:]
    assert r.returncode == 0 or "no CMU dictionary" in r.stderr


def test_login_shells_load_env_sh(tmp_path, monkeypatch):
    env = RT.setup(tmp_path, monkeypatch)
    env_sh = Path(os.environ["SLOP_HOME"]) / "env.sh"
    env_sh.write_text("export PATH=/x:$PATH\n", encoding="utf-8")
    home = Path(os.environ["HOME"])
    (home / ".bashrc").write_text("# mine", encoding="utf-8")
    for _ in range(2):
        assert K.run("relay", "setup")[0] == 0
    for f in (".profile", ".bashrc"):
        text = (home / f).read_text(encoding="utf-8")
        assert text.count(f". {env_sh}") == 1, (f, text)
    assert (home / ".bashrc").read_text(encoding="utf-8").startswith("# mine\n")

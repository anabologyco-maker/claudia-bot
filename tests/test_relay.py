"""`slop relay`: Grok passes words, the production works. Every engine here is tests/fixtures/agents/fakecli.py (with
$FAKE_RELAY it plays the production: it posts `slop relay say "heard #N: ..."` through the relay's own `slop`), so no
token is spent and nothing touches the network."""
from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import threading
import time
import zipfile
from pathlib import Path

import pytest

_K = Path(__file__).parent / "fixtures" / "agents" / "kit.py"
_spec = importlib.util.spec_from_file_location("agents_kit", _K)
K = importlib.util.module_from_spec(_spec); sys.modules.setdefault("agents_kit", K); _spec.loader.exec_module(K)

pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX fake CLIs")
MCP_ADD = ["mcp", "add", "--transport", "http", "--scope", "user", "claudia", "https://claudia.gallery/mcp"]


def setup(tmp_path, monkeypatch, logged=("claude",), sleep=None):
    env = K.setup(tmp_path, monkeypatch, engines=("claude", "codex"), logged=logged)
    monkeypatch.setenv("SLOP_PROJECTS", str(tmp_path / "projects"))
    monkeypatch.setenv("FAKE_RELAY", "1")
    for k in ("FAKE_RELAY_SLEEP", "FAKE_RELAY_FAIL", "FAKE_RELAY_SHOW", "SLOP_RELAY_TURN"):
        monkeypatch.delenv(k, raising=False)
    if sleep is not None:
        monkeypatch.setenv("FAKE_RELAY_SLEEP", str(sleep))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("claudia/SKILL.md", "---\nname: claudia\n---\n# Claudia\n")
        z.writestr("../evil.txt", "never written")
    (tmp_path / "skill.zip").write_bytes(buf.getvalue())
    monkeypatch.setenv("SLOP_RELAY_SKILL_URL", (tmp_path / "skill.zip").as_uri())
    env["rd"] = env["sh"] / "relay"
    env["wd"] = tmp_path / "projects"
    return env


def relay_calls(env) -> list[dict]:
    return [c for c in K.calls(env["state"], "claude") + K.calls(env["state"], "codex") if c.get("relay")]


def collect(until, secs=40.0, wait=10) -> tuple[list, dict]:
    """read --wait until until(items, last_read) holds; returns every item seen."""
    items, t0, r = [], time.monotonic(), {}
    while time.monotonic() - t0 < secs:
        rc, r = K.run("relay", "read", "--wait", str(wait))
        assert rc == 0, r
        items += r["items"]
        if until(items, r):
            return items, r
        if r["production"]["state"] != "working":
            time.sleep(0.2)
    raise AssertionError(f"timed out; items {items}; last read {r}")


def wait_turn_running(env, secs=20.0) -> dict:
    t0, tj = time.monotonic(), {}
    while time.monotonic() - t0 < secs:
        tj = json.loads((env["rd"] / "turn.json").read_text()) if (env["rd"] / "turn.json").is_file() else {}
        if tj.get("state") == "running" and relay_calls(env):
            return tj
        time.sleep(0.1)
    log = (env["rd"] / "relay.log").read_text() if (env["rd"] / "relay.log").is_file() else ""
    raise AssertionError(f"no turn started: turn.json {tj}; calls {relay_calls(env)}; log {log}")


# ------------------------------------------------------------------------------------------------------- setup
def test_setup_registers_the_mcp_installs_the_skill_and_writes_the_brief(tmp_path, monkeypatch):
    env = setup(tmp_path, monkeypatch)
    rc, out = K.run("relay", "setup")
    assert rc == 0 and out["ok"], out
    adds = [c for c in K.calls(env["state"], "claude") if c["argv"][:2] == ["mcp", "add"]]
    assert [c["argv"] for c in adds] == [MCP_ADD]
    for name in ("CLAUDE.md", "AGENTS.md"):
        text = (env["wd"] / name).read_text()
        assert text.startswith("<!-- slop relay: production brief") and "\r" not in text
        assert "claudia_canon" in text and "Silence never approves spending" in text and "{{" not in text
        assert "slop relay say" in text and "slop relay inbox" in text
        assert "slop -p NAME relay job --kind grok-imagine" in text and "--kind midjourney" in text and "--kind person" in text
    skills = env["home"] / ".claude" / "skills"
    assert (skills / "claudia" / "SKILL.md").is_file() and not (skills.parent / "evil.txt").exists()
    assert out["skill"]["skills"] == ["claudia"]
    cfg = json.loads((env["rd"] / "config.json").read_text())
    assert cfg["engine"] == "claude" and cfg["model"] == "opus"
    codex = (env["home"] / ".codex" / "config.toml").read_text()     # Codex gets the claudia MCP too
    assert "[mcp_servers.claudia]" in codex and 'url = "https://claudia.gallery/mcp"' in codex
    assert out["mcp_also"]["codex"]["ok"]
    for name in ("CLAUDE.md", "AGENTS.md"):                         # the home GPU is parked: never offered
        text = (env["wd"] / name).read_text()
        assert "never offer, pair or wait for a GPU" in text and "gpu pair" not in text
    rc, out = K.run("relay", "setup")                      # idempotent: no second registration
    assert rc == 0 and out["mcp"]["already"] is True
    assert len([c for c in K.calls(env["state"], "claude") if c["argv"][:2] == ["mcp", "add"]]) == 1


def test_setup_stops_with_the_sign_in_step_and_keeps_a_foreign_brief(tmp_path, monkeypatch):
    env = setup(tmp_path, monkeypatch, logged=())
    rc, out = K.run("relay", "setup")
    assert rc == 1 and out["next"] == "slop agents login claude" and not (env["wd"] / "CLAUDE.md").exists()
    rc, out = K.run("relay", "send", "hello")
    assert rc == 1 and "relay setup" in out["error"]
    (env["state"] / "claude_logged_in").write_text("1")
    (env["wd"] / "CLAUDE.md").write_text("# my own notes\n")
    rc, out = K.run("relay", "setup")
    assert rc == 1 and "--force" in out["next"] and (env["wd"] / "CLAUDE.md").read_text() == "# my own notes\n"
    rc, out = K.run("relay", "setup", "--force")
    assert rc == 0 and "production brief" in (env["wd"] / "CLAUDE.md").read_text()


def test_codex_setup_writes_its_config_once(tmp_path, monkeypatch):
    env = setup(tmp_path, monkeypatch, logged=("codex",))
    cfg = env["home"] / ".codex" / "config.toml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text('model = "gpt-6"\n\n[mcp_servers.other]\nurl = "https://example.com/mcp"\n')
    for _ in range(2):
        rc, out = K.run("relay", "setup", "--engine", "codex")
        assert rc == 0, out
    text = cfg.read_text()
    assert text.count("[mcp_servers.claudia]") == 1 and 'url = "https://claudia.gallery/mcp"' in text
    assert 'model = "gpt-6"' in text and "[mcp_servers.other]" in text
    adds = [c for c in K.calls(env["state"], "claude") if c["argv"][:2] == ["mcp", "add"]]
    assert len(adds) == 1 and out["mcp_also"]["claude"]["ok"], "Claude Code gets the claudia MCP too, once"


# ------------------------------------------------------------------------------------------------------- the loop
def test_send_turn_say_ask_read(tmp_path, monkeypatch):
    env = setup(tmp_path, monkeypatch)
    sheet = tmp_path / "sheet.png"
    sheet.write_bytes(K.FIX.joinpath("fakecli.py").read_bytes()[:10])
    monkeypatch.setenv("FAKE_RELAY_SHOW", str(sheet))
    assert K.run("relay", "setup")[0] == 0
    t0 = time.monotonic()
    rc, out = K.run("relay", "send", "a still of her on a rooftop, which light?")
    assert rc == 0 and out["started"] and out["id"] == 1, out
    assert time.monotonic() - t0 < 10
    items, r = collect(lambda it, r: any(i["kind"] == "ask" for i in it) and r["production"]["state"] != "working")
    say = next(i for i in items if i["kind"] == "say")
    assert say["text"] == "heard #1: a still of her on a rooftop, which light?" and say["files"] == [str(sheet)]
    ask = next(i for i in items if i["kind"] == "ask")
    assert ask["text"] == "Which one?" and ask["default"] == "A"
    assert r["production"]["state"] == "waiting" and "answer" in r["grok_next"]
    c = relay_calls(env)[0]
    assert c["cwd"] == str(env["wd"]) and c["slop"] == str(env["rd"] / "bin" / "slop") and c["turn"] == "1"
    argv = c["argv"]
    assert argv[argv.index("--permission-mode") + 1] == "bypassPermissions" and "stream-json" in argv
    assert argv[argv.index("--model") + 1] == "opus" and "--resume" not in argv
    assert "decisions.md" in os.listdir(env["rd"])
    assert "rooftop" in (env["rd"] / "decisions.md").read_text()
    rc, again = K.run("relay", "read")                      # items are shown once
    assert again["items"] == [] and K.run("relay", "read", "--all")[1]["count"] == 2
    for f in env["rd"].rglob("*"):
        if f.is_file() and f.suffix in (".json", ".jsonl", ".log", ".md"):
            assert b"\r" not in f.read_bytes(), f


def test_a_send_while_running_is_picked_up_by_the_next_turn(tmp_path, monkeypatch):
    env = setup(tmp_path, monkeypatch, sleep=2)
    assert K.run("relay", "setup")[0] == 0
    assert K.run("relay", "send", "one")[1]["started"]
    wait_turn_running(env)
    t0 = time.monotonic()
    rc, out = K.run("relay", "send", "two")
    assert rc == 0 and out["started"] is False and out["queued"] and time.monotonic() - t0 < 5, out
    items, r = collect(lambda it, r: {"heard #1: one", "heard #2: two"} <= {i["text"] for i in it}
                       and r["production"]["state"] == "idle")
    calls = relay_calls(env)
    assert [c["messages"] for c in calls] == [[1], [2]]
    assert calls[1]["resumed"] and calls[1]["session"] == calls[0]["session"]
    assert calls[1]["argv"][calls[1]["argv"].index("--resume") + 1] == calls[0]["session"]
    st = json.loads((env["rd"] / "state.json").read_text())
    assert st["turns"] == 2 and st["delivered"] == 2 and st["sessions"]["claude"] == calls[0]["session"]


def test_read_wait_returns_early(tmp_path, monkeypatch):
    env = setup(tmp_path, monkeypatch, sleep=2)
    assert K.run("relay", "setup")[0] == 0
    t0 = time.monotonic()
    rc, r = K.run("relay", "read", "--wait", "30")          # idle: nothing to wait for
    assert rc == 0 and time.monotonic() - t0 < 5 and r["production"]["state"] == "idle"
    assert "relay send" in r["grok_next"]
    K.run("relay", "send", "hello")
    t0 = time.monotonic()
    items, r = collect(lambda it, r: bool(it), wait=60)
    assert time.monotonic() - t0 < 30 and items[0]["text"] == "heard #1: hello"
    res = {}
    th = threading.Thread(target=lambda: res.update(r=K.run("relay", "read", "--wait", "60")[1]))
    (env["rd"] / "runner.json").write_text(json.dumps({"state": "running", "pid": os.getpid()}) + "\n")
    t0 = time.monotonic()
    th.start()
    time.sleep(1.0)
    K.run("relay", "say", "a direct post")
    th.join(30)
    assert time.monotonic() - t0 < 10 and res["r"]["items"][0]["text"] == "a direct post"
    assert "Post this message verbatim" in res["r"]["grok_next"]


def test_jobs_done_and_fail_reach_the_production(tmp_path, monkeypatch):
    env = setup(tmp_path, monkeypatch)
    assert K.run("relay", "setup")[0] == 0
    rc, out = K.run("relay", "job", "--kind", "grok-imagine", "--what", "still", "--prompt", "her on a rooftop",
                    "--aspect", "16:9")
    assert rc == 0 and out["job"] == "J-0001", out
    save = Path(out["save"])
    assert save == env["wd"] / "inbox" / "grok-imagine" and save.is_dir()
    rc, out = K.run("relay", "job", "--kind", "grok-imagine", "--what", "clip", "--prompt", "x", "--image", "nope.png")
    assert rc == 1 and "--image" in out["error"]
    rc, out = K.run("relay", "job", "--kind", "person", "--what", "song", "--text", "[Verse]\nla la", "--expect",
                    "song/take1.wav")
    assert rc == 0 and out["job"] == "J-0002"
    rc, r = K.run("relay", "read")
    jobs = {j["job"]: j for j in r["jobs"]}
    assert jobs["J-0001"]["prompt"] == "her on a rooftop" and jobs["J-0001"]["aspect"] == "16:9"
    assert jobs["J-0002"]["expect"] == [str(env["wd"] / "song" / "take1.wav")]
    assert r["grok_next"].startswith("Claim job J-0001") and "then run it with skill grok-imagine" in r["grok_next"]
    assert "J-0002 to the person" in r["grok_next"]
    rc, out = K.run("relay", "done", "J-0001", "--file", "missing.png")
    assert rc == 1 and "no such file" in out["error"]
    (save / "J-0001-1.png").write_bytes(b"png")
    rc, out = K.run("relay", "done", "J-0001", "--file", "J-0001-1.png")
    assert rc == 0 and out["started"] and out["files"] == [str(save / "J-0001-1.png")], out
    items, r = collect(lambda it, r: bool(it))
    assert items[0]["text"] == f"heard #1: [grok] J-0001 done: files {save / 'J-0001-1.png'}"
    assert [j["job"] for j in r["jobs"]] == ["J-0002"]
    rc, out = K.run("relay", "done", "J-0001", "--file", str(save / "J-0001-1.png"))
    assert rc == 1 and "already done" in out["error"]
    rc, out = K.run("relay", "fail", "J-0002", "--reason", "the person has no Suno plan", "--declined")
    assert rc == 0 and out["status"] == "declined"
    collect(lambda it, r: any("declined by the service" in i["text"] for i in it))
    assert K.run("relay", "status")[1]["jobs"] == []


def test_a_failed_turn_keeps_its_messages_and_the_next_send_retries(tmp_path, monkeypatch):
    env = setup(tmp_path, monkeypatch)
    assert K.run("relay", "setup")[0] == 0
    monkeypatch.setenv("FAKE_RELAY_FAIL", "1")
    K.run("relay", "send", "first")
    _, r = collect(lambda it, r: r["production"]["state"] == "failed")
    assert "usage limit" in r["grok_next"] and r["production"]["pending"] == 1
    monkeypatch.delenv("FAKE_RELAY_FAIL")
    K.run("relay", "send", "continue", "--from", "grok")
    items, r = collect(lambda it, r: len(it) >= 2 and r["production"]["state"] == "idle")
    assert [i["text"] for i in items] == ["heard #1: first", "heard #2: continue"]
    assert relay_calls(env)[-1]["messages"] == [1, 2]
    assert "continue" not in (env["rd"] / "decisions.md").read_text()      # Grok's notes are not director words


def test_stop(tmp_path, monkeypatch):
    env = setup(tmp_path, monkeypatch, sleep=60)
    assert K.run("relay", "setup")[0] == 0
    K.run("relay", "send", "a long one")
    wait_turn_running(env)
    rc, out = K.run("relay", "stop", "--grace", "3")
    assert rc == 0 and out["stopped"], out
    assert K.run("relay", "status")[1]["production"]["state"] == "stopped"
    t0 = time.monotonic()
    while time.monotonic() - t0 < 10 and K.pids_alive(f"fakecli.py claude -p"):
        time.sleep(0.2)
    assert not K.pids_alive("fakecli.py claude -p")
    assert json.loads((env["rd"] / "turn.json").read_text())["state"] in ("stopped", "failed")
    rc, out = K.run("relay", "stop")
    assert rc == 0 and out["stopped"] is False
    monkeypatch.setenv("FAKE_RELAY_SLEEP", "0")
    assert K.run("relay", "send", "again")[1]["started"]
    collect(lambda it, r: any(i["text"] == "heard #2: again" for i in it))


def test_codex_production_resumes_its_thread(tmp_path, monkeypatch):
    env = setup(tmp_path, monkeypatch, logged=("codex",))
    assert K.run("relay", "setup", "--engine", "codex")[0] == 0
    K.run("relay", "send", "one")
    collect(lambda it, r: bool(it) and r["production"]["state"] == "idle")
    K.run("relay", "send", "two")
    collect(lambda it, r: bool(it) and r["production"]["state"] == "idle")
    a, b = relay_calls(env)
    assert a["argv"][:1] == ["exec"] and "-C" in a["argv"] and 'sandbox_mode="danger-full-access"' in a["argv"]
    assert b["argv"][:2] == ["exec", "resume"] and b["argv"][-2] == a["session"] and b["resumed"]

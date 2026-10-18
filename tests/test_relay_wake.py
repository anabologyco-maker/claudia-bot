"""Wake-ups (0.3.0): the relay calls Grok's wake-up routine (a webhook) when the production - Claude Code or Codex -
posts something Grok has not read while Grok is not waiting, and when a turn fails. Once per burst of posts; the key
from $CLAUDIA_WAKE_KEY goes in the Authorization header and is never printed; the body names the kind of news, never
its words."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import test_relay as RT  # noqa: E402  (its fake engine and helpers)
K = RT.K

KEY = "wk-test-0123456789abcdef"


@pytest.fixture
def hook():
    got: list[dict] = []

    class Hook(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            n = int(self.headers.get("Content-Length") or 0)
            got.append({"path": self.path, "auth": self.headers.get("Authorization"),
                        "body": json.loads(self.rfile.read(n) or b"{}")})
            self.send_response(int(os.environ.get("FAKE_HOOK_STATUS", "200")))
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Hook)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield {"url": f"http://127.0.0.1:{srv.server_address[1]}/hooks/routine-abc123", "got": got}
    srv.shutdown()


def _until(cond, secs: float = 40.0) -> bool:
    t0 = time.monotonic()
    while time.monotonic() - t0 < secs:
        if cond():
            return True
        time.sleep(0.2)
    return False


def _idle() -> bool:
    return K.run("relay", "status")[1]["production"]["state"] in ("idle", "waiting", "failed")


def _ready(tmp_path, monkeypatch, hook, engine="claude", **kw) -> dict:
    env = RT.setup(tmp_path, monkeypatch, logged=(engine,), **kw)
    monkeypatch.setenv("CLAUDIA_WAKE_KEY", KEY)
    assert K.run("relay", "setup", "--engine", engine)[0] == 0
    rc, out = K.run("relay", "wake", hook["url"])
    assert rc == 0 and out["on"] and out["key"], out
    return env


def test_the_wake_up_setting(tmp_path, monkeypatch):
    RT.setup(tmp_path, monkeypatch)
    monkeypatch.setenv("CLAUDIA_WAKE_KEY", KEY)
    rc, out = K.run("relay", "wake")
    assert rc == 0 and out["on"] is False and "off" in out["text"]
    for bad in ("ftp://hooks.example.com/h", "http://hooks.example.com/h", "not a url"):
        rc, out = K.run("relay", "wake", bad)
        assert rc == 1 and "https://" in out["error"], bad
    rc, out = K.run("relay", "wake", "https://hooks.example.com/v1/routines/abc/secretpart9")
    assert rc == 0 and out["on"] and out["url"] == "https://hooks.example.com/...art9" and out["key"] is True
    assert "secretpart9" not in json.dumps(out) and KEY not in json.dumps(out)
    rc, out = K.run("relay", "wake", "off")
    assert rc == 0 and out["on"] is False


@pytest.mark.parametrize("engine", ["claude", "codex"])
def test_a_post_wakes_grok_once_whichever_engine_produces(tmp_path, monkeypatch, hook, engine):
    _ready(tmp_path, monkeypatch, hook, engine)
    K.run("relay", "send", "a still of her on a rooftop")
    assert _until(lambda: hook["got"]), "no wake-up"
    w = hook["got"][0]
    assert w["auth"] == f"Bearer {KEY}" and w["path"] == "/hooks/routine-abc123"
    assert w["body"]["event"] in ("posted", "finished") and w["body"]["unread"] >= 1 and "say" in w["body"]["kinds"]
    assert "rooftop" not in json.dumps(w["body"]), "the body never carries the words"
    assert _until(_idle)
    time.sleep(3)
    assert len(hook["got"]) == 1, hook["got"]
    rc, r = K.run("relay", "read")
    assert any("rooftop" in i["text"] for i in r["items"])
    time.sleep(3)
    assert len(hook["got"]) == 1, "what Grok read wakes nobody"


def test_no_wake_up_while_grok_waits(tmp_path, monkeypatch, hook):
    _ready(tmp_path, monkeypatch, hook, sleep=3)
    K.run("relay", "send", "hello")
    reader = subprocess.Popen([sys.executable, "-m", "slop", "--json", "relay", "read", "--wait", "40"],
                              stdout=subprocess.PIPE, text=True, env=os.environ.copy())
    out = json.loads(reader.communicate(timeout=60)[0].strip().splitlines()[-1])
    assert any("hello" in i["text"] for i in out["items"]), out
    assert _until(_idle)
    time.sleep(3)
    assert hook["got"] == [], "Grok was waiting: no wake-up"


def test_a_failed_turn_wakes_grok(tmp_path, monkeypatch, hook):
    _ready(tmp_path, monkeypatch, hook)
    monkeypatch.setenv("FAKE_RELAY_FAIL", "1")                   # after setup, which clears it
    K.run("relay", "send", "first")
    assert _until(lambda: hook["got"]), "no wake-up"
    assert hook["got"][0]["body"]["event"] == "failed" and hook["got"][0]["body"]["production"] == "failed"


def test_whatever_the_person_copied_works(tmp_path, monkeypatch, hook):
    """The routine's settings offer the key and a ready "Authorization: Bearer <key>" line; the URL is pasted with
    whatever came along with it."""
    RT.setup(tmp_path, monkeypatch)
    rc, out = K.run("relay", "wake", f"POST to {hook['url']}.")
    assert rc == 0 and out["on"], out
    for pasted in (KEY, f"Authorization: Bearer {KEY}", f"Bearer {KEY}", f'"{KEY}"'):
        monkeypatch.setenv("CLAUDIA_WAKE_KEY", pasted)
        rc, out = K.run("relay", "wake", "test")
        assert rc == 0 and out["ok"], (pasted, out)
        assert hook["got"][-1]["auth"] == f"Bearer {KEY}" and hook["got"][-1]["path"] == "/hooks/routine-abc123"


def test_only_the_routines_real_address_is_taken(tmp_path, monkeypatch, hook):
    """A URL built from the routine's id was turned down (401) on a live bot: the relay takes only the POST to
    address, and says so when given the routine's link."""
    RT.setup(tmp_path, monkeypatch)
    monkeypatch.setenv("CLAUDIA_WAKE_KEY", KEY)
    link = "grokbot://app/v1/agent?id=AGENT01&tab=routines&automation=auto_Abc123xyz&target=webhook-key"
    rc, out = K.run("relay", "wake", link)
    assert rc == 1 and "POST to address" in out["error"], out
    rc, out = K.run("relay", "wake", "https://cursor.com/grok-bot/link/v1/agent?id=A&automation=auto_Abc123xyz")
    assert rc == 1 and "not its webhook address" in out["error"], out
    rc, out = K.run("relay", "wake", f"POST to {hook['url']}")
    assert rc == 0 and out["on"]
    rc, out = K.run("relay", "wake", "test")
    assert rc == 0 and hook["got"][-1]["path"] == "/hooks/routine-abc123"

def test_wake_test_and_a_turned_down_key(tmp_path, monkeypatch, hook):
    RT.setup(tmp_path, monkeypatch)
    monkeypatch.setenv("CLAUDIA_WAKE_KEY", KEY)
    rc, out = K.run("relay", "wake", "test")
    assert rc == 1 and "off" in out["error"]
    K.run("relay", "wake", hook["url"])
    rc, out = K.run("relay", "wake", "test")
    assert rc == 0 and out["ok"] and hook["got"][-1]["body"]["event"] == "test"
    monkeypatch.setenv("FAKE_HOOK_STATUS", "401")
    rc, out = K.run("relay", "wake", "test")
    assert rc == 1 and out["ok"] is False and "CLAUDIA_WAKE_KEY" in out["error"] and KEY not in json.dumps(out)
    assert K.run("relay", "setup")[0] == 0
    assert "wake-ups: on" in K.run("relay", "status")[1]["text"]

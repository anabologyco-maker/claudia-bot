"""`slop agents login`: the sign-in keeper (a background `slop job`), driven against fake CLIs that print what the real
ones print (Claude Code paste flow, Codex and Muse device flows, Gemini under a pseudo-terminal). No network."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import threading
from pathlib import Path

import pytest

_K = Path(__file__).parent / "fixtures" / "agents" / "kit.py"
_spec = importlib.util.spec_from_file_location("agents_kit", _K)
K = importlib.util.module_from_spec(_spec); sys.modules.setdefault("agents_kit", K); _spec.loader.exec_module(K)

pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX: FIFOs, process groups, pseudo-terminals")

GOOD = "good-code#0123456789abcdef"


@pytest.fixture
def env(tmp_path, monkeypatch):
    return K.setup(tmp_path, monkeypatch)


def _cleanup(*engines):
    from slop.agents import login
    for e in engines:
        try:
            login.cancel(e)
        except Exception:  # noqa: BLE001
            pass


def test_claude_paste_flow_end_to_end(env, monkeypatch):
    try:
        rc, out = K.run("agents", "login", "claude")
        assert rc == 0, out
        assert out["state"] == "waiting_code" and out["url"].startswith("https://claude.com/cai/oauth/authorize?")
        assert out["code_secret"] == "CLAUDE_LOGIN_CODE"
        assert out["next"] == "slop agents login claude --code-from-env CLAUDE_LOGIN_CODE"
        assert "SECURE SECRET CARD named CLAUDE_LOGIN_CODE" in out["text"]
        fifo = env["sh"] / "agents" / "login" / "claude" / "code.fifo"
        assert fifo.exists() and oct(fifo.stat().st_mode & 0o777) == "0o600"
        monkeypatch.setenv("CLAUDE_LOGIN_CODE", GOOD)
        rc, out = K.run("agents", "login", "claude", "--code-from-env", "CLAUDE_LOGIN_CODE")
        assert rc == 0, out
        assert out["state"] == "done" and out["logged_in"] is True and out["plan"] == "max"
        assert out["next"] == "slop agents test claude"
        c = K.calls(env["state"], "claude")
        assert c[0]["browser"] == "false"                      # never opens a browser on the box
        assert c[-1]["stdin_head"] == f"len={len(GOOD)}"       # the code reached the CLI's stdin
        # the code is never written anywhere
        for f in list((env["sh"]).rglob("*")):
            if f.is_file():
                assert GOOD not in f.read_text(encoding="utf-8", errors="replace"), f
        assert not fifo.exists()
        rc, st = K.run("agents", "status", "claude")
        assert st["agents"][0]["logged_in"] is True and st["agents"][0]["plan"] == "max"
    finally:
        _cleanup("claude")


def test_claude_wrong_code_fails_and_a_new_link_is_needed(env, monkeypatch):
    try:
        rc, out = K.run("agents", "login", "claude")
        assert out["state"] == "waiting_code"
        monkeypatch.setenv("CLAUDE_LOGIN_CODE", "wrong-code#000000000000")
        rc, out = K.run("agents", "login", "claude", "--code-from-env", "CLAUDE_LOGIN_CODE")
        assert rc == 1 and out["state"] == "failed"
        assert "did not accept the code" in out["error"] and out["next"] == "slop agents login claude"
        assert any("wasn't accepted" in t for t in out["tail"])   # the 2.1.3xx wording
        assert not K.pids_alive("fakecli.py claude auth login")   # the waiting CLI was killed
        rc, out = K.run("agents", "login", "claude", "--code-from-env", "CLAUDE_LOGIN_CODE")
        assert rc == 1 and "no Claude Code sign-in is waiting" in out["error"] and "NEW link" in out["error"]
    finally:
        _cleanup("claude")


def test_code_from_env_checks_the_variable_not_the_value(env, monkeypatch):
    rc, out = K.run("agents", "login", "claude", "--code-from-env", "CLAUDE_LOGIN_CODE")
    assert rc == 1 and "CLAUDE_LOGIN_CODE is not set" in out["error"] and "secure secret card" in out["error"]
    rc, out = K.run("agents", "login", "claude", "--code-from-env", "abc#defghijkl123")
    assert rc == 1 and "NAME of an environment variable" in out["error"]
    monkeypatch.setenv("CLAUDE_LOGIN_CODE", "two words here")
    rc, out = K.run("agents", "login", "claude", "--code-from-env", "CLAUDE_LOGIN_CODE")
    assert rc == 1 and "does not look like a sign-in code" in out["error"] and "two words" not in json.dumps(out)
    rc, out = K.run("agents", "login", "codex", "--code-from-env", "CLAUDE_LOGIN_CODE")
    assert rc == 1 and "does not take a pasted code" in out["error"]


def test_codex_device_flow_and_plan(env):
    try:
        rc, out = K.run("agents", "login", "codex")
        assert rc == 0 and out["state"] == "waiting_approval", out
        assert out["url"] == "https://auth.openai.com/codex/device" and out["user_code"] == "ABCD-EFGHI"
        assert "never a code someone else sent them" in out["text"]
        call = K.calls(env["state"], "codex")[-1]
        assert call["argv"][:2] == ["login", "--device-auth"] and 'forced_login_method="chatgpt"' in call["argv"]
        (env["state"] / "codex_approve").write_text("1")
        rc, out = K.run("agents", "login", "codex", "--check")
        assert rc == 0 and out["state"] == "done" and out["plan"] == "pro", out
    finally:
        _cleanup("codex")


def test_muse_device_flow_and_status_reads_only_key_names(env, monkeypatch):
    try:
        rc, out = K.run("agents", "login", "muse")
        assert out["state"] == "waiting_approval" and out["user_code"] == "WXYZ-ABCD"
        assert out["url"].startswith("https://auth.meta.com/oauth/device/")
        assert K.calls(env["state"], "muse")[-1]["muse_no_auto_update"] == "1"
        (env["state"] / "muse_approve").write_text("1")
        rc, out = K.run("agents", "login", "muse", "--check")
        assert out["state"] == "done" and out["logged_in"] is True
        monkeypatch.setenv("META_API_KEY", "meta-secret-value-123")
        rc, st = K.run("agents", "status", "muse")
        row = st["agents"][0]
        assert row["auth"] == "meta_account" and any("META_API_KEY" in n for n in row["notes"])
        assert "meta-secret-value-123" not in json.dumps(st)
    finally:
        _cleanup("muse")


def test_gemini_signs_in_under_a_pseudo_terminal(env, monkeypatch):
    try:
        rc, out = K.run("agents", "login", "gemini")
        assert rc == 0 and out["state"] == "waiting_code", out
        assert out["url"].startswith("https://accounts.google.com/") and out["code_secret"] == "GEMINI_LOGIN_CODE"
        settings = json.loads((env["home"] / ".gemini" / "settings.json").read_text())
        assert settings["security"]["auth"]["selectedType"] == "oauth-personal"
        assert K.calls(env["state"], "gemini")[-1]["no_browser"] == "true"
        monkeypatch.setenv("GEMINI_LOGIN_CODE", "4/good-gemini-code-123")
        rc, out = K.run("agents", "login", "gemini", "--code-from-env", "GEMINI_LOGIN_CODE")
        assert rc == 0 and out["state"] == "done" and out["logged_in"] is True, out
        st = json.loads((env["sh"] / "agents" / "login" / "gemini" / "state.json").read_text())
        assert "4/good-gemini-code-123" not in json.dumps(st)        # the pty echo is scrubbed
        assert not K.pids_alive("fakecli.py gemini")                 # the interactive UI was stopped
        rc, s = K.run("agents", "status", "gemini")
        assert s["agents"][0]["auth"] == "google_account" and s["agents"][0]["account"] == "u***@e***.com"
    finally:
        _cleanup("gemini")


def test_start_twice_reuses_the_waiting_session_and_cancel_kills_it(env):
    try:
        rc, a = K.run("agents", "login", "codex")
        rc, b = K.run("agents", "login", "codex")
        assert b["reused"] is True and b["user_code"] == a["user_code"]
        assert len([c for c in K.calls(env["state"], "codex") if c["argv"][:1] == ["login"]]) == 1
        assert K.pids_alive("fakecli.py codex login")
        rc, c = K.run("agents", "login", "codex", "--cancel")
        assert c["state"] == "cancelled"
        assert not K.pids_alive("fakecli.py codex login")
        rc, d = K.run("agents", "login", "codex", "--check")
        assert d["ok"] is False and "cancelled" in d["error"]
    finally:
        _cleanup("codex")


def test_already_signed_in_needs_force(tmp_path, monkeypatch):
    env = K.setup(tmp_path, monkeypatch, logged=("codex",))
    rc, out = K.run("agents", "login", "codex")
    assert rc == 0 and out["already"] is True and "--force" in out["text"]
    assert not K.calls(env["state"], "codex")


def test_not_installed(tmp_path, monkeypatch):
    K.setup(tmp_path, monkeypatch, engines=())
    rc, out = K.run("agents", "login", "claude")
    assert rc == 1 and "slop agents install claude" in out["error"]


def test_keeper_expires_and_reports(env, monkeypatch):
    from slop.agents import login
    monkeypatch.setenv("FAKE_APPROVE_WAIT", "30")
    res = {}
    t = threading.Thread(target=lambda: res.update(login.run_session("codex", ttl=2.0)))
    t.start(); t.join(20)
    assert res["state"] == "expired" and res["ok"] is False
    st = login.read_state("codex")
    assert st["state"] == "expired" and "within" in st["message"]
    assert not K.pids_alive("fakecli.py codex login")


def test_token_from_env_for_claude(env, monkeypatch):
    rc, out = K.run("agents", "login", "claude", "--token-from-env", "CLAUDE_CODE_OAUTH_TOKEN")
    assert rc == 1 and "claude setup-token" in out["error"]
    rc, out = K.run("agents", "login", "claude", "--token-from-env", "MY_TOKEN")
    assert rc == 1 and "only from CLAUDE_CODE_OAUTH_TOKEN" in out["error"]
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-" + "x" * 30)
    rc, out = K.run("agents", "login", "claude", "--token-from-env", "CLAUDE_CODE_OAUTH_TOKEN")
    assert rc == 0 and out["auth"] == "oauth_token" and out["next"] == "slop agents test claude"
    assert "x" * 30 not in json.dumps(out)


def test_key_from_env_for_gemini_keeps_other_settings(env, monkeypatch):
    g = env["home"] / ".gemini"; g.mkdir(parents=True)
    (g / "settings.json").write_text(json.dumps({"ui": {"theme": "x"}}))
    rc, out = K.run("agents", "login", "gemini", "--key-from-env", "GEMINI_API_KEY")
    assert rc == 1 and "aistudio" in out["error"]
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-not-real-0123456789")
    rc, out = K.run("agents", "login", "gemini", "--key-from-env", "GEMINI_API_KEY")
    assert rc == 0 and out["auth"] == "api_key"
    s = json.loads((g / "settings.json").read_text())
    assert s["ui"]["theme"] == "x" and s["security"]["auth"]["selectedType"] == "gemini-api-key"
    rc, st = K.run("agents", "status", "gemini")
    assert st["agents"][0]["auth"] == "api_key" and "AIza-not-real" not in json.dumps(st)
    rc, out = K.run("agents", "login", "codex", "--key-from-env", "OPENAI_API_KEY")
    assert rc == 1 and "plan" in out["error"]


def test_a_keeper_that_cannot_start_says_why_in_its_state(tmp_path, monkeypatch):
    K.setup(tmp_path, monkeypatch, engines=())
    from slop.agents import login
    with pytest.raises(login.SlopError):
        login.run_session("muse", ttl=5)
    st = login.read_state("muse")
    assert st["state"] == "failed" and "slop agents install muse" in st["message"]
    out = login.describe("muse", st)
    assert out["ok"] is False and out["next"] == "slop agents login muse"

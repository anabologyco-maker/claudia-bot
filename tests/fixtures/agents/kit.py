"""Shared setup for tests/test_agents_*.py and tests/test_gen_codex_image.py: a throwaway HOME + SLOP_HOME with fake
agent CLIs (fakecli.py) linked into $SLOP_HOME/bin, a clean PATH (no real agent CLI can be found), no secrets."""
from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import sys
import time
from pathlib import Path

FIX = Path(__file__).resolve().parent
FAKECLI = FIX / "fakecli.py"
ROOT = FIX.parents[2]
ENGINES = ("claude", "codex", "muse", "gemini")
SCRUB_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "OPENAI_API_KEY", "CODEX_API_KEY", "META_API_KEY",
             "GEMINI_API_KEY", "GOOGLE_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDECODE", "CLAUDE_LOGIN_CODE",
             "GEMINI_LOGIN_CODE", "SLOP_PROJECT", "SLOP_JOB_ID", "SLOP_CODEX_IMAGE_FOREGROUND", "SLOP_FREE_ONLY",
             "XDG_CONFIG_HOME", "CLAUDE_CONFIG_DIR", "GEMINI_CLI_HOME", "MUSE_AUTH_PATH", "FAKE_ROUTE_ENGINE",
             "FAKE_CODEX_IMG", "DELEG_CLAUDE_BIN", "DELEG_CODEX_BIN", "DELEG_MUSE_BIN", "DELEG_GEMINI_BIN",
             "FAKE_SCENARIO", "FAKE_REPLY", "SLOP_CODEX_IMAGE_TIMEOUT", "OPENROUTER_API_KEY", "ELEVENLABS_API_KEY")


def modules_with_agents() -> str:
    from slop import cli
    return ",".join(dict.fromkeys(list(cli.MODULES) + ["slop.agents.cli"]))


def setup(tmp_path: Path, monkeypatch, engines=ENGINES, logged=()) -> dict:
    home, sh, state = tmp_path / "home", tmp_path / "sh", tmp_path / "state"
    for d in (home, sh / "bin", state):
        d.mkdir(parents=True, exist_ok=True)
    for k in SCRUB_ENV:
        monkeypatch.delenv(k, raising=False)
    node = shutil.which("node")
    path = [str(Path(sys.executable).parent)] + ([str(Path(node).parent)] if node else []) + ["/usr/bin", "/bin"]
    monkeypatch.setenv("PATH", os.pathsep.join(dict.fromkeys(path)))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("SLOP_HOME", str(sh))
    monkeypatch.setenv("CODEX_HOME", str(home / ".codex"))
    monkeypatch.setenv("FAKE_STATE", str(state))
    monkeypatch.setenv("SLOP_MODULES", modules_with_agents())
    monkeypatch.setenv("SLOP_WAIT_MAX", "12")
    monkeypatch.setenv("PYTHONPATH", str(ROOT))
    if node:
        monkeypatch.setenv("FAKE_NODE", node)
    for e in engines:
        add_fake(sh / "bin", e)
    for e in logged:
        (state / f"{e}_logged_in").write_text("1")
    return {"home": home, "sh": sh, "state": state, "bin": sh / "bin", "node": node}


def add_fake(d: Path, engine: str) -> Path:
    f = Path(d) / engine
    f.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKECLI}" {engine} "$@"\n', encoding="utf-8")
    f.chmod(0o755)
    return f


def run(*argv) -> tuple[int, dict]:
    from slop.cli import main
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(["--json", *argv])
    txt = buf.getvalue().strip().splitlines()
    return rc, json.loads(txt[-1]) if txt else {}


def calls(state: Path, engine: str | None = None) -> list[dict]:
    f = Path(state) / "calls.jsonl"
    if not f.is_file():
        return []
    rows = [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]
    return [r for r in rows if engine is None or r["engine"] == engine]


def wait_state(engine: str, states, secs: float = 20.0) -> dict:
    from slop.agents import login
    t0 = time.time()
    st = None
    while time.time() - t0 < secs:
        st = login.read_state(engine)
        if st and st.get("state") in states:
            return st
        time.sleep(0.1)
    return st or {}


def pids_alive(pattern: str) -> list[int]:
    """Live processes whose command line contains pattern (Linux /proc)."""
    out = []
    for p in Path("/proc").glob("[0-9]*"):
        try:
            cmd = (p / "cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace")
            stat = (p / "stat").read_text()
        except OSError:
            continue
        if pattern in cmd and stat.split(")")[-1].split()[0] != "Z":
            out.append(int(p.name))
    return out

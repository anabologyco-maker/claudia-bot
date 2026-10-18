"""0.3.6 setup after a box reset: the check is not fooled by the projects folder, setup puts the PATH lines back, a
missing venv or package says what to run instead of crashing, and a failing or expiring OpenRouter key reaches Grok
before the next paid call fails on it."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from slop import cli, doctor, relay, util

import test_core_setup as CS  # noqa: E402  (its shell helpers)

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(CS.BASH is None or sys.platform == "win32", reason="needs bash on Linux/macOS")


def _editable_venv(tmp_path: Path) -> Path:
    """A venv whose `slop` is found the way an editable install finds it: a finder appended to sys.meta_path."""
    v = tmp_path / "venv"
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(v)], check=True, timeout=120)
    site = next((v / "lib").glob("python3*/site-packages"))
    (site / "_claudia_finder.py").write_text(
        "import sys\nfrom importlib.machinery import PathFinder\n\n\nclass F:\n    @classmethod\n"
        "    def find_spec(cls, name, path=None, target=None):\n"
        f"        return PathFinder.find_spec(name, [{str(ROOT)!r}]) if name == 'slop' else None\n\n\n"
        "sys.meta_path.append(F)\n")
    (site / "_claudia.pth").write_text("import _claudia_finder\n")
    return v / "bin" / "python"


def test_the_check_is_not_fooled_by_the_projects_folder(tmp_path):
    py = _editable_venv(tmp_path)
    ws = tmp_path / "workspace"
    (ws / "slop" / "projects").mkdir(parents=True)                   # /workspace/slop/projects on the box
    funcs = CS._setup_function("editable_ok", "installed_from")
    r = CS.sh([CS.BASH, "-c", funcs + '\nPY="$1"; REPO="$2"; editable_ok && echo installed; installed_from',
               "x", str(py), str(ROOT)], os.environ, cwd=str(ws))
    assert r.stdout.split() == ["installed", str(ROOT)], r.stdout + r.stderr


def test_setup_puts_the_path_lines_back(tmp_path):
    home = tmp_path / "home-box"
    home.mkdir()
    (home / ".bashrc").write_text("# the box's own lines\n")
    funcs = CS._setup_function("log", "shell_rc_ok", "shell_rc_fix")
    env = {**os.environ, "HOME": str(home), "SLOP_HOME": "/workspace/.claudia"}
    run = lambda body: CS.sh([CS.BASH, "-c", funcs + "\n" + body], env)  # noqa: E731
    assert run("shell_rc_ok").returncode == 1                        # a reset cleared them
    assert run("shell_rc_fix").returncode == 0
    assert run("shell_rc_ok").returncode == 0
    run("shell_rc_fix")                                              # every setup run: never twice
    for rc in (".bashrc", ".profile"):
        assert (home / rc).read_text().count('. "/workspace/.claudia/env.sh"') == 1
    assert (home / ".bashrc").read_text().startswith("# the box's own lines")


def test_after_a_reset_the_launcher_says_what_to_run(tmp_path):
    env = CS._env(tmp_path)
    (tmp_path / "home").mkdir()
    (tmp_path / "home" / "env.sh").write_text('export SLOP_PROFILE="full"\n')   # setup ran before; the venv is gone
    r = CS.sh(["sh", str(CS.SHIM), "--version"], env)
    assert r.returncode == 0 and r.stdout.startswith("slop "), r.stderr
    assert "the toolkit's Python is gone" in r.stderr and "nohup setsid bash" in r.stderr and "--check" in r.stderr


def test_a_missing_package_says_what_to_run(tmp_path, monkeypatch, capsys):
    (tmp_path / "fake_mod.py").write_text(
        "def register(sub):\n"
        "    p = sub.add_parser('boom')\n"
        "    def run(a):\n"
        "        raise ModuleNotFoundError(\"No module named 'scipy'\", name='scipy')\n"
        "    p.set_defaults(func=run)\n")
    (tmp_path / "fake_heavy.py").write_text("import torch_not_here_either as t\n\ndef register(sub):\n    pass\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setenv("SLOP_MODULES", "fake_mod")
    assert cli.main(["--json", "boom"]) == 1
    out = json.loads(capsys.readouterr().out)
    assert "'scipy' is not installed" in out["error"] and "setup.sh" in out["error"] and "traceback" not in out
    monkeypatch.setenv("SLOP_MODULES", "fake_heavy")                    # a module that cannot even load
    assert cli.main(["--json", "--version"]) == 1
    assert "not installed" in json.loads(capsys.readouterr().out)["error"]
    assert cli._missing_package(ModuleNotFoundError("x", name="slop.gpu")) is None   # a slop module: the traceback
    assert "--full" in cli._missing_package(ModuleNotFoundError("x", name="torch"))


def _key(days=None, **kw):
    info = {"present": True, "ok": True, "status": 200, "limit": None, "usage": 3.0}
    if days is not None:
        info["expires_at"] = (datetime.now(tz=timezone.utc) + timedelta(days=days)).isoformat()
    return {**info, **kw}


def test_key_trouble_is_said_before_it_fails():
    T = util.openrouter_key_trouble
    assert T(_key()) is None and T(_key(days=60)) is None
    assert "expires on" in T(_key(days=3)) and "(3 days)" in T(_key(days=3.2))
    assert "expired on" in T(_key(days=-1))
    assert "no longer works" in T({"present": True, "ok": False, "status": 401, "error": "HTTP 401"})
    assert T({"present": True, "ok": False, "status": 0, "error": "unreachable"}) is None
    assert T({"present": False}) is None
    assert "$1.00 left of its $10.00 limit" in T(_key(limit=10, limit_remaining=1))
    weekly = {"remaining_usd": 0.5, "reset_interval": "weekly"}
    assert "weekly budget has $0.50 left" in T(_key(effective_budget=weekly))


def test_the_doctor_names_the_secure_card_and_the_budget(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-placeholder")
    monkeypatch.setattr(util, "openrouter_key_info", lambda **kw: {"present": True, "ok": False, "status": 401,
                                                                   "error": "OpenRouter rejected the key (HTTP 401)"})
    c = doctor.check_openrouter()
    assert c["status"] == "fail" and "secure secret card" in c["fix"]
    monkeypatch.setattr(util, "openrouter_key_info", lambda **kw: _key(
        limit=None, effective_budget={"remaining_usd": 1.25, "reset_interval": "monthly", "resets_at": "2026-11-01"}))
    c = doctor.check_openrouter()
    assert c["status"] == "warn" and "monthly budget has $1.25 left (resets 2026-11-01)" in c["detail"]


def test_a_failing_key_reaches_grok_once_a_day(tmp_path, monkeypatch):
    import test_relay as RT
    env = RT.setup(tmp_path, monkeypatch)
    assert RT.K.run("relay", "setup")[0] == 0
    rd = env["rd"]
    monkeypatch.setenv("SLOP_KEY_WATCH", "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-placeholder")
    calls = []
    monkeypatch.setattr(util, "openrouter_key_info", lambda **kw: calls.append(1) or _key(days=4))
    relay._key_watch(rd)
    says = [r for r in relay._rows(rd / "outbox.jsonl") if r.get("source") == "toolkit"]
    assert len(says) == 1 and "expires on" in says[0]["text"] and "secure secret card" in says[0]["text"]
    relay._key_watch(rd)                                             # checked just now: not again for 12 h
    assert len(calls) == 1
    kw = json.loads((rd / "keywatch.json").read_text())
    kw["checked_ts"] = time.time() - relay.KEY_WATCH_S - 1
    (rd / "keywatch.json").write_text(json.dumps(kw))
    relay._key_watch(rd)                                             # checked again, but told already today
    assert len(calls) == 2 and len([r for r in relay._rows(rd / "outbox.jsonl") if r.get("source") == "toolkit"]) == 1
    r = RT.K.run("relay", "read")[1]
    assert "from the toolkit, not the production" in r["text"], r["text"]


def test_earshot_is_optional_and_never_blocks_the_check(tmp_path):
    env = CS._env(tmp_path)
    r = CS.sh([CS.BASH, str(CS.SETUP), "--check", "--json", "--full"], env)
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert "earshot" in out["optional"] and "earshot" not in out["missing"], out
    r = CS.sh([CS.BASH, str(CS.SETUP), "--check", "--full"], env)
    assert "optional earshot" in " ".join(r.stdout.split()), r.stdout


def test_a_chosen_model_survives_setup_again(tmp_path, monkeypatch):
    import test_relay as RT
    env = RT.setup(tmp_path, monkeypatch)
    assert RT.K.run("relay", "setup", "--model", "sonnet")[1]["model"] == "sonnet"
    assert RT.K.run("relay", "setup")[1]["model"] == "sonnet"              # a repair or an update keeps it
    assert RT.K.run("relay", "setup", "--model", "opus")[1]["model"] == "opus"
    assert json.loads((env["rd"] / "config.json").read_text())["model"] == "opus"

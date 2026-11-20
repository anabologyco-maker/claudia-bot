"""`slop agents install`: npm prefix under $SLOP_HOME, the vendors' installers, links in $SLOP_HOME/bin, idempotence,
and the background-job hand-off. Fake npm / fake installers only (the real installs were measured by hand in WSL)."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

_K = Path(__file__).parent / "fixtures" / "agents" / "kit.py"
_spec = importlib.util.spec_from_file_location("agents_kit", _K)
K = importlib.util.module_from_spec(_spec); sys.modules.setdefault("agents_kit", K); _spec.loader.exec_module(K)

pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX links and shell installers")

FAKE_NPM = r'''#!/bin/sh
# fake npm: records its argv, then "installs" the package's bin into <prefix>/bin
echo "$@" >> "$FAKE_STATE/npm-calls.txt"
[ -n "$FAKE_NPM_FAIL" ] && { echo "npm ERR! code ENOSPC" >&2; exit 1; }
prefix=""; pkg=""
while [ $# -gt 0 ]; do case "$1" in --prefix) prefix="$2"; shift;; @*) pkg="$1";; esac; shift; done
case "$pkg" in
  @openai/codex@*) name=codex;; @google/gemini-cli@*) name=gemini;; @anthropic-ai/claude-code@*) name=claude;; *) exit 3;;
esac
mkdir -p "$prefix/bin"
printf '#!/bin/sh\nexec "%s" "%s" %s "$@"\n' "$FAKE_PY" "$FAKE_CLI" "$name" > "$prefix/bin/$name"
chmod 755 "$prefix/bin/$name"
'''


@pytest.fixture
def env(tmp_path, monkeypatch):
    e = K.setup(tmp_path, monkeypatch, engines=())
    tools = tmp_path / "tools"; tools.mkdir()
    (tools / "npm").write_text(FAKE_NPM); (tools / "npm").chmod(0o755)
    monkeypatch.setenv("PATH", f"{tools}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_PY", sys.executable)
    monkeypatch.setenv("FAKE_CLI", str(K.FAKECLI))
    from slop.agents import engines as E
    monkeypatch.setattr(E, "node_info", lambda: {"path": "/usr/bin/node", "version": "v20.20.2", "major": 20})
    return e


def _fake_installer(monkeypatch, env, engine):
    """install._download returns a local script that does what the vendor installer does (no network)."""
    from slop.agents import install
    if engine == "claude":
        body = (f'mkdir -p "$HOME/.local/bin"; printf \'#!/bin/sh\\nexec "{sys.executable}" "{K.FAKECLI}" claude "$@"\\n\''
                ' > "$HOME/.local/bin/claude"; chmod 755 "$HOME/.local/bin/claude"; echo "Installation complete!"')
    else:
        body = ('echo "MUSE_INSTALL_DIR=$MUSE_INSTALL_DIR NO_MODIFY=$MUSE_NO_MODIFY_PATH NO_UPDATE=$MUSE_NO_AUTO_UPDATE" > '
                '"$FAKE_STATE/muse-installer-env.txt"; mkdir -p "$MUSE_INSTALL_DIR"; '
                f'printf \'#!/bin/sh\\nexec "{sys.executable}" "{K.FAKECLI}" muse "$@"\\n\' > "$MUSE_INSTALL_DIR/muse"; '
                'chmod 755 "$MUSE_INSTALL_DIR/muse"')
    seen = []

    def dl(url, dst):
        seen.append(url)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text("#!/bin/bash\nset -e\n" + body + "\n")
        return dst
    monkeypatch.setattr(install, "_download", dl)
    return seen


def test_npm_install_goes_to_the_slop_home_prefix_and_is_linked(env):
    rc, out = K.run("agents", "install", "codex", "--foreground")
    assert rc == 0, out
    row = out["installed"][0]
    assert row["version"] == "0.160.0" and row["method"] == "npm"
    link = env["sh"] / "bin" / "codex"
    assert link.is_symlink() and os.readlink(link) == str(env["sh"] / "npm" / "bin" / "codex")
    argv = (env["state"] / "npm-calls.txt").read_text().split()
    assert argv[:2] == ["install", "-g"] and argv[argv.index("--prefix") + 1] == str(env["sh"] / "npm")
    assert "@openai/codex@latest" in argv
    assert out["next"] == "slop agents login codex"
    assert (env["sh"] / "agents" / "install-codex.log").is_file()


def test_rerun_is_skipped_and_repairs_a_missing_link(env):
    K.run("agents", "install", "gemini", "--foreground")
    (env["sh"] / "bin" / "gemini").unlink()
    rc, out = K.run("agents", "install", "gemini", "--foreground")
    row = out["installed"][0]
    assert row["skipped"] is True and row["linked"] == str(env["sh"] / "bin" / "gemini")
    assert (env["state"] / "npm-calls.txt").read_text().count("install") == 1
    rc, out = K.run("agents", "install", "gemini", "--foreground", "--upgrade")
    assert out["installed"][0]["skipped"] is False


def test_claude_native_installer_and_link(env, monkeypatch):
    seen = _fake_installer(monkeypatch, env, "claude")
    rc, out = K.run("agents", "install", "claude", "--foreground")
    assert rc == 0, out
    assert seen == ["https://claude.ai/install.sh"] and out["installed"][0]["method"] == "native"
    assert os.readlink(env["sh"] / "bin" / "claude") == str(env["home"] / ".local" / "bin" / "claude")
    rc, out = K.run("agents", "install", "claude", "--foreground", "--method", "npm", "--upgrade")
    assert rc == 1 and "needs Node 22+" in out["installed"][0]["error"], "npm builds need Node 22 (2.1.198 on)"
    from slop.agents import engines as E
    monkeypatch.setattr(E, "node_info", lambda: {"path": "/usr/bin/node", "version": "v22.23.2", "major": 22})
    rc, out = K.run("agents", "install", "claude", "--foreground", "--method", "npm", "--upgrade")
    assert out["installed"][0]["method"] == "npm"
    assert "@anthropic-ai/claude-code@latest" in (env["state"] / "npm-calls.txt").read_text()


def test_muse_installer_runs_inside_slop_home_without_touching_profiles(env, monkeypatch):
    seen = _fake_installer(monkeypatch, env, "muse")
    rc, out = K.run("agents", "install", "muse", "--foreground")
    assert rc == 0, out
    assert seen == ["https://dev.meta.ai/install.sh"]
    got = (env["state"] / "muse-installer-env.txt").read_text()
    assert f"MUSE_INSTALL_DIR={env['sh'] / 'muse'}" in got and "NO_MODIFY=1" in got and "NO_UPDATE=1" in got
    assert os.readlink(env["sh"] / "bin" / "muse") == str(env["sh"] / "muse" / "muse")
    assert out["installed"][0]["version"] == "1.4.2"


def test_failure_names_the_log_and_the_next_step(env, monkeypatch):
    monkeypatch.setenv("FAKE_NPM_FAIL", "1")
    rc, out = K.run("agents", "install", "codex", "--foreground")
    assert rc == 1 and "ENOSPC" in out["error"] and "install-codex.log" in out["error"]
    assert "slop agents install codex" in out["error"]


def test_all_continues_past_a_failure(env, monkeypatch):
    _fake_installer(monkeypatch, env, "claude")
    from slop.agents import install
    real = install.install_one

    def one(eng, method=None, upgrade=False):
        if eng == "muse":
            raise install.SlopError("muse download refused")
        return real(eng, method, upgrade)
    monkeypatch.setattr(install, "install_one", one)
    rc, out = K.run("agents", "install", "all", "--foreground")
    assert rc == 1
    ok = {r["engine"]: r["ok"] for r in out["installed"]}
    assert ok == {"claude": True, "codex": True, "muse": False, "gemini": True}
    assert "muse download refused" in out["error"]


def test_without_foreground_it_starts_a_job(env, monkeypatch):
    from slop import job
    got = {}

    def fake_start(words, project=None, **kw):
        got["words"] = words
        return {"job": {"id": "agents-install-abcd", "wait": "slop job wait agents-install-abcd --max 25"},
                "existing": False}
    monkeypatch.setattr(job, "start", fake_start)
    rc, out = K.run("agents", "install", "all")
    assert rc == 0 and got["words"] == ["agents", "install", "all"]
    assert out["next"] == "slop job wait agents-install-abcd --max 25"
    rc, out = K.run("agents", "install", "claude", "--method", "npm", "--upgrade")
    assert got["words"] == ["agents", "install", "claude", "--method", "npm", "--upgrade"]
    rc, out = K.run("agents", "install", "codex", "--method", "native")
    assert rc == 1 and "installs with: npm" in out["error"]


def test_the_job_argv_is_a_valid_command(env):
    from slop import job
    ns = job.check_argv(["agents", "install", "all"])
    assert ns.func.__name__ == "cmd_install"
    ns = job.check_argv(["agents", "_login-session", "claude"])
    assert ns.func.__name__ == "cmd_login_session"


def test_dry_run_and_old_node(env, monkeypatch):
    rc, out = K.run("agents", "install", "all", "--dry-run")
    cmds = {p["engine"]: p["command"] for p in out["plans"]}
    assert "claude.ai/install.sh" in cmds["claude"] and f"--prefix {env['sh'] / 'npm'}" in cmds["gemini"]
    assert "MUSE_NO_MODIFY_PATH=1" in cmds["muse"]
    from slop.agents import engines as E
    monkeypatch.setattr(E, "node_info", lambda: {"path": "/usr/bin/node", "version": "v18.19.1", "major": 18})
    rc, out = K.run("agents", "install", "gemini", "--foreground")
    assert rc == 1 and "Node 20+" in out["installed"][0]["error"]


def test_box_reinstalls_a_copy_that_a_computer_update_would_wipe(env, monkeypatch):
    from slop.agents import engines as E
    sysbin = env["home"].parent / "usr-bin"; sysbin.mkdir()
    K.add_fake(sysbin, "codex")
    monkeypatch.setenv("PATH", f"{sysbin}{os.pathsep}{os.environ['PATH']}")
    assert E.find("codex")["via"] == "PATH"
    monkeypatch.setattr(E, "on_box", lambda: True)
    rc, out = K.run("agents", "install", "codex", "--foreground")
    assert out["installed"][0]["skipped"] is False and (env["sh"] / "npm" / "bin" / "codex").is_file()
    assert json.loads(json.dumps(out))["ok"] is True

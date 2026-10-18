"""0.3.6 the production's audio tools: earshot (its ears) and ElevenLabs reach both engines through `relay setup`; a
key is passed by name from the production's environment and never written into an engine's config."""
from __future__ import annotations

import json

from slop import relay

import test_relay as RT  # noqa: E402  (its fake engines and helpers)
K = RT.K


def _servers(home, eleven=False):
    ready = {"earshot": {"command": str(home / "venv" / "bin" / "python"), "args": ["-m", "earshot", "mcp"],
                         "env": {"EARSHOT_HOME": str(home / "cache" / "earshot")}, "env_vars": []}}
    if eleven:
        ready["elevenlabs"] = {"command": str(home / "bin" / "elevenlabs-mcp"), "args": [], "env_vars":
                               ["ELEVENLABS_API_KEY"], "env": {"ELEVENLABS_MCP_BASE_PATH": "/projects"}}
    return lambda wd: (ready, {} if eleven else {"elevenlabs": "off: no ELEVENLABS_API_KEY"})


def test_setup_gives_both_engines_their_ears(tmp_path, monkeypatch):
    env = RT.setup(tmp_path, monkeypatch, logged=("claude", "codex"))
    sk = env["sh"] / "vendor" / "earshot" / "skills" / "earshot"
    sk.mkdir(parents=True)
    (sk / "SKILL.md").write_text("---\nname: earshot\n---\n# earshot\n")
    monkeypatch.setattr(relay, "_tool_servers", _servers(env["sh"]))
    rc, out = K.run("relay", "setup")
    assert rc == 0, out
    assert "earshot (the production's ears): ready for Claude Code, Codex" in out["text"], out["text"]
    assert "ElevenLabs: off: no ELEVENLABS_API_KEY" in out["text"]
    got = json.loads((env["state"] / "claude_mcp.json").read_text())["earshot"]
    assert got["args"] == ["-m", "earshot", "mcp"] and got["env"]["EARSHOT_HOME"].endswith("cache/earshot")
    toml = (env["home"] / ".codex" / "config.toml").read_text()
    assert '[mcp_servers.earshot]\ncommand = "' in toml and 'args = ["-m", "earshot", "mcp"]' in toml
    assert "[mcp_servers.claudia]" in toml and "tool_timeout_sec = 900" in toml
    for d in (".claude", ".agents"):                                 # Claude Code and Codex read skills there
        assert (env["wd"] / d / "skills" / "earshot" / "SKILL.md").is_file()
    adds = [c for c in K.calls(env["state"], "claude") if c.get("argv", [])[:2] == ["mcp", "add"]]
    assert any("earshot" in c["argv"] for c in adds), adds
    assert K.run("relay", "setup")[0] == 0                          # again: nothing to change
    assert len([c for c in K.calls(env["state"], "claude") if c.get("argv", [])[:2] == ["mcp", "add"]]) == len(adds)
    assert (env["home"] / ".codex" / "config.toml").read_text() == toml


def test_the_elevenlabs_key_is_passed_by_name_never_written(tmp_path, monkeypatch):
    env = RT.setup(tmp_path, monkeypatch, logged=("claude", "codex"))
    secret = "fake-value-for-the-test"
    monkeypatch.setenv("ELEVENLABS_API_KEY", secret)
    monkeypatch.setattr(relay, "_tool_servers", _servers(env["sh"], eleven=True))
    rc, out = K.run("relay", "setup")
    assert rc == 0 and "ElevenLabs: ready for Claude Code, Codex" in out["text"], out["text"]
    toml = (env["home"] / ".codex" / "config.toml").read_text()
    assert 'env_vars = ["ELEVENLABS_API_KEY"]' in toml
    for f in (env["home"] / ".codex" / "config.toml", env["state"] / "claude_mcp.json", env["sh"] / "relay" /
              "config.json"):
        assert secret not in f.read_text(), f
    monkeypatch.delenv("ELEVENLABS_API_KEY")                       # the key is gone: so is the server, never stale
    monkeypatch.setattr(relay, "_tool_servers", _servers(env["sh"]))
    assert K.run("relay", "setup")[0] == 0
    assert "elevenlabs" not in json.loads((env["state"] / "claude_mcp.json").read_text())
    assert "[mcp_servers.elevenlabs]" not in (env["home"] / ".codex" / "config.toml").read_text()


def test_the_production_gets_the_key_and_the_other_engines_do_not(monkeypatch):
    from slop.agents import engines as E
    monkeypatch.setenv("ELEVENLABS_API_KEY", "fake-value-for-the-test")
    assert "ELEVENLABS_API_KEY" in E.TOOLKIT_SECRETS
    assert "ELEVENLABS_API_KEY" not in E.base_env("claude")         # an agent CLI never sees it; the relay adds it


def test_codex_sections_are_replaced_whole_and_others_kept(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    (tmp_path / "config.toml").write_text('model = "x"\n\n[mcp_servers.earshot]\ncommand = "old"\n\n[other]\na = 1\n')
    spec = {"command": "/new/python", "args": ["-m", "earshot", "mcp"], "env": {"EARSHOT_HOME": "/c"}, "env_vars": []}
    assert relay._mcp_codex_stdio("earshot", spec)["ok"]
    t = (tmp_path / "config.toml").read_text()
    assert 'command = "/new/python"' in t and 'command = "old"' not in t and "[other]\na = 1" in t
    assert 'env = { EARSHOT_HOME = "/c" }' in t and t.startswith('model = "x"')
    assert relay._mcp_codex_stdio("earshot", spec)["already"]
    assert relay._mcp_codex_stdio("earshot", None)["ok"]
    t = (tmp_path / "config.toml").read_text()
    assert "earshot" not in t and "[other]\na = 1" in t

"""`slop onboard` through the real router: status / next / mark / set / apply, --json contracts (`next` is only ever
a command that does the step; record steps stand apart), never "all set" while the tier is not ready, every command
and skill the checklist prints is real, no secret value in any output or in onboard.json, and one run on the real
probes (offline: no network, no spend)."""
from __future__ import annotations

import json
import shlex
import time
from pathlib import Path

import pytest

from slop import cli, util
from slop.config import toolkit_root
from slop.onboard import items as I
from slop.onboard import probes
from slop.onboard import state as st

FAKE_KEY = "sk-or-v1-THISISAFAKEKEYFORTESTSONLY0123"
ALL_MODULES = list(cli.MODULES)
REAL = {n: getattr(probes, n) for n in ("doctor", "agents", "gpu", "setup_running")}
N_ITEMS = 31


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    home, projects = tmp_path / "home", tmp_path / "projects"
    monkeypatch.setenv("SLOP_HOME", str(home))
    monkeypatch.setenv("SLOP_PROJECTS", str(projects))
    monkeypatch.setenv("HOME", str(tmp_path / "user"))
    for v in ("SLOP_PROJECT", "OPENROUTER_API_KEY", "ARENA_TOKEN", "HIGGSFIELD_API_KEY", "SLOP_PROFILE",
              "SLOP_MODULES", "GEMINI_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "SLOP_WAIT_MAX"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "MODULES", ["slop.core_cli", "slop.onboard.cli"])
    # fast, deterministic probes (the real ones run in test_real_probes_offline)
    monkeypatch.setattr(probes, "doctor", lambda: {"ok": True, "fails": [], "warns": [], "passed": 9,
                                                   "deps_full": "ok"})
    monkeypatch.setattr(probes, "agents", lambda: {"available": False, "engines": {}})
    monkeypatch.setattr(probes, "gpu", lambda: {"available": False})
    monkeypatch.setattr(probes, "setup_running", lambda: [])
    return {"home": home, "projects": projects, "tmp": tmp_path}


def run(capsys, *argv) -> tuple[int, dict]:
    try:
        rc = cli.main(["--json", *argv])
    except SystemExit as e:                     # argparse usage errors (printed as JSON by util.json_usage_errors)
        rc = e.code
    out = capsys.readouterr().out.strip().splitlines()
    return rc, json.loads(out[-1])


def install(home: Path, profile: str = "full") -> None:
    """What bin/setup.sh leaves behind: env.sh, the shim, the profile marker, and env.sh loaded by ~/.bashrc and
    ~/.profile (the PATH step)."""
    (home / "bin").mkdir(parents=True, exist_ok=True)
    user = Path.home()
    user.mkdir(parents=True, exist_ok=True)
    for rc in (".bashrc", ".profile"):
        (user / rc).write_text(f". {home / 'env.sh'}\n", encoding="utf-8")
    (home / "env.sh").write_text("export SLOP_PROFILE=full\n", encoding="utf-8")
    (home / "bin" / "slop").write_text("#!/bin/sh\n", encoding="utf-8")
    (home / "bin" / "slop").chmod(0o755)
    (home / "profile").write_text(profile + "\n", encoding="utf-8")


def with_key(monkeypatch, payload=None):
    monkeypatch.setenv("OPENROUTER_API_KEY", FAKE_KEY)
    payload = payload or {"data": {"limit": 25, "usage": 1.5, "limit_remaining": 23.5, "is_free_tier": False}}
    monkeypatch.setattr(util, "http_json", lambda url, headers=None, timeout=20, method="GET": (200, payload, None))


# ---------------------------------------------------------------- status / next
def test_bare_onboard_is_the_status_and_takes_its_flags(capsys):
    rc, out = run(capsys, "onboard")
    assert rc == 0 and out["ok"] and len(out["items"]) == N_ITEMS and out["next_item"] == "tier"
    assert out["next"] == "slop onboard next" and out["text"].startswith("Claudia setup - quick tier")
    rc2, out2 = run(capsys, "onboard", "status", "--offline")
    assert rc2 == 0 and [i["id"] for i in out2["items"]] == [i["id"] for i in out["items"]]
    rc, out = run(capsys, "onboard", "--tier", "studio", "--offline")          # the reviewer's failing call
    assert rc == 0 and out["tier"] == "studio" and out["tier_source"] == "--tier"
    rc, out = run(capsys, "onboard", "--tier", "director", "--group", "gpu")
    assert rc == 0 and out["tier"] == "director" and [i["id"] for i in out["items"]] == ["gpu"]
    rc, out = run(capsys, "onboard", "--tier", "studio", "status")            # a value given before the action
    assert rc == 0 and out["tier"] == "studio"
    rc, out = run(capsys, "onboard", "--tier", "studio", "next")
    assert rc == 0 and out["tier"] == "studio"


def test_status_group_filter_and_tier_flag(capsys, env):
    install(env["home"])
    rc, out = run(capsys, "onboard", "status", "--tier", "director", "--group", "agents-box", "--offline")
    assert rc == 0 and out["tier"] == "director" and {i["group"] for i in out["items"]} == {"agents-box"}
    assert "Coding agents on the box" in out["text"] and "Toolkit" not in out["text"].splitlines()[1:]
    rc, out = run(capsys, "onboard", "status", "--tier", "mega")
    assert rc == 2 and out["ok"] is False and "invalid choice" in out["error"]


def test_next_walks_the_studio_setup(capsys, env, monkeypatch):
    install(env["home"])
    with_key(monkeypatch)
    rc, out = run(capsys, "onboard", "next")
    assert out["item"]["id"] == "tier" and out["next"] is None and out["answers"]["studio"] == \
        "slop onboard set tier studio"
    assert any("Quick tier ready" in u for u in out["new_unlocks"]) and out["text"].startswith("NEW: ")
    assert any("Studio tier unlocked" in u for u in out["new_unlocks"]), "OpenRouter alone opens Studio"
    rc, out = run(capsys, "onboard", "set", "tier", "studio")
    assert rc == 0 and out["value"] == "studio"
    rc, out = run(capsys, "onboard", "next")
    assert rc == 0 and out["tier"] == "studio" and out["item"]["id"] == "higgsfield"
    # a record step: nothing to run blindly; the record command stands apart, with when to run it
    assert out["next"] is None and out["record_cmd"] == "slop onboard mark higgsfield --connected"
    assert out["record_when"].startswith("ONLY after you saw it working")
    assert "record, ONLY after you saw it working" in out["text"]
    assert "mark higgsfield --skip" in out["text"], "recommended: OpenRouter already makes the clips"
    assert out["new_unlocks"] == [], "each unlock is new only once"
    rc, out = run(capsys, "onboard", "mark", "hf", "--connected")
    assert rc == 0 and out["item"] == "higgsfield" and out["mark"] == "done" and "warn" not in out
    rc, out = run(capsys, "onboard", "next")
    assert out["item"]["id"] == "suno" and "free: slop onboard set suno-plan free" in out["text"]
    assert out["next"] is None and out["ask"] and out["record_cmd"] is None
    assert I.SPEC["higgsfield"]["unlocks"] in out["new_unlocks"] and out["ready"] and not out["all_set"]
    rc, out = run(capsys, "onboard", "next", "--except", "suno")
    assert out["item"]["id"] == "midjourney"
    rc, out = run(capsys, "onboard", "set", "suno-plan", "free")
    assert rc == 0 and "non-commercial" in out["text"]
    for cmd in (["set", "mj-plan", "none"], ["new", "my-song", "--tier", "studio"]):
        rc, out = run(capsys, *(["onboard"] + cmd if cmd[0] == "set" else cmd))
        assert rc == 0, out
    rc, out = run(capsys, "onboard", "next")
    assert out["item"]["id"] == "coding-agents" and out["answers"]["chatgpt"] == "slop onboard set coding-agents codex"
    rc, out = run(capsys, "onboard", "set", "coding-agents", "none")
    assert rc == 0 and out["value"] == "none"
    rc, out = run(capsys, "onboard", "next")
    assert out["item"]["id"] == "taste" and out["item"]["next_skill"] == "claudia-relay"   # the production runs it
    rc, out = run(capsys, "onboard", "mark", "taste", "--skip", "--note", "later")
    assert rc == 0 and "warn" not in out, "taste is recommended, not required"
    rc, out = run(capsys, "onboard", "next")
    assert out["all_set"] and out["item"] is None and out["hand_off"] == "claudia-relay" and out["stuck"] == []
    assert "Make something with Claudia: skill claudia-relay" in out["text"] and out["next"] == "slop --project my-song status"
    rc, out = run(capsys, "onboard", "status")
    assert out["next_item"] is None and out["next"] == "slop --project my-song status" and out["hand_off"] == \
        "claudia-relay"


def test_next_never_says_all_set_while_the_tier_is_not_ready(capsys, env):
    """The reviewer's repro: toolkit, openrouter, higgsfield and first-project skipped on a fresh machine."""
    run(capsys, "onboard", "set", "tier", "quick")
    run(capsys, "onboard", "set", "coding-agents", "none")
    warns = {}
    for iid in ("toolkit", "openrouter", "higgsfield", "first-project"):
        rc, out = run(capsys, "onboard", "mark", iid, "--skip")
        assert rc == 0, out
        warns[iid] = out.get("warn")
    assert "required for the quick tier" in warns["toolkit"] and "slop onboard mark toolkit --todo" in warns["toolkit"]
    assert warns["higgsfield"] is None, "recommended for Quick: skipping it does not block the tier"
    rc, out = run(capsys, "onboard", "next")
    assert rc == 0 and out["item"] is None and out["all_set"] is False and out["ready"] is False
    assert out["hand_off"] is None and out["next"] is None
    assert {s["id"] for s in out["stuck"]} == {"toolkit"}, "Quick needs no account"
    assert "NOT ready" in out["text"] and "Everything" not in out["text"] and "Make a video" not in out["text"]
    rc, out = run(capsys, "onboard", "status")
    assert out["next"] is None and out["hand_off"] is None and "NOT ready" in out["text"]
    rc, out = run(capsys, "onboard", "mark", "toolkit", "--todo")
    rc, out = run(capsys, "onboard", "next")
    assert out["item"]["id"] == "toolkit" and out["next"].endswith("bin/setup.sh --minimal")
    assert "next --except toolkit" in out["text"] and "mark toolkit --skip" not in out["text"]


# ---------------------------------------------------------------- mark / set / apply rules
def test_mark_rules(capsys):
    rc, out = run(capsys, "onboard", "mark", "toolkit", "--done")
    assert rc == 1 and "checked automatically" in out["error"] and "--skip" in out["error"]
    rc, out = run(capsys, "onboard", "mark", "suno", "--done")
    assert rc == 1 and "slop onboard set suno-plan" in out["error"]
    rc, out = run(capsys, "onboard", "mark", "mj-profile", "--done")
    assert rc == 1 and "slop onboard set mj-profile" in out["error"]
    rc, out = run(capsys, "onboard", "mark", "tier", "--done")
    assert rc == 1 and "slop onboard set tier" in out["error"]
    rc, out = run(capsys, "onboard", "mark", "coding-agents", "--done")
    assert rc == 1 and "slop onboard set coding-agents" in out["error"]
    rc, out = run(capsys, "onboard", "mark", "nope", "--done")
    assert rc == 1 and "unknown onboarding item" in out["error"] and "higgsfield" in out["error"]
    rc, out = run(capsys, "onboard", "mark", "higgsfield")
    assert rc == 2 and out["ok"] is False and "usage" in out             # one of the flags is required
    rc, out = run(capsys, "onboard", "mark", "home-codex", "--done", "--note", f"plan pro {FAKE_KEY}")
    assert rc == 1 and "secret" in out["error"] and not st.path().exists()
    for note in ("signed in as bob.smith@example.com", "password hunter2"):
        rc, out = run(capsys, "onboard", "mark", "home-codex", "--done", "--note", note)
        assert rc == 1 and "NOT saved" in out["error"] and not st.path().exists()
        assert "example.com" not in out["error"] and "hunter2" not in out["error"]
    rc, out = run(capsys, "onboard", "mark", "gpu", "--skip", "--note", "no NVIDIA card")
    assert rc == 0 and st.load()["marks"]["gpu"]["note"] == "no NVIDIA card"
    rc, out = run(capsys, "onboard", "mark", "gpu", "--todo")
    assert rc == 0 and "gpu" not in st.load()["marks"]


def test_set_show_and_clear(capsys):
    rc, out = run(capsys, "onboard", "set", "mj-profile")
    assert rc == 0 and out["value"] is None and "not set" in out["text"]
    rc, out = run(capsys, "onboard", "set", "mj-profile", "abc123x")
    assert rc == 0 and out["value"] == "ab… (7 characters)" and "abc123x" not in json.dumps(out)
    rc, out = run(capsys, "onboard", "set", "mj-profile")
    assert out["value"] == "ab… (7 characters)"
    rc, out = run(capsys, "onboard", "set", "mj-profile", "--clear")
    assert rc == 0 and "mj_profile" not in st.load()["settings"]
    rc, out = run(capsys, "onboard", "set", "suno-plan", "gold")
    assert rc == 1 and "free, pro, premier, none" in out["error"]
    rc, out = run(capsys, "onboard", "set", "colour", "red")
    assert rc == 2 and out["ok"] is False
    rc, out = run(capsys, "onboard", "set", "coding-agents", "claude,chatgpt")
    assert rc == 0 and out["value"] == "claude,codex" and "Claude Code, Codex" in out["text"]
    rc, out = run(capsys, "onboard", "set", "coding-agents")
    assert out["value"] == "claude,codex"
    rc, out = run(capsys, "onboard", "set", "coding-agents", "copilot")
    assert rc == 1 and "nothing was saved" in out["error"]


def test_apply_copies_the_midjourney_plan_and_profile_code_into_a_project(capsys, env):
    rc, out = run(capsys, "onboard", "apply")
    assert rc == 1 and "no project" in out["error"]
    rc, out = run(capsys, "new", "my-song")
    assert rc == 0
    rc, out = run(capsys, "-p", "my-song", "onboard", "apply")
    assert rc == 1 and "slop onboard set mj-profile" in out["error"] and "mj-plan" in out["error"]
    run(capsys, "onboard", "set", "mj-profile", "abc123x")
    rc, out = run(capsys, "-p", "my-song", "onboard", "apply")
    assert rc == 0 and out["changed"] and "abc123x" not in json.dumps(out)
    pj_path = env["projects"] / "my-song" / "project.json"
    pj = json.loads(pj_path.read_text(encoding="utf-8"))
    assert pj["mj"]["profile"] == "abc123x" and pj["mj"]["params"], "the rest of mj is kept"
    assert "plan" not in pj["mj"], "no plan recorded: the plate book keeps its default"
    rc, out = run(capsys, "onboard", "apply", "--project", "my-song")
    assert rc == 0 and out["changed"] is False
    run(capsys, "onboard", "set", "mj-plan", "basic")
    rc, out = run(capsys, "onboard", "status", "--offline")
    assert next(i for i in out["items"] if i["id"] == "midjourney")["next_cmd"] == "slop --project my-song onboard apply"
    rc, out = run(capsys, "-p", "my-song", "onboard", "apply")
    assert rc == 0 and out["changed"] and any("mj.plan = basic" in c for c in out["set"])
    pj = json.loads(pj_path.read_text(encoding="utf-8"))
    assert pj["mj"]["plan"] == "basic" and pj["mj"]["profile"] == "abc123x"
    pj["mj"]["profile"] = "zzz999"
    pj_path.write_text(json.dumps(pj), encoding="utf-8")
    rc, out = run(capsys, "-p", "my-song", "onboard", "apply")
    assert rc == 1 and "--force" in out["error"]
    rc, out = run(capsys, "-p", "my-song", "onboard", "apply", "--force")
    assert rc == 0 and out["changed"]
    rc, out = run(capsys, "onboard", "status", "--offline")
    by = {i["id"]: i for i in out["items"]}
    assert by["mj-profile"]["next_cmd"] is None and by["midjourney"]["next_cmd"] is None


# ---------------------------------------------------------------- no secrets anywhere
def test_no_secret_value_in_any_output_or_in_the_state_file(capsys, env, monkeypatch):
    install(env["home"])
    with_key(monkeypatch)
    monkeypatch.setenv("ARENA_TOKEN", "arena-THISISAFAKETOKENFORTESTS")
    seen = []
    for argv in (["onboard", "status"], ["onboard", "next"], ["onboard", "mark", "higgsfield", "--connected"],
                 ["onboard", "status", "--tier", "director"]):
        rc, out = run(capsys, *argv)
        assert rc == 0
        seen.append(json.dumps(out))
    rc = cli.main(["onboard", "status"])                       # the human rendering too
    seen.append(capsys.readouterr().out)
    blob = "\n".join(seen) + st.path().read_text(encoding="utf-8")
    assert FAKE_KEY not in blob and "THISISAFAKETOKEN" not in blob
    assert "OPENROUTER_API_KEY" in blob and "ARENA_TOKEN" in blob, "secrets are named, never shown"
    status = json.loads(seen[0])
    ork = next(i for i in status["items"] if i["id"] == "openrouter")
    assert ork["state"] == "done" and ork["data"]["limit"] == 25


# ---------------------------------------------------------------- every printed command / skill is real
def _all_commands(reports: list[dict]) -> tuple[set[str], set[str]]:
    cmds, skills = set(), set()
    for r in reports:
        for it in r["items"]:
            for c in (it.get("next_cmd"), it.get("record_cmd"), *(it.get("answers") or {}).values()):
                if c:
                    cmds.add(c)
            if it.get("next_skill"):
                skills.add(it["next_skill"])
        if r["hand_off"]:
            skills.add(r["hand_off"])
    return cmds, skills


def _reports(env) -> list[dict]:
    base = {"tk": probes.toolkit(), "doc": {"ok": True, "fails": [], "warns": [], "deps_full": "ok"},
            "key": {"present": False, "checked": False, "valid": False}, "env": {}, "taste": {"available": True,
                                                                                         "taps": 3},
            "projects": [], "running": [], "agents": {"available": False}, "gpu": {"available": False}}
    proj = [{"name": "my-song", "tier": "studio", "mj_profile_set": False, "mj_plan": "standard", "broken": False,
             "mtime": 1.0}]
    ag_states = [{"available": True, "engines": {}},
                 {"available": True, "engines": {}, "error": "boom"},
                 {"available": True, "engines": {e: {"installed": False} for e in I.ENGINE_NAMES}},
                 {"available": True, "engines": {e: {"installed": True, "logged_in": False} for e in I.ENGINE_NAMES}},
                 {"available": True, "engines": {e: {"installed": True, "logged_in": True} for e in I.ENGINE_NAMES}},
                 {"available": True, "engines": {e: {"installed": False, "error": "x"} for e in I.ENGINE_NAMES}},
                 {"available": False, "unregistered": True}]
    gpu_states = [{"available": True, "mode": "none", "ok": True},
                  {"available": True, "mode": "paired", "healthy": False},
                  {"available": True, "mode": "paired", "healthy": False, "why": "no computer is paired",
                   "hint_cmd": "slop gpu pair"},
                  {"available": True, "mode": "paired", "healthy": False, "why": "the job server is not running",
                   "hint_cmd": "slop gpu serve"},
                  {"available": True, "mode": "paired", "healthy": False, "why": "the audio profile is not installed",
                   "hint_cmd": "slop gpu install audio"},
                  {"available": True, "mode": "none", "ok": False, "error": "boom"},
                  {"available": False, "unregistered": True}]
    out = []
    for plans in (None, "none", "codex,claude", "gemini"):
        st.set_setting("coding-agents", plans)
        for tier in I.TIERS:
            out.append(I.report(tier=tier, data=base, record=False))
            out.append(I.report(tier=tier, data={**base, "projects": proj, "doc": {"ok": False, "error": "x"},
                                                 "tk": {**base["tk"], "installed": True, "on_path": False,
                                                        "profile": "minimal", "shell_rc": []},
                                                 "key": {"present": True, "checked": True, "valid": False,
                                                         "status": 0}}, record=False))
            for a, g in zip(ag_states, gpu_states):
                out.append(I.report(tier=tier, data={**base, "agents": a, "gpu": g, "projects": proj}, record=False))
    st.set_setting("mj-plan", "pro")
    st.set_setting("mj-profile", "abc123x")
    out.append(I.report(tier="studio", data={**base, "projects": proj}, record=False))
    return out


def _families() -> dict[str, str | None]:
    """agents / gpu -> the module that would register them: the real router's, else the package's own cli (a track
    that has not appended its MODULES line yet is still checked against its own parser)."""
    return {fam: f"slop.{fam}.cli" if probes.package_present(fam) else None for fam in ("agents", "gpu")}


def test_every_command_the_checklist_prints_parses_with_the_real_router(env, monkeypatch):
    cmds, skills = _all_commands(_reports(env))
    assert len(cmds) >= 30, cmds
    families = _families()
    mods = list(dict.fromkeys(ALL_MODULES + ["slop.onboard.cli"] + [m for m in families.values() if m]))
    monkeypatch.setattr(cli, "MODULES", mods)
    parser = cli.build_parser()
    checked = 0
    for c in sorted(cmds):
        words = shlex.split(c)
        if words[0] == "bash":                                   # bin/setup.sh lines
            assert Path(words[1]).name == "setup.sh" and (toolkit_root() / "bin" / "setup.sh").is_file(), c
            assert words[2] in ("--minimal", "--full"), c
            continue
        if words[0] == "grep":                                   # the PATH line: both ~/.bashrc and ~/.profile
            assert c.count("|| echo") == 2 and ">> ~/.bashrc;" in c and c.endswith(">> ~/.profile"), c
            continue
        assert words[0] == "slop", c
        assert not any(probes.PLACEHOLDER_RE.match(w) for w in words), f"placeholder in {c}"
        sub = next(w for w in words[1:] if not w.startswith("-") and w not in ("my-song",))
        if sub in families and not families[sub]:
            continue                                             # only printed when the module exists
        try:
            parser.parse_args(util.hoist_global_flags(words[1:]))
        except SystemExit as e:
            pytest.fail(f"`{c}` does not parse with the real router (exit {e.code})")
        checked += 1
    assert checked >= 25
    for s in skills:
        assert (toolkit_root() / "skills" / s / "SKILL.md").is_file(), f"skill {s} does not exist"


def test_planned_skills_fall_back_until_they_ship(monkeypatch, tmp_path):
    monkeypatch.setattr(I, "toolkit_root", lambda: tmp_path)
    assert I.skill("setup-accounts") == "claudia-setup" and I.skill("taste") == "taste"
    assert I.skill("setup-agents") is None and I.skill("setup-gpu") is None, "no skill covers them yet"
    (tmp_path / "skills" / "setup-accounts").mkdir(parents=True)
    (tmp_path / "skills" / "setup-accounts" / "SKILL.md").write_text("x", encoding="utf-8")
    assert I.skill("setup-accounts") == "setup-accounts"


# ---------------------------------------------------------------- the other modules' CLIs, for real
def test_run_cli_plumbing_with_a_real_module(env):
    r = probes.run_cli("slop.core_cli", ["projects"], timeout=60)
    assert r["ok"] and isinstance(r["data"], dict) and "projects" in r["data"]
    r = probes.run_cli("slop.core_cli", ["agents", "status"], timeout=60)
    assert r["unregistered"] and not r["ok"] and "has no `slop agents status`" in r["error"]
    assert probes.module_for("core_cli") == "slop.core_cli" and probes.module_for("no_such_family") is None


def test_agents_and_gpu_probes_never_raise(monkeypatch):
    monkeypatch.setattr(probes, "module_for", lambda fam: None)
    assert REAL["agents"]()["available"] is False and REAL["gpu"]()["available"] is False
    monkeypatch.setattr(probes, "module_for", lambda fam: f"slop.{fam}.cli")
    monkeypatch.setattr(probes, "run_cli", lambda m, w, t=0: {"ok": False, "data": None, "rc": 124,
                                                              "error": "`slop agents status` did not answer"})
    a = REAL["agents"]()
    assert a["available"] and a["engines"] == {} and "did not answer" in a["error"]
    g = REAL["gpu"]()
    assert g["available"] and g["mode"] == "none" and "did not answer" in g["error"]
    monkeypatch.setattr(probes, "run_cli", lambda m, w, t=0: {
        "ok": True, "rc": 0, "error": None,
        "data": {"ok": True, "engines": {"claude": {"installed": True, "logged_in": True}}} if w[0] == "agents"
        else {"ok": True, "mode": "paired", "healthy": True}})
    assert REAL["agents"]()["engines"]["claude"]["logged_in"] is True
    assert REAL["gpu"]()["mode"] == "paired"


def test_a_crashing_probe_does_not_hide_the_checklist(capsys, monkeypatch):
    def boom():
        raise RuntimeError(f"exploded with {FAKE_KEY}")
    monkeypatch.setattr(probes, "doctor", boom)
    monkeypatch.setattr(probes, "agents", boom)
    rc, out = run(capsys, "onboard", "status", "--tier", "director")
    assert rc == 0 and len(out["items"]) == N_ITEMS
    d = next(i for i in out["items"] if i["id"] == "doctor")
    assert d["state"] == "error" and "exploded" in d["why"] and FAKE_KEY not in json.dumps(out)
    assert next(i for i in out["items"] if i["id"] == "agent-claude")["state"] == "error"


def test_real_probes_offline(capsys, monkeypatch, env):
    """No fakes: doctor --quick, toolkit, taste, projects, and the real agents / GPU modules when the router loads
    them (else 'not available'). --offline: no network."""
    for n, f in REAL.items():
        monkeypatch.setattr(probes, n, f)
    monkeypatch.setattr(cli, "MODULES", ALL_MODULES)
    t0 = time.monotonic()
    rc, out = run(capsys, "onboard", "status", "--offline", "--tier", "director")
    took = time.monotonic() - t0
    assert rc == 0 and out["ok"] and len(out["items"]) == N_ITEMS, out.get("error")
    assert took < 60, f"onboard status took {took:.1f} s"
    by = {i["id"]: i for i in out["items"]}
    assert by["toolkit"]["state"] == "todo"                   # SLOP_HOME is a fresh temporary folder
    assert by["first-project"]["state"] == "todo" and by["taste"]["state"] == "blocked"
    for fam, ids in (("agents", ["agent-claude"]), ("gpu", ["gpu"])):
        if probes.module_for(fam) is None:
            assert all(by[i]["available"] is False for i in ids)
        else:
            assert all(by[i].get("available") is not False for i in ids), by[ids[0]]
    print(f"onboard status (real probes, offline): {took:.2f} s")

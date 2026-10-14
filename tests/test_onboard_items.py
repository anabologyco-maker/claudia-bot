"""Onboarding checklist logic: item states per tier, the next item, tier readiness (never "all set" while the tier is
not ready), the tier / coding-agent / GPU questions, Director engines, unlocks, and the shape-tolerant readers of
`slop agents status` / `slop gpu status`. Probe results are fed in directly (no network, no child processes); the
OpenRouter checks go through the real probe with util.http_json mocked."""
from __future__ import annotations

import json

import pytest

from slop import util
from slop.onboard import items as I
from slop.onboard import probes
from slop.onboard import state as st

FAKE_KEY = "sk-or-v1-THISISAFAKEKEYFORTESTSONLY0123"
CONTRACT = ("id", "group", "title", "state", "need", "why", "do", "next_cmd", "next_skill", "cost_note", "unlocks")
N_ITEMS = 31


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SLOP_PROJECTS", str(tmp_path / "projects"))
    for v in ("OPENROUTER_API_KEY", "ARENA_TOKEN", "HIGGSFIELD_API_KEY", "SLOP_PROFILE", "SLOP_MODULES",
              "SLOP_WAIT_MAX"):
        monkeypatch.delenv(v, raising=False)
    return tmp_path


def data(**over) -> dict:
    """Probe results of a machine where the toolkit (full profile) is installed and the OpenRouter key is valid."""
    d = {"tk": {"version": "0.1.0", "profile": "full", "installed": True, "env_sh": "/w/.claudia/env.sh",
                "shim": "/w/.claudia/bin/slop", "slop_home": "/w/.claudia", "toolkit": "/w/claudia",
                "on_path": True, "shell_rc": [], "on_box": True},
         "doc": {"ok": True, "fails": [], "warns": ["cloudflared"], "passed": 12, "deps_full": "ok"},
         "key": {"present": True, "checked": True, "valid": True, "limit": 25.0, "limit_remaining": 20.0,
                 "usage": 5.0},
         "env": {"ARENA_TOKEN": False, "HIGGSFIELD_API_KEY": False},
         "agents": {"available": False, "engines": {}}, "gpu": {"available": False},
         "taste": {"available": True, "taps": 0, "images": 0, "meter": None}, "projects": [], "running": []}
    for k, v in over.items():
        d[k] = {**d[k], **v} if isinstance(v, dict) and isinstance(d.get(k), dict) else v
    return d


FRESH = dict(tk={"installed": False, "profile": "minimal", "on_path": False},
             key={"present": False, "checked": False, "valid": False})
PROJECT = {"name": "my-song", "tier": "studio", "mj_profile_set": False, "mj_plan": "standard", "broken": False,
           "mtime": 1.0}
NO_KEY = {"present": False, "checked": False, "valid": False}


def rep(tier="quick", choose=True, **over):
    """The report for TIER; choose=True records that tier first (the user answered the tier question)."""
    if tier and choose:
        st.set_setting("tier", tier)
    return I.report(tier=tier, data=data(**over))


def item(r, iid):
    return next(i for i in r["items"] if i["id"] == iid)


def engines(**rows):
    return {"available": True, "ok": True, "engines": rows}


# ---------------------------------------------------------------- the contract
def test_every_item_carries_the_contract_fields_in_every_state():
    gpu_none = {"available": True, "mode": "none", "ok": True}
    variants = [rep(t, choose=False, **FRESH) for t in I.TIERS] + [rep(t) for t in I.TIERS] + [
        rep("director", agents=engines(claude={"installed": True, "logged_in": False}), gpu=gpu_none,
            projects=[PROJECT]),
        rep("quick", agents=engines(), gpu={"available": False, "unregistered": True})]
    for r in variants:
        assert len(r["items"]) == len(I.CATALOG) == N_ITEMS
        assert sum(r["counts"].values()) == N_ITEMS
        for it in r["items"]:
            for k in CONTRACT:
                assert k in it, (it["id"], k)
            assert it["state"] in I.STATES and it["need"] in I.NEED.values() and it["why"]
            if it["state"] in ("todo", "error"):
                assert it["next_cmd"] or it["next_skill"] or it.get("record_cmd") or it.get("ask"), it
            if it.get("ask"):                           # one exact command per answer, or (free text) what to run
                assert it.get("answers") or it.get("do"), it
            if it["state"] == "blocked":
                assert it.get("blocked_by") or it.get("available") is False, it
    assert set(I.PRIORITY) == set(I.ITEM_IDS) and len(I.PRIORITY) == len(I.ITEM_IDS)
    assert I.PRIORITY[0] == "tier"


@pytest.mark.parametrize("tier", I.TIERS)
def test_a_fresh_machine_asks_the_tier_then_installs(tier):
    r = rep(tier, choose=False, **FRESH)
    assert r["next_item"] == "tier"
    t = item(r, "tier")
    assert t["state"] == "todo" and t["need"] == "required" and "Director" in t["ask"]
    assert t["answers"] == {x: f"slop onboard set tier {x}" for x in I.TIERS} and t["next_cmd"] is None
    r = rep(tier, **FRESH)
    assert item(r, "tier")["state"] == "done" and r["next_item"] == "toolkit"
    tk = item(r, "toolkit")
    assert tk["state"] == "todo" and tk["next_cmd"].startswith("bash ") and tk["next_cmd"].endswith(
        "bin/setup.sh --minimal") and tk.get("long")
    assert item(r, "path")["state"] == "blocked" and item(r, "path")["blocked_by"] == ["toolkit"]
    assert not any(v["ready"] for v in r["tiers"].values()) and r["hand_off"] is None


# ---------------------------------------------------------------- tier walk-throughs
def test_quick_tier_walkthrough_to_all_set():
    r = rep("quick")
    assert item(r, "openrouter")["state"] == "done" and "used $5.00 of its $25.00 limit" in item(r, "openrouter")["why"]
    assert item(r, "api-images")["state"] == "done" and item(r, "lyria")["state"] == "done"
    assert r["tiers"]["quick"]["ready"] and r["ready"]
    assert r["tiers"]["studio"]["ready"], "OpenRouter alone opens Studio"
    assert ("Quick tier ready: stills from OpenRouter or Grok's image tool, 2.5D motion with devices plus OpenRouter "
            "clips, the song from your own upload or Lyria, render and master here") in r["unlocked"]
    assert r["next_item"] == "higgsfield"                       # recommended for Quick
    hf = item(r, "higgsfield")
    assert hf["record_cmd"] == "slop onboard mark higgsfield --connected" and hf["need"] == "recommended"
    assert hf["next_cmd"] is None, "a record step is never a command to run blindly"
    st.set_mark("higgsfield", "done")
    r = rep("quick")
    assert r["next_item"] == "coding-agents", "the coding-agent plans are asked in Quick too"
    ca = item(r, "coding-agents")
    assert ca["need"] == "recommended" and "ChatGPT" in ca["ask"] and ca["answers"]["chatgpt"] == \
        "slop onboard set coding-agents codex"
    st.set_setting("coding-agents", "none")
    r = rep("quick")
    assert item(r, "coding-agents")["state"] == "optional" and item(r, "coding-agents")["skipped"]
    assert r["next_item"] == "first-project" and item(r, "first-project")["next_skill"] == "claudia-relay"
    assert item(r, "suno")["state"] == "optional" and item(r, "midjourney")["state"] == "optional"
    r = rep("quick", projects=[PROJECT])
    assert r["next_item"] is None and r["hand_off"] == "claudia-relay" and r["stuck"] == []
    assert "everything the quick tier needs" in I.render_status(r)
    assert "Make something with Claudia: skill claudia-relay" in I.render_next(None, r)


def test_studio_asks_for_the_plans_with_one_exact_command_per_answer():
    st.set_mark("higgsfield", "done")
    st.set_setting("coding-agents", "none")
    r = rep("studio")
    assert r["tiers"]["studio"]["ready"], r["tiers"]
    assert ("Studio tier unlocked: sung clips with measured lip sync via OpenRouter and Higgsfield, full analysis "
            "install") in r["unlocked"]
    assert r["next_item"] == "suno"
    su = item(r, "suno")
    assert su["ask"] and su["answers"] == {p: f"slop onboard set suno-plan {p}" for p in st.SUNO_PLANS}
    st.set_setting("suno-plan", "free")
    r = rep("studio")
    assert item(r, "suno")["state"] == "done" and "non-commercial" in item(r, "suno")["warn"]
    assert item(r, "suno-signin")["state"] == "optional" and item(r, "suno-signin")["next_skill"] == "setup-accounts"
    assert r["next_item"] == "midjourney"
    st.set_setting("mj-plan", "standard")
    r = rep("studio")
    mp = item(r, "mj-profile")                     # no code to ask for: personalization is the P button
    assert mp["state"] == "optional" and "P button" in mp["why"] and not mp.get("ask")
    assert r["next_item"] == "first-project"
    r = rep("studio", projects=[PROJECT])
    assert r["next_item"] == "taste"
    assert item(r, "taste")["next_skill"] == "claudia-relay" and not item(r, "taste").get("next_cmd")


def test_plan_none_means_skipped_and_its_dependants_follow():
    st.set_setting("suno-plan", "none")
    st.set_setting("mj-plan", "none")
    r = rep("studio")
    for iid in ("suno", "suno-signin", "midjourney", "mj-profile", "mj-signin"):
        assert item(r, iid)["state"] == "optional", iid
    assert item(r, "suno")["skipped"] and "upload or Lyria" in item(r, "suno")["why"]


def test_lyria_is_the_quick_fallback_and_blocked_without_a_key():
    r = rep("quick", key=NO_KEY)
    ly = item(r, "lyria")
    assert ly["state"] == "blocked" and ly["blocked_by"] == ["openrouter"] and ly["need"] == "recommended"
    st.set_setting("suno-plan", "pro")
    assert item(rep("quick"), "lyria")["need"] == "optional"


# ---------------------------------------------------------------- never "all set" while the tier is not ready
def test_a_tier_that_cannot_become_ready_is_stuck_not_all_set():
    """The reviewer's case: required items skipped -> nothing to pick, but the tier is NOT ready. (Studio: both clip
    routes skipped; Quick needs neither since 2026-10-02.)"""
    st.set_setting("coding-agents", "none")
    for k in ("suno-plan", "mj-plan"):
        st.set_setting(k, "none")
    for iid in ("openrouter", "higgsfield", "taste"):
        st.set_mark(iid, "skip")
    r = rep("studio", key=NO_KEY, projects=[PROJECT])
    assert r["next_item"] is None and not r["ready"] and r["hand_off"] is None
    assert r["tiers"]["quick"]["ready"], "Quick needs no account"
    assert [s["id"] for s in r["stuck"]] == ["video"]
    reason = r["stuck"][0]["reason"]
    assert "waits for one of: openrouter (skipped" in reason and "slop onboard mark openrouter --todo" in reason
    assert "higgsfield (skipped" in reason
    text = I.render_next(None, r)
    assert "NOT ready" in text and "Everything" not in text and "Make a video" not in text
    assert "NOT ready" in I.render_status(r) and "everything the studio tier needs" not in I.render_status(r)


def test_an_install_that_is_running_is_named_as_the_reason():
    r = rep("quick", running=[{"pid": 7, "full": False}], **FRESH)
    assert item(r, "toolkit")["running"] and r["next_item"] == "openrouter"
    todo = [i["id"] for i in r["items"] if i["state"] in ("todo", "error")]
    assert I.pick_next(r["items"], exclude=todo) is None
    s = {x["id"]: x["reason"] for x in I.stuck(r["items"], r["tiers"], "quick", exclude=todo)}
    assert "installing now" in s["toolkit"] and set(s) == {"toolkit"}
    s = {x["id"]: x["reason"] for x in I.stuck(r["items"], r["tiers"], "studio", exclude=todo)}
    assert s["video"].startswith("waits for one of: openrouter (passed over with --except")
    text = I.render_next(None, r, exclude=todo)
    assert "NOT ready" in text and "installing now" in text and "Still installing" not in text


def test_the_footer_never_suggests_skipping_a_required_item():
    st.set_setting("coding-agents", "none")
    st.set_mark("openrouter", "skip")
    r = rep("studio", key=NO_KEY)
    hf = item(r, "higgsfield")
    assert hf["need"] == "required", "the last clip route left"
    text = I.render_next(hf, r)
    assert "slop onboard next --except higgsfield" in text and "mark higgsfield --skip" not in text
    assert "record, ONLY after you saw it working" in text
    st.set_mark("higgsfield", "done")
    r = rep("studio", key=NO_KEY)
    su = item(r, "suno")
    assert su["need"] == "recommended" and "slop onboard mark suno --skip" in I.render_next(su, r)
    assert "already ready" in I.render_next(su, r)


def test_optional_extras_offer_agents_and_the_gpu_first():
    st.set_mark("higgsfield", "done")
    st.set_setting("coding-agents", "none")
    st.set_mark("gpu", "skip")
    r = rep("quick", agents=engines(), gpu={"available": True, "mode": "none", "ok": True}, projects=[PROJECT])
    assert r["next_item"] is None and r["ready"]
    ex = I.extras_text(r)
    assert ex.startswith("Coding agents on the box: agent-claude, agent-codex, agent-muse, agent-gemini")
    assert ex.index("Coding agents on your own computer") < ex.index("Music") and "gpu" not in ex.split("; ")[0]
    assert "Optional extras to offer" in I.render_next(None, r)


# ---------------------------------------------------------------- coding agents and the Director tier
def test_director_asks_the_plan_when_no_engine_is_known_then_wires_it():
    st.set_mark("higgsfield", "done")
    for k in ("suno-plan", "mj-plan"):
        st.set_setting(k, "none")
    r = rep("director", agents=engines())
    assert r["tiers"]["director"]["missing"] == ["coding-agents"] and r["next_item"] == "coding-agents"
    ca = item(r, "coding-agents")
    assert ca["need"] == "required" and set(ca["answers"]) == {"claude", "chatgpt", "muse", "gemini", "none"}
    st.set_setting("coding-agents", "chatgpt")                     # a ChatGPT plan only: Codex, not Claude
    r = rep("director", agents=engines(codex={"installed": False}))
    assert r["tiers"]["director"]["missing"] == ["agent-codex"] and r["next_item"] == "agent-codex"
    cx = item(r, "agent-codex")
    assert cx["need"] == "required" and cx["next_cmd"] == "slop agents install codex"
    assert "slop agents use codex --for director" in cx["do"]
    assert item(r, "agent-claude")["need"] == "optional"
    r = rep("director", agents=engines(codex={"installed": True, "logged_in": True, "version": "0.155.1",
                                              "plan": "pro"}))
    cx = item(r, "agent-codex")
    assert cx["state"] == "todo" and cx["next_cmd"] == "slop agents use codex --for director"
    assert "new Director jobs still use Claude Code" in cx["why"] and not r["ready"]
    st.update(lambda d: d.update(agents={"use": {"director": "codex"}}))     # what `slop agents use` writes
    r = rep("director", agents=engines(codex={"installed": True, "logged_in": True, "version": "0.155.1"}))
    assert item(r, "agent-codex")["state"] == "done" and r["tiers"]["director"]["ready"]
    assert "Director tier unlocked: Codex logged in on the box" in r["unlocked"]


def test_director_with_no_plan_offers_the_studio_tier():
    st.set_setting("coding-agents", "none")
    r = rep("director", agents=engines())
    ca = item(r, "coding-agents")
    assert ca["state"] == "todo" and ca["answers"]["studio"] == "slop onboard set tier studio"
    assert "gemini" not in ca["answers"] and "none" not in ca["answers"]
    assert r["tiers"]["director"]["missing"][-1] == "coding-agents"
    assert item(rep("studio", agents=engines()), "coding-agents")["state"] == "optional"


def test_director_needs_one_logged_in_agent_on_the_box():
    st.set_mark("higgsfield", "done")
    for k, v in (("suno-plan", "pro"), ("mj-plan", "none"), ("coding-agents", "claude")):
        st.set_setting(k, v)
    ag = engines(claude={"installed": True, "logged_in": False, "version": "2.1.280"})
    r = rep("director", agents=ag)
    assert r["next_item"] == "agent-claude"
    cl = item(r, "agent-claude")
    assert cl["need"] == "required" and cl["next_cmd"] == "slop agents login claude"
    assert "CLAUDE_LOGIN_CODE" in cl["do"] and "secure secret card" in cl["do"]
    assert "agents use" not in cl["do"], "Claude Code is already the runner's default"
    assert item(r, "agent-codex")["need"] == "optional" and item(r, "agent-codex")["next_cmd"] == \
        "slop agents install codex"
    assert r["tiers"]["director"]["missing"] == ["agent-claude"]
    ag = engines(claude={"installed": True, "logged_in": True, "version": "2.1.280", "plan": "max"})
    r = rep("director", agents=ag)
    assert item(r, "agent-claude")["state"] == "done" and "(max plan)" in item(r, "agent-claude")["why"]
    assert r["tiers"]["director"]["ready"]
    assert "Director tier unlocked: Claude Code logged in on the box" in r["unlocked"]
    assert "Director tier unlocked: Claude Code logged in on the box" in r["new_unlocks"]
    assert item(r, "agent-codex")["need"] == "optional"
    assert rep("director", agents=ag)["new_unlocks"] == [], "an unlock is new only once"


def test_an_engine_already_on_the_box_is_preferred_over_a_hardcoded_claude():
    st.set_mark("higgsfield", "done")
    r = rep("director", agents=engines(codex={"installed": True, "logged_in": False}))
    assert I.pref_engine(I.Ctx(tier="director", s=st.load(), agents=engines(codex={"installed": True}))) == "codex"
    assert r["tiers"]["director"]["missing"] == ["agent-codex"]
    assert item(r, "agent-codex")["next_cmd"] == "slop agents login codex"


def test_the_users_plans_are_recommended_in_every_tier_in_their_order():
    st.set_setting("coding-agents", "codex,claude")
    r = rep("quick", agents=engines())
    assert item(r, "agent-codex")["need"] == "recommended" and item(r, "agent-claude")["need"] == "recommended"
    assert item(r, "agent-muse")["need"] == "optional" and item(r, "home-codex")["need"] == "optional"
    assert r["priority"].index("agent-codex") < r["priority"].index("agent-claude")
    r = rep("studio", agents={"available": False, "engines": {}})          # no slop agents: the user's computer
    assert item(r, "home-codex")["need"] == "recommended" and item(r, "home-codex")["state"] == "todo"


def test_director_goes_home_when_slop_agents_is_missing_or_skipped():
    st.set_setting("coding-agents", "claude")
    r = rep("director")                                       # agents module unavailable
    assert r["tiers"]["director"]["missing"][-1] == "home-claude"
    hc = item(r, "home-claude")
    assert hc["need"] == "required" and hc["record_cmd"] == "slop onboard mark home-claude --done"
    assert "claude auth status --json" in hc["do"] and hc["next_cmd"] is None
    st.set_mark("home-claude", "done", "Max plan")
    r = rep("director")
    assert item(r, "home-claude")["state"] == "done"
    assert r["tiers"]["director"]["agents"] == ["claude (home)"]
    st.set_mark("home-claude", "todo")
    # box available but the user skipped the box route: the requirement moves to their own computer
    st.set_mark("agent-claude", "skip")
    r = rep("director", agents=engines())
    assert item(r, "agent-claude")["state"] == "optional" and item(r, "home-claude")["need"] == "required"


def test_director_follows_the_engine_the_user_chose():
    st.update(lambda d: d.update(agents={"use": {"director": "codex"}}))    # what `slop agents use` writes
    r = rep("director", agents=engines(codex={"installed": False}))
    assert item(r, "agent-codex")["need"] == "required" and item(r, "agent-claude")["need"] == "optional"
    assert item(r, "agent-codex")["next_cmd"] == "slop agents install codex"
    assert "agents use" not in item(r, "agent-codex")["do"], "already the chosen Director agent"
    st.set_mark("home-muse", "done")
    r = rep("director", agents=engines(codex={"installed": False}))
    assert item(r, "agent-codex")["need"] == "optional", "any ready engine satisfies the tier"


def test_home_checks_show_the_sign_in_not_just_the_install():
    r = rep("quick")
    for e in I.ENGINES:
        do = item(r, f"home-{e}")["do"]
        assert "--version" not in do and "Windows PowerShell" in do and "Mac or Linux" in do, e
        assert "never an account address" in do
    assert "`codex.cmd login status`" in item(r, "home-codex")["do"], "codex.ps1 is blocked by the default policy"
    assert "auth.json" in item(r, "home-muse")["do"] and "oauth_creds.json" in item(r, "home-gemini")["do"]


def test_director_engines_come_from_the_briefs_and_the_runner():
    """runner/deleg.mjs drives gemini too, but no delegation brief lists it, so `slop agents use` refuses it as the
    Director agent and the runner would fall back to Claude Code: Gemini never unlocks Director."""
    assert I.director_engines() == ("claude", "codex", "muse")
    st.set_mark("higgsfield", "done")
    ag = engines(gemini={"installed": True, "logged_in": True})
    r = rep("director", agents=ag)
    assert item(r, "agent-gemini")["state"] == "done" and item(r, "agent-gemini")["need"] == "optional"
    assert not r["tiers"]["director"]["agents"] and r["tiers"]["director"]["missing"][-1] == "coding-agents"
    st.update(lambda d: d.update(agents={"use": {"director": "gemini"}}))   # a stale choice from an older toolkit
    r = rep("director", agents=ag)
    assert not r["tiers"]["director"]["ready"], "the runner ignores an engine no brief lists"
    st.set_setting("coding-agents", "gemini")
    r = rep("director", agents=ag)
    ca = item(r, "coding-agents")
    assert ca["state"] == "todo" and "none of them can be the Director agent" in ca["why"]
    assert set(ca["answers"]) == {"claude", "chatgpt", "muse", "studio"}
    assert "Gemini" not in I.TIER_ASK.split("Director:")[1]


def test_director_engines_follow_the_repository(monkeypatch, tmp_path):
    def toolkit(runner_engines, brief_line):
        root = tmp_path / str(len(list(tmp_path.iterdir())))
        (root / "runner").mkdir(parents=True)
        (root / "templates" / "briefs").mkdir(parents=True)
        (root / "runner" / "deleg.mjs").write_text(f"const ENGINES = {runner_engines};\n", encoding="utf-8")
        if brief_line is not None:
            (root / "templates" / "briefs" / "x.md").write_text(
                f"<!--\nslop-brief: x\nengines: {brief_line}\n-->\nbody\n", encoding="utf-8")
        monkeypatch.setattr(I, "toolkit_root", lambda: root)
        return I.director_engines()
    assert toolkit("['claude', 'codex', 'muse', 'gemini', 'raw']", "claude, codex or gemini") == \
        ("claude", "codex", "gemini"), "a brief that lists gemini makes it a Director agent"
    assert toolkit("['claude', 'codex', 'raw']", "claude, codex or muse") == ("claude", "codex"), \
        "the runner must drive it too"
    assert toolkit("['claude']", None) == I.FALLBACK_DIRECTOR_ENGINES, "no readable briefs: the fallback"


def test_codex_images_follow_codex_on_the_box():
    r = rep("quick", agents=engines(codex={"installed": True, "logged_in": False}))
    assert item(r, "codex-images")["blocked_by"] == ["agent-codex"]
    r = rep("quick", agents=engines(codex={"installed": True, "logged_in": True}))
    assert item(r, "codex-images")["state"] == "done"


def test_missing_modules_are_named_and_never_next():
    r = rep("director", **FRESH)
    for iid in ("agent-claude", "agent-codex", "agent-muse", "agent-gemini", "codex-images", "gpu"):
        it = item(r, iid)
        assert it["state"] == "blocked" and it["available"] is False
        assert "not available in this toolkit version" in it["why"] and it["next_skill"] == "claudia-toolkit"
    st.set_mark("gpu", "skip")
    assert item(rep("director"), "gpu")["state"] == "blocked", "a skip does not hide a missing module"
    r = rep("quick", gpu={"available": False, "unregistered": True})
    g = item(r, "gpu")
    assert g["state"] == "blocked" and "does not load it yet" in g["why"] and "slop.gpu.cli" in g["do"]


def test_a_failed_agents_probe_is_an_error_with_the_command_to_read():
    r = rep("director", agents={"available": True, "engines": {}, "error": "boom"})
    cl = item(r, "agent-claude")
    assert cl["state"] == "error" and cl["need"] == "optional", "no plan recorded: no engine is required yet"
    assert r["next_item"] != "agent-claude"
    st.set_setting("coding-agents", "claude")
    r = rep("director", agents={"available": True, "engines": {}, "error": "boom"})
    assert item(r, "agent-claude")["state"] == "error" and item(r, "agent-claude")["next_cmd"] == "slop agents status"
    q = rep("quick", agents={"available": True, "engines": {}, "error": "boom"})
    assert item(q, "agent-codex")["need"] == "optional" and q["next_item"] != "agent-codex"


# ---------------------------------------------------------------- toolkit, doctor, install in progress
def test_path_item_writes_both_shell_files():
    r = rep("quick", tk={"on_path": False, "shell_rc": []})
    p = item(r, "path")
    assert p["state"] == "todo" and p["next_cmd"] == (
        "grep -qsF /w/.claudia/env.sh ~/.bashrc || echo '. /w/.claudia/env.sh' >> ~/.bashrc; "
        "grep -qsF /w/.claudia/env.sh ~/.profile || echo '. /w/.claudia/env.sh' >> ~/.profile")
    assert "/w/.claudia/bin/slop by its full path" in p["do"]
    p = item(rep("quick", tk={"on_path": False, "shell_rc": [".bashrc"]}), "path")
    assert p["state"] == "todo" and "only ~/.bashrc" in p["why"]
    p = item(rep("quick", tk={"on_path": False, "shell_rc": [".bashrc", ".profile"]}), "path")
    assert p["state"] == "done" and "/w/.claudia/bin/slop by its full path" in p["warn"]
    assert item(rep("quick"), "path")["state"] == "done"


def test_doctor_failures_are_an_error_and_come_next():
    fails = [{"name": "ffmpeg", "detail": "ffmpeg not found", "fix": "install ffmpeg"}]
    r = rep("quick", doc={"ok": True, "fails": fails, "warns": [], "deps_full": "ok"})
    d = item(r, "doctor")
    assert d["state"] == "error" and d["next_cmd"] == "slop doctor" and "first fix: install ffmpeg" in d["why"]
    assert r["next_item"] == "doctor" and not r["tiers"]["quick"]["ready"]
    r = rep("quick", doc={"ok": False, "error": "RuntimeError: x"})
    assert item(r, "doctor")["state"] == "error"


def test_full_profile_states_and_an_install_in_progress_is_passed_over():
    st.set_mark("higgsfield", "done")
    r = rep("studio", tk={"profile": "minimal"}, doc={"deps_full": "skip"})
    fp = item(r, "full-profile")
    assert fp["state"] == "todo" and fp["next_cmd"].endswith("bin/setup.sh --full") and fp["long"]
    r = rep("studio", tk={"profile": "minimal"}, doc={"deps_full": "skip"}, running=[{"pid": 7, "full": True}])
    assert item(r, "full-profile")["running"] and r["next_item"] != "full-profile"
    assert r["running"] == ["full-profile"] and "Installing now: full-profile" in I.render_status(r)
    r = rep("studio", doc={"deps_full": "fail"})
    assert item(r, "full-profile")["state"] == "error"


# ---------------------------------------------------------------- the OpenRouter key (real probe, mocked HTTP)
def _key(monkeypatch, status, payload, err=None, offline=False):
    monkeypatch.setenv("OPENROUTER_API_KEY", FAKE_KEY)
    calls = []

    def fake(url, headers=None, timeout=20, method="GET"):
        calls.append(url)
        assert url.endswith("/api/v1/key"), url
        return status, payload, err
    monkeypatch.setattr(util, "http_json", fake)
    k = probes.openrouter(offline=offline)
    assert FAKE_KEY not in json.dumps(k)
    return item(I.report(tier="quick", data={**data(), "key": k}), "openrouter"), calls


def test_key_missing_is_todo_with_the_secure_card():
    k = probes.openrouter()
    it = item(I.report(tier="quick", data={**data(), "key": k}), "openrouter")
    assert it["state"] == "todo" and "secure secret card" in it["do"] and it["next_skill"] == "setup-accounts"


def test_key_rejected_unreachable_offline(monkeypatch):
    it, _ = _key(monkeypatch, 401, {"error": {"message": "no"}}, "no")
    assert it["state"] == "error" and "rejected" in it["why"]
    it, _ = _key(monkeypatch, 0, None, "network error: refused")
    assert it["state"] == "error" and it["next_cmd"] == "slop doctor --net"
    it, calls = _key(monkeypatch, 200, {"data": {}}, offline=True)
    assert it["state"] == "done" and "not checked" in it["why"] and calls == []


def test_key_limit_expiry_and_free_tier(monkeypatch):
    from datetime import datetime, timedelta, timezone
    soon = (datetime.now(tz=timezone.utc) + timedelta(days=5, hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    it, _ = _key(monkeypatch, 200, {"data": {"limit": 80, "usage": 9.6, "limit_remaining": 70.4,
                                             "expires_at": soon, "is_free_tier": False}})
    assert it["state"] == "done" and "used $9.60 of its $80.00 limit ($70.40 left)" in it["why"]
    assert f"expires {soon[:10]} (5 days)" in it["why"] and "before it expires" in it["warn"]
    assert "used $9.60" in it["cost_note"]
    past = (datetime.now(tz=timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    it, _ = _key(monkeypatch, 200, {"data": {"limit": 80, "usage": 1, "expires_at": past}})
    assert it["state"] == "error" and "EXPIRED" in it["why"]
    it, _ = _key(monkeypatch, 200, {"data": {"limit": None, "usage": 0, "is_free_tier": True}})
    assert it["state"] == "done" and "FREE tier" in it["warn"] and "credit limit" in it["warn"]


# ---------------------------------------------------------------- marks
def test_skip_moves_an_item_out_of_the_way_and_todo_brings_it_back():
    r = rep("studio")
    assert r["next_item"] == "higgsfield"
    st.set_mark("higgsfield", "skip", "no Higgsfield account")
    r = rep("studio")
    hf = item(r, "higgsfield")
    assert hf["state"] == "optional" and hf["skipped"] and "no Higgsfield account" in hf["why"]
    assert "undo: slop onboard mark higgsfield --todo" in hf["why"] and r["next_item"] != "higgsfield"
    assert "record_cmd" not in hf and hf["next_cmd"] is None
    st.set_mark("higgsfield", "todo")
    assert rep("studio")["next_item"] == "higgsfield"


def test_an_old_note_is_scrubbed_when_shown():
    """A file written before the note rules (or by hand) still never shows an address or a key."""
    st.update(lambda d: d["marks"].update({"home-codex": {"state": "done", "at": "2026-10-01",
                                                          "note": f"bob.smith@example.com {FAKE_KEY}"}}))
    r = rep("quick")
    why = item(r, "home-codex")["why"]
    assert "example.com" not in why and FAKE_KEY not in why and "[account]" in why


def test_done_wins_over_an_old_skip():
    st.set_mark("gpu", "skip")
    g = {"available": True, "ok": True, "mode": "paired", "healthy": True,
         "gpus": [{"name": "RTX 3090 Ti", "vram_gb": 24.0}], "profiles": ["audio"]}
    it = item(rep("director", gpu=g), "gpu")
    assert it["state"] == "done" and "RTX 3090 Ti 24 GB paired" in it["why"] and "audio" in it["why"]


def test_except_passes_over_an_item_for_now():
    r = rep("studio")
    assert I.pick_next(r["items"])["id"] == "higgsfield"
    assert I.pick_next(r["items"], exclude=["higgsfield"])["id"] == "suno"


# ---------------------------------------------------------------- GPU
@pytest.mark.parametrize("g,state,cmd", [
    ({"mode": "paired", "healthy": False, "last_seen": "2026-10-01T10:00Z", "gpus": []}, "error",
     "slop gpu pair --refresh"),
    ({"mode": "paired", "healthy": None, "gpus": [{"name": "RTX 5070", "vram_gb": 12.0}]}, "done", None),
    ({"mode": "direct", "healthy": None, "gpus": []}, "done", None),
    ({"mode": "none", "healthy": None, "gpus": [], "ok": True}, "todo", None),
    ({"mode": "none", "healthy": None, "gpus": [], "ok": False, "error": "boom"}, "error", "slop gpu status"),
])
def test_gpu_states(g, state, cmd):
    it = item(rep("director", gpu={"available": True, **g}), "gpu")
    assert it["state"] == state and it["next_cmd"] == cmd
    if g["mode"] == "none" and state == "todo":
        assert it["need"] == "recommended" and "NVIDIA" in it["ask"]
        assert it["answers"] == {"paired": "slop gpu serve", "direct-windows": "slop gpu direct-plan",
                                 "direct-mac-linux": "slop gpu direct-plan --os mac_linux",
                                 "none": "slop onboard mark gpu --skip"}
        assert item(rep("quick", gpu={"available": True, **g}), "gpu")["state"] == "todo", "asked in every tier"


def test_gpu_follows_the_gpu_modules_own_reason():
    def gpu_item(**g):
        return item(rep("studio", gpu={"available": True, "mode": "paired", "healthy": False, **g}), "gpu")
    it = gpu_item(why="no computer is paired", hint_cmd="slop gpu pair")
    assert it["state"] == "todo" and it["next_cmd"] == "slop gpu pair" and "ONE line" in it["do"]
    it = gpu_item(why="the GPU job server is not running on the box", hint_cmd="slop gpu serve")
    assert it["state"] == "error" and it["next_cmd"] == "slop gpu serve" and "tunnel URL" not in it["do"]
    it = gpu_item(why="the paired computer has not checked in for 900 s", hint_cmd="slop gpu pair --refresh")
    assert it["state"] == "error" and "asleep" in it["do"]
    it = gpu_item(why="the GPU is busy (another program uses 9 GiB)", hint_cmd=None)
    assert it["state"] == "done" and "busy" in it["warn"]


# ---------------------------------------------------------------- taste (real probe on the user profile)
def test_taste_reads_the_user_profile(env):
    root = env / "home" / "taste"
    root.mkdir(parents=True)
    rows = [{"eid": f"e{i}", "t": "2026-10-01", "item": f"i{i}", "action": "like" if i % 2 else "pass"}
            for i in range(20)]
    (root / "taps.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    t = probes.taste()
    assert t["taps"] == 20
    r = I.report(tier="studio", data={**data(), "taste": t})
    assert item(r, "taste")["state"] == "blocked" and item(r, "taste")["blocked_by"] == ["first-project"]
    r = I.report(tier="studio", data={**data(), "taste": t, "projects": [PROJECT]})
    assert item(r, "taste")["state"] == "todo" and "20 of 150" in item(r, "taste")["why"]
    rows = [{"eid": f"f{i}", "t": "2026-10-01", "item": f"j{i}", "action": "like"} for i in range(140)]
    with (root / "taps.jsonl").open("a", encoding="utf-8") as f:
        f.write("\n".join(json.dumps(r) for r in rows) + "\n")
    (root / "meter.jsonl").write_text(json.dumps({"accuracy": 0.78, "margin": 0.05, "n": 160}) + "\n",
                                      encoding="utf-8")
    r = I.report(tier="studio", data={**data(), "taste": probes.taste(), "projects": [PROJECT]})
    assert item(r, "taste")["state"] == "done" and "160 taps, meter 78 % ± 5" in item(r, "taste")["why"]


# ---------------------------------------------------------------- Midjourney plan + profile code -> the project
def test_recorded_midjourney_settings_are_offered_to_the_newest_project():
    st.set_setting("mj-plan", "pro")
    st.set_setting("mj-profile", "abc123x")
    st.set_setting("suno-plan", "none")
    st.set_mark("higgsfield", "done")
    r = rep("studio", projects=[PROJECT])
    mp, mj = item(r, "mj-profile"), item(r, "midjourney")
    assert "abc123x" not in json.dumps(r) and "ab… (7 characters)" in mp["why"]
    assert mp["state"] == "done" and mp["next_cmd"] is None and "P button" in mp["why"]
    assert mj["state"] == "todo" and mj["next_cmd"] == "slop --project my-song onboard apply"
    assert "sizes its prompt batches for Standard" in mj["why"] and r["next_item"] == "midjourney"
    r = rep("studio", projects=[{**PROJECT, "mj_profile_set": True, "mj_plan": "pro"}])
    assert item(r, "mj-profile")["state"] == "done" and item(r, "mj-profile")["next_cmd"] is None
    assert item(r, "midjourney")["state"] == "done" and item(r, "midjourney")["next_cmd"] is None
    st.set_setting("mj-plan", "standard")                    # the plate book's default already matches
    assert item(rep("studio", projects=[PROJECT]), "midjourney")["state"] == "done"


# ---------------------------------------------------------------- tier choice and unlock memory
def test_tier_comes_from_the_flag_the_setting_or_the_newest_project():
    r = I.report(data=data())
    assert r["tier"] == "quick" and r["tier_source"].startswith("default")
    assert "judged for quick for now: default" in item(r, "tier")["why"]
    assert I.report(data=data(projects=[PROJECT]))["tier"] == "studio"
    st.set_setting("tier", "director")
    r = I.report(data=data(projects=[PROJECT]))
    assert r["tier"] == "director" and item(r, "tier")["state"] == "done"
    assert I.report(tier="quick", data=data())["tier_source"] == "--tier"


def test_new_unlocks_are_reported_once():
    r1 = rep("quick")
    assert any(u.startswith("Quick tier ready: stills from OpenRouter or Grok's image tool") for u in r1["new_unlocks"])
    r2 = rep("quick")
    assert r2["new_unlocks"] == [] and r2["unlocked"] == r1["unlocked"]
    st.set_mark("higgsfield", "done")
    r3 = rep("quick")
    assert I.SPEC["higgsfield"]["unlocks"] in r3["new_unlocks"]
    assert "stills from OpenRouter or Higgsfield or Grok's image tool" in r3["unlocked"][0]
    assert "Quick tier ready" not in " ".join(r3["new_unlocks"]), "a changed unlock text is not new again"


def test_report_without_record_writes_nothing():
    I.report(tier="quick", data=data(), record=False)
    assert not st.path().exists()


# ---------------------------------------------------------------- readers of the other modules' JSON
@pytest.mark.parametrize("payload", [
    {"ok": True, "engines": {"claude": {"installed": True, "version": "2.1.280", "logged_in": True,
                                        "plan": "max"}, "codex": {"installed": False}}},
    {"ok": True, "engines": [{"engine": "claude", "path": "/w/bin/claude", "version": "2.1.280",
                              "auth": {"loggedIn": True, "subscriptionType": "max", "email": "a@example.com"}},
                             {"engine": "codex", "installed": False}]},
    {"ok": True, "agents": {"Claude Code": {"version": "2.1.280", "login": {"state": "logged_in", "plan": "max"}},
                            "Codex": {"installed": "no"}}},
    {"ok": True, "claude": {"installed": True, "version": "2.1.280", "auth_status": "ok", "account": {"plan": "max"}},
     "codex": {"present": False}, "text": "..."},
    # slop.agents' own `agents status` shape (slop/agents/status.py)
    {"ok": True, "ready": ["claude"], "agents": [
        {"engine": "claude", "title": "Claude Code", "installed": True, "bin": "/w/.claudia/bin/claude",
         "via": "native", "version": "2.1.280", "logged_in": True, "auth": "claude.ai", "plan": "max",
         "account": "someone@example.com", "next": "slop agents test claude"},
        {"engine": "codex", "title": "Codex", "installed": False, "bin": None, "version": None, "logged_in": None,
         "plan": None, "account": None, "next": "slop agents install codex"}]},
])
def test_normalize_agents_reads_many_shapes(payload):
    got = probes.normalize_agents(payload)
    keep = ("installed", "logged_in", "version", "plan", "error")
    assert {k: got["claude"][k] for k in keep} == {"installed": True, "logged_in": True, "version": "2.1.280",
                                                   "plan": "max", "error": None}
    assert got["codex"]["installed"] is False and got["codex"]["logged_in"] is None
    assert "example.com" not in json.dumps(got)


def test_a_pending_sign_in_uses_the_agents_modules_own_next_step():
    got = probes.normalize_agents({"agents": [
        {"engine": "codex", "installed": True, "version": "0.155.1", "logged_in": False,
         "login_pending": {"state": "waiting", "url": "https://auth.example.com/device", "user_code": "ABCD-1234"},
         "next": "slop agents login codex --check", "detail": "device code issued"},
        {"engine": "claude", "installed": True, "logged_in": False, "next": "rm -rf / ; echo"}]})
    assert got["codex"]["login_pending"] and got["codex"]["next"] == "slop agents login codex --check"
    assert got["claude"]["next"] is None, "only `slop agents ...` steps without placeholders are taken over"
    assert "ABCD-1234" not in json.dumps(got) and "auth.example.com" not in json.dumps(got)
    r = rep("director", agents={"available": True, "ok": True, "engines": got})
    it = item(r, "agent-codex")
    assert it["next_cmd"] == "slop agents login codex --check" and "waiting for the user" in it["why"]
    assert item(r, "agent-claude")["next_cmd"] == "slop agents login claude"


def test_normalize_agents_edge_cases():
    assert probes.normalize_agents(None) == {} and probes.normalize_agents({"ok": False, "error": "x"}) == {}
    got = probes.normalize_agents({"engines": {"muse": {"installed": True, "logged_in": "logged-out",
                                                        "error": "token sk-or-v1-ABCDEFGHIJKLMNOPQRSTUV expired"},
                                               "copilot": {"installed": True}}})
    assert list(got) == ["muse"] and got["muse"]["logged_in"] is False
    assert "ABCDEFGHIJ" not in got["muse"]["error"] and "[hidden]" in got["muse"]["error"]


@pytest.mark.parametrize("payload,want", [
    ({"mode": "paired", "worker": {"alive": True, "gpus": [{"name": "NVIDIA GeForce RTX 3090 Ti",
                                                            "memory_total_mib": 24564}],
                                   "profiles": {"audio": {"installed": True}, "matte": {"installed": False}}}},
     {"mode": "paired", "healthy": True, "gpus": [{"name": "NVIDIA GeForce RTX 3090 Ti", "vram_gb": 24.0}],
      "profiles": ["audio"]}),
    ({"paired": True, "worker_alive": False, "last_seen": "2026-10-01T09:00:00Z", "gpu": "RTX 5070",
      "profiles": ["audio", "matte"]},
     {"mode": "paired", "healthy": False, "gpus": [{"name": "RTX 5070", "vram_gb": None}],
      "profiles": ["audio", "matte"]}),
    ({"connection": "direct", "gpus": [{"name": "RTX 5070", "vram": "12227 MiB"}]},
     {"mode": "direct", "healthy": None, "gpus": [{"name": "RTX 5070", "vram_gb": 11.9}], "profiles": []}),
    ({"ok": True, "mode": "none"}, {"mode": "none", "healthy": None, "gpus": [], "profiles": []}),
    ({"pairing": {"url": "https://x.trycloudflare.com", "status": "offline"}},
     {"mode": "paired", "healthy": False, "gpus": [], "profiles": []}),
    # slop.gpu's health record (slop/gpu/route.py health()), nested or flat
    ({"ok": True, "health": {"ok": False, "configured": True, "mode": "paired",
                             "why": "the paired computer has not checked in for 900 s",
                             "next": "on the PC run `slopgpu start`, or paste the line from `slop gpu pair --refresh`",
                             "worker": {"gpus": [{"kind": "cuda", "name": "RTX 5070", "total_mib": 12227}],
                                        "profiles": {"audio": {"ready": True}, "matte": {"ready": False}},
                                        "fresh": False, "age_s": 900.0}}},
     {"mode": "paired", "healthy": False, "gpus": [{"name": "RTX 5070", "vram_gb": 11.9}], "profiles": ["audio"],
      "hint_cmd": "slop gpu pair --refresh", "last_seen": "900 s ago"}),
    ({"ok": False, "configured": False, "mode": "none", "why": "no home GPU is set up",
      "next": "`slop gpu serve --tunnel` then `slop gpu pair` (or direct mode: `slop gpu direct-plan`)", "worker": {}},
     {"mode": "none", "hint_cmd": "slop gpu serve --tunnel", "why": "no home GPU is set up",
      "hint_cmds": ["slop gpu serve --tunnel", "slop gpu pair", "slop gpu direct-plan"]}),
    # positional words are kept (the old reader cut them off)
    ({"mode": "paired", "healthy": False, "why": "the audio profile is not installed on the PC yet",
      "next": "`slop gpu install audio`"},
     {"hint_cmd": "slop gpu install audio"}),
    ({"mode": "none", "next": "slop gpu serve"}, {"hint_cmd": "slop gpu serve"}),
])
def test_normalize_gpu_reads_many_shapes(payload, want):
    got = probes.normalize_gpu(payload)
    assert {k: got[k] for k in want} == want


# ---------------------------------------------------------------- small helpers
def test_scrub_hides_keys_and_addresses():
    s = probes.scrub(f"failed for someone@example.com with {FAKE_KEY}\n next line")
    assert FAKE_KEY not in s and "example.com" not in s and "\n" not in s and "[hidden]" in s
    assert probes.scrub("studio-tier-with-higgsfield-creator-plan") == "studio-tier-with-higgsfield-creator-plan"


@pytest.mark.parametrize("words,want", [
    (["bash", "/workspace/claudia/bin/setup.sh", "--full"], {"full": True}),
    (["bash", "/workspace/claudia/bin/setup.sh"], {"full": False}),
    (["bash", "-c", "(bash /w/bin/setup.sh --minimal && bash /w/bin/setup.sh --full) > /w/log 2>&1"], {"full": True}),
    (["bash", "-lc", "bash /w/bin/setup.sh --minimal > /w/log"], {"full": False}),
    (["bash", "/w/bin/setup.sh", "--check", "--full", "--json"], None),
    (["python", "setup.sh", "--full"], None),
    (["bash", "-c", "slop onboard status"], None),
    ([], None),
])
def test_setup_call(words, want):
    assert probes.setup_call(words) == want


def test_resolve_item_aliases_and_unknown():
    assert I.resolve_item("HF") == "higgsfield" and I.resolve_item("claude") == "agent-claude"
    assert I.resolve_item("mj") == "midjourney" and I.resolve_item("home-gpu") == "gpu"
    assert I.resolve_item("chatgpt") == "agent-codex" and I.resolve_item("plans") == "coding-agents"
    from slop.config import SlopError
    with pytest.raises(SlopError, match="Items: tier, toolkit, path"):
        I.resolve_item("nonsense-item")


def test_probe_timeout_stays_under_the_bot_shell_limit(monkeypatch):
    assert probes.probe_timeout() == 15.0
    monkeypatch.setenv("SLOP_WAIT_MAX", "18")
    assert probes.probe_timeout() == 8.0
    monkeypatch.setenv("SLOP_WAIT_MAX", "nonsense")
    assert probes.probe_timeout() == 15.0


def test_a_family_counts_only_when_the_router_loads_it(monkeypatch):
    assert probes.module_for("onboard") == "slop.onboard.cli" and probes.command_parses("slop onboard next")
    monkeypatch.setenv("SLOP_MODULES", "slop.core_cli")
    assert probes.module_for("onboard") is None and probes.package_present("onboard")
    assert not probes.command_parses("slop onboard next"), "the real `slop` would say invalid choice"
    from slop import cli
    monkeypatch.delenv("SLOP_MODULES")
    monkeypatch.setattr(cli, "MODULES", [m for m in cli.MODULES if m != "slop.gpu.cli"])
    assert probes.module_for("gpu") is None
    g = probes.gpu()
    assert g["available"] is False and g["unregistered"] is probes.package_present("gpu")


def test_foreign_hints_are_used_only_when_they_parse(monkeypatch):
    assert probes.command_parses("slop onboard next --tier studio")
    assert probes.command_parses("slop --project my-song onboard apply")
    assert not probes.command_parses("slop --project NAME onboard apply"), "a placeholder never runs as printed"
    assert not probes.command_parses("slop onboard next --bogus")
    assert not probes.command_parses("slop nosuchfamily status")
    assert not probes.command_parses("rm -rf /") and not probes.command_parses("slop 'unclosed")
    monkeypatch.setattr(probes, "module_for", lambda fam: "slop.gpu.cli")
    monkeypatch.setattr(probes, "command_parses", lambda c: c in ("slop gpu serve", "slop gpu pair"))
    for nxt, want in (("`slop gpu serve --no-such-flag` then `slop gpu pair`", "slop gpu pair"),
                      ("`slop gpu serve --no-such-flag`", "slop gpu serve"),     # flags dropped as a last resort
                      ("slop gpu serve", "slop gpu serve"),
                      ("use `--gpu require`, then `slop gpu direct-plan JOB`", None)):
        monkeypatch.setattr(probes, "run_cli", lambda m, w, t=0, n=nxt: {
            "ok": True, "rc": 0, "error": None, "data": {"mode": "none", "healthy": False, "next": n}})
        g = probes.gpu()
        assert g["hint_cmd"] == want, nxt
        it = item(rep("director", gpu=g), "gpu")
        assert it["next_cmd"] is None and it["ask"], "mode none: the GPU question comes first"
    monkeypatch.setattr(probes, "command_parses", lambda c: False)
    monkeypatch.setattr(probes, "module_for", lambda fam: "slop.agents.cli")
    monkeypatch.setattr(probes, "run_cli", lambda m, w, t=0: {"ok": True, "rc": 0, "error": None, "data": {
        "agents": [{"engine": "codex", "installed": True, "logged_in": False, "next": "slop agents login codex --nope"}]}})
    assert probes.agents()["engines"]["codex"]["next"] is None

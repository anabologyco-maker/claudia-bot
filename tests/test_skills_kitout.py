"""Locks for the KIT-OUT skills fixes: the walks of a new user with (a) only Grok Bot, (b) Grok Bot + OpenRouter
+ Suno + Midjourney and (c) everything incl. Claude Code, Codex, Muse and an NVIDIA PC must never dead-end. The skills
sit a few bytes under their budgets, so a later trim must not silently undo any of these."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"


def read(rel: str) -> str:
    return (SKILLS / rel).read_text(encoding="utf-8")


def test_profile_lets_printed_codes_reach_the_owner():
    prof = read("profile.md")
    rule = next(ln for ln in prof.splitlines() if ln.startswith("3. Secrets"))
    assert "sign-in code" in rule and "device codes" in rule.lower(), rule   # (pairing lines return with the GPU link)
    assert "key, code or password" not in rule, "a bare 'code' forbids sending device codes and storing the MJ profile"
    assert "/workspace/claudia/bin/slop" in prof, "before the install only the checkout's launcher exists"


def test_setup_install_is_detached_and_the_clone_never_prompts():
    setup = read("claudia-setup/SKILL.md")
    assert "nohup setsid bash -c 'bash /workspace/claudia/bin/setup.sh --minimal && bash " \
           "/workspace/claudia/bin/setup.sh --full' > /workspace/claudia-install.log 2>&1 < /dev/null &" in setup
    assert "GIT_TERMINAL_PROMPT=0" in setup
    code = next(ln for ln in setup.splitlines() if ln.startswith("1. Code"))
    assert "test -f /workspace/claudia/bin/setup.sh ||" in code, "a staged checkout is kept"
    assert "detached" in read("DESIGN.md") and "ONE background install shell" not in read("DESIGN.md")
    assert "nohup setsid bash /workspace/claudia/bin/setup.sh" in read("claudia-toolkit/SKILL.md"), "repair too"


def test_setup_never_dead_ends():
    setup = read("claudia-setup/SKILL.md")
    assert "can come later" in setup and '("setup" brings this back)' in setup, "every account can wait"
    assert "Grok Imagine is your own tool: nothing to sign in." in setup, "no X plan needed for Grok Imagine"
    assert "still failing: go on" in setup, "a gallery outage never blocks the setup"
    assert setup.rstrip().endswith("Their next message: skill claudia-relay.")


def test_agents_install_needs_a_yes_and_cards_reach_a_new_shell():
    text = read("setup-agents/SKILL.md")
    assert "after one yes from the person" in text
    step = next(ln for ln in text.splitlines() if ln.startswith("2. Install"))
    assert "only the ones they have" in step and "install all" not in step, "never install engines they do not use"
    assert "agents install all" not in read("claudia-toolkit/SKILL.md")
    assert "agents login codex --cancel" in text, "a waiting sign-in is only re-shown: cancel before a retry"
    assert "bash -lc '/workspace/claudia/bin/slop --json agents login claude --code-from-env CLAUDE_LOGIN_CODE'" in text
    assert "research-lyrics, prompt-book and chapter-motion need Claude Code or Codex" in text
    acc = read("setup-accounts/SKILL.md")
    assert "bash -lc 'slop " not in acc, "`slop` may not be on PATH yet in a login shell: use the checkout's launcher"
    assert "onboard mark openrouter --skip" in acc and "Grok Imagine" in acc


def test_gpu_skill_never_polls_and_names_no_foreign_flag():
    text = read("setup-gpu/SKILL.md")
    assert "--force-gpu" not in text, "only `slop gpu submit` has --force-gpu"
    assert not re.search(r"gpu status` until", text), "end the turn instead of polling"
    assert "1-2 min per song analysis" in text


def test_quick_stills_keep_the_chatgpt_plan_choice():
    assert "without `--quality medium`" in read("mv-quick/SKILL.md")


def test_director_checks_the_job_engine_before_start():
    assert "do not start" in read("mv-director/SKILL.md")

"""The Grok Bot template (skills/): the recipe builder, the import budget, front matter, scrub, and the operator's
commands and pointers.

The skills are replayed by the model on import and then followed by a weaker model, so every command they name must
exist in the real argparse tree (placeholders filled), every doc and section they point to must exist, every `slop`
step must be `slop --json ...` with the project named, and the setup skill must carry the public install line, its own
import self-check and the toolkit version it was written for. The onboarding set (claudia-setup driven by `slop onboard`,
setup-accounts, setup-agents, setup-gpu) must use the checklist's real fields and the agents' real secret names. No
network, no browser.
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import scrublist  # noqa: E402
from slop import __version__, cli, util  # noqa: E402

_spec = importlib.util.spec_from_file_location("build_recipe", SKILLS / "build_recipe.py")
BR = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(BR)

CLONE = "git clone -q https://github.com/anabologyco-maker/claudia-bot /workspace/claudia"
PIN = f"git -C /workspace/claudia checkout -q v{__version__}"
SETUP = "bash /workspace/claudia/bin/setup.sh --minimal && bash /workspace/claudia/bin/setup.sh --full"
ENV_LINE = "grep -qs claudia/env.sh ~/.bashrc || echo '. /workspace/.claudia/env.sh' >> ~/.bashrc"
SKILL_FILES = [SKILLS / s / "SKILL.md" for s in BR.ORDER]
SOURCES = SKILL_FILES + [SKILLS / "profile.md", SKILLS / "memory.md"] + sorted((SKILLS / "routines").glob("*.md"))
# commands that need no project (everything else must name one with -p / --project); per file: a box-level job
# (`slop agents install` runs as a job in $SLOP_HOME/jobs, so its wait names no project)
PROJECTLESS = {("new",), ("projects",), ("doctor",), ("gen", "models"), ("gen", "estimate"), ("job", "selftest"),
               ("onboard", "next"), ("onboard", "status"), ("onboard", "mark"), ("onboard", "set"), ("agents",), ("gpu",),
               ("relay",), ("update",)}
PROJECTLESS_IN = {"setup-agents/SKILL.md": {("job", "wait")}}
FILL = {"USD": "USD", "UNIT": "credits", "FILE": "x.wav", "CLIP": "c01", "SHOT": "s001", "PLATE": "p001", "ID": "j1", "URL": "https://x.test/a",
        "LINK": "https://x.test/a", "TITLE": "t", "NAME": "demo", "BATCH": "b1", "SLUG": "s", "DIR": "d", "RULE": "texture",
        "ENGINE": "claude", "JOB": "0123abcd", "PROFILE": "audio", "SECTION": "intro", "MODE": "native", "CODE": "abc12"}


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def built():
    return BR.build()


# ---------------------------------------------------------------- the recipe
def test_builds_with_no_problems(built):
    recipe, problems, report = built
    assert problems == [], "\n".join(problems)
    assert report["total"] <= BR.MAX_TOTAL


def test_recipe_matches_the_template_schema(built):
    recipe, _, _ = built
    assert set(recipe) == {"profile", "memory", "skills", "routines", "plugins", "gettingStarted"}
    assert recipe["profile"]["name"] == "Claudia" and recipe["profile"]["description"].strip()
    assert [s["name"] for s in recipe["skills"]] == BR.ORDER and len(BR.ORDER) == 11
    assert "setup-gpu" not in BR.ORDER and (SKILLS / "setup-gpu" / "SKILL.md").is_file(), "parked, not shipped"
    for s in recipe["skills"]:
        assert set(s) == {"name", "description", "content"} and all(s.values())
        assert s["content"] == read(SKILLS / s["name"] / "SKILL.md")           # the whole file, front matter included
    assert recipe["gettingStarted"] == {"skill": "claudia-welcome"}
    assert recipe["memory"] and all(m["kind"] == "log" and m["content"] for m in recipe["memory"])
    assert recipe["routines"] == [], "no routine: the Grok side only relays"
    assert not set(BR.ORDER) & set(BR.PRODUCTION), "stage guides for the production stay out of the template"
    assert all((SKILLS / s / "SKILL.md").is_file() for s in BR.PRODUCTION)
    assert recipe["plugins"] == [{"name": "Higgsfield", "description": BR.PLUGIN["description"],
                                  "pluginId": BR.PLUGIN_ID_DEFAULT}]
    assert BR.PLUGIN_ID_DEFAULT.isdigit() and BR.PLUGIN_ID_DEFAULT != BR.PLUGIN_PLACEHOLDER
    assert BR.validate(recipe) == []


def test_the_shipped_recipe_is_current(built):
    """skills/dist/recipe.json is what `python skills/build_recipe.py` writes now (rebuild it after any skill edit)."""
    shipped = json.loads((SKILLS / "dist" / "recipe.json").read_text(encoding="utf-8"))
    assert shipped == built[0], "stale: run python skills/build_recipe.py"
    assert shipped["plugins"][0]["pluginId"] == "5420454"


def test_schema_rules_catch_a_broken_recipe(built):
    recipe = json.loads(json.dumps(built[0]))
    recipe["gettingStarted"]["skill"] = "nope"
    recipe["skills"].append(dict(recipe["skills"][0]))
    recipe["plugins"][0]["pluginId"] = ""
    probs = BR.validate(recipe)
    assert any("gettingStarted" in p for p in probs) and any("duplicate" in p for p in probs)
    assert any("pluginId" in p for p in probs)


def test_builder_cli_writes_the_recipe_and_release_needs_the_plugin_id(tmp_path, capsys, built):
    out = tmp_path / "recipe.json"
    assert BR.main(["--out", str(out), "--json"]) == 0
    res = json.loads(capsys.readouterr().out)
    assert res["ok"] and res["wrote"] == str(out)
    assert json.loads(out.read_text(encoding="utf-8")) == built[0]
    assert BR.main(["--check", "--release", "--json"]) == 0             # the recorded default id
    assert json.loads(capsys.readouterr().out)["report"]["plugin_id"] == "default"
    assert BR.main(["--check", "--release", "--plugin-id", BR.PLUGIN_PLACEHOLDER, "--json"]) == 1
    res = json.loads(capsys.readouterr().out)
    assert any("placeholder" in p for p in res["problems"])
    assert BR.main(["--check", "--release", "--plugin-id", "1234567", "--json"]) == 0
    capsys.readouterr()
    recipe, problems, _ = BR.build("1234567", release=True)
    assert not problems and recipe["plugins"][0]["pluginId"] == "1234567"


# ---------------------------------------------------------------- sizes and front matter
def test_sizes_fit_the_import_budget():
    sizes = {p.parent.name: len(read(p).encode("utf-8")) for p in SKILL_FILES}
    assert all(n <= 6 * 1024 for n in sizes.values()), sizes
    _, profile = BR.front_matter(read(SKILLS / "profile.md"))
    assert len(profile.strip().encode("utf-8")) <= 3 * 1024
    total = sum(len(read(p).encode("utf-8")) for p in SOURCES)
    assert total <= 80 * 1024, total
    assert BR.MAX_TOTAL == 80 * 1024 and BR.MAX_SKILL == 6 * 1024


def test_the_import_budget_counts_everything_the_importer_re_emits(built):
    recipe, _, report = built
    descs = sum(len(s["description"].encode("utf-8")) for s in recipe["skills"])
    assert descs > 1000                                                    # sent again besides each skill's content
    plugin = sum(len(p["description"].encode("utf-8")) for p in recipe["plugins"])
    profile = len(recipe["profile"]["description"].encode("utf-8"))
    routines = sum(len((r["content"] + r["description"]).encode("utf-8")) for r in recipe["routines"])
    memory = sum(len(m["content"].encode("utf-8")) for m in recipe["memory"])
    assert report["total"] == report["skills_total"] + descs + profile + routines + memory + plugin
    assert report["total"] == BR.import_bytes(recipe) <= BR.MAX_TOTAL


@pytest.mark.parametrize("slug", BR.ORDER)
def test_front_matter(slug):
    text = read(SKILLS / slug / "SKILL.md")
    assert BR.FRONT.match(text), "the platform's front-matter regex must match"
    meta, body = BR.front_matter(text)
    assert set(meta) == {"name", "description"}
    assert meta["name"] == slug and BR.SLUG.match(slug)
    assert meta["description"].startswith("Use when") and len(meta["description"]) <= BR.MAX_DESCRIPTION
    assert ": " not in meta["description"] and " #" not in meta["description"]
    assert re.search(r"^# \S", body, flags=re.M), "a '# Title' line"
    assert "\r" not in text


# ---------------------------------------------------------------- scrub
@pytest.mark.parametrize("path", sorted(p for p in SKILLS.rglob("*") if p.is_file() and "dist" not in p.parts
                                        and "__pycache__" not in p.parts), ids=lambda p: p.relative_to(SKILLS).as_posix())
def test_scrub(path):
    text = read(path)
    assert scrublist.private_hits(text) == []
    if path.suffix == ".md" and path.name != "DESIGN.md":
        assert BR.scrub_problems(path.name, text) == []


def test_the_builder_scrub_catches_secrets_and_ids():
    planted = {
        "key": "OPENROUTER key sk-or-v1-" + "ab12" * 6,
        "uuid": "job " + "-".join(["0f8fad5b", "d9cb", "469f", "a165", "70867728950e"]),
        "assign": "ARENA_" + "TOKEN=" + "abcdefgh12345",
        "profile": "--ar 16:9 --" + "p " + "q7z9x2k",
        "home": "/home/" + "someone/x",
    }
    for what, text in planted.items():
        assert BR.scrub_problems("x.md", text), what
    assert BR.scrub_problems("x.md", "--p <YOUR_PROFILE_CODE> in /home/box/sand-data and C:/Users/you") == []


def test_no_skill_asks_for_a_key_outside_the_secure_card():
    for p in SOURCES:
        text = read(p)
        if re.search(r"OPENROUTER_API_KEY|ARENA_TOKEN|HIGGSFIELD_API_KEY|_LOGIN_CODE|OAUTH_TOKEN|GEMINI_API_KEY", text):
            assert "secure" in text, f"{p.name} names a key without the secure secret card"
        assert not re.search(r"(?i)\b(paste|type|send) (me )?(your|the) (api )?(key|password)", text), p.name


def test_plugins_are_only_installed_after_a_widget():
    accounts = read(SKILLS / "setup-accounts" / "SKILL.md")
    assert "SearchPlugins" in accounts and "question widget" in accounts and "next turn" in accounts
    setup = read(SKILLS / "claudia-setup" / "SKILL.md")
    assert setup.index("question widget") < setup.index("https://claudia.gallery/mcp"), "the MCP only after a yes"
    assert "widget" in BR.front_matter(read(SKILLS / "profile.md"))[1]


# ---------------------------------------------------------------- the setup skill
def test_setup_self_checks_pins_and_installs():
    setup = read(SKILLS / "claudia-setup" / "SKILL.md")
    assert CLONE in setup and PIN in setup and SETUP in setup, "clone, pin to the skills' version, then install"
    assert setup.index(CLONE) < setup.index(PIN) < setup.index(SETUP)
    assert setup.index("Which do you have") < setup.index(CLONE), "nothing is cloned before the person's first answer"
    assert "test -f /workspace/claudia/bin/setup.sh || " + CLONE in setup, "a staged checkout is kept"
    assert "/workspace/claudia/bin/slop" in setup and "/workspace/.claudia/bin/slop" in read(SKILLS / "profile.md")
    assert ENV_LINE in read(SKILLS / "claudia-toolkit" / "SKILL.md"), "the repair after a computer update"
    assert "bash /workspace/claudia/bin/setup.sh --check --json" in setup
    welcome = read(SKILLS / "claudia-welcome" / "SKILL.md")
    line = next(ln for ln in welcome.splitlines() if "/home/box/sand-data/workflows" in ln)
    assert all(s in line for s in BR.ORDER) and f"all {len(BR.ORDER)}" in line, "the import self-check lists every skill"


def test_setup_connects_the_gallery_signs_in_and_hands_off_to_the_relay():
    """The Grok side: the claudia.gallery MCP, Opus on the box (relay setup), the person's own X sign-in, then the
    relay; the person does every sign-in."""
    setup = read(SKILLS / "claudia-setup" / "SKILL.md")
    for must in ("https://claudia.gallery/mcp", "claudia_canon", "skill setup-agents", "`slop --json relay setup`",
                 "https://grok.com/imagine", "I never type passwords", "`slop --json onboard status`",
                 "skill claudia-relay", "onboard set tier director"):
        assert must in setup, must
    for setting in ("onboard set tier", "onboard set coding-agents", "onboard set suno-plan", "onboard set mj-plan"):
        assert setting in setup, setting
    order = ["Which do you have", "## Reply 2", "## Reply 3", "## Reply 4", "## Hand-off"]
    assert [setup.index(s) for s in order] == sorted(setup.index(s) for s in order)
    profile = read(SKILLS / "profile.md")
    assert "relay, not the director" in profile and "#1 source of truth" in profile and "claudia-relay" in profile


def test_the_checklist_fields_the_setup_reads_exist(tmp_path, monkeypatch):
    """Run the setup's own onboarding commands (free, offline) and check the JSON fields the loop acts on."""
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SLOP_PROJECTS", str(tmp_path / "projects"))
    monkeypatch.delenv("SLOP_PROJECT", raising=False)
    for argv in (["onboard", "set", "tier", "director"], ["onboard", "set", "coding-agents", "claude,codex"],
                 ["onboard", "set", "suno-plan", "pro"], ["onboard", "set", "mj-plan", "none"],
                 ["onboard", "mark", "gpu", "--skip"]):
        code, res = _slop(*argv)
        assert code == 0 and res["ok"], (argv, res)
    code, res = _slop("onboard", "next", "--offline")
    assert code == 0 and res["ok"], res
    for key in ("item", "ask", "answers", "next", "record_cmd", "stuck", "all_set", "new_unlocks", "hand_off"):
        assert key in res, key
    assert {"id", "next_skill", "next_cmd"} <= set(res["item"])
    code, res = _slop("onboard", "mark", "toolkit", "--skip")
    assert code == 0 and res.get("warn"), "a required item skipped warns (the setup tells the owner)"


def test_the_checklist_names_the_onboarding_skills():
    """slop/onboard falls back to other skills until setup-accounts/-agents/-gpu ship: they ship now."""
    from slop.onboard import items
    for name in items.SKILL_FALLBACK:
        assert (SKILLS / name / "SKILL.md").is_file() and name in BR.ORDER + BR.PARKED, name
        assert items.skill(name) == name


def test_setup_agents_covers_every_engine_and_sign_in():
    from slop.agents import engines
    text = read(SKILLS / "setup-agents" / "SKILL.md")
    for e in engines.ENGINES:
        assert f"agents login {e}" in text, e
    for flag, names in (("--code-from-env", set(engines.LOGIN_CODE_ENV)),
                        ("--token-from-env", {engines.SPEC["claude"]["token_env"]}),
                        ("--key-from-env", {engines.SPEC["gemini"]["key_env"]})):
        used = set(re.findall(re.escape(flag) + r" ([A-Z_]+)", text))
        assert used and used <= names, (flag, used, names)
        assert all(f"card named {n}" in text for n in used), "each secret comes through the secure card"
    for must in ("secure secret card", "agents test ENGINE", "agents status --limits", "--for director",
                 "--pass-env GEMINI_API_KEY", "`ask_user`", "agents install all", "home-claude --done",
                 "step by step", "--check"):
        assert must in text, must
    assert "never the Director agent" in text, "Gemini is refused as director (slop agents use)"


def test_setup_gpu_covers_both_modes_and_the_pairing_rules():
    text = read(SKILLS / "setup-gpu" / "SKILL.md")
    for must in ("gpu serve", "gpu pair`", "gpu pair --refresh", "gpu pair --new", "24 h", "gpu status", "gpu unpair",
                 "gpu mode paired", "gpu direct-plan", "gpu direct-ingest JOB", "--accept-licence", "first 8 digits",
                 "--gpu require", "onboard mark gpu --skip", "slop/gpu/README.md", "only lines from your own bot",
                 "refuses while a worker is paired"):
        assert must in text, must


def test_setup_accounts_covers_every_account():
    text = read(SKILLS / "setup-accounts" / "SKILL.md")
    for must in ("OPENROUTER_API_KEY", "credit limit", "SearchPlugins", "question widget", "next turn",
                 "onboard mark higgsfield --connected", "onboard mark drive --connected", "onboard set suno-plan",
                 "suno-signin --done", "skill suno", "onboard set mj-plan", "P button",
                 "onboard apply", "mj-signin --done", "skill midjourney", "never type passwords", "ARENA_TOKEN",
                 "secure secret card"):
        assert must in text, must


def test_director_delegates_on_the_box_first():
    text = read(SKILLS / "mv-director" / "SKILL.md")
    assert text.index("agents status") < text.index("## On the box") < text.index("## On their computer")
    for must in ("deleg.mjs new auto", "deleg.mjs start JOB_DIR", "deleg.mjs wait JOB_DIR 25", "never in a loop",
                 "agents use ENGINE --for director", "skill setup-agents", "user_run_command", "CopyToBox"):
        assert must in text, must


# ---------------------------------------------------------------- commands
def code_texts(text: str) -> list[str]:
    """Inline code spans and fenced-block lines."""
    out = []
    fences = re.compile(r"^```[^\n]*\n(.*?)^```", flags=re.S | re.M)
    for m in fences.finditer(text):
        out += [ln for ln in m.group(1).splitlines() if ln.strip()]
    out += re.findall(r"`([^`\n]+)`", fences.sub("", text))
    return out


def slop_commands(text: str) -> list[list[str]]:
    """Every `slop ...` command (tokens after `slop`) inside code, split at shell operators; a bare `slop` mention
    is skipped."""
    cmds = []
    for code in code_texts(text):
        code = re.sub(r"<[^<>]*>", "x", code)                     # <text you write>
        lex = shlex.shlex(code, posix=True, punctuation_chars=";&|")
        lex.whitespace_split = True
        lex.commenters = ""                                         # a '#' inside a pick list is not a comment
        cur: list[str] = []
        for tok in [*lex, ";"]:
            if tok and set(tok) <= set(";&|"):
                if len(cur) > 1 and (cur[0] == "slop" or cur[0].endswith("/bin/slop")) and "..." not in cur:
                    cmds.append(cur[1:])                            # `slop --json ...` is a format, not a step
                cur = []
            else:
                cur.append(tok)
    return cmds


def fill(words: list[str]) -> list[str]:
    return [re.sub(r"\b[A-Z][A-Z0-9_]*\b", lambda m: FILL.get(m.group(0), "1"), w) for w in words]


def command_name(words: list[str]) -> tuple[str, ...]:
    rest, i = [], 0
    while i < len(words):
        w = words[i]
        if w in ("-p", "--project"):
            i += 2
            continue
        if not w.startswith("-"):
            rest.append(w)
        i += 1
    return tuple(rest[:2])


ALL_COMMANDS = [(p.relative_to(SKILLS).as_posix(), c) for p in SOURCES for c in slop_commands(read(p))]


def test_the_skills_name_many_commands():
    assert len(ALL_COMMANDS) > 60, len(ALL_COMMANDS)
    per_skill = {p: sum(1 for q, _ in ALL_COMMANDS if q == p) for p, _ in ALL_COMMANDS}
    assert all(per_skill.get(f"{s}/SKILL.md", 0) >= 3 for s in BR.ORDER if s != "claudia-welcome"), per_skill


def test_every_slop_command_parses_with_the_real_router():
    ap = cli.build_parser()
    bad = []
    for where, words in ALL_COMMANDS:
        if words == ["--version"]:
            continue
        argv = fill(words)
        try:
            ns = ap.parse_args(util.hoist_global_flags(argv))
            inner = list(getattr(ns, "argv", None) or [])                # `job start -- <command>`: parse that too
            if command_name(words)[:2] == ("job", "start"):
                inner = inner[1:] if inner[:1] == ["--"] else inner
                assert inner, "job start needs a command after --"
                ap.parse_args(util.hoist_global_flags(inner))
        except (SystemExit, AssertionError):
            bad.append(f"{where}: slop {' '.join(words)}")
    assert not bad, "\n".join(bad)


def test_every_step_is_json_and_names_the_project():
    bad = []
    for where, words in ALL_COMMANDS:
        if words == ["--version"]:
            continue
        if words[0] != "--json":
            bad.append(f"{where}: not `slop --json ...`: slop {' '.join(words)}")
        name = command_name(words)
        if name[:2] in PROJECTLESS_IN.get(where, ()):
            continue
        if name[:1] not in PROJECTLESS and name[:2] not in PROJECTLESS and not {"-p", "--project"} & set(words):
            bad.append(f"{where}: no -p NAME: slop {' '.join(words)}")
    assert not bad, "\n".join(bad)


def test_the_parser_check_catches_a_wrong_command():
    words = slop_commands("run `slop --json -p NAME clip launch CLIP --yes` and `slop --json -p NAME job start -- nope`")
    ap = cli.build_parser()
    with pytest.raises(SystemExit):
        ap.parse_args(util.hoist_global_flags(fill(words[0])))
    ns = ap.parse_args(util.hoist_global_flags(fill(words[1])))
    with pytest.raises(SystemExit):
        ap.parse_args(util.hoist_global_flags([w for w in ns.argv if w != "--"]))


def test_runner_and_setup_commands_exist():
    """The other commands the skills hand the bot: runner subcommands, brief templates and setup.sh flags."""
    runner = read(ROOT / "runner" / "deleg.mjs")
    runner_cmds = set(re.findall(r"case '([a-z]+)': (?:out = |return )(?:await )?cmd", runner))
    assert {"new", "run", "stop", "unpack", "doctor", "selftest", "preflight"} <= runner_cmds
    setup_flags = set(re.findall(r"^\s+(--[a-z-]+)\)", read(ROOT / "bin" / "setup.sh"), flags=re.M))
    assert {"--minimal", "--full", "--check", "--json"} <= setup_flags
    briefs = {p.stem for p in (ROOT / "templates" / "briefs").glob("*.md")}
    bad = []
    for p in SOURCES:
        text = read(p)
        for cmd in re.findall(r"deleg\.mjs\"? ([a-z_-]+)", text):
            if cmd not in runner_cmds:
                bad.append(f"{p.name}: runner command {cmd}")
        for b in re.findall(r"--brief ([a-z-]+)", text):
            if b not in briefs:
                bad.append(f"{p.name}: brief {b}")
        for line in re.findall(r"setup\.sh\"?((?: --[a-z-]+)*)", text):
            bad += [f"{p.name}: setup.sh {f}" for f in line.split() if f not in setup_flags]
    assert not bad, "\n".join(bad)


# ---------------------------------------------------------------- docs and pointers
REF = re.compile(r"((?:docs|runner|templates|bin)/[A-Za-z0-9._/-]*[A-Za-z0-9_-]\.(?:md|sh|mjs|js|json)|slop/[a-z]+/README\.md)"
                 r"|§\s*([0-9]+[a-z]?(?:\.[0-9]+[a-z]?)*|[A-M])\b")


def headings(doc: Path) -> set[str]:
    return {m.group(1).rstrip(".") for m in re.finditer(r"^#{1,4}\s+(\S+)", read(doc), flags=re.M)}


def doc_refs(text: str) -> list[tuple[str, str | None]]:
    """[(doc path, section or None)]: a bare §N belongs to the last .md path named before it."""
    out, current = [], None
    for m in REF.finditer(text):
        if m.group(1):
            path = m.group(1)
            out.append((path, None))
            if path.endswith(".md"):
                current = path
        else:
            out.append((current or "<no doc named before it>", m.group(2)))
    return out


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.relative_to(SKILLS).as_posix())
def test_every_referenced_doc_and_section_exists(path):
    bad = []
    for doc, sec in doc_refs(read(path)):
        f = ROOT / doc
        if not f.is_file():
            bad.append(f"{doc} does not exist")
        elif sec is not None and sec not in headings(f):
            bad.append(f"{doc} has no section {sec}")
    assert not bad, "\n".join(sorted(set(bad)))


def test_the_skills_point_to_docs():
    for s in BR.ORDER:
        if s in ("claudia-welcome", "claudia-setup"):
            continue
        refs = [d for d, _ in doc_refs(read(SKILLS / s / "SKILL.md")) if d.endswith(".md")]
        assert refs, f"{s} names no doc to read before acting"


def test_skill_cross_references_exist():
    names = set(BR.ORDER)
    for p in SOURCES:
        for ref in re.findall(r"\bskills? ([a-z0-9]+(?:-[a-z0-9]+)+)\b", read(p)):
            assert ref in names, f"{p.name}: skill {ref} does not exist"


def test_doc_refs_resolve_against_the_last_doc():
    refs = doc_refs("Read docs/40-storyboard.md §0 and §9.1. (§4; docs/70-motion-design.md §5). Then §10.")
    assert refs == [("docs/40-storyboard.md", None), ("docs/40-storyboard.md", "0"), ("docs/40-storyboard.md", "9.1"),
                    ("docs/40-storyboard.md", "4"), ("docs/70-motion-design.md", None),
                    ("docs/70-motion-design.md", "5"), ("docs/70-motion-design.md", "10")]
    assert "7b" in headings(ROOT / "docs/ARCHITECTURE.md") and "2.4b" in headings(ROOT / "docs/30-taste.md")
    assert doc_refs("read /workspace/claudia/slop/gpu/README.md first") == [("slop/gpu/README.md", None)]


# ---------------------------------------------------------------- shell safety and the operator's rules
@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.relative_to(SKILLS).as_posix())
def test_owner_text_is_single_quoted(path):
    """bash expands $ and ` inside double quotes: decide "caps of $20" would record "caps of 0"."""
    text = read(path)
    assert '"<' not in text, [ln for ln in text.splitlines() if '"<' in ln]
    assert BR.lint_problems(path.name, text) == []


def test_the_lint_catches_double_quoted_owner_text():
    assert BR.lint_problems("x.md", "`slop --json -p NAME decide \"<their words>\" --by owner`")
    assert BR.lint_problems("x.md", "`slop --json -p NAME decide '<their words>' --by owner`") == []


def test_clips_host_start_images_on_the_verified_tunnel():
    """Higgsfield uploads: `gen host --role start|audio --tunnel` + media_import_url (verified for both), after
    `gen tunnel status --verify` in a later call; media_upload + PUT with If-None-Match only as the fallback."""
    clips = read(SKILLS / "clips" / "SKILL.md")          # a stage guide for the production, not a template skill
    hosted = [c for c in slop_commands(clips) if command_name(c)[:2] == ("gen", "host") and "--tunnel" in c]
    assert any("--role" in c and "start" in c for c in hosted), "the start image goes on the tunnel"
    assert "media_import_url" in clips and "gen tunnel status --verify" in clips and "LATER call" in clips
    assert clips.index("media_import_url") < clips.index("media_upload") and "If-None-Match: *" in clips


def test_clips_finalize_and_the_sung_window_routing():
    clips = read(SKILLS / "clips" / "SKILL.md")
    assert "--finalize-from TAKE" in clips and "clip sync CLIP --take N" in clips and "`--again`" in clips
    assert "two OpenRouter takes" in clips and "Higgsfield 480p draft" in clips and "else cut away" in clips


def test_song_sections_example_is_only_a_format():
    """`song sections --set` replaces ALL sections: a runnable example with made-up values is a trap."""
    song = read(SKILLS / "song" / "SKILL.md")
    assert "--set 'SECTION@START,...'" in song and "EVERY section" in song
    assert not re.search(r"sections --set '[a-z]+\d*@", song)


def test_no_jq_edit_where_project_set_works():
    """`slop project set` validates and logs; jq is left only for keys it does not take (banned) and for reads."""
    bad = [f"{p.name}: {m.group(0)}" for p in SOURCES
           for m in re.finditer(r"jq [^`]*'\.(look|models|board|budget|mj|tier|lead)\b", read(p))]
    assert not bad, "use slop project set: " + "; ".join(bad)


def test_job_waits_follow_the_turn_rule():
    """A bot cannot wake itself (e2e/QUICK-E2E.md defect 1): THE TURN RULE in the profile keeps it waiting inside the
    turn (bounded waits, ~10 a turn) up to a checkpoint, else it ends on an explicit 'say continue'. Skills point to the
    rule; every wait they spell out is bounded; none waits 'until' a job ends (one frames job is ~50 waits of 25 s)."""
    profile = read(SKILLS / "profile.md")
    assert "THE TURN RULE" in profile and "`slop --json relay read --wait 200`" in profile
    assert 'Say "continue"' in profile and "up to 8 times" not in profile
    for p in SOURCES:
        text = read(p)
        assert not re.search(r"(?i)job wait ID`?\s+until", text), p.name
        for m in re.finditer(r"job wait ID([^`]*)`", text):
            assert "--max 25" in m.group(1), f"{p.name}: an unbounded job wait"


def test_the_board_prompt_field_follows_the_tier():
    """Writing img_prompt on a Midjourney board deletes mj_prompt (one plate, one generator)."""
    sb = read(SKILLS / "storyboard" / "SKILL.md")
    assert "--img-prompt" in sb and "--mj-prompt" in sb and "Never write the other one" in sb
    assert "{lead}" in sb and "{far}" in sb and "--example" in sb



# ---------------------------------------------------------------- smoke: the free commands the skills hand the bot
def _slop(*argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = cli.main(["--json", *argv])
    return code, json.loads(buf.getvalue())


@pytest.fixture()
def box(tmp_path, monkeypatch):
    """A project under SLOP_PROJECTS, with the shell somewhere else (the bot's shell is not in the project)."""
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "slophome"))
    monkeypatch.setenv("SLOP_PROJECTS", str(tmp_path / "projects"))
    monkeypatch.delenv("SLOP_PROJECT", raising=False)
    (tmp_path / "elsewhere").mkdir()
    monkeypatch.chdir(tmp_path / "elsewhere")
    code, res = _slop("new", "demo", "--tier", "studio")
    assert code == 0 and res["ok"], res
    return tmp_path / "projects" / "demo"


def test_smoke_studio_caps_and_lead_plates_before_a_board(box, tmp_path):
    """Studio stage 5 runs beside stages 2-4, before any board: ingest one file per lead plate, then the sheet."""
    pil = pytest.importorskip("PIL.Image")
    proj = json.loads((box / "project.json").read_text(encoding="utf-8"))
    assert proj["budget"]["openrouter_usd"] == 100 and proj["budget"]["higgsfield_credits"] == 1500
    keys = ["lead-cu", "lead-mcu", "lead-fs", "lead-ws"]
    for k in keys:
        f = tmp_path / "dl" / f"{k}.png"
        f.parent.mkdir(exist_ok=True)
        pil.new("RGB", (64, 36), (200, 100, 50)).save(f)
        code, res = _slop("-p", "demo", "plates", "ingest", str(f), "--plate", k)
        assert code == 0 and res["ok"], res
    code, res = _slop("-p", "demo", "plates", "sheet", "--plates", ",".join(keys))
    assert code == 0 and res["ok"], res
    code, res = _slop("-p", "demo", "plates", "status")
    assert not res["ok"] and "storyboard" in res["error"], "plates status/book need a board (the skill says so)"


def test_smoke_lead_none_needs_lead_min(box):
    code, res = _slop("-p", "demo", "lead", "--none", "--by", "owner")
    assert code == 0 and res["ok"] and "lead_min" in res["text"]
    assert "project set board.lead_min 0" in read(SKILLS / "mv-quick" / "SKILL.md")
    code, res = _slop("-p", "demo", "project", "set", "board.lead_min", "0")
    assert code == 0 and res["ok"], res


def test_smoke_caps_go_down_freely_and_up_only_with_the_owner(box):
    """The setup's 'other numbers' line: a raise needs --owner-ok --by owner (the setup and mv-quick say so)."""
    code, res = _slop("-p", "demo", "project", "set", "budget.openrouter_usd", "150")
    assert not res["ok"]
    code, res = _slop("-p", "demo", "project", "set", "budget.openrouter_usd", "150", "--owner-ok", "--by", "owner")
    assert code == 0 and res["ok"], res
    code, res = _slop("-p", "demo", "project", "set", "budget.openrouter_usd", "90")
    assert code == 0 and res["ok"], res
    for s in ("mv-quick",):
        assert "--owner-ok --by owner" in read(SKILLS / s / "SKILL.md"), s


@pytest.mark.skipif(not shutil.which("bash"), reason="needs bash")
def test_smoke_single_quoted_owner_words_survive_the_shell(box, tmp_path):
    words = "caps of $20, `x` and a 'quote'"
    quoted = "'" + words.replace("'", r"'\''") + "'"                    # the profile's rule: ' -> '\''
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    r = subprocess.run(["bash", "-c", f"{shlex.quote(sys.executable)} -m slop --json -p demo decide {quoted} --by owner"],
                       env=env, cwd=tmp_path / "elsewhere", capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert words in (box / "DECISIONS.md").read_text(encoding="utf-8")

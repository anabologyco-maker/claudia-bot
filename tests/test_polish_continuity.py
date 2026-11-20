"""Locks for the continuity polish after the live Quick run inside a real Grok Bot (e2e/QUICK-E2E.md, PASS: v1 for
$1.06, lyric gate 74/74, 13 user turns, 1 % -> 4 % of a Pro+ week incl. the install):

1. a bot cannot wake itself: THE TURN RULE lives once in the profile (bounded `job wait --max 25`, about 10 a turn, up
   to a checkpoint; else an explicit 'say continue'); every skill that starts a long job points to it. Since the live
   Studio run (e2e/STUDIO-E2E.md) the continue line goes out FIRST, before any wait over ~2 min, because the platform
   ends a turn silently ~5-6 min into a long call (tests/test_studio_skills.py);
2. usage claims are the measured ones (about 0.25 % of a Pro+ week a reply; Quick 10-15 replies);
3. the setup probes the toolkit before announcing an install;
4. a bare "continue" names what it approves;
5. Quick runs with no key at all (GenerateImage stills, no clips); Studio needs OpenRouter or Higgsfield;
6. the approved lead close-up anchors every later lead plate. Review fixes: the lead batch runs alone (`gen image
   --jobs --only`; a full book written while the board waited holds every plate), and the anchored book is the FULL
   book (`gate prompts --approve` needs plates/prompts.md; a --missing/--only book is a subset, prompts-B.md); the
   turn rule keeps dependent steps waiting ("meanwhile only work that does not need it").

The skills sit a few bytes under their budgets, so a later trim must not silently undo any of these. No network.
"""
from __future__ import annotations

import importlib.util
import io
import json
import re
import shlex
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
sys.path.insert(0, str(ROOT))

from slop import cli, util  # noqa: E402

_spec = importlib.util.spec_from_file_location("build_recipe_polish", SKILLS / "build_recipe.py")
BR = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(BR)

SKILL = {s: SKILLS / s / "SKILL.md" for s in BR.ORDER + BR.PRODUCTION + BR.PARKED}
SOURCES = (list(SKILL.values()) + [SKILLS / "profile.md", SKILLS / "memory.md"]
           + sorted((SKILLS / "routines").glob("*.md")))


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def profile() -> str:
    return BR.front_matter(read(SKILLS / "profile.md"))[1]


def line_with(text: str, needle: str) -> str:
    return next(ln for ln in text.splitlines() if needle in ln)


def parses(*argv: str) -> bool:
    try:
        cli.build_parser().parse_args(util.hoist_global_flags(list(argv)))
    except SystemExit:
        return False
    return True


def _slop(*argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = cli.main(["--json", *argv])
    return code, json.loads(buf.getvalue())


# ---------------------------------------------------------------- 1. turn continuity
def test_the_profile_carries_the_turn_rule_once():
    prof = profile()
    assert prof.count("THE TURN RULE") == 1
    rule = line_with(prof, "THE TURN RULE")
    for must in ("only the claudia-wake routine wakes you", "never say \"I'll come back\"", "checkpoint", "a question for the person",
                 "a failure", "done", "`slop --json relay read --wait 200`", "before any wait over ~2 min",
                 "FIRST post the status and the time left", 'Say "continue" and I carry on', "the result first",
                 "Never poll with routines"):
        assert must in rule, must
    assert rule.index('Say "continue" and I carry on') < rule.index("relay read --wait 200"), "the line before the wait"
    for slug, p in SKILL.items():                                  # referenced, never restated (budget, one truth)
        text = read(p)
        assert "THE TURN RULE:" not in text and "about 10 waits" not in text and "cannot wake" not in text, slug


def test_the_turn_rule_keeps_dependent_steps_waiting():
    """The old rule said 'next step only when the job is done'; 'free work between' alone lets a weaker model start
    `render encode` while `render frames` still runs, or the board while `analyze` runs."""
    rule = line_with(profile(), "THE TURN RULE")
    assert "meanwhile only work that does not need it" in rule
    assert "free work between" not in rule
    assert "Start a step only when the one before is done" in read(SKILL["render-and-review"])


def test_every_once_per_turn_poll_ends_on_the_continue_line():
    """A poll the skill allows only once a turn (runner jobs, local-exec GPU bundles) must say how that turn ends."""
    for slug, p in SKILL.items():
        for ln in read(p).splitlines():
            if "once per turn" in ln:
                assert '"continue"' in ln, f"{slug}: {ln[:120]}"


def test_the_turn_rule_matches_the_job_command(monkeypatch):
    """--max is a real flag of `job wait` and 25 s is its default (under the bot shell's foreground limit)."""
    from slop import job
    monkeypatch.delenv("SLOP_WAIT_MAX", raising=False)
    assert job.default_wait() == 25
    ns = cli.build_parser().parse_args(util.hoist_global_flags(["--json", "-p", "demo", "job", "wait", "j1", "--max",
                                                                 "25"]))
    assert ns.max == 25


def test_no_skill_promises_to_come_back():
    promise = re.compile(r"(?i)\bI(?:'|’)?ll (?:come|get|check|report) back|\bI will (?:come|get|check) back"
                         r"|\bI(?:'|’)?ll (?:let you know|ping you)|\bcomes when the install ends")
    for p in SOURCES:
        for ln in read(p).splitlines():
            if promise.search(ln):
                assert p.name == "profile.md" and 'never say "I\'ll come back"' in ln, f"{p.name}: {ln[:120]}"


def test_every_skill_that_starts_a_long_job_points_to_the_turn_rule():
    long_job = re.compile(r"job start -- |deleg\.mjs start|jobs_wait|gpu install|agents install|taste embed")
    for slug, p in SKILL.items():
        text = read(p)
        if long_job.search(text):
            assert "turn rule" in text, f"{slug} starts a long job but never points to the profile's turn rule"


def test_no_turn_ends_without_the_continue_line():
    """'end the turn', 'when they write' or 'again next turn' left the owner guessing (5 nudges in the live run)."""
    vague = re.compile(r"(?i)end the turn|when they (?:next )?(?:write|speak)|check when they|again next turn")
    for p in SOURCES:
        hits = [ln[:100] for ln in read(p).splitlines() if vague.search(ln)]
        assert not hits, f"{p.name}: {hits}"
    for slug in ("mv-director", "setup-gpu", "setup-agents", "render-and-review"):
        assert '"continue"' in read(SKILL[slug]), f"{slug}: an owner-side wait names the word to say"


def test_the_runner_wait_stays_once_per_turn():
    """A Director workflow job runs 1-3 hours: ten waits would not finish it, so the turn ends on the continue line."""
    d = read(SKILL["mv-director"])
    step = line_with(d, "deleg.mjs wait JOB_DIR 25")
    assert "1-3 hours" in step and 'say "continue"' in step and "once per turn, never in a loop" in step


def test_render_waits_inside_the_turn_and_records_long_runs():
    r = read(SKILL["render-and-review"])
    intro = line_with(r, "Long steps are jobs")
    assert "turn rule" in intro and "runs add ID --kind render" in intro and "new chat can resume" in intro
    excerpt = line_with(r, "out/draft.mp4")
    assert 'Say "continue" and I render the rest' in excerpt and "go on to v1" in excerpt
    assert "(Default: yes, I render the rest.)" not in r, "a default the bot cannot act on without a new turn"


# ---------------------------------------------------------------- 2. usage honesty
STALE = re.compile(r"1\s*[-–]\s*2 ?% (?:of a|a reply|per)|15\s*[-–]\s*25 (?:repl|turn)|1\.5 ?% of a Pro|"
                   r"installing 15|Install, detached \(15")


def test_usage_claims_are_the_measured_ones():
    for p in SOURCES + [SKILLS / "DESIGN.md"]:
        assert not STALE.search(read(p)), f"{p.name}: a pre-measurement usage or install claim"
    line = line_with(profile(), "weekly pool")
    for must in ("0.25 % of a Pro+ week a reply", "measured", "You only relay"):
        assert must in line, must
    desc = BR.front_matter(read(SKILL["mv-quick"]))[0]["description"]
    assert "10-15 replies" in desc and "$0-20" in desc
    design = read(SKILLS / "DESIGN.md")
    assert "≈0.25 % of a Pro+ week per reply" in design and "~10–15 replies (13 measured" in design


# ---------------------------------------------------------------- 3. setup: probe before installing
def test_setup_probes_the_toolkit_before_announcing_an_install():
    setup = read(SKILL["claudia-setup"])
    r2 = setup[setup.index("## Reply 2"):setup.index("## Reply 3")]
    probe = "`bash /workspace/claudia/bin/setup.sh --check --json`"
    assert probe in r2 and r2.index(probe) < r2.index("nohup setsid"), "probe first"
    step = line_with(r2, probe)
    assert '"toolkit ready"' in step and "(no install)" in step and "`profile` full" in step
    assert "15-25" not in setup and "installing, about 5 min" in step
    welcome = read(SKILL["claudia-welcome"])
    assert "5 min" not in welcome[:welcome.index("**My skills**")], "the welcome never promises an install time"
    sh = read(ROOT / "bin" / "setup.sh")
    assert '"profile": prof' in sh and '"ok": not miss' in sh, "the fields the probe reads"


# ---------------------------------------------------------------- 4. "continue" names what it approves
def test_a_bare_continue_names_what_it_approves():
    assert "Silence is never a yes" in profile()
    relay = read(SKILL["claudia-relay"])                       # the relay sends every answer word for word: Opus,
    assert 'even "yes" or "B": step 1, word for word.' in relay   # not Grok, names what it approves


def test_trims_for_the_turn_rule_kept_the_safety_rules():
    """Room for the turn rule came from trims; ARCHITECTURE §7 rule 9 (browser assist only after the owner's opt-in
    and their own sign-in) and rule 5 (inputs in colour, grade in post) stay in the always-loaded profile."""
    prof = profile()
    five = line_with(prof, "5. Every job is yours")
    assert "Midjourney" in five and "Suno" in five and "never the person's" in five
    assert "never alter it to get it through" in line_with(prof, "4. Claudia stays herself")
    allowed = line_with(read(SKILL["clips"]), "Declined by a face filter")   # trimmed from the profile for the Studio
    assert "never alter it" in allowed and "Allowed: the same image on the other provider" in allowed   # rules
    six = line_with(prof, "6. Nothing goes public")
    assert "AI label" in six and "never as anabology" in six and "without the person's yes" in six
    assert "/workspace/claudia" in line_with(prof, "- Toolkit `slop`")


# ---------------------------------------------------------------- 5. Quick with no key; Studio needs a video route
def test_quick_runs_with_no_key_at_all():
    q = read(SKILL["mv-quick"])
    nokey = line_with(q, "No key at all")
    for must in ("their own song file", "GenerateImage", "motion clips only from Grok Imagine", "clip ingest CLIP --file",
                 "or none (2.5D and devices",
                 "`slop --json -p NAME project set budget.motion_s 0` before the board", 'no "say so" checks'):
        assert must in nokey, must
    gi = line_with(q, "No key, GenerateImage")
    assert "uploads/gen/PLATE/K.png" in gi and "`slop --json -p NAME plates ingest uploads/gen`" in gi
    assert "plates/cands/PLATE/K.png" not in gi, "ingest refuses plates/cands/ itself (the candidates)"
    for must in ("in place of `gen image`", "per plate of the step without candidates", "`prompt` (16:9)", "`refs`",
                 "plates/jobs.json"):
        assert must in gi, must                    # jobs.json, not a book: subset books are plates/prompts-B.md
    assert q.index("No key at all") < q.index("1. Song"), "said before the steps, so the board is drafted right"
    acc = read(SKILL["setup-accounts"])
    assert "Grok Imagine" in acc and "no sung lip-sync clips" in acc
    assert "Needs an OpenRouter key or the Higgsfield connector" in read(SKILL["mv-studio"])
    assert "(needs OpenRouter or Higgsfield)" in line_with(q, "Promote later")
    pl = read(SKILL["plates"])
    assert "from GenerateImage (no key): saved as uploads/gen/PLATE/K.png" in pl and "plates ingest uploads/gen" in pl


def test_smoke_a_no_key_quick_project_gets_no_clip_budget(tmp_path, monkeypatch):
    """The no-key line's command runs on a fresh Quick project without the owner flag (it only lowers a budget)."""
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SLOP_PROJECTS", str(tmp_path / "projects"))
    monkeypatch.delenv("SLOP_PROJECT", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    (tmp_path / "elsewhere").mkdir()
    monkeypatch.chdir(tmp_path / "elsewhere")
    code, res = _slop("new", "demo", "--tier", "quick")
    assert code == 0 and res["ok"], res
    code, res = _slop("-p", "demo", "project", "set", "budget.motion_s", "0")
    assert code == 0 and res["ok"], res
    proj = json.loads((tmp_path / "projects" / "demo" / "project.json").read_text(encoding="utf-8"))
    assert proj["budget"]["motion_s"] == 0
    from slop.board.common import motion_budget_s
    assert motion_budget_s(proj) == 0.0


def test_smoke_generate_image_stills_reach_the_picking_sheet(tmp_path, monkeypatch):
    """Run the skill's no-key stills line as the bot would: each image saved where it says, then its ingest command
    from the bot's own folder (not the project's); the sheet and the picks then see exactly one candidate per image."""
    pil = pytest.importorskip("PIL.Image")
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SLOP_PROJECTS", str(tmp_path / "projects"))
    monkeypatch.delenv("SLOP_PROJECT", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    code, res = _slop("new", "demo", "--tier", "quick")
    assert code == 0 and res["ok"], res
    proj = tmp_path / "projects" / "demo"
    shots = [{"id": "s001", "t0": 0, "t1": 2, "plate": "lead-cu", "lead_on_screen": True, "framing": "CU",
              "img_prompt": "CU of {lead} in a hall"},
             {"id": "s002", "t0": 2, "t1": 4, "plate": "p002", "lead_on_screen": False, "framing": "WS",
              "img_prompt": "WS of an empty hall"}]
    (proj / "board").mkdir(exist_ok=True)
    (proj / "board" / "shots.json").write_text(json.dumps({"version": 1, "duration": 4, "chapters": [], "seedance": [],
                                                           "plates": [], "shots": shots}), encoding="utf-8")
    line = line_with(read(SKILL["mv-quick"]), "No key, GenerateImage")
    save = re.search(r"save each image as /workspace/slop/projects/NAME/(\S+?\.png)", line).group(1)
    ingest = re.search(r"`(?:cd /workspace/slop/projects/NAME && )?slop --json -p NAME (plates ingest[^`]*)`",
                       line).group(1)
    for n, plate in enumerate(("lead-cu", "p002")):
        f = proj / re.sub(r"\bK\b", "1", re.sub(r"\bPLATE\b", plate, save))
        f.parent.mkdir(parents=True, exist_ok=True)
        pil.new("RGB", (64, 36), (200, 100 + n * 50, 50)).save(f)
    (tmp_path / "elsewhere").mkdir()
    monkeypatch.chdir(tmp_path / "elsewhere")
    code, res = _slop("-p", "demo", *shlex.split(ingest))
    assert code == 0 and res["ok"], res
    from slop.board import plates
    for plate in ("lead-cu", "p002"):
        have = sorted(f.name for f in (proj / "plates/cands" / plate).iterdir())
        assert len(plates._cands(proj, plate)) == 1, (plate, have)
    code, res = _slop("-p", "demo", "plates", "pick", "--all-first")
    assert code == 0 and res["ok"], res


# ---------------------------------------------------------------- 6. the identity anchor
def test_lead_plates_are_anchored_on_the_approved_close_up():
    q = read(SKILL["mv-quick"])
    lead = line_with(q, "- Lead: 4 plates")
    assert "`slop --json -p NAME gen image --jobs --only K1,K2,K3,K4 --quality medium`" in lead, \
        "the lead batch runs alone: a full book written while the board waited holds every plate"
    g3 = lead[lead.index("G3:"):]
    assert "`slop --json -p NAME plates book`" in g3
    assert "`slop --json -p NAME gen image --jobs --missing --quality medium`" in g3
    on_yes = line_with(q, "- On yes:")
    order = ["`slop --json -p NAME plates pick PLATE K`", "`slop --json -p NAME plates book --anchor PLATE`",
             "`slop --json -p NAME gate prompts --approve --note '<their words>'`", "that `gen image` with `--yes`"]
    assert all(s in on_yes for s in order) and [on_yes.index(s) for s in order] == sorted(on_yes.index(s) for s in order)
    assert "--missing --anchor" not in q, "a --missing book is a subset (plates/prompts-B.md): the G5 gate refuses"
    assert "anchored jobs with the close-up as reference" in line_with(q, "generate_image_batch")
    pl = read(SKILL["plates"])
    anchor = line_with(pl, "Identity anchor")
    assert "plates pick PLATE K" in anchor and "plates book --anchor PLATE` (the full book" in anchor
    assert "`gen image --jobs --missing`" in anchor and "`--ref PLATE:K`" in anchor and "--only K1,K2,K3,K4" in anchor
    assert "--missing --anchor" not in pl


def _cmds(line: str) -> list[str]:
    """The `slop --json -p NAME ...` commands of one skill line, in order (what follows `-p NAME`)."""
    return re.findall(r"`slop --json -p NAME ([^`]+)`", line)


def test_smoke_the_skill_stills_steps_in_order(tmp_path, monkeypatch):
    """mv-quick step 7 exactly as written, on a project whose FULL plate book was written while the board waited
    (skill storyboard step 7 says so, and `slop next` does it): the lead batch plans only the 4 test plates; the G3
    message's estimate skips them; on yes the pick, the anchored full book and the G5 gate all succeed (the gate needs
    plates/prompts.md, which a --missing subset book never writes), and the dry run then sends the approved close-up
    with every lead plate still to make. Dry runs only: nothing is generated or spent."""
    pil = pytest.importorskip("PIL.Image")
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SLOP_PROJECTS", str(tmp_path / "projects"))
    monkeypatch.delenv("SLOP_PROJECT", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    (tmp_path / "elsewhere").mkdir()
    monkeypatch.chdir(tmp_path / "elsewhere")
    assert _slop("new", "demo", "--tier", "quick")[0] == 0
    assert _slop("-p", "demo", "lead", "--canon", "a woman, 30, orange streak in black hair, grey parka",
                 "--far", "a woman in a grey parka")[0] == 0
    proj = tmp_path / "projects" / "demo"
    spec = [("lead-cu", "CU", True), ("lead-mcu", "MCU", True), ("lead-fs", "FS", True), ("lead-ws", "WS", True),
            ("hall-ws", "WS", False), ("lead-ms", "MS", True)]
    shots = [{"id": f"s{i + 1:03d}", "t0": 2 * i, "t1": 2 * i + 2, "plate": pl, "lead_on_screen": lead, "framing": fr,
              "img_prompt": ("close-up of {lead} in a hall" if fr in ("CU", "MCU", "MS") else
                             "wide shot of {far} crossing a hall" if lead else "wide shot of an empty hall")}
             for i, (pl, fr, lead) in enumerate(spec)]
    (proj / "board").mkdir(exist_ok=True)
    (proj / "board" / "shots.json").write_text(json.dumps({"version": 1, "duration": 12, "chapters": [], "seedance": [],
                                                           "plates": [], "shots": shots}), encoding="utf-8")
    assert _slop("-p", "demo", "plates", "book")[0] == 0                # the free work while the board waited
    leads = "lead-cu,lead-mcu,lead-fs,lead-ws"
    fill = {"K1,K2,K3,K4": leads, "PLATE": "lead-cu", " K": " 2", "'<their words>'": "'yes, CU 2 is her, go'"}

    def run(cmd: str) -> dict:
        for k, v in fill.items():
            cmd = cmd.replace(k, v)
        code, res = _slop("-p", "demo", *shlex.split(cmd))
        assert code == 0 and res["ok"], (cmd, res)
        return res

    def planned(res: dict) -> set[str]:
        return {r["plate"] for r in res["jobs"] if not r.get("skip")}

    q = read(SKILL["mv-quick"])
    lead_line, on_yes = line_with(q, "- Lead: 4 plates"), line_with(q, "- On yes:")
    seen = []
    for cmd in _cmds(lead_line):
        if cmd.startswith("plates sheet"):                              # the owner said yes: the 4 test plates exist
            for n, plate in enumerate(leads.split(",")):
                for k in (1, 2):
                    f = proj / "uploads" / "gen" / plate / f"{k}.png"
                    f.parent.mkdir(parents=True, exist_ok=True)
                    pil.new("RGB", (64, 36), (40 * n, 60 * k, 90)).save(f)
            assert _slop("-p", "demo", "plates", "ingest", "uploads/gen")[0] == 0
        res = run(cmd)
        seen.append(cmd.split(" --")[0])
        if cmd.startswith("gen image") and "--only" in cmd:
            assert res["dry_run"] and planned(res) == set(leads.split(",")), "the lead batch runs alone (before G3)"
        elif cmd.startswith("gen image"):
            assert res["dry_run"] and planned(res) == {"hall-ws", "lead-ms"}, "the G5 estimate skips the made plates"
    assert seen == ["plates book", "gen image", "plates sheet", "plates book", "gen image"], seen
    for cmd in _cmds(on_yes):
        res = run(cmd)
        if cmd.startswith("gate prompts"):
            assert "approved" in res["text"]
    assert (proj / "plates" / "prompts.md").is_file(), "the G5 book the owner read"
    res = run(re.search(r"`slop --json -p NAME (gen image --jobs --missing[^`]*)`", lead_line).group(1))
    assert planned(res) == {"hall-ws", "lead-ms"} and res.get("anchored") == ["lead-ms"]
    jobs = {j["plate"]: j for j in json.loads((proj / "plates" / "jobs.json").read_text(encoding="utf-8"))["jobs"]}
    assert jobs["lead-ms"]["anchor"] == "lead-cu:2" and (proj / jobs["lead-ms"]["refs"][0]).is_file(), \
        "GenerateImage (no key) takes this `refs` path as its reference image"
    assert not jobs["hall-ws"].get("refs") and "anchor" not in jobs["lead-cu"]
    assert _slop("-p", "demo", "plates", "pick", "--all-first")[0] == 0   # "you pick" keeps the owner's G3 choice
    assert json.loads((proj / "plates" / "picks.json").read_text(encoding="utf-8"))["lead-cu"]["cand_k"] == 2


def test_the_old_subset_book_order_cannot_record_g5(tmp_path, monkeypatch):
    """Why the skill books the FULL book after G3: with only subset books (--only, then --missing) there is no
    plates/prompts.md and `gate prompts --approve` refuses."""
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SLOP_PROJECTS", str(tmp_path / "projects"))
    monkeypatch.delenv("SLOP_PROJECT", raising=False)
    assert _slop("new", "demo", "--tier", "quick")[0] == 0
    proj = tmp_path / "projects" / "demo"
    shots = [{"id": "s001", "t0": 0, "t1": 2, "plate": "p001", "lead_on_screen": False, "framing": "WS",
              "img_prompt": "wide shot of an empty hall"}]
    (proj / "board").mkdir(exist_ok=True)
    (proj / "board" / "shots.json").write_text(json.dumps({"version": 1, "duration": 2, "chapters": [], "seedance": [],
                                                           "plates": [], "shots": shots}), encoding="utf-8")
    code, res = _slop("-p", "demo", "plates", "book", "--missing")
    assert code == 0 and res["subset"] and res["book"] != "plates/prompts.md"
    code, res = _slop("-p", "demo", "gate", "prompts", "--approve", "--note", "go")
    assert not res["ok"] and "plates/prompts.md" in res["error"]


def test_the_anchor_flags_are_the_shipped_ones():
    assert parses("--json", "-p", "demo", "plates", "book", "--anchor", "lead-cu")
    assert parses("--json", "-p", "demo", "plates", "book", "--anchor", "lead-cu:2")
    assert parses("--json", "-p", "demo", "gen", "image", "--jobs", "--only", "a,b,c,d", "--quality", "medium")
    assert parses("--json", "-p", "demo", "gen", "image", "--jobs", "--missing", "--quality", "medium", "--yes")
    assert parses("--json", "-p", "demo", "gen", "image", "a prompt", "--plate", "p004", "--ref", "lead-cu:2")
    assert not parses("--json", "-p", "demo", "plates", "book", "--anchor-plate", "lead-cu")

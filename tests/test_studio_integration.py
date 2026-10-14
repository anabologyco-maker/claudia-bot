"""Studio-run fix round, integration: the five tracks (sung, plates, engine, skills, ledger) agree with each other.

- the short sung template has ONE wording: templates.SHORT_TEMPLATE / SHORT_RULE / SHORT_CLOSER are what docs/60 §4.0
  and §5 ship, what `clip new` drafts (slots aside), what skills/clips step 2 quotes, what the prompt-book brief gives
  the Director-tier writer, and what the lock warning and the sync `first:` line say;
- `slop clip new SHOT --kind sung` (every board-audit clip_cmd) drafts the short form through the CLI too;
- nothing left describes every clip as a screenplay (board draft, core status, the prompt-book brief), and
  ARCHITECTURE §7b routes a sung window short form first;
- a refused or failed Higgsfield finalize puts the clip back to delivered on its draft (no re-lock advice: that would
  buy a new draft; the start image is not declined by it), and `ingest --failed` takes an OpenRouter take's $ estimate
  off the log as it does a Higgsfield take's credits;
- a board changed after approval points at the skills' own re-approval command (`board approve --note`)."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import re
import sys
from pathlib import Path

import pytest

_H = Path(__file__).parent / "fixtures" / "gen" / "helpers.py"
_spec = importlib.util.spec_from_file_location("gen_test_helpers", _H)
H = importlib.util.module_from_spec(_spec); sys.modules.setdefault("gen_test_helpers", H); _spec.loader.exec_module(H)
H = sys.modules["gen_test_helpers"]

from slop import core_cli, ledger  # noqa: E402
from slop.cli import main  # noqa: E402
from slop.gen import clips, store, templates as tpl  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
DRAFT_JOB = "0f8fad5b-d9cb-469f-a165-70867728950e"


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def flat(s: str) -> str:
    return " ".join(s.split())


def fenced(s: str) -> list[str]:
    return [b.strip() for b in re.findall(r"```[a-z]*\n(.*?)```", s, flags=re.S)]


def line_with(text: str, needle: str) -> str:
    return next(ln for ln in text.splitlines() if needle in ln)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SLOP_PROJECTS", str(tmp_path / "projects"))
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-test-not-a-real-key")
    monkeypatch.delenv("SLOP_PROJECT", raising=False)
    monkeypatch.delenv("SLOP_FREE_ONLY", raising=False)
    H.write_cache(tmp_path / "home")
    return H.make_project(tmp_path / "projects")


def run(pdir, *argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(["--json", "--project", str(pdir), *argv])
    return rc, json.loads(buf.getvalue())


# ------------------------------------------------------------------------------------------------ one wording
def test_the_short_template_is_one_block_everywhere():
    t = tpl.SHORT_TEMPLATE
    assert t.split("\n")[0] == tpl.HEAD.format(words="<every word in the window>") + "."
    assert t.split("\n")[1] == tpl.SHORT_LINE and t.split("\n")[-1] == tpl.SHORT_CLOSER
    assert tpl.SHORT_CLOSER == "One continuous shot, no cuts, no head turns. Only she sings. No text, letters or logos."
    d60 = read(DOCS / "60-clips.md")
    assert fenced(d60).count(t) == 2, "docs/60 ships the block verbatim in §4.0 and §5"
    sec40 = d60[d60.index("### 4.0"):d60.index("### 4.1")]
    sec5 = d60[d60.index("## 5. Templates"):d60.index("## 6. Providers")]
    assert t in fenced(sec40) and t in fenced(sec5)
    assert tpl.SHORT_RULE in flat(sec40)
    book = read(ROOT / "templates" / "briefs" / "prompt-book.md")
    generic = (t.replace("She lip-syncs", "<Lead pronoun> <lip-syncs/lip-sync>")
               .replace("of the woman", "of <lead noun>")
               .replace("<how she sings the words>", "<how the lead sings the words>")
               .replace("Only she sings.", "Only <lead pronoun> <sings/sing>."))
    assert generic in fenced(book) and tpl.SHORT_RULE in flat(book)
    assert "configured noun/possessive" in book and "--allow-turn" in book
    assert t in read(ROOT / "slop" / "gen" / "templates.py").replace("\n                ", "\n"), "the module doc"


def test_the_draft_is_the_template_with_slots():
    lead = tpl.lead_words({"lead": {"canon": "black bob, one orange streak"}})
    p = tpl.sung_prompt(words="Sit up, darling", phrases=[], t0=0, duration=4, shot={}, lead=lead, kicks=[], downbeats=[])
    lines = p.split("\n")
    assert lines[0] == tpl.HEAD.format(words="Sit up, darling") + "." and lines[-1] == tpl.SHORT_CLOSER
    generic = re.sub(r"^\[\[framing[^\]]*\]\]", "<Framing>", lines[1])
    generic = generic.replace("(black bob, one orange streak)", "(<canon tags>)")
    generic = re.sub(r"\[\[how she sings the words[^\]]*\]\]", "<how she sings the words>", generic)
    generic = re.sub(r"\[\[Light[^\]]*\]\]", "<Light>", generic).replace("Locked camera.", "<Camera>.")
    assert generic == tpl.SHORT_LINE
    assert len(lines) == 3, "the 2 optional beat lines are the writer's (times in draft_notes)"


def test_the_clips_skill_quotes_the_same_words():
    step = line_with(read(ROOT / "skills" / "clips" / "SKILL.md"), "2. Timing for each clip")
    sung = step[step.index("Sung clips:"):step.index("Motion clips:")]
    assert tpl.SHORT_RULE in sung and tpl.SHORT_CLOSER.replace("Only she sings.", "Only <lead pronoun> <sings/sing>.") in sung
    assert f"about {tpl.SHORT_MAX_WORDS} words" in sung and f"at most {tpl.SHORT_MAX_BEATS} timed beats" in sung
    design = flat(read(ROOT / "skills" / "DESIGN.md"))
    assert tpl.SHORT_RULE in design and tpl.SHORT_CLOSER.replace("Only she sings.", "Only <lead pronoun> <sings/sing>.") in design


def test_the_code_says_the_same_rule():
    long = tpl.HEAD.format(words="Go") + ". " + " ".join(["word"] * 120)
    assert tpl.SHORT_RULE in tpl.sung_length_warning(long) and "configured lead pronoun" in tpl.sung_length_warning(long)
    first = clips.short_first({"id": "W01", "kind": "sung", "body": {"prompt": long}}, .1, False)
    assert tpl.SHORT_RULE in first
    assert "framing/light" not in read(ROOT / "slop" / "gen" / "clips.py")


# ------------------------------------------------------------------------------------------------ the CLI default
def test_cli_clip_new_drafts_by_kind(env):
    rc, out = run(env, "clip", "new", "s002", "--kind", "sung")
    assert rc == 0 and out["clip"]["draft_notes"]["style"] == "short", out
    assert out["clip"]["body"]["prompt"].endswith(tpl.SHORT_CLOSER) and tpl.SHORT_RULE in out["text"]
    rc, out = run(env, "clip", "new", "s004", "--kind", "motion")
    assert rc == 0 and out["clip"]["draft_notes"]["style"] == "screenplay"
    rc, out = run(env, "clip", "new", "s003", "--kind", "sung", "--style", "screenplay")
    assert rc == 0 and out["clip"]["draft_notes"]["style"] == "screenplay" and "--style short" in out["text"]


# ------------------------------------------------------------------------------------------------ no "every clip a screenplay"
def test_nothing_describes_every_clip_as_a_screenplay():
    from slop.board import draft
    nxt = draft.clip_next(Path("demo"), "c01")
    assert "short sung form" in nxt and "timed screenplay" in nxt
    assert "gen drafts the timed screenplay with" not in read(ROOT / "slop" / "board" / "draft.py")
    assert "(a screenplay, docs/60-clips)" not in read(ROOT / "slop" / "core_cli.py")
    book = read(ROOT / "templates" / "briefs" / "prompt-book.md")
    assert "screenplay video prompts for every motion and sung clip" not in book
    assert "screenplay for acting and motion, short for copy" in flat(book)
    arch = read(DOCS / "ARCHITECTURE.md")
    s7b = flat(arch[arch.index("## 7b."):arch.index("## 8.")])
    assert "short form first" in s7b and "2 OpenRouter non-copies of the short form" in s7b
    assert s7b.index("short form first") < s7b.index("2 OpenRouter non-copies of the short form")
    assert "after 2 OpenRouter non-copies on a window → Higgsfield" not in s7b


# ------------------------------------------------------------------------------------------------ finalize ingest
DRAFT = {"n": 1, "provider": "higgsfield", "status": "delivered", "file": "clips/W01/take-1.mp4", "id": DRAFT_JOB,
         "submitted": "2026-10-02T07:10:00", "credits": 12, "body": {"resolution": "480p", "draft": True}}


def _finalize_requested(pdir: Path) -> dict:
    c = {"id": "W01", "kind": "sung", "status": "submitted", "provider": "higgsfield", "start": "plates/x.png",
         "body": {"prompt": "p", "duration": 4}, "declined": [],
         "takes": [dict(DRAFT), {"n": 2, "provider": "higgsfield", "status": "requested", "finalize_of": 1,
                                 "credits_est": 48, "id": None, "submitted": "2026-10-02T07:40:00",
                                 "model": "seedance_2_5", "needs_sync": True}]}
    store.save(pdir, c)
    ledger.record(pdir, provider="higgsfield", model="seedance_2_5", kind="video-finalize", credits=48,
                  status="submitted", units={"clip": "W01", "take": 2, "finalize_of": 1})
    return c


@pytest.mark.parametrize("flag", ["--failed", "--declined"])
def test_a_refused_finalize_leaves_the_clip_on_its_draft(env, flag):
    _finalize_requested(env)
    assert ledger.spent_credits(env) == 48
    rc, out = run(env, "clip", "ingest", "W01", flag, "rejected: draft_job_id is not a finalizable draft")
    assert rc == 0, out
    c = store.load(env, "W01")
    assert c["status"] == "delivered" and c["takes"][1]["status"] in ("failed", "declined")
    assert c["declined"] == [], "a finalize sends no start image: the image is not declined by it"
    assert ledger.spent_credits(env) == 0 and "not charged" in ledger.rows(env)[-1]["note"]
    assert "counts 0 credits" in out["text"] and "take 1 stays W01's take" in out["text"]
    assert "clip lock" not in out["text"] and "--finalize-from 1 --yes" in out["text"], "no new paid draft offered"
    assert core_cli.clip_state(c) == "delivered" and core_cli.failed_finalize(c)["n"] == 2   # status reads it alike
    rc, out = run(env, "clip", "submit", "W01", "--yes", "--res", "480p")
    assert rc == 1 and "not locked" in out["error"], "a new take needs a deliberate re-lock"


def test_a_failed_regular_take_still_offers_the_retry(env):
    c = _finalize_requested(env)
    c["takes"] = [{**c["takes"][1], "finalize_of": None}]
    store.save(env, c)
    rc, out = run(env, "clip", "ingest", "W01", "--failed", "failed with no reason (filter)")
    assert rc == 0 and store.load(env, "W01")["status"] == "locked" and "clip lock W01" in out["text"]


def test_ingest_failed_takes_an_openrouter_estimate_off_the_log(env):
    c = {"id": "W01", "kind": "sung", "status": "submitted", "provider": "openrouter", "start": "plates/x.png",
         "body": {"prompt": "p", "duration": 4},
         "takes": [{"n": 1, "provider": "openrouter", "status": "submitted", "id": "gen-vid-1", "est_usd": 0.93,
                    "model": "bytedance/seedance-2.5"}]}
    store.save(env, c)
    ledger.record(env, provider="openrouter", model="bytedance/seedance-2.5", kind="video", est_usd=0.93,
                  status="submitted", request_id="gen-vid-1", units={"clip": "W01", "take": 1})
    assert ledger.spent_usd(env, "openrouter") == 0.93
    rc, out = run(env, "clip", "ingest", "W01", "--failed", "job failed: output audio rejected")
    assert rc == 0, out
    assert ledger.spent_usd(env, "openrouter") == 0 and ledger.rows(env)[-1]["note"].endswith(": refunded")


# ------------------------------------------------------------------------------------------------ board approval
def test_the_stale_board_line_names_the_skills_command():
    src = read(ROOT / "slop" / "board" / "common.py")
    fn = src[src.index("def board_gate_stale"):]
    assert "board approve')} --note '<their words>'" in fn[:fn.index("\ndef ")]
    for slug in ("storyboard", "render-and-review"):
        assert "board approve --note '<their words>'" in read(ROOT / "skills" / slug / "SKILL.md"), slug
    d40 = flat(read(DOCS / "40-storyboard.md"))
    assert "board approve --note '<their words>'` (it re-audits first and logs their words" in d40

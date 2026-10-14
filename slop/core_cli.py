"""Core commands: new, status, projects, lead, doctor, spend, gate, decide, runs.

  slop new NAME [--title T] [--tier quick|studio|director]   scaffold a project from templates/project
  slop status                     stages done / missing / STALE, gates, ledger spend, the next suggested step
  slop projects                   every project under $SLOP_PROJECTS with its next stage (for a fresh session)
  slop lead [--canon T] [--far T] [--none] ...   show or set the lead's identity text (or: no lead)
  slop doctor [--quick] [--net]   is this machine ready (python, deps, ffmpeg+libx264, chromium, cloudflared,
                                  OPENROUTER_API_KEY validity via the FREE /api/v1/key, disk, RAM, CPU)
  slop spend [--offline]          ledger estimate by provider + REAL OpenRouter usage/limit/balance (free endpoints)
  slop spend --freeze REASON | --unfreeze   the owner's quality flag stops all spending (budget.frozen, logged)
  slop gate [NAME] [--approve|--revoke]   owner gates (board, prompts, v1); what each approval covered is recorded
  slop decide TEXT [--supersedes REF]     dated line appended to DECISIONS.md (`decide --list` to read)
  slop project set KEY VALUE | project show [KEY]   one dotted project.json key (look.accent, lead.canon, budget.*,
                                  models.*, tier, board.generator, ...), validated and logged in DECISIONS.md: no
                                  hand-editing of project.json (gates, name and budget.frozen have their own commands)
  slop runs add ID ... | runs list        run ids of long jobs in RUNS.md, for resume
  slop next [--steps N] [--free-only] [--fg] [--dry-run]   RUN status's next command when it is free, not an owner
                                  gate and needs no creative input first (long steps start as a background job,
                                  slop/job.py); otherwise print it and why

Bot ergonomics (hardening pass): every stage carries "auto" (running its cmd IS the step); status shows the
project's background jobs (and, when one is already running the next step, says to wait for it). For a long step
next.cmd IS the `job start` form (next.step_cmd keeps the plain command): a weaker operator runs what it is shown, and
a long step in the foreground dies at the shell's time limit. Hints: sections guessed by the analysis (source
"heuristic"); while they are open `board draft` is preceded by the confirm command (next.first). A "scan" stage (the
safety + canon scan of every generated take edit/edl.json plays) comes before gate v1 and the master when the edit
plays clips; its verdict is the review module's own (slop/review/scan.py state(): block findings on takes the edit
plays now; findings on re-made or cut takes are stale), its command the one step to do (`review scan-sheets`, look +
`review record FILE`, or triage + `review status`). `gate prompts --approve` accepts a clip-only approval when there
is no plate book. The render/master stages point at `render encode` once render/frames is complete and current by
the render module's content fingerprint (render/frames/.inputs.json), so an identical re-export does not loop back
to `render frames`. A job records status_signature() when it starts; when the newest job of the next step ended and
status still reads the same, `slop next` does not start it again (next.repeat).
Studio run (a refused 1080p finalize read "submitted" and its 48 credits stayed in the spend): status reads a clip
through clip_state(): a finalize take that was rejected or failed (`clip ingest --failed`, which puts the clip back to
delivered; older clip files say locked) shows as "finalize rejected" / "finalize failed" (not charged) and the clip as delivered on its draft; a
Higgsfield take still "requested" with no job id is named with the two ways to close it. Spend totals skip the rows a
settlement voided (ledger.voided: a take reported failed / rejected counts 0), and the Higgsfield credits of requests
that never got a job id are shown apart ("requested", not yet confirmed as spent). The owner's standing prompts yes
(clip_prompt_approved) does not cover a clip left "locked" only by a refused finalize: a new paid take of it needs --yes.

Ported from the original pipeline's newproject.py (scaffold + stage list) and project.py (project selection).
Intentional changes:
  - projects live under $SLOP_PROJECTS (no data-volume symlinks, no media/ split); layout = ARCHITECTURE section 3.2;
  - no default project ever (the original fell back to a hard-coded project when its env var was unset);
  - project.json follows ARCHITECTURE 4.1 with an EMPTY Midjourney profile (each user adds their own code); the lead
    block also carries the source's "note" (how identity is held) and the gen module's optional "noun"/"pronoun";
    extra top-level keys: "created", "claudia" (version) and "gates_meta" (see gates below);
  - budget caps come from the tier (quick $20 / studio $100 / director $150 OpenRouter; 300 / 1500 / 3300
    Higgsfield credits; confirm over $2), derived from the research cost model; the owner may raise them;
  - the template restores the source's BRIEF.md (the owner's ask verbatim), PLAN.md (its 12 headings),
    bible/LEAD.md (the canon), NOTES.md and the lyric references table (lyrics/SOURCES.md), scrubbed;
  - the stage list is computed from the files present (`slop status`) instead of printed once. It follows the
    source's step list (brief, song, lyrics, analysis, lead + look, storyboard, plates, clips, edit, QA + render,
    deliver) and adds the toolkit's code gates: lyric gate N/N, flash + history check, the 9:16 cut. It checks
    freshness (a stage whose inputs changed after it ran is not done): analysis vs lyrics.txt/song, display vs the
    timing, engine export vs its inputs, lyric gate and renders vs the engine data, the check vs the master;
  - gates record WHAT the owner approved (project.json "gates_meta": time + content signatures of board/shots.json,
    plates/prompts.md + every locked clip prompt, out/review.mp4). An approval whose files changed shows as STALE and
    must be re-approved. gates.prompts_approved - the standing "yes" the gen module honours for clip submits - is set
    only when the approval covered at least one locked clip prompt and no clip was still a draft; approving the plate
    book alone is recorded but leaves every clip submit needing its own --yes. Approvals of the board / v1 need the
    board audit / the lyric gate to pass (or --force, logged);
  - new commands for a weaker operator: `slop projects` (a fresh session finds its project), `slop lead` (writes the
    identity text without hand-editing JSON), `slop spend --freeze REASON | --unfreeze` (rule 8: the owner's quality
    flag stops all spending; stored as project.json budget.frozen and logged - ledger.check_budget refuses every
    paid call while it is set); usage errors of every command honour --json (util.json_usage_errors, wired in the
    router), and `slop brief TEXT` records the owner's ask in BRIEF.md (integration: no hand-editing Markdown).
Every command is idempotent: re-running `new` only adds missing template files; `gate`/`decide`/`runs add`
do not write duplicate lines.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import time
import re
import shlex
import shutil
from pathlib import Path

from . import __version__, util
from .config import SlopError, projects_root, resolve_project, save_project, toolkit_root
from .ledger import COUNTED, ledger_path, voided

TIERS = ("quick", "studio", "director")
TIER_BUDGETS = {
    "quick": {"openrouter_usd": 20, "higgsfield_credits": 300, "confirm_over_usd": 2},
    "studio": {"openrouter_usd": 100, "higgsfield_credits": 1500, "confirm_over_usd": 2},
    "director": {"openrouter_usd": 150, "higgsfield_credits": 3300, "confirm_over_usd": 2},
}
DIRS = ["audio/stems", "audio/windows", "lyrics", "analysis", "taste", "bible", "board", "plates/cands", "clips",
        "edit", "engine", "render/frames", "out"]
DEFAULT_GATES = ("board_approved", "prompts_approved", "v1_approved")
GATE_SHORT = {"board_approved": "board", "prompts_approved": "prompts", "v1_approved": "v1"}
TEXT_SUFFIXES = {".md", ".txt", ".json", ".html", ".js", ".csv", ".css"}
RUNS_HEADER = "| when | id | kind | what | status | resume |\n|---|---|---|---|---|---|\n"
AUDIO_EXT = {".wav", ".mp3", ".flac", ".m4a", ".aiff", ".aif", ".ogg"}
CLIP_PENDING = ("draft", "locked", "submitted")
ENGINE_CORE = ("beats.js", "lyrics.js", "shots.js", "edl.js")  # written by every `slop edit export`
EXPORT_INPUTS = ("edit/edl.json", "board/shots.json", "analysis/beats.json", "analysis/words.json",
                 "analysis/hits.json", "lyrics/display.txt", "plates/picks.json")
EPS = 1e-3  # seconds; mtime comparisons


def template_dir() -> Path:
    return toolkit_root() / "templates" / "project"


def _sub_text(text: str, subs: dict[str, str]) -> str:
    for k, v in subs.items():
        text = text.replace(k, v)
    return text


def project_ref(pdir: Path) -> str:
    """What to pass to --project: the bare name under $SLOP_PROJECTS, else the full path (shell-quoted)."""
    try:
        if pdir.parent.resolve() == projects_root().resolve():
            return pdir.name
    except OSError:
        pass
    return shlex.quote(str(pdir))


def _pcmd(pdir: Path, rest: str) -> str:
    """A command line with the project flag spelled out (lesson: never rely on an exported default)."""
    return f"slop --project {project_ref(pdir)} {rest}"


def load_project_checked(pdir: Path) -> dict:
    """project.json as a dict; a broken file is a SlopError that names the file and the way out (no traceback)."""
    p = pdir / "project.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise SlopError(f"{p} is not valid JSON ({e.msg} at line {e.lineno} column {e.colno}). Fix that line, or copy "
                        f"the missing keys back from {template_dir() / 'project.json'} (keep this project's name, "
                        "title, tier, lead, budget and gates)") from None
    except OSError as e:
        raise SlopError(f"cannot read {p}: {e}") from None
    if not isinstance(data, dict):
        raise SlopError(f"{p} must hold one JSON object {{...}}; restore it from {template_dir() / 'project.json'}")
    return data


def _mtime(p: Path) -> float | None:
    try:
        return p.stat().st_mtime
    except OSError:
        return None


def _newer(a: Path, b: Path) -> bool:
    """True when both exist and a was modified after b."""
    ma, mb = _mtime(a), _mtime(b)
    return ma is not None and mb is not None and ma > mb + EPS


# ====================================================================== project discovery
def list_projects(root: Path | None = None, with_next: bool = True) -> list[dict]:
    root = Path(root) if root else projects_root()
    out: list[dict] = []
    if not root.is_dir():
        return out
    tree = command_tree() if with_next else None
    for d in sorted(p for p in root.iterdir() if p.is_dir() and (p / "project.json").is_file()):
        row: dict = {"name": d.name, "path": str(d), "updated": util.stamp(_mtime(d / "project.json"))}
        try:
            proj = load_project_checked(d)
            row.update(title=proj.get("title"), tier=proj.get("tier"))
            if with_next:
                st = project_status(d, tree=tree, proj=proj)
                nx = st["next"]
                row["next"] = nx["stage"] if nx else "done"
                row["next_do"] = nx["do"] if nx else ""
                row["jobs_running"] = st.get("jobs_running", 0)
                if row["jobs_running"]:
                    row["next"] += f" ({row['jobs_running']} job running)"
        except SlopError as e:
            row.update(title=None, tier=None, next="broken", next_do=str(e))
        out.append(row)
    return out


def _projects_hint() -> str:
    root = projects_root()
    try:
        names = [r["name"] for r in list_projects(root, with_next=False)]
    except OSError:
        names = []
    if not names:
        return f". No projects in {root} yet: create one with  slop new NAME"
    shown = ", ".join(names[:12]) + (f" (+{len(names) - 12} more)" if len(names) > 12 else "")
    return f". Projects in {root}: {shown}  (details: slop projects)"


def _resolve(args, must_exist: bool = True) -> Path:
    """resolve_project + the list of existing projects in the error (a fresh session must not have to `ls`)."""
    try:
        return resolve_project(getattr(args, "project", None), must_exist=must_exist)
    except SlopError as e:
        raise SlopError(str(e) + _projects_hint()) from None


# ====================================================================== new
def cmd_new(args) -> dict:
    name = util.validate_name(args.name)
    root = Path(args.root).expanduser() if getattr(args, "root", None) else projects_root()
    pdir = (root / name).resolve()
    tpl = template_dir()
    if not (tpl / "project.json").is_file():
        hint = ("claudia looks installed as a plain package (site-packages): templates/ and engine/ are not "
                "packaged. Use a git clone and bash bin/setup.sh (or pip install -e . from the clone)"
                if "site-packages" in str(toolkit_root()) else "the toolkit checkout is incomplete (re-clone it)")
        raise SlopError(f"project template missing at {tpl}: {hint}")
    exists = (pdir / "project.json").is_file()
    if pdir.exists() and not pdir.is_dir():
        raise SlopError(f"{pdir} exists and is a file; choose another NAME")
    if pdir.is_dir() and not exists and any(pdir.iterdir()):
        raise SlopError(f"{pdir} exists but is not a slop project (no project.json); choose another NAME "
                        "or move that folder away")
    notes: list[str] = []
    if exists:
        proj = load_project_checked(pdir)
        title = proj.get("title") or name
        tier = proj.get("tier") or "quick"
        if args.title and args.title != title:
            notes.append(f"kept the existing title {title!r} (edit project.json to change it)")
        if args.tier and args.tier != tier:
            notes.append(f"kept the existing tier {tier!r} (edit project.json \"tier\" to change it)")
    else:
        title = (args.title or name.replace("-", " ").title()).strip()
        tier = args.tier or "quick"
    subs = {"{{NAME}}": name, "{{TITLE}}": title, "{{TIER}}": tier, "{{DATE}}": util.today()}

    pdir.mkdir(parents=True, exist_ok=True)
    added: list[str] = []
    if not exists:  # project.json first: a crash after this leaves a folder `slop new` can still complete
        proj = json.loads((tpl / "project.json").read_text(encoding="utf-8"))
        proj.update({"name": name, "title": title, "tier": tier})
        proj["budget"] = {**proj.get("budget", {}), **TIER_BUDGETS[tier]}
        proj.setdefault("mj", {})["profile"] = ""  # each user's own --profile code; never ship one
        proj.setdefault("gates", {})
        for g in DEFAULT_GATES:
            proj["gates"].setdefault(g, False)
        proj["created"] = util.iso_now()
        proj["claudia"] = __version__
        save_project(pdir, proj)
        added.append("project.json")
    for src in sorted(tpl.rglob("*")):
        rel = src.relative_to(tpl)
        if src.is_dir() or rel == Path("project.json") or "__pycache__" in rel.parts:
            continue
        dst = pdir / rel
        if dst.exists():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.suffix.lower() in TEXT_SUFFIXES:
            util.atomic_write_text(dst, _sub_text(src.read_text(encoding="utf-8"), subs))
        else:
            shutil.copy2(src, dst)
        added.append(rel.as_posix())
    for d in DIRS:
        (pdir / d).mkdir(parents=True, exist_ok=True)

    st = project_status(pdir)
    lines = [(f"created {pdir}" if not exists else f"{pdir} already exists - kept it")
             + f"  (tier {tier}, title \"{title}\")"]
    if exists and added:
        lines.append("restored missing template files: " + ", ".join(added))
    lines += notes
    ref = project_ref(pdir)
    lines.append(f"use it on EVERY command:  slop --project {ref} <command>   (or SLOP_PROJECT={ref} slop <command>)")
    nx = st["next"]
    if nx:
        lines.append(f"next: {nx['do']}" + (f"\n      {nx['cmd']}" if nx.get("cmd") else ""))
    lines.append(f"any time: slop --project {ref} status")
    return {"project": str(pdir), "name": name, "title": title, "tier": tier, "created": not exists,
            "files_added": added, "notes": notes, "next": nx, "text": "\n".join(lines)}


# ====================================================================== status helpers
def _rel(pdir: Path, p: Path) -> str:
    try:
        return p.relative_to(pdir).as_posix()
    except ValueError:
        return str(p)


def _json_or_none(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None
    except (ValueError, OSError):
        return "unreadable"


def command_tree() -> dict | None:
    """{cmd: {subcmd: {...}}} of what this install registers (other modules may be missing)."""
    try:
        from .cli import build_parser
        ap = build_parser()
    except Exception:  # a broken module must not break status
        return None

    def walk(p: argparse.ArgumentParser) -> dict:
        tree: dict = {}
        for a in p._actions:
            if isinstance(a, argparse._SubParsersAction):
                for nm, sp in a.choices.items():
                    tree[nm] = walk(sp)
        return tree
    return walk(ap)


def command_available(cmd: str, tree: dict | None) -> bool | None:
    if tree is None or not cmd:
        return None
    try:
        words = shlex.split(cmd)
    except ValueError:
        words = cmd.split()
    if not words or words[0] != "slop":
        return None  # not a slop command (an instruction to edit a file)
    words = words[1:]
    while words[:1] and words[0].startswith("-"):  # skip "--project X"
        words = words[2:] if words[0] in ("--project", "-p") else words[1:]
    node = tree
    for w in words:
        if w.startswith("-") or not re.fullmatch(r"[a-z][a-z0-9_-]*", w) or not node:
            break
        if w not in node:
            return False
        node = node[w]
    return True


def _stage(name: str, done: bool, detail: str, do: str = "", cmd: str = "", optional: bool = False,
           auto: bool = False) -> dict:
    """One status stage. auto = running `cmd` as it stands IS the step (no creative/owner work first, no
    placeholder) - `slop next` only ever runs such commands."""
    return {"stage": name, "done": bool(done), "optional": optional, "detail": detail, "do": do, "cmd": cmd,
            "auto": bool(auto and cmd and not done)}


def status_signature(stages: list[dict]) -> str:
    """A hash of what status says about every stage (name, done, detail, command). A job records it when it starts;
    the same signature after the job ended means the job changed nothing status can see (`slop next` then does not
    start that step again)."""
    rows = [[s.get("stage"), bool(s.get("done")), s.get("detail"), s.get("cmd")] for s in stages]
    return "sha1:" + hashlib.sha1(json.dumps(rows, ensure_ascii=False, default=str).encode()).hexdigest()[:16]


def project_signature(pdir: Path) -> str | None:
    """status_signature of a project now (None when it cannot be computed; never raises)."""
    try:
        return status_signature(evaluate_stages(pdir, load_project_checked(pdir)))
    except Exception:  # noqa: BLE001 - advisory only
        return None


# ====================================================================== long + free steps (for `slop next` / jobs)
# command paths that can outlast the bot shell's foreground timeout: status suggests them as jobs, `next` starts jobs
LONG_STEPS = {("analyze",), ("edit", "export"), ("render", "frames"), ("render", "vertical"), ("render", "lyrics"),
              ("render", "encode"), ("render", "check"), ("render", "sheet"), ("render", "stills"),
              ("taste", "embed"), ("fetch",), ("review", "scan-sheets"), ("board", "sheet"), ("clip", "sync")}
# command paths `slop next` may run by itself: free (no provider spend), no owner decision
FREE_STEPS = {("song", "ingest"), ("lyrics", "lint"), ("lyrics", "display"), ("analyze",), ("board", "draft"),
              ("board", "audit"), ("board", "sheet"), ("plates", "book"), ("plates", "status"), ("clip", "list"),
              ("clip", "sync"), ("edit", "edl"), ("edit", "export"), ("render", "info"), ("render", "lyrics"),
              ("render", "frames"), ("render", "encode"), ("render", "check"), ("render", "vertical"),
              ("render", "sheet"), ("review", "scan-sheets"), ("review", "status"), ("status",)}
PLACEHOLDER_RE = re.compile(r"PATH/TO|\bTEXT\b|<[^>]*>|\[\[|(?:^|\s)--help\b|\bID\b")


def cmd_words(cmd: str) -> list[str]:
    """`slop --project x render frames --workers 4` -> ['render', 'frames', '--workers', '4'] (no slop/root flags)."""
    try:
        words = shlex.split(cmd or "")
    except ValueError:
        words = (cmd or "").split()
    if words[:1] != ["slop"]:
        return []
    words = words[1:]
    out, i = [], 0
    while i < len(words):
        w = words[i]
        if w in ("--project", "-p"):
            i += 2
            continue
        if w == "--json" or w.startswith("--project="):
            i += 1
            continue
        out.append(w)
        i += 1
    return out


def _cmd_path(cmd: str) -> tuple[str, ...]:
    path = []
    for w in cmd_words(cmd):
        if w.startswith("-") or not re.fullmatch(r"[a-z][a-z0-9_-]*", w):
            break
        path.append(w)
    return tuple(path)


def is_long(cmd: str) -> bool:
    p = _cmd_path(cmd)
    return p[:2] in LONG_STEPS or p[:1] in LONG_STEPS


def is_free_step(cmd: str) -> bool:
    p = _cmd_path(cmd)
    return p[:2] in FREE_STEPS or p[:1] in FREE_STEPS


def job_cmd(pdir: Path, cmd: str) -> str:
    """The same step as a background job: slop --project X job start -- <command>."""
    return _pcmd(pdir, "job start -- " + " ".join(shlex.quote(w) for w in cmd_words(cmd)))


# ====================================================================== the safety scan (render/scan/scan.json)
SCAN_FILE = "render/scan/scan.json"
SCAN_LIST = "render/scan-list.json"


def played_takes(pdir: Path) -> list[str]:
    """Engine clip names ("<clip>-t<k>") of the generated takes edit/edl.json plays (its segs)."""
    E = _json_or_none(pdir / "edit/edl.json")
    names: set[str] = set()
    if isinstance(E, dict):
        for e in E.values():
            if isinstance(e, dict):
                for g in e.get("segs") or []:
                    if isinstance(g, dict) and isinstance(g.get("clip"), str) and g["clip"].strip():
                        names.add(g["clip"].strip())
    return sorted(names)


def _take_file(pdir: Path, name: str) -> Path | None:
    clip, _, k = name.rpartition("-t")
    if not clip or not k.isdigit():
        return None
    c = _json_or_none(pdir / "clips" / f"{clip}.json")
    takes = c.get("takes") if isinstance(c, dict) else None
    if not isinstance(takes, list) or not (1 <= int(k) <= len(takes)) or not isinstance(takes[int(k) - 1], dict):
        return None
    f = takes[int(k) - 1].get("file")
    return (pdir / f) if isinstance(f, str) and f else None


def _review_scan():
    """The review module's scan reader (slop/review/scan.py: its state() is the release verdict), or None when this
    install lacks it. Imported lazily: status must work without it."""
    try:
        return importlib.import_module("slop.review.scan")
    except Exception:  # noqa: BLE001 - a missing or broken module: core reads scan.json itself
        return None


def scan_list_takes(pdir: Path) -> list[str] | None:
    """The take names render/scan-list.json holds (written by `slop review scan-sheets`), None when there is none."""
    v = _json_or_none(pdir / SCAN_LIST)
    if not isinstance(v, list):
        return None
    return sorted({str(t["clip"]) for t in v if isinstance(t, dict) and t.get("clip")})


def _short_list(xs: list[str], n: int = 8) -> str:
    return ", ".join(xs[:n]) + (" …" if len(xs) > n else "")


def scan_state(pdir: Path) -> dict:
    """The safety scan against the takes the edit plays NOW: {played, problem (None = cleared or not needed), step}.

    step = the one thing to do next: "sheets" (`review scan-sheets`: no sheets yet, the edit changed after they were
    made, or a take was re-made), "record" (look at the sheets, then `review record FILE`), "triage" (open blocks:
    re-make or cut, then re-scan), "unreadable" (scan.json is broken). The verdict (open blocks, unchecked takes) is
    the review module's own (review.scan.state); without that module core applies the same rule to scan.json: only
    block findings on takes the edit plays (or on plates) are open, every played take must be in "checked"."""
    played = played_takes(pdir)
    out: dict = {"played": played, "problem": None, "step": None, "blocks": [], "unchecked": []}
    if not played:
        return out
    lst = scan_list_takes(pdir)
    list_stale = lst is not None and set(lst) != set(played)
    sp = pdir / SCAN_FILE
    s = _json_or_none(sp)
    if s is None:
        out.update(problem=f"{len(played)} generated take(s) the edit plays have not been safety-scanned",
                   step="record" if lst is not None and not list_stale else "sheets", unchecked=list(played))
        return out
    if not isinstance(s, dict):
        out.update(problem=f"{SCAN_FILE} is not valid JSON", step="unreadable")
        return out
    blocks: list[dict] | None = None
    unchecked: list[str] | None = None
    rv = _review_scan() if not list_stale else None
    if rv is not None:
        try:
            st = rv.state(pdir)
            blocks = [f for f in st.get("open") or [] if isinstance(f, dict) and f.get("severity") == "block"]
            unchecked = [t for t in st.get("unchecked") or [] if t in played]
        except Exception:  # noqa: BLE001 - fall back to reading the file
            blocks = unchecked = None
    checked = {str(x) for x in s.get("checked") or [] if isinstance(x, (str, int))}
    if blocks is None:
        live = set(played)
        blocks = [f for f in s.get("findings") or [] if isinstance(f, dict) and f.get("severity") == "block"
                  and (f.get("clip") in live or str(f.get("clip", "")).startswith("plate:"))]
    missing = [t for t in played if t not in checked]
    if unchecked is not None:
        missing = sorted(set(missing) | set(unchecked))
    smt = _mtime(sp) or 0
    newer = [t for t in played if (f := _take_file(pdir, t)) is not None and (_mtime(f) or 0) > smt + EPS]
    probs = []
    if list_stale:
        gone = sorted(set(lst or []) - set(played))
        new = sorted(set(played) - set(lst or []))
        probs.append("the edit changed after the scan sheets were made ("
                     + "; ".join(x for x in (f"new: {_short_list(new)}" if new else "",
                                             f"no longer played: {_short_list(gone)}" if gone else "") if x) + ")")
    if blocks:
        probs.append(f"{len(blocks)} open block finding(s): " + "; ".join(
            f"{b.get('clip')} @{b.get('time', '?')}: {str(b.get('what', ''))[:60]}" for b in blocks[:4])
            + (" …" if len(blocks) > 4 else ""))
    if missing:
        probs.append(f"{len(missing)} take(s) the edit plays are not in the recorded scan: {_short_list(missing)}")
    if newer:
        probs.append(f"re-made after the last scan: {_short_list(newer)}")
    if not probs:
        return out
    step = "sheets" if (list_stale or newer or (missing and lst is None)) else ("record" if missing else "triage")
    out.update(problem="; ".join(probs), step=step, blocks=blocks, unchecked=missing)
    return out


def scan_problem(pdir: Path) -> tuple[list[str], str | None]:
    """(takes the edit plays, why the safety scan does not count as cleared; None = cleared or not needed)."""
    st = scan_state(pdir)
    return st["played"], st["problem"]


SCAN_FINDINGS = "render/scan/findings.json"


def scan_step(pdir: Path, step: str | None) -> tuple[str, str, bool]:
    """(what to do, the command, auto) for a scan_state step."""
    record = _pcmd(pdir, f"review record {SCAN_FINDINGS}")
    if step == "sheets":
        return ("make the scan sheets: 6 frames of every generated take the edit plays (only new or changed takes get "
                "new sheets); then look at every sheet and record the findings", _pcmd(pdir, "review scan-sheets"), True)
    if step == "record":
        return ("look at EVERY sheet in render/scan/ (rubric: docs/80-review-qa §9.2 - block = must not ship, fix, "
                "note); copy render/scan/findings-template.json to " + SCAN_FINDINGS + ", put each finding in "
                "\"findings\" ({\"clip\", \"time\", \"severity\", \"kind\", \"what\"}) and add every take you looked at "
                "(the template lists them under \"to_check\") to \"checked\"; then record it", record, False)
    if step == "unreadable":
        return (f"{SCAN_FILE} is broken: move it aside (rename it to scan.broken.json), then record the findings "
                "again", record, False)
    return ("each block must not ship (docs/80-review-qa §9.4): fix it at the source and re-make that take, or cut "
            f"it from the edit ({_pcmd(pdir, 'edit edl')}); then make the sheets again and record the re-scan. The "
            "open blocks:", _pcmd(pdir, "review status"), False)


# ====================================================================== rendered frames (render frames -> encode)
def _render_project():
    """slop/render/project.py (the frame fingerprint: read_fingerprint / current_fingerprint), or None."""
    try:
        return importlib.import_module("slop.render.project")
    except Exception:  # noqa: BLE001 - status must work without the render module
        return None


def frames_state(pdir: Path, proj: dict) -> dict:
    """{ready, complete, current, placeholders} of render/frames (ready = `render encode` can run on them).

    current is judged the way `render frames` / `render encode` judge it: the content fingerprint the frames were
    drawn from (render/frames/.inputs.json) against the project now (render.project.current_fingerprint), so an
    identical re-export (new file times, same content) does not send the render step back to `render frames`.
    Without the render module: .inputs.json (rewritten by every `render frames` run) at least as new as the engine
    data. Frames with no .inputs.json: the oldest frame at least as new as the engine data."""
    out = {"ready": False, "complete": False, "current": None, "placeholders": False, "by": "time", "newest": None}
    d = pdir / "render/frames"
    if not d.is_dir():
        return out
    dur = None
    for rel in ("analysis/beats.json", "board/shots.json"):
        v = _json_or_none(pdir / rel)
        if isinstance(v, dict) and isinstance(v.get("duration"), (int, float)) and v["duration"] > 0:
            dur = float(v["duration"])
            break
    if dur is None:
        return out
    try:
        fps = float(proj.get("fps") or 24)
    except (TypeError, ValueError):
        fps = 24.0
    need = int(-(-(dur * fps - 1e-6) // 1))
    n, oldest, newest = 0, None, None
    try:
        with os.scandir(d) as it:
            for e in it:
                if re.fullmatch(r"f\d{5,}\.jpg", e.name):
                    n += 1
                    m = e.stat().st_mtime
                    oldest = m if oldest is None else min(oldest, m)
                    newest = m if newest is None else max(newest, m)
    except OSError:
        return out
    if n < need or oldest is None:
        return out
    out.update(complete=True, newest=newest)
    et = engine_time(pdir)
    fp_file = d / ".inputs.json"
    rec = _json_or_none(fp_file)
    current = None
    if isinstance(rec, dict) and rec.get("hash"):
        out["placeholders"] = bool(rec.get("placeholders"))
        rp = _render_project()
        if rp is not None:
            try:
                current = rp.current_fingerprint(pdir, rec).get("hash") == rec["hash"]
                out["by"] = "fingerprint"
            except Exception:  # noqa: BLE001 - e.g. the engine page is missing: judge by file times
                current = None
        if current is None:
            current = et is None or (_mtime(fp_file) or 0) + EPS >= et
    else:
        current = et is None or oldest + EPS >= et
    out["current"] = bool(current)
    out["ready"] = bool(current) and not out["placeholders"]
    return out


def frames_ready(pdir: Path, proj: dict) -> bool:
    """render/frames holds every frame of the song, drawn from the project as it is now (encode can run)."""
    return frames_state(pdir, proj)["ready"]


# ====================================================================== hints (not stages: nothing blocks on them)
def _num_text(x: float) -> str:
    return f"{x:.2f}".rstrip("0").rstrip(".") or "0"


def sections_hint(pdir: Path, tree: dict | None) -> dict | None:
    """'sections unconfirmed' when analysis/beats.json sections were guessed (source "heuristic" / "unconfirmed": true),
    with the commands that confirm or fix them (the audio module's `slop song sections --set`, when installed)."""
    b = _json_or_none(pdir / "analysis/beats.json")
    if not isinstance(b, dict):
        return None
    secs = [s for s in (b.get("sections") or []) if isinstance(s, dict)]
    if not secs:
        return None
    guessed = [s for s in secs if str(s.get("source", "")).lower() == "heuristic" or s.get("unconfirmed") is True]
    if not guessed and str(b.get("sections_source", b.get("sections_from", ""))).lower() == "heuristic":
        guessed = secs
    if not guessed:
        return None

    def span(s: dict) -> str:
        mark = "?" if s in guessed else ""
        try:
            return f"{s.get('name', '?')}{mark} {float(s.get('t0')):.0f}-{float(s.get('t1')):.0f} s"
        except (TypeError, ValueError):
            return f"{s.get('name', '?')}{mark}"
    table = ", ".join(span(s) for s in secs[:12]) + (" …" if len(secs) > 12 else "")
    lead = (f"sections unconfirmed: the analysis GUESSED {len(guessed)} of {len(secs)} section names/starts ({table}; "
            "? = guess). They set the board's pace, which clip windows are sung and the look per section. Listen to "
            "the song with analysis/report.md's section table open, then")
    has_set = isinstance(tree, dict) and isinstance(tree.get("song"), dict) and "sections" in tree["song"]
    if has_set:
        try:
            parts = []
            for s in secs:
                nm = re.sub(r"[,@\s]+", "-", str(s.get("name") or "section"))
                parts.append(nm + "@" + _num_text(float(s["t0"])))
            spec = ",".join(parts)
        except (KeyError, TypeError, ValueError):
            spec = None                 # never print made-up values as a runnable command: show the real list first
        if spec is None:
            show = _pcmd(pdir, "song sections")
            text = (f"{lead} run {show}: it prints every section as NAME@START; then confirm or fix them with "
                    f"{_pcmd(pdir, 'song sections --set')} \"NAME@START,…\" listing EVERY section (it replaces them "
                    f"all), or tag the lyric lines ([Verse 1], [Chorus]) and run: {_pcmd(pdir, 'analyze --steps sections')}")
            return {"kind": "sections", "text": text, "cmd": show, "show": show, "guessed": len(guessed),
                    "total": len(secs)}
        confirm = _pcmd(pdir, f"song sections --set {shlex.quote(spec)}")
        text = (f"{lead} if they are right, confirm them as they are: {confirm} ; if not, run the same command with "
                "the right names and starts (START = seconds, barK or lineN), or tag the lyric lines ([Verse 1], "
                f"[Chorus]) and run: {_pcmd(pdir, 'analyze --steps sections')}")
        return {"kind": "sections", "text": text, "cmd": confirm, "show": _pcmd(pdir, "song sections"),
                "guessed": len(guessed), "total": len(secs)}
    fix = _pcmd(pdir, "analyze --steps sections")
    text = (f"{lead} if a section is wrong, write project.json audio.sections (e.g. [{{\"name\": \"verse1\", "
            f"\"t0\": 15.2}}, {{\"name\": \"chorus1\", \"bar\": 16}}]) or tag the lyric lines ([Verse 1], [Chorus]), "
            f"and run: {fix}")
    return {"kind": "sections", "text": text, "cmd": fix, "guessed": len(guessed), "total": len(secs)}


def brief_ask(pdir: Path) -> str:
    """The text under BRIEF.md's "ask" heading, without HTML comments, empty quote markers and blank lines."""
    p = pdir / "BRIEF.md"
    if not p.is_file():
        return ""
    text = re.sub(r"<!--.*?-->", "", p.read_text(encoding="utf-8"), flags=re.S)
    out, inside = [], False
    for line in text.splitlines():
        if line.startswith("## "):
            inside = "ask" in line.lower()
            continue
        if inside:
            s = line.strip().lstrip(">").strip()
            if s:
                out.append(s)
    return "\n".join(out)


def add_brief_ask(pdir: Path, text: str, when: str | None = None) -> dict:
    """Append the owner's words, verbatim and dated, as a quote under BRIEF.md's ask heading (integration: a bot used
    to have to edit the Markdown by hand, and text appended at the end of the file was not counted). Idempotent: the
    same words are not added twice."""
    text = (text or "").strip()
    if not text:
        raise SlopError("give the owner's words: slop --project NAME brief \"<their ask, verbatim>\" (or --file F)")
    p = pdir / "BRIEF.md"
    if not p.is_file():
        raise SlopError("no BRIEF.md: re-run `slop new NAME` (it restores missing template files), then retry")
    if text in brief_ask(pdir):
        return {"added": False, "ask": brief_ask(pdir)}
    lines = p.read_text(encoding="utf-8").splitlines()
    head = next((i for i, ln in enumerate(lines) if ln.startswith("## ") and "ask" in ln.lower()), None)
    quote = [f"> {when or util.today()}: " + text.splitlines()[0]] + [f"> {ln}" for ln in text.splitlines()[1:]]
    if head is None:
        lines += ["", "## The owner's ask (verbatim, with dates)", ""] + quote
    else:
        end = next((i for i in range(head + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
        body = list(range(head + 1, end))
        empty = [i for i in body if lines[i].strip() == ">"]
        if empty:                           # the template's empty quote marker: fill it
            i = empty[0]
            lines[i:i + 1] = quote
        else:
            last = max([i for i in body if lines[i].strip()] or [head])
            lines[last + 1:last + 1] = [">"] + quote if lines[last].startswith(">") else [""] + quote
    util.atomic_write_text(p, "\n".join(lines) + "\n")
    return {"added": True, "ask": brief_ask(pdir)}


def cmd_brief(args) -> dict:
    pdir = _resolve(args)
    text = " ".join(args.text or [])
    if args.file:
        text = Path(args.file).expanduser().read_text(encoding="utf-8")
    if not text.strip():
        ask = brief_ask(pdir)
        return {"ask": ask, "text": ("the owner's ask (BRIEF.md):\n" + ask) if ask else
                "BRIEF.md has no ask yet: slop --project NAME brief \"<the owner's words, verbatim>\""}
    r = add_brief_ask(pdir, text, args.date)
    r["text"] = (("added to BRIEF.md" if r["added"] else "already in BRIEF.md (not added twice)")
                 + " under \"The owner's ask\". References and taboos: edit the other BRIEF.md sections.")
    return r


def _board_clip_refs(shots) -> set[str] | None:
    """Clip ids the storyboard uses (shot clip / clips / seedance_clip and the top-level seedance list); None = none."""
    if not isinstance(shots, dict):
        return None
    refs: set[str] = set()
    for sh in shots.get("shots") or []:
        if isinstance(sh, dict):
            for c in (sh.get("clips") or []) + [sh.get("clip"), sh.get("seedance_clip")]:
                if isinstance(c, str) and c:
                    refs.add(c)
    for c in shots.get("seedance") or []:
        if isinstance(c, dict) and (c.get("clip") or c.get("id")):
            refs.add(str(c.get("clip") or c.get("id")))
    return refs or None


def clip_docs(pdir: Path) -> list[tuple[str, dict | None]]:
    """[(clip id, clips/<id>.json as a dict, or None when unreadable)]"""
    d = pdir / "clips"
    if not d.is_dir():
        return []
    out = []
    for f in sorted(d.glob("*.json")):
        c = _json_or_none(f)
        out.append((f.stem, c if isinstance(c, dict) else None))
    return out


def _chosen_take(c: dict) -> dict | None:
    """The take the edit uses: the latest delivered take with a file that was not rejected (gen/edit rule)."""
    for tk in reversed(c.get("takes") or []):
        if not isinstance(tk, dict):
            continue
        rejected = bool(tk.get("rejected")) or tk.get("status") == "rejected" or \
            (tk.get("qa") or {}).get("verdict") == "reject"
        if tk.get("status") == "delivered" and tk.get("file") and not rejected:
            return tk
    return None


FAILED_TAKE = ("failed", "declined", "rejected")


def failed_finalize(c: dict) -> dict | None:
    """The clip's newest take when it is a Higgsfield finalize that was rejected or failed (never delivered, never
    charged) while a delivered take (the draft) is still the clip's take; else None."""
    takes = [t for t in (c.get("takes") or []) if isinstance(t, dict)]
    tk = takes[-1] if takes else {}
    if tk.get("finalize_of") and tk.get("status") in FAILED_TAKE and not tk.get("file") and _chosen_take(c):
        return tk
    return None


def finalize_label(tk: dict) -> str:
    """"rejected" when it never got a job (refused at get_cost / submit) or the reason says so, else "failed"."""
    why = str(tk.get("error") or "").lower()
    return "rejected" if (not tk.get("id") or "reject" in why or "refus" in why) else "failed"


def clip_state(c: dict) -> str:
    """The clip's status as `slop status` reads it. `clip ingest --failed` on a finalize now puts the clip back to
    delivered itself; a clip file written before that says locked, and when the take that failed was a finalize of a
    delivered draft (and the clip was not locked again after it), the draft is still the clip's take: delivered."""
    s = str(c.get("status") or "?")
    fin = failed_finalize(c) if s in ("locked", "failed", "declined") else None
    if fin and not str(c.get("locked_at") or "") > str(fin.get("submitted") or ""):
        return "delivered"
    return s


def requested_takes(c: dict) -> list[dict]:
    """Higgsfield takes whose request file was written but no job id was recorded (still "requested")."""
    return [t for t in (c.get("takes") or []) if isinstance(t, dict) and t.get("provider") == "higgsfield"
            and t.get("status") == "requested" and not t.get("id")]


def clip_prompt_sig(c: dict) -> str:
    """Signature of what the owner reads and pays for in a clip: prompt, words, start image, model, provider, length."""
    body = c.get("body") or {}
    keys = {"prompt": body.get("prompt"), "duration": body.get("duration"), "words": c.get("words"),
            "start": c.get("start"), "model": c.get("model"), "provider": c.get("provider"), "kind": c.get("kind")}
    return "sha1:" + hashlib.sha1(json.dumps(keys, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def _engine_files(pdir: Path) -> list[Path]:
    eng = pdir / "engine"
    out: list[Path] = []
    for pat in ("*.js", "assets/*.js", "ch/*.js"):
        out += [p for p in eng.glob(pat) if p.is_file()]
    return out


def engine_time(pdir: Path) -> float | None:
    """Newest change to the project's engine data or chapter code (what a render shows)."""
    ts = [t for t in (_mtime(p) for p in _engine_files(pdir)) if t is not None]
    return max(ts) if ts else None


def export_problem(pdir: Path) -> str | None:
    """Why engine/assets is missing or older than its inputs (None = exported and current)."""
    assets = pdir / "engine/assets"
    core = [assets / n for n in ENGINE_CORE if (assets / n).is_file()]
    if not core:
        return "engine/assets has no exported data"
    exported = min(_mtime(p) or 0 for p in core)
    changed = [n for n in EXPORT_INPUTS if (_mtime(pdir / n) or 0) > exported + EPS]
    if changed:
        return ", ".join(changed) + " changed after the last export"
    return None


def lyric_gate_problem(pdir: Path) -> str | None:
    """Why the lyric gate (render/lyrics-report.json from `slop render lyrics`) does not count as passed."""
    rep = pdir / "render/lyrics-report.json"
    r = _json_or_none(rep)
    if r is None:
        return "the lyric gate has not run (render/lyrics-report.json missing)"
    if not isinstance(r, dict):
        return "render/lyrics-report.json is unreadable"
    try:
        checked = int(r.get("checked") or 0)
    except (TypeError, ValueError):
        checked = 0
    missing = r.get("missing") or []
    if checked <= 0:
        return "the last lyric gate checked 0 tokens (the page had no lyrics)"
    if missing:
        return f"lyric gate FAILED: {len(missing)} of {checked} sung tokens not on screen at their time"
    et = engine_time(pdir)
    if et is not None and (_mtime(rep) or 0) + EPS < et:
        return "the engine data changed after the last lyric gate"
    return None


def board_audit_problem(pdir: Path) -> str | None:
    """Why the board cannot count as audited (None = board/audit.json passes and is newer than shots.json)."""
    shots, audit = pdir / "board/shots.json", pdir / "board/audit.json"
    if not shots.is_file():
        return "there is no board/shots.json"
    a = _json_or_none(audit)
    if a is None:
        return "not audited yet"
    if not isinstance(a, dict):
        return "board/audit.json is unreadable"
    ok = a.get("ok", a.get("pass", a.get("passed")))
    if ok is False:
        return "audit FAILED (see board/audit.json)"
    if _newer(shots, audit):
        return "board/shots.json changed after the last audit"
    return None


# ====================================================================== gates
def gate_problem(pdir: Path, key: str) -> str | None:
    """What must hold before the owner's approval can be recorded (None = ready)."""
    if key == "board_approved":
        p = board_audit_problem(pdir)
        if p:
            step = "board draft" if not (pdir / "board/shots.json").is_file() else "board audit"
            return f"board not ready: {p} (run: {_pcmd(pdir, step)})"
    if key == "prompts_approved" and not (pdir / "plates/prompts.md").is_file():
        # a clip-only approval is fine when there is no plate book (plates from the owner, or no plates at all)
        if not any(c and clip_state(c) == "locked" for _, c in clip_docs(pdir)):
            return (f"nothing for the owner to read yet: no plates/prompts.md (run: {_pcmd(pdir, 'plates book')}) "
                    f"and no locked clip prompt (lock one: {_pcmd(pdir, 'clip lock ID')})")
    if key == "v1_approved":
        if not any((pdir / f).is_file() for f in ("out/review.mp4", "out/master.mp4")):
            return ("there is no out/review.mp4 for the owner to watch (run: "
                    f"{_pcmd(pdir, 'render frames')}, then {_pcmd(pdir, 'render encode --review')})")
        lp = lyric_gate_problem(pdir)
        if lp:
            return f"{lp} - every sung word must be on screen before v1 (run: {_pcmd(pdir, 'render lyrics')})"
        sc = scan_state(pdir)
        if sc["problem"]:
            return (f"{sc['problem']} - every generated take the edit plays must pass the safety + canon scan before "
                    f"v1 (docs/80-review-qa §9; next: {scan_step(pdir, sc['step'])[1]})")
    return None


def gate_covers(pdir: Path, key: str, clips: list | None = None) -> dict[str, str | None]:
    """Content signatures of what an approval of `key` covers right now."""
    if key == "board_approved":
        return {"board/shots.json": util.file_sig(pdir / "board/shots.json")}
    if key == "prompts_approved":
        cov: dict[str, str | None] = {"plates/prompts.md": util.file_sig(pdir / "plates/prompts.md")}
        for cid, c in (clip_docs(pdir) if clips is None else clips):
            if c and clip_state(c) == "locked":
                cov[f"clips/{cid}.json"] = clip_prompt_sig(c)
        return cov
    if key == "v1_approved":
        for rel in ("out/review.mp4", "out/master.mp4"):
            if (pdir / rel).is_file():
                return {rel: util.file_sig(pdir / rel)}
    return {}


def clip_prompt_approved(proj: dict, clip: dict) -> bool:
    """True when the owner's recorded prompts approval covers THIS clip prompt as it is now.

    The gen module should require this (not only gates.prompts_approved) before submitting a clip without --yes, so
    a clip locked or rewritten after the approval needs the owner again: `if not (yes or clip_prompt_approved(p, c))`.
    """
    if not (proj.get("gates") or {}).get("prompts_approved"):
        return False
    if clip_state(clip) == "delivered" and clip.get("status") != "delivered":
        return False      # "locked" only because a finalize was refused: a new paid take needs the owner's own yes
    metas = proj.get("gates_meta") if isinstance(proj.get("gates_meta"), dict) else {}
    covers = (metas.get("prompts_approved") or {}).get("covers") or {}
    cid = clip.get("id")
    return bool(cid) and covers.get(f"clips/{cid}.json") == clip_prompt_sig(clip)


def spend_frozen(proj: dict) -> dict | None:
    """{"at", "reason"} when the owner froze spending (`slop spend --freeze`), else None."""
    fr = (proj.get("budget") or {}).get("frozen")
    if not fr:
        return None
    return fr if isinstance(fr, dict) else {"at": None, "reason": str(fr)}


def gate_state(pdir: Path, proj: dict, key: str, clips: list | None = None) -> dict:
    """{approved, recorded, current, standing, at, covers, stale[], uncovered[], drafts[]} for one gate.

    approved = the owner approved something (the flag, or a recorded approval); current = nothing it covered changed
    and (prompts) every locked clip prompt is covered. standing (prompts only) = gates.prompts_approved, the flag the
    gen module treats as a standing yes for clip submits.
    """
    flag = bool((proj.get("gates") or {}).get(key))
    metas = proj.get("gates_meta") if isinstance(proj.get("gates_meta"), dict) else {}
    meta = metas.get(key) if isinstance(metas.get(key), dict) else None
    st: dict = {"gate": key, "flag": flag, "recorded": meta is not None, "at": None, "covers": {}, "stale": [],
                "uncovered": [], "drafts": [], "standing": flag if key == "prompts_approved" else None}
    if key == "prompts_approved":
        clips = clip_docs(pdir) if clips is None else clips
        st["drafts"] = [cid for cid, c in clips if c and c.get("status") == "draft"]
    if meta is not None:
        rec = meta.get("covers") if isinstance(meta.get("covers"), dict) else {}
        st["at"], st["covers"] = meta.get("at"), rec
        if key == "prompts_approved":
            now = gate_covers(pdir, key, clips)
            if rec.get("plates/prompts.md") != now.get("plates/prompts.md"):
                if now.get("plates/prompts.md") is None:
                    st["stale"].append("plates/prompts.md is gone")
                elif rec.get("plates/prompts.md") is None:  # a clip-only approval; the book came later
                    st["stale"].append("plates/prompts.md was written after the approval (the owner has not read it)")
                else:
                    st["stale"].append("plates/prompts.md changed since the approval")
            for rel, sig in now.items():
                if rel.startswith("clips/"):
                    cid = Path(rel).stem
                    if rel not in rec:
                        st["uncovered"].append(f"{cid} (new)")
                    elif rec[rel] != sig:
                        st["uncovered"].append(f"{cid} (prompt changed)")
        else:
            for rel, sig in rec.items():
                cur = util.file_sig(pdir / rel)
                if cur is None:
                    if key == "board_approved":
                        st["stale"].append(f"{rel} is gone")
                elif cur != sig:
                    st["stale"].append(f"{rel} changed since the approval")
    st["approved"] = flag or meta is not None
    st["current"] = st["approved"] and not st["stale"] and not st["uncovered"]
    return st


def gate_label(st: dict) -> str:
    if not st["approved"]:
        return "no"
    if not st["current"]:
        return "STALE (re-approve)"
    if st["gate"] == "prompts_approved" and not st["flag"]:
        return "plate book only (each clip submit needs --yes)"
    return "YES" if st["recorded"] else "YES (not recorded what)"


def _gate_stage(pdir: Path, proj: dict, key: str, do: str, clips: list | None = None) -> dict:
    short = GATE_SHORT[key]
    name, cmd = f"gate:{short}", _pcmd(pdir, f"gate {short} --approve")
    st = gate_state(pdir, proj, key, clips)
    if not st["approved"]:
        if key == "prompts_approved" and not (pdir / "plates/prompts.md").is_file():
            cl = clip_docs(pdir) if clips is None else clips
            if not any(c and clip_state(c) == "locked" for _, c in cl):
                if st["drafts"]:
                    return _stage(name, False, f"clip drafts not locked yet: {', '.join(st['drafts'])} (no plate book)",
                                  "finish each clip prompt (sung: the short sung form; motion: the screenplay; "
                                  "docs/60-clips §4) and lock it; then the owner reads the locked prompts with the "
                                  "estimate", _pcmd(pdir, "clip list"))
                return _stage(name, True, "nothing to approve (no plate book, no clip prompts)")
        return _stage(name, False, "not approved", do, cmd)
    if not st["recorded"]:
        return _stage(name, True, f"approved (which version was not recorded: re-run `{cmd}` after the owner's "
                                  "yes to record it)")
    when = st["at"] or "?"
    if not st["current"]:
        parts = list(st["stale"])
        if st["uncovered"]:
            parts.append(f"{len(st['uncovered'])} locked clip prompt(s) the owner has not approved: "
                         + ", ".join(st["uncovered"]))
        what = {"board_approved": f"show the owner the changed board ({_pcmd(pdir, 'board sheet')})",
                "prompts_approved": "the owner reads the new or changed prompts with the cost estimate before any "
                                    f"spend ({_pcmd(pdir, 'clip list')}); nothing is submitted until then",
                "v1_approved": "send the new out/review.mp4 to the owner"}[key]
        return _stage(name, False, f"approved {when}, but " + "; ".join(parts), f"{what}; after their yes:", cmd)
    detail = f"approved {when}"
    if key == "prompts_approved":
        nclips = sum(1 for r in st["covers"] if r.startswith("clips/"))
        if not st["covers"].get("plates/prompts.md"):
            detail += f" ({nclips} clip prompts; no plate book)"
        else:
            detail += f" (plate book + {nclips} clip prompts)" if nclips else " (plate book; no clip prompts locked yet)"
        if not st["flag"]:
            detail += "; clip submits need --yes each until the owner approves the locked clip prompts"
        if st["drafts"]:
            detail += f"; drafts not covered: {', '.join(st['drafts'])}"
    return _stage(name, True, detail)


# ====================================================================== stages
def evaluate_stages(pdir: Path, proj: dict) -> list[dict]:
    tier = proj.get("tier", "quick")
    S: list[dict] = []

    # 0 brief (the owner's ask, verbatim: binding on the storyboard and every agent prompt)
    ask = brief_ask(pdir)
    if ask:
        S.append(_stage("brief", True, f"BRIEF.md ask: {len(ask.split())} words"))
    else:
        S.append(_stage("brief", False, "BRIEF.md has no ask yet" if (pdir / "BRIEF.md").is_file() else "no BRIEF.md",
                        "record the owner's ask VERBATIM (dated) in BRIEF.md, then add the references they pointed "
                        "at (missing file: re-run `slop new NAME` to restore it)",
                        _pcmd(pdir, "brief \"<the owner's words, verbatim>\"")))

    # 1 song
    song = pdir / (proj.get("song") or "audio/song.wav")
    if song.is_file():
        S.append(_stage("song", True, f"{_rel(pdir, song)} ({util.human_bytes(song.stat().st_size)})"))
    else:
        others = sorted(p.name for p in (pdir / "audio").glob("*") if p.suffix.lower() in AUDIO_EXT) \
            if (pdir / "audio").is_dir() else []
        hint = f" (found audio/{others[0]} - ingest it)" if others else ""
        do = ("put the song master in place (the owner's Suno/WAV upload; a share link: "
              f"{_pcmd(pdir, 'fetch URL --to audio')}" +
              (", or generate one with Lyria via OpenRouter" if tier == "quick" else "") + "), then ingest it")
        if len(others) == 1:  # exactly one candidate: ingesting it IS the step
            S.append(_stage("song", False, f"no {_rel(pdir, song)}{hint}", do,
                            _pcmd(pdir, "song ingest " + shlex.quote(str(pdir / "audio" / others[0]))), auto=True))
        else:
            S.append(_stage("song", False, f"no {_rel(pdir, song)}{hint}", do,
                            _pcmd(pdir, "song ingest PATH/TO/song.wav")))

    # 2 lyrics (as sung)
    lyr_path = pdir / "lyrics/lyrics.txt"
    lyr = util.read_lyric_lines(lyr_path)
    if not lyr:
        S.append(_stage("lyrics", False, "lyrics/lyrics.txt has no lyric lines yet",
                        "write lyrics/lyrics.txt: the words AS SUNG, one line per line (rules: lyrics/README.md), "
                        "then lint it", _pcmd(pdir, "lyrics lint")))
    else:
        S.append(_stage("lyrics", True, f"{len(lyr)} lyric lines"))

    # 3 analysis (fresh: the analysed sheet is the current sheet, the song did not change after it)
    need = ["analysis/beats.json", "analysis/words.json", "analysis/hits.json"]
    missing = [n for n in need if not (pdir / n).is_file()]
    words_p = pdir / "analysis/words.json"
    if missing:
        S.append(_stage("analysis", False, "missing " + ", ".join(missing),
                        "analyse the song (stems, variable beat map, word alignment, hits), then check the ear-check "
                        "list in analysis/report.md BY EAR", _pcmd(pdir, "analyze"), auto=bool(lyr)))
    else:
        w = _json_or_none(words_p)
        stale: list[str] = []
        det = "beats, words, hits present"
        if isinstance(w, dict):
            det = f"{len(w.get('words', []))} aligned words, {len(w.get('gaps', []))} gaps to ear-check"
            wl = [re.sub(r"\s+", " ", str(x.get("text", ""))).strip() for x in (w.get("lines") or [])
                  if isinstance(x, dict)]
            if wl and lyr:
                cur = [re.sub(r"\s+", " ", x).strip() for x in lyr]
                if len(wl) != len(cur):
                    stale.append(f"analysis/words.json has {len(wl)} lines but lyrics.txt has {len(cur)}")
                else:
                    diff = [k for k, (a, b) in enumerate(zip(wl, cur, strict=True)) if a != b]
                    if diff:
                        stale.append(f"lyrics.txt line {diff[0] + 1} differs from the analysed text"
                                     + (f" (+{len(diff) - 1} more)" if len(diff) > 1 else ""))
            elif _newer(lyr_path, words_p):
                stale.append("lyrics/lyrics.txt changed after the analysis")
        elif w == "unreadable":
            stale.append("analysis/words.json is unreadable")
        if song.is_file() and _newer(song, words_p):
            stale.append(f"{_rel(pdir, song)} changed after the analysis")
        if stale:
            S.append(_stage("analysis", False, "STALE: " + "; ".join(stale),
                            "re-run the analysis on the current song and sheet, then re-check analysis/report.md by "
                            "ear (line numbers key everything downstream)", _pcmd(pdir, "analyze"),
                            auto=w != "unreadable"))
        else:
            if not (pdir / "analysis/report.md").is_file():
                det += "; no report.md"
            if sections_hint(pdir, None):
                det += "; sections unconfirmed (guessed: see the hint)"
            S.append(_stage("analysis", True, det))

    # 3b on-screen lyrics (as read): display.txt validated against the sheet and the timing
    dis_path, built = pdir / "lyrics/display.txt", pdir / "analysis/lyrics-display.json"
    dis = util.read_lyric_lines(dis_path)
    aligned = words_p.is_file()
    if not dis:
        S.append(_stage("display", False, "lyrics/display.txt has no lines yet",
                        "start the on-screen lyrics from the sheet, then edit lines that should read differently "
                        "(+25%|4, AGI|3)", _pcmd(pdir, "lyrics display --init --force"), auto=aligned and bool(lyr)))
    elif lyr and len(dis) != len(lyr):
        S.append(_stage("display", False, f"display.txt has {len(dis)} lines but lyrics.txt has {len(lyr)}; they "
                        "must match line for line", "fix lyrics/display.txt so line N shows line N of lyrics.txt",
                        _pcmd(pdir, "lyrics display")))
    elif not built.is_file():
        S.append(_stage("display", False, f"{len(dis)} display lines, not validated against the timing yet",
                        "validate display.txt against the aligned words", _pcmd(pdir, "lyrics display"), auto=aligned))
    elif _newer(dis_path, built) or _newer(words_p, built):
        S.append(_stage("display", False, "STALE: " + ("lyrics/display.txt" if _newer(dis_path, built)
                                                       else "analysis/words.json") + " changed after the last validation",
                        "re-validate display.txt against the current word timing", _pcmd(pdir, "lyrics display"),
                        auto=aligned))
    else:
        S.append(_stage("display", True, f"{len(dis)} display lines validated"))

    # 4 taste (optional). The taste module knows whether this project links to a trained user profile (then the
    # next step is writing this project's tokens, not tapping again); without the module, the file check.
    tt = pdir / "taste/taste-tokens.json"
    try:
        from slop.taste.profile import status_stage as _taste_stage
        ts = _taste_stage(pdir)
    except Exception:  # noqa: BLE001 - taste not installed (SLOP_MODULES) or an unreadable profile: the plain check
        ts = None
    if ts:
        nxt = str(ts.get("next") or "slop taste serve --tunnel").split("   ")[0].strip()
        nxt = nxt[len("slop "):] if nxt.startswith("slop ") else nxt
        do = ("write this project's taste tokens from the shared taste profile" if nxt.startswith("taste tokens") else
              "capture the owner's taste on their phone (tap app; no tunnel: `taste sheet` pair sheets in the chat), "
              "then write the tokens")
        S.append(_stage("taste", bool(ts.get("done")), str(ts.get("detail") or ""), do, _pcmd(pdir, nxt),
                        optional=True))
    else:
        S.append(_stage("taste", tt.is_file(), "taste/taste-tokens.json present" if tt.is_file()
                        else "no taste profile (optional; recommended for Studio/Director)",
                        "capture the owner's taste on their phone (tap app), then write the tokens",
                        _pcmd(pdir, "taste serve --tunnel"), optional=True))

    # 5 lead (identity is TEXT: the canon goes into every prompt with the lead)
    shots = _json_or_none(pdir / "board/shots.json")
    shot_list = [s for s in (shots.get("shots") or []) if isinstance(s, dict)] if isinstance(shots, dict) else []
    n_lead = sum(1 for s in shot_list if s.get("lead_on_screen"))
    lead = proj.get("lead") if isinstance(proj.get("lead"), dict) else {}
    canon = str(lead.get("canon") or "").strip()
    if lead.get("none") and not canon:
        S.append(_stage("lead", n_lead == 0, "no lead character (owner's decision: lead.none)" if n_lead == 0 else
                        f"lead.none is set but {n_lead} shots have the lead on screen",
                        "either take the lead out of those shots (lead_on_screen false) or write a canon",
                        _pcmd(pdir, 'lead --canon "TEXT" --far "SHORT TEXT"')))
    elif canon:
        det = f"lead.canon set ({len(canon.split())} words)"
        if not str(lead.get("far") or "").strip():
            det += "; no lead.far yet (full-length shots reuse the canon - a SHORT far variant frames better)"
        S.append(_stage("lead", True, det))
    else:
        required = tier != "quick" or n_lead > 0
        det = "no lead.canon in project.json" + (f" but {n_lead} shots have the lead on screen" if n_lead else "")
        S.append(_stage("lead", False, det,
                        "write the lead's canon with the owner in bible/LEAD.md (pin face, age, ethnicity, skin; "
                        "hair and marks; outfit; colour rules; 4 test plates, gate G3), then store the prompt text",
                        _pcmd(pdir, 'lead --canon "TEXT" --far "SHORT TEXT"'),
                        optional=not required))

    # 6 storyboard + audit
    if shots is None:
        S.append(_stage("board", False, "no board/shots.json",
                        "draft the storyboard from the analysis, then the lead fills its TODOs (docs/40-storyboard)",
                        _pcmd(pdir, "board draft"), auto=True))
    elif shots == "unreadable":
        S.append(_stage("board", False, "board/shots.json is not valid JSON", "fix board/shots.json",
                        _pcmd(pdir, "board audit")))
    else:
        n = len(shot_list)
        problem = board_audit_problem(pdir)
        if problem:
            S.append(_stage("board", False, f"{n} shots; {problem}",
                            "fix board/shots.json until every audit gate passes", _pcmd(pdir, "board audit"),
                            auto="FAILED" not in problem and "unreadable" not in problem))
        else:
            S.append(_stage("board", True, f"{n} shots; audit passed"))
    S.append(_gate_stage(pdir, proj, "board_approved",
                         f"make the contact sheet ({_pcmd(pdir, 'board sheet')}), send board/board.pdf to the owner; "
                         "after their yes:"))

    # 7 prompts + plates
    clips = clip_docs(pdir)
    pb = pdir / "plates/prompts.md"
    picks = _json_or_none(pdir / "plates/picks.json")
    npk = len(picks) if isinstance(picks, dict) else 0
    if pb.is_file():
        S.append(_stage("prompts", True, "plates/prompts.md present"))
    elif npk:  # the plates came from elsewhere (the owner's own images): no book to write
        S.append(_stage("prompts", True, f"no plates/prompts.md; {npk} plates already picked (made without a book)"))
    else:
        S.append(_stage("prompts", False, "no plates/prompts.md",
                        "write the prompt book from the board (docs/50-plates-midjourney, docs/51-plates-api)",
                        _pcmd(pdir, "plates book"), auto=True))
    S.append(_gate_stage(pdir, proj, "prompts_approved",
                         "the owner reads plates/prompts.md (and every locked clip prompt) with the cost estimate "
                         "before anything is generated; after their yes:", clips))
    S.append(_stage("plates", npk > 0, f"{npk} plates picked" if npk else "no plates/picks.json",
                    "generate or ingest plate candidates, pick one image per shot, then vary repeats",
                    _pcmd(pdir, "plates status")))

    # 8 clips
    S.append(_clips_stage(pdir, tier, clips, shots))

    # 9 edit + export
    blank = util.shots_without_picture(pdir) if (pdir / "edit/edl.json").is_file() else None
    if blank:
        S.append(_stage("edit", False, util.no_picture_text(blank).split(" — ")[0],
                        "give every shot a picture: pick plates (or make the clips), or mark code-drawn shots "
                        "(\"treatment\": \"pure-motion\"), then rebuild the edit", _pcmd(pdir, "edit edl")))
    else:
        S.append(_stage("edit", (pdir / "edit/edl.json").is_file(),
                        "edit/edl.json present" if (pdir / "edit/edl.json").is_file() else "no edit/edl.json",
                        "build the edit decision list", _pcmd(pdir, "edit edl"), auto=True))
    ep = export_problem(pdir)
    S.append(_stage("export", ep is None, "engine/assets current" if ep is None else ep,
                    "export the engine data (beats, lyrics, clips, edl, plates, shots)", _pcmd(pdir, "edit export"),
                    auto=(pdir / "edit/edl.json").is_file()))

    # 10 QA + render: lyric gate N/N, review copy, safety scan, v1
    lp = lyric_gate_problem(pdir)
    rep = _json_or_none(pdir / "render/lyrics-report.json")
    S.append(_stage("lyric-gate", lp is None,
                    f"{rep.get('drawn', rep.get('checked'))}/{rep.get('checked')} sung tokens on screen at their time"
                    if lp is None and isinstance(rep, dict) else lp,
                    "run the lyric gate: every sung word must be drawn at its aligned time (N/N) before any render "
                    "goes to the owner", _pcmd(pdir, "render lyrics"), auto=lp is not None and "FAILED" not in lp))
    et = engine_time(pdir)
    fs = frames_state(pdir, proj)
    ready = fs["ready"]

    def video_stale(p: Path) -> bool:
        """Older than the engine data - unless it was encoded from the current frames (same content fingerprint:
        an identical re-export changes file times only)."""
        m = _mtime(p) or 0
        if fs["by"] == "fingerprint" and fs["current"] and fs["newest"] is not None and m + EPS >= fs["newest"]:
            return False
        return et is not None and m + EPS < et

    if fs["complete"] and fs["current"] and fs["placeholders"]:  # drawn with --allow-missing: encode refuses them
        frames_do = ("the frames were drawn with --allow-missing (placeholders for missing media): add the missing "
                     f"files ({_pcmd(pdir, 'render info')} lists them), then render the frames again")
        step = mstep = _pcmd(pdir, "render info")
        auto_step = False
    else:
        frames_do = ""
        step = _pcmd(pdir, "render encode --review") if ready else _pcmd(pdir, "render frames")
        mstep = _pcmd(pdir, "render encode") if ready else _pcmd(pdir, "render frames")
        auto_step = True
    rv = [p for p in (pdir / "out/review.mp4", pdir / "out/master.mp4") if p.is_file()]
    if not rv:
        S.append(_stage("render", False, "no out/review.mp4" + ("; the frames are rendered" if ready else ""),
                        frames_do or f"contact sheet first ({_pcmd(pdir, 'render sheet')}), then render the frames "
                        f"({_pcmd(pdir, 'render frames')}) and encode a review copy "
                        f"({_pcmd(pdir, 'render encode --review')})", step, auto=auto_step))
    elif all(video_stale(p) for p in rv):
        S.append(_stage("render", False, f"STALE: {_rel(pdir, max(rv, key=lambda p: _mtime(p) or 0))} is older than "
                        "the engine data" + ("; the frames are re-rendered" if ready else ""),
                        frames_do or "re-render the frames and re-encode the review copy "
                        f"({_pcmd(pdir, 'render encode --review')})", step, auto=auto_step))
    else:
        S.append(_stage("render", True, ", ".join(f"{_rel(pdir, p)} ({util.human_bytes(p.stat().st_size)})"
                                                  for p in rv)))
    scan = scan_state(pdir)
    if scan["played"]:  # the edit plays generated clips: they must pass the safety + canon scan before v1 / master
        sdo, scmd, sauto = scan_step(pdir, scan["step"])
        S.append(_stage("scan", scan["problem"] is None,
                        f"{len(scan['played'])} generated takes in the edit; safety scan clear (0 open blocks)"
                        if scan["problem"] is None else scan["problem"],
                        "safety + canon scan of every generated take the edit plays (docs/80-review-qa §9): " + sdo,
                        scmd, auto=sauto))
    S.append(_gate_stage(pdir, proj, "v1_approved", "send out/review.mp4 to the owner; after their yes:"))

    # 11 deliver: master, flash + history check, 9:16 cut
    master = pdir / "out/master.mp4"
    if not master.is_file():
        S.append(_stage("master", False, "no out/master.mp4",
                        frames_do or "encode the master (BT.709 tags, CRF 16, ffprobe-verified) from the "
                        "full-resolution frames"
                        + ("" if ready else f" (render the frames first, then: {_pcmd(pdir, 'render encode')})"),
                        mstep, auto=auto_step))
    elif video_stale(master):
        S.append(_stage("master", False, "STALE: out/master.mp4 is older than the engine data",
                        frames_do or "re-render the frames and re-encode the master"
                        + ("" if ready else f" (frames first, then: {_pcmd(pdir, 'render encode')})"), mstep,
                        auto=auto_step))
    else:
        S.append(_stage("master", True, f"out/master.mp4 ({util.human_bytes(master.stat().st_size)})"))
    S.append(_checks_stage(pdir, master))
    vert = pdir / "out/vertical.mp4"
    if not vert.is_file():
        S.append(_stage("vertical", False, "no out/vertical.mp4",
                        "make the 9:16 cut (1080x1920) for Shorts/Reels/TikTok", _pcmd(pdir, "render vertical"),
                        auto=True))
    elif et is not None and (_mtime(vert) or 0) + EPS < et:
        S.append(_stage("vertical", False, "STALE: out/vertical.mp4 is older than the engine data",
                        "re-make the 9:16 cut", _pcmd(pdir, "render vertical"), auto=True))
    else:
        S.append(_stage("vertical", True, f"out/vertical.mp4 ({util.human_bytes(vert.stat().st_size)})"))
    return S


def _clips_stage(pdir: Path, tier: str, clips: list, shots) -> dict:
    optional = tier == "quick"
    if not clips:
        return _stage("clips", False, "no clips/*.json" + (" (Quick tier: optional - 2.5D plates can carry it)"
                                                           if optional else ""),
                      "plan motion/sung clips from the storyboard, estimate, then generate after the owner's OK",
                      _pcmd(pdir, "clip new --help"), optional=optional)
    by_id = {cid: c for cid, c in clips if c}
    refs = _board_clip_refs(shots)

    def on_board(cid: str, c: dict) -> bool:
        if refs is None:
            return True
        root, seen = cid, set()
        while root not in seen:
            seen.add(root)
            if root in refs:
                return True
            parent = (by_id.get(root) or {}).get("parent")
            if not parent:
                break
            root = parent
        return False

    counts: dict[str, int] = {}
    pending, decide, unsynced, unreadable, dropped, fin = [], [], [], [], [], []
    rejected, no_job = [], []
    for cid, c in clips:
        if c is None:
            unreadable.append(cid)
            continue
        s = clip_state(c)
        counts[s] = counts.get(s, 0) + 1
        ff = failed_finalize(c) if s == "delivered" else None
        if ff:
            why = re.sub(r"^\s*(rejected|failed)\s*:\s*", "", str(ff.get("error") or ""), flags=re.I).strip()
            rejected.append(f"finalize {finalize_label(ff)}: {cid} take {ff.get('n')} (1080p, of take "
                            f"{ff.get('finalize_of')}" + (f": {why[:120]}" if why else "") + ") - not charged, the "
                            f"edit keeps take {(_chosen_take(c) or {}).get('n')}")
        if s == "submitted":
            for t in requested_takes(c):
                what = f"the finalize of take {t['finalize_of']}" if t.get("finalize_of") else "Higgsfield"
                no_job.append(f"{cid} take {t.get('n')} ({what}) is only requested, no job id recorded: run its "
                              f"request file, then {_pcmd(pdir, f'clip ingest {cid} --job-id JOB_ID --pending')}; if "
                              f"the connector refused it, {_pcmd(pdir, f'clip ingest {cid} --failed')} "
                              "\"rejected: <its reply, verbatim>\" (nothing was charged); not sure: look for its job "
                              "in the connector's `transactions` first")
        if s != "delivered" and not on_board(cid, c):
            dropped.append(cid)
        elif s in CLIP_PENDING:
            pending.append(cid)
        elif s in ("failed", "declined"):
            decide.append(f"{cid} {s}")
        elif s == "delivered" and c.get("kind") == "sung":
            tk = _chosen_take(c)
            if not tk or not (tk.get("sync") or {}).get("mode"):
                unsynced.append(cid)
                if tk and tk.get("needs_sync"):                      # a 1080p finalize: the edit already cuts it
                    fin.append(f"{cid} take {tk.get('n')} (the finalize of take {tk.get('finalize_of')}: edit/render "
                               "use it at once, with no lag correction until it is measured)")
    det = f"{len(clips)} clips: " + ", ".join(f"{v} {k}" for k, v in sorted(counts.items()))
    if rejected:
        det += "; " + "; ".join(rejected)
    if no_job:
        det += "; " + "; ".join(no_job)
    if dropped:
        det += f"; not on the board (ignored): {', '.join(dropped)}"
    if unreadable:
        return _stage("clips", False, det + f"; unreadable: {', '.join(unreadable)}",
                      "fix the unreadable clip files (valid JSON)", _pcmd(pdir, "clip list"), optional=optional)
    if pending:
        close = ""
        if no_job:                                   # `slop next` prints only do + cmd: name the requests here
            names = [x.split(" (", 1)[0] for x in no_job]
            one = names[0].split(" ", 1)[0] if len({n.split(" ", 1)[0] for n in names}) == 1 else "CLIP"
            close = (f"close the Higgsfield request{'s' if len(names) > 1 else ''} with no job id ({', '.join(names)}): "
                     f"record the job id ({_pcmd(pdir, f'clip ingest {one} --job-id JOB_ID --pending')}), or if the "
                     f"connector refused it: {_pcmd(pdir, f'clip ingest {one} --failed')} \"rejected: <its reply, "
                     "verbatim>\" (it then counts 0); then ")
        return _stage("clips", False, det, close + "finish the pending clips: lock each, the owner reads "
                      "the locked prompts (gate prompts), then submit, poll and sync", _pcmd(pdir, "clip list"),
                      optional=optional)
    if decide:
        return _stage("clips", False, det + f"; needs a decision: {', '.join(decide)}",
                      "for each failed/declined clip: retry on the other provider with the UNALTERED image (slop clip "
                      "set ID --provider higgsfield|openrouter, lock, submit) or cut away (give that shot a plate "
                      "instead of the clip in board/shots.json, then re-audit). Never alter an image to pass a filter",
                      _pcmd(pdir, "clip list"), optional=optional)
    if unsynced:
        return _stage("clips", False, det + f"; lip sync not measured: {', '.join(unsynced)}"
                      + "".join(f"; {x}" for x in fin),
                      "measure the lip sync of every delivered sung take (rule 6), then cover or cut divergences",
                      _pcmd(pdir, f"clip sync {unsynced[0]}"), optional=optional, auto=True)
    return _stage("clips", True, det, optional=optional)


def _checks_stage(pdir: Path, master: Path) -> dict:
    cmd = _pcmd(pdir, "render check")
    do = "run the flash check (3 flashes/s or fewer, WCAG 2.3.1) on the master and the history check"
    if not master.is_file():
        return _stage("checks", False, "no out/master.mp4 to check yet", do, cmd)
    cj_p = pdir / "render/check.json"
    cj = _json_or_none(cj_p)
    if cj is None:
        return _stage("checks", False, "flash + history check not run", do, cmd, auto=True)
    if not isinstance(cj, dict):
        return _stage("checks", False, "render/check.json is unreadable", do, cmd, auto=True)
    probs = []
    fl, hi = cj.get("flash"), cj.get("history")
    if not isinstance(fl, dict) or "pass" not in fl:
        probs.append("flash check not run")
    elif fl.get("pass") is not True:
        probs.append(f"flash check FAILED (worst {fl.get('worst_per_second', '?')}/s, limit {fl.get('limit', 3)}): "
                     "slow or soften the flashing seconds")
    if not isinstance(hi, dict) or "ok" not in hi:
        probs.append("history check not run")
    elif hi.get("ok") is not True:
        probs.append("history check FAILED (a frame depends on what was rendered before it)")
    if _newer(master, cj_p):
        probs.append("out/master.mp4 changed after the last check")
    if probs:
        return _stage("checks", False, "; ".join(probs), do, cmd, auto=not any("FAILED" in p for p in probs))
    return _stage("checks", True, f"flash PASS (worst {fl.get('worst_per_second', '?')}/s), history PASS")


# ====================================================================== status
def _ledger_rows(pdir: Path) -> tuple[list[dict], int]:
    p = ledger_path(pdir)
    if not p.is_file():
        return [], 0
    rows, bad = [], 0
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
            if isinstance(r, dict):
                rows.append(r)
            else:
                bad += 1
        except ValueError:
            bad += 1
    return rows, bad


def _requested_keys(pdir: Path) -> dict[tuple[str, str, str], str]:
    """{(provider, clip, take): "CLIP take N"} of the Higgsfield takes still "requested" with no job id."""
    out = {}
    for cid, c in clip_docs(pdir):
        for t in requested_takes(c) if c else []:
            out[("higgsfield", str(cid), str(t.get("n")))] = f"{cid} take {t.get('n')}"
    return out


def ledger_summary(pdir: Path, proj: dict) -> dict:
    """Ledger totals by provider. A row voided by a later settlement (the take was reported failed / rejected /
    uncharged: ledger.voided) counts nothing; Higgsfield credits of requests with no job id recorded yet are counted
    (the budget stays safe) and also shown apart as "requested" (+ "requested_takes")."""
    rows, bad = _ledger_rows(pdir)
    void = voided(rows)
    asked = _requested_keys(pdir)
    by: dict[str, dict] = {}
    active_hedra, confirmed_in_ledger = set(), set()
    for i, r in enumerate(rows):
        prov = str(r.get("provider") or "?")
        b = by.setdefault(prov, {"calls": 0, "est_usd": 0.0, "real_usd": 0.0, "credits": 0.0,
                                 "declined": 0, "failed": 0, "other": 0})
        u = r.get("units") if isinstance(r.get("units"), dict) else {}
        b["calls"] += 0 if u.get("settles") or u.get("cost_confirmation") else 1           # a settlement closes a call; it is not another one
        st = r.get("status")
        if i in void:
            continue
        if st in COUNTED:
            b["est_usd"] += float(r.get("est_usd") or 0)
            b["credits"] += float(r.get("credits") or 0)
            if isinstance(r.get("real_usd"), (int, float)):
                b["real_usd"] += float(r["real_usd"])
            k = (prov, str(u.get("clip")), str(u.get("take")))
            if prov == "hedra" and u.get("clip") is not None and u.get("take") is not None:
                active_hedra.add(k)
                if isinstance(r.get("real_usd"), (int, float)):
                    confirmed_in_ledger.add(k)
            if k in asked and r.get("credits"):
                b["requested"] = b.get("requested", 0.0) + float(r["credits"])
                b.setdefault("requested_takes", [])
                if asked[k] not in b["requested_takes"]:
                    b["requested_takes"].append(asked[k])
        elif st == "declined":
            b["declined"] += 1
        elif st == "failed":
            b["failed"] += 1
        else:
            b["other"] += 1
    # Older Hedra ingests saved confirmed cost only on the take. Read it without
    # rewriting history, and never add it again when a ledger confirmation exists.
    if active_hedra - confirmed_in_ledger:
        import math
        for cid, c in clip_docs(pdir):
            for tk in (c or {}).get("takes", []):
                key = ("hedra", str(cid), str(tk.get("n")))
                cost = tk.get("cost_usd")
                if (key in active_hedra - confirmed_in_ledger and tk.get("provider") == "hedra"
                        and tk.get("currency") == "USD" and isinstance(cost, (int, float))
                        and not isinstance(cost, bool) and math.isfinite(cost) and cost >= 0):
                    by["hedra"]["real_usd"] += cost
                    confirmed_in_ledger.add(key)
    for b in by.values():
        for k in ("est_usd", "real_usd", "credits", "requested"):
            if k in b:
                b[k] = round(b[k], 4)
    budget = proj.get("budget", {}) or {}
    cap_usd = float(budget.get("openrouter_usd") or 0)
    cap_cr = float(budget.get("higgsfield_credits") or 0)
    or_est = by.get("openrouter", {}).get("est_usd", 0.0)
    hf_cr = by.get("higgsfield", {}).get("credits", 0.0)
    return {
        "by_provider": by, "rows": len(rows), "bad_lines": bad,
        "total_est_usd": round(sum(b["est_usd"] for b in by.values()), 4),
        "budget": {"openrouter_usd": cap_usd, "openrouter_left_usd": round(cap_usd - or_est, 4) if cap_usd else None,
                   "higgsfield_credits": cap_cr, "higgsfield_left": round(cap_cr - hf_cr, 2) if cap_cr else None,
                   "hedra_usd": float(budget.get("hedra_usd") or 0),
                   "hedra_credits": float(budget.get("hedra_credits") or 0),
                   "confirm_over_usd": budget.get("confirm_over_usd"),
                   "uncapped": {key: not bool(float(budget.get(key) or 0)) for key in
                                ("openrouter_usd", "higgsfield_credits", "hedra_usd", "hedra_credits")}},
    }


def _own_job_id() -> str | None:
    """The id of the background job this process runs inside (env SLOP_JOB_ID), so it never waits for itself."""
    return os.environ.get("SLOP_JOB_ID") or None


def _running(jobs: list[dict]) -> list[dict]:
    me = _own_job_id()
    return [j for j in jobs if j.get("state") not in ("done", "failed", "stopped") and j.get("id") != me]


def last_same_job(pdir: Path, cmd: str) -> dict | None:
    """The newest background job of this project that ran exactly this step (None if none; never raises)."""
    try:
        from .job import last_job
        return last_job(pdir, cmd_words(cmd))
    except Exception:  # noqa: BLE001 - a broken job record must not break status
        return None


REPEAT = {"failed": "last-failed", "stopped": "last-stopped", "done": "last-no-progress"}


def project_status(pdir: Path, tree: dict | None | bool = False, proj: dict | None = None) -> dict:
    """Stages, gates and spend of one project. tree=False builds the command tree; pass one to reuse it.

    next: {stage, do, cmd, step_cmd, ...}. cmd is what to run now: for a long step its `job start` form (step_cmd keeps
    the plain command; a weaker operator must never run a long step in the foreground: the shell time limit kills it);
    while a job already runs this step, its wait command. repeat/last_job: the newest job that ran this step ended
    (failed / stopped / done) and status reads exactly as it did when that job started - nothing changed, so running
    it again would not help (`slop next` does not; read the job first). first: a command that must come before this
    step (the sections confirmation before `board draft`)."""
    proj = load_project_checked(pdir) if proj is None else proj
    tier = proj.get("tier", "quick")
    stages = evaluate_stages(pdir, proj)
    sig = status_signature(stages)
    if tree is False:
        tree = command_tree()
    for s in stages:
        s["cmd_available"] = command_available(s["cmd"], tree) if s["cmd"] else None
        if s["cmd"] and not s["done"] and is_long(s["cmd"]):
            s["job_cmd"] = job_cmd(pdir, s["cmd"])
    nxt = next((s for s in stages if not s["done"] and not s["optional"]), None)
    jobs = project_jobs_safe(pdir)
    running = _running(jobs)
    hints = [h for h in (sections_hint(pdir, tree if isinstance(tree, dict) else None),) if h]
    nx = None
    if nxt:
        step = nxt["cmd"]
        nx = {"stage": nxt["stage"], "do": nxt["do"], "cmd": step, "step_cmd": step,
              "cmd_available": nxt["cmd_available"], "auto": nxt["auto"], "long": bool(step) and is_long(step)}
        path = _cmd_path(step)
        same = [j for j in running if path and tuple(j.get("argv") or [])[:len(path)] == path]
        if same:  # this very step is already running as a job: the next thing to do is wait for it
            j = same[0]
            nx.update(running_job=j["id"], cmd=j["wait"],
                      do=f"wait for job {j['id']} - it is running this step ({' '.join(path)}); repeat the wait until "
                         "it has finished", cmd_available=command_available(j["wait"], tree))
        else:
            if nx["long"]:
                from .job import default_wait
                nx["job_cmd"] = nx["cmd"] = job_cmd(pdir, step)
                nx["then"] = ("it prints the job id and its wait command at once; run that wait command (it returns "
                              f"within ~{default_wait():g} s) again and again until the job has finished")
            if nxt["cmd_available"] is False:
                nx["note"] = (f"'{step}' is not available in this install; see `slop --help` and the README "
                              "command index")
            last = last_same_job(pdir, step) if step else None
            if last and last.get("state") in REPEAT and last.get("status_sig") == sig:
                nx["repeat"] = REPEAT[last["state"]]
                nx["last_job"] = {"id": last["id"], "state": last["state"], "error": last.get("error"),
                                  "finished": last.get("finished"), "read": job_read_cmd(last)}
            if path[:2] == ("board", "draft"):
                sec = next((h for h in hints if h.get("kind") == "sections"), None)
                if sec:
                    nx["first"] = sec["cmd"]
                    nx["first_why"] = ("the song's sections are GUESSED and they set the storyboard's pace: confirm "
                                       "or fix them first (listen with analysis/report.md open, and check its ear-check "
                                       "lines BY EAR too)")
    gates = {k: bool(v) for k, v in (proj.get("gates") or {}).items()}
    clips = clip_docs(pdir)
    gstate = {k: gate_state(pdir, proj, k, clips) for k in DEFAULT_GATES}
    spend = ledger_summary(pdir, proj)
    return {"project": str(pdir), "name": proj.get("name", pdir.name), "title": proj.get("title"), "tier": tier,
            "stages": stages, "gates": gates,
            "gate_state": {k: {"label": gate_label(v), "current": v["current"], "at": v["at"],
                               "stale": v["stale"] + v["uncovered"]} for k, v in gstate.items()},
            "spend": spend, "frozen": spend_frozen(proj), "jobs": jobs, "jobs_running": len(running),
            "hints": hints, "signature": sig, "next": nx}


def job_read_cmd(j: dict) -> str:
    """`slop --project X job status ID` for a job summary (its result, error and log tail)."""
    return j["wait"].replace(" wait ", " status ").rsplit(" --max", 1)[0]


def project_jobs_safe(pdir: Path) -> list[dict]:
    """Running (and finished-but-unread) background jobs of a project; never raises (status must always work)."""
    try:
        from .job import project_jobs
        return project_jobs(pdir)
    except Exception:  # noqa: BLE001 - a broken job record must not break status
        return []


def _job_line(j: dict) -> str:
    from .job import dur, progress_text
    st = j.get("state")
    pt = progress_text(j.get("progress"))
    if st in ("done", "failed", "stopped"):
        return f"  job {j['id']} {st.upper() if st != 'done' else 'finished'} ({j.get('cmd')})  -> read it: {job_read_cmd(j)}"
    return (f"  job {j['id']} running {dur(j.get('elapsed_s'))}" + (f" [{pt}]" if pt else "") + f": {j.get('cmd')}"
            f"\n      wait: {j['wait']}")


def _repeat_lines(nx: dict) -> list[str]:
    lj = nx["last_job"]
    what = {"last-failed": f"FAILED ({lj.get('error') or 'see its log'})",
            "last-stopped": "was stopped (`slop job stop`)",
            "last-no-progress": "finished, but this stage is still open"}[nx["repeat"]]
    return [f"      last run: job {lj['id']} {what}, and nothing status can see has changed since it started.",
            f"      read it first: {lj['read']}",
            "      then fix the cause (or the input it complains about) before starting it again"]


def _cap_text(value, unit):
    return f"{value:g} {unit}" if value else "no cap (0 = unlimited)"


def next_lines(pdir: Path, nx: dict, offer_next: bool = True) -> list[str]:
    """The 'next:' block of `slop status` (and of `slop next` when it stops)."""
    lines = [f"next: {nx['do']}"]
    if nx.get("first"):
        lines.append(f"      FIRST: {nx['first_why']}:")
        lines.append(f"      {nx['first']}")
        lines.append("      then:")
    if nx.get("cmd"):
        lines.append(f"      {nx['cmd']}" + ("   (not installed in this build)" if nx.get("cmd_available") is False
                                             else ""))
    if nx.get("job_cmd") and not nx.get("running_job"):
        lines.append(f"      (a long step, so it runs as a background job: {nx['then']})")
    if nx.get("repeat"):
        lines += _repeat_lines(nx)
    elif offer_next and nx.get("auto") and not nx.get("running_job") and not nx.get("first") \
            and next_blocker(nx) is None:
        lines.append(f"      (or let slop run it: {_pcmd(pdir, 'next')})")
    return lines


def _requested_note(hf: dict) -> str:
    if not hf.get("requested"):
        return ""
    return (f" ({hf['requested']:g} of them only requested, no job id yet: "
            f"{', '.join(hf.get('requested_takes') or [])})")


def cmd_status(args) -> dict:
    pdir = _resolve(args)
    st = project_status(pdir)
    lines = [f"{st['name']} - \"{st['title']}\" (tier {st['tier']})  {pdir}"]
    if st["frozen"]:
        lines.append(f"SPENDING FROZEN since {st['frozen'].get('at')}: {st['frozen'].get('reason')} - no paid call "
                     f"until the owner's flag is resolved ({_pcmd(pdir, 'spend --unfreeze')})")
    lines.append("stages:")
    for s in st["stages"]:
        mark = "done" if s["done"] else ("opt " if s["optional"] else "todo")
        lines.append(f"  {mark}  {s['stage']:<15} {s['detail']}")
    lines.append("gates: " + " | ".join(f"{GATE_SHORT.get(k, k)} {v['label']}" for k, v in st["gate_state"].items()))
    sp = st["spend"]
    b = sp["budget"]
    or_ = sp["by_provider"].get("openrouter", {})
    hf = sp["by_provider"].get("higgsfield", {})
    lines.append(f"spend (ledger estimate): openrouter {util.money(or_.get('est_usd', 0))} of "
                 f"{_cap_text(b['openrouter_usd'], 'USD')} cap | higgsfield {hf.get('credits', 0):g} of "
                 f"{_cap_text(b['higgsfield_credits'], 'credits')}" + _requested_note(hf) + f"   (real spend: {_pcmd(pdir, 'spend')})")
    hd = sp["by_provider"].get("hedra", {})
    lines.append(f"Hedra: {hd.get('est_usd', 0):g} USD / {hd.get('credits', 0):g} credits; "
                 f"USD cap: {_cap_text(b['hedra_usd'], 'USD')}; "
                 f"credit cap: {_cap_text(b['hedra_credits'], 'credits')}")
    if sp["bad_lines"]:
        lines.append(f"WARNING: ledger.jsonl has {sp['bad_lines']} unreadable lines")
    if st["jobs"]:
        lines.append("background jobs:")
        lines += [_job_line(j) for j in st["jobs"]]
    for h in st["hints"]:
        lines.append(f"hint: {h['text']}")
    nx = st["next"]
    if nx:
        lines += next_lines(pdir, nx)
    else:
        lines.append("all stages done. Before posting: label it as AI-generated and write the posting copy "
                     "(docs/90-master-publish).")
    st["text"] = "\n".join(lines)
    return st


# ====================================================================== next
WHY = {
    "done": "every stage is done",
    "job-running": "a background job is running",
    "owner-gate": "this is the OWNER's decision: show them what the stage says, and only after their yes run the "
                  "command",
    "manual": "this step needs your work first (writing, choosing, or the owner's material); do it, then run the "
              "command",
    "sections": "the song's sections are guessed: confirm or fix them first (the FIRST command above), then run "
                "`next` again",
    "not-free": "this step can spend money or is not on the free list: run it yourself after the estimate and the "
                "owner's OK",
    "not-installed": "that command is not installed in this build",
    "no-progress": "the step ran but the stage is still open: read its output above",
    "failed": "the step failed: read its error above",
    "last-failed": "the last run of this step failed and nothing changed since: read that job (command above), fix "
                   "the cause, then start it again yourself (or: next --retry)",
    "last-stopped": "the last run of this step was stopped and nothing changed since: start it again yourself if "
                    "that is still wanted (or: next --retry)",
    "last-no-progress": "the last run of this step finished but the stage is still open and nothing changed since: "
                        "read that job's result (command above) - running it again would not help",
    "job-started": "a long step was started in the background",
    "time": "this call has run long enough (SLOP_WAIT_MAX): run `next` again to continue",
    "steps": "ran the number of steps asked for (--steps)",
}


def next_blocker(nx: dict | None, retry: bool = False) -> str | None:
    """Why `slop next` must not run the next step by itself (None = it may)."""
    if nx is None:
        return "done"
    if nx.get("running_job"):
        return "job-running"
    cmd = nx.get("step_cmd") or nx.get("cmd") or ""
    if nx["stage"].startswith("gate:") or _cmd_path(cmd)[:1] in (("gate",), ("spend",), ("lead",), ("brief",)):
        return "owner-gate" if nx["stage"].startswith("gate:") or _cmd_path(cmd)[:1] == ("gate",) else "manual"
    if not cmd:
        return "manual"
    if nx.get("cmd_available") is False:
        return "not-installed"
    if not nx.get("auto") or PLACEHOLDER_RE.search(" ".join(cmd_words(cmd))):
        return "manual"
    if not is_free_step(cmd):
        return "not-free"
    if nx.get("first"):
        return "sections"
    if nx.get("repeat") and not retry:
        return nx["repeat"]
    return None


def _run_inline(pdir: Path, cmd: str, free_only: bool, timeout: float | None) -> dict:
    """Run one slop command in a child process (`--json`); returns its JSON object (ok false on any failure)."""
    import subprocess
    import sys
    from .job import _child_env
    argv = [sys.executable, "-m", "slop", "--json", "--project", str(pdir), *cmd_words(cmd)]
    env = _child_env({"SLOP_FREE_ONLY": "1"} if free_only else {})
    try:
        cp = subprocess.run(argv, stdout=subprocess.PIPE, stderr=None, stdin=subprocess.DEVNULL, env=env,
                            timeout=timeout, text=True, encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"timed out after {timeout:g} s; run it as a job: {job_cmd(pdir, cmd)}"}
    for line in reversed([ln for ln in (cp.stdout or "").splitlines() if ln.strip()]):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if isinstance(d, dict):
            d.setdefault("ok", cp.returncode == 0)
            return d
    return {"ok": False, "error": f"exit code {cp.returncode} and no JSON result: " + (cp.stdout or "").strip()[-400:]}


def cmd_next(args) -> dict:
    from .job import default_wait
    pdir = _resolve(args)
    steps = max(1, min(int(args.steps or 1), 20))
    retry = bool(getattr(args, "retry", False))
    budget = default_wait()  # never start another inline step once this call has run that long
    t_start = time.monotonic()
    ran: list[dict] = []
    lines: list[str] = []
    why = None
    tree = command_tree()
    prev = None
    st = project_status(pdir, tree=tree)
    for k in range(steps):
        nx = st["next"]
        running = _running(st.get("jobs") or [])
        why = next_blocker(nx, retry=retry and k == 0)
        if why is None and running:
            why = "job-running"
        if why is None and prev == (nx["stage"], nx["step_cmd"]):
            why = "no-progress"
        if why is None and ran and time.monotonic() - t_start > budget:
            why = "time"
        if why:
            break
        cmd = nx["step_cmd"]
        prev = (nx["stage"], cmd)
        if args.dry_run:
            lines.append(f"would run: {nx['cmd'] if nx['long'] and not args.fg else cmd}"
                         + ("  (a background job)" if nx["long"] and not args.fg else ""))
            why = "steps"
            break
        if nx["long"] and not args.fg:
            from .job import start
            r = start(cmd_words(cmd), project=str(pdir), free_only=args.free_only, status_sig=st.get("signature"))
            j = r["job"]
            ran.append({"stage": nx["stage"], "cmd": cmd, "mode": "job", "job": j})
            lines.append(f"started job {j['id']} (stage {nx['stage']}): {cmd}" +
                         (" - it was already running" if r["existing"] else ""))
            lines.append(f"  it runs in the background; next:  {j['wait']}   (repeat until it has finished)")
            why = "job-started"
            break
        res = _run_inline(pdir, cmd, args.free_only, None if args.fg else 900)
        ok = res.get("ok", True) is not False
        ran.append({"stage": nx["stage"], "cmd": cmd, "mode": "inline", "ok": ok, "result": res})
        lines.append(f"ran (stage {nx['stage']}): {cmd}")
        body = str(res.get("text") or res.get("error") or "").rstrip()
        if body:
            blines = body.splitlines()
            lines += ["  " + ln for ln in blines[:40]] + ([f"  ... ({len(blines) - 40} more lines)"]
                                                          if len(blines) > 40 else [])
        if not ok:
            lines.append(f"  FAILED: {res.get('error')}")
            why = "failed"
            st = project_status(pdir, tree=tree)
            break
        st = project_status(pdir, tree=tree)
    else:
        why = "steps"
    nx = st["next"]
    if why == "job-started":
        pass
    elif nx:
        lines += next_lines(pdir, nx, offer_next=False)
        if why in ("failed", "no-progress", "time"):
            lines.append(f"stopped: {WHY[why]}")
        elif why and why != "steps":
            lines.append(f"not run by `slop next`: {WHY.get(why, why)}")
            if why == "job-running" and not nx.get("running_job"):
                for j in _running(st.get("jobs") or []):
                    lines.append(f"  job {j['id']} ({j.get('cmd')}) - wait for it first: {j['wait']}")
        elif why == "steps" and next_blocker(nx) is None and not args.dry_run:
            lines.append(f"      (run it: {_pcmd(pdir, 'next')})")
    else:
        lines.append("all stages done. Before posting: label it as AI-generated and write the posting copy "
                     "(docs/90-master-publish).")
    for h in st.get("hints") or []:
        lines.append(f"hint: {h['text']}")
    failed = any(r.get("mode") == "inline" and not r.get("ok") for r in ran)
    out = {"ran": ran, "ran_count": len(ran), "stopped": why, "why": WHY.get(why, why), "next": nx,
           "hints": st.get("hints") or [], "jobs": st.get("jobs") or [], "free_only": bool(args.free_only),
           "elapsed_s": round(time.monotonic() - t_start, 2), "text": "\n".join(lines)}
    if failed:
        out["ok"] = False
        out["error"] = f"the step failed: {ran[-1]['result'].get('error')}"
    return out


def cmd_projects(args) -> dict:
    root = Path(args.root).expanduser() if getattr(args, "root", None) else projects_root()
    rows = list_projects(root)
    if not rows:
        return {"root": str(root), "projects": [], "count": 0,
                "text": f"no projects in {root} yet - create one with: slop new NAME --title \"Title\" --tier quick"}
    tbl = util.table([[r["name"], r.get("tier") or "?", (r.get("title") or "")[:28], r.get("next", ""), r["updated"]]
                      for r in rows], ["name", "tier", "title", "next stage", "project.json changed"])
    return {"root": str(root), "projects": rows, "count": len(rows),
            "text": f"projects in {root}:\n{tbl}\nopen one with: slop --project NAME status"}


# ====================================================================== lead
LEAD_FIELDS = ("canon", "far", "possessive", "noun", "pronoun")


def cmd_lead(args) -> dict:
    if args.none and (args.canon or args.far):
        raise SlopError("--none means the video has no lead character: pass either --none or --canon/--far, not both")
    pdir = _resolve(args)
    proj = load_project_checked(pdir)
    lead = proj.get("lead") if isinstance(proj.get("lead"), dict) else {}
    changes: dict = {}
    for f in LEAD_FIELDS:
        v = getattr(args, f, None)
        if v is None:
            continue
        v = re.sub(r"\s+", " ", v).strip()
        if f == "pronoun" and v:
            v = v.capitalize()
        if lead.get(f) != v:
            changes[f] = v
    if args.none and not lead.get("none"):
        changes["none"] = True
    elif changes.get("canon") and lead.get("none"):
        changes["none"] = False  # a canon means there is a lead after all
    dec = None
    if changes:
        lead.update(changes)
        proj["lead"] = lead
        save_project(pdir, proj)
        text = "lead " + "; ".join(f"{k} = \"{v}\"" for k, v in changes.items() if k != "none")
        if changes.get("none") is True:
            text = "no lead character in this video" + (f"; {text}" if len(changes) > 1 else "")
        dec = append_decision(pdir, text, by=args.by)
    from .gen.templates import lead_words
    effective = lead_words(proj)
    show = {f: lead.get(f) or effective.get(f, "") for f in LEAD_FIELDS}
    asked = bool(args.none) or any(getattr(args, f, None) is not None for f in LEAD_FIELDS)
    lines = [("updated: " + ", ".join(changes) + " (logged in DECISIONS.md)") if changes else
             ("no change" if asked else "the lead:")]
    for f in LEAD_FIELDS:
        lines.append(f"  {f:<10} {show[f] or '-'}")
    if lead.get("none"):
        lines.append("lead.none: the owner decided there is no lead character (set board.lead_min to 0 in "
                     "project.json for the board audit)")
    elif not show["canon"]:
        lines.append("lead.canon is empty: write it with the owner in bible/LEAD.md (pin face, age, ethnicity, skin; "
                     "hair/marks; outfit), then: " + _pcmd(pdir, 'lead --canon "TEXT" --far "SHORT TEXT"'))
    lines.append("canon = close/medium framings (framing words FIRST in the prompt, then the canon); far = a SHORT "
                 "variant for full-length shots; never use a face image as the identity reference")
    return {"lead": show, "none": bool(lead.get("none")), "changed": sorted(changes), "decision": dec,
            "text": "\n".join(lines)}


# ====================================================================== project set / show
PROJECT_TOP = ("title", "tier", "song", "fps", "size", "lead", "look", "mj", "models", "budget", "board", "audio",
               "chrome", "looks")
REFUSED_KEYS = {"name": "the project's name is its folder name: make a new project (slop new NAME) instead",
                "gates": "gates record the owner's approvals: slop gate NAME --approve|--revoke",
                "gates_meta": "written by slop gate (what each approval covered)",
                "budget.frozen": "the owner's quality flag: slop spend --freeze \"REASON\" | --unfreeze",
                "created": "written once by slop new", "claudia": "the toolkit version that created the project"}
LOOK_KEYS = ("mode", "accent", "medium", "hero_plate", "section_accents", "strength", "contrast")
LEAD_TEXT = ("canon", "far", "possessive", "noun")
MODEL_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._:-]*$")
HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
NONE_WORDS = {"null", "none", "no", "off", ""}
GENERATORS = {"api": "api", "img": "api", "image": "api", "images": "api", "img_prompt": "api", "mj": "mj",
              "midjourney": "mj", "mj_prompt": "mj"}
BOARD_KEYS = ("generator", "pace", "max_clips", "lead_min", "lead_target", "cover_allowance", "treatments", "banned",
              "api_candidates")
AUDIO_KEYS = ("downbeat_phase", "downbeat_method", "tempo_range", "bpm_hint", "beatgrid", "beat_pad0", "hits",
              "sections", "section_pickup_beats", "whisper_map", "whisper_model", "whisper_usd_per_s", "conf_min")
GRADE_MODES = ("clean-grade", "print")          # edit look grades plates toward the accent: it needs a colour


def _hex6(v: str) -> str:
    h = v.strip().upper()
    return "#" + "".join(ch * 2 for ch in h[1:]) if len(h) == 4 else h          # #abc -> #AABBCC


def parse_value(raw: str):
    """VALUE as typed: JSON when it parses (12, 0.5, true, null, [1920,1080], {"a":1}, "text"), else the text itself."""
    s = str(raw).strip()
    if s.lower() in ("none", "null"):
        return None
    try:
        return json.loads(s)
    except (ValueError, TypeError):
        return s


def _num(key: str, v, lo: float = 0.0, hi: float | None = None, integer: bool = False):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise SlopError(f"{key} must be a number, not {v!r}")
    if v < lo or (hi is not None and v > hi):
        raise SlopError(f"{key} must be between {lo:g} and {hi:g}" if hi is not None else f"{key} must be {lo:g} or more")
    return int(v) if integer else v


def _text_value(key: str, v) -> str:
    if v is None or isinstance(v, (dict, list, bool)):
        raise SlopError(f"{key} must be text, not {v!r}")
    s = re.sub(r"\s+", " ", str(v)).strip()
    if not s:
        raise SlopError(f"{key} is empty")
    if "TODO" in s or re.search(r"<[^<>]{1,80}>", s) or s in ("…", "..."):
        raise SlopError(f"{key}: {s!r} is still a placeholder - write the real text")
    return s


def validate_setting(key: str, v):
    """The value to store for a dotted project.json key, or a SlopError that says what is allowed."""
    parts = key.split(".")
    top = parts[0]
    for k, why in REFUSED_KEYS.items():
        if key == k or key.startswith(k + "."):
            raise SlopError(f"{key} is not set with project set: {why}")
    if top not in PROJECT_TOP:
        raise SlopError(f"unknown project.json key {top!r}: project set takes {', '.join(PROJECT_TOP)} "
                        "(and their dotted sub-keys, e.g. look.accent, budget.openrouter_usd, models.image)")
    sub = parts[1] if len(parts) > 1 else None
    example = {"lead": "canon", "look": "accent", "models": "image", "budget": "openrouter_usd", "board": "generator",
               "mj": "params", "audio": "downbeat_phase"}
    if top in example and sub is None:
        raise SlopError(f"name one {top} key: e.g. slop project set {top}.{example[top]} VALUE")
    if top == "tier":
        if str(v).lower() not in TIERS:
            raise SlopError(f"tier must be one of {', '.join(TIERS)}")
        return str(v).lower()
    if top == "title":
        return _text_value(key, v)
    if top == "song":
        return _text_value(key, v)
    if top == "fps":
        if isinstance(v, str) or (isinstance(v, float) and not v.is_integer()):
            raise SlopError(f"fps must be a whole number (24, 25, 30, 60), not {v!r}")
        return _num(key, v, 1, 120, integer=True)
    if top == "size":
        if isinstance(v, str) and re.fullmatch(r"\s*\d+\s*[xX×,]\s*\d+\s*", v):
            v = [int(x) for x in re.split(r"[xX×,]", v)]
        if not (isinstance(v, list) and len(v) == 2 and all(isinstance(x, int) and 64 <= x <= 8192 for x in v)):
            raise SlopError("size must be WIDTHxHEIGHT, e.g. 1920x1080 (or [1920,1080])")
        return v
    if top == "look":
        if sub not in LOOK_KEYS:
            if sub == "fonts":
                raise SlopError("fonts must be OFL fonts the engine has: slop edit look set --font-lyric NAME "
                                "(--font-micro, --font-display) checks that")
            raise SlopError(f"look.{sub} is not a key project set writes: {', '.join('look.' + k for k in LOOK_KEYS)}")
        if sub == "mode":
            if v not in ("native", "clean-grade", "print"):
                raise SlopError("look.mode must be native, clean-grade or print")
            return v
        if sub == "accent":
            if v is None or (isinstance(v, str) and v.strip().lower() in NONE_WORDS):
                return None                                          # no accent: the engine draws none
            if not (isinstance(v, str) and HEX_RE.match(v.strip())):
                raise SlopError("look.accent must be a hex colour like #D97757, or none (no accent colour at all)")
            return _hex6(v)
        if sub == "medium":
            m = {"cel": "cel", "illustrated": "illustration"}.get(str(v).lower(), str(v).lower())
            if m not in ("photo", "illustration", "cel"):
                raise SlopError("look.medium must be photo, illustration or cel")
            return m
        if sub == "hero_plate":
            return None if v is None or str(v).strip().lower() in NONE_WORDS else _text_value(key, v)
        if sub == "section_accents":
            if isinstance(v, bool):
                return v
            if isinstance(v, dict) and all(isinstance(x, str) and HEX_RE.match(x.strip()) for x in v.values()):
                return {k: _hex6(x) for k, x in v.items()}
            raise SlopError("look.section_accents must be true, false, or {\"verse2\": \"#RRGGBB\", ...}")
        return _num(key, v, 0, 1)                                    # strength, contrast
    if top == "lead":
        if sub in LEAD_TEXT:
            return _text_value(key, v)
        if sub == "pronoun":
            if str(v).lower() not in ("she", "he", "they", "it"):
                raise SlopError("lead.pronoun must be she, he, they or it")
            return str(v).capitalize()
        if sub == "none":
            if not isinstance(v, bool):
                raise SlopError("lead.none must be true or false")
            return v
        raise SlopError(f"lead.{sub} is not a lead key: lead.{', lead.'.join(LEAD_TEXT)}, lead.pronoun, lead.none")
    if top == "budget":
        if sub in ("openrouter_usd", "hedra_usd", "confirm_over_usd"):
            return _num(key, v, 0, 10000)
        if sub in ("higgsfield_credits", "hedra_credits"):
            return _num(key, v, 0, 1_000_000)
        if sub == "motion_s":
            return _num(key, v, 0, 3600)
        raise SlopError(f"budget.{sub} is not a budget key: budget.openrouter_usd, budget.higgsfield_credits, budget.hedra_usd, budget.hedra_credits, "
                        "budget.confirm_over_usd, budget.motion_s")
    if top == "models":
        if sub == "pin":
            return str(v).strip().lower() in ("true", "on", "yes", "1") if not isinstance(v, bool) else v
        if sub not in ("image", "video", "video_cheap", "edit", "vlm", "text", "song", "whisper"):
            raise SlopError(f"models.{sub}: the model slots are image, video, video_cheap, edit, vlm, text, song, "
                            "whisper (models.pin true keeps them exactly as set)")
        if not (isinstance(v, str) and MODEL_ID_RE.match(v.strip())):
            raise SlopError(f"{key} must be an OpenRouter model id like openai/gpt-image-2 (list them: slop gen models "
                            f"--kind {'video' if sub.startswith('video') else 'image' if sub in ('image', 'edit') else 'text'})")
        return v.strip()
    if top == "board":
        if sub not in BOARD_KEYS:
            raise SlopError(f"board.{sub} is not a board key: {', '.join('board.' + k for k in BOARD_KEYS)}")
        if sub == "generator":
            g = GENERATORS.get(str(v).strip().lower()) if v is not None else None
            if v is not None and not g:
                raise SlopError("board.generator must be api (API images: board set --img-prompt) or mj (Midjourney: "
                                "--mj-prompt), or none (follow the board / the tier)")
            return g
        if sub == "pace":
            if isinstance(v, dict) or v in TIERS:
                return v
            raise SlopError("board.pace must be quick, studio, director, or {\"SECTION\": seconds_per_shot, ...}")
        if sub == "max_clips":
            return _num(key, v, 0, 500, integer=True)
        if sub == "lead_min":
            v = _num(key, v, 0, 100)
            return round(v / 100, 4) if v > 1 else v                 # 70 -> 0.70
        return v
    if top == "audio":
        if sub not in AUDIO_KEYS:
            raise SlopError(f"audio.{sub} is not an audio key: {', '.join('audio.' + k for k in AUDIO_KEYS)}")
        if sub == "downbeat_phase":
            return _num(key, v, 0, 3, integer=True)
        if sub == "downbeat_method" and v not in ("kick", "harmony", "auto"):
            raise SlopError("audio.downbeat_method must be kick, harmony or auto")
        return v
    if top == "mj":
        if sub not in ("params", "profile", "raw", "hd", "personalize", "version"):
            raise SlopError("mj keys: mj.params (e.g. \"--ar 16:9\"; never a --v), mj.raw / mj.hd / mj.personalize "
                            "(true|false, the person's choice), mj.version (only when they asked for one), mj.profile")
        if sub in ("raw", "hd", "personalize"):
            if isinstance(v, bool):
                return v
            if str(v).strip().lower() in ("true", "on", "yes", "1"):
                return True
            if str(v).strip().lower() in ("false", "off", "no", "0"):
                return False
            raise SlopError(f"mj.{sub}: true or false")
        return "" if v is None else str(v).strip()
    return v                                                         # chrome, looks: engine options, stored as given


def _money_guard(proj: dict, key: str, had: bool, old, new) -> str | None:
    """Why this budget change loosens the owner's money guard (a cap up or removed, confirm_over_usd up, more paid
    clip seconds), or None (a cap lowered, or not a guard). The owner decides those, never the bot alone."""
    sub = key.split(".", 1)[1] if key.startswith("budget.") else None
    if sub in ("openrouter_usd", "higgsfield_credits", "hedra_usd", "hedra_credits"):
        unit = "$" if sub.endswith("_usd") else ""
        cap_old = float(old) if had and old else float("inf")             # 0 / unset = no cap (ledger.check_budget)
        cap_new = float(new) if new else float("inf")
        if cap_new > cap_old:
            return ("it removes the spend cap (0 = no cap)" if cap_new == float("inf") else
                    f"it raises the spend cap from {unit}{cap_old:g} to {unit}{cap_new:g}")
    elif sub == "confirm_over_usd":
        was = float(old or 0) if had else 2.0                              # ledger default: 2
        if float(new or 0) > was:
            return f"fewer paid calls would ask first (confirm over ${was:g} -> ${float(new or 0):g})"
    elif sub == "motion_s":
        from .board.common import motion_budget_s
        was = motion_budget_s(proj)
        if float(new) > was:
            return f"it lets the board plan more paid clip seconds ({was:g} s -> {float(new):g} s)"
    return None


def _get_dotted(d: dict, key: str):
    cur = d
    for k in key.split("."):
        if not isinstance(cur, dict) or k not in cur:
            return None, False
        cur = cur[k]
    return cur, True


def _set_dotted(d: dict, key: str, value) -> None:
    parts = key.split(".")
    cur = d
    for k in parts[:-1]:
        nxt = cur.get(k)
        if nxt is None:
            nxt = cur[k] = {}
        if not isinstance(nxt, dict):
            raise SlopError(f"project.json {k} is not an object, so {key} cannot be set inside it")
        cur = nxt
    cur[parts[-1]] = value


def cmd_project(args) -> dict:
    pdir = _resolve(args)
    proj = load_project_checked(pdir)
    key = (getattr(args, "key", None) or "").strip().strip(".")
    if args.project_cmd == "show":
        if not key:
            return {"project": proj, "text": json.dumps(proj, indent=1, ensure_ascii=False)}
        val, found = _get_dotted(proj, key)
        if not found:
            raise SlopError(f"project.json has no {key}")
        return {"key": key, "value": val, "text": f"{key} = {json.dumps(val, ensure_ascii=False)}"}
    if not key or not re.fullmatch(r"[a-z_][a-z0-9_]*(?:\.[a-z0-9_]+)*", key, re.I):
        raise SlopError("give a dotted key and a value, e.g. slop project set look.accent \"#D97757\"")
    new = validate_setting(key, parse_value(args.value))
    old, had = _get_dotted(proj, key)
    if had and old == new:
        return {"key": key, "value": new, "old": old, "changed": False, "decision": None,
                "text": f"{key} is already {json.dumps(new, ensure_ascii=False)} (no change)"}
    why = _money_guard(proj, key, had, old, new)
    if why and not (getattr(args, "owner_ok", False) and str(getattr(args, "by", "") or "").strip().lower() == "owner"):
        again = _pcmd(pdir, f'project set {key} {shlex.quote(str(args.value))} --owner-ok --by owner --note '
                            '"owner: THEIR WORDS"')
        raise SlopError(f"{key} = {json.dumps(new)} loosens the owner's money guard: {why}. Nothing was changed. Ask "
                        f"the owner first and show them what was spent ({_pcmd(pdir, 'spend')}). Only after they say "
                        f"yes: {again}. Lowering a cap needs no flag.")
    look = proj.get("look") or {}
    if key == "look.accent" and new is None and look.get("mode") in GRADE_MODES:
        raise SlopError(f"look.mode is {look.get('mode')}: its colour grade keeps the accent colour, so it needs one. "
                        f"Keep a hex accent (e.g. #D97757), or first {_pcmd(pdir, 'project set look.mode native')}, "
                        "then set look.accent none")
    if key == "look.mode" and new in GRADE_MODES and "accent" in look and look.get("accent") is None:
        fix = _pcmd(pdir, 'project set look.accent "#D97757"')
        raise SlopError(f"look.mode {new} grades the plates toward the accent colour, and look.accent is none: first "
                        f"{fix} (any hex colour), then set the mode")
    _set_dotted(proj, key, new)
    save_project(pdir, proj)
    shown = json.dumps(new, ensure_ascii=False)
    dec = append_decision(pdir, f"project.json {key} = {shown} (was {json.dumps(old, ensure_ascii=False) if had else 'unset'})"
                          + (f" - {args.note.strip()}" if getattr(args, "note", None) else ""), by=args.by)
    lines = [f"{key} = {shown} (was {json.dumps(old, ensure_ascii=False) if had else 'unset'}); logged in DECISIONS.md"]
    if key == "tier":
        lines.append("the budget caps did not change: set them too if the owner wants the new tier's caps "
                     f"({_pcmd(pdir, 'project set budget.openrouter_usd N')}; raising a cap needs the owner's yes: "
                     "add --owner-ok --by owner)")
    if key == "look.accent" and new is None:
        lines.append("no accent: the engine draws accent marks in the plain type colour (no colour emphasis)")
    if key.startswith("look.") or key in ("fps", "size"):
        lines.append(f"re-export the engine data before the next render: {_pcmd(pdir, 'edit export')}")
    if key == "board.generator":
        lines.append("board set now expects " + ("--img-prompt (API images)" if new == "api" else
                                                  "--mj-prompt (Midjourney)" if new == "mj" else
                                                  "the prompt field the board's shots already use"))
    return {"key": key, "value": new, "old": old if had else None, "changed": True, "decision": dec,
            "text": "\n".join(lines)}


# ====================================================================== doctor / spend
def cmd_doctor(args) -> dict:
    from .doctor import run_doctor
    return run_doctor(profile=args.profile, quick=args.quick, offline=args.offline, net=args.net)


def _optional_project(args) -> Path | None:
    """The project if one was named or the cwd is inside one; None otherwise (spend works without a project)."""
    try:
        return resolve_project(args.project)
    except SlopError:
        if args.project or os.environ.get("SLOP_PROJECT"):
            raise SlopError(f"no project {args.project or os.environ.get('SLOP_PROJECT')!r}" + _projects_hint()) \
                from None
        return None


def _freeze(args) -> dict:
    """slop spend --freeze REASON | --unfreeze: the owner's quality flag stops all spending (rule 8)."""
    pdir = _resolve(args)
    proj = load_project_checked(pdir)
    budget = proj.setdefault("budget", {})
    cur = spend_frozen(proj)
    note = f" - {args.note.strip()}" if getattr(args, "note", None) else ""
    if args.unfreeze:
        if not cur:
            return {"frozen": None, "changed": False, "text": "spending is not frozen (no change)"}
        budget.pop("frozen", None)
        save_project(pdir, proj)
        dec = append_decision(pdir, f"SPEND unfrozen (was: {cur.get('reason')}){note}")
        return {"frozen": None, "changed": True, "decision": dec,
                "text": "spending unfrozen; logged in DECISIONS.md. Paid calls still need their estimate and --yes."}
    reason = re.sub(r"\s+", " ", args.freeze or "").strip()
    if not reason:
        raise SlopError('say why, in the owner\'s words: slop spend --freeze "owner: the faces look wrong"')
    if cur and cur.get("reason") == reason:
        return {"frozen": cur, "changed": False, "text": f"spending already frozen since {cur.get('at')}: {reason}"}
    budget["frozen"] = {"at": util.stamp(), "reason": reason}
    save_project(pdir, proj)
    dec = append_decision(pdir, f"SPEND FROZEN - {reason}{note}")
    return {"frozen": budget["frozen"], "changed": True, "decision": dec,
            "text": f"SPENDING FROZEN: {reason}. Submit nothing paid (images, clips, songs) until the owner's flag is "
                    f"resolved; then: {_pcmd(pdir, 'spend --unfreeze')}. Logged in DECISIONS.md."}


def cmd_spend(args) -> dict:
    if getattr(args, "freeze", None) is not None or getattr(args, "unfreeze", False):
        return _freeze(args)
    pdir = _optional_project(args)
    out: dict = {"project": str(pdir) if pdir else None, "real_spend_checked": False}
    lines = []
    left = None
    if pdir:
        proj = load_project_checked(pdir)
        led = ledger_summary(pdir, proj)
        out["ledger"] = led
        left = led["budget"].get("openrouter_left_usd")
        fr = spend_frozen(proj)
        out["frozen"] = fr
        if fr:
            lines.append(f"SPENDING FROZEN since {fr.get('at')}: {fr.get('reason')} - no paid call until the owner's "
                         f"flag is resolved ({_pcmd(pdir, 'spend --unfreeze')})")
        lines.append(f"{proj.get('name', pdir.name)} - ledger (estimates at submit; declined/failed not counted):")
        if led["by_provider"]:
            rows = [[p, b["calls"], util.money(b["est_usd"]), f"{b['credits']:g}", b["declined"], b["failed"]]
                    for p, b in sorted(led["by_provider"].items())]
            lines.append(util.table(rows, ["provider", "calls", "est $", "credits", "declined", "failed"]))
            hd = led["by_provider"].get("hedra")
            if hd is not None:
                lines.append(f"Hedra confirmed USD from recorded takes: {util.money(hd['real_usd'])} "
                             "(unconfirmed costs remain estimates; credits are not converted)")
            hf = led["by_provider"].get("higgsfield") or {}
            if hf.get("requested"):
                rq = hf.get("requested_takes") or []
                one = rq[0].split(" ", 1)[0] if rq and len({x.split(" ", 1)[0] for x in rq}) == 1 else "CLIP"
                lines.append(f"higgsfield: {hf['requested']:g} of these credits are requests with no job id recorded "
                             f"({', '.join(rq)}): record the job id "
                             f"({_pcmd(pdir, f'clip ingest {one} --job-id JOB_ID --pending')}), or if the connector "
                             f"refused it: {_pcmd(pdir, f'clip ingest {one} --failed')} \"rejected: <its reply>\" "
                             "(it then counts 0)")
        else:
            lines.append("  no paid calls recorded yet")
        bud = led["budget"]
        lines.append(f"budget: openrouter cap {util.money(bud['openrouter_usd'])} (left ~{util.money(bud['openrouter_left_usd'])})"
                     f" | higgsfield cap {bud['higgsfield_credits']:g} credits (left ~{bud['higgsfield_left']})"
                     f" | confirm over {util.money(bud['confirm_over_usd'])}")
        if "hedra" in led["by_provider"] or bud["hedra_usd"] or bud["hedra_credits"]:
            lines.append(f"Hedra caps: {_cap_text(bud['hedra_usd'], 'USD')} / {_cap_text(bud['hedra_credits'], 'credits')}; "
                         "unknown or unconfirmed refunds retain their estimate")
        if led["bad_lines"]:
            lines.append(f"WARNING: ledger.jsonl has {led['bad_lines']} unreadable lines")
    else:
        lines.append("no project selected: showing provider totals only (add --project NAME for the ledger)")
    if args.offline:
        out["openrouter"] = {"checked": False}
        lines.append("OpenRouter: not checked (--offline) - the numbers above are estimates")
    else:
        key = util.openrouter_key_info()
        cred = util.openrouter_credits() if key.get("ok") else {"ok": False, "error": "skipped (key check failed)"}
        out["openrouter"] = {"checked": True, "key": dict(key), "credits": cred}
        if not key.get("present"):
            lines.append("OpenRouter: OPENROUTER_API_KEY not set - ask the bot to request it with its secure secret "
                         "card. Real spend NOT read; the numbers above are estimates")
        elif not key.get("ok"):
            out["ok"] = False
            out["error"] = f"real OpenRouter spend could not be read: {key.get('error')}"
            lines.append(f"ERROR: real spend NOT read - {key.get('error')}. Do not quote spend from the ledger as real.")
        else:
            out["real_spend_checked"] = True
            lim = key.get("limit")
            lines.append("OpenRouter REAL (this key, all projects): used " + util.money(key.get("usage")) +
                         (f" of key limit {util.money(lim)}, {util.money(key.get('limit_remaining'))} left"
                          if lim is not None else " (no key limit set)") +
                         f"; today {util.money(key.get('usage_daily'))}, this week {util.money(key.get('usage_weekly'))}")
            if cred.get("ok"):
                lines.append(f"OpenRouter account: credits {util.money(cred.get('total_credits'))}, used "
                             f"{util.money(cred.get('total_usage'))}, balance {util.money(cred.get('balance'))}")
            else:
                lines.append(f"OpenRouter account balance not read: {cred.get('error')}")
            notes = []
            if left is not None and lim is not None and isinstance(key.get("limit_remaining"), (int, float)) \
                    and key["limit_remaining"] < left:
                notes.append("NOTE: the key's own limit is below the project's remaining budget - submits will fail "
                             "with HTTP 403 at the key limit; raise it in the OpenRouter dashboard if the owner agrees")
            if left is not None and cred.get("ok") and isinstance(cred.get("balance"), (int, float)) \
                    and cred["balance"] < left:
                notes.append(f"NOTE: the account balance {util.money(cred['balance'])} is below the project's "
                             f"remaining budget {util.money(left)} - submits fail with HTTP 402 when it runs out; the "
                             "owner tops up credits at openrouter.ai (never the bot)")
            exp = util.parse_iso(key.get("expires_at"))
            if exp is not None:
                from datetime import datetime, timezone
                days = (exp - datetime.now(tz=timezone.utc)).total_seconds() / 86400
                if days < 14:
                    notes.append(f"NOTE: this key expires {exp.strftime('%Y-%m-%d')} ({max(days, 0):.0f} days): ask the "
                                 "owner for a new key before then")
            out["notes"] = notes
            lines += notes
    lines.append("Quote spend from the provider numbers, not the ledger. Higgsfield: check the balance in the connector.")
    out["text"] = "\n".join(lines)
    return out


# ====================================================================== gate
def _gate_key(name: str, gates: dict) -> str:
    k = name.strip().lower().replace("-", "_")
    if k in gates:
        return k
    if k + "_approved" in gates:
        return k + "_approved"
    raise SlopError(f"unknown gate {name!r}; gates in this project: " + ", ".join(
        g.replace("_approved", "") for g in gates))


def _decisions_path(pdir: Path, proj: dict) -> Path:
    p = pdir / "DECISIONS.md"
    if not p.is_file():
        tpl = template_dir() / "DECISIONS.md"
        subs = {"{{NAME}}": proj.get("name", pdir.name), "{{TITLE}}": proj.get("title", pdir.name),
                "{{TIER}}": proj.get("tier", "?"), "{{DATE}}": util.today()}
        if tpl.is_file():  # header + instructions only; the "project created" line belongs to `slop new`
            raw = "".join(ln for ln in tpl.read_text(encoding="utf-8").splitlines(keepends=True)
                          if not ln.startswith("- {{DATE}} - project created"))
            text = _sub_text(raw, subs)
        else:
            text = "# decisions\n\n## Log\n\n"
        util.atomic_write_text(p, text)
    return p


DEC_RE = re.compile(r"^- (" + util.STAMP_RE.pattern + r") - (.*)$")


def _decision_entries(p: Path) -> list[dict]:
    if not p.is_file():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        m = DEC_RE.match(line.strip())
        if m:
            out.append({"when": m.group(1), "text": m.group(2)})
    return out


def append_decision(pdir: Path, text: str, supersedes: str | None = None, by: str | None = None) -> dict:
    """Append one dated line to DECISIONS.md (no duplicate of the last entry). Other modules may call this."""
    proj = load_project_checked(pdir)
    text = re.sub(r"\s*\n\s*", " / ", text.strip())
    if not text:
        raise SlopError('nothing to record: slop decide "the decision, in the owner\'s words"')
    body = (f"UPDATE (supersedes {supersedes.strip()}) - " if supersedes else "") + (f"[{by.strip()}] " if by else "") + text
    p = _decisions_path(pdir, proj)
    entries = _decision_entries(p)
    if entries and entries[-1]["text"] == body:
        return {"recorded": False, "duplicate": True, "entry": entries[-1], "file": str(p)}
    when = util.stamp()
    cur = p.read_text(encoding="utf-8")
    util.append_text(p, ("" if cur.endswith("\n") or not cur else "\n") + f"- {when} - {body}\n")
    return {"recorded": True, "duplicate": False, "entry": {"when": when, "text": body}, "file": str(p)}


def record_gate(pdir: Path, key: str, approve: bool, note: str | None = None, force: bool = False) -> dict:
    """Approve or revoke one gate, recording what the approval covers and logging it in DECISIONS.md.

    Other modules that approve gates (e.g. `slop board approve`) should call this so the approval is recorded and can
    go stale. Raises SlopError when the precondition fails and force is False.
    """
    proj = load_project_checked(pdir)
    gates = proj.setdefault("gates", {})
    for g in DEFAULT_GATES:
        gates.setdefault(g, False)
    if key not in gates:
        raise SlopError(f"unknown gate {key!r}")
    metas = proj.get("gates_meta") if isinstance(proj.get("gates_meta"), dict) else {}
    clips = clip_docs(pdir)
    before = gate_state(pdir, proj, key, clips)
    if not approve:
        changed = bool(gates[key]) or key in metas
        dec = None
        if changed:
            gates[key] = False
            metas.pop(key, None)
            proj["gates_meta"] = metas
            save_project(pdir, proj)
            dec = append_decision(pdir, f"GATE {key} revoked" + (f" - {note.strip()}" if note else ""))
        return {"gate": key, "approved": False, "changed": changed, "decision": dec,
                "text": f"{key} revoked" + ("; logged in DECISIONS.md" if changed else " (no change)")}
    problem = gate_problem(pdir, key)
    covers = gate_covers(pdir, key, clips)
    drafts = before["drafts"]
    standing = True
    if key == "prompts_approved":  # the standing yes needs read clip prompts and no unfinished draft; never downgraded
        standing = not drafts and (any(r.startswith("clips/") for r in covers) or (before["current"] and before["flag"]))
    same = before["recorded"] and before["current"] and before["flag"] == standing
    if same:
        return {"gate": key, "approved": True, "changed": False, "standing": standing if key == "prompts_approved"
                else None, "covers": covers, "decision": None, "text": f"{key} approved (no change)"}
    forced = None
    if problem:
        if not force:
            raise SlopError(f"cannot record approval of {key}: {problem}. Fix that first; only if the owner "
                            "explicitly approves anyway, re-run with --force (it is logged).")
        forced = problem
    gates[key] = standing
    metas[key] = {"at": util.stamp(), "covers": covers, **({"forced": forced} if forced else {}),
                  **({"note": note.strip()} if note else {})}
    proj["gates_meta"] = metas
    save_project(pdir, proj)
    what = ""
    if key == "prompts_approved":
        nclip = sum(1 for r in covers if r.startswith("clips/"))
        if not covers.get("plates/prompts.md"):
            what = f" ({nclip} clip prompts; no plate book)"
        else:
            what = f" (plate book + {nclip} clip prompts)" if nclip else " (plate book only)"
    again = " re-approved after: " + "; ".join(before["stale"] + before["uncovered"]) \
        if before["approved"] and not before["current"] else ""
    text = f"GATE {key} approved{what}" + (f" -{again}" if again else "") + (f" - {note.strip()}" if note else "") + \
        (f" (FORCED: {forced})" if forced else "")
    dec = append_decision(pdir, text)
    lines = [f"{key} approved{what}; logged in DECISIONS.md"]
    if key == "prompts_approved" and not standing:
        if drafts:
            lines.append(f"clip drafts not covered: {', '.join(drafts)} - lock them, show them to the owner, then "
                         f"approve again ({_pcmd(pdir, 'gate prompts --approve')})")
        lines.append("clip submits still need --yes each (only after the owner agreed to that clip and its estimate) "
                     "until the owner approves the locked clip prompts")
    elif key == "prompts_approved":
        lines.append("the locked clip prompts listed in gates_meta may now be submitted without --yes; any clip "
                     "locked or changed later needs the owner again")
    return {"gate": key, "approved": True, "changed": True, "standing": standing if key == "prompts_approved" else None,
            "covers": covers, "forced": forced, "decision": dec, "text": "\n".join(lines)}


def cmd_gate(args) -> dict:
    pdir = _resolve(args)
    proj = load_project_checked(pdir)
    gates = proj.setdefault("gates", {})
    for g in DEFAULT_GATES:
        gates.setdefault(g, False)
    clips = clip_docs(pdir)
    if not args.name:
        if args.approve or args.revoke:
            raise SlopError("name the gate: slop gate board --approve  (gates: " +
                            ", ".join(g.replace("_approved", "") for g in gates) + ")")
        states = {k: gate_state(pdir, proj, k, clips) for k in gates if k in GATE_SHORT}
        return {"gates": {k: bool(v) for k, v in gates.items()},
                "state": {k: {"label": gate_label(v), "current": v["current"], "at": v["at"],
                              "stale": v["stale"] + v["uncovered"]} for k, v in states.items()},
                "text": "gates: " + " | ".join(f"{GATE_SHORT.get(k, k)} {gate_label(v)}" for k, v in states.items())}
    key = _gate_key(args.name, gates)
    if args.approve or args.revoke:
        return record_gate(pdir, key, bool(args.approve), note=args.note, force=args.force)
    st = gate_state(pdir, proj, key, clips)
    problem = gate_problem(pdir, key)
    lines = [f"{key}: {gate_label(st)}" + (f" (approved {st['at']})" if st["at"] else "")]
    if st["covers"]:
        lines.append("  covers: " + ", ".join(st["covers"]))
    for s in st["stale"] + st["uncovered"]:
        lines.append(f"  changed since: {s}")
    if st["drafts"]:
        lines.append(f"  clip drafts (not covered): {', '.join(st['drafts'])}")
    if problem and not st["current"]:
        lines.append(f"  not ready: {problem}")
    return {"gate": key, "approved": st["approved"], "current": st["current"], "flag": st["flag"],
            "standing": st["standing"], "at": st["at"], "covers": st["covers"],
            "stale": st["stale"] + st["uncovered"], "drafts": st["drafts"], "ready": problem is None,
            "problem": problem, "text": "\n".join(lines)}


def cmd_decide(args) -> dict:
    pdir = _resolve(args)
    if args.list:
        p = pdir / "DECISIONS.md"
        ents = _decision_entries(p)
        last = ents[-args.last:] if args.last else ents
        return {"decisions": last, "count": len(ents),
                "text": "\n".join(f"{e['when']}  {e['text']}" for e in last) or f"no decisions yet in {p}"}
    r = append_decision(pdir, " ".join(args.text or []), args.supersedes, args.by)
    r["text"] = ("recorded: " if r["recorded"] else "already recorded (same as the last entry): ") + \
        f"{r['entry']['when']} - {r['entry']['text']}"
    return r


# ====================================================================== runs
def _cell(s: str | None) -> str:
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    return s.replace("|", "\\|")


def _uncell(s: str) -> str:
    return s.strip().replace("\\|", "|")


RUN_COLS = ("when", "id", "kind", "what", "status", "resume")


def _runs_path(pdir: Path) -> Path:
    p = pdir / "RUNS.md"
    if not p.is_file():
        proj = load_project_checked(pdir)
        tpl = template_dir() / "RUNS.md"
        subs = {"{{NAME}}": proj.get("name", pdir.name), "{{TITLE}}": proj.get("title", pdir.name),
                "{{TIER}}": proj.get("tier", "?"), "{{DATE}}": util.today()}
        util.atomic_write_text(p, _sub_text(tpl.read_text(encoding="utf-8"), subs) if tpl.is_file()
                               else "# runs\n\n" + RUNS_HEADER)
    return p


def read_runs(pdir: Path) -> list[dict]:
    p = pdir / "RUNS.md"
    if not p.is_file():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not (s.startswith("|") and s.endswith("|")):
            continue
        cells = [_uncell(c) for c in re.split(r"(?<!\\)\|", s[1:-1])]
        if len(cells) != len(RUN_COLS) or cells[0] == "when" or set(cells[0]) <= set("-: "):
            continue
        out.append(dict(zip(RUN_COLS, cells, strict=True)))
    return out


def cmd_runs(args) -> dict:
    pdir = _resolve(args)
    if args.runs_cmd == "list":
        rows = read_runs(pdir)
        if args.latest:
            seen: dict[str, dict] = {}
            for r in rows:
                seen[r["id"]] = r
            rows = list(seen.values())
        if args.last:
            rows = rows[-args.last:]
        txt = util.table([[r[c] for c in RUN_COLS] for r in rows], RUN_COLS) if rows else "no runs recorded yet"
        return {"runs": rows, "count": len(rows), "text": txt}
    # add
    rid = args.id.strip()
    if not rid or len(rid) > 200:
        raise SlopError("run ID must be 1-200 characters (the workflow/job id, e.g. wf_1a2b3c4d)")
    row = {"when": util.stamp(), "id": rid, "kind": args.kind, "what": args.what or "", "status": args.status,
           "resume": args.resume or ""}
    prev = [r for r in read_runs(pdir) if r["id"] == rid]
    if prev and all(prev[-1][k] == _uncell(_cell(row[k])) for k in ("kind", "what", "status", "resume")):
        return {"recorded": False, "duplicate": True, "run": prev[-1],
                "text": f"already recorded: {rid} ({prev[-1]['status']})"}
    p = _runs_path(pdir)
    cur = p.read_text(encoding="utf-8")
    prefix = "" if cur.endswith("\n") or not cur else "\n"
    if "| when | id | kind |" not in cur:
        prefix += "\n" + RUNS_HEADER
    util.append_text(p, prefix + "| " + " | ".join(_cell(row[c]) for c in RUN_COLS) + " |\n")
    return {"recorded": True, "duplicate": False, "run": row, "file": str(p),
            "text": f"recorded run {rid} ({args.kind}, {args.status}) in RUNS.md"}


# ====================================================================== register
def register(sub) -> None:
    mine: list[argparse.ArgumentParser] = []

    def add(name: str, **kw) -> argparse.ArgumentParser:
        p = sub.add_parser(name, **kw)
        mine.append(p)
        return p

    p = add("new", help="create a project from the template",
            description="Create projects/NAME from templates/project (idempotent: re-running only adds "
                        "missing template files). Example: slop new my-song --title \"My Song\" --tier quick")
    p.add_argument("name", help="folder name: lowercase letters, digits, dashes (e.g. my-song)")
    p.add_argument("--title", help="display title (default: from NAME)")
    p.add_argument("--tier", choices=TIERS, default=None, help="quick (default) | studio | director")
    p.add_argument("--root", help="parent folder for the project (default $SLOP_PROJECTS)")
    util.add_common_flags(p)
    p.set_defaults(func=cmd_new)

    p = add("status", help="stages done/missing/stale, gates, spend, next step",
            description="Where is this project and what is the next step? Reads files only (no network).")
    util.add_common_flags(p)
    p.set_defaults(func=cmd_status)

    p = add("next", help="run the next step when it is free and needs no owner/creative input (else print it)",
            description="Reads `slop status`, then RUNS its next command when that is free (no provider spend), not "
                        "an owner gate and needs no writing or choosing first; otherwise prints it with why. Long "
                        "steps (analyze, edit export, render ...) start as a background job: then repeat the wait "
                        "command it prints (job wait ID). A long step whose last run failed, was stopped or changed "
                        "nothing is not started again (read that job first; --retry overrides). Short steps run one "
                        "after another until --steps or SLOP_WAIT_MAX seconds. Example: slop --project my-song next "
                        "--steps 3")
    p.add_argument("--steps", type=int, default=1, help="run up to N steps in a row (stops at anything it cannot run)")
    p.add_argument("--free-only", action="store_true",
                   help="hard spend lock for what it runs: any paid call inside is refused (SLOP_FREE_ONLY=1)")
    p.add_argument("--fg", action="store_true", help="run long steps in this call instead of as a background job")
    p.add_argument("--retry", action="store_true",
                   help="start the step even though its last run failed, was stopped or changed nothing")
    p.add_argument("--dry-run", action="store_true", help="only say what would run")
    util.add_common_flags(p)
    p.set_defaults(func=cmd_next)

    p = add("brief", help="show or add the owner's ask (verbatim, dated) in BRIEF.md",
            description="The owner's words, VERBATIM, under BRIEF.md's ask heading (binding on the storyboard and every "
                        "prompt). No TEXT: print the ask. Example: slop --project my-song brief \"make a video for my "
                        "song about ...\"")
    p.add_argument("text", nargs="*", help="the owner's words, verbatim")
    p.add_argument("--file", help="read the words from a file instead")
    p.add_argument("--date", help="the date the owner said it (default today, YYYY-MM-DD)")
    util.add_common_flags(p)
    p.set_defaults(func=cmd_brief)

    p = add("projects", help="list the projects (with their next stage)",
            description="Every folder under $SLOP_PROJECTS (or --root) that holds a project.json.")
    p.add_argument("--root", help="folder to list (default $SLOP_PROJECTS)")
    util.add_common_flags(p)
    p.set_defaults(func=cmd_projects)

    p = add("lead", help="show or set the lead's identity text (project.json lead)",
            description="The lead's identity is TEXT pasted into every prompt with the lead (never a face image). "
                        "Write it with the owner in bible/LEAD.md first. Example: slop --project my-song lead "
                        "--canon \"a woman in her mid-twenties with ...\" --far \"a young woman with ...\"")
    p.add_argument("--canon", help="the pinned identity text: face, age, ethnicity, skin, hair, marks, outfit")
    p.add_argument("--far", help="a SHORT variant for full-length / wide shots")
    p.add_argument("--possessive", help="e.g. \"the singer's\"")
    p.add_argument("--noun", help="how clip prompts name the lead (default \"the woman\")")
    p.add_argument("--pronoun", type=str.lower, choices=("she", "he", "they", "it"), help="default she")
    p.add_argument("--none", action="store_true",
                   help="only when the owner decided the video has NO lead character (then also set board.lead_min "
                        "to 0 in project.json for the board audit)")
    p.add_argument("--by", help="who decided (e.g. owner); logged with the change")
    util.add_common_flags(p)
    p.set_defaults(func=cmd_lead)

    p = add("project", help="show or set project.json values (validated; changes are logged in DECISIONS.md)",
            description="No hand-editing of project.json: `slop project set KEY VALUE` writes one dotted key "
                        "(look.accent, look.mode, lead.canon, budget.openrouter_usd, models.image, tier, "
                        "board.generator, ...), checks the value and logs the change in DECISIONS.md. VALUE is JSON when "
                        "it parses (12, 0.5, true, null, [1920,1080]); none/null clears a nullable key (look.accent none "
                        "= no accent colour). Example: slop -p my-song project set look.accent \"#3FA7D6\"")
    ps = p.add_subparsers(dest="project_cmd", metavar="set|show", required=True)
    sp = ps.add_parser("set", help="set one dotted key (validated, logged)")
    sp.add_argument("key", help="dotted key, e.g. look.accent, budget.openrouter_usd, models.image, tier")
    sp.add_argument("value", help="the value (JSON when it parses; none/null = empty)")
    sp.add_argument("--note", help="context logged with the change (e.g. the owner's words)")
    sp.add_argument("--by", help="who decided (e.g. owner)")
    sp.add_argument("--owner-ok", action="store_true",
                    help="ONLY after the owner said yes: allows a change that loosens a money guard (a budget cap up "
                         "or removed, confirm_over_usd up, budget.motion_s up); needs --by owner. Lowering needs no flag")
    util.add_common_flags(sp)
    sp.set_defaults(func=cmd_project)
    sh = ps.add_parser("show", help="print project.json, or one dotted key")
    sh.add_argument("key", nargs="?", help="dotted key (default: everything)")
    util.add_common_flags(sh)
    sh.set_defaults(func=cmd_project)
    util.add_common_flags(p)
    mine += [sp, sh]

    p = add("doctor", help="check this machine (deps, ffmpeg, chromium, keys, disk)",
            description="Readiness checks. Free network only: OpenRouter GET /api/v1/key (no spend).")
    p.add_argument("--profile", choices=("minimal", "full"), default=None,
                   help="which install profile must be complete (default: the one setup.sh recorded)")
    p.add_argument("--quick", action="store_true", help="skip heavy imports and the browser launch")
    p.add_argument("--offline", action="store_true", help="no network at all (skips the OpenRouter key check)")
    p.add_argument("--net", action="store_true", help="also probe hosts setup needs (pypi, github, huggingface, ...)")
    util.add_common_flags(p)
    p.set_defaults(func=cmd_doctor)

    p = add("spend", help="ledger estimate + real OpenRouter usage/limit/balance",
            description="Project ledger totals by provider (if a project is selected) and the REAL OpenRouter "
                        "usage, key limit and balance from the free /api/v1/key and /credits. Exit 1 with "
                        "\"ok\": false when the key is set but real spend could not be read.")
    p.add_argument("--offline", action="store_true", help="ledger only; no network")
    fz = p.add_mutually_exclusive_group()
    fz.add_argument("--freeze", metavar="REASON",
                    help="the owner flagged quality: stop ALL spending (recorded in project.json budget.frozen and "
                         "DECISIONS.md) until --unfreeze")
    fz.add_argument("--unfreeze", action="store_true", help="the owner's flag is resolved: allow spending again")
    p.add_argument("--note", help="with --freeze/--unfreeze: context logged with the change")
    util.add_common_flags(p)
    p.set_defaults(func=cmd_spend)

    p = add("gate", help="show or set an owner gate (board, prompts, v1)",
            description="Gates record the OWNER's approval and what it covered. Only approve after the owner said "
                        "yes. Preconditions: board = audit passing and newer than shots.json; prompts = "
                        "plates/prompts.md exists (the standing yes for clip submits needs every clip locked and "
                        "read); v1 = out/review.mp4 exists and the lyric gate passed. A changed file makes the "
                        "approval STALE. Example: slop gate board --approve --note \"owner: looks great\"")
    p.add_argument("name", nargs="?", help="board | prompts | v1 (or the full key, e.g. board_approved)")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--approve", action="store_true")
    g.add_argument("--revoke", action="store_true")
    p.add_argument("--note", help="short context logged with the change (e.g. the owner's words)")
    p.add_argument("--force", action="store_true",
                   help="record the approval even though its precondition fails (audit, prompt book, review copy, "
                        "lyric gate); only when the owner explicitly says so - it is logged")
    util.add_common_flags(p)
    p.set_defaults(func=cmd_gate)

    p = add("decide", help="append a dated decision to DECISIONS.md",
            description="Record the owner's decision (quote their words). Never edit old lines: "
                        "use --supersedes to replace one.")
    p.add_argument("text", nargs="*", help="the decision")
    p.add_argument("--supersedes", metavar="REF", help="which earlier decision this replaces (its date or words)")
    p.add_argument("--by", help="who decided (e.g. owner)")
    p.add_argument("--list", action="store_true", help="show recorded decisions instead")
    p.add_argument("--last", type=int, default=0, help="with --list: only the last N")
    util.add_common_flags(p)
    p.set_defaults(func=cmd_decide)

    p = add("runs", help="record/list long-running job ids (RUNS.md) for resume",
            description="Every long job gets a row the moment it starts, so it can be resumed.")
    rs = p.add_subparsers(dest="runs_cmd", metavar="add|list", required=True)
    a = rs.add_parser("add", help="record a run id")
    a.add_argument("id", help="workflow / job / run id")
    a.add_argument("--kind", default="workflow", help="workflow | deleg | render | gen | other (default workflow)")
    a.add_argument("--what", help="what it does, in a few words")
    a.add_argument("--status", default="running", help="running | done | failed | killed (default running)")
    a.add_argument("--resume", help="how to resume: args file, command")
    util.add_common_flags(a)
    a.set_defaults(func=cmd_runs)
    li = rs.add_parser("list", help="list recorded runs")
    li.add_argument("--last", type=int, default=0, help="only the last N rows")
    li.add_argument("--latest", action="store_true", help="one row per id (its newest)")
    util.add_common_flags(li)
    li.set_defaults(func=cmd_runs)
    util.add_common_flags(p)

    for p in mine:  # usage errors of core commands honour --json (the root parser is the router's: see util)
        util.json_usage_errors(p)

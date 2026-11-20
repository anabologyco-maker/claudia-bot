"""Tests for the docs-c module: docs/70, 80, 90, 95, 99 and docs/examples/**.

These are documentation tests: every owned file exists and has a title, nothing shipped leaks private identifiers
(checked by hash so this file does not itself contain them), the machine-readable exemplars parse and follow the
contracts the docs describe, the failure catalogue is a well-formed table, and the load-bearing numbers the docs promise
are still present (so a careless edit that drops a rule fails here). Cross-module checks: every `slop` command and
flag the docs quote exists in the CLI (global flags only before the command group), every engine `NAME.member` the docs
quote exists in engine/src, the documented treatment names pass `slop board audit`, and the documented recipes (the
safety-scan list builder, the song-patch time map) run. One slow test renders the doc's chapter template in the engine.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
EX = DOCS / "examples"

OWNED_MD = [
    DOCS / "70-motion-design.md",
    DOCS / "80-review-qa.md",
    DOCS / "90-master-publish.md",
    DOCS / "95-delegation.md",
    DOCS / "99-failures.md",
    EX / "README.md",
    EX / "suno-packs.md",
    EX / "mj-prompts.md",
    EX / "seedance-prompts.md",
    EX / "image-edit.md",
    EX / "shots-json.md",
    EX / "production-skeleton.md",
    EX / "review.md",
]
OWNED_JSON = [EX / "shots.example.json", EX / "review-pass.json", EX / "review-fail.json",
              EX / "review-toolkit-form.json"]


def _owned_files() -> list[Path]:
    files = list(OWNED_MD) + list(OWNED_JSON)
    # anything else that lands under docs/examples is owned too
    for p in sorted(EX.rglob("*")):
        if p.is_file() and p not in files:
            files.append(p)
    return files


def _text(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# --- scrub: hashes of private tokens (lower-case unless noted), so this file never contains them -------------------
_H = lambda s: hashlib.sha256(s.encode("utf-8")).hexdigest()  # noqa: E731
BANNED_LOWER = {
    "a537830719fd3767b1898d8f730256de94f9c69b287704435e69104a6cca2f39",  # agent-server host name
    "65a9200f9247b5eb6ed0c449c89cd31913441d3b516acdefe6c7479fc4f56d04",  # render-box host name
    "9702d9de853966388d3fbbb1692969bb672e2a628e7a2d18bb00ea6904b3e4e2",  # GPU-box host name
    "ae679821f0649c15f6c5181130efecf6ca5e4eb04e469b87510b48aa4725a449",  # the project taboo word
    "841486c93b12e81bd9fa1e7a86ce75862d65b62e8963979da438ecfcd5684700",  # the owner's Midjourney profile code
    "c0e7c9f31054f1ac234982646d6e0e5cca1f649f5edcb8384795cd878dcf7019",  # the owner's mail local part
    "fe0f6d7131c18323e3e8cba5ccc0e079ca6ebf795787717f3e6e0bcc5ad0262e",  # the tailnet name
    "a189ab606c73e71be38a14dd49c67b45257222a0631397f9555f7a767369435c",  # the owner's private repo name
    "8c5a24e9400550c2ab78a75f840425ab942e0faf92af4809c547fa68a5549ffb",  # the owner's OS user name
}
BANNED_CASE = {
    "0df9e03357ae3a2b287a404094d2d61aa6ec114eb8bb1c92a6c2154a03dc438a",  # the owner's initials
    "37c66a2cfceda4d420a247bb617e5dadfb2d2107fd484fffaacff7bcd72091dc",  # a startup name
}
UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
RUN_ID = re.compile(r"\bwf_[0-9a-f]{6,}", re.I)
PROFILE = re.compile(r"--profile\s+(?!<)[A-Za-z0-9]{4,}")
MAGIC_DNS = re.compile(r"\.ts\.net\b", re.I)
PRIVATE_PATHS = re.compile(r"(/opt/[a-z]|/mnt/HC_|/root/\.claude|C:\\\\?Users\\\\?[a-z])", re.I)
# a clock time of day (hh:mm, two-digit hour, not part of a longer timecode); song times are m:ss / m:ss.ss and elapsed
# times are written +h:mm, so neither matches
CLOCK_TIME = re.compile(r"(?<![\d:.+\-−])(?:[01]\d|2[0-3]):[0-5]\d(?![\d:.])")


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[A-Za-z0-9]+", text)) | set(re.findall(r"[A-Za-z0-9][A-Za-z0-9-]*[A-Za-z0-9]", text))


@pytest.mark.parametrize("path", _owned_files(), ids=lambda p: p.relative_to(ROOT).as_posix())
def test_scrubbed(path: Path) -> None:
    text = _text(path)
    toks = _tokens(text)
    # count only, so a failure never prints the private token itself
    n_hits = sum(1 for t in toks if _H(t.lower()) in BANNED_LOWER) + sum(1 for t in toks if _H(t) in BANNED_CASE)
    lines = [i + 1 for i, ln in enumerate(text.splitlines())
             if any(_H(t.lower()) in BANNED_LOWER or _H(t) in BANNED_CASE for t in _tokens(ln))]
    assert n_hits == 0, f"{n_hits} private token(s) in {path.name} on lines {lines}"
    assert not UUID.search(text), f"a job id / uuid in {path.name}"
    assert not RUN_ID.search(text), f"a workflow run id in {path.name}"
    assert not PROFILE.search(text), f"a Midjourney --profile code in {path.name}"
    assert not MAGIC_DNS.search(text), f"a tailnet host in {path.name}"
    assert not PRIVATE_PATHS.search(text), f"a private path in {path.name}"
    clock = [i + 1 for i, ln in enumerate(text.splitlines()) if CLOCK_TIME.search(ln)]
    assert not clock, f"a clock time of day in {path.name} on lines {clock} (write elapsed time, e.g. +4:05)"


def test_this_test_file_is_scrubbed_too() -> None:
    me = Path(__file__)
    text = _text(me)
    toks = _tokens(text)
    n_hits = sum(1 for t in toks if _H(t.lower()) in BANNED_LOWER) + sum(1 for t in toks if _H(t) in BANNED_CASE)
    assert n_hits == 0


# --- structure ---------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("path", OWNED_MD, ids=lambda p: p.relative_to(ROOT).as_posix())
def test_markdown_has_title_and_body(path: Path) -> None:
    assert path.is_file(), f"missing {path}"
    text = _text(path)
    first = text.lstrip().splitlines()[0]
    assert first.startswith("# "), f"{path.name} must start with an H1 title"
    assert len(text) > 1500, f"{path.name} is too short to be the knowledge doc it claims to be"
    assert text.count("```") % 2 == 0, f"unbalanced code fences in {path.name}"


def test_examples_readme_links_resolve() -> None:
    text = _text(EX / "README.md")
    links = re.findall(r"\]\(([^)#]+)\)", text)
    assert links, "README should link every exemplar"
    for link in links:
        assert (EX / link).is_file(), f"broken link in examples/README.md: {link}"
    for p in EX.iterdir():
        if p.is_file() and p.name != "README.md":
            assert p.name in text, f"examples/README.md does not list {p.name}"


# --- machine-readable exemplars ------------------------------------------------------------------------------------
REVIEW_KEYS = {"director", "craft", "sync", "story", "pass", "fixes"}


@pytest.mark.parametrize("name", ["review-pass.json", "review-fail.json"])
def test_review_examples_follow_the_schema(name: str) -> None:
    rev = json.loads(_text(EX / name))
    assert REVIEW_KEYS <= set(rev), f"{name} misses {REVIEW_KEYS - set(rev)}"
    for k in ("director", "craft", "sync", "story"):
        assert isinstance(rev[k], (int, float)) and 0 <= rev[k] <= 10
    computed = rev["director"] >= 8 and min(rev["craft"], rev["sync"], rev["story"]) >= 7
    assert rev["pass"] is computed, f"{name}: pass must equal director>=8 and the others>=7"
    assert 1 <= len(rev["fixes"]) <= 12
    for f in rev["fixes"]:
        assert {"shot", "problem", "fix"} <= set(f)
        assert len(f["problem"]) > 40 and len(f["fix"]) > 40, "fixes must be concrete"
    assert rev["_note"].count("WHY") == 1


def _toolkit_verdict(r: dict, min_owner: float = 7, min_other: float = 6) -> dict:
    """The verdict rule of templates/workflows/chapters.js, restated (80-review-qa.md §8.2)."""
    valid = (all(isinstance(r.get(k), (int, float)) and 0 <= r[k] <= 10 for k in ("owner", "craft", "sync", "story"))
             and isinstance(r.get("fixes"), list) and isinstance(r.get("checks"), dict)
             and str(r["checks"].get("lyric_gate", "")).strip() and str(r["checks"].get("wired", "")).strip()
             and float(r["checks"].get("sheets") or 0) > 0)
    if not valid:
        return {"valid": False, "pass": False}
    blocking = [f for f in r["fixes"] if not f or f.get("severity") != "polish"]
    m = re.search(r"(\d+)\s*/\s*(\d+)", r["checks"]["lyric_gate"])
    gate = bool(m and m.group(1) == m.group(2) and int(m.group(2)) > 0)
    wired = bool(re.match(r"\s*WIRED\b", str(r["checks"]["wired"])))
    ok = not blocking and r["owner"] >= min_owner and min(r["craft"], r["sync"], r["story"]) >= min_other and gate and wired
    return {"valid": True, "pass": ok, "blocking": len(blocking), "polish": len(r["fixes"]) - len(blocking)}


def test_toolkit_form_review_verdict() -> None:
    r = json.loads(_text(EX / "review-toolkit-form.json"))
    for f in r["fixes"]:
        assert f["severity"] in ("blocking", "polish") and {"shot", "problem", "fix"} <= set(f)
    v = _toolkit_verdict(r)
    exp = r["_expected_verdict"]
    assert v["valid"] is exp["valid"] and v["pass"] is exp["pass"]
    assert v["blocking"] == exp["blocking"] and v["polish"] == exp["polish"]
    # the same review with no blocking fix would pass the calibrated floors (owner 7, others >= 6.5)
    r2 = dict(r, fixes=[dict(f, severity="polish") for f in r["fixes"]])
    assert _toolkit_verdict(r2)["pass"] is True
    # a null / render-less review is never a pass
    assert _toolkit_verdict({})["pass"] is False
    assert _toolkit_verdict(dict(r, checks={"lyric_gate": "", "sheets": 0}))["pass"] is False


def test_review_pass_and_fail_differ() -> None:
    assert json.loads(_text(EX / "review-pass.json"))["pass"] is True
    assert json.loads(_text(EX / "review-fail.json"))["pass"] is False


SHOT_FIELDS = {"id", "t0", "t1", "section", "lines", "set", "lead_on_screen", "framing", "action", "camera",
               "motion_tier", "plate", "clip", "type", "devices", "treatment", "transition_in", "chrome", "accent", "notes"}
FRAMINGS = {"ECU", "CU", "MCU", "MS", "MWS", "WS", "FS", "EWS"}
TIERS = {"still", "plate3d", "motion", "sung"}
MODES = {"subtitle", "coverline", "masthead", "stack", "mass"}
KEYS = set("WBHFT")


def test_shots_example_follows_the_contract() -> None:
    data = json.loads(_text(EX / "shots.example.json"))
    assert {"version", "duration", "chapters", "shots", "seedance", "plates"} <= set(data)
    shots = data["shots"]
    assert len(shots) >= 5
    ids = [s["id"] for s in shots]
    assert len(ids) == len(set(ids))
    for s in shots:
        missing = SHOT_FIELDS - set(s)
        assert not missing, f"{s.get('id')} misses {missing}"
        assert ("mj_prompt" in s) or ("img_prompt" in s)
        assert s["t1"] > s["t0"]
        assert s["framing"] in FRAMINGS
        assert s["motion_tier"] in TIERS
        if s["motion_tier"] in ("motion", "sung"):
            assert s["clip"], f"{s['id']}: a motion/sung shot names its clip"
        if s["motion_tier"] == "plate3d":
            assert s["treatment"], f"{s['id']}: a 2.5D shot names its treatment"
        for t in s["type"]:
            assert t["mode"] in MODES and {"line", "text", "placement"} <= set(t)
        for d in s["devices"]:
            assert {"kind", "anchor", "params", "key"} <= set(d)
            assert d["key"] in KEYS
        assert s["notes"].startswith("WHY"), f"{s['id']}: notes must start with WHY"
    for c in data["seedance"]:
        if c.get("sing"):
            assert c["words"] and f'"{c["words"]}"' in c["prompt"], "a sung prompt quotes exactly its window's words"


# --- the failure catalogue -----------------------------------------------------------------------------------------
def test_failure_catalogue_is_a_consolidated_table() -> None:
    text = _text(DOCS / "99-failures.md")
    rows = [ln for ln in text.splitlines() if re.match(r"^\| [A-M]\d+ \|", ln)]
    assert len(rows) >= 100, f"expected the merged catalogue (>= 100 rows), found {len(rows)}"
    ids = [r.split("|")[1].strip() for r in rows]
    assert len(ids) == len(set(ids)), "duplicate failure ids"
    for r in rows:
        cells = [c.strip() for c in r.strip().strip("|").split("|")]
        # #, failure, cause, fix, see — a literal \| inside a cell is allowed
        assert len(cells) >= 5, f"malformed row: {r[:60]}"
        assert all(cells[:4]), f"empty cell in: {r[:60]}"
    for tag in ("[EV]", "[SP]", "[ops]", "[tk]"):
        assert tag in text


# --- load-bearing rules stay in the docs ---------------------------------------------------------------------------
MUST_CONTAIN = {
    "70-motion-design.md": [
        "pure function of song time", "at least 3 ordered information layers", "one explaining graphic per lyric line",
        "at least five different", "never the same treatment on two consecutive", "within **0.03 s** of a beat",
        "M = {l: 72, t: 56, r: 96, b: 84}", "≥ 40 px", "≤ 3 full-frame flashes in any second",
        "subtitle", "coverline", "masthead", "stack", "mass", "KIN.mark(tk)", "native", "clean-grade", "print",
        "Keep generation inputs in colour", "engine/DEVICES.md", "Depth-Anything-V2-Small",
        "What the toolkit gives you", "PLATES[name].boxes", "\"treatment\": \"pure-motion\"", "ENGINE.time.beatsSince",
        "ch/_index.js", "loads **before** the device library", "Reference pipeline only, not shipped",
    ],
    "80-review-qa.md": [
        "N/N", "8 %, 25 %, 42 %, 58 %, 75 % and 92 %", "block", "fix", "note", "director", "craft", "sync", "story",
        "a missing or empty review is a failure", "no blocking fix left", "HISTORY-INDEPENDENT", "40 levels",
        "severity", "polish", "owner ≥ 7", "checks.sheets > 0",
        "iec61966-2-1", "Whitelist intended anachronisms", "one line per", "Approval by timeout",
        "slop --json --project NAME <command>", "slop lyrics fix --word N", "slop gate prompts --approve",
        "the connector's `balance` tool", "render/scan-list.json", "a real, recognisable person",
        "given: { type: 'number'", "132/132 tokens on screen at their time",
    ],
    "90-master-publish.md": [
        "-color_primaries bt709", "-crf 16", "-movflags +faststart", "−15.7 LUFS", "BPM lock OFF",
        "timemap.json", "paid-partnership label", "30 days", "AI IMAGE", "1080 × 1920", "Credit only the chosen pseudonym",
        "f00000.jpg", "setparams=color_primaries=bt709", "does not pass `-map_metadata -1`", "{\"segments\":",
        "slop render frames --timemap", "Reference pipeline only, not shipped",
    ],
    "95-delegation.md": [
        "READ FIRST: PRODUCTION.md", "≈ 1.5 % of a Pro+ week per user turn", "$21.5", "Max 20x", "Max 5x",
        "What exactly prints PASS", "Write the acceptance test before the brief", "Say what a role does NOT do",
        "Design for interruption", "against the provider's billing", "Every human observation becomes a metric",
        "runner/deleg.mjs", "stop every workflow", "same session",
        "new auto --project <project> --brief <name>", "safety-scan", "chapter-motion", "storyboard-panel",
    ],
    "99-failures.md": [
        "with `estimate_video_cost`", "`estimate_image_cost`", "`generate_video_batch` rejects `get_cost`",
        "fixed in the toolkit engine",
        "--every 2", "they work",
    ],
    "examples/seedance-prompts.md": [
        "Inputs warning", "reference mode only", "Higgsfield only", "@Image1 `<plate>` (reference)",
    ],
}


def test_nothing_prices_higgsfield_with_get_cost_any_more() -> None:
    """The connector's generate_video no longer takes get_cost ("Price a request with estimate_video_cost"): no doc,
    skill or module tells the bot to preflight that way (the request file's own steps: tests/test_gen_higgsfield.py)."""
    old = re.compile(r"get_cost: true|get_cost is the truth|get_cost (?:first|preflight|price)|"
                     r"generate_\w+ (?:with|and) `?get_cost|generate_video\(get_cost")
    files = [*DOCS.rglob("*.md"), *(ROOT / "skills").rglob("*.md"), *(ROOT / "slop").rglob("*.py")]
    hits = [f"{p.relative_to(ROOT)}: {m.group(0)}" for p in files for m in old.finditer(_text(p))]
    assert not hits, hits


@pytest.mark.parametrize("name", sorted(MUST_CONTAIN))
def test_load_bearing_rules_present(name: str) -> None:
    # normalise line wrapping and blockquote markers so a re-wrap never fails the check
    text = re.sub(r"\s+", " ", re.sub(r"(?m)^>\s?", "", _text(DOCS / name)))
    missing = [s for s in MUST_CONTAIN[name] if s not in text]
    assert not missing, f"{name} lost: {missing}"


def test_encode_flags_match_between_docs() -> None:
    """The master tags promised in 80 (ffprobe table) are the ones 90's encode command writes."""
    enc = _text(DOCS / "90-master-publish.md")
    qa = _text(DOCS / "80-review-qa.md")
    for flag, value in (("-colorspace", "bt709"), ("-color_primaries", "bt709"), ("-color_trc", "iec61966-2-1"),
                        ("-color_range", "tv")):
        assert f"{flag} {value}" in enc
        assert value in qa


def test_examples_quote_window_words_exactly() -> None:
    """Every sung head in the Seedance exemplars quotes words, and the quote closes with '".' as the template does."""
    text = _text(EX / "seedance-prompts.md")
    heads = re.findall(r"lip-syncs to @Audio1 exactly, every word in time: \"([^\"]+)\"\.", text)
    assert len(heads) >= 6
    assert all(h.strip() for h in heads)


ENGINE_DEVICES = ROOT / "engine" / "src" / "devices"
# the 2.5D treatment names 70 §11 documents (the engine's family names) and the code-drawn form both tools accept
DOC_TREATMENTS = ["push", "layers", "rack", "relight", "contours", "scan", "xerox", "stills", "diagram", "occlusion"]
CODE_TREATMENT = "pure-motion"


def test_example_treatments_use_documented_names() -> None:
    doc = _text(DOCS / "70-motion-design.md")
    for name in DOC_TREATMENTS + [CODE_TREATMENT]:
        assert f"`{name}`" in doc or f'"{name}"' in doc, f"70 §11 no longer documents the treatment {name!r}"
    data = json.loads(_text(EX / "shots.example.json"))
    for s in data["shots"]:
        t = s["treatment"]
        fam = t.get("family") if isinstance(t, dict) else t
        assert fam is None or fam in DOC_TREATMENTS + [CODE_TREATMENT], f"{s['id']}: treatment {fam!r} is not documented"


def test_example_anchors_need_no_detections() -> None:
    """The toolkit detects no boxes (70 §5.0): the exemplar anchors use uv/keys/rect/xy/slot, never box/track/lead."""
    data = json.loads(_text(EX / "shots.example.json"))
    for s in data["shots"]:
        for d in s["devices"]:
            a = d["anchor"]
            assert not isinstance(a, str) or a in ("left", "right", "top", "bottom", "center", "auto") or a.startswith(("top-", "bottom-")), \
                f"{s['id']}: anchor {a!r} needs detections the toolkit does not make"
            if isinstance(a, dict):
                assert not ({"box", "track", "label"} & set(a)), f"{s['id']}: anchor {a} needs detections"
                assert {"uv", "keys", "rect", "xy", "slot"} & set(a), f"{s['id']}: unknown anchor form {a}"


@pytest.mark.skipif(not ENGINE_DEVICES.is_dir(), reason="engine device library not present")
def test_example_device_kinds_exist_in_the_engine() -> None:
    src = "\n".join(p.read_text(encoding="utf-8") for p in ENGINE_DEVICES.glob("*.js"))
    known = set(re.findall(r"register\(['\"]([A-Za-z0-9._-]+)['\"]", src))
    for alias_list in re.findall(r"alias:\s*\[([^\]]*)\]", src):
        known |= set(re.findall(r"['\"]([A-Za-z0-9._-]+)['\"]", alias_list))
    if not known:
        pytest.skip("no device registrations found")
    data = json.loads(_text(EX / "shots.example.json"))
    for s in data["shots"]:
        for d in s["devices"]:
            assert d["kind"] in known, f"{s['id']}: device kind {d['kind']!r} is not registered in engine/src/devices"


# --- every `slop …` command quoted in these docs exists in the CLI, with the flags it uses --------------------------
CMD_RE = re.compile(r"`slop\s+([^`]+)`")


def _cli_parsers():
    import argparse
    try:
        from slop.cli import build_parser
        ap = build_parser()
    except Exception:  # the router itself is broken: its own tests say so
        return None, None
    top = next(a for a in ap._actions if isinstance(a, argparse._SubParsersAction))
    root_opts = {s for a in ap._actions for s in a.option_strings}
    return top.choices, root_opts


def _opts(p) -> set[str]:
    return {s for a in p._actions for s in a.option_strings}


def _subparsers(p):
    import argparse
    subs = [a for a in p._actions if isinstance(a, argparse._SubParsersAction)]
    return subs[0].choices if subs else None


@pytest.mark.parametrize("path", [p for p in OWNED_MD], ids=lambda p: p.relative_to(ROOT).as_posix())
def test_documented_commands_and_flags_exist(path: Path) -> None:
    groups, root_opts = _cli_parsers()
    if groups is None:
        pytest.skip("CLI router not importable here")
    bad = []
    text = _text(path)
    quoted = [m.group(1) for m in CMD_RE.finditer(text)]
    # commands on their own line inside code blocks too (a trailing "# comment" is dropped)
    quoted += [m.group(1) for m in re.finditer(r"(?m)^[ \t]*slop[ \t]+([^#\n]+)", text)]
    for cmd in quoted:
        toks = cmd.replace("…", " ").split()
        while toks and toks[0] in ("-p", "--project", "--json"):
            toks = toks[2:] if toks[0] in ("-p", "--project") else toks[1:]
        if not toks or toks[0].startswith(("-", "<")):
            continue
        group = toks[0]
        if group not in groups:
            bad.append(f"slop {group}")
            continue
        parser, rest = groups[group], toks[1:]
        subs = _subparsers(parser)
        if subs and rest and not rest[0].startswith(("-", "<", '"')):
            if rest[0] not in subs:
                bad.append(f"slop {group} {rest[0]}")
                continue
            parser, rest = subs[rest[0]], rest[1:]
        known = _opts(parser)          # root options (--json, --project) count only BEFORE the group (80 §1 note)
        for i, tok in enumerate(rest):
            if tok == "--":            # `job start -- <command>`: what follows is a slop command of its own
                quoted.append(" ".join(rest[i + 1:]))
                break
            flag = tok.split("=", 1)[0].rstrip(",;:.)")
            if flag.startswith("--") and flag not in known:
                bad.append(f"slop {cmd.split()[0]} … {flag}")
    assert not bad, f"{path.name} documents commands/flags the CLI does not have: {sorted(set(bad))}"



# --- every engine NAME.member the docs quote exists in engine/src ----------------------------------------------------
ENGINE_SRC = ROOT / "engine" / "src"
API_DOCS = ["70-motion-design.md", "80-review-qa.md", "90-master-publish.md", "95-delegation.md", "99-failures.md"]
# data globals (their members are data fields) and file-name extensions after an upper-case name
DATA_ROOTS = {"PROJECT", "BEATS", "LYR", "SHOTS", "SHOTLIST", "EDL", "PLATES", "CLIPS", "TRACK", "HITS", "SONG", "SPECTRUM",
              "FXSEQ", "SLOP", "SCENES", "IMG", "SEQ", "DEVICE_FILES"}
FILE_EXT = {"md", "json", "js", "mjs", "txt", "jpg", "png", "mp4", "mp3", "wav", "pdf", "py", "html", "jsonl", "tgz", "env",
            "log", "csv", "sh"}
CHAIN = re.compile(r"(?<![\w$.])([A-Z][A-Z0-9_]*)((?:\.[A-Za-z_$][\w$]*)+)")


def _obj_keys(src: str, i: int) -> set[str]:
    """Top-level keys of the JS object literal that starts at src[i] == '{' (shorthand, key: value, method())."""
    keys: set[str] = set()
    depth, j, expect, n = 0, i, False, len(src)
    while j < n:
        c = src[j]
        if c in "\"'`":
            q, j = c, j + 1
            while j < n and src[j] != q:
                j += 2 if src[j] == "\\" else 1
            j += 1
            expect = False
            continue
        if c == "/" and src[j + 1:j + 2] == "/":
            j = src.find("\n", j)
            j = n if j < 0 else j
            continue
        if c in "([{":
            depth += 1
            expect = depth == 1
            j += 1
            continue
        if c in ")]}":
            depth -= 1
            j += 1
            if depth == 0:
                return keys
            continue
        if depth == 1:
            if c == ",":
                expect = True
            elif expect and (c.isalpha() or c in "_$"):
                m = re.match(r"[A-Za-z_$][\w$]*", src[j:])
                keys.add(m.group(0))
                j += len(m.group(0))
                expect = False
                continue
            elif not c.isspace():
                expect = False
        j += 1
    return keys


def _engine_api() -> tuple[dict[str, set[str]], str]:
    files = sorted(ENGINE_SRC.glob("*.js")) + sorted((ENGINE_SRC / "devices").glob("*.js"))
    texts = [f.read_text(encoding="utf-8") for f in files]
    api: dict[str, set[str]] = {}
    for src in texts:
        for m in re.finditer(r"^const ([A-Z][A-Z0-9_]*) = \(\(\) => \{", src, re.M):     # IIFE modules
            end = src.find("\n})();", m.end())
            body = src[m.end(): end if end > 0 else len(src)]
            k = max(body.rfind("\n  return {"), body.rfind("\n  const api = {"))
            if k >= 0:
                api.setdefault(m.group(1), set()).update(_obj_keys(body, body.index("{", k)))
            else:
                api.setdefault(m.group(1), set())
        for m in re.finditer(r"^const ([A-Z][A-Z0-9_]*) = \{", src, re.M):              # plain objects (INK)
            api.setdefault(m.group(1), set()).update(_obj_keys(src, m.end() - 1))
        for m in re.finditer(r"D\.alias\('([A-Z][A-Z0-9_]*)', \{", src):               # device-library aliases
            api.setdefault(m.group(1), set()).update(_obj_keys(src, m.end() - 1))
        for m in re.finditer(r"^const (?:[A-Z][A-Z0-9_]*\s*=\s*\S+,\s*)*([A-Z][A-Z0-9_]*)\s*=", src, re.M):
            api.setdefault(m.group(1), set())                                             # other globals (W, H, M, F …)
    allsrc = "\n".join(texts)
    api.setdefault("ENGINE", set()).update(re.findall(r"\b(?:E|ENGINE)\.([A-Za-z_$][\w$]*)\s*=(?!=)", allsrc))
    for m in re.finditer(r"Object\.assign\(ENGINE, \{", allsrc):                       # core.js's ENGINE members
        api["ENGINE"].update(_obj_keys(allsrc, m.end() - 1))
    api.setdefault("DEV", set()).update(re.findall(r"\b(?:D|DEV)\.([A-Za-z_$][\w$]*)\s*=(?!=)", allsrc))
    api["M"] = {"l", "t", "r", "b"}
    k = allsrc.find(".roles) || {")
    api["F"] = (_obj_keys(allsrc, allsrc.index("{", k + 8)) | {"round"}) if k >= 0 else set()
    return api, allsrc


def _code_of(md: str) -> list[str]:
    """Fenced code blocks (blockquote markers removed) and inline code spans of a doc."""
    text = re.sub(r"(?m)^>[ \t]?", "", md)
    blocks = re.findall(r"```[^\n]*\n(.*?)```", text, re.S)
    prose = re.sub(r"```[^\n]*\n.*?```", "", text, flags=re.S)
    return blocks + re.findall(r"`([^`\n]+)`", prose)


@pytest.mark.skipif(not ENGINE_SRC.is_dir(), reason="engine sources not present")
@pytest.mark.parametrize("name", API_DOCS)
def test_documented_engine_api_exists(name: str) -> None:
    api, allsrc = _engine_api()
    assert {"ENGINE", "KIN", "CAM", "HIT", "MEDIA", "OCC", "FX", "DEV", "LY"} <= set(api), "engine API index is broken"
    bad = []
    for code in _code_of(_text(DOCS / name)):
        local = set(re.findall(r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)", code))
        local |= set(re.findall(r",\s*([A-Za-z_$][\w$]*)\s*=(?!=)", code))
        for m in CHAIN.finditer(code):
            root, members = m.group(1), m.group(2).split(".")[1:]
            if root in local or root in DATA_ROOTS or members[0] in FILE_EXT or len(root) == 1 and root not in ("M", "F"):
                continue
            if root not in api:
                bad.append(f"{root}.{members[0]} (no global {root} in engine/src)")
                continue
            if api[root] and members[0] not in api[root]:
                bad.append(f"{root}.{members[0]}")
                continue
            if len(members) > 1 and not re.search(rf"(?<![\w$]){re.escape(members[1])}\s*[(:=,}}]", allsrc):
                bad.append(f"{root}.{members[0]}.{members[1]}")
    assert not bad, f"{name} quotes engine names that do not exist: {sorted(set(bad))}"


# --- the documented treatment vocabulary passes `slop board audit` -------------------------------------------------
def _mini_board(tmp_path: Path, treatments: list[str | None]) -> Path:
    """A synthetic 2 s-per-shot board on a 120 BPM grid; None = a code-drawn shot written as 70 §11 says."""
    p = tmp_path / "proj"
    (p / "analysis").mkdir(parents=True)
    (p / "board").mkdir()
    dur = 2.0 * len(treatments)
    beats = [round(i * .5, 3) for i in range(int(dur / .5) + 1)]
    (p / "project.json").write_text(json.dumps({"name": "docs-c", "tier": "quick", "budget": {"motion_s": 60}}), encoding="utf-8")
    (p / "analysis" / "beats.json").write_text(json.dumps({"duration": dur, "beats": beats, "downbeats": beats[::4],
                                                           "sections": [{"name": "verse1", "t0": 0, "t1": dur}]}), encoding="utf-8")
    shots = []
    for i, tr in enumerate(treatments):
        sh = {"id": f"s{i + 1:03d}", "t0": 2.0 * i, "t1": 2.0 * (i + 1), "section": "verse1", "lines": [], "set": "x",
              "lead_on_screen": True, "framing": "MS", "action": "she holds still", "camera": "static", "clip": None,
              "type": [], "devices": [], "transition_in": "cut", "chrome": "", "accent": None, "notes": "WHY: test"}
        if tr is None:
            sh.update(motion_tier="still", plate=None, treatment=CODE_TREATMENT)
        else:
            sh.update(motion_tier="plate3d", plate=f"p{i + 1:03d}", treatment=tr)
        shots.append(sh)
    (p / "board" / "shots.json").write_text(json.dumps({"version": 2, "duration": dur, "chapters": [], "shots": shots,
                                                        "seedance": [], "plates": []}), encoding="utf-8")
    return p


def test_documented_treatments_pass_the_board_audit(tmp_path: Path) -> None:
    try:
        from slop.board import audit
    except Exception as e:  # noqa: BLE001 — the board module's own tests report a broken import
        pytest.skip(f"slop.board.audit not importable: {e}")
    names = DOC_TREATMENTS[:4] + [None] + DOC_TREATMENTS[4:]          # a code-drawn shot in the middle
    rep = audit.audit(_mini_board(tmp_path / "a", names))
    failed = {g: v["fails"] for g, v in rep["gates"].items() if not v["ok"]}
    assert not failed, f"the documented treatment names fail the audit: {failed}"
    # a back-to-back repeat in the documented vocabulary is caught (a code-drawn shot between them does not hide it)
    rep = audit.audit(_mini_board(tmp_path / "b", ["layers", None, "layers", "relight"]))
    assert any("same treatment" in f for f in rep["gates"]["treatments"]["fails"])


# --- the documented recipes run ------------------------------------------------------------------------------------
def test_scan_list_recipe_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    doc = _text(DOCS / "80-review-qa.md")
    m = re.search(r"python3 - <<'PY'\n(.*?)\n[ \t]*PY\n", doc, re.S)
    assert m, "80 §9.1 lost the scan-list recipe"
    code = textwrap.dedent(m.group(1))
    (tmp_path / "edit").mkdir()
    (tmp_path / "clips").mkdir()
    (tmp_path / "edit" / "edl.json").write_text(json.dumps({
        "s001": {"segs": [{"t0": 0.0, "clip": "W01-t2", "in": 0.4}]},
        "s002": {"plate": "p002"},
        "s003": {"segs": [{"t0": 4.0, "clip": "W01-t2", "in": 4.4}, {"t0": 5.0, "clip": "M02-t1", "in": 0.0}]}}), encoding="utf-8")
    (tmp_path / "clips" / "W01.json").write_text(json.dumps({"id": "W01", "kind": "sung", "song_t0": 0.0, "body": {"duration": 6},
        "takes": [{"file": "clips/W01/take-1.mp4"}, {"file": "clips/W01/take-2.mp4"}]}), encoding="utf-8")
    (tmp_path / "clips" / "M02.json").write_text(json.dumps({"id": "M02", "kind": "motion", "song_t0": 5.0, "body": {"duration": 4},
        "takes": [{"file": "clips/M02/take-1.mp4"}]}), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    exec(compile(code, "80-review-qa.md scan-list recipe", "exec"), {})
    out = json.loads((tmp_path / "render" / "scan-list.json").read_text(encoding="utf-8"))
    assert out == [{"clip": "M02-t1", "file": "clips/M02/take-1.mp4", "shots": ["s003"], "song_t0": 5.0, "dur": 4},
                   {"clip": "W01-t2", "file": "clips/W01/take-2.mp4", "shots": ["s001", "s003"], "song_t0": 0.0, "dur": 6}]
    # the safety-scan workflow reads exactly this list shape
    assert all({"clip", "file"} <= set(e) for e in out)


def test_song_patch_timemap_example_is_valid(tmp_path: Path) -> None:
    doc = _text(DOCS / "90-master-publish.md")
    m = re.search(r"```json\n(\s*\{\"segments\":.*?)```", doc, re.S)
    assert m, "90 §3.1 lost the time-map example"
    tm = json.loads(m.group(1))
    seg = tm["segments"]
    assert seg[0][0] == 0 and all(a[1] == b[0] for a, b in zip(seg, seg[1:])), "segments must tile new-song time from 0"
    assert all(s[1] > s[0] and s[3] > s[2] for s in seg)
    try:
        from slop.render.frames import load_timemap
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"slop.render.frames not importable: {e}")
    (tmp_path / "edit").mkdir()
    (tmp_path / "edit" / "timemap.json").write_text(json.dumps(tm), encoding="utf-8")
    tl = load_timemap(tmp_path)          # the file shape the doc shows is the one the renderer reads
    assert tl(0.0) == 0.0 and abs(tl(seg[-1][1] - 1e-6) - seg[-1][3]) < 1e-3
    assert abs(tl(seg[1][1]) - seg[2][2]) < 1e-6


# --- slow: the doc's chapter template and box recipe run in the real engine ----------------------------------------
DEMO = ROOT / "tests" / "fixtures" / "engine" / "demo-project"


def _js_block(doc: str, needle: str) -> str:
    text = re.sub(r"(?m)^>[ \t]?", "", doc)
    for b in re.findall(r"```js\n(.*?)```", text, re.S):
        if needle in b:
            return b
    raise AssertionError(f"no js block with {needle!r}")


@pytest.mark.slow
@pytest.mark.skipif(not DEMO.is_dir(), reason="engine demo fixture not present")
def test_chapter_template_renders_in_the_engine(tmp_path: Path) -> None:
    pytest.importorskip("playwright.sync_api")
    from slop.render import project as P
    from slop.render.browser import EnginePage
    from slop.render.frames import _sync_playwright
    doc = _text(DOCS / "70-motion-design.md")
    d = tmp_path / "demo"
    shutil.copytree(DEMO, d)
    # what `slop edit export` gives a toolkit project: no boxes (70 §5.0)
    pj = d / "engine" / "plates.js"
    plates = json.loads(pj.read_text(encoding="utf-8").split("=", 1)[1].strip().rstrip(";"))
    for v in plates.values():
        v["boxes"] = {}
    pj.write_text("window.PLATES = " + json.dumps(plates) + ";\n", encoding="utf-8")
    # the doc's hand-written boxes recipe, on the demo's plate
    common = _js_block(doc, "PLATES[plate].boxes").replace("'dadcap-cu'", "'grad-a'")
    (d / "engine" / "common.js").write_text(common, encoding="utf-8")
    # the doc's chapter loader and scene template, on the demo's shot s001 / line 0
    (d / "engine" / "ch").mkdir()
    index = _js_block(doc, "document.write").replace("['01_arrival.js', '02_board.js']", "['01_test.js']")
    (d / "engine" / "ch" / "_index.js").write_text(index, encoding="utf-8")
    tpl = _js_block(doc, "scene(ID, SH.t0, SH.t1").replace("'s042'", "'s001'").replace("KIN.byLine(23)", "KIN.byLine(0)")
    (d / "engine" / "ch" / "01_test.js").write_text(tpl, encoding="utf-8")
    spec = P.page_spec(d, 960, 540)
    try:
        with _sync_playwright()() as p:
            pg = EnginePage(p, spec)
            try:
                found = pg.page.evaluate("() => !!ENGINE.findScene('s001') && typeof ENGINE.findScene('s001').trans === 'object'")
                drawn = pg.drawn(2.2)
                face = pg.page.evaluate("async () => { const c = document.createElement('canvas'); c.width = 960; c.height = 540;"
                                        " const m = await MEDIA.drawPlate(c.getContext('2d'), 'grad-a', {}, 0); return m && m.box('a face'); }")
                jpg = pg.frame_jpeg(2.2)
                errors, console = list(pg.errors), list(pg.console)
            finally:
                pg.close()
    except Exception as e:  # noqa: BLE001
        if "could not start a browser" in str(e):
            pytest.skip(str(e))
        raise
    assert not errors, f"the doc's template throws in the engine: {errors}"
    assert not [c for c in console if "[device]" in c or "TypeError" in c], console
    assert found, "the chapter file did not register its scene (check ch/_index.js)"
    assert {"1.00", "1.50", "2.00"} <= set(drawn), f"the template's lyric did not mark its tokens: {drawn}"
    assert face and len(face) == 4, "the common.js boxes recipe did not give m.box('a face') a box"
    assert len(jpg) > 1000


# --- the doc's copies of the workflow schemas match the templates they quote ---------------------------------------
@pytest.mark.parametrize("template,start,stop", [
    ("chapters.js", "const REVIEW = ", "\nconst SEVERITY"),
    ("safety-scan.js", "const SCHEMA = ", "\n\nphase("),
])
def test_workflow_schemas_copied_exactly(template: str, start: str, stop: str) -> None:
    src_path = ROOT / "templates" / "workflows" / template
    if not src_path.is_file():
        pytest.skip(f"{template} not present")
    src = src_path.read_text(encoding="utf-8")
    i = src.index(start)
    want = src[i:src.index(stop, i)].strip()
    block = _js_block(_text(DOCS / "80-review-qa.md"), start.strip())
    got = block[block.index(start):].strip()
    norm = lambda x: re.sub(r"\s+", " ", x).strip()  # noqa: E731
    assert norm(got) == norm(want), f"80-review-qa.md's copy of {template}'s schema has drifted: re-copy it"

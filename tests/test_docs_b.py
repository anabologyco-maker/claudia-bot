"""Tests for module docs-b: the plates / clips / lip-sync / moderation playbooks.

Files under test: docs/50-plates-midjourney.md, docs/51-plates-api.md, docs/60-clips.md, docs/61-lipsync.md,
docs/62-moderation.md.

What is checked (fast, offline, no fixtures on disk):
- well-formed Markdown: one H1, balanced code fences (3- and 4-backtick), no tabs;
- cross-references: every `NN-name.md` points at a planned doc (ARCHITECTURE §6); every § reference into one of these
  five docs names a section that exists;
- the scrub list (ARCHITECTURE §7.12): no owner identity, no Midjourney profile code, no hostnames, no job ids, no
  e-mail addresses, no banned word. The private words are compared by SHA-256 only, so this file never contains them
  (it is scanned too);
- the verified provider facts (ARCHITECTURE §7b): reference mode by default, first frames drop the audio, data: audio
  is rejected, photoreal faces are routed to Higgsfield; the coverage-based accept rule; consistent counts;
- every `slop …` command the docs cite exists in the real CLI, and every full example line parses;
- the load-bearing facts and verbatim templates the operator relies on;
- worked numbers recomputed from their formulas (Seedance prices, the lag example);
- the documented permutation paste expands to the stated job count under Midjourney's escaping rules;
- the timing-sheet snippet in 60-clips runs on a synthetic project and prints the right words and kicks.
"""
from __future__ import annotations

import hashlib
import json
import re
import runpy
import sys
from pathlib import Path

import pytest

DOCS = Path(__file__).resolve().parent.parent / "docs"
MINE = ["50-plates-midjourney.md", "51-plates-api.md", "60-clips.md", "61-lipsync.md", "62-moderation.md"]
PLANNED = {
    "00-overview.md", "10-song.md", "20-analysis.md", "30-taste.md", "40-storyboard.md",
    "50-plates-midjourney.md", "51-plates-api.md", "60-clips.md", "61-lipsync.md", "62-moderation.md",
    "70-motion-design.md", "80-review-qa.md", "90-master-publish.md", "95-delegation.md",
    "96-setup-and-hardware.md", "99-failures.md",
}
# SHA-256 of the private Midjourney profile code that must never ship (the code itself is not stored anywhere here).
PROFILE_CODE_SHA256 = "841486c93b12e81bd9fa1e7a86ce75862d65b62e8963979da438ecfcd5684700"
KEEP_CLAUSE = ("Keep everything else exactly as it is: the same framing and crop, the same light, colours, film grain "
               "and sharpness, the same people and objects except what this instruction changes. Photorealistic, the "
               "same photograph, same aspect ratio.")


def text(name: str) -> str:
    return (DOCS / name).read_text(encoding="utf-8")


def flat(name: str) -> str:
    """The doc with line breaks folded to spaces (facts may wrap across lines)."""
    return re.sub(r"\s+", " ", text(name))


def fenced_blocks(src: str) -> list[str]:
    """Contents of fenced code blocks; handles ``` and ```` fences (a block closes on a fence at least as long)."""
    blocks, cur, fence = [], None, 0
    for line in src.split("\n"):
        m = re.match(r"^\s*(`{3,})", line)
        if cur is None:
            if m:
                fence, cur = len(m.group(1)), []
        else:
            if m and len(m.group(1)) >= fence and line.strip() == m.group(1):
                blocks.append("\n".join(cur))
                cur = None
            else:
                cur.append(line)
    assert cur is None, "unclosed code fence"
    return blocks


def section_ids(src: str) -> set[str]:
    ids = set()
    for line in src.split("\n"):
        m = re.match(r"^#{2,4} (\d+(?:\.\d+)*)[. ]", line)
        if m:
            ids.add(m.group(1))
    return ids


# ---------------------------------------------------------------- structure


@pytest.mark.parametrize("name", MINE)
def test_doc_exists_and_is_well_formed(name):
    p = DOCS / name
    assert p.is_file(), f"missing {p}"
    src = text(name)
    assert len(src) > 8000, "a playbook this short is missing content"
    lines = src.split("\n")
    assert lines[0].startswith("# "), "first line must be the H1 title"
    # an H1 inside a code block (e.g. a script comment) is fine; count only outside fences
    outside, in_fence, fence = [], False, 0
    for line in lines:
        m = re.match(r"^\s*(`{3,})", line)
        if m and not in_fence:
            in_fence, fence = True, len(m.group(1))
            continue
        if m and in_fence and len(m.group(1)) >= fence and line.strip() == m.group(1):
            in_fence = False
            continue
        if not in_fence and line.startswith("# "):
            outside.append(line)
    assert len(outside) == 1, f"exactly one H1 expected outside code, got {outside}"
    assert "\t" not in src, "tabs in Markdown"
    fenced_blocks(src)  # raises on an unclosed fence


@pytest.mark.parametrize("name", MINE)
def test_cross_references_resolve(name):
    src = text(name)
    for ref in re.findall(r"\b(\d\d-[a-z0-9-]+\.md)\b", src):
        assert ref in PLANNED, f"{name} links to unknown doc {ref}"
    own = section_ids(src)
    for line in src.split("\n"):
        for m in re.finditer(r"§(\d+(?:\.\d+)?)", line):
            before = line[:m.start()]
            if re.search(r"ARCHITECTURE(\s*§[\d.]+,)*\s*$", before):
                continue
            doc = re.search(r"`(\d\d-[a-z0-9-]+\.md)`\s*$", before)
            target = doc.group(1) if doc else name
            if target not in MINE:
                continue  # sections of other modules' docs are theirs to keep
            ids = own if target == name else section_ids(text(target))
            assert m.group(1) in ids, f"{name}: '§{m.group(1)}' not found in {target}: {line.strip()[:100]}"


# ---------------------------------------------------------------- scrub


# Private words that must never ship, as full SHA-256 digests (the words themselves are not written anywhere in this
# file): the owner's initials (case-sensitive), private user, host, network and volume names, and the owner's taboo
# word. Every token of a scanned file is hashed as written, lower-cased, by its dotted suffixes (host.domain.tld) and by
# its parts split on "." "-" "_".
FORBIDDEN_SHA256 = {
    "0df9e03357ae3a2b287a404094d2d61aa6ec114eb8bb1c92a6c2154a03dc438a": "the owner's initials",
    "8c5a24e9400550c2ab78a75f840425ab942e0faf92af4809c547fa68a5549ffb": "a private user name",
    "a537830719fd3767b1898d8f730256de94f9c69b287704435e69104a6cca2f39": "a private host",
    "65a9200f9247b5eb6ed0c449c89cd31913441d3b516acdefe6c7479fc4f56d04": "a private host",
    "9702d9de853966388d3fbbb1692969bb672e2a628e7a2d18bb00ea6904b3e4e2": "a private host",
    "ec6f049478046f72becb006a2339202eae93911281dd610a7c869adec1ba3297": "a private network name",
    "795b104abe3e4134960ca245ded0e617f162c751209347b7f003bc35e062f43e": "a private network name",
    "9c2c431ce731298cb3b0a8d47a11d98efe8c606df8d5ecc49f471e1e0e970f8f": "a private network domain",
    "a189ab606c73e71be38a14dd49c67b45257222a0631397f9555f7a767369435c": "a private repository name",
    "0d2a1a78af155f27dbc77a32b25d43f974bf1c96cd71b3c930702f2459288216": "a private host folder",
    "cb0eaefae8eacd1d5d385adffc8407215e9f60aab4d53e1174158e71d884a88e": "a private volume name",
    "ae679821f0649c15f6c5181130efecf6ca5e4eb04e469b87510b48aa4725a449": "the owner's taboo word",
}
FORBIDDEN_RE = [
    (re.compile(r"/opt/|C:\\Users|/mnt/c/|/home/[a-z]", re.I), "a private path"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[a-z]{2,}"), "an e-mail address"),
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I), "a job / media id"),
    (re.compile(r"gen-vid-\d"), "an OpenRouter job id"),
    (re.compile(r"sk-or-[A-Za-z0-9]|sk-[A-Za-z0-9]{20,}"), "an API key"),
]


def _sha(w: str) -> str:
    return hashlib.sha256(w.encode("utf-8")).hexdigest()


def forbidden_hits(src: str) -> list[str]:
    hits = []
    for m in re.finditer(r"[A-Za-z0-9][A-Za-z0-9.\-_]*", src):
        tok = m.group(0).rstrip(".-_")
        low = tok.lower()
        cands = {tok, low}
        labels = low.split(".")
        cands.update(".".join(labels[i:]) for i in range(1, len(labels)))
        cands.update(re.split(r"[.\-_]", low))
        for c in cands:
            if c and _sha(c) == PROFILE_CODE_SHA256:
                hits.append("the Midjourney profile code")
            why = FORBIDDEN_SHA256.get(_sha(c)) if c else None
            if why:
                hits.append(f"{why}: {tok!r}")
    for rx, why in FORBIDDEN_RE:
        hits += [f"{why}: {m.group(0)!r}" for m in rx.finditer(src)]
    return hits


@pytest.mark.parametrize("name", MINE)
def test_scrubbed(name):
    src = text(name)
    hits = forbidden_hits(src)
    assert not hits, f"{name} must not ship: " + "; ".join(sorted(set(hits)))
    for m in re.finditer(r"--(?:profile|p)\s+(<[^>\n]*>|[^\s`\"',;)]+)", src):
        assert m.group(1).startswith("<") and m.group(1).endswith(">"), f"{name}: a concrete profile code: {m.group(0)}"
    # a profile code is never written into a prompt: personalization is the P button
    if name == "50-plates-midjourney.md":
        assert "**Never a profile code:**" in src and "<YOUR_PROFILE_CODE>" not in src


def test_this_test_file_is_scrubbed_too(monkeypatch):
    own = Path(__file__).read_text(encoding="utf-8")
    hits = [h for h in forbidden_hits(own) if not h.startswith(("a private path", "an e-mail", "a job", "an OpenRouter",
                                                               "an API key"))]
    assert not hits, hits
    # the scanner itself still catches planted words (stand-ins added to the hash list for this test only)
    for w in ("plantedhost", "plantedword", "plx"):
        monkeypatch.setitem(FORBIDDEN_SHA256, _sha(w), "a planted word")
    planted = "see plantedhost.example.net and PlantedWord and the PLX cut"
    assert len(forbidden_hits(planted)) == 3


# ---------------------------------------------------------------- 50 · Midjourney


def test_mj_grammar_slots_in_order():
    src = text("50-plates-midjourney.md")
    want = [("Slot 1", "Framing"), ("Slot 2", "canon"), ("Slot 3", "Placement"), ("Slot 4", "Pose"),
            ("Slot 5", "Set and props"), ("Slot 6", "empty field"), ("Slot 7", "style tail"), ("Slot 8", "closer")]
    pos = -1
    for slot, word in want:
        m = re.search(rf"^### {slot} — .*{word}", src, re.M | re.I)
        assert m, f"missing heading for {slot} ({word})"
        assert m.start() > pos, f"{slot} out of order"
        pos = m.start()
    rule = flat("50-plates-midjourney.md")
    assert ("framing/vantage → lead canon (visible garments only) → placement → pose → set/props with the concept as an "
            "object → declared empty field for type → chapter style tail → `no text, no letters, no logos`") in rule


def test_mj_facts():
    f = flat("50-plates-midjourney.md")
    for needle in [
        "**Never `--v`:**", "**Never a profile code:**", "P button", "Personalize", "unlocks", "a record, not a setting",
        "`mj.personalize`", "`--oref`", "Edit Model",
        "≤ 4 (Basic), ≤ 10 (Standard), ≤ 40 (Pro, Mega)", r"`\,`", "variety pool", "`lead.far`", "`lead.possessive`",
        "Caucasian American", "2944×1648", "1456×816", "no text, no letters, no logos", "Grok runs Midjourney in its browser",
        "never type, read or store your password", "never by position", "plates/picks.json", "cand_k",
        "Casting call", "single-variable", "one batch at a time", "Fix the source", "G3",
    ]:
        assert needle in f, f"50 is missing: {needle}"
    assert KEEP_CLAUSE in f


def _mj_expand(paste: str) -> list[str]:
    """Expand one Midjourney permutation paste: `{a, b} params` -> ['a params', 'b params'] honouring `\\,`."""
    m = re.fullmatch(r"\{(.*)\}\s*(.*)", paste.strip(), re.S)
    assert m, "a permutation paste starts with { and closes with } before the parameters"
    body, params = m.group(1), m.group(2)
    assert "{" not in body and "}" not in body, "nested braces in a plate permutation"
    parts = re.split(r"(?<!\\),", body)
    return [p.strip().replace("\\,", ",") + " " + params for p in parts]


def test_mj_permutation_example_expands_to_stated_count():
    src = text("50-plates-midjourney.md")
    blocks = [b for b in fenced_blocks(src) if b.strip().startswith("{") and "\\," in b]
    assert blocks, "no permutation example found"
    jobs = _mj_expand(blocks[0])
    stated = int(re.search(r"That paste is \*\*(\d+) jobs\*\*", src).group(1))
    assert len(jobs) == stated
    for j in jobs:
        prompt, params = j.split(" --ar ", 1)
        assert prompt.endswith("no text, no letters, no logos")
        assert params.strip() == "16:9 --raw", params                # no --v, no profile code
    # escaping a real comma-heavy plate prompt the documented way survives the round trip
    plate = "close-up of a woman, eyes closed, the lower third empty, no text, no letters, no logos"
    paste = "{" + ", ".join(p.replace(",", "\\,") for p in [plate, plate]) + "} --ar 16:9"
    assert [j.rsplit(" --ar", 1)[0] for j in _mj_expand(paste)] == [plate, plate]


def test_mj_exemplars_end_with_closer():
    src = text("50-plates-midjourney.md")
    ex = src[src.index("## 14. Exemplars"):src.index("## 15. Checklists")]
    prompts = [b.strip() for b in fenced_blocks(ex) if not b.strip().startswith("{")]
    assert len(prompts) >= 7
    for p in prompts:
        assert p.endswith("no text, no letters, no logos"), p[:80]
        assert len(p) < 1100, "exemplar longer than the documented prompt budget allows"


# ---------------------------------------------------------------- 51 · API images


def test_api_models_and_edit_grammar():
    f = flat("51-plates-api.md")
    for needle in [
        "openai/gpt-image-2", "openai/gpt-image-2.5-flare", "openai/gpt-image-2.5-sunburst",
        "bytedance-seed/seedream-5-0-lite", "google/gemini-3-pro-image", "x-ai/grok-imagine-image-2.0",
        "soul_cast", "GenerateImage", "Quick tier", "Edit this photograph. Change only <X>",
        "never** for", "Lanczos", "aspect_ratio", "`usage.cost`",
    ]:
        assert needle in f, f"51 is missing: {needle}"
    assert KEEP_CLAUSE in f, "the fixed KEEP clause must be identical in 50 and 51"


# ---------------------------------------------------------------- 60 · clips


SUNG_HEAD = '@Image1 sings @Audio1. She lip-syncs to @Audio1 exactly, every word in time: "<exact words>".'
EV_SUNG = ('@Image1 sings @Audio1. She lip-syncs to @Audio1 exactly, every word in time: "<exact aligned words in the '
           'window>". <Framing> of the woman from @Image1 <pose/action, singing/saying the words + how>. <Light>. '
           '<Camera>, no cuts[, no head turns].')
EV_MOTION = ('The scene from @Image1, moving in time with @Audio1. <Framing>. The woman from @Image1 <one clear action '
             'with an end state>. <Camera move>. No cuts. Her mouth stays closed, face expressionless.')


def test_clip_templates_verbatim():
    blocks = [b.strip() for b in fenced_blocks(text("60-clips.md"))]
    assert SUNG_HEAD in blocks
    assert EV_SUNG in blocks
    assert EV_MOTION in blocks
    screenplay = next(b for b in blocks if b.startswith("[@Image1 sings @Audio1."))
    for part in ["0.0–a.aa s:", '("<words>")', "(<the sound:", "Camera:", "<Mouth rule>",
                 "One continuous shot, no cuts. No text, letters or logos."]:
        assert part in screenplay


def test_clip_facts():
    f = flat("60-clips.md")
    for needle in [
        "830", "in one context", "reads the whole prompt book", "stop every path that can spend", "G5",
        "Length 4–8 s", "Start in a word gap", "Quote ALL the words", "≥ 0.8 s before the window end",
        "`generate_audio: false`", "**$0.231/s at 720p**", "**$0.103/s at 480p**", "3 / 7 / 12 credits per second",
        "`mode: \"omni_reference\"` always explicit", "with `estimate_video_cost` and the request's own `params`",
        "`generate_video` no longer takes `get_cost`", "`declined_preset_id`",
        "Wan 3.0", "Grok Video 1.5", "Kling 3 Turbo", "MiniMax H3", "`draft: true`", "`draft_job_id`",
        "story beat", "action **and** reaction", "environment answers the music", "camera is tied to the hits",
        "Mouth rules", "start_image → image_references → video_references → audio_references", "**`@Image2`**",
    ]:
        assert needle in f, f"60 is missing: {needle}"


def test_seedance_prices_match_formula():
    f = flat("60-clips.md")
    rate = float(re.search(r"\*\*\$(0\.0000107)\*\* per token", f).group(1))
    per_s = lambda w, h: w * h * 24 / 1024 * rate  # noqa: E731
    assert round(per_s(1280, 720), 3) == 0.231
    assert round(per_s(854, 480), 3) == 0.103
    for secs, usd in [(4, "0.92"), (5, "1.16"), (8, "1.85")]:
        assert f"{secs} s = ${usd}" in f
        assert f"{per_s(1280, 720) * secs:.2f}" == usd
    assert f"4 s = ${per_s(854, 480) * 4:.2f}" in f
    # the worked budget example
    m = re.search(r"= 140 s × \$0\.231 = \$([\d.]+), \+ covers 0\.6 × 60 s × \$0\.231 = \$([\d.]+)", f)
    assert m and float(m.group(1)) == round(140 * 0.231, 2) and float(m.group(2)) == round(0.6 * 60 * 0.231, 2)


def test_screenplay_exemplars_are_well_timed():
    src = text("60-clips.md")
    ex = src[src.index("## 11. Exemplars"):src.index("## 12. Failure catalogue")]
    blocks = [b for b in fenced_blocks(ex)]
    timed = 0
    for b in blocks:
        assert re.search(r"no cuts", b, re.I), b[:80]
        quoted_head = re.match(r'@Image1 sings @Audio1\. She lip-syncs to @Audio1 exactly, every word in time: "([^"]+)"',
                               b)
        for a, z in re.findall(r"^(\d+\.\d+)–(\d+\.\d+) s", b, re.M):
            timed += 1
            assert 0.0 <= float(a) <= float(z) <= 8.0, (a, z)
        if quoted_head and "\n" in b:  # screenplay form: every quoted word appears in a timestamp line
            said = " ".join(re.findall(r'^\d+\.\d+–\d+\.\d+ s \("([^"]+)"\)', b, re.M))
            norm = lambda s: re.findall(r"[a-z']+", s.lower())  # noqa: E731
            assert norm(quoted_head.group(1)) == norm(said) or set(norm(quoted_head.group(1))) <= set(norm(said)), \
                f"not every quoted word has a timestamp: {quoted_head.group(1)}"
    assert timed >= 30


def test_timing_sheet_snippet_runs(tmp_path, capsys, monkeypatch):
    src = text("60-clips.md")
    snippet = next(b for b in fenced_blocks(src) if b.startswith("# timing_sheet.py"))
    proj = tmp_path / "proj"
    (proj / "analysis").mkdir(parents=True)
    words = [{"i": 0, "w": "before", "line": 0, "t0": 9.50, "t1": 9.80},
             {"i": 1, "w": "why", "line": 1, "t0": 10.30, "t1": 10.42},
             {"i": 2, "w": "would", "line": 1, "t0": 10.50, "t1": 10.66},
             {"i": 3, "w": "late", "line": 2, "t0": 13.95, "t1": 14.10}]  # starts after t1 - 0.08 -> not quoted
    lines = [{"line": 0, "text": "Before the night,", "t0": 9.5, "t1": 9.8},
             {"line": 1, "text": "Why would I deceive you?", "t0": 10.3, "t1": 11.2},
             {"line": 2, "text": "Too late.", "t0": 13.95, "t1": 14.6}]
    (proj / "analysis" / "words.json").write_text(json.dumps({"words": words, "lines": lines}), encoding="utf-8")
    (proj / "analysis" / "hits.json").write_text(json.dumps(
        {"kick": [9.0, 10.45, 11.0, 14.5], "snare": [10.9], "hits": [{"t": 12.16, "score": 0.9}]}), encoding="utf-8")
    (proj / "analysis" / "beats.json").write_text(json.dumps(
        {"beats": [10.0, 10.45, 10.9], "downbeats": [10.0, 11.8]}), encoding="utf-8")
    script = tmp_path / "timing_sheet.py"
    script.write_text(snippet, encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [str(script), str(proj), "10.0", "4"])
    runpy.run_path(str(script), run_name="__main__")
    out = capsys.readouterr().out
    # the quote comes from the lyric sheet's line text (spelling + punctuation), the times from the aligned tokens
    assert 'line 1: "Why would I deceive you?"' in out
    assert "line 0" not in out and "line 2" not in out and "Before the night" not in out and "Too late" not in out
    assert "0.30-0.42 s  why" in out and "0.50-0.66 s  would" in out
    assert "s  before" not in out and "s  late" not in out
    assert "KICK: 0.45, 1.00" in out
    assert "SNARE: 0.90" in out
    assert "DOWNBEATS: 0.00, 1.80" in out
    assert "IMPACTS: 2.16" in out
    # a words.json without lines[] still runs (the line text shows as "?")
    (proj / "analysis" / "words.json").write_text(json.dumps({"words": words}), encoding="utf-8")
    runpy.run_path(str(script), run_name="__main__")
    assert 'line 1: "?"' in capsys.readouterr().out


# ---------------------------------------------------------------- 61 · lip sync


def test_lipsync_facts():
    f = flat("61-lipsync.md")
    for needle in [
        "copies the reference audio into its own soundtrack", "The mouth follows that soundtrack",
        "NCC > 0.2", "±1.0 s", "**0.35 s**", "**0.40 s**", "**24 dB**", "**15 ms raised-cosine ramps**",
        "**−16 dBFS RMS**", "**−1 dBFS**", "**last eighth ≤ `synced_until`**", "**0.6 s**", "≥ 0.8 s",
        "**41 %**", "**≈ 21 %**", "≈ 86 % of sung seconds", "cut away", "`sync_so`", "`sync_mode: \"cut_off\"`",
        "Opt-in only", "measured per take", "clamp(ceil(end − start + 0.3), 4, 8)", "frame **at the cut**",
        "thr = null90 + 0.4 × (matched_med − null90)", "±37, ±61, ±89, ±131 frames",
    ]:
        assert needle in f, f"61 is missing: {needle}"
    assert "song time  = song_t0 + clip_time − lag_s" in text("61-lipsync.md")
    assert "clip time  = song time − song_t0 + lag_s" in text("61-lipsync.md")


def test_lag_worked_example_is_right():
    f = flat("61-lipsync.md")
    m = re.search(r"([\d.]+) − ([\d.]+) \+ ([\d.]+) = \*\*([\d.]+) s\*\*", f)
    assert m, "worked lag example missing"
    a, b, c, res = map(float, m.groups())
    assert round(a - b + c, 3) == res


# ---------------------------------------------------------------- 62 · moderation


def test_moderation_facts_and_table():
    src = text("62-moderation.md")
    f = flat("62-moderation.md")
    for needle in [
        "Never alter an image to get it past a filter", "SAME unaltered image", "PrivacyInformation",
        "InputTextSensitiveContentDetected", "copyright restrictions", "`generate_audio: false`", "status `failed`",
        "`nsfw`", "`declined_preset_id`", "`unlim_choice`", "Keep the beat, change the words", "AI IMAGE",
        "8 %, 25 %, 42 %, 58 %, 75 %, 92 %", "`80-review-qa.md` §9", "empty or missing result is a failure",
        "never solves a captcha",
    ]:
        assert needle in f, f"62 is missing: {needle}"
    lines = src[src.index("| Clip | Blocked wording | What passed |"):].split("\n")
    assert re.fullmatch(r"\|(-+\|){3}", lines[1].replace(" ", "")), "table separator row missing"
    rows = []
    for line in lines[2:]:
        if not line.startswith("|"):
            break
        rows.append(line)
    assert len(rows) >= 12
    for r in rows:
        cells = [c.strip() for c in r.strip("|").split("|")]
        assert len(cells) == 3 and all(cells), r


# ---------------------------------------------------------------- verified provider facts (ARCHITECTURE §7b)


def test_reference_mode_is_the_default_and_first_frames_drop_audio():
    f60, f61, f62 = flat("60-clips.md"), flat("61-lipsync.md"), flat("62-moderation.md")
    for needle in ["Reference mode is the default for every clip, sung and motion",
                   "First-frame mode drops `@Audio1` on OpenRouter", "sung clips never use a first frame",
                   "`slop clip new s014 --kind motion --frame first`",
                   "`The scene from @Image1, moving in time with @Audio1.` (reference mode, **the default**)"]:
        assert needle in f60, f"60 is missing: {needle}"
    assert "the plate as the **first frame**" not in f60, "motion clips must not default to first-frame mode"
    assert "`frame_images` wins" not in f60, "say that the audio is lost, not just that frame_images wins"
    assert "**Never as OpenRouter `frame_images`**" in f61
    assert "Never \"fix\" a decline by switching a sung clip, or a cover, to an **OpenRouter first frame**" in f62
    assert "try the image as a **reference** instead of a first frame" not in f62


def test_audio_hosting_is_the_verified_answer():
    f = flat("60-clips.md")
    for needle in ["**Inline `data:` audio is rejected**", "\"Only HTTPS URLs are allowed\"", "slop gen tunnel start",
                   "slop gen host W02 --tunnel", "slop gen host W02 --url https://<the CloudFront URL> --media-id"]:
        assert needle in f, f"60 is missing: {needle}"
    assert not re.search(r"data:` audio is untested", f)


def test_accept_rule_is_coverage_based():
    f = flat("61-lipsync.md")
    assert "**Accept rule (coverage, not NCC):**" in f
    assert "The global NCC is a **diagnostic only**" in f
    assert "`mode == \"copy\"` **and**" not in f, "the old NCC-gated accept rule is back"
    assert "**0.157** and still held **99 %**" in f  # W05b take 2: low NCC, full hold
    # the two meanings of "correlation" are labelled
    assert "windowed 100 ms waveform measure (**wave**, §3) scores 0.8–0.97" in f and "**global NCC**" in f


def test_photoreal_routing_is_stated_everywhere():
    for name in ("60-clips.md", "62-moderation.md", "51-plates-api.md"):
        f = flat(name)
        assert "18 of 27" in f, f"{name}: the photoreal decline figure"
        assert re.search(r"[Ii]llustrated or stylized", f), f"{name}: stylized faces pass"
    f60 = flat("60-clips.md")
    assert "**Higgsfield** Seedance 2.5 720p (`--provider higgsfield`" in f60
    assert "OpenRouter first for every clip" not in f60
    assert "a photoreal sung close-up" in f60 or "photoreal sung close-ups on Higgsfield first" in f60
    assert "### 3.1 Photoreal or stylized?" in text("51-plates-api.md")


def test_sync_evidence_is_complete():
    f61 = flat("61-lipsync.md")
    holds = text("61-lipsync.md")[text("61-lipsync.md").index("**All five full holds on Higgsfield**"):]
    for take in ("`W02` take 1", "`W07` take 2", "`W15` (burn round)", "`W05b` take 2", "`W09` take 2"):
        assert take in holds, take
    assert "**Weak observations, not rules**" in f61
    assert "**The provider difference is not established.**" in f61
    assert "| SP, OpenRouter | **0 of 8** sung takes |" in text("61-lipsync.md")
    assert "Trust the measured figures" in f61
    f60 = flat("60-clips.md")
    assert "this long timestamped form held only **28 %**" in f60 and "held **100 %**" in f60
    assert "whispers at the ear rarely lock" not in f60


def test_counts_agree_across_the_module():
    f60, f61 = flat("60-clips.md"), flat("61-lipsync.md")
    assert "47 clips + 28 covers (plus 2 LatentSync patches and 7 tests) in 91 submissions" in f60
    assert "28 covers (plus 2 LatentSync patches) across 47 clips" in f61
    for f in (f60, f61):
        assert "30 covers" not in f
    # MiniMax H3 on OpenRouter: 5–15 s, $0.13/s -> the shortest clip is 5 s
    assert "**5–15 s** on OpenRouter" in f60 and f"5 s: **${5 * 0.13:.2f}**" in f60
    assert "use 4–8 for sung windows and 4–12 for motion" in f60
    assert "`duration = clamp(ceil(needed_end − song_t0 + 0.3), 4, 8)`" in f60
    assert "**On Higgsfield: keep the last needed word ≥ 0.8 s before the window end**" in f60


def test_api_defaults_match_the_project_template():
    tpl = json.loads((DOCS.parent / "templates" / "project" / "project.json").read_text(encoding="utf-8"))
    f = flat("51-plates-api.md")
    sec = f[f.index("### 2.4 Defaults"):f.index("### 2.5 Before you spend")]
    assert f'`models.image: "{tpl["models"]["image"]}"`' in sec
    assert f'`models.edit: "{tpl["models"]["edit"]}"`' in sec
    assert "low **$0.004** (measured, 1536×864" in f
    for needle in ("slop plates book", "slop gen estimate", "slop gate prompts --approve", "--yes",
                   "budget.openrouter_usd", "budget.confirm_over_usd", "4 test plates of the lead", "G3"):
        assert needle in f[f.index("### 2.5 Before you spend"):], f"51 §2.5 is missing: {needle}"


def test_mj_permutation_test_chunk_and_manual_lint():
    f = flat("50-plates-midjourney.md")
    assert "**The first permutation paste of a project is a 3-prompt test chunk.**" in f
    assert "Long Prompt" in f
    assert "No single command runs all of these" in f
    assert "Run the lint (§7.3)" not in f
    ex = f[f.index("`ghost-float`; the canon is shown as its slot"):]
    assert "**This is the one exception to rule 5:**" in ex


# ---------------------------------------------------------------- the commands the docs cite are real


def _parser():
    sys.path.insert(0, str(DOCS.parent))
    from slop.cli import build_parser
    return build_parser()


def _subchoices(parser):
    import argparse
    for act in parser._actions:
        if isinstance(act, argparse._SubParsersAction):
            return act.choices
    return None


def _cited_commands(src: str) -> tuple[list[str], list[str]]:
    """(inline `slop …` spans, full `slop …` lines from code blocks), placeholders filled in."""
    inline = [m.group(1) for m in re.finditer(r"`(slop [^`]+)`", src)]
    lines = []
    for b in fenced_blocks(src):
        for ln in b.split("\n"):
            ln = ln.strip()
            if ln.startswith("slop ") and "$(" not in ln:
                lines.append(re.split(r"\s{2,}#", ln)[0].strip())
    return inline, lines


def _tokens(cmd: str) -> list[str]:
    import shlex
    return shlex.split(re.sub(r"<[^>]*>", "1", cmd))[1:]


def _path(tokens: list[str]) -> list[str]:
    i = 0
    while i < len(tokens) and tokens[i].startswith("-"):
        i += 2 if tokens[i] in ("--project", "-p") else 1
    return tokens[i:]


@pytest.mark.parametrize("name", MINE)
def test_cited_commands_exist(name):
    ap = _parser()
    root = _subchoices(ap)
    inline, lines = _cited_commands(text(name))
    assert inline or name == "62-moderation.md" or lines, f"{name} cites no slop command"
    for cmd in inline + lines:
        toks = _path(_tokens(cmd))
        if not toks or not re.fullmatch(r"[a-z][a-z-]*", toks[0]):
            continue
        assert toks[0] in root, f"{name}: `{cmd}`: there is no `slop {toks[0]}`"
        sub = _subchoices(root[toks[0]])
        if sub is not None and len(toks) > 1 and re.fullmatch(r"[a-z][a-z-]*", toks[1]):
            assert toks[1] in sub, f"{name}: `{cmd}`: `slop {toks[0]}` has no action {toks[1]!r} ({sorted(sub)})"
    for cmd in lines + [c for c in inline if "…" not in c and any(not t.startswith("-") for t in _path(_tokens(c))[2:])]:
        try:
            ap.parse_args(_tokens(cmd))
        except SystemExit:
            pytest.fail(f"{name}: this documented command does not parse: {cmd}")


@pytest.mark.parametrize("name", MINE)
def test_no_help_hedges(name):
    assert "slop --help" not in text(name), f"{name}: cite the real command instead of 'run slop --help'"

"""Studio-run fix, track sung: sung (lip-sync) clips draft the SHORT template by default; the timestamped screenplay stays
the default for motion clips (and a sung acting moment on request); `clip lock` warns, never refuses, when a sung prompt
runs past ~90 words or 2 timed beats; covers of sung clips stay short.

Why (measured on a live Studio-tier run, docs/61-lipsync.md §1.1): with long screenplay prompts Seedance re-sang the line
instead of copying @Audio1 — c01 0 % -> 78 % of its sung seconds in sync with the short form, SP W02 28 % -> 100 %."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import re
import shlex
import sys
from pathlib import Path

import numpy as np
import pytest

_H = Path(__file__).parent / "fixtures" / "gen" / "helpers.py"
_spec = importlib.util.spec_from_file_location("gen_test_helpers", _H)
H = importlib.util.module_from_spec(_spec); sys.modules.setdefault("gen_test_helpers", H); _spec.loader.exec_module(H)

from slop.cli import main  # noqa: E402
from slop.config import SlopError  # noqa: E402
from slop.gen import clips, store, templates as tpl  # noqa: E402

KEY = "sk-or-v1-test-not-a-real-key"
DOCS = Path(__file__).resolve().parent.parent / "docs"
HEAD = '@Image1 sings @Audio1. She lip-syncs to @Audio1 exactly, every word in time: '
SUNG_CLOSER = "One continuous shot, no cuts, no head turns. Only she sings. No text, letters or logos."

# SP W02, the long timestamped screenplay that held 28 % (60-clips §11), and EV SD08, a short sung prompt
W02_LONG = (HEAD + '"Why would I deceive you?".\n'
            "Night on her black sea rock, moonlight, faint spray. Close-up of the woman from @Image1 (black bob, one orange "
            "streak, star clip, thin headset mic, white ruffled gown). Someone has just asked her whether they can trust "
            "her; this is her answer, sung softly a cappella straight into the lens, as if to one person.\n"
            "0.0–0.3 s: she draws a slow breath, lips parting, eyes on the lens, head tilted a little.\n"
            '0.3–0.74 s ("Why would I"): she sings softly, her eyebrows lifting a fraction, as if the question has hurt '
            "her feelings a little.\n"
            '0.88–1.34 s ("deceive"): she leans closer to the lens; her voice warms and her eyes soften.\n'
            '1.44–1.56 s ("you?"): the word ends on a small, disarming smile; her eyes stay on ours.\n'
            "1.6–2.16 s: silence; she holds the gaze, lips parted, completely sure of herself.\n"
            "2.16 s (the beat drops): a wave bursts behind her and the wind whips her wet bob across her cheek; she does "
            "not flinch, and her smile deepens.\n"
            "2.16–4.0 s: she keeps looking into the lens, lips closed, as the spray falls.\n"
            "Camera: a very slow push in until 2.16 s, a small jolt on the drop, then still. One continuous shot, no cuts. "
            "No text, letters or logos.")
SD08_SHORT = (HEAD + '"Lock in, baby, foot down on the gas. Feel the A G I, feel it". Close-up of the woman from @Image1 '
              "with her black bob, clay-orange streak and headset microphone, facing the camera, singing with her eyes "
              "closed, her head tilting back slightly on the long notes. Warm light from the side. Locked camera, very "
              "slight push in, no cuts, no head turns.")


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SLOP_PROJECTS", str(tmp_path / "projects"))
    monkeypatch.setenv("OPENROUTER_API_KEY", KEY)
    monkeypatch.delenv("SLOP_PROJECT", raising=False)
    H.write_cache(tmp_path / "home")
    return H.make_project(tmp_path / "projects")


def run(pdir, *argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(["--json", "--project", str(pdir), *argv])
    return rc, json.loads(buf.getvalue())


def filled(prompt: str, text: str = "warm light from the side") -> str:
    return tpl.SLOT_RE.sub(text, prompt)


def write_prompt(env, tmp_path, cid: str, prompt: str) -> None:
    f = tmp_path / f"{cid}.txt"
    f.write_text(prompt, encoding="utf-8")
    rc, out = run(env, "clip", "set", cid, "--prompt-file", str(f))
    assert rc == 0, out


# ------------------------------------------------------------------------------------------------ the counting
def test_timed_beats_and_words_are_counted_outside_the_quoted_lyric():
    assert tpl.timed_beats("0.0–0.3 s: a breath. 2.16 s (the beat drops): spray.") == 2      # a range is one beat
    assert tpl.timed_beats("On every kick (0.45, 0.91, 1.37 s): ripples. At 1.2 seconds she turns.") == 4
    assert tpl.timed_beats("@Image1 sings @Audio1 in a 35mm frame, 4K, 1980s wallpaper.") == 0  # not times
    assert tpl.timed_beats("at 2.16s the drop; at 3 s she smiles") == 2                        # glued decimals count
    assert tpl.timed_beats(HEAD + '"24 7 s, 3 s".') == 0                                      # the lyric is not counted
    st = tpl.prompt_stats(SD08_SHORT)
    assert st == {"words": 60, "beats": 0} and tpl.is_short(SD08_SHORT)
    st = tpl.prompt_stats(W02_LONG)
    assert st["beats"] == 8 and st["words"] > 200 and not tpl.is_short(W02_LONG)
    w = tpl.sung_length_warning(W02_LONG)
    assert "8 timed beats" in w and "words besides the quoted lyric" in w
    assert "0 % to 78 %" in w and "c01" in w and "28 % to 100 %" in w and "W02" in w        # the measured copy rates
    assert "configured lead pronoun" in w and "60-clips.md §4.0" in w
    assert "Only she sings" not in w
    assert tpl.sung_length_warning(SD08_SHORT) is None


def test_the_limits_are_about_ninety_words_and_two_beats():
    base = HEAD + '"Sit up, darling".\nClose-up of the woman from @Image1, singing with her eyes closed.\n' + SUNG_CLOSER
    two = base + "\n1.2 s (downbeat): she tilts her head back.\n2.4 s: she opens her eyes."
    assert tpl.is_short(two) and tpl.sung_length_warning(two) is None
    three = two + "\n3.1 s: she smiles."
    assert "3 timed beats" in tpl.sung_length_warning(three) and "words" not in tpl.sung_length_warning(three).split(".")[0]
    pad = base + "\n" + " ".join(["slowly"] * (tpl.SHORT_MAX_WORDS - tpl.prompt_stats(base)["words"]))
    assert tpl.prompt_stats(pad)["words"] == tpl.SHORT_MAX_WORDS and tpl.sung_length_warning(pad) is None
    over = pad + " still"
    assert f"{tpl.SHORT_MAX_WORDS + 1} words" in tpl.sung_length_warning(over) and "timed beats" not in \
        tpl.sung_length_warning(over).split(".")[0]


def test_defaults_per_kind():
    assert tpl.default_style("sung") == "short" and tpl.default_style("motion") == "screenplay"
    lead = tpl.lead_words({"lead": {"canon": "black bob"}})
    p = tpl.sung_prompt(words="Sit up, darling", phrases=[{"t0": 10.0, "t1": 10.6, "text": "Sit up, darling"}], t0=9.3,
                        duration=4, shot={"framing": "CU"}, lead=lead, kicks=[10.0], downbeats=[10.0])
    lines = p.split("\n")
    assert len(lines) == 3 and lines[0] == HEAD + '"Sit up, darling".' and lines[2] == SUNG_CLOSER
    assert lines[1].startswith("Close-up of the woman from @Image1 (black bob), [[") and "mouth fully visible" in lines[1]
    assert lines[1].endswith("Locked camera.") and tpl.timed_beats(p) == 0
    he = tpl.sung_prompt(words="Go", phrases=[], t0=0, duration=4, shot={}, lead=tpl.lead_words({"lead": {"pronoun": "he"}}),
                         kicks=[], downbeats=[])
    assert "He lip-syncs" in he and "Only he sings." in he and "his mouth fully visible" in he


# ------------------------------------------------------------------------------------------------ clip new
def test_new_sung_clip_drafts_the_short_form_by_default(env):
    r = clips.new(env, "s002", "sung")
    c = r["clip"]
    p = c["body"]["prompt"]
    assert c["draft_notes"]["style"] == "short" and c["draft_notes"]["scaffold"] == p
    lines = p.split("\n")
    assert lines[0] == HEAD + '"Sit up, darling, eyes out on the road.".'
    assert lines[1].startswith("Close-up of the woman from @Image1 (black bob, one orange streak, star clip, headset mic), "
                               "facing the camera, singing with her eyes closed. [[Light")
    assert lines[1].endswith("Locked camera, very slight push in.")                   # the shot's own camera
    assert lines[2] == SUNG_CLOSER and len(lines) == 3
    assert tpl.timed_beats(p) == 0 and tpl.is_short(filled(p))
    assert "Short sung form" in r["text"] and "at most 2 timed beats" in r["text"]
    # the timing is still there for (at most 2) beats
    assert c["draft_notes"]["window_words"] and "kicks" in c["draft_notes"] and "downbeats" in c["draft_notes"]
    # it locks with no warning once the light is written
    clips.set_fields(env, c["id"], prompt=filled(p))
    lk = clips.lock(env, c["id"])
    assert lk["clip"]["status"] == "locked" and lk["warnings"] == [] and "\n  ! " not in lk["text"]


def test_motion_clips_keep_the_screenplay(env):
    c = clips.new(env, "s004", "motion")["clip"]
    p = c["body"]["prompt"]
    assert c["draft_notes"]["style"] == "screenplay"
    assert p.startswith("The scene from @Image1, moving in time with @Audio1. [[Place + light + blocking at 0.0 s")
    assert "\n0.0–5.0 s: [[the main action" in p and tpl.timed_beats(p) >= 1 and p.endswith(tpl.CLOSER)


def test_sung_screenplay_on_request_and_bad_style(env):
    r = clips.new(env, "s002", "sung", style="screenplay")
    p = r["clip"]["body"]["prompt"]
    assert '\n0.7–1.25 s ("Sit up,"): [[' in p and "One continuous shot, no cuts. No text, letters or logos." in p
    assert r["clip"]["draft_notes"]["style"] == "screenplay"
    assert "acting moment" in r["text"] and ("clip new s002 --kind sung --style short --id W01 --t0 10 --t1 12.6 "
                                             "--song-t0 9.3 --duration 4 --start plates/cands/hero-cu/1.png --force") in r["text"]
    # the hinted command rebuilds the same draft in the short form (same id, same start plate)
    again = clips.new(env, "s002", "sung", cid="W01", style="short", force=True)["clip"]
    assert again["id"] == "W01" and again["start"] == r["clip"]["start"] and again["body"]["prompt"].endswith(SUNG_CLOSER)
    with pytest.raises(SlopError, match="--style must be short or screenplay"):
        clips.new(env, "s003", "sung", style="caption")


def test_cli_style_short_drafts_the_short_form(env):
    rc, out = run(env, "clip", "new", "s002", "--kind", "sung", "--style", "short")
    assert rc == 0, out
    p = out["clip"]["body"]["prompt"]
    assert p.endswith(SUNG_CLOSER) and tpl.timed_beats(p) == 0 and out["clip"]["draft_notes"]["style"] == "short"


def test_cli_clip_new_sung_defaults_to_the_short_form(env):
    rc, out = run(env, "clip", "new", "s002", "--kind", "sung")          # every board-audit clip_cmd takes this form
    assert rc == 0 and out["clip"]["draft_notes"]["style"] == "short"
    assert out["clip"]["body"]["prompt"].endswith(SUNG_CLOSER) and tpl.timed_beats(out["clip"]["body"]["prompt"]) == 0
    rc, out = run(env, "clip", "new", "s004", "--kind", "motion")          # motion keeps the screenplay
    assert rc == 0 and out["clip"]["draft_notes"]["style"] == "screenplay"


def test_window_move_redrafts_the_short_scaffold_in_its_own_style(env):
    c = clips.new(env, "s002", "sung")["clip"]
    out = clips.set_fields(env, c["id"], song_t0=9.2)
    c = store.load(env, c["id"])
    assert "prompt scaffold" in out["changed"] and c["draft_notes"]["style"] == "short"
    assert c["body"]["prompt"].endswith(SUNG_CLOSER) and tpl.timed_beats(c["body"]["prompt"]) == 0
    assert not any("timestamped screenplay" in w for w in out["warnings"])


def test_window_move_flags_a_written_short_prompt_only_when_it_has_beats(env, tmp_path):
    c = clips.new(env, "s002", "sung")["clip"]
    plain = filled(c["body"]["prompt"])
    write_prompt(env, tmp_path, "W01", plain)
    out = clips.set_fields(env, "W01", song_t0=9.2)                     # no times in it: nothing to rewrite
    assert not out["warnings"] and clips.lock(env, "W01")["clip"]["status"] == "locked"
    lines = plain.split("\n")
    write_prompt(env, tmp_path, "W01", "\n".join([lines[0], lines[1], "1.3 s (downbeat): she tilts her head back.",
                                                  lines[2]]))
    out = clips.set_fields(env, "W01", song_t0=9.3)                     # its one beat time is now wrong
    assert any("timed beats" in w and "9.20 s + 4" in w for w in out["warnings"])
    with pytest.raises(SlopError, match="timestamps were written for the old one"):
        clips.lock(env, "W01")


# ------------------------------------------------------------------------------------------------ clip lock
def test_lock_warns_on_a_long_sung_prompt_but_locks(env, tmp_path):
    rc, out = run(env, "clip", "new", "s002", "--kind", "sung", "--style", "screenplay")
    assert rc == 0, out
    write_prompt(env, tmp_path, "W01", filled(out["clip"]["body"]["prompt"], "she sings it softly, eyes on the lens"))
    rc, out = run(env, "clip", "lock", "W01")
    assert rc == 0 and out["status"] == "locked"                                # a warning, never a refusal
    assert "timed beats" in out["text"] and "0 % to 78 %" in out["text"] and "28 % to 100 %" in out["text"]
    assert "Locked anyway" in out["text"] and "clip set W01 --prompt-file FILE" in out["text"]
    # an already locked clip says nothing new; the warning is computed from the clip file
    again = clips.lock(env, "W01")
    assert "already locked" in again["text"] and "timed beats" not in again["text"]
    c = store.load(env, "W01")
    assert clips.lock_warnings(c) and c["status"] == "locked"


def test_lock_counts_beats_and_words_on_a_written_short_prompt(env, tmp_path):
    c = clips.new(env, "s002", "sung")["clip"]
    short = filled(c["body"]["prompt"]) + "\n1.3 s (downbeat): she tilts her head back on the long note."
    write_prompt(env, tmp_path, c["id"], short)
    assert clips.lock(env, c["id"])["warnings"] == []                           # 1 beat: fine
    three = short + "\n2.2 s: she opens her eyes.\n3.1 s: she smiles at the lens."
    write_prompt(env, tmp_path, c["id"], three)
    w = clips.lock(env, c["id"])["warnings"]
    assert len(w) == 1 and "3 timed beats" in w[0]
    long = filled(c["body"]["prompt"]).replace("Locked camera", "Locked camera, " + "very " * 40 + "slowly")
    write_prompt(env, tmp_path, c["id"], long)
    w = clips.lock(env, c["id"])["warnings"]
    assert len(w) == 1 and "words besides the quoted lyric" in w[0] and "timed beats" not in w[0].split(".")[0]


def test_motion_clips_never_get_the_sung_warning(env, tmp_path):
    c = clips.new(env, "s004", "motion")["clip"]
    write_prompt(env, tmp_path, c["id"], filled(c["body"]["prompt"], "she walks toward the lens, " + "slowly " * 60))
    lk = clips.lock(env, c["id"])
    assert lk["clip"]["status"] == "locked" and lk["warnings"] == []


# ------------------------------------------------------------------------------------------------ covers sing: short
def _cover(env, root: str, start: str, cid: str = "W01-c1", t0: float = 11.04) -> dict:
    prop = {"id": cid, "parent": root, "song_t0": t0, "duration": 4, "needed": [11.1, 12.6],
            "why": f"cover for {root}: it diverges from our audio at song 11.2; this window starts in the word gap at {t0}"}
    clips.make_cover(env, root, prop, start=str(env / start))
    return store.load(env, cid)


def test_cover_of_a_screenplay_parent_is_drafted_short(env, tmp_path):
    rc, out = run(env, "clip", "new", "s002", "--kind", "sung", "--style", "screenplay")
    write_prompt(env, tmp_path, "W01", filled(out["clip"]["body"]["prompt"], "she sings it softly"))
    cv = _cover(env, "W01", "plates/cands/hero-cu/2.png")
    p = cv["body"]["prompt"]
    assert p.startswith(HEAD + f'"{cv["words"]}".') and p.endswith(SUNG_CLOSER) and tpl.timed_beats(p) == 0
    assert cv["draft_notes"]["style"] == "short" and cv["draft_notes"]["scaffold"] == p
    assert "short sung form" in cv["draft_notes"]["prompt_source"]


def test_cover_of_a_short_parent_keeps_its_lines_and_drops_its_beats(env, tmp_path):
    c = clips.new(env, "s002", "sung")["clip"]
    lines = filled(c["body"]["prompt"]).split("\n")
    parent = "\n".join([lines[0], lines[1], "1.3 s (downbeat): she tilts her head back on the long note.", lines[2]])
    write_prompt(env, tmp_path, "W01", parent)
    cv = _cover(env, "W01", "plates/cands/hero-cu/2.png")
    p = cv["body"]["prompt"]
    assert p == "\n".join([HEAD + f'"{cv["words"]}".', lines[1], lines[2]])       # framing/light kept, beat dropped
    assert "scaffold" not in cv["draft_notes"] and "timed-beat lines dropped" in cv["draft_notes"]["prompt_source"]
    assert not tpl.slots(p) and clips.lock_problems(env, cv) == []                 # ready to lock as it is


def test_cover_of_a_short_parent_without_beats_is_requoted(env, tmp_path):
    c = clips.new(env, "s002", "sung")["clip"]
    write_prompt(env, tmp_path, "W01", filled(c["body"]["prompt"]))
    cv = _cover(env, "W01", "plates/cands/hero-cu/2.png")
    assert cv["body"]["prompt"].split("\n")[1:] == filled(c["body"]["prompt"]).split("\n")[1:]
    assert cv["draft_notes"]["prompt_source"] == "the parent prompt with this window's exact words re-quoted"


def test_cover_make_lock_reports_the_warning(env, tmp_path):
    c = clips.new(env, "s002", "sung")["clip"]
    long_parent = filled(c["body"]["prompt"]).replace("Locked camera", "Locked camera, " + "very " * 50 + "slowly")
    write_prompt(env, tmp_path, "W01", long_parent)                                 # long, but untimed: re-quoted as is
    prop = {"id": "W01-c1", "parent": "W01", "song_t0": 11.04, "duration": 4, "needed": [11.1, 12.6], "why": "cover"}
    m = clips.make_cover(env, "W01", prop, start=str(env / "plates/cands/hero-cu/2.png"), lock_it=True)
    assert m["locked"] and any("words besides the quoted lyric" in w for w in m["warnings"])


# ------------------------------------------------------------------------------------------------ the docs say it
def test_docs_state_the_rule_and_the_measurements():
    f60 = " ".join((DOCS / "60-clips.md").read_text(encoding="utf-8").split())
    f61 = " ".join((DOCS / "61-lipsync.md").read_text(encoding="utf-8").split())
    f99 = " ".join((DOCS / "99-failures.md").read_text(encoding="utf-8").split())
    ex = " ".join((DOCS / "examples" / "seedance-prompts.md").read_text(encoding="utf-8").split())
    assert "### 4.0 The short sung form" in (DOCS / "60-clips.md").read_text(encoding="utf-8")
    assert "### 1.1 Short prompts copy" in (DOCS / "61-lipsync.md").read_text(encoding="utf-8")
    for f in (f60, f61):
        for needle in ("0 %", "78 %", "28 %", "100 %", "One continuous shot, no cuts, no head turns.", "Only she sings",
                       "at most 2 timed beats", "try the short form first"):
            assert needle in f, needle
    assert "screenplay for acting and motion, short for copy" in f60 and "screenplay for acting and motion, short for copy" in f61
    for f in (f60, f61):
        assert "2 OpenRouter non-copies" in f and "Higgsfield" in f and "cut away" in f
    assert "c01" in f99 and "78 %" in f99 and "short sung form" in f99
    assert "short sung form" in ex and "78 %" in ex
    # the shipped short template block is what clip new drafts (slots aside)
    assert ("@Image1 sings @Audio1. She lip-syncs to @Audio1 exactly, every word in time: \"<every word in the window>\". "
            "<Framing> of the woman from @Image1 (<canon tags>), <how she sings the words>. <Light>. <Camera>. "
            "[<a.aa s (the sound)>: <one small action>.] [<b.bb s (the sound)>: <one small action>.] " + SUNG_CLOSER) in f60


# ------------------------------------------------------------------------------------------------ review fixes
def test_counting_edge_cases():
    assert tpl.timed_beats("1.2 s–2.4 s: she turns") == 1                 # a range with the unit on both ends
    assert tpl.timed_beats("at 3s she smiles; 0–3s she turns") == 2       # glued whole seconds are times
    assert tpl.timed_beats("the 80s and 90s, 1980s wallpaper, 2020s neon") == 0   # decades are not
    assert tpl.timed_beats("an 8-second hold, v2.5 shots, 35mm, 4K") == 0


def test_they_agrees_in_every_drafted_line():
    lead = tpl.lead_words({"lead": {"pronoun": "they", "noun": "the singer"}})
    short = tpl.sung_prompt(words="Go", phrases=[], t0=0, duration=4, shot={}, lead=lead, kicks=[], downbeats=[])
    long = tpl.sung_prompt(words="Go", phrases=[{"t0": 1.0, "t1": 1.5, "text": "Go"}], t0=0, duration=4, shot={},
                           lead=lead, kicks=[1.0], downbeats=[], style="screenplay")
    for p in (short, long):
        assert "They lip-sync to @Audio1" in p and "they sings" not in p and "They lip-syncs" not in p
        assert tpl.quoted_words(p) == "Go"                                   # the head is still found
    assert "Only they sing." in short and "how they sing the words" in short
    assert "Only they sing;" in long and "as they sing this" in long and "what they want." in long
    she = tpl.sung_prompt(words="Go", phrases=[], t0=0, duration=4, shot={}, lead=tpl.lead_words({}), kicks=[], downbeats=[])
    assert she.startswith(HEAD) and she.endswith(SUNG_CLOSER)                 # the default wording is untouched


def _hint(text: str) -> list[str]:
    cmd = re.search(r"in the short form: (slop .*?--force)", text).group(1)
    return shlex.split(re.sub(r"^slop (?:-p \S+ )?", "", cmd))


def test_short_rebuild_hint_keeps_window_plate_provider_and_quote(env):
    rc, out = run(env, "clip", "new", "s002", "--kind", "sung", "--style", "screenplay", "--id", "c01", "--t0", "10.0",
                  "--t1", "12.6", "--song-t0", "9.3", "--duration", "5", "--provider", "higgsfield", "--res", "1080p",
                  "--words", "Sit up, darling")
    assert rc == 0, out
    before = store.load(env, "c01")
    argv = _hint(out["text"])
    assert argv[:7] == ["clip", "new", "s002", "--kind", "sung", "--style", "short"] and argv[-1] == "--force"
    for flag in ("--song-t0", "--duration", "--t0", "--t1", "--start", "--provider", "--res", "--words"):
        assert flag in argv, flag
    rc, again = run(env, *argv)                                           # the bot runs it exactly as printed
    assert rc == 0, again
    after = store.load(env, "c01")
    for k in ("song_t0", "needed", "provider", "model", "start", "words", "her_words", "window"):
        assert after.get(k) == before.get(k), k
    assert after["body"]["resolution"] == "1080p" and after["body"]["duration"] == 5
    assert after["draft_notes"]["style"] == "short" and after["body"]["prompt"].endswith(SUNG_CLOSER)


def test_rebuild_cmd_quotes_survive_a_shell():
    import shutil
    import subprocess
    if not shutil.which("bash"):
        pytest.skip("needs bash (the bot's shell)")
    words = 'Cash out $100, `now`, "baby" \\ go'
    cmd = clips.rebuild_cmd("s 01", "c01", "short", need=[10.0, 12.6], song_t0=9.3, duration=5,
                            start="plates/my plates/1.png", provider="higgsfield", words=words)
    assert cmd.startswith("slop ")
    out = subprocess.run(["bash", "-c", "printf '%s\\0' " + cmd[len("slop "):]], capture_output=True, check=True).stdout
    argv = out.decode("utf-8").split("\0")[:-1]                            # exactly what bash hands the program
    assert argv[argv.index("--words") + 1] == words and argv[2] == "s 01"
    assert argv[argv.index("--start") + 1] == "plates/my plates/1.png" and argv[argv.index("--song-t0") + 1] == "9.3"
    assert "--model" not in argv and "--res" not in argv and argv[-1] == "--force"


def test_short_rebuild_hint_on_a_default_clip_is_minimal_but_exact(env):
    r = clips.new(env, "s002", "sung", style="screenplay")
    argv = _hint(r["text"])
    assert "--provider" not in argv and "--words" not in argv and "--res" not in argv
    rc, out = run(env, *argv)
    assert rc == 0, out
    c = store.load(env, "W01")
    assert c["song_t0"] == r["clip"]["song_t0"] and c["start"] == r["clip"]["start"] and c["window"] == r["clip"]["window"]


def test_dry_run_repeats_the_long_prompt_warning(env, tmp_path):
    rc, out = run(env, "clip", "new", "s002", "--kind", "sung", "--style", "screenplay")
    write_prompt(env, tmp_path, "W01", filled(out["clip"]["body"]["prompt"], "she sings it softly"))
    run(env, "gen", "host", "W01", "--url", "https://cdn.example.com/W01.wav")
    rc, dr = run(env, "clip", "submit", "W01", "--dry-run")
    assert rc == 0 and any("timed beats" in w and "Lock and submit still go ahead" in w for w in dr["prompt_warnings"])
    assert "Lock and submit still go ahead" in dr["text"]
    assert not dr["warnings"]                                    # the request warnings (hosting, budget) stay apart
    run(env, "clip", "lock", "W01")
    rc, dr = run(env, "clip", "submit", "W01", "--dry-run")
    assert any("Locked anyway" in w for w in dr["prompt_warnings"]) and "clip submit W01 --yes" in dr["text"]   # not refused
    c = clips.new(env, "s003", "sung", cid="W02")["clip"]                 # the short form: no warning
    clips.set_fields(env, "W02", prompt=filled(c["body"]["prompt"]))
    run(env, "gen", "host", "W02", "--url", "https://cdn.example.com/W02.wav")
    rc, dr = run(env, "clip", "submit", "W02", "--dry-run")
    assert dr["prompt_warnings"] == [] and "timed beats" not in dr["text"]


def make_take(env, c: dict, diverge_at: float, out: Path) -> Path:
    """a take whose audio copies the clip's window until `diverge_at` (clip time), then sings something else."""
    from slop.sync.avsync import load
    ref = load(env / c["window"]["wav"], 44100)
    other = H.babble(len(ref) / 44100, seed=7)
    k = int(diverge_at * 44100)
    take = np.r_[ref[:k], other[k:len(ref)]] if diverge_at < len(ref) / 44100 else ref
    H.write_wav(out.with_suffix(".wav"), take)
    return H.make_mp4(out, out.with_suffix(".wav"))


def _synced(env, tmp_path, style: str, diverge_at: float) -> dict:
    rc, out = run(env, "clip", "new", "s002", "--kind", "sung", "--style", style)
    write_prompt(env, tmp_path, "W01", filled(out["clip"]["body"]["prompt"], "she sings it softly, eyes on the lens"))
    run(env, "clip", "lock", "W01")
    take = make_take(env, store.load(env, "W01"), diverge_at, tmp_path / "t.mp4")
    rc, out = run(env, "clip", "ingest", "W01", "--file", str(take), "--provider", "openrouter")
    assert rc == 0, out
    rc, out = run(env, "clip", "sync", "W01", "--no-png")
    assert rc == 0, out
    return out


def test_sync_says_short_first_after_a_long_prompt_mostly_out_of_sync(env, tmp_path):
    out = _synced(env, tmp_path, "screenplay", 1.0)
    assert out["share"] < .5 and out["short_first"]
    first = out["text"].split("\n  first: ", 1)[1]
    assert "words besides the quoted lyric" in first and "timed beats" in first and "same provider" in first
    assert "0 %" in first and "78 %" in first and "docs/60-clips.md §4.0" in first
    assert first.index("Before a cover or another provider") < first.index("clip set W01 --prompt-file FILE")
    # following it works on a clip that already has a take: rewrite short, re-lock, dry run (nothing refused)
    words = tpl.quoted_words(store.load(env, "W01")["body"]["prompt"])
    short = "\n".join([HEAD + f'"{words}".', "Close-up of the woman from @Image1 (black bob, one orange streak, star clip, "
                       "headset mic), facing the lens, singing with her eyes closed. Warm light from the side. Locked camera.",
                       SUNG_CLOSER])
    write_prompt(env, tmp_path, "W01", short)
    lk = clips.lock(env, "W01")
    assert lk["clip"]["status"] == "locked" and lk["warnings"] == []
    run(env, "gen", "host", "W01", "--url", "https://cdn.example.com/W01.wav")
    rc, dr = run(env, "clip", "submit", "W01", "--dry-run")
    assert rc == 0 and not dr["lock_problems"] and "clip submit W01 --yes" in dr["text"]


def test_sync_says_nothing_new_for_a_short_prompt(env, tmp_path):
    out = _synced(env, tmp_path, "short", 1.0)                          # short already: covers / routing as before
    assert out["share"] < .5 and out["short_first"] is None and "first:" not in out["text"]


def test_sync_long_prompt_that_held_gets_no_advice(env, tmp_path):
    out = _synced(env, tmp_path, "screenplay", 99.0)                    # copied the whole window
    assert out["share"] >= .5 and out["short_first"] is None and "first:" not in out["text"]
    assert clips.short_first({"kind": "motion", "id": "M1", "body": {"prompt": W02_LONG}}, 0.0, False) is None

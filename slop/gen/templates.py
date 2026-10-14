"""Seedance prompt templates — the verbatim heads and grammars from the shipped videos, the short sung form and a
screenplay scaffold.

Heads (verbatim):
  sung       @Image1 sings @Audio1. She lip-syncs to @Audio1 exactly, every word in time: "<exact window words>".
  motion     Moving in time with @Audio1.                          (first-frame clips: the plate IS frame 0)
             The scene from @Image1, moving in time with @Audio1.   (reference clips)
  closer     One continuous shot, no cuts. No text, letters or logos.                                  (screenplay)
             One continuous shot, no cuts, no head turns. Only she sings. No text, letters or logos.   (short sung)
Rules carried with them: quote EXACTLY the words that start in the window (a take that quoted fewer words diverged inside
the missing ones); one dominant camera move; say who voices and keep every other mouth closed; no style/grade words
(the plate carries the look). Which grammar (DEFAULT_STYLE):
  short       THE DEFAULT FOR SUNG (lip-sync) CLIPS AND THEIR COVERS: SHORT_RULE, "the head quoting every word, one
              line of framing and light, at most 2 timed beats", then SHORT_CLOSER. SHORT_TEMPLATE, the block shipped
              verbatim in docs/60-clips.md §4.0 and §5 (and in the prompt-book brief; skills/clips quotes SHORT_RULE and
              SHORT_CLOSER; tests/test_studio_integration.py keeps them identical):
                @Image1 sings @Audio1. She lip-syncs to @Audio1 exactly, every word in time: "<every word in the window>".
                <Framing> of the woman from @Image1 (<canon tags>), <how she sings the words>. <Light>. <Camera>.
                [<a.aa s (the sound)>: <one small action>.]
                [<b.bb s (the sound)>: <one small action>.]
                One continuous shot, no cuts, no head turns. Only she sings. No text, letters or logos.
              sung_prompt(style="short") drafts exactly those lines with [[slots]] (the beat lines left to the writer).
              Measured: with long screenplay prompts Seedance re-sang the line instead of copying @Audio1 (sung seconds in
              sync: studio-run c01 0 % -> 78 %, SP W02 28 % -> 100 % with the short form). `slop clip lock` warns (never
              refuses) when a sung prompt has more than ~SHORT_MAX_WORDS words besides the quoted lyric or more than
              SHORT_MAX_BEATS timed beats (sung_length_warning).
              Motion, short (EV): PREFIX + "<Framing>. The woman from @Image1 <one clear action with an end state>.
              <Camera move>. No cuts. Her mouth stays closed, face expressionless."
  screenplay  THE DEFAULT FOR MOTION CLIPS (and for a sung shot played as an acting moment, --style screenplay): HEAD,
              place + light + blocking at 0.0 s, the story beat in one sentence, timestamped lines "a.aa–b.bb s
              ("<words>"): <action>; <reaction>" on the real word / kick / downbeat times (seconds from the clip's first
              frame — @Audio1 starts on frame 0), the environment answering the music, the camera tied to the hits,
              mouth rules, closer.
The scaffold fills every time from the analysis and leaves [[slots]] for the writing; `slop clip lock` refuses a prompt
that still has a [[slot]]. Generic changes: "She"/"the woman" come from project.json lead.pronoun / lead.noun when set
(defaults keep the verbatim wording; the verbs agree: "They lip-sync", "Only they sing").
"""
from __future__ import annotations

import re

HEAD = '@Image1 sings @Audio1. She lip-syncs to @Audio1 exactly, every word in time: "{words}"'
MOTION_FIRST = "Moving in time with @Audio1. "
MOTION_REF = "The scene from @Image1, moving in time with @Audio1. "
CLOSER = "One continuous shot, no cuts. No text, letters or logos."
SUNG_CLOSER = "One continuous shot, no cuts, no head turns."
NO_TEXT = "No text, letters or logos."
SHORT_CLOSER = f"{SUNG_CLOSER} Only she sings. {NO_TEXT}"           # "she" follows lead.pronoun in a draft
SHORT_LINE = "<Framing> of the woman from @Image1 (<canon tags>), <how she sings the words>. <Light>. <Camera>."
SHORT_RULE = "the head quoting every word, one line of framing and light, at most 2 timed beats"
SHORT_TEMPLATE = "\n".join([HEAD.format(words="<every word in the window>") + ".", SHORT_LINE,
                            "[<a.aa s (the sound)>: <one small action>.]", "[<b.bb s (the sound)>: <one small action>.]",
                            SHORT_CLOSER])
STYLES = ("short", "screenplay")
DEFAULT_STYLE = {"sung": "short", "motion": "screenplay"}
SHORT_MAX_WORDS = 90                 # words besides the quoted lyric (SP W02's 100 % prompt: 86 words in all)
SHORT_MAX_BEATS = 2
# a timed beat: "2.16 s", "0.3–0.74 s", "1.2 s–2.4 s", "at 1.2 seconds"; a list "(0.3, 0.77, 1.24 s)" counts one beat per
# time; a range is one beat whether or not its start carries the unit
_NUM, _UNIT = r"\d+(?:\.\d+)?", r"(?:s|secs?|seconds?)"
TIME_RE = re.compile(rf"(?<![\w.@])({_NUM}(?:(?:\s*{_UNIT})?\s*[–-]\s*{_NUM}|\s*(?:,|&|\band\b)\s*{_NUM})*)\s*{_UNIT}\b")
SLOT_RE = re.compile(r"\[\[[^\]]*\]\]")
QUOTE_RE = re.compile(r'(?:every word in time|whispering one word in time): "([^"]*)"')
FRAMING = {"ECU": "Extreme close-up", "CU": "Close-up", "MCU": "Medium close-up", "MS": "Medium shot",
           "MWS": "Medium wide shot", "WS": "Wide shot", "FS": "Full-length shot", "EWS": "Extreme wide shot",
           "OTS": "Over-the-shoulder shot"}


def default_style(kind: str) -> str:
    """short for sung (lip-sync) clips — the measured copy winner; the screenplay for motion clips."""
    return DEFAULT_STYLE.get(kind, "screenplay")


def lead_words(project: dict) -> dict:
    lead = project.get("lead") or {}
    pron = (lead.get("pronoun") or "She").strip().capitalize()
    poss = {"She": "Her", "He": "His", "They": "Their", "It": "Its"}.get(pron, "Their")
    return {"noun": (lead.get("noun") or {"She": "the woman", "He": "the man", "They": "the singer", "It": "the subject"}.get(pron, "the singer")).strip(), "pronoun": pron, "possessive": poss,
            "sings": _verb(pron, "sings"), "canon": (lead.get("canon") or "").strip(),
            "far": (lead.get("far") or "").strip()}


def _verb(pronoun: str, verb: str) -> str:
    """the verb agreeing with the pronoun: "they sing", "they lip-sync"; she/he/it keep the -s."""
    return verb[:-1] if pronoun.strip().lower() == "they" and verb.endswith("s") else verb


def head(words: str, pronoun: str = "She") -> str:
    h = HEAD.format(words=words)
    return h if pronoun == "She" else h.replace(" She lip-syncs", f" {pronoun} {_verb(pronoun, 'lip-syncs')}")


def sing_prompt(prompt: str, words: str, pronoun: str = "She") -> str:
    """the prompt with the exact window words quoted in the singing head (head added when missing)."""
    if "@Audio1" in prompt and QUOTE_RE.search(prompt):
        return QUOTE_RE.sub(lambda m: m.group(0).split(":", 1)[0] + f': "{words}"', prompt, count=1)
    return head(words, pronoun) + ". " + prompt.strip()


def quoted_words(prompt: str) -> str | None:
    m = QUOTE_RE.search(prompt or "")
    return m.group(1) if m else None


def norm_words(s: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9' ]+", " ", (s or "").lower()).split())


def slots(prompt: str) -> list[str]:
    return SLOT_RE.findall(prompt or "")


def _lyric_free(prompt: str) -> str:
    """the prompt with the quoted lyric taken out of the head (the head's own words stay)."""
    return QUOTE_RE.sub(lambda m: m.group(0).split(":", 1)[0] + ":", prompt or "")


def _times(text: str) -> list[int]:
    """beats per time expression in text (a list of n times counts n). "1980s" and "the 90s" are decades, not times: a
    glued "s" after a whole number ending in 0 (two digits or more) is skipped ("3s", "2.16s" and "4 s" count)."""
    out = []
    for m in TIME_RE.finditer(text or ""):
        last = re.findall(_NUM, m.group(1))[-1]
        glued = not m.group(0)[len(m.group(1)):][:1].isspace()
        if glued and re.fullmatch(r"\d+0", last) and m.group(0).endswith("s") and not re.search(r"[–-]", m.group(1)):
            continue
        out.append(len(re.split(r"\s*(?:,|&|\band\b)\s*", m.group(1))))
    return out


def timed_beats(prompt: str) -> int:
    """timed beats outside the quoted lyric: a time or a range is one beat, a list of times one beat per time."""
    return sum(_times(_lyric_free(prompt)))


def prompt_stats(prompt: str) -> dict:
    """{words: words besides the quoted lyric, beats: timed beats}: the short sung form's two limits."""
    return {"words": len([t for t in _lyric_free(prompt).split() if re.search(r"\w", t)]), "beats": timed_beats(prompt)}


def is_short(prompt: str) -> bool:
    st = prompt_stats(prompt)
    return st["words"] <= SHORT_MAX_WORDS and st["beats"] <= SHORT_MAX_BEATS


def sung_length_warning(prompt: str) -> str | None:
    """why a sung prompt is past the short form's limits (None when it is short). A warning: lock never refuses on it."""
    st = prompt_stats(prompt)
    over = ([f"{st['words']} words besides the quoted lyric (short form: about {SHORT_MAX_WORDS} or fewer)"]
            if st["words"] > SHORT_MAX_WORDS else []) + \
           ([f"{st['beats']} timed beats (short form: at most {SHORT_MAX_BEATS})"] if st["beats"] > SHORT_MAX_BEATS else [])
    if not over:
        return None
    return ("this sung prompt has " + " and ".join(over) + ". With long screenplay prompts Seedance mostly re-sang the "
            "line instead of copying @Audio1; the short sung form raised the measured share of sung seconds in sync from "
            f"0 % to 78 % (studio run, c01) and from 28 % to 100 % (SP W02): {SHORT_RULE}, then \"{SHORT_CLOSER}\" "
            "(docs/60-clips.md §4.0). Keep a long form only for an acting moment with a cut-away ready")


def without_timed_lines(prompt: str) -> str | None:
    """a short prompt with its timed-beat lines dropped (their times belonged to another window), the head line kept;
    None when a time sits inside a line that stays (a one-paragraph prompt): redraft instead."""
    lines = (prompt or "").split("\n")
    keep = [ln for i, ln in enumerate(lines) if i == 0 or not _times(_lyric_free(ln))]
    if not "\n".join(keep[1:]).strip() or any(_times(_lyric_free(ln)) for ln in keep):
        return None
    return "\n".join(keep)


def framing_name(code: str | None) -> str:
    if not code:
        return "[[framing: close-up / medium shot / full-length shot …]]"
    return FRAMING.get(str(code).upper(), str(code))


def _r(x: float) -> str:
    return f"{x:.2f}".rstrip("0").rstrip(".") if abs(x - round(x)) > 1e-9 else f"{x:.1f}"


def sung_prompt(*, words: str, phrases: list[dict], t0: float, duration: float, shot: dict, lead: dict,
                kicks: list[float], downbeats: list[float], style: str = "short") -> str:
    """phrases are song-time {t0, t1, text}; kicks/downbeats song-time. Times in the prompt are clip-relative.
    "short" (the sung default, SHORT_TEMPLATE): the head, one line of framing and light and the sung closer; timed beats
    are left to the writer (at most 2, from draft_notes). "screenplay": the timestamped scaffold, for a sung shot played as an acting moment."""
    pron, noun, poss = lead["pronoun"], lead["noun"], lead["possessive"]
    sings = lead.get("sings") or _verb(pron, "sings")
    fr = framing_name(shot.get("framing"))
    canon = f" ({lead['canon']})" if lead.get("canon") and len(lead["canon"]) <= 160 else ""
    action = (shot.get("action") or "").strip().rstrip(".")
    camera = (shot.get("camera") or "").strip().rstrip(".")
    h = head(words, pron) + "."
    if style == "short":
        act = action or (f"[[how {pron.lower()} {sings} the words, {poss.lower()} mouth fully visible: facing the lens, "
                         "eyes closed, deadpan, full voice …]]")
        cam = camera or "Locked camera"
        return "\n".join([h, f"{fr} of {noun} from @Image1{canon}, {act}. [[Light, e.g. Warm light from the side]]. {cam}.",
                          f"{SUNG_CLOSER} Only {pron.lower()} {sings}. {NO_TEXT}"])
    lines = [h,
             f"[[Place + light + blocking at 0.0 s: where we are, the light, who is where and wearing what]] {fr} of {noun} "
             f"from @Image1{canon}." + (f" ({action}.)" if action else ""),
             "[[The story beat in one sentence: what this moment means and what " + pron.lower() + " "
             + _verb(pron, "wants") + ".]]"]
    rel = [(max(0.0, p["t0"] - t0), min(duration, p["t1"] - t0), p["text"]) for p in phrases]
    cur = 0.0
    if rel and rel[0][0] > .15:
        lines.append(f"0.0–{_r(rel[0][0])} s: [[before the first word: a breath, a look, a small move]]")
    for a, b, txt in rel:
        lines.append(f"{_r(a)}–{_r(b)} s (\"{txt}\"): [[{poss.lower()} action as {pron.lower()} {sings} this; anyone else's reaction]]")
        cur = b
    if duration - cur > .2:
        lines.append(f"{_r(cur)}–{_r(duration)} s: [[after the last word: hold, react, end state]]")
    hits = []
    if kicks:
        hits.append("kicks at " + ", ".join(_r(k - t0) for k in kicks) + " s")
    if downbeats:
        hits.append("downbeats at " + ", ".join(_r(d - t0) for d in downbeats) + " s")
    if hits:
        lines.append(f"({'; '.join(hits)}: [[what the environment does on them — spray, light, wind]])")
    cam = f"Camera: {camera}." if camera else "Camera: [[one move tied to a hit, e.g. a very slow push in until the drop, then still]]."
    lines.append(f"{cam} Only {pron.lower()} {sings}; anyone else keeps their mouth closed. {CLOSER}")
    return "\n".join(lines)


def motion_prompt(*, t0: float, duration: float, shot: dict, lead: dict, kicks: list[float], downbeats: list[float],
                  frame: str = "ref", style: str = "screenplay") -> str:
    prefix = MOTION_FIRST if frame == "first" else MOTION_REF
    noun, poss = lead["noun"], lead["possessive"]
    fr = framing_name(shot.get("framing"))
    action = (shot.get("action") or "").strip().rstrip(".")
    camera = (shot.get("camera") or "").strip().rstrip(".")
    lead_on = shot.get("lead_on_screen", True)
    if style == "short":
        who = f" {noun[0].upper() + noun[1:]} from @Image1 " + (action or "[[one clear action with an end state]]") + "." if lead_on else \
            " " + (action[0].upper() + action[1:] if action else "[[one clear action with an end state]]") + "."
        tail = f" No cuts. {poss} mouth stays closed, face expressionless." if lead_on else " No cuts. No text, letters or logos."
        return f"{prefix}{fr}.{who} {(camera or '[[Camera move]]')}.{tail}"
    lines = [prefix + f"[[Place + light + blocking at 0.0 s: where we are, the light, who is where and wearing what]] {fr}."
             + (f" ({action}.)" if action else ""),
             "[[The story beat in one sentence: what this moment means.]]"]
    marks: list[float] = []
    for m in sorted([round(k - t0, 2) for k in kicks] + [round(d - t0, 2) for d in downbeats]):
        if not marks or m - marks[-1] > .05:                     # a kick and a downbeat 10-20 ms apart are one hit
            marks.append(m)
    if marks:
        lines.append(f"0.0–{_r(duration)} s: [[the main action, with a clear end state]]")
        lines.append("On the hits (" + ", ".join(_r(m) for m in marks if 0 <= m < duration) +
                     " s): [[what lands on them — a step, a turn, spray, a light]]")
    else:
        lines.append(f"0.0–{_r(duration)} s: [[the main action, with a clear end state]]")
    cam = f"Camera: {camera}." if camera else "Camera: [[one move tied to a hit]]."
    lines.append(f"{cam} Nobody's lips form words. {CLOSER}")
    return "\n".join(lines)

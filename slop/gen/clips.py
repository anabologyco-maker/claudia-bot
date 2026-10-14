"""Clip lifecycle: new -> (set) -> lock -> submit -> poll / ingest -> sync -> coverage -> covers.

A clip file (clips/<id>.json, ARCHITECTURE §4.6) is the unit of spend and sync. Port of the production seedance.py /
orv.py / prompts.py flow, made generic and gated for a weaker operator:
  * window rules: a sung window starts in a word gap before the shot (gap_start(shot t0, lead .3)), lasts
    int(min(8, max(4, ceil(needed_end − t0 + .3)))) s and quotes exactly the words that start in it; a motion window starts
    on the shot (no pre-roll), 4–12 s. @Audio1 = the clean vocal window (sung, default: only the quoted words, from the
    audio module), the raw vocal stem window (`--window vocal`) or the mix window (motion), mono 44.1 kHz (MP3 192 kbps
    for Higgsfield, WAV for OpenRouter).
  * THE QUOTE IS THE SOURCE OF TRUTH (prompts.py `apply`): a prompt that quotes words ("every word in time: "…"") keeps
    them; they are checked against the window's aligned words with the her_words matcher (in order, other voices and
    the next line may be skipped) and the clean window is (re)cut to hold exactly those words — the second video's
    "her words only" windows. `--words "…"` does the same without a new prompt. Only `--requote` (or a prompt without a
    quote) puts every word of the window in the quote. A window move (--song-t0 / --duration / --recut) keeps a
    restricted quote and re-cuts for it. A raw vocal / mix window holds every word, so its quote must be all of them.
    `lock` refuses a quote that differs from what the window audio holds (audio/windows/<clip>.json, written by the
    audio module), a window file cut for other times, and screenplay lines ("a–b s ("…"):") that quote words outside
    the head quote. A prompt that is still the untouched scaffold (draft_notes.scaffold) is redrafted when the words or
    the window change; a written screenplay is never rewritten — a window move flags it and lock waits for a new one.
  * sung clips use REFERENCE MODE (the plate as @Image1 reference + @Audio1) — verified: a first frame makes OpenRouter
    ignore the audio — and on OpenRouter a model that takes an audio reference (Seedance 2+): another model could not
    lip-sync, so new/set/lock/submit refuse it. Motion clips default to reference mode on OpenRouter ("The scene from
    @Image1, moving in time with @Audio1."); --frame first pins the exact composition (no audio conditioning on
    OpenRouter: the take is warned and the prompt says "the music"). On Higgsfield motion clips default to --frame first
    (start_image + audio_references: both count there).
  * two clips never start from the same frame: a plate already used as a start makes the next clip take the plate's next
    unused candidate (plates/cands/<plate>/*), else it is an error that names `slop clip frame` (a frame of an earlier
    take, by default its last in-sync frame — the production plan's "continue the previous clip").
  * spending requires status "locked" AND --yes (or the project gate prompts_approved), and the budget check passes
    BEFORE anything is sent. A provider face-filter decline is final for that reference (status "declined"); the same
    UNALTERED image may go to the other provider. A submit that gets no clear answer (5xx / dropped connection) records
    an "unknown" take, counts the estimate as spent and keeps the clip "submitted": nothing re-sends it until the job is
    attached (`slop clip poll CLIP --job-id ID`) or abandoned (`slop clip submit CLIP --yes --resubmit-unknown`).
  * `slop clip submit CLIP --dry-run` prints the exact request (mode, every reference by role, frame_images, prompt)
    and its estimate; nothing is sent, hosted, saved or spent (works on drafts too, listing their lock problems). It
    runs the submit's own preflight (preflight(): lock problems, a sung clip without @Audio1, resolution limits) and the
    budget check (dollars, or credits for Higgsfield), and prints the --yes command only when none of them fails.
  * output-audio refusals ("sensitive information", "copyright"; unbilled) are counted per clip (clip.refusals) and
    answered with ONE next step (ARCHITECTURE §7b): the first is retried once (sensitive: reworded prompt; copyright:
    as is), the second on the same provider goes to the other provider with the same unaltered image and window. This
    runs on OpenRouter (submit and poll) and on Higgsfield (`slop clip ingest CLIP --failed "REASON"`); the provider's
    generic advice is left out of those lines so the operator reads exactly one instruction.
  * clean windows that quote only some words pass those aligned tokens to the audio module (make_window tokens=, when
    it takes them), so a repeated word can never be matched to an earlier repeat.
  * after delivery: `slop clip sync` measures the take (slop.sync.avsync) and stores take.sync; `slop clip coverage`
    reports the sung seconds held in sync; `slop clip cover CLIP --make` writes covers for the gaps (frame at the cut as
    the start/reference image; a her-words chain keeps her words). No lip-sync-model fallback: what stays uncovered is
    cut away in the edit.
  * hosting: while the quick tunnel runs, `submit` puts the window (OpenRouter @Audio1) or the start image, references
    and window (Higgsfield: the request lists them for media_import_url) on it by itself (auto_host); without a tunnel
    the error / request says to start it first (media_upload with the signed `If-None-Match: *` header is the fallback).
  * `submit --finalize-from TAKE` (Higgsfield): a kept 480p draft -> a 1080p finalize request (draft_job_id, get_cost
    first, ~12 credits/s) as a new take; a sung clip's finalized take carries needs_sync until `clip sync` measures it.
    A finalize recorded failed / declined / rejected (`ingest --failed`/`--declined`) counts 0 and puts the clip back to
    delivered on its draft (no re-lock advice: that would buy a new draft; the start image is not declined by it).
  * `ingest --failed`/`--declined` takes the take's estimate off the log on either provider (credits or $; failed and
    refused jobs are not charged): ledger.record turns it into a settlement of that take.
  * every hint line and error of the public functions names the project (`slop -p NAME clip …`, hints.project_hints).
Intentional changes: no pre-grade of start images/frames (inputs stay in colour; never alter a reference to pass a filter);
SUNG CLIPS DRAFT THE SHORT FORM (templates.DEFAULT_STYLE; measured on a live Studio run: long timestamped screenplays
made Seedance re-sing the line instead of copying @Audio1 — c01 0 % -> 78 % of its sung seconds in sync, SP W02
28 % -> 100 % with the short form), motion clips the screenplay; `--style screenplay` keeps the long form for a sung shot
played as an acting moment (its `new` text gives the short rebuild with the same window, plate and provider, rebuild_cmd).
`lock` and `submit --dry-run` WARN (never refuse) when a sung prompt runs past ~90 words besides the quoted lyric or 2
timed beats (templates.sung_length_warning); `sync` adds a "first:" line (short_first) when such a clip's take held under
half its sung seconds: rewrite it short and retake on the same provider before covers or re-routing (docs/61 §8). Covers
sing, so a cover of a screenplay parent is re-scaffolded in the
short form (its timestamps would be wrong anyway) and a short parent's timed-beat lines are dropped, the rest kept; a
window move under a screenplay prompt is flagged and lock waits for a rewritten prompt; a clean window's start is moved
back to the next word's t0 − .06 when the gap midpoint would mute that word (SongData.clean_start); `submit --res` applies
to that take only (the clip and its future covers keep their resolution); `ingest --file` is idempotent (file sha1).
"""
from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
from pathlib import Path

from .. import ledger
from ..config import SlopError, load_project
from ..sync.songdata import CLEAN_LO, SongData, norm_compact
from . import higgsfield as hf
from . import hedra
from . import hosting
from . import models as reg
from . import store
from . import templates as tpl
from . import video as vid
from .hints import project_hints
from .openrouter import OpenRouter, ProviderError, classify, data_url

SUNG_DUR = (4, 8)
MOTION_DUR = (4, 12)
RESOLUTIONS = ("480p", "720p", "1080p")
TS_RE = re.compile(r"\d+(?:\.\d+)?\s*[–-]\s*\d+(?:\.\d+)?\s*s\b")
LINE_QUOTE_RE = re.compile(r'\d+(?:\.\d+)?\s*[–-]\s*\d+(?:\.\d+)?\s*s\s*\("([^"]*)"\)')   # a screenplay line's sung words
FPS = 24


def _unquoted(prompt: str) -> str:
    return tpl.QUOTE_RE.sub("", prompt or "").strip()


def untouched_scaffold(c: dict) -> bool:
    """the prompt is still the drafted scaffold (only its head quote may differ): safe to rebuild."""
    sc = (c.get("draft_notes") or {}).get("scaffold")
    return bool(sc) and _unquoted((c.get("body") or {}).get("prompt") or "") == _unquoted(sc)


# ------------------------------------------------------------------------------------------------ project data
def proj(pdir: Path) -> dict:
    return load_project(pdir)


def shots_doc(pdir: Path) -> dict:
    p = pdir / "board" / "shots.json"
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise SlopError(f"board/shots.json is not valid JSON ({e})") from e


def find_shot(pdir: Path, shot_id: str) -> dict | None:
    for s in shots_doc(pdir).get("shots", []):
        if s.get("id") == shot_id:
            return s
    return None


def aspect(project: dict) -> str:
    w, h = (project.get("size") or [1920, 1080])[:2]
    r = w / h if h else 16 / 9
    return "16:9" if r > 1.2 else ("9:16" if r < .83 else "1:1")


def default_model(project: dict) -> str:
    from . import models as M
    return M.resolve(project, "video", vid.DEFAULT_MODEL, "video")


def sung_default_model(project: dict) -> tuple[str, str | None]:
    """the project's video model when it takes an audio reference, else Seedance 2.5 (with a note)."""
    m = default_model(project)
    if vid.media_refs_ok(m):
        return m, None
    from . import models as M
    best = M.latest(vid.DEFAULT_MODEL, "video")
    return best, (f"project models.video {m} takes no audio reference, so it cannot lip-sync: this sung clip uses "
                  f"{best} (cheaper drafts: the newest seedance mini, see slop gen models --kind video)")


def model_problem(c: dict) -> str | None:
    """sung clips on OpenRouter need a model that takes the song window as @Audio1 (Seedance 2+)."""
    if c.get("kind") != "sung" or (c.get("provider") or "openrouter") != "openrouter":
        return None
    m = c.get("model") or ""
    if vid.media_refs_ok(m):
        return None
    return (f"sung clips need a model that takes an audio reference (bytedance/seedance-2.x); {m or 'this model'} does "
            f"not, so its take could not lip-sync: slop clip set {c['id']} --model bytedance/seedance-2.5 (or "
            "bytedance/seedance-2.0-mini for cheap drafts), or make it a motion clip")


def gate_ok(project: dict, clip: dict | None = None) -> bool:
    """The owner's standing yes for a clip submit: gates.prompts_approved AND (for a clip) a recorded approval that
    covers this clip prompt as it is now (core_cli.clip_prompt_approved) - a clip locked or rewritten after the
    approval needs the owner again (integration fix: the flag alone used to cover any locked clip)."""
    if not (project.get("gates") or {}).get("prompts_approved"):
        return False
    if clip is None:
        return True
    try:
        from slop.core_cli import clip_prompt_approved
    except ImportError:          # core missing: the flag alone
        return True
    return clip_prompt_approved(project, clip)


def ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise SlopError("ffmpeg is not installed or not on PATH (run bin/setup.sh)")
    return exe


def probe_duration(path: Path) -> float | None:
    exe = shutil.which("ffprobe")
    if not exe:
        return None
    r = subprocess.run([exe, "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return None


def inflight_msg(c: dict) -> str:
    cid = c["id"]
    unk = store.unknown_take(c)
    if unk and unk.get("provider") == "hedra":
        return (f"{cid} take {unk['n']}: Hedra outcome unknown, still reserved. Find the job in Hedra, then "
                f"slop clip poll {cid} --job-id JOB_ID; do not submit again.")
    if unk:
        return (f"{cid} take {unk['n']}: the submit got no clear answer, so it may be running and is counted as spent. Look "
                "for it at https://openrouter.ai/activity: found -> slop clip poll " + cid + " --job-id JOB_ID; nothing there "
                f"after ~10 min -> slop clip submit {cid} --yes --resubmit-unknown")
    return f"{cid} has a take in flight: run slop clip poll {cid} (or slop clip ingest for Higgsfield) before changing it"


RETRY_ONCE = ("sensitive", "copyright")      # output-audio refusals (unbilled): retry once, then the other provider


def note_refusal(c: dict, status: str, provider: str, take: int | None = None) -> str:
    """record an output-audio refusal on the clip and return the ONE next step (ARCHITECTURE §7b): the first refusal is
    retried once with a changed request; the second on the same provider goes to the other provider with the same
    unaltered image and window."""
    cid = c["id"]
    c.setdefault("refusals", []).append({"provider": provider, "status": status, "at": store.now(),
                                         **({"take": take} if take else {})})
    n = sum(1 for r in c["refusals"] if r.get("provider") == provider and r.get("status") in RETRY_ONCE)
    other = "higgsfield" if provider == "openrouter" else "openrouter"
    what = ("the output audio may contain sensitive information" if status == "sensitive" else
            "the output audio may be related to copyright restrictions")
    if n <= 1:
        if status == "copyright":
            return (f"NEXT ({provider} refused once: {what}; failed jobs are not billed): retry once as it is - it often "
                    f"passes: slop clip submit {cid} --yes")
        return (f"NEXT ({provider} refused once: {what}; failed jobs are not billed): retry once with a changed request. "
                f"Reword the prompt - keep every timestamp and the quoted words exactly, change how the scene and the "
                f"singing are described - save it to a file, then: slop clip set {cid} --prompt-file FILE && slop clip "
                f"lock {cid} && slop clip submit {cid} --yes")
    tail = (" (a motion clip may instead drop the generated audio: slop clip set " + cid + " --no-audio)"
            if c.get("kind") == "motion" and status == "copyright" else "")
    return (f"NEXT ({provider} refused {n} times: {what}): do not retry there again. Send the same unaltered image and "
            f"window to {other}: slop clip set {cid} --provider {other} && slop clip lock {cid} && slop clip submit "
            f"{cid} --yes" + tail)


# ------------------------------------------------------------------------------------------------ starts + windows
def plate_candidates(pdir: Path, plate: str | None) -> list[Path]:
    if not plate:
        return []
    out: list[Path] = []
    picks = pdir / "plates" / "picks.json"
    if picks.is_file():
        try:
            pk = json.loads(picks.read_text(encoding="utf-8")).get(plate) or {}
            if pk.get("file"):
                out.append(store.absp(pdir, pk["file"]))
        except json.JSONDecodeError:
            pass
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        p = pdir / "plates" / f"{plate}{ext}"
        if p.is_file():
            out.append(p)
    cd = pdir / "plates" / "cands" / plate
    if cd.is_dir():
        out += sorted([p for p in cd.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")],
                      key=lambda p: (len(p.stem), p.stem))
    seen, uniq = set(), []
    for p in out:
        if p and p.is_file() and p.resolve() not in seen:
            seen.add(p.resolve()); uniq.append(p)
    return uniq


FRAME_HINT = ("continue from a frame of an earlier take: slop clip frame EARLIER_CLIP [--at SONG_T] (default: its last "
              "in-sync frame), then pass that file with --start")


def choose_start(pdir: Path, cid: str, plate: str | None, explicit: str | None) -> tuple[Path, str, str]:
    """(path, pixel sha1, note): the first candidate no other clip starts from."""
    used = store.used_starts(pdir, exclude=cid)
    if explicit:
        p = Path(explicit)
        p = p if p.is_absolute() else (Path.cwd() / p if (Path.cwd() / p).is_file() else pdir / p)
        if not p.is_file():
            raise SlopError(f"start image not found: {explicit}")
        h = store.image_sha1(p)
        if h in used:
            raise SlopError(f"{p.name} is already the start of clip {used[h]}: two clips never start from the same frame. "
                            f"Use another candidate of the plate (plates/cands/<plate>/), or {FRAME_HINT}.")
        return p, h, "explicit"
    cands = plate_candidates(pdir, plate)
    if not cands:
        if not plate:
            raise SlopError("this shot has no plate yet: pass --start IMAGE (or give the shot a plate on the board)")
        raise SlopError(f"no image for plate {plate!r} (plates/picks.json, plates/{plate}.jpg or plates/cands/{plate}/): "
                        "ingest/pick it first (slop plates …) or pass --start IMAGE")
    for k, p in enumerate(cands):
        h = store.image_sha1(p)
        if h not in used:
            return p, h, ("the pick" if k == 0 else f"candidate {k + 1}: earlier candidates already start other clips")
    raise SlopError(f"every candidate of plate {plate!r} already starts another clip (two clips never start from the same "
                    f"frame). Generate/pick another candidate (slop gen image --plate {plate} …), or {FRAME_HINT}.")


WORD_LO = {"clean": CLEAN_LO}                  # a clean window keeps the words starting in [t0 + .05, t1 - .08)


def word_lo(window: dict | None) -> float:
    return WORD_LO.get((window or {}).get("mode") or "", -.02)


def window_meta(pdir: Path, cid: str) -> dict | None:
    """audio/windows/<clip>.json — the audio module's description of the window files (mode, t0, t1, words kept)."""
    p = pdir / "audio" / "windows" / f"{cid}.json"
    try:
        d = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None
    except (OSError, json.JSONDecodeError):
        return None
    return d if isinstance(d, dict) else None


def _meta_matches(meta: dict, c: dict) -> bool:
    try:
        t0 = float(c["song_t0"]); t1 = t0 + float(c["body"]["duration"])
        return abs(float(meta.get("t0")) - t0) <= .011 and abs(float(meta.get("t1")) - t1) <= .011
    except (TypeError, ValueError, KeyError):
        return False


def _meta_words(song: SongData, meta: dict) -> str:
    if meta.get("quoted"):
        return str(meta["quoted"])
    return song.text_for([[w.get("t0"), w.get("t1"), w.get("w", "")] for w in meta.get("words") or []]) or \
        str(meta.get("sung") or "")


def kept_words(pdir: Path, c: dict, song: SongData | None = None) -> str | None:
    """the words a clean window's audio holds (audio/windows/<clip>.json, when it describes this clip's window)."""
    meta = window_meta(pdir, c["id"])
    if not meta or meta.get("mode") != "clean" or not _meta_matches(meta, c):
        return None
    return _meta_words(song or SongData(pdir), meta)


def all_words(song: SongData, c: dict, window: dict | None = None) -> str:
    t0 = float(c["song_t0"])
    return song.words_in(t0, t0 + float(c["body"]["duration"]), word_lo(window if window is not None else c.get("window")))


def is_restricted(song: SongData, c: dict) -> bool:
    """the clip quotes only some of its window's words (a her-words window)."""
    return (c.get("kind") == "sung" and bool(c.get("words")) and song.has_words
            and norm_compact(c["words"]) != norm_compact(all_words(song, c)))


def window_src(pdir: Path, c: dict) -> Path | None:
    win = c.get("window") or {}
    return store.absp(pdir, win.get("wav") or win.get("file"))


def check_quote(song: SongData, quote: str, t0: float, dur: float, mode: str, cid: str) -> list[dict]:
    """the her_words tokens for a quote, or a SlopError that says what to do."""
    if mode != "clean":
        allw = song.words_in(t0, t0 + dur, -.02)
        if norm_compact(allw) != norm_compact(quote):
            raise SlopError(f'a {mode} window holds every word sung in {t0:.2f}–{t0 + dur:.2f} s ("{allw}"), but the quote is '
                            f'"{quote}": quote them all (slop clip set {cid} --requote), or use a clean window that holds only '
                            f'your words (slop clip set {cid} --audio-mode clean --words "{quote}")')
        return song.words_starting_in(t0, t0 + dur, -.02)
    hw, ok = song.her_words(quote, t0, t0 + dur)
    if not ok:
        allw = song.words_in(t0, t0 + dur, CLEAN_LO)
        raise SlopError(f'the quoted words "{quote}" are not all sung, in this order, by words starting inside the window '
                        f'{t0:.2f}–{t0 + dur:.2f} s (its words: "{allw}"; matched: "{song.join(hw)}"). Quote words from the '
                        f'window exactly (slop clip set {cid} --words "…"), quote all of them (--requote), or move the '
                        "window (--song-t0 / --duration).")
    return hw


def _token_kwargs(make_window, tokens: list | None) -> dict:
    """{"tokens": [[t0, t1, w], ...]} when the audio module's make_window takes explicit tokens (the exact aligned words
    to keep, so a quote is never matched to an earlier repeat of the same words); {} on an older audio module."""
    if not tokens:
        return {}
    import inspect
    try:
        params = inspect.signature(make_window).parameters
    except (TypeError, ValueError):
        return {}
    return {"tokens": [list(t) for t in tokens]} if "tokens" in params else {}


def cut_window(pdir: Path, cid: str, t0: float, dur: float, kind: str, mode: str | None = None,
               quoted: str | None = None, tokens: list | None = None) -> tuple[dict, list[str]]:
    """the clip's @Audio1: clean vocal (sung, default; only `quoted` when given) / raw vocal stem ("vocal") / mix (motion).
    clean and mix come from the audio module (slop.audio.window.make_window) when it is installed. `tokens` (the
    her_words [[t0, t1, w], ...] of the quote) go to make_window when it accepts them."""
    warn: list[str] = []
    mode = mode or ("clean" if kind == "sung" else "mix")
    if mode in ("clean", "mix"):
        try:
            from ..audio.window import make_window
        except ImportError:
            make_window = None
        if make_window is not None:
            try:
                info = make_window(pdir, cid, round(t0, 3), round(t0 + dur, 3), mode=mode,
                                   quoted=quoted if mode == "clean" else None,
                                   **(_token_kwargs(make_window, tokens) if mode == "clean" and quoted else {}))
                return {"t0": round(t0, 3), "t1": round(t0 + dur, 3), "mode": mode, "file": info.get("file"),
                        "wav": info.get("wav"), "url": None, "source": "cut", "quoted": quoted if mode == "clean" else None}, \
                    list(info.get("warnings") or [])
            except SlopError as e:
                if "ends past the song" in str(e):   # never fall back to a raw cut: it would send a silent @Audio1
                    raise SlopError(f"{e}\n(move the clip with `slop clip set {cid} --song-t0 S` or shorten it with "
                                    "--duration, so the window ends inside the song)") from e
                if mode == "clean" and quoted:
                    raise SlopError(f"{e}\n(the clip quotes only \"{quoted}\": --requote quotes every word of the window, "
                                    "--words \"…\" picks words sung inside it)") from e
                if mode == "clean":
                    warn.append(f"no clean vocal window ({e}); using the raw vocal stem window instead")
                    mode = "vocal"
                else:
                    warn.append(f"audio module window failed ({e}); cutting the mix directly")
        elif mode == "clean":
            if quoted:
                raise SlopError("a window that holds only the quoted words needs the audio module (slop.audio.window): "
                                "reinstall the toolkit (bin/setup.sh), or --requote to quote every word")
            mode = "vocal"
    return _raw_window(pdir, cid, t0, dur, kind, mode, warn)


def _raw_window(pdir: Path, cid: str, t0: float, dur: float, kind: str, mode: str, warn: list[str]) -> tuple[dict, list[str]]:
    stem = pdir / "audio" / "stems" / "vocals.wav"
    mix = pdir / "audio" / "song.wav"
    if kind == "sung" and mode != "mix" and stem.is_file():
        src, mode = stem, "vocal"
    elif mix.is_file():
        src, mode = mix, "mix"
        if kind == "sung":
            warn.append("no vocal stem (audio/stems/vocals.wav): the sung window uses the full mix — run slop analyze "
                        "(stems) and re-cut with slop clip set CLIP --recut")
    else:
        warn.append("no song audio yet (audio/song.wav): the window audio is missing — run slop song ingest, then "
                    "slop clip set CLIP --recut")
        return {"t0": round(t0, 3), "t1": round(t0 + dur, 3), "mode": "vocal" if kind == "sung" else "mix",
                "file": None, "wav": None, "url": None, "source": "cut"}, warn
    wd = pdir / "audio" / "windows"; wd.mkdir(parents=True, exist_ok=True)
    mp3, wav = wd / f"{cid}.mp3", wd / f"{cid}.wav"
    for out, codec in ((mp3, ["-b:a", "192k"]), (wav, ["-c:a", "pcm_s16le"])):
        r = subprocess.run([ffmpeg(), "-v", "error", "-y", "-ss", f"{t0:.3f}", "-t", f"{dur:.3f}", "-i", str(src),
                            "-ac", "1", "-ar", "44100", *codec, str(out)], capture_output=True)
        if r.returncode:
            raise SlopError(f"ffmpeg could not cut the window: {r.stderr.decode(errors='replace')[-300:]}")
    (wd / f"{cid}.json").unlink(missing_ok=True)                      # it described the files just replaced
    return {"t0": round(t0, 3), "t1": round(t0 + dur, 3), "mode": mode, "file": store.rel(pdir, mp3),
            "wav": store.rel(pdir, wav), "url": None, "source": "cut"}, warn


def _attach_audio(pdir: Path, c: dict, audio: str, audio_mode: str | None, warns: list[str]) -> dict | None:
    """use FILE as the window audio. Returns the audio module's window description when FILE is this clip's own window
    (audio/windows/<clip>.mp3|wav from `slop audio window`), else None (a foreign file: its words cannot be checked)."""
    cid = c["id"]
    a = Path(audio)
    if not a.is_file():
        raise SlopError(f"audio file not found: {audio}")
    wd = pdir / "audio" / "windows"; wd.mkdir(parents=True, exist_ok=True)
    mp3, wav = wd / f"{cid}.mp3", wd / f"{cid}.wav"
    own = a.resolve() in (mp3.resolve(), wav.resolve())
    meta = window_meta(pdir, cid) if own else None
    if not (own and mp3.is_file() and wav.is_file()):                 # own files from `slop audio window` are used as is
        for out, codec in ((mp3, ["-b:a", "192k"]), (wav, ["-c:a", "pcm_s16le"])):
            if a.resolve() != out.resolve():
                r = subprocess.run([ffmpeg(), "-v", "error", "-y", "-i", str(a), "-ac", "1", "-ar", "44100", *codec, str(out)],
                                   capture_output=True)
                if r.returncode:
                    raise SlopError(f"ffmpeg could not read {a.name}: {r.stderr.decode(errors='replace')[-200:]}")
    if not own:
        (wd / f"{cid}.json").unlink(missing_ok=True)                  # it described the files just replaced
    mode = (meta or {}).get("mode") or audio_mode or ("clean" if c["kind"] == "sung" else "mix")
    if meta and audio_mode and audio_mode != meta.get("mode"):
        warns.append(f"audio/windows/{cid}.json says this is a {meta.get('mode')} window: using that, not --audio-mode "
                     f"{audio_mode}")
    c["window"] = {**(c.get("window") or {}), "file": store.rel(pdir, mp3), "wav": store.rel(pdir, wav), "url": None,
                   "mode": mode, "t0": c["song_t0"], "t1": round(float(c["song_t0"]) + float(c["body"]["duration"]), 3),
                   "source": "cut" if meta else "attached", "quoted": (meta or {}).get("quoted")}
    if not meta and c["kind"] == "sung":
        warns.append(f"{a.name} is not a window written by slop (no audio/windows/{cid}.json): slop cannot check which words "
                     f"it holds — it must hold exactly the quoted words. `slop audio window {cid} --t0 T0 --t1 T1 --mode clean "
                     "--words \"…\"` writes a checked one")
    return meta


def next_id(pdir: Path, kind: str, shot: str | None) -> str:
    if kind == "motion" and shot:
        cid = f"M-{shot}"; k = 2
        while store.exists(pdir, cid):
            cid = f"M-{shot}-{chr(ord('a') + k - 2)}"; k += 1
        return cid
    n = 1
    while store.exists(pdir, f"W{n:02d}"):
        n += 1
    return f"W{n:02d}"


def draft_prompt(pdir: Path, project: dict, song: SongData, *, kind: str, t0: float, dur: float, words: str,
                 shot: dict, frame: str, style: str, lo: float = -.02, keep: list | None = None) -> str:
    lead = tpl.lead_words(project)
    kicks, dbs = song.kicks(t0, t0 + dur), song.downbeats_in(t0, t0 + dur)
    if kind == "sung":
        return tpl.sung_prompt(words=words, phrases=song.phrases(t0, t0 + dur, lo=lo, keep=keep), t0=t0, duration=dur,
                               shot=shot, lead=lead, kicks=kicks, downbeats=dbs, style=style)
    return tpl.motion_prompt(t0=t0, duration=dur, shot=shot, lead=lead, kicks=kicks, downbeats=dbs, frame=frame, style=style)


def higgsfield_tail_warning(song: SongData, t0: float, dur: float) -> str | None:
    """Higgsfield takes start with a pre-roll of up to ~+0.8 s, so the last ~0.8 s of the window may never appear."""
    ws = song.words_starting_in(t0, t0 + dur)
    if ws and ws[-1]["t1"] > t0 + dur - .8 and dur < SUNG_DUR[1]:
        return ("the last word ends less than 0.8 s before the window end: Higgsfield takes start up to ~0.8 s late, so it "
                f"may be cut off — make the window one second longer (slop clip set CLIP --duration {int(dur) + 1})")
    return None


def _hw_list(tokens: list[dict]) -> list[list]:
    return [[round(float(w["t0"]), 3), round(float(w["t1"]), 3), w.get("w") or w.get("text") or ""] for w in tokens]


# ------------------------------------------------------------------------------------------------ new / set / lock
@project_hints
def new(pdir: Path, shot_id: str, kind: str, *, cid: str | None = None, t0: float | None = None, t1: float | None = None,
        song_t0: float | None = None, duration: int | None = None, start: str | None = None, frame: str | None = None,
        style: str | None = None, provider: str | None = None, model: str | None = None, resolution: str | None = None,
        force: bool = False, window_mode: str | None = None, words: str | None = None) -> dict:
    if kind not in ("sung", "motion"):
        raise SlopError("--kind must be sung or motion")
    style = style or tpl.default_style(kind)                  # sung: the short form (it copies @Audio1); motion: screenplay
    if style not in tpl.STYLES:
        raise SlopError("--style must be short or screenplay")
    if words is not None and kind != "sung":
        raise SlopError("--words is for sung clips (the words the lead sings in the window)")
    project = proj(pdir)
    song = SongData(pdir)
    shot = find_shot(pdir, shot_id) or {}
    if not shot and (t0 is None or t1 is None):
        raise SlopError(f"shot {shot_id!r} is not in board/shots.json: pass --t0 and --t1 (the song span the edit needs) "
                        "or create the storyboard first (slop board …)")
    for c in store.all_clips(pdir):                                   # idempotent: one clip per shot + kind
        if c.get("shot") == shot_id and c.get("kind") == kind and not c.get("parent") and not force and (cid in (None, c["id"])):
            return {"clip": c, "created": False, "warnings": [],
                    "text": f"{c['id']} already exists for {shot_id} ({kind}, {c['status']}); use slop clip set to change "
                            "it, or --force (draft only) to rebuild it"}
    need = [float(t0 if t0 is not None else shot["t0"]), float(t1 if t1 is not None else shot["t1"])]
    if need[1] <= need[0]:
        raise SlopError(f"empty needed span {need}")
    prov = provider or "openrouter"
    warns: list[str] = []
    q_tokens: list | None = None
    if model:
        mdl = model
        if kind == "sung" and prov == "openrouter" and not vid.media_refs_ok(model):
            raise SlopError(f"sung clips need a model that takes an audio reference (bytedance/seedance-2.x); {model} does "
                            "not, so its take could not lip-sync: --model bytedance/seedance-2.5 (or "
                            "bytedance/seedance-2.0-mini for cheap drafts), or make it a motion clip (--kind motion)")
    elif prov == "hedra":
        mdl = hedra.MODEL
    elif kind == "sung":
        mdl, note = sung_default_model(project)
        if note and prov == "openrouter":
            warns.append(note)
    else:
        mdl = default_model(project)
    cid = cid or next_id(pdir, kind, shot_id)
    if store.exists(pdir, cid):
        old = store.load(pdir, cid)
        if not force:
            raise SlopError(f"clip {cid} exists; pick another --id, or --force to rebuild it (only while it is a draft)")
        if old.get("status") != "draft" or old.get("takes"):
            raise SlopError(f"{cid} is {old.get('status')} with {len(old.get('takes') or [])} take(s): never rebuilt; make a "
                            "new clip with another --id")
    if kind == "sung":
        if not song.has_words:
            raise SlopError("no aligned words (analysis/words.json): run slop analyze first — sung windows quote the exact "
                            "aligned words")
        mode = window_mode or "clean"
        wt0 = float(song_t0) if song_t0 is not None else song.gap_start(need[0], lead=.3)
        if song_t0 is None and mode == "clean":
            wt0 = song.clean_start(wt0)
        dur = int(duration) if duration else int(min(SUNG_DUR[1], max(SUNG_DUR[0], math.ceil(need[1] - wt0 + .3 - 1e-9))))
        if not SUNG_DUR[0] <= dur <= SUNG_DUR[1]:
            raise SlopError("sung windows are 4–8 s (never more than 8 s sung): plan a chain of windows")
        if not song.words_in(wt0, wt0 + dur):
            raise SlopError(f"no sung words start in {wt0:.2f}–{wt0 + dur:.2f} s: this is a motion clip (--kind motion)")
        if need[1] > wt0 + dur - .08:
            nxt = song.gap_start(wt0 + dur - .3, lead=.1)
            warns.append(f"the needed span ends at {need[1]:.2f} s, after this window ({wt0:.2f}–{wt0 + dur:.2f} s): plan a "
                         f"second window from the word gap at {nxt:.2f} s (slop clip new {shot_id} --kind sung --t0 "
                         f"{wt0 + dur - .3:.2f} --t1 {need[1]:.2f} --id {cid}b)")
        if prov == "higgsfield":
            tail = higgsfield_tail_warning(song, wt0, dur)
            if tail:
                warns.append(tail.replace("CLIP", cid))
        if words is not None:
            words = words.strip()
            q_tokens = _hw_list(check_quote(song, words, wt0, dur, mode, cid))
    else:
        wt0 = float(song_t0) if song_t0 is not None else need[0]
        dur = int(duration) if duration else int(min(MOTION_DUR[1], max(MOTION_DUR[0], math.ceil(need[1] - need[0] - 1e-9))))
        if not MOTION_DUR[0] <= dur <= MOTION_DUR[1]:
            raise SlopError("motion clips are 4–12 s")
    if frame is None:                         # Higgsfield: start_image + audio both count (OpenRouter drops the audio)
        frame = "first" if (kind == "motion" and prov == "higgsfield") else "ref"
    if kind == "sung" and frame == "first":
        raise SlopError("sung clips use reference mode (the plate as @Image1 reference): with a first frame OpenRouter "
                        "ignores the audio window (verified). Drop --frame first.")
    sp, sha, note = choose_start(pdir, cid, shot.get("plate"), start)
    if note.startswith("candidate"):
        warns.append(f"start image: {note}")
    window, w2 = cut_window(pdir, cid, wt0, dur, kind, window_mode, quoted=words or None,
                            tokens=q_tokens if words else None); warns += w2
    lo = word_lo(window)
    keep: list | None = None
    if kind == "sung":
        allw = song.words_in(wt0, wt0 + dur, lo)
        if not allw:
            raise SlopError(f"no sung words start in {wt0:.2f}–{wt0 + dur:.2f} s: this is a motion clip (--kind motion)")
        if words and norm_compact(words) != norm_compact(allw):
            keep = _hw_list(check_quote(song, words, wt0, dur, window.get("mode") or "clean", cid))
        else:
            words = allw
    else:
        words = ""
    prompt = draft_prompt(pdir, project, song, kind=kind, t0=wt0, dur=dur, words=words, shot=shot, frame=frame, style=style,
                          lo=lo, keep=keep)
    ks = {round(k[0], 3) for k in keep} if keep else None
    clip = {"id": cid, "shot": shot_id, "kind": kind, "status": "draft", "provider": prov,
            "model": mdl, "frame": frame, "start": store.rel(pdir, sp), "start_sha1": sha,
            "refs": [], "videos": [], "song_t0": round(wt0, 3), "needed": [round(need[0], 3), round(need[1], 3)],
            "words": words, "window": window,
            "body": {"prompt": prompt, "duration": dur, "resolution": resolution or "720p", "aspect_ratio": aspect(project),
                     "generate_audio": True},
            "takes": [], "covers": [], "why": (shot.get("notes") or shot.get("action") or f"storyboard shot {shot_id}"),
            "created": store.now(), "hosted": {}, "declined": [], "history": [],
            "draft_notes": {"style": style, "shot": {k: shot.get(k) for k in ("framing", "action", "camera", "lines", "set",
                                                                              "lead_on_screen", "plate") if k in shot},
                            "window_words": [[round(w["t0"] - wt0, 2), round(w["t1"] - wt0, 2), w["text"]]
                                             for w in song.words_starting_in(wt0, wt0 + dur, lo)
                                             if ks is None or round(w["t0"], 3) in ks],
                            "kicks": [round(k - wt0, 2) for k in song.kicks(wt0, wt0 + dur)],
                            "downbeats": [round(b - wt0, 2) for b in song.downbeats_in(wt0, wt0 + dur)],
                            "lead_canon": tpl.lead_words(project)["canon"], "scaffold": prompt}}
    if keep:
        clip["her_words"] = keep
    store.save(pdir, clip)
    n_slots = len(tpl.slots(prompt))
    txt = (f"{cid}: {kind} clip for {shot_id}, window {wt0:.2f}–{wt0 + dur:.2f} s ({dur} s)"
           + (f', words "{words}"' if words else "") + (" (her words only)" if keep else "") + f", start {Path(sp).name}. "
           + (f"The prompt has {n_slots} [[slot(s)]] to write: edit it (slop clip set {cid} --prompt-file FILE), then "
              f"slop clip lock {cid}." if n_slots else f"Review the prompt, then slop clip lock {cid}."))
    if kind == "motion" and prov == "openrouter" and frame == "ref":
        txt += " (Reference mode keeps the song as @Audio1; --frame first pins the plate's exact composition but sends no audio on OpenRouter.)"
    if kind == "sung" and style == "short":
        txt += (" Short sung form (it copies @Audio1 far more often than a long screenplay): keep it to "
                f"{tpl.SHORT_RULE} (times in draft_notes); the story goes in the book.")
    elif kind == "sung":
        redo = rebuild_cmd(shot_id, cid, "short", need=need, song_t0=wt0, duration=dur, start=store.rel(pdir, sp),
                           provider=prov, model=model, resolution=resolution, window_mode=window_mode,
                           words=words if keep else None)
        txt += (" (A screenplay on a sung clip is for an acting moment with a cut-away ready: long prompts copy @Audio1 "
                f"far less often, and lock will warn. The same window, plate and provider in the short form: {redo})")
    return {"clip": clip, "created": True, "warnings": warns, "text": txt + "".join("\n  ! " + w for w in warns)}


def _arg(s, *, quote: bool = False) -> str:
    """a command-line value: bare when it is safe (unless quote), else double-quoted the way every hint quotes --words,
    with \\ " $ ` escaped so a shell passes a lyric through unchanged."""
    s = str(s)
    if not quote and re.fullmatch(r"[\w./:@+=-]+", s):
        return s
    return '"' + re.sub(r'([\\"$`])', r"\\\1", s) + '"'


def _t(x: float) -> str:
    return f"{float(x):.3f}".rstrip("0").rstrip(".")


def rebuild_cmd(shot_id: str, cid: str, style: str, *, need: list, song_t0: float, duration: int, start: str,
                provider: str = "openrouter", model: str | None = None, resolution: str | None = None,
                window_mode: str | None = None, words: str | None = None) -> str:
    """`slop clip new … --force` that redrafts a sung draft in another style with the SAME needed span, window, plate,
    provider, model, resolution and quote: a bare `--id CLIP --force` would recompute the window from the shot (a board
    clip spanning several shots, or one placed with --song-t0, would move) and fall back to OpenRouter 720p."""
    parts = [f"slop clip new {_arg(shot_id)} --kind sung --style {style} --id {_arg(cid)}",
             f"--t0 {_t(need[0])} --t1 {_t(need[1])} --song-t0 {_t(song_t0)} --duration {int(duration)}",
             f"--start {_arg(start)}"]
    if provider and provider != "openrouter":
        parts.append(f"--provider {provider}")
    if model:
        parts.append(f"--model {_arg(model)}")
    if resolution:
        parts.append(f"--res {resolution}")
    if window_mode:
        parts.append(f"--window {window_mode}")
    if words:
        parts.append(f"--words {_arg(words, quote=True)}")
    return " ".join(parts + ["--force"])


@project_hints
def set_fields(pdir: Path, cid: str, *, prompt: str | None = None, requote: bool = False, words: str | None = None,
               duration: int | None = None, song_t0: float | None = None, resolution: str | None = None,
               model: str | None = None, provider: str | None = None, frame: str | None = None, start: str | None = None,
               refs: list[str] | None = None, clear_refs: bool = False, audio: str | None = None,
               audio_mode: str | None = None, generate_audio: bool | None = None, recut: bool = False,
               why: str | None = None, needed: list[float] | None = None) -> dict:
    c = store.load(pdir, cid)
    if c.get("status") == "submitted":
        raise SlopError(inflight_msg(c))
    project = proj(pdir)
    song = SongData(pdir)
    lead = tpl.lead_words(project)
    sung = c["kind"] == "sung"
    if words is not None and not sung:
        raise SlopError("--words is for sung clips (the words the lead sings in the window)")
    if words is not None and requote:
        raise SlopError('give either --words "…" (quote only these) or --requote (quote every word of the window), not both')
    changed: list[str] = []
    warns: list[str] = []
    old_t0, old_dur = float(c["song_t0"]), int(c["body"]["duration"])
    old_words = c.get("words") or ""
    restricted = sung and is_restricted(song, c)
    scaffold = prompt is None and untouched_scaffold(c)           # nothing written yet: rebuild it when the window moves
    notes = c.setdefault("draft_notes", {})
    if prompt is not None:
        if c.get("takes"):
            c.setdefault("history", []).append({"at": store.now(), "status": c.get("status"), "prompt": c["body"].get("prompt")})
        c["body"]["prompt"] = prompt.strip(); changed.append("prompt")
        notes.pop("window_changed", None)
    if needed:
        c["needed"] = [round(float(needed[0]), 3), round(float(needed[1]), 3)]; changed.append("needed")
    meta_in = None
    if audio:                                                         # the attached window may carry its own times
        a = Path(audio)
        wd = pdir / "audio" / "windows"
        if a.is_file() and a.resolve() in ((wd / f"{cid}.mp3").resolve(), (wd / f"{cid}.wav").resolve()):
            meta_in = window_meta(pdir, cid)
        if meta_in and song_t0 is None and duration is None and not _meta_matches(meta_in, c):
            mt0, mt1 = float(meta_in.get("t0", 0)), float(meta_in.get("t1", 0))
            if abs((mt1 - mt0) - round(mt1 - mt0)) > .011:
                raise SlopError(f"audio/windows/{cid}.json is {mt0:.3f}–{mt1:.3f} s ({mt1 - mt0:.3f} s): clip windows are whole "
                                f"seconds. Re-cut it: slop audio window {cid} --t0 {mt0:.3f} --t1 {mt0 + round(mt1 - mt0):.3f} …")
            song_t0, duration = mt0, int(round(mt1 - mt0))
            warns.append(f"the clip window now follows the attached audio: {mt0:.3f} s + {duration} s")
    # ---- window geometry
    moved = False
    if song_t0 is not None and abs(round(float(song_t0), 3) - old_t0) > 1e-9:
        c["song_t0"] = round(float(song_t0), 3); moved = True
    if duration is not None:
        lo_, hi_ = SUNG_DUR if sung else MOTION_DUR
        if not lo_ <= int(duration) <= hi_:
            raise SlopError(f"{c['kind']} clips are {lo_}–{hi_} s")
        if int(duration) != old_dur:
            c["body"]["duration"] = int(duration); moved = True
    if moved:
        changed.append("window"); recut = recut or not audio
        cur = c["body"].get("prompt") or ""
        if prompt is None and not scaffold and (TS_RE.search(cur) or tpl.timed_beats(cur)):   # a short form's beats too
            notes["window_changed"] = {"from": [old_t0, old_dur], "to": [c["song_t0"], c["body"]["duration"]],
                                       "at": store.now()}
            warns.append(f"the prompt has times (a timestamped screenplay, or timed beats) written for the window "
                         f"{old_t0:.2f} s + {old_dur} s; the "
                         f"window is now {c['song_t0']:.2f} s + {c['body']['duration']} s (every time shifts by "
                         f"{old_t0 - c['song_t0']:+.2f} s; words may have entered or left). Rewrite the lines and pass the "
                         f"new prompt: slop clip set {cid} --prompt-file FILE (lock refuses until then)")
    cur_mode = (c.get("window") or {}).get("mode") or ("clean" if sung else "mix")
    if audio_mode and not audio and audio_mode != cur_mode:
        recut = True
    target_mode = audio_mode or cur_mode
    # ---- simple fields
    if resolution:
        if resolution not in RESOLUTIONS:
            raise SlopError("--res must be 480p, 720p or 1080p")
        c["body"]["resolution"] = resolution; changed.append("resolution")
    if model:
        c["model"] = model; changed.append("model")
    if provider:
        if provider not in ("openrouter", "higgsfield", "hedra"):
            raise SlopError("--provider must be openrouter, higgsfield or hedra")
        previous_provider = c.get("provider")
        c["provider"] = provider; changed.append("provider")
        if provider == "hedra" and previous_provider != "hedra" and not model:
            c["model"] = hedra.MODEL
        elif previous_provider == "hedra" and provider != "hedra" and not model:
            c["model"] = default_model(proj(pdir))
        if provider == "higgsfield" and not sung and c.get("frame") != "first" and not frame:
            warns.append(f"on Higgsfield a motion clip can keep the plate's exact composition AND the audio: slop clip set "
                         f"{cid} --frame first (start_image + audio_references)")
    if (model or provider) and model_problem(c):
        raise SlopError(model_problem(c))
    if frame:
        if frame not in ("ref", "first"):
            raise SlopError("--frame must be ref or first")
        if sung and frame == "first":
            raise SlopError("sung clips use reference mode: with a first frame OpenRouter ignores the audio window (verified)")
        c["frame"] = frame; changed.append("frame")
    if start:
        sp, sha, _ = choose_start(pdir, cid, None, start)
        c["start"], c["start_sha1"] = store.rel(pdir, sp), sha
        c.pop("start_frame", None); c.get("hosted", {}).pop("start", None); changed.append("start")
    if clear_refs:
        c["refs"] = []; changed.append("refs")
    for r in refs or []:
        p = Path(r)
        if not p.is_file():
            raise SlopError(f"reference image not found: {r}")
        c.setdefault("refs", []).append(store.rel(pdir, p)); changed.append("refs")
    if generate_audio is not None:
        c["body"]["generate_audio"] = bool(generate_audio); changed.append("generate_audio")
    if why:
        c["why"] = why
    # ---- the quote (source of truth: --words, else the prompt's own quote, else a kept restriction, else every word)
    explicit = None
    if sung:
        if words is not None:
            explicit = words.strip()
        elif prompt is not None and not requote:
            explicit = tpl.quoted_words(c["body"]["prompt"])
    keep_q = None if requote else (explicit or (c.get("words") if restricted else None))
    touch_words = sung and (words is not None or requote or prompt is not None or moved or recut or bool(audio)
                            or bool(audio_mode))
    # ---- the window audio
    if audio:
        meta = _attach_audio(pdir, c, audio, audio_mode, warns)
        c.get("hosted", {}).pop("audio", None); changed.append("audio")
        if sung and meta and meta.get("mode") == "clean" and _meta_matches(meta, c):
            held = _meta_words(song, meta)
            if explicit and norm_compact(explicit) != norm_compact(held):
                raise SlopError(f'the attached window holds "{held}" but the quote is "{explicit}": quote exactly the words '
                                f'it holds, or re-cut it for your quote (slop clip set {cid} --words "{explicit}" --recut)')
            if not requote and not explicit:
                keep_q = held                                         # the attached window decides the words
        target_mode = c["window"]["mode"]
    if sung and touch_words and target_mode != "clean" and keep_q is not None:
        check_quote(song, keep_q, float(c["song_t0"]), float(c["body"]["duration"]), target_mode, cid)
    if not audio:
        win = c.get("window") or {}
        need_cut = recut or not (store.absp(pdir, win.get("file")) and store.absp(pdir, win.get("file")).is_file())
        if sung and touch_words and target_mode == "clean" and not need_cut and win.get("source") != "attached":
            held = kept_words(pdir, c, song)
            target = keep_q if keep_q is not None else all_words(song, c, {"mode": "clean"})
            need_cut = held is None or norm_compact(held) != norm_compact(target)
        if need_cut and (recut or touch_words):
            toks = None
            if sung and keep_q is not None:
                toks = _hw_list(check_quote(song, keep_q, float(c["song_t0"]), float(c["body"]["duration"]), target_mode,
                                            cid))
            w, ws = cut_window(pdir, cid, float(c["song_t0"]), float(c["body"]["duration"]), c["kind"], target_mode,
                               quoted=keep_q if target_mode == "clean" else None,
                               tokens=toks if target_mode == "clean" else None)
            c["window"] = w; c.get("hosted", {}).pop("audio", None); changed.append("window audio"); warns += ws
    # ---- the words and the prompt's quote
    if touch_words:
        t0, dur = float(c["song_t0"]), float(c["body"]["duration"])
        mode = (c.get("window") or {}).get("mode") or "clean"
        allw = song.words_in(t0, t0 + dur, word_lo(c.get("window")))
        if not allw:
            raise SlopError(f"no sung words start in {t0:.2f}–{t0 + dur:.2f} s: move the window (--song-t0) or make it a "
                            "motion clip")
        if keep_q is None or norm_compact(keep_q) == norm_compact(allw):
            if keep_q is None:
                c["words"] = allw
            else:
                c["words"] = keep_q
            c.pop("her_words", None)
        else:
            hw = check_quote(song, keep_q, t0, dur, mode, cid)
            c["words"] = keep_q
            c["her_words"] = _hw_list(hw)
        q = tpl.quoted_words(c["body"]["prompt"])
        if q != c["words"]:
            c["body"]["prompt"] = tpl.sing_prompt(c["body"]["prompt"], c["words"], lead["pronoun"])
            if q is None or norm_compact(q) != norm_compact(c["words"]):
                changed.append("quoted words")
    if scaffold and (moved or bool(frame) or (sung and (c.get("words") or "") != old_words)):
        t0, dur = float(c["song_t0"]), float(c["body"]["duration"])     # unwritten scaffold: redraft it for the new
        c["body"]["prompt"] = draft_prompt(pdir, project, song, kind=c["kind"], t0=t0, dur=dur,   # words / window
                                           words=c.get("words") or "", shot=find_shot(pdir, c.get("shot") or "") or {},
                                           frame=c.get("frame") or "ref",
                                           style=notes.get("style") or tpl.default_style(c["kind"]),
                                           lo=word_lo(c.get("window")), keep=c.get("her_words"))
        notes["scaffold"] = c["body"]["prompt"]
        notes.pop("window_changed", None)
        changed.append("prompt scaffold")
    was = c.get("status")
    if changed and was in ("locked", "delivered", "failed", "declined"):
        c["status"] = "draft"
    store.save(pdir, c)
    msg = f"{cid}: changed {', '.join(dict.fromkeys(changed)) or 'nothing'}"
    if sung and touch_words:
        msg += f'; quotes "{c["words"]}"' + (" (her words only: the window holds just these)" if c.get("her_words") else "")
    if changed and was != c["status"]:
        msg += f" (was {was}, now draft: re-lock with slop clip lock {cid})"
    return {"clip": c, "changed": list(dict.fromkeys(changed)), "warnings": warns,
            "text": msg + "".join("\n  ! " + w for w in warns)}


def lock_problems(pdir: Path, c: dict) -> list[str]:
    p = []
    cid = c["id"]
    st = store.absp(pdir, c.get("start"))
    if not st or not st.is_file():
        p.append(f"start image missing ({c.get('start')}): slop clip set {cid} --start IMAGE")
    win = c.get("window") or {}
    wf = store.absp(pdir, win.get("file"))
    if c["kind"] == "sung" and (not wf or not wf.is_file()):
        p.append(f"window audio missing: slop clip set {cid} --recut (needs audio/stems/vocals.wav or audio/song.wav)")
    prompt = (c.get("body") or {}).get("prompt") or ""
    sl = tpl.slots(prompt)
    if sl:
        p.append(f"the prompt still has {len(sl)} [[slot(s)]] (e.g. {sl[0][:60]}): write them, then slop clip set "
                 f"{cid} --prompt-file FILE")
    wc = (c.get("draft_notes") or {}).get("window_changed")
    if wc:
        p.append(f"the window moved from {wc['from'][0]:.2f} s + {wc['from'][1]} s to {wc['to'][0]:.2f} s + {wc['to'][1]} s "
                 f"but the screenplay's timestamps were written for the old one: rewrite them (slop clip set {cid} "
                 "--prompt-file FILE)")
    mp = model_problem(c)
    if mp:
        p.append(mp)
    if c["kind"] == "sung":
        q = tpl.quoted_words(prompt)
        stray = [ph for ph in LINE_QUOTE_RE.findall(prompt)
                 if q is not None and norm_compact(ph) and norm_compact(ph) not in norm_compact(q)]
        if stray:
            p.append(f'screenplay line(s) quote words that are not in the sung quote "{q}" (e.g. "{stray[0]}"): the model '
                     f"would be told to sing words @Audio1 does not hold — rewrite those lines (slop clip set {cid} "
                     "--prompt-file FILE)")
        if q is None:
            p.append(f'the sung prompt has no quoted words (every word in time: "…"): slop clip set {cid} --requote')
        elif tpl.norm_words(q) != tpl.norm_words(c.get("words", "")):
            p.append(f'the quoted words ("{q}") are not the clip\'s words ("{c.get("words")}"): slop clip set {cid} '
                     f'--words "{q}" (quote only these) or --requote (every word of the window)')
        elif wf and wf.is_file():
            song = SongData(pdir)
            t0 = float(c.get("song_t0") or 0); t1 = t0 + float((c.get("body") or {}).get("duration") or 0)
            meta = window_meta(pdir, cid)
            mode = win.get("mode") or "clean"
            if meta and not _meta_matches(meta, c):
                p.append(f"the window audio (audio/windows/{cid}.json) was cut for {float(meta.get('t0', 0)):.2f}–"
                         f"{float(meta.get('t1', 0)):.2f} s but the clip's window is {t0:.2f}–{t1:.2f} s: re-cut it "
                         f"(slop clip set {cid} --recut) or attach the right one (slop clip set {cid} --audio FILE)")
            elif mode == "clean" and win.get("source") != "attached":
                held = _meta_words(song, meta) if meta and meta.get("mode") == "clean" else None
                if held is not None and norm_compact(held) != norm_compact(q):
                    p.append(f'the window audio holds "{held}" (audio/windows/{cid}.json) but the prompt quotes "{q}": the '
                             f'model would sing words it cannot hear. Quote exactly those (slop clip set {cid} --words '
                             f'"{held}") or re-cut the window for the quote (slop clip set {cid} --words "{q}" --recut)')
                elif song.has_words and not song.her_words(q, t0, t1)[1]:
                    p.append(f'the quoted words "{q}" are not all sung inside the window {t0:.2f}–{t1:.2f} s: slop clip set '
                             f'{cid} --requote, or --words "…" with words sung inside it')
            elif mode in ("vocal", "mix") and song.has_words:
                allw = song.words_in(t0, t1, -.02)
                if norm_compact(allw) != norm_compact(q):
                    p.append(f'a {mode} window holds every word sung in it ("{allw}") but the prompt quotes "{q}": quote them '
                             f'all (slop clip set {cid} --requote) or cut a clean window for your words (slop clip set {cid} '
                             f'--audio-mode clean --words "{q}")')
    dur = int((c.get("body") or {}).get("duration") or 0)
    lo, hi = SUNG_DUR if c["kind"] == "sung" else MOTION_DUR
    if not lo <= dur <= hi:
        p.append(f"duration {dur} s is outside {lo}–{hi} s")
    if c["kind"] == "sung" and c.get("frame") == "first":
        p.append("sung clips must use reference mode (frame ref)")
    if any(d.get("provider") == c.get("provider") and d.get("start") == c.get("start") and not d.get("prompt_only")
           for d in c.get("declined") or []):
        p.append(f"{c.get('provider')} declined this reference image (final): switch provider (slop clip set {cid} "
                 "--provider higgsfield|openrouter) or use another plate candidate (--start) — never alter the image")
    return p


@project_hints
def lock(pdir: Path, cid: str) -> dict:
    c = store.load(pdir, cid)
    if c.get("status") == "locked":
        return {"clip": c, "text": f"{cid} is already locked (ready to submit)"}
    if c.get("status") == "submitted":
        raise SlopError(inflight_msg(c))
    probs = lock_problems(pdir, c)
    if probs:
        raise SlopError(f"cannot lock {cid}:\n  - " + "\n  - ".join(probs))
    c["status"] = "locked"; c["locked_at"] = store.now()
    store.save(pdir, c)
    warns = lock_warnings(c)
    return {"clip": c, "warnings": warns,
            "text": f"{cid} locked: ready to submit (slop clip submit {cid} --yes) — estimate: {describe_cost(c)}"
                    + "".join("\n  ! " + w for w in warns)}


def lock_warnings(c: dict) -> list[str]:
    """what lock (and the dry run) says but never refuses on: a sung prompt past the short form's limits (~90 words
    besides the quoted lyric, 2 timed beats) — measured to copy @Audio1 far less often (templates.sung_length_warning)."""
    if c.get("kind") != "sung":
        return []
    w = tpl.sung_length_warning((c.get("body") or {}).get("prompt") or "")
    done = "Locked anyway" if c.get("status") == "locked" else "Lock and submit still go ahead"
    return [f"{w}. {done}; to shorten it: slop clip set {c['id']} --prompt-file FILE, then slop clip lock "
            f"{c['id']}"] if w else []


# ------------------------------------------------------------------------------------------------ costs
def clip_cost(c: dict) -> dict:
    b = c.get("body") or {}
    if c.get("provider") == "hedra":
        return {"usd": None}
    if c.get("provider") == "higgsfield":
        cr = hf.credits(int(b.get("duration") or 5), b.get("resolution") or "720p")
        return {"credits": cr, "usd": round(cr * hf.USD_PER_CREDIT, 2)}
    try:
        usd = reg.estimate_video(c.get("model") or reg.latest(vid.DEFAULT_MODEL, "video"), float(b.get("duration") or 5), b.get("resolution") or "720p",
                                 generate_audio=bool(b.get("generate_audio", True)))
    except SlopError:
        usd = None
    return {"usd": usd}


def describe_cost(c: dict) -> str:
    k = clip_cost(c)
    if "credits" in k:
        return f"~{k['credits']:g} Higgsfield credits (~${k['usd']:.2f} at pack price)"
    return f"~${k['usd']:.2f} on OpenRouter" if k.get("usd") is not None else "price unknown"


# ------------------------------------------------------------------------------------------------ hosting
def hosted_files(pdir: Path, c: dict) -> list[tuple[str, Path | None, str]]:
    """(hosted key, local file, media type) of every file a Higgsfield request carries: the start image ("start"),
    the extra references ("ref0".., "video0"..) and the window audio ("audio": the same file OpenRouter is sent)."""
    out: list[tuple[str, Path | None, str]] = [("start", store.absp(pdir, c.get("start")), "image")]
    out += [(f"ref{i}", store.absp(pdir, r), "image") for i, r in enumerate(c.get("refs") or [])]
    out += [(f"video{i}", store.absp(pdir, v), "video") for i, v in enumerate(c.get("videos") or [])]
    win = c.get("window") or {}
    if win.get("file") or win.get("wav"):
        out.append(("audio", window_src(pdir, c), "audio"))
    return out


def host_name(pdir: Path, cid: str, key: str, src: Path) -> str:
    return f"{pdir.name}__{cid}" + ("" if key == "audio" else f"__{key}") + src.suffix


def tunnel_host(pdir: Path, c: dict, key: str, src: Path) -> str:
    """publish one of the clip's files on the RUNNING tunnel and record hosted[key] = {url, sha1} (a media_id recorded
    for an older version of the file is dropped). Returns the public URL."""
    url = hosting.publish(src, host_name(pdir, c["id"], key, src))
    hosted = c.setdefault("hosted", {})
    old = hosted.get(key) or {}
    sha = store.file_sha1(src)
    rec = {"url": url, "sha1": sha}
    if old.get("media_id") and (not old.get("sha1") or old.get("sha1") == sha):
        rec["media_id"] = old["media_id"]
    hosted[key] = rec
    if key == "audio":
        win = c.setdefault("window", {})
        win["url"] = url; win["url_mode"] = "tunnel"
    return url


def auto_host(pdir: Path, c: dict, keys: tuple[str, ...] | None = None) -> list[str]:
    """When the quick tunnel is running: put every file of the clip that has no usable URL (none, a dead tunnel URL,
    or a file that changed since) on the tunnel, so the provider (OpenRouter audio) or the bot (Higgsfield
    media_import_url) can fetch it. Returns notes; does nothing (no notes) when the tunnel is not running."""
    if not hosting.status()["running"]:
        return []
    hosted = c.setdefault("hosted", {})
    done = []
    for key, src, _kind in hosted_files(pdir, c):
        if keys is not None and key not in keys:
            continue
        if not (src and src.is_file()):
            continue
        rec = hosted.get(key) or {}
        url = rec.get("url") or ((c.get("window") or {}).get("url") if key == "audio" else None)
        fresh = bool(url) and not str(url).startswith("data:") and hosting.url_is_live_tunnel(url) and \
            (not rec.get("sha1") or rec.get("sha1") == store.file_sha1(src))
        if fresh:
            continue
        tunnel_host(pdir, c, key, src)
        done.append(key)
    return [f"hosted {', '.join(done)} on the running tunnel"] if done else []


# ------------------------------------------------------------------------------------------------ audio URL
def resolve_audio_url(pdir: Path, c: dict, *, experimental_data: bool = False) -> tuple[str | None, list[str]]:
    notes: list[str] = []
    win = c.get("window") or {}
    hosted = c.setdefault("hosted", {})
    url = win.get("url") or (hosted.get("audio") or {}).get("url")
    src = window_src(pdir, c)
    if not (src and src.is_file()):
        raise SlopError(f"{c['id']} has no window audio file ({win.get('wav') or win.get('file')}): slop clip set {c['id']} "
                        "--recut")
    cur = store.file_sha1(src)
    was = (hosted.get("audio") or {}).get("sha1")
    stale = bool(was and cur and was != cur)
    if url and not url.startswith("data:"):
        if not hosting.url_is_live_tunnel(url) or (stale and "trycloudflare.com" in url):
            if hosting.status()["running"]:
                url = hosting.publish(src, f"{pdir.name}__{c['id']}{src.suffix}")
                win["url"] = url; c["window"] = win
                hosted["audio"] = {**(hosted.get("audio") or {}), "url": url, "sha1": cur}
                notes.append("re-hosted the window on the running tunnel" + (" (the window audio changed)" if stale else
                                                                             " (the tunnel restarted)"))
            else:
                raise SlopError(f"{c['id']}'s window is hosted on a quick tunnel that is not running: slop gen tunnel start, "
                                f"then re-run (it re-hosts automatically), or slop gen host {c['id']} --url URL")
        elif stale:
            raise SlopError(f"{c['id']}'s window audio changed after it was hosted at {url}: host the current one on the "
                            f"tunnel (slop gen tunnel start, then re-run this command: it hosts the window itself), or "
                            f"upload {store.rel(pdir, src)} with the Higgsfield connector and run slop gen host {c['id']} "
                            "--url NEW_URL [--media-id ID]")
        return url, notes
    if win.get("url_mode") == "tunnel" or (win.get("url_mode") != "data" and hosting.status()["running"]):
        auto = win.get("url_mode") != "tunnel"
        url = tunnel_host(pdir, c, "audio", src)                       # submit hosts the window itself (phase-2 UX fix)
        return url, notes + (["hosted the window on the running tunnel (keep the tunnel running until the job leaves "
                              "'pending')"] if auto else [])
    if win.get("url_mode") == "data":
        if not experimental_data:
            raise SlopError("data: audio URLs are rejected by OpenRouter (verified 2026-10-01: 'Only HTTPS URLs are allowed'). "
                            f"Host the window: slop gen host {c['id']} --tunnel, or --url URL")
        return data_url(src, kind="audio"), ["EXPERIMENTAL data: audio URL (known rejected 2026-10-01)"]
    return None, notes


# ------------------------------------------------------------------------------------------------ submit
def _new_take(c: dict, **kw) -> dict:
    tk = {"n": len(c.get("takes") or []) + 1, "submitted": store.now(), **kw}
    c.setdefault("takes", []).append(tk)
    return tk


PENDING_URL = "https://HOSTED-AT-SUBMIT/"


def preflight(pdir: Path, c: dict, project: dict, *, resolution: str | None = None,
              no_audio_ref: bool = False) -> tuple[list[str], str, str]:
    """(problems, resolution, model): every check a submit runs before anything is sent — the lock problems, a sung clip
    without its audio window, the model's resolution limits. `submit` refuses on any problem; `submit --dry-run` lists
    the same problems and never offers the --yes command while one is open."""
    if resolution and resolution not in RESOLUTIONS:
        raise SlopError("--res must be 480p, 720p or 1080p")
    cid = c["id"]
    probs = lock_problems(pdir, c)
    res = resolution or (c.get("body") or {}).get("resolution") or "720p"        # --res applies to this take only
    if no_audio_ref and c.get("kind") == "sung":
        probs.append("a sung clip is never submitted without its audio window (the lips follow it): drop --no-audio-ref")
    if c.get("provider") == "hedra":
        model = c.get("model") or hedra.MODEL
    elif c.get("provider") == "higgsfield":
        model = hf.MODEL
    else:
        model = c.get("model") or default_model(project)
        if res == "1080p" and "seedance-2.5" in model:
            probs.append("Seedance 2.5 on OpenRouter is 480p/720p only: --res 720p (or Higgsfield for 1080p: "
                         f"slop clip set {cid} --provider higgsfield)")
    return probs, res, model


def dry_run(pdir: Path, c: dict, project: dict, *, resolution: str | None = None, no_audio_ref: bool = False,
            flags: str = "") -> dict:
    """the exact request a submit would send (inline images shown as "data"), its mode and estimate — nothing is sent,
    hosted, saved or spent. Works on a draft too (its lock problems are listed). It runs the submit's own preflight, so
    it never approves a request the real submit would refuse."""
    cid = c["id"]
    probs, res, model = preflight(pdir, c, project, resolution=resolution, no_audio_ref=no_audio_ref)
    if c.get("status") == "submitted":
        probs.append(inflight_msg(c))
    lines: list[str] = []
    warnings: list[str] = []
    budget_ok = True
    if c.get("provider") == "higgsfield":
        req = hf.build_request(pdir, c, resolution=res)
        prm = req["request"]["params"]
        cr = req["expected_credits"]
        lines = [f"{cid} DRY RUN (nothing sent or spent): Higgsfield {prm['model']} mode {prm['mode']}, {prm['duration']} s "
                 f"{prm['resolution']}{' draft' if prm.get('draft') else ''}, ~{cr:g} credits",
                 "medias: " + ", ".join(f"{m['role']}={m['value'] if not str(m['value']).startswith('<<') else 'upload'}"
                                        for m in prm["medias"]),
                 "prompt:", prm["prompt"]]
        if c.get("kind") == "sung":
            if not any(m.get("role") == "audio_references" for m in prm["medias"]):
                probs.append(f"a sung clip must carry its window as audio_references (the lips follow it): slop clip set "
                             f"{cid} --recut")
            tail = higgsfield_tail_warning(SongData(pdir), float(c.get("song_t0") or 0), float(c["body"]["duration"]))
            if tail:
                warnings.append(tail.replace("CLIP", cid))
        try:
            ledger.check_budget(pdir, "higgsfield", add_usd=cr * hf.USD_PER_CREDIT, add_credits=cr, yes=True)
        except SlopError as e:
            budget_ok = False
            warnings.append(str(e))
        out = {"dry_run": True, "clip": cid, "provider": "higgsfield", "mode": prm["mode"],
               "would_send": {k: v for k, v in prm.items()}, "expected_credits": cr}
    else:
        send = {**c, "body": {**c["body"], "resolution": res}}
        audio_url = None
        if c.get("frame") != "first" and vid.media_refs_ok(model) and not no_audio_ref:
            win = c.get("window") or {}
            src = window_src(pdir, c)
            if c.get("kind") != "sung" and not (src and src.is_file()):      # sung: lock_problems already says it
                probs.append(f"{cid} has no window audio file: slop clip set {cid} --recut")
            audio_url = win.get("url") or ((c.get("hosted") or {}).get("audio") or {}).get("url")
            if not audio_url or audio_url.startswith("data:"):
                audio_url = PENDING_URL + f"{cid}.wav"
                warnings.append("the window has no HTTPS URL yet: the real submit hosts it on the tunnel itself when the "
                                "tunnel is running" + ("" if hosting.status()["running"] else
                                                       " — start it first: slop gen tunnel start")
                                + f" (or host it now: slop gen host {cid} --tunnel)")
        body = vid.build_body(pdir, send, model=model, audio_url=audio_url, video_urls=list(c.get("video_urls") or []),
                              warnings=warnings)
        est = vid.estimate(model, body)
        sm = vid.summary(body)
        mode = "first-frame" if body.get("frame_images") else "reference"
        roles = []
        n_img = 0
        for r in body.get("input_references") or []:
            if r.get("type") == "image_url":
                n_img += 1
                roles.append(f"@Image{n_img} image_url ({'inline data' if r['image_url']['url'].startswith('data:') else r['image_url']['url']})")
            elif r.get("type") == "audio_url":
                roles.append(f"@Audio1 audio_url ({r['audio_url']['url']})")
            elif r.get("type") == "video_url":
                roles.append(f"@Video video_url ({r['video_url']['url']})")
        lines = [f"{cid} DRY RUN (nothing sent or spent): OpenRouter {model}, {body.get('duration')} s {res}, {mode} mode, "
                 f"~${est:.4f}",
                 "input_references: " + ("; ".join(roles) or "none"),
                 "frame_images: " + (", ".join(x for x in sm["refs"] if x.endswith(":image")) or "none"),
                 f"generate_audio: {body.get('generate_audio')}", "prompt:", body.get("prompt") or ""]
        if c.get("kind") == "sung":
            if mode != "reference":
                probs.append("a sung clip must go out in reference mode (no frame_images)")
            if not no_audio_ref and not any(r.get("type") == "audio_url" for r in body.get("input_references") or []):
                probs.append("a sung clip must carry its window as @Audio1 (an audio_url reference): reference mode is "
                             "@Image1 + @Audio1, and without the window the lips cannot follow the song")
        try:
            ledger.check_budget(pdir, "openrouter", add_usd=est, yes=True)
        except SlopError as e:
            budget_ok = False
            warnings.append(str(e))
        out = {"dry_run": True, "clip": cid, "provider": "openrouter", "model": model, "mode": mode, "would_send": sm,
               "est_usd": est}
    if probs:
        lines.append("before submit: " + "; ".join(probs))
    prompt_warns = lock_warnings(c)              # a long sung prompt: said here too (kept apart from request warnings)
    st = c.get("status")
    nxt = ("fix the problems above, then run the dry run again" if probs else
           "the budget cap above refuses this take: ask the owner before anything else" if not budget_ok else
           f"slop clip submit {cid}{flags} --yes (after the owner's yes)" if st == "locked" else
           f"slop clip lock {cid}")
    lines.append("next: " + nxt)
    return {**out, "status": c.get("status"), "lock_problems": probs, "warnings": warnings,
            "prompt_warnings": prompt_warns,
            "text": "\n".join(lines) + "".join("\n  ! " + w for w in warnings + prompt_warns)}


@project_hints
def submit(pdir: Path, cid: str, *, provider: str | None = None, yes: bool = False, resolution: str | None = None,
           no_audio_ref: bool = False, experimental_data: bool = False, resubmit_unknown: bool = False,
           client: OpenRouter | None = None, dry: bool = False, finalize_from: int | None = None,
           again: bool = False, hedra_transport: str = "api", hedra_cost: float | None = None,
           hedra_currency: str | None = None, quote_only: bool = False) -> dict:
    if hedra_transport not in ("api", "mcp"):
        raise SlopError("--hedra-transport must be api or mcp")
    if quote_only and (finalize_from is not None or dry):
        raise SlopError("--quote-only cannot be combined with --dry-run or --finalize-from")
    if finalize_from is not None:
        if provider and provider != "higgsfield":
            raise SlopError("--finalize-from finalizes a Higgsfield 480p draft: use --provider higgsfield (or leave "
                            "--provider out)")
        return finalize(pdir, cid, finalize_from, yes=yes, dry=dry, again=again)
    if again:
        raise SlopError("--again only goes with --finalize-from TAKE (a second paid finalize of the same draft)")
    c = store.load(pdir, cid)
    project = proj(pdir)
    flags = ""
    if provider and provider != c.get("provider"):
        if provider not in ("openrouter", "higgsfield", "hedra"):
            raise SlopError("--provider must be openrouter, higgsfield or hedra")
        previous_provider = c.get("provider")
        c["provider"] = provider
        if provider == "hedra":
            c["model"] = hedra.MODEL
        elif previous_provider == "hedra":
            c["model"] = default_model(project)
        flags += f" --provider {provider}"
    if c.get("provider") != "hedra" and (quote_only or hedra_transport != "api" or hedra_cost is not None or hedra_currency is not None):
        raise SlopError("--hedra-* options require --provider hedra")
    if dry and c.get("provider") == "hedra":
        return hedra.dry_run(pdir, c, transport=hedra_transport, resolution=resolution, no_audio_ref=no_audio_ref)
    if dry:
        flags += (f" --res {resolution}" if resolution else "") + (" --no-audio-ref" if no_audio_ref else "")
        return dry_run(pdir, c, project, resolution=resolution, no_audio_ref=no_audio_ref, flags=flags)
    st = c.get("status")
    if st == "submitted":
        unk = store.unknown_take(c)
        if unk and unk.get("provider") == "hedra":
            raise SlopError(f"{cid}: Hedra outcome unknown; do not resubmit. Locate the job, then clip poll {cid} --job-id ID")
        if not (unk and resubmit_unknown):
            raise SlopError(inflight_msg(c) if unk else
                            f"{cid} already has a take in flight: slop clip poll {cid} (or slop clip ingest for Higgsfield)")
        if not (yes or gate_ok(project, c)):
            raise SlopError(f"re-submitting {cid} spends money ({describe_cost(c)}): re-run with --yes after the user agrees")
        unk.update(status="abandoned", abandoned=store.now())
        ledger.record(pdir, provider=unk.get("provider") or "openrouter", model=unk.get("model", ""), kind="video-refund",
                      est_usd=-float(unk.get("est_usd") or 0), status="ok", units={"clip": cid, "take": unk["n"]},
                      note="unknown outcome, not found on the provider: assumed not accepted (--resubmit-unknown)")
        c["status"] = st = "locked"
        store.save(pdir, c)
    if st != "locked":
        raise SlopError(f"{cid} is '{st}', not locked: spending needs a locked clip — review it, then slop clip lock {cid}")
    if not quote_only and not (yes or gate_ok(project, c)):
        raise SlopError(f"submitting {cid} spends money ({describe_cost(c)}): show the prompt and the estimate to the user and "
                        "re-run with --yes after they agree")
    probs, res, model = preflight(pdir, c, project, resolution=resolution, no_audio_ref=no_audio_ref)
    if probs:
        raise SlopError(f"{cid} is not ready:\n  - " + "\n  - ".join(probs))
    if c["provider"] == "hedra":
        return hedra.submit(pdir, c, transport=hedra_transport, yes=yes, resolution=res, no_audio_ref=no_audio_ref,
                            cost=hedra_cost, currency=hedra_currency, client=client, quote_only=quote_only)
    if c["provider"] == "higgsfield":
        return _submit_higgsfield(pdir, c, yes=yes, resolution=res)
    send = {**c, "body": {**c["body"], "resolution": res}}
    warnings: list[str] = []
    audio_url = None
    wants_audio = c.get("frame") != "first" and vid.media_refs_ok(model) and not no_audio_ref
    if wants_audio:
        audio_url, notes = resolve_audio_url(pdir, c, experimental_data=experimental_data)
        warnings += notes
        if not audio_url:
            raise SlopError(f"{cid}'s song window needs an HTTPS URL (OpenRouter takes audio references by HTTPS only) and "
                            f"no tunnel is running. Start it: slop gen tunnel start  — then run this submit again: it "
                            f"hosts the window on the tunnel itself. Only if the tunnel cannot start: upload "
                            f"{c['window'].get('wav') or c['window'].get('file')} with the Higgsfield connector "
                            "(media_upload; PUT the bytes with the header 'If-None-Match: *' or it answers 403; "
                            f"media_confirm; show_medias for its URL) and run slop gen host {cid} --url URL. "
                            + ("" if c["kind"] == "sung" else "(motion only: --no-audio-ref submits without the song, "
                                                               "losing the beat conditioning)"))
    tunnel_urls = [u for u in [audio_url, *(c.get("video_urls") or [])] if u and "trycloudflare.com" in str(u)]
    if tunnel_urls:                                                   # OpenRouter fetches it at once: it must answer
        v = hosting.ensure_verified()
        if not v.get("verified"):
            store.save(pdir, c)                                       # keep what was hosted; nothing was sent
            raise SlopError(f"{cid}: " + hosting.unverified_msg(v.get("error")))
    body = vid.build_body(pdir, send, model=model, audio_url=audio_url, video_urls=[u for u in c.get("video_urls") or []],
                          warnings=warnings)
    est = vid.estimate(model, body)
    ledger.check_budget(pdir, "openrouter", add_usd=est, yes=yes)       # BEFORE anything is sent
    client = client or OpenRouter()
    try:
        r = vid.submit(client, body)
    except ProviderError as e:
        return _record_submit_error(pdir, c, e, model, est, body, audio_url)
    tk = _new_take(c, provider="openrouter", id=r["id"], polling_url=r.get("polling_url"), status="submitted", model=model,
                   est_usd=est, body=vid.summary(body),
                   ref_audio=(c.get("window") or {}).get("wav") if audio_url else None)
    c["status"] = "submitted"
    store.save(pdir, c)
    ledger.record(pdir, provider="openrouter", model=model, kind="video", est_usd=est, request_id=r["id"], status="submitted",
                  units={"clip": cid, "take": tk["n"], "duration": body.get("duration"), "resolution": body.get("resolution")})
    return {"clip": cid, "take": tk["n"], "job": r["id"], "est_usd": est, "warnings": warnings,
            "text": f"{cid} take {tk['n']} submitted to OpenRouter ({model}, {body.get('duration')} s {body.get('resolution')}, "
                    f"~${est:.2f}); jobs take ~1–3 min: slop clip poll {cid} --wait 300"
                    + "".join("\n  ! " + w for w in warnings)}


def _record_submit_error(pdir: Path, c: dict, e: ProviderError, model: str, est: float, body: dict,
                         audio_url: str | None) -> dict:
    cid = c["id"]
    if e.status == "unknown_outcome":                                 # may be running and billed: never re-sent blindly
        tk = _new_take(c, provider="openrouter", id=None, status="unknown", model=model, est_usd=est,
                       body=vid.summary(body), ref_audio=(c.get("window") or {}).get("wav") if audio_url else None,
                       error=str(e)[:400])
        c["status"] = "submitted"
        store.save(pdir, c)
        ledger.record(pdir, provider="openrouter", model=model, kind="video", est_usd=est, status="submitted",
                      units={"clip": cid, "take": tk["n"], "duration": body.get("duration"),
                             "resolution": body.get("resolution")},
                      note="unknown_outcome: counted as spent until attached (--job-id) or abandoned (--resubmit-unknown)")
        adv = (f"{cid} take {tk['n']}: the submit got no clear answer ({'HTTP ' + str(e.http) if e.http else 'connection lost'}) "
               f"— the job may be running, so it is counted as spent (~${est:.2f}). Do NOT submit again. Look for a video job "
               f"made just now at https://openrouter.ai/activity: if it is there, attach it: slop clip poll {cid} --job-id "
               f"JOB_ID; if nothing shows up after ~10 minutes, it was not accepted: slop clip submit {cid} --yes "
               "--resubmit-unknown")
        return {"ok": False, "clip": cid, "take": tk["n"], "status": "unknown", "error": adv, "text": adv}
    st = "declined" if e.status in ("declined_face", "declined_text", "moderation") else "failed"
    ledger.record(pdir, provider="openrouter", model=model, kind="video", est_usd=0.0, status=st,
                  units={"clip": cid, "est_usd": est}, note=e.status)
    if e.status == "declined_face":
        c["status"] = "declined"
        c.setdefault("declined", []).append({"provider": "openrouter", "at": store.now(), "status": e.status,
                                             "note": e.detail[:300], "start": c.get("start")})
        store.save(pdir, c)
        return {"ok": False, "clip": cid, "status": "declined", "error": str(e),
                "text": f"{cid}: DECLINED by OpenRouter's face filter (free, final for this image). Never alter the image. "
                        f"Options: keep the shot on its 2.5D plate; or send the same unaltered image to Higgsfield: "
                        f"slop clip set {cid} --provider higgsfield && slop clip lock {cid} && slop clip submit {cid} --yes"}
    if e.status in ("declined_text", "moderation"):
        c["status"] = "draft"
        c.setdefault("declined", []).append({"provider": "openrouter", "at": store.now(), "status": e.status,
                                             "note": e.detail[:300], "prompt_only": True})
        store.save(pdir, c)
        return {"ok": False, "clip": cid, "status": e.status, "error": str(e),
                "text": f"{cid}: the prompt was refused ({e.status}). Reword it — keep the beat, change the words — "
                        f"then slop clip set {cid} --prompt-file FILE && slop clip lock {cid}"}
    if e.status in RETRY_ONCE:                                       # refused before a job existed: same protocol
        step = note_refusal(c, e.status, "openrouter")
        store.save(pdir, c)
        return {"ok": False, "clip": cid, "status": e.status, "error": e.head + " — " + step,   # ONE next step
                "text": f"{cid}: refused at submit ({e.status}, not billed).\n  {step}"}
    raise e


def _submit_higgsfield(pdir: Path, c: dict, *, yes: bool, resolution: str | None = None) -> dict:
    cid = c["id"]
    res = resolution or c["body"].get("resolution") or "720p"
    hf.build_request(pdir, c, resolution=res)                         # every check before anything is hosted or spent
    cr = hf.credits(int(c["body"].get("duration") or 5), res)
    ledger.check_budget(pdir, "higgsfield", add_usd=cr * hf.USD_PER_CREDIT, add_credits=cr, yes=yes)
    host_notes = auto_host(pdir, c)                                   # files on the running tunnel -> media_import_url
    req = hf.build_request(pdir, c, resolution=res)
    warns = []
    tail = (higgsfield_tail_warning(SongData(pdir), float(c.get("song_t0") or 0), float(c["body"]["duration"]))
            if c.get("kind") == "sung" else None)
    if tail:
        warns.append(tail.replace("CLIP", cid))
    if any("trycloudflare.com" in str(u.get("https_url") or "") for u in req["uploads"]):
        v = hosting.ensure_verified()
        if not v.get("verified"):
            warns.append(f"the tunnel's public URL does not answer yet ({v.get('error') or 'not verified'}): before any "
                         f"media_import_url, run slop gen tunnel status --verify until it says 'reachable through the "
                         f"public URL' (a new hostname can take ~30-60 s)")
    if any(u.get("method") == "media_upload" for u in req["uploads"]):
        warns.append(f"no tunnel is running, so the request uploads with media_upload (a PUT that needs the header "
                     f"'If-None-Match: *'). Simpler: slop gen tunnel start, then slop gen host {cid} --role start --tunnel "
                     f"and slop gen host {cid} --tunnel - they switch the request file to media_import_url")
    if warns:
        req["warnings"] = warns
    p = hf.write_request(pdir, c, req)
    tk = _new_take(c, provider="higgsfield", id=None, status="requested", model=hf.MODEL, credits_est=cr,
                   request_file=store.rel(pdir, p), body={k: v for k, v in req["request"]["params"].items() if k != "medias"},
                   ref_audio=(c.get("window") or {}).get("file"))
    c["status"] = "submitted"
    store.save(pdir, c)
    ledger.record(pdir, provider="higgsfield", model=hf.MODEL, kind="video", est_usd=0.0, credits=cr, status="submitted",
                  units={"clip": cid, "take": tk["n"], "duration": c["body"]["duration"], "resolution": res,
                         "usd_equiv": round(cr * hf.USD_PER_CREDIT, 2)}, note="request file for the bot")
    return {"clip": cid, "take": tk["n"], "request_file": str(p), "expected_credits": cr, "request": req,
            "warnings": req.get("warnings", []), "hosted": host_notes,
            "text": f"{cid}: wrote the Higgsfield request ({cr:g} credits expected) to {store.rel(pdir, p)}. The bot runs it "
                    "with its Higgsfield connector, step by step (how_to_run in the file), then: "
                    f"slop clip ingest {cid} --url RESULT_URL --job-id JOB_ID --credits {cr:g}"
                    + "".join("\n  " + n + " (the request uses media_import_url for them)" for n in host_notes)
                    + "".join("\n  ! " + w for w in req.get("warnings", []))}


@project_hints
def finalize(pdir: Path, cid: str, take_n: int, *, yes: bool = False, dry: bool = False, again: bool = False) -> dict:
    """`slop clip submit CLIP --provider higgsfield --finalize-from TAKE`: the request that finalizes a kept 480p
    Higgsfield draft take at 1080p (draft_job_id + a get_cost preflight). A new take is opened ("requested", like any
    Higgsfield submit) with its own request file (clips/CLIP/higgsfield-take-N-finalize-of-D.json). A draft that was
    already finalized (a take with finalize_of = D that did not fail) is refused unless `again` (the owner wants a second
    paid finalize). The edit uses the newest delivered take, so a sung clip's finalized take must be measured
    (`slop clip sync CLIP --take N`) before `edit edl` / render: until then it has no lag correction."""
    c = store.load(pdir, cid)
    takes = c.get("takes") or []
    if not 1 <= int(take_n) <= len(takes):
        raise SlopError(f"{cid} has {len(takes)} take(s): --finalize-from N names one of them (slop clip status {cid})")
    d = takes[int(take_n) - 1]
    b = d.get("body") or {}
    probs = []
    if d.get("provider") != "higgsfield":
        probs.append(f"take {take_n} is a {d.get('provider')} take: only a Higgsfield draft can be finalized")
    elif not (b.get("draft") or b.get("resolution") == "480p"):
        probs.append(f"take {take_n} is not a 480p draft (resolution {b.get('resolution')}): there is nothing to finalize")
    if d.get("status") != "delivered":
        probs.append(f"take {take_n} is {d.get('status')}: finalize a delivered draft (slop clip ingest {cid} --url URL "
                     "--job-id JOB_ID first)")
    elif d.get("finalize_of"):
        probs.append(f"take {take_n} is already a finalized take (of take {d['finalize_of']})")
    done = [t for t in takes if t.get("finalize_of") == int(take_n)
            and t.get("status") not in ("failed", "declined", "abandoned")]
    if done and not again:
        t = done[-1]
        probs.append(f"take {take_n} was already finalized as take {t.get('n')} ({t.get('status')}): use that take, do not "
                     "pay again - " + (f"slop clip sync {cid} --take {t.get('n')}" if t.get("status") == "delivered"
                                        and c.get("kind") == "sung" else f"slop clip status {cid}")
                     + ". Only if the owner asks for a second paid finalize of the same draft: add --again")
    idp = hf.job_id_problem(d.get("id")) if d.get("id") else (
        f"take {take_n} has no Higgsfield job id, and draft_job_id needs it: find the draft's job id (show_generations "
        "or transactions in the connector) and tell the owner; it cannot be finalized without it")
    if idp:
        probs.append(idp)
    if c.get("kind") == "sung" and not probs:
        sy = d.get("sync") or {}
        if not sy:
            probs.append(f"measure the draft first (finalize only a draft you keep): slop clip sync {cid} --take {take_n}")
        elif sy.get("mode") != "copy":
            probs.append(f"take {take_n} did not copy the song (NCC {sy.get('ncc')}): a 1080p finalize keeps its motion, "
                         "so it would not fix the lip sync - re-route the window or cut away instead (docs/61-lipsync)")
    age = hf.draft_age_days(d)
    if age is not None and age > hf.FINALIZE_DAYS:
        probs.append(f"take {take_n} is {age:.1f} days old: Higgsfield finalizes drafts within {hf.FINALIZE_DAYS} days - "
                     f"generate a new take instead (slop clip set {cid} --res 720p && slop clip lock {cid} && slop clip "
                     f"submit {cid} --yes)")
    if c.get("status") == "submitted":
        probs.append(inflight_msg(c))
    if probs and not dry:
        raise SlopError(f"cannot finalize {cid} take {take_n}:\n  - " + "\n  - ".join(probs))
    req = hf.build_finalize(pdir, c, {**d, "n": int(take_n), "id": d.get("id") or "<DRAFT JOB ID>"},
                            index=0)
    cr = req["expected_credits"]
    if dry:
        lines = [f"{cid} DRY RUN (nothing sent or spent): finalize take {take_n} at 1080p (draft_job_id "
                 f"{req['draft_job_id']}), ~{cr:g} credits (observed 12/s; get_cost is the truth)", "prompt:",
                 req["request"]["params"]["prompt"]]
        if probs:
            lines.append("before submit: " + "; ".join(probs))
        lines.append("next: " + ("fix the problems above, then run the dry run again" if probs else
                                 f"slop clip submit {cid} --provider higgsfield --finalize-from {take_n}"
                                 + (" --again" if again else "") + " --yes (after the owner's yes)"))
        return {"dry_run": True, "clip": cid, "provider": "higgsfield", "finalize_of": int(take_n), "expected_credits": cr,
                "would_send": req["request"]["params"], "lock_problems": probs, "text": "\n".join(lines)}
    if not yes:
        raise SlopError(f"finalizing {cid} take {take_n} spends Higgsfield credits (~{cr:g} at 1080p; get_cost tells the "
                        f"exact price): show the owner the estimate, then re-run with --yes")
    ledger.check_budget(pdir, "higgsfield", add_usd=cr * hf.USD_PER_CREDIT, add_credits=cr, yes=yes)
    new_n = len(takes) + 1                                           # its own file: a later finalize never overwrites it
    p = store.clip_folder(pdir, cid) / f"higgsfield-take-{new_n}-finalize-of-{int(take_n)}.json"
    p.write_text(json.dumps(req, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    tk = _new_take(c, provider="higgsfield", id=None, status="requested", model=hf.MODEL, credits_est=cr,
                   request_file=store.rel(pdir, p), body=dict(req["request"]["params"]), finalize_of=int(take_n),
                   ref_audio=d.get("ref_audio"), **({"needs_sync": True} if c.get("kind") == "sung" else {}))
    c["status"] = "submitted"
    store.save(pdir, c)
    ledger.record(pdir, provider="higgsfield", model=hf.MODEL, kind="video-finalize", est_usd=0.0, credits=cr,
                  status="submitted", units={"clip": cid, "take": tk["n"], "finalize_of": int(take_n),
                                             "duration": req["request"]["params"]["duration"], "resolution": "1080p",
                                             "usd_equiv": round(cr * hf.USD_PER_CREDIT, 2)},
                  note="finalize request for the bot")
    sync_line = (f"; then REQUIRED: slop clip sync {cid} (a finalize may not keep the lip sync)"
                 if c.get("kind") == "sung" else "")
    return {"clip": cid, "take": tk["n"], "finalize_of": int(take_n), "request_file": str(p), "expected_credits": cr,
            "text": f"{cid}: wrote the finalize request for take {take_n} (1080p, ~{cr:g} credits expected; get_cost first) "
                    f"to {store.rel(pdir, p)}. The bot runs it with its Higgsfield connector (how_to_run in the file), "
                    f"then: slop clip ingest {cid} --url RESULT_URL --job-id JOB_ID --credits N{sync_line}"}


# ------------------------------------------------------------------------------------------------ poll / ingest
@project_hints
def poll(pdir: Path, cids: list[str] | None = None, *, wait_s: float = 0.0, job_id: str | None = None,
         client: OpenRouter | None = None, sleep=None) -> dict:
    attached = None
    hedra_client = client if isinstance(client, hedra.Hedra) else None
    if job_id:
        if not cids or len(cids) != 1:
            raise SlopError("--job-id attaches one job to one clip: slop clip poll CLIP --job-id JOB_ID")
        c = store.load(pdir, cids[0])
        if any(t.get("provider") == "hedra" and t.get("status") in ("unknown", "submitted", "requested", "pending")
               for t in c.get("takes", [])):
            r = hedra.poll(pdir, c, wait_s=wait_s, job_id=job_id, client=client, sleep=sleep)
            return {"results": [r], "text": r["text"]}
        unk = store.unknown_take(c)
        if not unk:
            if any(t.get("id") == job_id for t in c.get("takes") or []):
                attached = None
            else:
                raise SlopError(f"{cids[0]} has no take with an unknown outcome to attach {job_id} to")
        else:
            unk.update(id=job_id.strip(), status="submitted", attached=store.now())
            c["status"] = "submitted"
            store.save(pdir, c)
            ledger.record(pdir, provider="openrouter", model=unk.get("model", ""), kind="video-attach", est_usd=0.0,
                          request_id=job_id.strip(), status="ok", units={"clip": c["id"], "take": unk["n"]},
                          note="job id attached to the unknown-outcome take (its estimate is already counted)")
            attached = unk["n"]
    clips = [store.load(pdir, x) for x in cids] if cids else [c for c in store.all_clips(pdir) if c.get("status") == "submitted"]
    results, lines = [], []
    if attached:
        lines.append(f"{cids[0]}: job {job_id} attached to take {attached}")
    client = client or (OpenRouter() if any(_pending_or(c) for c in clips) else None)
    for c in clips:
        if any(t.get("provider") == "hedra" and t.get("status") in ("unknown", "submitted", "requested", "pending")
               for t in c.get("takes", [])):
            r = hedra.poll(pdir, c, wait_s=wait_s, sleep=sleep, client=hedra_client)
            results.append(r); lines.append(r["text"]); continue
        tk = _pending_or(c)
        if not tk:
            hfk = next((t for t in reversed(c.get("takes") or []) if t.get("provider") == "higgsfield"
                        and t.get("status") in ("requested", "pending")), None)
            unk = store.unknown_take(c)
            if unk:
                msg = inflight_msg(c)
            elif hfk:
                msg = (f"{c['id']}: Higgsfield take {hfk['n']} is {hfk['status']} — the bot polls it with jobs_wait, then "
                       f"slop clip ingest {c['id']} --url RESULT_URL --job-id JOB_ID")
            else:
                msg = f"{c['id']}: nothing in flight (status {c.get('status')})"
            results.append({"clip": c["id"], "status": c.get("status"), **({"take": unk["n"], "job_status": "unknown"}
                                                                           if unk else {})})
            lines.append(msg); continue
        kw = {"sleep": sleep} if sleep else {}
        stt = vid.wait(client, tk["id"], tk.get("polling_url"), wait_s, **kw)
        state = stt.get("status")
        tk["result"] = {k: v for k, v in stt.items() if k not in ("unsigned_urls",)}
        if state == "completed":
            out = store.take_path(pdir, c["id"], tk["n"])
            vid.download(client, tk["id"], out)
            real = (stt.get("usage") or {}).get("cost")
            tk.update(status="delivered", file=store.rel(pdir, out), delivered=store.now(),
                      cost_usd=float(real) if real is not None else None, sha1=store.file_sha1(out))
            c["status"] = "delivered"
            est = float(tk.get("est_usd") or 0)
            if real is not None and abs(float(real) - est) > 1e-6:
                ledger.record(pdir, provider="openrouter", model=tk.get("model", ""), kind="video-adjust",
                              est_usd=round(float(real) - est, 6), request_id=tk["id"], status="ok",
                              units={"clip": c["id"], "take": tk["n"], "real_usd": real, "est_usd": est},
                              note="settled to the provider's usage.cost")
            lines.append(f"{c['id']}: take {tk['n']} delivered -> {tk['file']} (${real if real is not None else est:.2f}); "
                         + (f"next: slop clip sync {c['id']}" if c["kind"] == "sung" else "motion take: review it"))
        elif state in vid.TERMINAL:
            err = vid.failure_error(stt, tk["id"])
            tk.update(status="declined" if err.status == "declined_face" else "failed", error=str(err)[:600], error_class=err.status)
            ledger.record(pdir, provider="openrouter", model=tk.get("model", ""), kind="video-refund",
                          est_usd=-float(tk.get("est_usd") or 0), request_id=tk["id"], status="ok",
                          units={"clip": c["id"], "take": tk["n"]}, note=f"job {state}: failed jobs are not billed")
            if err.status == "declined_face":
                c["status"] = "declined"
                c.setdefault("declined", []).append({"provider": "openrouter", "at": store.now(), "status": err.status,
                                                     "note": str(err)[:300], "start": c.get("start")})
            else:
                c["status"] = "locked"                                # ready for a retry (the production behaviour)
            lines.append(f"{c['id']}: take {tk['n']} {state}: "
                         + (f"{err.head} (not billed)" if err.status in RETRY_ONCE else str(err)))
            if err.status in RETRY_ONCE:                                 # the protocol's ONE next step, not the advice
                tk["next"] = note_refusal(c, err.status, "openrouter", take=tk["n"])
                lines.append("  " + tk["next"])
        else:
            lines.append(f"{c['id']}: take {tk['n']} {state or 'unknown'} (still rendering; jobs take ~1–3 min) — "
                         f"slop clip poll {c['id']} --wait 300")
        store.save(pdir, c)
        results.append({"clip": c["id"], "take": tk["n"], "status": tk.get("status"), "job_status": state,
                        "file": tk.get("file"), "cost_usd": tk.get("cost_usd")})
    if not clips:
        lines.append("no clips in flight")
    return {"results": results, "text": "\n".join(lines)}


def _pending_or(c: dict) -> dict | None:
    for tk in reversed(c.get("takes") or []):
        if tk.get("provider") == "openrouter" and tk.get("status") == "submitted" and tk.get("id"):
            return tk
    return None


@project_hints
def ingest(pdir: Path, cid: str, *, file: str | None = None, url: str | None = None, job_id: str | None = None,
           credits: float | None = None, pending: bool = False, failed: str | None = None, declined: str | None = None,
           provider: str | None = None, session=None, cost_usd: float | None = None) -> dict:
    c = store.load(pdir, cid)
    if provider == "hedra" or (provider is None and c.get("provider") == "hedra"):
        return hedra.ingest(pdir, c, file=file, url=url, job_id=job_id, credits=credits, cost_usd=cost_usd,
                            pending=pending, failed=failed, declined=declined, session=session)
    if cost_usd is not None:
        raise SlopError("--cost-usd is for Hedra results")
    prov = provider or ("higgsfield" if any(t.get("provider") == "higgsfield" and t.get("status") in ("requested", "pending")
                                            for t in c.get("takes") or []) else c.get("provider") or "higgsfield")
    tk = next((t for t in reversed(c.get("takes") or []) if t.get("provider") == prov
               and t.get("status") in ("requested", "pending", "submitted")), None)
    idw = hf.job_id_problem(job_id) if prov == "higgsfield" else None   # a warning: the id is kept as given
    if pending:
        if not tk:
            raise SlopError(f"{cid} has no requested {prov} take to attach a job id to (submit it first)")
        if not job_id:
            raise SlopError("--pending needs --job-id")
        tk.update(id=job_id.strip(), status="pending", job_recorded=store.now())
        store.save(pdir, c)
        return {"clip": cid, "take": tk["n"], "warnings": [idw] if idw else [],
                "text": f"{cid}: take {tk['n']} job {job_id} recorded (pending); poll it with jobs_wait {{jobs:[{{index:0, "
                        f"job_id}}], timeout_seconds:15}} until it is terminal" + (f"\n  ! {idw}" if idw else "")}
    if failed or declined:
        if not tk:
            raise SlopError(f"{cid} has no take in flight to mark")
        reason = failed or declined
        tk.update(status="declined" if declined else "failed", error=reason, id=job_id or tk.get("id"))
        est_cr, est_usd = float(tk.get("credits_est") or 0), float(tk.get("est_usd") or 0)
        if est_cr or est_usd:                     # failed / refused jobs are not charged: the estimate comes off the log
            ledger.record(pdir, provider=prov, model=tk.get("model", ""), kind="video-refund",
                          credits=-est_cr if est_cr else None, est_usd=-est_usd if est_usd else 0.0, status="ok",
                          units={"clip": cid, "take": tk["n"]},
                          note=f"{reason}: " + ("refunded" if tk.get("id") else "not charged (no job ran)"))
        fin = tk.get("finalize_of")
        draft = store.latest_delivered_take(c) if fin else None
        if fin and draft:                         # a finalize that failed or was refused: nothing new was made, nothing
            c["status"] = "delivered"             # charged; the draft stays the clip's take (no new paid draft offered)
            adv = (f"the 1080p finalize of take {fin} was not made and counts 0 credits; take {draft.get('n')} stays "
                   f"{cid}'s take ({cid} is delivered, nothing to re-lock). Tell the owner; a retry only on their yes: "
                   f"slop clip submit {cid} --provider higgsfield --finalize-from {fin} --yes")
        elif declined:
            c["status"] = "declined"
            c.setdefault("declined", []).append({"provider": prov, "at": store.now(), "status": "declined", "note": reason,
                                                 "start": c.get("start")})
            adv = ("the image is declined for this provider (final): keep the shot on its plate or try the other provider "
                   "with the same unaltered image")
        else:
            c["status"] = "locked"
            kind = classify(None, reason)
            if kind in RETRY_ONCE:                                   # output-audio refusal: the same protocol as OpenRouter
                adv = note_refusal(c, kind, prov, take=tk["n"])
                tk["error_class"] = kind; tk["next"] = adv
            else:
                adv = ("silent input filter: reword the prompt without changing the beat (docs/62-moderation), then "
                       f"slop clip set {cid} --prompt-file FILE && slop clip lock {cid} && slop clip submit {cid} --yes"
                       if "filter" in reason.lower() or "fail" in reason.lower() else
                       "output flagged: change the staging, not the image (slop clip set " + cid + " --prompt-file FILE)"
                       if "nsfw" in reason.lower() else
                       f"read the reason, fix the clip (slop clip set {cid} …), then slop clip lock {cid} && slop clip "
                       f"submit {cid} --yes")
        store.save(pdir, c)
        return {"clip": cid, "take": tk["n"], "status": tk["status"], **({"next": tk["next"]} if tk.get("next") else {}),
                "text": f"{cid}: take {tk['n']} {tk['status']} ({reason}) — {adv}"}
    if not (file or url):
        raise SlopError("give the take: --file MP4 or --url RESULT_URL (or --pending/--failed/--declined)")
    sha_in = store.file_sha1(Path(file)) if file and Path(file).is_file() else None
    for t in c.get("takes") or []:                                    # idempotent: the same job / URL / file is ingested once
        if t.get("status") == "delivered" and ((job_id and t.get("id") == job_id) or (url and t.get("source_url") == url)
                                               or (sha_in and t.get("sha1") == sha_in)):
            return {"clip": cid, "take": t["n"], "file": t.get("file"), "duration_s": t.get("duration_s"),
                    "text": f"{cid}: take {t['n']} already ingested from that job/URL/file ({t.get('file')})"}
    n = tk["n"] if tk else len(c.get("takes") or []) + 1
    out = store.take_path(pdir, cid, n)
    if url:
        hf.fetch_result(url, out, session=session)
    else:
        hf.copy_file(Path(file), out)
    d = probe_duration(out)
    if d is not None and d <= 0.2:
        raise SlopError(f"{out.name} does not look like a video (duration {d})")
    if not tk:
        tk = _new_take(c, provider=prov if (provider or url) else "manual", status="delivered")
    tk.update(status="delivered", file=store.rel(pdir, out), delivered=store.now(), id=job_id or tk.get("id"),
              source_url=url, duration_s=d, sha1=store.file_sha1(out))
    if credits is not None:
        tk["credits"] = float(credits)
        est = float(tk.get("credits_est") or 0)
        if est and abs(float(credits) - est) > 1e-6:
            ledger.record(pdir, provider=prov, model=tk.get("model", hf.MODEL), kind="video-adjust",
                          credits=round(float(credits) - est, 2), est_usd=0.0, status="ok", units={"clip": cid, "take": n})
        elif not est:
            ledger.record(pdir, provider=prov, model=tk.get("model", hf.MODEL), kind="video", credits=float(credits),
                          est_usd=0.0, status="delivered", request_id=job_id, units={"clip": cid, "take": n})
    if not tk.get("ref_audio"):
        tk["ref_audio"] = (c.get("window") or {}).get("file") if prov == "higgsfield" else (c.get("window") or {}).get("wav")
    c["status"] = "delivered"
    store.save(pdir, c)
    out = {"clip": cid, "take": n, "file": tk["file"], "duration_s": d,
           "text": f"{cid}: take {n} ingested -> {tk['file']}" + (f"; next: slop clip sync {cid}" if c["kind"] == "sung" else "")}
    if tk.get("finalize_of") and c["kind"] == "sung":
        out["next"] = f"slop clip sync {cid} --take {n}"
        out["text"] = (f"{cid}: take {n} (the 1080p finalize of take {tk['finalize_of']}) ingested -> {tk['file']}; "
                       f"REQUIRED next: {out['next']} (a finalize may not keep the lip sync, and the edit uses this newest "
                       f"take at once with NO lag correction until it is measured: run the sync before edit edl or render)")
    return out


# ------------------------------------------------------------------------------------------------ sync
@project_hints
def sync(pdir: Path, cid: str, take_n: int | None = None, png: bool = True) -> dict:
    from ..sync import avsync
    from ..sync.coverage import coverage
    c = store.load(pdir, cid)
    takes = c.get("takes") or []
    if take_n:
        if not 1 <= take_n <= len(takes):
            raise SlopError(f"{cid} has {len(takes)} take(s)")
        tk = takes[take_n - 1]
    else:
        tk = store.latest_delivered_take(c)
    if not tk or not tk.get("file"):
        raise SlopError(f"{cid} has no delivered take to measure (slop clip poll / ingest first)")
    vfile = store.absp(pdir, tk["file"])
    ref = store.absp(pdir, tk.get("ref_audio") or (c.get("window") or {}).get("wav") or (c.get("window") or {}).get("file"))
    if not ref or not ref.is_file():
        raise SlopError(f"the window audio sent with {cid} is missing ({ref}): re-cut it (slop clip set {cid} --recut)")
    song = SongData(pdir)
    t0 = float(c.get("song_t0") or 0.0); dur = float((c.get("body") or {}).get("duration") or 0)
    pngp = store.clip_folder(pdir, cid) / f"take-{tk['n']}-sync.png" if png else None
    o = avsync.check(vfile, ref, t0, png=pngp, song=song, title=proj(pdir).get("title") or "")
    spans = [[a, min(b, t0 + dur)] for a, b in (o.get("spans_song") or []) if min(b, t0 + dur) > a]
    synced = [round(t0 + o["synced_from"] - o["lag_s"], 3), round(min(o.get("synced_until_song") or t0 + dur, t0 + dur), 3)]
    tk["sync"] = {"lag_s": o["lag_s"], "ncc": o["lag_ncc"], "mode": "copy" if o["lag_ncc"] > .2 else "none",
                  "synced": spans, "diverge_at": o.get("diverge_at_song"), "cut_at": o.get("cut_eighth_song"),
                  "lag_ncc": o["lag_ncc"], "diverges": o["diverges"], "diverge_at_song": o.get("diverge_at_song"),
                  "synced_until_song": o.get("synced_until_song"), "cut_eighth_song": o.get("cut_eighth_song"),
                  "cut_beat_song": o.get("cut_beat_song"), "dips": o["dips"], "spans_song": spans, "synced_song": synced,
                  "words_at_divergence": o.get("words_at_divergence"), "png": store.rel(pdir, pngp) if pngp else None,
                  "measured": store.now(), "avsync_mode": o["mode"]}
    tk.pop("needs_sync", None)                                        # a finalized take is measured now
    store.save(pdir, c)
    need = c.get("needed") or [t0, t0 + dur]
    cov, tot, gaps = coverage(spans, song.words, need, min_gap=.6) if song.has_words else (0.0, 0.0, [])
    share = round(cov / tot, 3) if tot else None
    partial = share is not None and share < .95                       # phase-2 UX: never "in sync" at 21-47 %
    verdict = (f"PARTIAL: {cov:.2f}/{tot:.2f} sung s in sync (every gap is under 0.6 s: no cover needed)"
               if partial and not gaps else
               "in sync for the needed sung seconds" if tot and not gaps else
               f"diverges at song {o.get('diverge_at_song')} s; cut on the eighth at {o.get('cut_eighth_song')} s"
               if o["diverges"] else "no divergence found")
    txt = (f"{cid} take {tk['n']}: lag {o['lag_s'] * 1000:+.0f} ms, copy NCC {o['lag_ncc']:.2f} "
           f"({'copy' if o['lag_ncc'] > .2 else 'not a copy'}), {verdict}"
           + (f"; {cov:.2f}/{tot:.2f} sung s in sync ({share:.0%})" if share is not None else "")
           + (f"; uncovered gaps {gaps}: slop clip cover {c.get('parent') or cid}" if gaps else "")
           + (f"\n  figure: {tk['sync']['png']}" if pngp else ""))
    first = short_first(c, share, o["lag_ncc"] > .2)
    if first:
        txt += "\n  first: " + first
    return {"clip": cid, "take": tk["n"], "sync": tk["sync"], "covered_s": round(cov, 3), "sung_s": round(tot, 3),
            "share": share, "gaps": gaps, "short_first": first, "text": txt}


def short_first(c: dict, share: float | None, copied: bool) -> str | None:
    """the measured first step for a sung take that mostly did not copy (under half its sung seconds in sync, or no
    copy) while the clip's prompt is past the short form's limits: rewrite it short and retake on the SAME provider,
    before covers or re-routing (docs/61-lipsync.md §8; Studio run c01 0 % -> 78 % that way)."""
    mostly_off = share < .5 if share is not None else not copied
    if c.get("kind") != "sung" or not mostly_off:
        return None
    st = tpl.prompt_stats((c.get("body") or {}).get("prompt") or "")
    if st["words"] <= tpl.SHORT_MAX_WORDS and st["beats"] <= tpl.SHORT_MAX_BEATS:
        return None
    cid = c["id"]
    return (f"{cid}'s prompt is long ({st['words']} words besides the quoted lyric, {st['beats']} timed beats): long sung "
            "prompts re-sang the line instead of copying @Audio1 (Studio run c01: 0 % in sync; short: 78 %). Before a "
            f"cover or another provider, rewrite it in the short sung form (docs/60-clips.md §4.0: {tpl.SHORT_RULE}) "
            "and retake on the same provider: slop clip set "
            f"{cid} --prompt-file FILE, slop clip lock {cid}, slop clip submit {cid} --dry-run")


# ------------------------------------------------------------------------------------------------ frames
@project_hints
def take_frame(pdir: Path, cid: str, at: float | None = None, *, take_n: int | None = None, out: str | None = None) -> dict:
    """a still of a delivered take at SONG time `at` (clip time = at − song_t0 + the take's measured lag), default its last
    in-sync frame (synced_song end − .05 s, the production last_good_frame) — a start image that continues that take."""
    from ..sync.coverage import extract_frame
    c = store.load(pdir, cid)
    takes = c.get("takes") or []
    if take_n:
        if not 1 <= take_n <= len(takes):
            raise SlopError(f"{cid} has {len(takes)} take(s)")
        tk = takes[take_n - 1]
    else:
        tk = store.latest_synced_take(c) or store.latest_delivered_take(c)
    if not tk or not tk.get("file") or not (store.absp(pdir, tk["file"]) or Path()).is_file():
        raise SlopError(f"{cid} has no delivered take to take a frame from (slop clip poll / ingest first)")
    sy = tk.get("sync") or {}
    warns = []
    if not sy:
        warns.append(f"take {tk['n']} has no sync measurement: lag 0 assumed (slop clip sync {cid} measures it)")
    t0 = float(c.get("song_t0") or 0.0); lag = float(sy.get("lag_s") or 0.0)
    if at is None:
        end = (sy.get("synced_song") or [None, None])[1]
        if end is None:
            raise SlopError(f"pass --at SONG_T (take {tk['n']} of {cid} has no measured in-sync span to default to)")
        at = float(end) - .05
    vf = store.absp(pdir, tk["file"])
    d = probe_duration(vf) or float((c.get("body") or {}).get("duration") or 0)
    ct = float(at) - t0 + lag
    if ct < 0 or ct > d - .02:
        raise SlopError(f"song time {at:.2f} s is outside take {tk['n']} of {cid} (it shows song {t0 - lag:.2f}–"
                        f"{t0 - lag + d:.2f} s)")
    fr = int(round(ct * FPS))
    fr = min(fr, max(0, int(d * FPS) - 1))
    dst = Path(out) if out else store.clip_folder(pdir, cid) / f"take-{tk['n']}-frame-{fr}.png"
    if not dst.is_absolute():
        dst = pdir / dst
    extract_frame(vf, fr / FPS, dst)
    used = store.used_starts(pdir).get(store.image_sha1(dst))
    if used:
        warns.append(f"this frame is already the start of {used}: pick another --at (two clips never start from the same frame)")
    rp = store.rel(pdir, dst)
    return {"clip": cid, "take": tk["n"], "file": rp, "song_t": round(float(at), 3), "clip_t": round(fr / FPS, 3),
            "frame": fr, "lag_s": lag, "used_by": used, "warnings": warns,
            "text": f"{cid} take {tk['n']} frame {fr} (song {float(at):.2f} s) -> {rp}; use it as a start: slop clip new SHOT "
                    f"--kind sung|motion --start {rp} (or slop clip set CLIP --start {rp})"
                    + "".join("\n  ! " + w for w in warns)}


# ------------------------------------------------------------------------------------------------ covers
def cover_words(song: SongData, her: list | None, t0: float, dur: float, mode: str | None) -> tuple[str, str | None, list]:
    """(quoted words, clean-window quote or None, her_words) for a cover window. A her-words chain keeps her words (the
    production make_cover: hw = the parent's her_words starting inside the cover window); otherwise every word."""
    if her and (mode or "clean") == "clean":
        hw = [list(w) for w in her if t0 + CLEAN_LO <= float(w[0]) < t0 + dur - .08]
        if hw:
            txt = song.text_for(hw)
            return txt, txt, hw
    return song.words_in(t0, t0 + dur, word_lo({"mode": mode})), None, []


@project_hints
def make_cover(pdir: Path, root_id: str, prop: dict, *, lock_it: bool = False, start: str | None = None) -> dict:
    from ..sync.coverage import extract_frame
    root = store.load(pdir, root_id)
    parent = store.load(pdir, prop["parent"]) if prop.get("parent") else root
    project = proj(pdir)
    song = SongData(pdir)
    lead = tpl.lead_words(project)
    cid = prop["id"]
    if store.exists(pdir, cid):
        raise SlopError(f"{cid} already exists")
    if start:
        sp, sha, _ = choose_start(pdir, cid, None, start); sf = None
    else:
        sf = prop.get("start_frame")
        if not sf or prop.get("start_problem"):
            raise SlopError(f"no start frame for {cid}: {prop.get('start_problem') or 'unknown'}")
        sp = extract_frame(store.absp(pdir, sf["take_file"]), sf["t"], store.clip_folder(pdir, cid) / "start.png")
        sha = store.image_sha1(sp)
        used = store.used_starts(pdir, exclude=cid)
        if sha in used:
            raise SlopError(f"the frame at the cut is identical to the start of {used[sha]}: pass --start IMAGE")
    t0, dur = float(prop["song_t0"]), int(prop["duration"])
    mode = (root.get("window") or {}).get("mode")
    words, quoted, hw = cover_words(song, parent.get("her_words") or root.get("her_words"), t0, dur, mode)
    window, warns = cut_window(pdir, cid, t0, dur, "sung", mode, quoted=quoted, tokens=hw or None)
    lo = word_lo(window)
    if not hw:
        words = song.words_in(t0, t0 + dur, lo)
    pprompt = (parent.get("body") or {}).get("prompt") or ""
    timed = bool(TS_RE.search(pprompt) or tpl.timed_beats(pprompt))  # its times belong to the parent's window
    kept = tpl.without_timed_lines(pprompt) if timed and tpl.is_short(pprompt) else None
    scaffolded = timed and not kept
    if scaffolded:                                                   # a cover sings: redraft it in the short form
        prompt = tpl.sung_prompt(words=words, phrases=song.phrases(t0, t0 + dur, lo=lo, keep=hw or None), t0=t0, duration=dur,
                                 shot=(find_shot(pdir, root.get("shot") or "") or {}), lead=lead,
                                 kicks=song.kicks(t0, t0 + dur), downbeats=song.downbeats_in(t0, t0 + dur), style="short")
        note = ("the parent prompt is timestamped for its own window: this cover is drafted in the short sung form (it "
                "copies @Audio1 far more often); write its line of framing and light")
    elif kept:
        prompt = tpl.sing_prompt(kept, words, lead["pronoun"])
        note = ("the parent's short prompt with its timed-beat lines dropped (their times belonged to the parent's "
                "window) and this window's exact words re-quoted")
    else:
        prompt = tpl.sing_prompt(pprompt, words, lead["pronoun"])
        note = "the parent prompt with this window's exact words re-quoted"
    clip = {"id": cid, "shot": root.get("shot"), "kind": "sung", "status": "draft", "provider": parent.get("provider") or "openrouter",
            "model": parent.get("model") or sung_default_model(project)[0], "frame": "ref", "start": store.rel(pdir, sp),
            "start_sha1": sha, **({"start_frame": sf} if sf else {}), "refs": list(parent.get("refs") or []), "videos": [],
            "song_t0": round(t0, 3), "needed": prop["needed"], "words": words, "window": window,
            "body": {**(parent.get("body") or {}), "prompt": prompt, "duration": dur},
            "takes": [], "covers": [], "parent": root_id, "after": prop.get("parent"), "why": prop["why"],
            "created": store.now(), "hosted": {}, "declined": [], "history": [],
            "draft_notes": {"cover_of": prop.get("parent"), "prompt_source": note, "parent_prompt": pprompt,
                            **({"scaffold": prompt, "style": "short"} if scaffolded else {})}}
    if hw:
        clip["her_words"] = [[round(float(w[0]), 3), round(float(w[1]), 3), w[2] if len(w) > 2 else ""] for w in hw]
    store.save(pdir, clip)
    root = store.load(pdir, root_id)
    root.setdefault("covers", [])
    if cid not in root["covers"]:
        root["covers"].append(cid)
    store.save(pdir, root)
    locked = False
    if lock_it and not lock_problems(pdir, clip):
        warns += lock(pdir, cid).get("warnings") or []; locked = True
    return {"id": cid, "locked": locked, "start": clip["start"], "warnings": warns, "prompt_source": note}


# ------------------------------------------------------------------------------------------------ list / status
def row(c: dict) -> dict:
    tks = c.get("takes") or []
    last = tks[-1] if tks else {}
    sy = (store.latest_synced_take(c) or {}).get("sync") or {}
    return {"id": c["id"], "shot": c.get("shot"), "kind": c.get("kind"), "status": c.get("status"),
            "provider": c.get("provider"), "model": c.get("model"), "song_t0": c.get("song_t0"),
            "duration": (c.get("body") or {}).get("duration"), "resolution": (c.get("body") or {}).get("resolution"),
            "takes": len(tks), "last_take": last.get("status"), "synced": sy.get("synced"), "lag_s": sy.get("lag_s"),
            "parent": c.get("parent"), "covers": c.get("covers") or [], "cost": clip_cost(c),
            "spent_usd": round(sum(float(t.get("cost_usd") or 0) for t in tks), 4),
            "spent_credits": round(sum(float(t.get("credits") or 0) for t in tks), 2)}


@project_hints
def listing(pdir: Path) -> dict:
    rows_ = [row(c) for c in store.all_clips(pdir)]
    pending_usd = sum((r["cost"].get("usd") or 0) for r in rows_ if r["status"] in ("draft", "locked") and "credits" not in r["cost"])
    pending_cr = sum((r["cost"].get("credits") or 0) for r in rows_ if r["status"] in ("draft", "locked"))
    sing_usd = sum((r["cost"].get("usd") or 0) for r in rows_ if r["status"] in ("draft", "locked") and r["kind"] == "sung"
                   and "credits" not in r["cost"])
    lines = [f"{r['id']:<12} {r['kind'] or '':<6} {r['status'] or '':<9} {r['provider'] or '':<10} "
             f"t0 {r['song_t0'] if r['song_t0'] is not None else '-':>7} {r['duration'] or '-':>2}s {r['resolution'] or '':<5} "
             f"takes {r['takes']}" + (f" synced {r['synced']}" if r['synced'] else "")
             + (" OUTCOME UNKNOWN (slop clip poll " + r["id"] + ")" if r["last_take"] == "unknown" else "") for r in rows_]
    lines.append(f"expected for draft+locked: ~${pending_usd:.2f} OpenRouter (+ cover allowance 60% of sung: "
                 f"~${pending_usd + .6 * sing_usd:.2f}), ~{pending_cr:g} Higgsfield credits")
    return {"clips": rows_, "expected_usd": round(pending_usd, 2), "expected_usd_with_covers": round(pending_usd + .6 * sing_usd, 2),
            "expected_credits": pending_cr, "text": "\n".join(lines) if rows_ else "no clips yet: slop clip new SHOT --kind sung|motion"}

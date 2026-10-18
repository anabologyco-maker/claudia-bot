"""`slop render …` — the renderer CLI (router contract: register(subparsers); each step sets func(args) -> dict).

Steps (all resumable / idempotent; --json prints one JSON object):
  info      boot the engine page for the project and report what it loaded (scenes, lyrics, fonts, warnings)
  frames    render every frame (or --from/--to/--every) to render/frames/fNNNNN.jpg (resumable)
  stills    full-resolution frames at --times
  sheet     contact sheet of sampled frames (shot mid-points) -> render/sheet.jpg, with ms/frame (--vertical: 9:16);
            --chapter X: one chapter; --chapter X --review: every shot's first/mid/last frame, each line's first/last
            word, the strongest hits -> render/sheet-<chapter>-review.jpg
  lyrics    the lyric gate: every sung token drawn at its time -> N/N (fails otherwise; --vertical: the 9:16 layout).
            ARCHITECTURE §5 calls this step `lyrics-gate`; the command is `slop render lyrics`.
  encode    frames -> out/master.mp4 (x264 CRF 16, BT.709-tagged, AAC, +faststart), verified with ffprobe;
            --share: the chat copy out/share.mp4 under --max-mib (default 95, under the 100 MB Drive upload limit;
            up to 200): a copy of the current master when it fits, else a two-pass x264 encode
  check     flash check (WCAG 2.3.1, ≤ 3 flashes/s) on out/master.mp4 + history check (frames are pure functions of t);
            --layers: ONLY the density check (every shot's mid-point frame has ≥ 3 ordered layers) -> render/layers.json
            (--vertical: render/layers-vertical.json)
  vertical  the 9:16 cut: re-render at 1080x1920 -> out/vertical.mp4 at full quality (master profile; --from/--to: the
            stretch you post); --every N / --allow-missing: a preview -> out/vertical-draft.mp4 (--method crop: a
            preview -> out/vertical-crop.mp4); the result names the profile it used
  clean     delete the frames (GBs) once out/master.mp4 (and out/vertical.mp4) verify; --keep-master keeps render/frames;
            refused while another `slop job` of the project runs
Long steps (frames, vertical, lyrics, check --layers, sheet, encode) write their progress to $SLOP_PROGRESS_FILE when it
is set (slop/progress.py: {"command", "step", "stage", "done", "total", "pct", "eta_s", "state"}): run them in the
background and read it; the command is over only when "state" is done, stopped or failed ("stage_done" = one stage of
several finished, keep waiting) — `slop job wait ID` is the authoritative end.
Frames, stills, sheets and the vertical cut stop when media or fonts are missing (--allow-missing: placeholders, previews
only); frames drawn from inputs that changed since are discarded and redrawn (render/frames/.inputs.json).
"""
from __future__ import annotations

import argparse
import json

from ..config import SlopError, resolve_project


def _tracked(name: str, steps: int, fn) -> dict:
    """Run one command inside progress.command(): its stages write "stage_done" between them, and only its end writes
    done / stopped / failed to $SLOP_PROGRESS_FILE (slop/progress.py)."""
    from .. import progress
    with progress.command(name, steps) as c:
        r = fn()
        c.ok = bool(r.get("ok", True)) if isinstance(r, dict) else True
        return r


def _common(p: argparse.ArgumentParser) -> None:
    # the root parser owns --project/--json; accepting them after the step too is a convenience (SUPPRESS keeps the root value)
    p.add_argument("--project", "-p", default=argparse.SUPPRESS, help="project name or path")
    p.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="machine-readable JSON on stdout")


def _times(s: str | None) -> list[float] | None:
    if not s:
        return None
    try:
        return [float(x) for x in s.replace(";", ",").split(",") if x.strip()]
    except ValueError as e:
        raise SlopError(f"--times must be comma-separated seconds, e.g. 1.5,3,7.25 (got {s!r})") from e


def _size(s: str | None) -> tuple[int | None, int | None]:
    if not s:
        return None, None
    try:
        w, h = s.lower().split("x")
        return int(w), int(h)
    except ValueError as e:
        raise SlopError(f"--size must be WxH, e.g. 1080x1920 (got {s!r})") from e


def _pairs(s: str | None) -> list[tuple[float, float]] | None:
    if not s:
        return None
    out = []
    for part in s.split(","):
        a, _, b = part.partition(":")
        try:
            out.append((float(a), float(b)))
        except ValueError as e:
            raise SlopError(f"--pairs must be A:B,A:B (seconds; B is checked after A), got {s!r}") from e
    return out


def _size_or_vertical(a) -> tuple[int | None, int | None]:
    if getattr(a, "vertical", False):
        if getattr(a, "size", None):
            raise SlopError("pass --size WxH or --vertical, not both")
        return 1080, 1920
    return _size(getattr(a, "size", None))


def cmd_info(a) -> dict:
    from .frames import media_label, missing_text, probe
    pdir = resolve_project(a.project)
    w, h = _size(a.size)
    spec, info = probe(pdir, w, h, strict=False)
    missing = info.get("missingMedia") or []
    warn = list(info.get("warnings") or spec["warnings"]) + [f"font failed: {f}" for f in info.get("fontsFailed", [])]
    if info.get("depthUnlabelled"):
        warn.append("depth not labelled Depth-Anything-V2-Small (drawn flat): " + ", ".join(info["depthUnlabelled"][:8])
                    + " — re-run `slop edit export` (it stamps depth_model), or set depth_model in plates/picks.json")
    if missing:
        warn.insert(0, missing_text(missing).replace("\n", "\n    "))
    if info.get("page_errors"):
        warn.insert(0, "PAGE ERRORS: " + " | ".join(info["page_errors"][:3]))
    text = (f"{pdir.name}: {info['W']}x{info['H']} @ {info['FPS']} fps, {info.get('duration', 0):.2f}s, {info['scenes']} scenes "
            f"({info.get('shotsRenderer') or 'no renderer'}), {info['lyrics']} lyric lines / {info['tokens']} tokens, "
            f"{info['beats']} beats, {info['sections']} sections, look {info['look']}, data: {', '.join(spec['assets']) or '-'}"
            f"{' + fallbacks ' + ', '.join(spec['fallbacks']) if spec['fallbacks'] else ''}")
    if warn:
        text += "\n" + "\n".join("  ! " + x for x in warn)
    ok = not info.get("page_errors") and info.get("scenes", 0) > 0 and not missing and not info.get("fontsFailed")
    return {"ok": ok, "project": str(pdir), "url": spec["url"], "info": info, "assets": spec["assets"],
            "fallbacks": spec["fallbacks"], "missing_media": [media_label(m["src"]) for m in missing],
            "warnings": warn, "text": text}


def cmd_frames(a) -> dict:
    from .frames import render_frames
    pdir = resolve_project(a.project)
    w, h = _size(a.size)
    return _tracked("render frames", 1, lambda: render_frames(
        pdir, t_from=a.t_from, t_to=a.t_to, every=a.every, workers=a.workers, w=w, h=h, out=a.out, timemap=a.timemap,
        force=a.force, allow_missing=a.allow_missing))


def cmd_stills(a) -> dict:
    from .frames import stills
    pdir = resolve_project(a.project)
    ts = _times(a.times)
    if not ts:
        raise SlopError("pass --times, e.g. --times 1.5,12,30.25")
    w, h = _size(a.size)
    return stills(pdir, ts, out=a.out, w=w, h=h, allow_missing=a.allow_missing)


def cmd_sheet(a) -> dict:
    from .frames import sheet
    pdir = resolve_project(a.project)
    w, h = _size_or_vertical(a)
    return _tracked("render sheet", 1, lambda: sheet(
        pdir, times=_times(a.times), n=a.n, cols=a.cols, tile_w=a.w, out=a.out, w=w, h=h, allow_missing=a.allow_missing,
        chapter=a.chapter, review=a.review))


def cmd_lyrics(a) -> dict:
    from .frames import lyric_gate
    pdir = resolve_project(a.project)
    w, h = _size_or_vertical(a)
    return _tracked("render lyrics", 1, lambda: lyric_gate(pdir, t_from=a.t_from, t_to=a.t_to, workers=a.workers,
                                                           out=a.out, w=w, h=h))


def cmd_encode(a) -> dict:
    from .encode import encode, share
    pdir = resolve_project(a.project)
    if a.share:
        if a.review or a.draft or a.allow_gaps or a.no_audio:
            raise SlopError("--share makes the chat copy from the finished frames (or the master): drop --review / --draft / "
                            "--allow-gaps / --no-audio")
        from .encode import SHARE_DEFAULT_MIB
        return _tracked("render encode --share", 2, lambda: share(
            pdir, vertical=a.vertical, max_mib=SHARE_DEFAULT_MIB if a.max_mib is None else a.max_mib, frames=a.frames,
            out=a.out))
    if a.max_mib is not None:
        raise SlopError("--max-mib goes with --share (the chat copy): slop render encode --share --max-mib 95")
    profile = "review" if a.review else "draft" if a.draft else "master"
    return _tracked("render encode", 1, lambda: encode(pdir, frames=a.frames, out=a.out, profile=profile,
                                                       audio=not a.no_audio, allow_gaps=a.allow_gaps, vertical=a.vertical))


def cmd_check(a) -> dict:
    from . import project as P
    from .flash import flashcheck
    from .frames import default_pairs, history_check
    pdir = resolve_project(a.project)
    if a.layers:
        from .layers import check_layers
        if a.video or a.pairs:
            raise SlopError("--layers checks the storyboard's frames, not a video: drop --video / --pairs")
        w, h = _size_or_vertical(a)
        return _tracked("render check --layers", 1, lambda: check_layers(pdir, workers=a.workers, w=w, h=h))
    res: dict = {}
    ok = True
    lines = []
    if not a.skip_flash:
        from ..util import input_path
        video = input_path(pdir, a.video) if a.video else (pdir / "out" / "master.mp4")   # relative: cwd, else project
        if not video.is_file():
            res["flash"] = {"pass": False, "error": f"no video at {video}"}
            ok = False
            lines.append(f"flash: NOT RUN — {video} missing (run `slop render encode`, or pass --skip-flash)")
        else:
            f = flashcheck(video, a.max, a.area, a.delta)
            res["flash"] = f
            ok &= f["pass"]
            lines.append(f"flash: {'PASS' if f['pass'] else 'FAIL'} — worst {f['worst_per_second']}/s (limit {f['limit']}), "
                         f"{f['flashes']} flashes" + (f", failing seconds {f['fails'][:5]}" if f["fails"] else ""))
    if not a.skip_history:
        pairs = _pairs(a.pairs)
        if not pairs:
            dur = P.project_duration(pdir)
            if not dur:
                raise SlopError("no song duration yet — run `slop analyze` (or add audio/song.wav), or pass --pairs A:B,…")
            pairs = default_pairs(pdir, dur)
        hres = history_check(pdir, pairs)
        res["history"] = hres
        ok &= hres["ok"]
        lines.append("history: " + hres["text"])
    if not res:
        raise SlopError("nothing to check: drop --skip-flash or --skip-history")
    out = pdir / "render" / "check.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    return {"ok": ok, **res, "report": str(out), "text": "\n".join(lines)}


def cmd_vertical(a) -> dict:
    from .vertical import vertical
    pdir = resolve_project(a.project)
    return _tracked("render vertical", 1 if a.skip_encode else 2, lambda: vertical(
        pdir, method=a.method, workers=a.workers, t_from=a.t_from, t_to=a.t_to, every=a.every, skip_encode=a.skip_encode,
        audio=not a.no_audio, allow_missing=a.allow_missing))


def cmd_clean(a) -> dict:
    from .clean import clean
    return clean(resolve_project(a.project), keep_master=a.keep_master, dry=a.dry)


def _no_step(a) -> dict:
    raise SlopError("choose a step: slop render info|frames|stills|sheet|lyrics|encode|check|vertical|clean "
                    "(typical order: info → sheet → check --layers → lyrics → frames → encode → check → vertical → "
                    "encode --share → clean)")


def register(subparsers) -> None:
    from pathlib import Path
    p = subparsers.add_parser("render", help="render frames/sheets, lyric gate, encode the master, flash/history checks, 9:16 cut",
                              description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.set_defaults(func=_no_step)
    sp = p.add_subparsers(dest="render_step", metavar="STEP")

    s = sp.add_parser("info", help="boot the engine page and report what it loaded")
    _common(s)
    s.add_argument("--size", help="WxH (default project.json size)")
    s.set_defaults(func=cmd_info)

    s = sp.add_parser("frames", help="render frames to render/frames (resumable)")
    _common(s)
    s.add_argument("--from", dest="t_from", type=float, help="start, seconds (default 0)")
    s.add_argument("--to", dest="t_to", type=float, help="end, seconds (default: song end)")
    s.add_argument("--every", type=int, default=1, help="render every Nth frame (drafts / motion sampling)")
    s.add_argument("--workers", type=int, help="parallel browsers (default min(4, cpus/2), capped by the free memory: "
                                               "~3.5 GiB each, 3 GiB kept for Grok's browser)")
    s.add_argument("--size", help="WxH (default project.json size; frames go to render/frames-WxH)")
    s.add_argument("--out", type=Path, help="frames directory (default render/frames)")
    s.add_argument("--timemap", action="store_true", help="map final-song time through edit/timemap.json")
    s.add_argument("--force", action="store_true", help="redraw frames that already exist in the range, in place "
                                                         "(never delete them first: a crash would leave holes)")
    s.add_argument("--allow-missing", action="store_true",
                   help="draw placeholders for missing media/fonts instead of stopping (previews only; encode refuses a master)")
    s.set_defaults(func=cmd_frames)

    s = sp.add_parser("stills", help="full-resolution frames at given times")
    _common(s)
    s.add_argument("--times", required=True, help="comma-separated seconds")
    s.add_argument("--size", help="WxH")
    s.add_argument("--out", type=Path, help="directory (default render/stills)")
    s.add_argument("--allow-missing", action="store_true",
                   help="draw placeholders for missing media/fonts instead of stopping (previews only; encode refuses a master)")
    s.set_defaults(func=cmd_stills)

    s = sp.add_parser("sheet", help="contact sheet of sampled frames (default: every shot's mid-point)")
    _common(s)
    s.add_argument("--times", help="comma-separated seconds (default: shot mid-points)")
    s.add_argument("--n", type=int, help="N evenly spaced frames instead of shot mid-points")
    s.add_argument("--cols", type=int, help="tiles per row (default 4; 6 with --review)")
    s.add_argument("--w", type=int, help="tile width px (default 480; 320 with --review)")
    s.add_argument("--chapter", help="only this chapter's shots: its id (C3), name (chorus1) or number")
    s.add_argument("--review", action="store_true",
                   help="with --chapter: the review sheet — every shot's first/mid/last frame, each line's first/last word, "
                        "the strongest hits -> render/sheet-<chapter>-review.jpg")
    s.add_argument("--size", help="WxH (default project.json size)")
    s.add_argument("--vertical", action="store_true", help="the 9:16 layout (1080x1920) -> render/sheet-vertical.jpg")
    s.add_argument("--out", type=Path, help="file (default render/sheet.jpg)")
    s.add_argument("--allow-missing", action="store_true",
                   help="draw placeholders for missing media/fonts instead of stopping (previews only; encode refuses a master)")
    s.set_defaults(func=cmd_sheet)

    s = sp.add_parser("lyrics", help="lyric gate: every sung token drawn at its time (N/N)")
    _common(s)
    s.add_argument("--from", dest="t_from", type=float)
    s.add_argument("--to", dest="t_to", type=float)
    s.add_argument("--workers", type=int)
    s.add_argument("--size", help="WxH (default project.json size)")
    s.add_argument("--vertical", action="store_true",
                   help="gate the 9:16 layout (1080x1920) -> render/lyrics-report-vertical.json")
    s.add_argument("--out", type=Path, help="report (default render/lyrics-report.json)")
    s.set_defaults(func=cmd_lyrics)

    s = sp.add_parser("encode", help="frames -> out/master.mp4 (CRF 16, BT.709 tags, audio) + ffprobe verify")
    _common(s)
    s.add_argument("--frames", type=Path, help="frames directory (default render/frames)")
    s.add_argument("--out", type=Path, help="output file (default out/master.mp4)")
    s.add_argument("--review", action="store_true", help="review copy: CRF 20, maxrate 8M -> out/review.mp4")
    s.add_argument("--draft", action="store_true", help="quick preview: CRF 23 veryfast, gaps allowed -> out/draft.mp4")
    s.add_argument("--vertical", action="store_true", help="encode render/frames-vertical -> out/vertical.mp4")
    s.add_argument("--allow-gaps", action="store_true", help="hold frames over missing ones (previews only)")
    s.add_argument("--no-audio", action="store_true", help="silent encode (no audio/song.wav)")
    s.add_argument("--share", action="store_true",
                   help="the chat copy -> out/share.mp4 (--vertical: out/share-vertical.mp4) under --max-mib (Drive "
                        "takes ≤ 100 MB): a copy of the current master when it fits, else two-pass x264 with the "
                        "master colour tags; ffprobe-verified incl. size")
    s.add_argument("--max-mib", type=float, default=None, metavar="MIB",
                   help="--share size target in MiB (default 95: under the 100 MB Drive upload limit; at most 200)")
    s.set_defaults(func=cmd_encode)

    s = sp.add_parser("check", help="flash check on out/master.mp4 + history check")
    _common(s)
    s.add_argument("--video", type=Path, help="video to flash-check (default out/master.mp4)")
    s.add_argument("--pairs", help="history pairs A:B,… (B rendered fresh vs after A; default: 3 spread pairs)")
    s.add_argument("--skip-flash", action="store_true")
    s.add_argument("--skip-history", action="store_true")
    s.add_argument("--max", type=int, default=3, help="max flashes per second (WCAG 2.3.1: 3)")
    s.add_argument("--area", type=float, default=.25, help="min share of the frame a flash covers")
    s.add_argument("--delta", type=float, default=.10, help="min relative-luminance change of a flash")
    s.add_argument("--layers", action="store_true",
                   help="ONLY the layer check: every shot's mid-point frame needs ≥ 3 ordered layers (media + lyric + "
                        "chrome + annotation/graphic) -> render/layers.json; no master needed (run it before frames)")
    s.add_argument("--workers", type=int, help="--layers: parallel browsers (default min(4, cpus/2))")
    s.add_argument("--size", help="--layers: WxH (default project.json size)")
    s.add_argument("--vertical", action="store_true",
                   help="--layers: check the 9:16 layout (1080x1920) -> render/layers-vertical.json")
    s.set_defaults(func=cmd_check)

    s = sp.add_parser("clean", help="free the disk: delete the frames once out/master.mp4 (and out/vertical.mp4) verify")
    _common(s)
    s.add_argument("--keep-master", action="store_true",
                   help="keep render/frames (the master's frames: re-encode later without re-rendering)")
    s.add_argument("--dry", action="store_true", help="only list what would be deleted")
    s.set_defaults(func=cmd_clean)

    s = sp.add_parser("vertical", help="the 9:16 cut (1080x1920) -> out/vertical.mp4")
    _common(s)
    s.add_argument("--method", choices=["rerender", "crop"], default="rerender",
                   help="rerender (default; the engine lays out for portrait -> out/vertical.mp4) or crop (a fast PREVIEW "
                        "cropped from the master frames -> out/vertical-crop.mp4, draft quality)")
    s.add_argument("--workers", type=int)
    s.add_argument("--from", dest="t_from", type=float,
                   help="start of the stretch to post, seconds (full quality -> out/vertical.mp4; default 0)")
    s.add_argument("--to", dest="t_to", type=float, help="end of the stretch, seconds (default: song end)")
    s.add_argument("--every", type=int, default=1, help="every Nth frame: a sampled PREVIEW (draft -> out/vertical-draft.mp4)")
    s.add_argument("--skip-encode", action="store_true")
    s.add_argument("--no-audio", action="store_true")
    s.add_argument("--allow-missing", action="store_true",
                   help="draw placeholders for missing media/fonts instead of stopping (previews only; encode refuses a master)")
    s.set_defaults(func=cmd_vertical)

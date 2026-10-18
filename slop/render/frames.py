"""Frame rendering with N parallel browsers, stills, contact sheets, the lyric gate and the history check.

Safety nets (each one exists because the quiet failure shipped a bad cut at least once):
- media preflight: before anything is drawn, every media file the film declares (plates, clip first/last frames,
  declared depth maps and mattes — ENGINE.checkMedia) is decoded; a missing file stops `frames`, `stills`, `sheet` and
  `vertical` with the list and the fix, and so does a font that fails to load (`--allow-missing` draws placeholders:
  previews only). A frame that still asks for missing media at draw time is NOT written (it stays missing, so the
  re-run after the fix draws it);
- stale frames: <frames dir>/.inputs.json records what the frames were drawn from (project.inputs_fingerprint: engine
  code, project.json, the project's data files, the injected fallback JSON, media sizes/mtimes, size, renderer, time
  map). When any of it changed, `slop render frames` discards the stale frames and draws them again (the reference
  pipeline rendered every cut into a new versioned folder instead); `slop render encode` refuses stale frames;
- --timemap renders the FINAL song (time-map end, else the audio length) and a --to past the end is clipped with a
  warning;
- the frame range is [round(from·fps), ceil(to·fps)) — the original used round(to·fps), which dropped the last partial
  frame of a song whose length is not a whole number of frames.
"""
from __future__ import annotations

import concurrent.futures as cf
import io
import json
import os
import sys
import threading
import time
from pathlib import Path

from .. import progress
from ..config import SlopError
from ..util import no_picture_text, shots_without_picture
from . import project as P
from .browser import EnginePage, apply_env

RECYCLE_EVERY = 200          # a fresh page every 200 frames: bounded memory on long runs
GIB_PER_WORKER = 3.5         # Chromium per rendering worker on real films (3-4 GiB seen on a 15 GiB box)
RESERVE_GIB = 3.0            # left free for Grok's own browser and the rest of the box
STALL_S = float(os.environ.get("SLOP_RENDER_STALL_S") or 300)   # no frame for this long: a worker died
JPEG_Q = .95
FIX_MEDIA = ("Fix: run `slop edit export` (it rewrites engine/assets/plates.js and clips.js from plates/picks.json and "
             "the clip takes), check that plates/picks.json and edit/edl.json name files that exist, then run this again")


def _sync_playwright():
    apply_env()                  # PLAYWRIGHT_BROWSERS_PATH etc. must be set BEFORE the driver starts
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise SlopError("playwright is not installed in this Python — run bin/setup.sh "
                        "(or: pip install playwright==1.60.0 && python -m playwright install chromium)") from e
    return sync_playwright


def _cg_reclaimable(cg: Path) -> int:
    """Bytes of page cache in a cgroup that the kernel can reclaim (memory.stat active_file + inactive_file: file
    pages; tmpfs/shm pages are swap-backed and sit on the anon lists, so they are not counted). 0 when unreadable."""
    try:
        st = dict(line.split(None, 1) for line in (cg / "memory.stat").read_text().splitlines() if " " in line)
        return max(0, int(st.get("active_file", 0)) + int(st.get("inactive_file", 0)))
    except (OSError, ValueError):
        return 0


def _avail_gib(proc: Path = Path("/proc"), cgroot: Path = Path("/sys/fs/cgroup")) -> float | None:
    """Memory this process may still use: /proc/meminfo MemAvailable, lowered to what the tightest cgroup limit on
    the way up (memory.max of this cgroup and its parents) leaves — a container or `systemd-run -p MemoryMax=…` sees
    the host's meminfo. The cgroup's memory.current counts page cache (frames, stems and mp4s fill it over a session);
    that cache is reclaimable, so it is not counted as used (measured under systemd-run MemoryMax=8G: after writing a
    4 GiB file, memory.current was 4.12 GiB, 4.0 GiB of it inactive_file; max − current left 3.87 GiB = 2 workers,
    this rule 7.87 GiB = 4 workers)."""
    gib = None
    try:
        for line in (proc / "meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                gib = int(line.split()[1]) / 1024 / 1024
                break
    except (OSError, ValueError, IndexError):
        return None
    try:
        rel = next((line[3:] for line in (proc / "self" / "cgroup").read_text().splitlines() if line.startswith("0::")),
                   None)                                      # cgroup v2 ("0::/path"); v1 has no single answer
    except OSError:
        rel = None
    if rel is None:
        return gib
    root = Path(cgroot)
    cg = root / rel.strip().lstrip("/")
    for d in [cg, *cg.parents]:
        if root != d and root not in d.parents:
            break
        try:
            mx = (d / "memory.max").read_text().strip()
            if mx == "max":
                continue
            used = int((d / "memory.current").read_text().strip()) - _cg_reclaimable(d)
            left = (int(mx) - max(0, used)) / 1024 ** 3
            gib = left if gib is None else min(gib, left)
        except (OSError, ValueError):
            continue
    return gib


def _cpus() -> int:
    """CPUs this process may run on (taskset / cgroup cpusets), not the host's count."""
    f = getattr(os, "process_cpu_count", None)
    try:
        return int((f() if f else len(os.sched_getaffinity(0))) or os.cpu_count() or 2)
    except (AttributeError, OSError):
        return os.cpu_count() or 2


def default_workers(n_frames: int | None = None) -> int:
    w = max(1, min(4, _cpus() // 2))
    cap = memory_workers()
    if cap is not None:
        w = max(1, min(w, cap))
    if n_frames is not None:
        w = max(1, min(w, n_frames))
    return w


def memory_workers() -> int | None:
    """How many rendering browsers the free memory carries, after the reserve for Grok's browser (None: unknown)."""
    gib = _avail_gib()
    return None if gib is None else max(1, int(max(0.0, gib - RESERVE_GIB) // GIB_PER_WORKER))


def _descendants(root: int) -> list[int]:
    """Every live process under root (Linux /proc; elsewhere none)."""
    kids: dict[int, list[int]] = {}
    for st in Path("/proc").glob("[0-9]*/stat"):
        try:
            s = st.read_text()
            ppid = int(s[s.rindex(")") + 2:].split()[1])
            kids.setdefault(ppid, []).append(int(st.parent.name))
        except (OSError, ValueError, IndexError):
            continue
    out, todo = [], [root]
    while todo:
        for c in kids.get(todo.pop(), []):
            out.append(c)
            todo.append(c)
    return out


def _kill_descendants() -> int:
    import signal
    n = 0
    for pid in _descendants(os.getpid()):
        try:
            os.kill(pid, signal.SIGKILL)
            n += 1
        except OSError:
            pass
    return n


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


# ------------------------------------------------------------------------------------------- missing media ------
def media_label(src: str) -> str:
    """'file:///…/plates/a.jpg' -> the local path; 'clip:NAME' stays as it is."""
    q = P.url_path(src, Path("."))
    return str(q) if q is not None and str(src).lower().startswith("file:") else str(src)


def missing_text(missing: list, fonts: list | None = None) -> str:
    """One readable block: the missing media (with why) and failed fonts, and what to do."""
    lines = []
    if missing:
        lines.append(f"{len(missing)} media file(s) the film uses are missing — it would render placeholders:")
        for m in missing[:12]:
            src, why = (m.get("src"), m.get("why")) if isinstance(m, dict) else (m, "")
            lines.append(f"  {media_label(src)}" + (f"  ({why})" if why else ""))
        if len(missing) > 12:
            lines.append(f"  … and {len(missing) - 12} more")
        lines.append(FIX_MEDIA)
    if fonts:
        lines.append(f"font file(s) failed to load: {', '.join(map(str, fonts[:8]))} — run bin/setup.sh (it reinstalls the "
                     "toolkit fonts) or fix project.json font_files")
    return "\n".join(lines)


def _gate_media(info: dict, missing: list, allow_missing: bool, verb: str) -> list[str]:
    """Raise unless allowed; returns the warnings to report when allowed."""
    fonts = info.get("fontsFailed") or []
    if not (missing or fonts):
        return []
    msg = missing_text(missing, fonts)
    if not allow_missing:
        raise SlopError(msg + f"\n(or pass --allow-missing to {verb} with placeholders — previews only, never a master)")
    return ["--allow-missing: " + msg.replace("\n", " | ")]


def probe(pdir: Path, w: int | None = None, h: int | None = None, strict: bool = True,
          allow_missing: bool = False) -> tuple[dict, dict]:
    """Boot the page once and check its media: (spec, info). strict: SlopError on page exceptions, an empty timeline,
    missing media or fonts (unless allow_missing). info["missingMedia"] lists what is missing either way."""
    spec = P.page_spec(pdir, w, h)
    with _sync_playwright()() as p:
        with EnginePage(p, spec) as pg:
            info = pg.info()
            info["missingMedia"] = pg.check_media()
            info["page_errors"] = list(pg.errors)
    if strict and info.get("page_errors"):
        raise SlopError("the engine page threw errors (fix them before rendering): " + " | ".join(info["page_errors"][:3]))
    if strict and not info.get("scenes"):
        raise SlopError("the engine page has no scenes — the project has no storyboard, lyrics or duration yet "
                        "(run `slop analyze` and `slop board draft`, then `slop edit export`)")
    info["warnings"] = list(spec["warnings"]) + device_warnings(info)
    blank = shots_without_picture(pdir)
    if blank:
        info["warnings"].insert(0, no_picture_text(blank))
    if strict:
        info["warnings"] += _gate_media(info, info["missingMedia"], allow_missing, "render")
    return spec, info


def device_warnings(info: dict) -> list[str]:
    """The device library's plan repairs and boot dry-run throws (ENGINE.info().deviceWarnings/deviceErrors), as
    render warnings (integration: they were only readable inside info before)."""
    return ([f"device plan: {x}" for x in (info.get("deviceWarnings") or [])]
            + [f"DEVICE ERROR: {x}" for x in (info.get("deviceErrors") or [])])


def frames_dir(pdir: Path, w: int, h: int, vertical: bool = False) -> Path:
    if vertical:
        return pdir / "render" / "frames-vertical"
    pw, ph = P.project_size(pdir)
    return pdir / "render" / ("frames" if (w, h) == (pw, ph) else f"frames-{w}x{h}")


def frame_files(d: Path) -> list[Path]:
    import re
    return [f for f in Path(d).glob("f*.jpg") if re.fullmatch(r"f\d{5,}\.jpg", f.name)] if Path(d).is_dir() else []


def load_timemap(pdir: Path):
    for rel in ("edit/timemap.json", "timemap.json"):
        f = pdir / rel
        if f.is_file():
            seg = json.loads(f.read_text(encoding="utf-8")).get("segments") or []
            if not seg:
                break

            def tl(t: float, seg=seg) -> float:
                s = next((s for s in seg if s[0] <= t < s[1]), seg[-1])
                return s[2] + (t - s[0]) * (s[3] - s[2]) / (s[1] - s[0])
            return tl
    raise SlopError("--timemap needs edit/timemap.json {\"segments\": [[new0, new1, old0, old1], …]}")


def refresh_stale(pdir: Path, outdir: Path, fp: dict) -> str:
    """Discard frames drawn from other inputs (or with no record) and record `fp`; returns the note ('' if fresh)."""
    prev = P.read_fingerprint(outdir)
    existing = frame_files(outdir)
    note = ""
    if existing and (prev is None or prev.get("hash") != fp["hash"]):
        changed = P.fingerprint_changes(prev, fp)
        for f in existing:
            f.unlink(missing_ok=True)
        note = (f"inputs changed since the {len(existing)} frames in {outdir.name}/ were drawn "
                f"({', '.join(changed[:6])}{' …' if len(changed) > 6 else ''}): discarded them, drawing again")
        _log(note)
    elif prev is not None and prev.get("placeholders"):
        fp["placeholders"] = True                     # frames drawn over missing media are still in there
    P.write_fingerprint(outdir, fp)
    return note


def render_frames(pdir: Path, *, t_from: float | None = None, t_to: float | None = None, every: int = 1,
                  workers: int | None = None, w: int | None = None, h: int | None = None, out: Path | None = None,
                  vertical: bool = False, timemap: bool = False, force: bool = False, allow_missing: bool = False) -> dict:
    spec, info = probe(pdir, w, h, allow_missing=allow_missing)
    fps = float(spec["fps"])
    warns = list(info["warnings"])
    dur = float(info.get("duration") or 0) or (P.project_duration(pdir) or 0)
    if timemap:
        dur = P.render_duration(pdir, True) or dur          # --from/--to are FINAL-song times
    if dur <= 0:
        raise SlopError("unknown song duration: add analysis/beats.json (slop analyze) or audio/song.wav")
    a = 0.0 if t_from is None else max(0.0, float(t_from))
    b = dur if t_to is None else min(float(t_to), dur)
    if t_to is not None and float(t_to) > dur + 1e-6:
        warns.append(f"--to {float(t_to):g} is past the end of the {'final song (time map)' if timemap else 'song'} "
                     f"({dur:.3f} s): rendering to {dur:.3f} s")
    if b <= a:
        raise SlopError(f"empty range: --from {a:g} --to {b:g} (the song is {dur:.3f} s long)")
    every = max(1, int(every or 1))
    outdir = Path(out) if out else frames_dir(pdir, spec["w"], spec["h"], vertical)
    outdir.mkdir(parents=True, exist_ok=True)
    fp = P.inputs_fingerprint(pdir, spec, timemap=timemap)
    fp["duration"] = round(dur, 6)
    if allow_missing and (info.get("missingMedia") or info.get("fontsFailed")):
        fp["placeholders"] = True                     # encode refuses a master from these frames
    stale = refresh_stale(pdir, outdir, fp)
    if stale:
        warns.append(stale)
    span = (int(round(a * fps)), P.frame_count(b, fps))     # [first, end) frame indices of the range
    allidx = list(range(span[0], span[1], every))
    redraw = outdir / ".redraw-incomplete"           # a --force run that has not finished: encode refuses
    if force:                                         # frames are replaced one by one, never deleted first: a crash
        redraw.write_text(json.dumps({"span": list(span), "every": every}))   # leaves whole (older) frames, no holes
        todo = list(allidx)
    else:
        todo = [i for i in allidx if not (outdir / f"f{i:05d}.jpg").exists()]
    tl = load_timemap(pdir) if timemap else (lambda t: t)
    nw = workers or default_workers(len(todo))
    cap = memory_workers()
    if workers and cap is not None and workers > cap:
        warns.append(f"--workers {workers} would need about {workers * GIB_PER_WORKER:.0f} GiB; the free memory "
                     f"carries {cap} (with {RESERVE_GIB:g} GiB kept for Grok's browser): using {cap}")
        nw = cap
    nw = max(1, min(nw, max(1, len(todo))))
    try:
        os.nice(10)                                   # renders yield to Grok's browser and the relay
    except (AttributeError, OSError):
        pass
    _log(f"render: {len(todo)} frames to draw ({len(allidx) - len(todo)} already done) with {nw} worker(s) -> {outdir}")
    chunks = [todo[k::nw] for k in range(nw)]
    failed: list[dict] = []
    missing_seen: set[str] = set()
    lock = threading.Lock()
    last = [time.monotonic()]                         # when the last frame landed (the watchdog reads it)
    sync_playwright = _sync_playwright()
    stage = f"render {'vertical ' if spec['h'] > spec['w'] else ''}frames"
    prog = progress.Counter(len(allidx), stage, start=len(allidx) - len(todo),
                            msg=f"{stage}: {len(todo)} to draw with {nw} worker(s) -> {outdir}")

    def work(k_ch):
        k, ch = k_ch
        done = 0
        if not ch:
            return 0
        with sync_playwright() as p:
            pg = EnginePage(p, spec)
            try:
                for n, i in enumerate(ch):
                    if n and n % RECYCLE_EVERY == 0:
                        pg.reopen()
                    data, miss = None, []
                    for attempt in (0, 1):           # one retry on a fresh page; a frame that fails twice stays missing
                        try:
                            data, miss = pg.frame_checked(tl(i / fps), JPEG_Q)
                            break
                        except Exception as e:  # noqa: BLE001 — retried, then reported
                            _log(f"[frame {i}] {str(e)[:160]} — {'relaunching' if attempt == 0 else 'giving up'}")
                            try:
                                pg.reopen()
                            except Exception as e2:  # noqa: BLE001
                                _log(f"[frame {i}] relaunch failed: {str(e2)[:160]}")
                    if data is None:
                        with lock:
                            failed.append({"frame": i, "t": round(i / fps, 3)})
                        continue
                    if miss:
                        with lock:
                            missing_seen.update(miss)
                    if miss and not allow_missing:   # a placeholder frame is never written
                        with lock:
                            failed.append({"frame": i, "t": round(i / fps, 3), "missing": [media_label(m) for m in miss[:3]]})
                        continue
                    tmp = outdir / f"f{i:05d}.jpg.tmp"
                    tmp.write_bytes(data)
                    os.replace(tmp, outdir / f"f{i:05d}.jpg")
                    last[0] = time.monotonic()
                    done += 1
                    prog.add(1, f"{stage}: frame f{i:05d} ({i / fps:.2f} s)")
                    if done % 100 == 0:
                        _log(f"worker {k}: {done}/{len(ch)} · {time.strftime('%H:%M:%S')}")
            finally:
                pg.close()
        return done

    t0 = time.monotonic()
    last[0] = t0
    ex = cf.ThreadPoolExecutor(nw)
    try:
        futs = [ex.submit(work, kc) for kc in enumerate(chunks)]
        while True:                                   # a watchdog: a worker whose browser was killed (memory) can
            done_f, pending = cf.wait(futs, timeout=5)  # block forever; no frame for STALL_S fails the render instead
            if not pending:
                break
            if time.monotonic() - last[0] > STALL_S:
                killed = _kill_descendants()
                ex.shutdown(wait=False, cancel_futures=True)
                raise SlopError(f"render stalled: no frame for {STALL_S:.0f} s (a worker or its browser died, most "
                                f"often for memory; {killed} process(es) stopped). The frames drawn so far are kept: "
                                f"re-run the same command to resume, with fewer --workers")
        n = sum(f.result() for f in futs)
        ex.shutdown(wait=True)
    finally:
        prog.finish()
    el = time.monotonic() - t0
    if allow_missing and missing_seen and not fp.get("placeholders"):
        fp["placeholders"] = True
        P.write_fingerprint(outdir, fp)
    ms = round(el / max(n, 1) * 1000)
    have = sum(1 for i in allidx if (outdir / f"f{i:05d}.jpg").exists())
    ok = not failed and have == len(allidx)
    if ok:
        redraw.unlink(missing_ok=True)
    text = (f"{have}/{len(allidx)} frames in {outdir} ({n} new, {ms} ms/frame effective, {nw} workers)"
            + ("" if ok else f" — {len(failed)} failed: re-run the same command to retry them (resumable)"))
    if missing_seen:
        text += "\n" + missing_text(sorted(missing_seen)) + ("\n(drawn as placeholders: --allow-missing — previews only)"
                                                            if allow_missing else "\n(the frames that need them were not written)")
    if warns:
        text += "\n" + "\n".join("  ! " + x for x in warns[:8])
    return {"ok": ok, "frames_dir": str(outdir), "rendered": n, "skipped": len(allidx) - len(todo), "total": len(allidx),
            "complete": have == len(allidx), "failed": failed[:50], "workers": nw, "ms_per_frame_effective": ms,
            "range": [round(a, 3), round(b, 3)], "span": list(span), "every": every, "size": [spec["w"], spec["h"]],
            "duration": dur,
            "stale_discarded": bool(stale), "missing_media": sorted(media_label(m) for m in missing_seen),
            "warnings": warns + [c for c in info.get("console", []) if "[device]" in c][:10], "text": text}


def stills(pdir: Path, times: list[float], out: Path | None = None, w: int | None = None, h: int | None = None,
           allow_missing: bool = False) -> dict:
    spec = P.page_spec(pdir, w, h)
    outdir = Path(out) if out else pdir / "render" / "stills"
    outdir.mkdir(parents=True, exist_ok=True)
    files, ms, skipped = [], [], []
    with _sync_playwright()() as p:
        with EnginePage(p, spec) as pg:
            info = pg.info()
            warns = _gate_media(info, pg.check_media(), allow_missing, "render stills")
            for t in times:
                t0 = time.monotonic()
                data, miss = pg.frame_checked(t, .94)
                ms.append(int((time.monotonic() - t0) * 1000))
                if miss and not allow_missing:
                    skipped.append({"t": t, "missing": [media_label(m) for m in miss[:3]]})
                    continue
                f = outdir / f"t{t:08.3f}.jpg"
                f.write_bytes(data)
                files.append(str(f))
            errs = list(pg.errors)
    text = f"{len(files)} stills in {outdir} (ms/frame {ms})" + (f" — page errors: {errs[:2]}" if errs else "")
    if skipped:
        text += "\n" + missing_text(sorted({m for s in skipped for m in s["missing"]})) + "\n(those stills were not written)"
    return {"ok": not errs and not skipped, "files": files, "ms_per_frame": ms, "page_errors": errs[:5], "skipped": skipped,
            "warnings": spec["warnings"] + warns, "text": text}


def _sheet_times(pdir: Path, info: dict, n: int | None) -> list[float]:
    have = P.asset_files(pdir)
    shots = None
    if "shots" in have:
        shots = P.read_js_asset(have["shots"])
    if shots is None:
        shots = P._read_json(pdir / "board" / "shots.json")
    lst = (shots or {}).get("shots", []) if isinstance(shots, dict) else (shots or [])
    mids = [round((float(s["t0"]) + float(s["t1"])) / 2, 3) for s in lst if isinstance(s, dict) and "t0" in s and "t1" in s]
    if mids and not n:
        if len(mids) > 48:
            step = len(mids) / 48
            mids = [mids[int(k * step)] for k in range(48)]
        return mids
    dur = float(info.get("duration") or 0) or (P.project_duration(pdir) or 0)
    if dur <= 0:
        raise SlopError("no song duration yet — run `slop analyze` (or add audio/song.wav), or pass --times 1.0,2.5,…")
    n = n or 12
    return [round(dur * (k + .5) / n, 3) for k in range(n)]


def _suffix(pdir: Path, w: int, h: int) -> str:
    """'' at the project size, '-vertical' at 1080x1920, else '-WxH' (output names for other sizes)."""
    if (w, h) == P.project_size(pdir):
        return ""
    return "-vertical" if (w, h) == (1080, 1920) else f"-{w}x{h}"


def sheet(pdir: Path, times: list[float] | None = None, n: int | None = None, cols: int | None = None,
          tile_w: int | None = None, out: Path | None = None, w: int | None = None, h: int | None = None,
          allow_missing: bool = False, chapter: str | None = None, review: bool = False) -> dict:
    """A contact sheet. Default: every shot's mid-point. chapter: that chapter's shots only; review: the chapter's
    review sheet (shot first/mid/last frames, each line's first/last word, the strongest hits — slop/render/chapter.py)."""
    from PIL import Image, ImageDraw
    if review and not chapter:
        raise SlopError("--review needs --chapter X (the chapter to review: its id, name or number)")
    if chapter and (times or n):
        raise SlopError("pass --chapter or --times / --n, not both")
    spec = P.page_spec(pdir, w, h)
    cols = cols or (6 if review else 4)
    tile_w = tile_w or (320 if review else 480)
    tile_h = max(1, round(tile_w * spec["h"] / spec["w"]))
    label_h = 32 if chapter else 18
    ms, skipped = [], []
    labels: list[str] = []
    ch = None
    with _sync_playwright()() as p:
        with EnginePage(p, spec) as pg:
            info = pg.info()
            warns = _gate_media(info, pg.check_media(), allow_missing, "draw the sheet")
            if chapter:
                from .chapter import chapter_times
                ch, picks = chapter_times(pdir, chapter, review, float(spec["fps"]),
                                          lyr=pg.page.evaluate("() => window.LYR || []"))
                ts, labels = [t for t, _ in picks], [lab for _, lab in picks]
            else:
                ts = times or _sheet_times(pdir, info, n)
            if not ts:
                raise SlopError("no times to sample: pass --times 1.0,2.5,…")
            prog = progress.Counter(len(ts), "render sheet", msg=f"render sheet: {len(ts)} frames")
            cols = max(1, min(cols, len(ts)))
            rows = (len(ts) + cols - 1) // cols
            img = Image.new("RGB", (cols * tile_w, rows * (tile_h + label_h)), (17, 17, 17))
            d = ImageDraw.Draw(img)
            try:                                     # a crash still ends the progress record (never left "running")
                for k, t in enumerate(ts):
                    t0 = time.monotonic()
                    try:
                        data, miss = pg.frame_checked(t, .9)
                    except Exception as e:  # noqa: BLE001 — a crashed page: one retry on a fresh browser
                        _log(f"[sheet] t={t:.2f}: {str(e)[:160]} — relaunching")
                        pg.reopen()
                        data, miss = pg.frame_checked(t, .9)
                    ms.append(int((time.monotonic() - t0) * 1000))
                    if miss and not allow_missing:
                        skipped.extend(miss)
                    fr = Image.open(io.BytesIO(data)).convert("RGB")
                    name = pg.page.evaluate("(t) => window.sceneAt(t)", float(t)) or ""
                    x, y = (k % cols) * tile_w, (k // cols) * (tile_h + label_h)
                    img.paste(fr.resize((tile_w, tile_h)), (x, y))
                    d.text((x + 6, y + tile_h + 3), f"{t:7.2f}s  {name}" + ("  [MISSING MEDIA]" if miss else ""),
                           fill=(230, 230, 225))
                    if labels:
                        d.text((x + 6, y + tile_h + 17), labels[k][: max(8, tile_w // 6)], fill=(217, 119, 87))
                    prog.add(1)
            finally:
                prog.finish()
            errs = list(pg.errors)
    if ch is not None:
        cid = "".join(c if c.isalnum() or c in "-_" else "-" for c in str(ch.get("id") or ch["index"]))
        default = f"sheet-{cid}{'-review' if review else ''}{_suffix(pdir, spec['w'], spec['h'])}.jpg"
    else:
        default = f"sheet{_suffix(pdir, spec['w'], spec['h'])}.jpg"
    outf = Path(out) if out else pdir / "render" / default
    outf.parent.mkdir(parents=True, exist_ok=True)
    img.save(outf, quality=88)
    med = sorted(ms)[len(ms) // 2] if ms else 0
    text = (f"contact sheet {outf} ({len(ts)} frames at {spec['w']}x{spec['h']}, median {med} ms/frame; target ≤ 1500)"
            + (f" — page errors: {errs[:2]}" if errs else ""))
    if skipped:
        text += "\n" + missing_text(sorted(set(skipped)))
    if ch is not None:
        text += (f"\nchapter {ch.get('id') or ch['index']} ({ch.get('name', '')}, {float(ch.get('t0', 0)):.2f}–"
                 f"{float(ch.get('t1', 0)):.2f} s)" + (": shot first/mid/last frames, each line's first/last word, the "
                                                      "strongest hits — look at every tile" if review else ""))
    return {"ok": not errs and not skipped, "sheet": str(outf), "times": ts, "labels": labels, "size": [spec["w"], spec["h"]],
            "ms_per_frame": ms, "ms_median": med, "page_errors": errs[:5], "warnings": spec["warnings"] + warns,
            "chapter": ({k: ch.get(k) for k in ("id", "name", "t0", "t1")} if ch is not None else None), "review": review,
            "text": text}


def lyric_gate(pdir: Path, t_from: float | None = None, t_to: float | None = None, workers: int | None = None,
               out: Path | None = None, w: int | None = None, h: int | None = None) -> dict:
    """Every sung token must be drawn (KIN.mark) at t0 + clamp((t1−t0)/2, .03, .12). Prints N/N; fails otherwise.
    Words analysis/words.json could not time (t0 null) count as missing when the lyrics come from words.json."""
    spec = P.page_spec(pdir, w, h)
    sync_playwright = _sync_playwright()
    with sync_playwright() as p:
        with EnginePage(p, spec) as pg:
            toks = pg.lyric_tokens()
            errs = list(pg.errors)
    if errs:
        raise SlopError("the engine page threw errors: " + " | ".join(errs[:3]))
    a = -1e9 if t_from is None else float(t_from)
    b = 1e9 if t_to is None else float(t_to)
    toks = [tk for tk in toks if a <= tk["t0"] < b]
    untimed = [] if (t_from is not None or t_to is not None) else [
        {"line": u["line"], "token": u["i"], "txt": u["w"], "t0": None, "t": None,
         "why": "no t0: alignment failed — ear-check and fix analysis/words.json"} for u in spec.get("untimed", [])]
    if not toks and not untimed:
        return {"ok": False, "checked": 0, "missing": [], "error": "no sung tokens to check (no lyrics in the page)",
                "text": "0/0 — the page has no lyrics: run `slop analyze` then `slop edit export`"}
    nw = workers or default_workers(max(1, len(toks)))
    nw = max(1, min(nw, max(1, len(toks))))
    chunks = [toks[k::nw] for k in range(nw)]
    t0 = time.monotonic()
    prog = progress.Counter(len(toks), "render lyrics", msg=f"render lyrics: {len(toks)} tokens with {nw} worker(s)")

    def work(ch):
        miss = []
        if not ch:
            return miss
        with sync_playwright() as p:
            with EnginePage(p, spec) as pg:
                for n, tk in enumerate(ch):
                    if n and n % RECYCLE_EVERY == 0:
                        pg.reopen()
                    try:
                        ok = tk["key"] in set(pg.drawn(tk["t"]))
                    except Exception as e:  # noqa: BLE001 — a failed frame counts as a miss
                        _log(f"[lyrics] t={tk['t']:.2f}: {str(e)[:120]}")
                        pg.reopen()
                        ok = False
                    if not ok:
                        miss.append({"line": tk["line"], "token": tk["i"], "txt": tk["txt"], "t0": tk["t0"], "t": round(tk["t"], 3)})
                    prog.add(1)
        return miss

    try:
        with cf.ThreadPoolExecutor(nw) as ex:
            drawn_miss = [m for part in ex.map(work, chunks) for m in part]
    finally:
        prog.finish()
    missing = sorted(drawn_miss + untimed, key=lambda m: (m["t0"] is None, m["t0"] or 0.0, m["line"]))
    n = len(toks) + len(untimed)
    k = n - len(missing)
    lines = sorted({m["line"] for m in missing})
    rep = {"checked": n, "drawn": k, "missing": missing, "untimed": len(untimed), "lines_with_misses": lines,
           "size": [spec["w"], spec["h"]], "seconds": round(time.monotonic() - t0, 1)}
    outf = Path(out) if out else pdir / "render" / f"lyrics-report{_suffix(pdir, spec['w'], spec['h'])}.json"
    outf.parent.mkdir(parents=True, exist_ok=True)
    outf.write_text(json.dumps(rep, indent=1, ensure_ascii=False), encoding="utf-8")
    text = f"{k}/{n} tokens on screen at their time ({rep['seconds']}s, {spec['w']}x{spec['h']})"
    if missing:
        text += f"; lines with misses: {lines}\n" + "\n".join(
            f"  L{m['line']:02d} {m['t']:7.2f} {m['txt']}" if m["t"] is not None else f"  L{m['line']:02d}    —    {m['txt']}  ({m['why']})"
            for m in missing[:40])
        if drawn_miss:
            text += "\nFix: every lyric drawer must call KIN.mark(tk) for each token it draws, on the token's t0."
        if untimed:
            text += (f"\n{len(untimed)} word(s) have no time: re-run `slop analyze` or set their t0/t1 in analysis/words.json "
                     "by ear (the ear-check list in analysis/report.md), then `slop edit export`.")
    return {"ok": not missing, "gate": f"{k}/{n}", **rep, "report": str(outf), "text": text}


def history_check(pdir: Path, pairs: list[tuple[float, float]], threshold: int = 40) -> dict:
    """Render B fresh and B after A in one page: any pixel whose difference (as luma) exceeds 40 levels fails."""
    from PIL import Image, ImageChops
    spec = P.page_spec(pdir)
    results = []
    sync_playwright = _sync_playwright()
    with sync_playwright() as p:
        for a, b in pairs:
            with EnginePage(p, spec) as pg:
                fresh = Image.open(io.BytesIO(pg.frame_jpeg(b, .95))).convert("RGB")
            with EnginePage(p, spec) as pg:
                pg.frame_jpeg(a, .95)
                after = Image.open(io.BytesIO(pg.frame_jpeg(b, .95))).convert("RGB")
            d = ImageChops.difference(fresh, after).convert("L")
            n = sum(d.histogram()[threshold + 1:])
            results.append({"a": a, "b": b, "pixels_over": n, "ok": n == 0})
    bad = [r for r in results if not r["ok"]]
    return {"ok": not bad, "pairs": results,
            "text": ("HISTORY-INDEPENDENT" if not bad else "HISTORY-DEPENDENT") + " — "
                    + ", ".join(f"{r['b']}s after {r['a']}s: {r['pixels_over']} px differ" for r in results)}


def default_pairs(pdir: Path, duration: float) -> list[tuple[float, float]]:
    """Out-of-order pairs (A rendered first, then B): late→early, early→late, and across the middle."""
    d = max(duration, 1.0)
    pts = [round(d * f, 3) for f in (.85, .15, .55, .35)]
    return [(pts[0], pts[1]), (pts[1], pts[0]), (pts[2], pts[3])]

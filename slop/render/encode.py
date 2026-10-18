"""Encode frames to the master (x264 CRF 16, BT.709-tagged, AAC 256k, +faststart) and verify it with ffprobe.

Why the tags: frames are sRGB; untagged (or BT.601) streams show lighter and washed out in QuickTime/browsers. The
JPEGs are converted with the BT.709 matrix to limited range and tagged primaries bt709 / transfer iec61966-2-1 (sRGB) /
matrix bt709 / range tv — on the stream (x264 VUI) and on the frames (setparams).

What a master must be (checked, never assumed):
- frames f00000 … f<N−1> with N = ceil(duration · fps) — ALL of them, starting at frame 0, because the song's audio
  starts at 0 (a master that started at the first rendered frame played every word early); duration is the one the
  frames were drawn for (<frames>/.inputs.json: the beat map's, or the final song's with --timemap);
- drawn from the project as it is now (the .inputs.json fingerprint matches; stale frames are refused);
- verified: H.264 yuv420p, the four colour tags, the size, exactly N frames, a video duration within 1/fps of the
  song, and an audio stream.
Previews (--draft, or --allow-gaps) may start later and have holes: each frame is held until the next one, and the
audio is offset (-ss first/fps) so the words stay in sync.
A STRETCH (span: the frames of `slop render vertical --from A --to B`, the cut that is posted) is held to the master's
rules over its own range: every frame of the range, fresh, full quality, audio offset to its first frame; its
<video>.inputs.json records the span, so `clean` and `encode --share` know it is a stretch.
Port notes: the review profile keeps the reference review copy's `-tune grain` (CRF 20, maxrate 8M); the original
encoded `-framerate 24 -i f%05d.jpg` with no checks.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from fractions import Fraction
from pathlib import Path

from .. import progress
from ..config import SlopError
from ..util import no_picture_text, shots_without_picture
from . import project as P

VF = ("format=rgb24,scale=flags=accurate_rnd+full_chroma_int+full_chroma_inp:out_color_matrix=bt709:out_range=tv,"
      "format=yuv420p,setparams=color_primaries=bt709:color_trc=iec61966-2-1:colorspace=bt709:range=tv")
TAGS = ["-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "iec61966-2-1", "-color_range", "tv"]
EXPECT = {"codec_name": "h264", "pix_fmt": "yuv420p", "color_space": "bt709", "color_primaries": "bt709",
          "color_transfer": "iec61966-2-1", "color_range": "tv"}
PROFILES = {
    "master": ["-c:v", "libx264", "-preset", "slow", "-crf", "16"],
    "review": ["-c:v", "libx264", "-preset", "slow", "-tune", "grain", "-crf", "20", "-maxrate", "8M", "-bufsize", "16M"],
    "draft": ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23"],
}


def _need(tool: str) -> str:
    exe = shutil.which(tool)
    if not exe:
        raise SlopError(f"{tool} not found on PATH — install ffmpeg (the box has it; elsewhere: apt install ffmpeg)")
    return exe


def _run_once(full: list[str], total_frames: int, stage: str) -> tuple[int, str, int]:
    import tempfile
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as err:
        pr = subprocess.Popen(full, stdout=subprocess.PIPE, stderr=err, text=True, encoding="utf-8", errors="replace")
        progress.report(0, total_frames, f"{stage}: starting", stage=stage, force=True)
        n = 0
        assert pr.stdout is not None
        for line in pr.stdout:
            if line.startswith("frame="):
                try:
                    n = int(line.split("=", 1)[1].strip() or 0)
                except ValueError:
                    continue
                progress.report(n, total_frames, f"{stage}: frame {n}/{total_frames}", stage=stage)
        rc = pr.wait()
        err.seek(0)
        return rc, err.read(), n


def run_ffmpeg(cmd: list[str], total_frames: int, stage: str) -> subprocess.CompletedProcess:
    """Run ffmpeg with `-progress pipe:1` and report frame=N to $SLOP_PROGRESS_FILE (slop/progress.py) as it goes.
    stderr goes to a temporary file (a full stderr pipe would block ffmpeg). An ffmpeg KILLED by a signal (the memory
    limit, a box restart, another process) is run once more — the output is rewritten from the start; a real failure
    (exit code > 0) is not retried. The returned stderr names the signal when there is one."""
    import signal
    import sys
    full = [cmd[0], "-progress", "pipe:1", "-nostats", *cmd[1:]]
    rc, e, n = _run_once(full, total_frames, stage)
    if rc < 0:
        print(f"[{stage}] ffmpeg was killed by signal {-rc} at frame {n}/{total_frames} — running it again",
              file=sys.stderr, flush=True)
        rc, e, n = _run_once(full, total_frames, stage)
    if rc < 0:
        try:
            name = signal.Signals(-rc).name
        except ValueError:
            name = str(-rc)
        e = (e + f"\nffmpeg was killed by {name} twice (at frame {n} of {total_frames}): free memory or stop what else "
                 "is running, then run the same command again (it starts over safely)").strip()
    progress.end(n if rc == 0 else min(n, max(0, total_frames - 1)), total_frames,
                 f"{stage}: {'done' if rc == 0 else 'ffmpeg failed'}", stage=stage)
    return subprocess.CompletedProcess(full, rc, "", e)


def one_frame_pad(fps: float) -> str:
    """The audio filter that pads at most one frame of silence (a song ending inside the last frame keeps that frame)."""
    return f"apad=pad_dur={1 / float(fps or 24):.6f}"


def made_from_path(video: Path) -> Path:
    return Path(video).with_name(Path(video).name + ".inputs.json")


def audio_sig(song: Path) -> str | None:
    """A content hash of the song file (sha256, first 16 hex; streamed — a 5-minute WAV is ~55 MB). None if unreadable."""
    import hashlib
    try:
        h = hashlib.sha256()
        with open(song, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()[:16]
    except OSError:
        return None


def write_made_from(video: Path, frames: Path, rec: dict | None, n: int, audio: str | None = None,
                    span: tuple[int, int] | None = None) -> None:
    """<video>.inputs.json: which frames a verified master was encoded from (their .inputs.json hash) and which song
    (audio_sig), so `slop render clean` and `encode --share` can tell those frames from a later render without
    trusting file times (this machine's clock jumps). span: [first, end) frame indices of a stretch (else the song)."""
    import os
    f = made_from_path(video)
    tmp = f.with_name(f.name + ".tmp")
    rec2 = {"frames_dir": Path(frames).name, "hash": (rec or {}).get("hash"), "frames": n, "audio": audio}
    if span:
        rec2["span"] = [int(span[0]), int(span[1])]
    tmp.write_text(json.dumps(rec2, indent=1), encoding="utf-8")
    os.replace(tmp, f)


def read_made_from(video: Path) -> dict | None:
    try:
        v = json.loads(made_from_path(video).read_text(encoding="utf-8"))
        return v if isinstance(v, dict) else None
    except (OSError, ValueError):
        return None


def frame_indices(frames: Path) -> list[int]:
    out = []
    for f in Path(frames).glob("f*.jpg"):
        m = re.fullmatch(r"f(\d{5,})\.jpg", f.name)
        if m:
            out.append(int(m.group(1)))
    return sorted(out)


def ffprobe(path: Path) -> dict:
    r = subprocess.run([_need("ffprobe"), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                       capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        raise SlopError(f"ffprobe failed on {path}: {r.stderr.strip()[:300]}")
    return json.loads(r.stdout or "{}")


def _rate(s) -> float | None:
    try:
        f = Fraction(str(s))
        return float(f) if f > 0 else None
    except (ValueError, ZeroDivisionError):
        return None


def verify(path: Path, expect_frames: int | None = None, want_audio: bool = True, size: tuple[int, int] | None = None,
           expect_duration: float | None = None) -> dict:
    """Check the delivered file: H.264 yuv420p with BT.709/sRGB/tv tags, size, frame count, duration, audio."""
    info = ffprobe(path)
    vs = [s for s in info.get("streams", []) if s.get("codec_type") == "video"]
    aus = [s for s in info.get("streams", []) if s.get("codec_type") == "audio"]
    problems = []
    if not vs:
        return {"ok": False, "problems": ["no video stream"], "file": str(path)}
    v = vs[0]
    tags = {k: v.get(k) for k in EXPECT}
    for k, want in EXPECT.items():
        if v.get(k) != want:
            problems.append(f"{k} is {v.get(k)!r}, want {want!r}")
    if size and (v.get("width"), v.get("height")) != tuple(size):
        problems.append(f"size {v.get('width')}x{v.get('height')}, want {size[0]}x{size[1]}")
    nb = int(v.get("nb_frames") or 0)
    if expect_frames and nb != expect_frames:
        problems.append(f"{nb} frames, expected {expect_frames}"
                        + (" (is audio/song.wav shorter than the film? -shortest cut it)" if want_audio and nb < expect_frames else ""))
    fps = _rate(v.get("avg_frame_rate")) or _rate(v.get("r_frame_rate"))
    vdur = (nb / fps) if (nb and fps) else float(v.get("duration") or 0)
    if expect_duration and fps and abs(vdur - expect_duration) > 1 / fps + 1e-3:
        problems.append(f"video is {vdur:.3f} s, expected {expect_duration:.3f} s (± 1 frame)")
    if want_audio and not aus:
        problems.append("no audio stream")
    dur = float(info.get("format", {}).get("duration") or 0)
    return {"ok": not problems, "file": str(path), "problems": problems, "tags": tags, "width": v.get("width"),
            "height": v.get("height"), "frames": nb, "fps": v.get("r_frame_rate"), "duration": round(dur, 3),
            "video_duration": round(vdur, 3), "audio": aus[0].get("codec_name") if aus else None,
            "audio_duration": round(float(aus[0].get("duration") or 0), 3) if aus else None,
            "bytes": int(info.get("format", {}).get("size") or 0)}


def check_fresh(pdir: Path, frames: Path) -> tuple[dict | None, list[str] | None]:
    """(the frames' .inputs.json record, the changed parts if the project changed since they were drawn, else None)."""
    rec = P.read_fingerprint(frames)
    if rec is None:
        return None, None
    cur = P.current_fingerprint(pdir, rec)
    return rec, (P.fingerprint_changes(rec, cur) if cur["hash"] != rec["hash"] else None)


class _ProjectLock:
    """One encode at a time per project: a second one fails at once instead of writing the same file."""

    def __init__(self, pdir: Path):
        self.path = Path(pdir) / "render" / ".encode.lock"
        self.fh = None

    def __enter__(self):
        import fcntl
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fh = open(self.path, "w")
        try:
            fcntl.flock(self.fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.fh.close()
            raise SlopError("another encode is writing in this project right now: wait for it (`slop job list`), "
                            "then run this again") from None
        return self

    def __exit__(self, *exc):
        import fcntl
        try:
            fcntl.flock(self.fh, fcntl.LOCK_UN)
        finally:
            self.fh.close()


def encode(pdir: Path, frames: Path | None = None, out: Path | None = None, profile: str = "master",
           audio: bool = True, allow_gaps: bool = False, vertical: bool = False,
           span: tuple[int, int] | None = None) -> dict:
    with _ProjectLock(pdir):
        return _encode(pdir, frames, out, profile, audio, allow_gaps, vertical, span)


def _encode(pdir: Path, frames: Path | None = None, out: Path | None = None, profile: str = "master",
            audio: bool = True, allow_gaps: bool = False, vertical: bool = False,
            span: tuple[int, int] | None = None) -> dict:
    ffmpeg = _need("ffmpeg")
    fps = P.project_fps(pdir)
    step = "vertical" if vertical else "frames"
    if frames is None:
        frames = pdir / "render" / ("frames-vertical" if vertical else "frames")
    frames = Path(frames)
    idx = frame_indices(frames) if frames.is_dir() else []
    if not idx:
        raise SlopError(f"no frames in {frames} — run `slop render {step}` first")
    preview = profile == "draft" or allow_gaps
    if (frames / ".redraw-incomplete").exists() and not preview:
        raise SlopError(f"a `slop render {step} --force` redraw of {frames} did not finish (old and new frames are "
                        f"mixed): run the same render command again (it resumes), then encode")
    warns: list[str] = []
    blank = shots_without_picture(pdir)
    if blank:
        warns.append(no_picture_text(blank))
    rec, changed = check_fresh(pdir, frames)
    if changed:
        msg = f"the frames in {frames} are stale — the project changed since they were drawn ({', '.join(changed[:6])})"
        if not preview:
            raise SlopError(msg + f": run `slop render {step}` again (it discards and redraws them), then encode")
        warns.append(msg + " — encoded anyway (preview)")
    elif rec is not None and rec.get("placeholders"):
        msg = (f"the frames in {frames} were drawn with --allow-missing: some show placeholders for missing media")
        if not preview:
            raise SlopError(msg + f" — add the missing files (slop render info lists them), run `slop render {step}` "
                            "again (it redraws them), then encode")
        warns.append(msg + " (preview)")
    elif rec is None:
        warns.append(f"{frames} has no .inputs.json: these frames were not drawn by `slop render {step}`, so nothing "
                     "proves they match the project")
    dur = float((rec or {}).get("duration") or 0) or P.render_duration(pdir, bool((rec or {}).get("timemap")))
    expected_last = (P.frame_count(dur, fps) - 1) if dur else idx[-1]
    have = set(idx)
    if span is not None:
        lo, hi = int(span[0]), min(int(span[1]), expected_last + 1)
        if not 0 <= lo < hi:
            raise SlopError(f"empty stretch: frames {span[0]}-{span[1]} (the song has {expected_last + 1} frames)")
        span = None if (lo == 0 and hi == expected_last + 1) else (lo, hi)      # the whole song: an ordinary master
    if span is not None and not preview:
        lo, hi = span
        missing = [i for i in range(lo, hi) if i not in have]
        if missing:
            raise SlopError(f"{len(missing)} of {hi - lo} frames of the stretch {lo / fps:.2f}–{hi / fps:.2f} s missing in "
                            f"{frames} (first: f{missing[0]:05d} at {missing[0] / fps:.2f} s) — run `slop render {step}` "
                            "with the same --from/--to again (it resumes)")
        use = list(range(lo, hi))
    elif not preview:
        if not dur:
            raise SlopError("unknown song duration: add analysis/beats.json (slop analyze) or audio/song.wav — a master "
                            "must run the length of the song")
        missing = [i for i in range(0, expected_last + 1) if i not in have]
        if missing:
            raise SlopError(f"{len(missing)} of {expected_last + 1} frames missing in {frames} (first: f{missing[0]:05d} "
                            f"at {missing[0] / fps:.2f} s) — a master runs from frame 0 to the song's end ({dur:.2f} s): "
                            f"run `slop render {step}` with no --from/--to/--every (it resumes), or pass --draft / "
                            "--allow-gaps for a preview")
        use = list(range(0, expected_last + 1))
    else:
        use = [i for i in idx if i <= expected_last] if dur else idx
        if span is not None:
            use = [i for i in use if span[0] <= i < span[1]]
        if not use:
            raise SlopError(f"no frames of the song ({dur:.2f} s) in {frames} — run `slop render {step}`")
    first, last = use[0], use[-1]
    stride = (use[-1] - use[-2]) if len(use) > 1 else 1
    end = max(last + 1, min(expected_last + 1, last + stride)) if dur else last + 1    # the last frame holds its slot
    holes = (end - first) - len(use)
    if out is None:
        name = {"master": "vertical.mp4" if vertical else "master.mp4", "review": "review-vertical.mp4" if vertical else "review.mp4",
                "draft": "draft-vertical.mp4" if vertical else "draft.mp4"}[profile]
        out = pdir / "out" / name
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    song = P.audio_path(pdir)
    if audio and not song.is_file():
        raise SlopError(f"audio missing: {song} — add the song (slop song ingest) or pass --no-audio for a silent encode")
    lst = None
    if holes:
        # a preview with holes: each existing frame is held until the next one (concat demuxer)
        lst = out.with_suffix(".frames.txt")
        lines = []
        for k, i in enumerate(use):
            nxt = use[k + 1] if k + 1 < len(use) else end
            lines += [f"file '{(frames / f'f{i:05d}.jpg').resolve().as_posix()}'", f"duration {(nxt - i) / fps:.6f}"]
        lines.append(f"file '{(frames / f'f{use[-1]:05d}.jpg').resolve().as_posix()}'")
        lst.write_text("\n".join(lines) + "\n", encoding="utf-8")
        vin = ["-f", "concat", "-safe", "0", "-i", str(lst)]
        vout = ["-r", f"{fps:g}", "-fps_mode", "cfr", "-frames:v", str(end - first)]
    else:
        vin = ["-framerate", f"{fps:g}", "-start_number", str(first), "-i", str(frames / "f%05d.jpg")]
        vout = ["-frames:v", str(end - first)]
    # the audio starts where the picture starts (a preview from --from 2 hears the song from 2 s); a song that ends
    # inside the last frame (306.4 s = 7353.6 frames at 24 fps) is padded with at most ONE frame of silence (apad
    # pad_dur) — -shortest alone cut the picture to the audio and the master came out one frame short; a song that is
    # really shorter than the film still cuts the picture, and verify says so
    ain = ((["-ss", f"{first / fps:.6f}"] if first else []) + ["-i", str(song), "-map", "0:v:0", "-map", "1:a:0", "-c:a", "aac",
           "-b:a", "256k", "-af", one_frame_pad(fps), "-shortest"]) if audio else ["-map", "0:v:0"]
    cmd = [ffmpeg, "-y", "-loglevel", "error", *vin, *ain, "-vf", VF, *TAGS, *PROFILES[profile], "-pix_fmt", "yuv420p",
           *vout, "-movflags", "+faststart", str(out)]
    # the file is about to be replaced: its record (which frames, which song, a stretch's span) goes with it, and only a
    # verified master writes a new one — a failed or preview encode must not inherit the old one (a whole-song re-encode
    # that fails would otherwise still read as the earlier stretch to `clean` and `encode --share`)
    made_from_path(out).unlink(missing_ok=True)
    r = run_ffmpeg(cmd, end - first, f"encode {profile}{' vertical' if vertical else ''}")
    if lst is not None:
        lst.unlink(missing_ok=True)
    if r.returncode != 0:
        raise SlopError(f"ffmpeg failed (exit {r.returncode}): {r.stderr.strip()[-600:] or 'no message'} — run the same "
                        "command again; if it fails again, `slop doctor` checks ffmpeg")
    from PIL import Image
    with Image.open(frames / f"f{first:05d}.jpg") as im:
        size = im.size
    v = verify(out, expect_frames=end - first, want_audio=audio, size=size, expect_duration=(end - first) / fps)
    stretch = [first, end] if span is not None else None
    if v["ok"] and profile == "master" and not preview:
        write_made_from(out, frames, rec, end - first, audio=audio_sig(song) if audio else None, span=stretch)
    span = f" from {first / fps:.2f} s (audio offset to match)" if first else ""
    text = (f"{out} — {v.get('width')}x{v.get('height')} {v.get('frames')} frames {v.get('video_duration')}s{span}, "
            + ("verified (BT.709 / sRGB transfer / tv, frame count, duration" + (", audio)" if audio else ")") if v["ok"]
               else "WRONG: " + "; ".join(v["problems"])))
    if warns:
        text += "\n" + "\n".join("  ! " + w for w in warns)
    return {"ok": v["ok"], "out": str(out), "profile": profile, "verify": v, "gaps": holes, "start_frame": first,
            "frames_expected": end - first, "duration_expected": round((end - first) / fps, 3),
            "span": stretch, "warnings": warns, "text": text}


# ------------------------------------------------------------------------------------------- the share copy ------
SHARE_CAP_MIB = 200          # Grok chat's limit for a video file
SHARE_DEFAULT_MIB = 95       # the default target: under the 100 MB Drive upload limit (videos reach people via Drive)
SHARE_AUDIO_KBPS = 192
SHARE_MAX_KBPS = 20000       # more than this buys nothing visible at 1080p24 (short films stop here, under the cap)
SHARE_MIN_KBPS = 1500        # below this the lyric type smears in motion: say so
SHARE_OVERHEAD = .03         # MP4 container + rate-control slack
TAG_ONLY = "setparams=color_primaries=bt709:color_trc=iec61966-2-1:colorspace=bt709:range=tv"


def _video_kbps(video: Path) -> int | None:
    """The video stream's average bitrate (kbit/s) of an existing, tag-correct video; None otherwise."""
    if not Path(video).is_file():
        return None
    try:
        info = ffprobe(Path(video))
    except SlopError:
        return None
    vs = [s for s in info.get("streams", []) if s.get("codec_type") == "video"]
    if not vs or any(vs[0].get(k) != v for k, v in EXPECT.items()):
        return None
    try:
        br = int(vs[0].get("bit_rate") or 0)
    except (TypeError, ValueError):
        br = 0
    return br // 1000 or None


def share_bitrate(duration: float, max_mib: float, audio_kbps: int = SHARE_AUDIO_KBPS) -> int:
    """The video bitrate (kbit/s) that makes video + audio + container fit in max_mib MiB over `duration` seconds."""
    if duration <= 0:
        raise SlopError("unknown duration: cannot size the share copy (run `slop analyze` or add audio/song.wav)")
    total = max_mib * 1048576 * 8 * (1 - SHARE_OVERHEAD) / duration / 1000
    return int(min(SHARE_MAX_KBPS, total - audio_kbps))


def _share_source(pdir: Path, vertical: bool, frames: Path | None) -> dict:
    """Where the share copy comes from: the frames when every one is there and fresh (one generation, best quality),
    else the verified master video (out/master.mp4 or out/vertical.mp4)."""
    fps = P.project_fps(pdir)
    fdir = Path(frames) if frames else pdir / "render" / ("frames-vertical" if vertical else "frames")
    master = pdir / "out" / ("vertical.mp4" if vertical else "master.mp4")
    why = []
    # a verified stretch (`slop render vertical --from A --to B`) is the cut that is posted: share it, not the frames
    made = (read_made_from(master) or {}) if master.is_file() and not frames else {}
    sp = made.get("span")
    if isinstance(sp, list) and len(sp) == 2:
        v = verify(master, want_audio=False)
        if v["ok"] and v.get("frames"):
            # is it still the current cut? the frames on disk (when they are still there) say what the project is now
            stale = None
            if fdir.is_dir() and frame_indices(fdir):
                rec, changed = check_fresh(pdir, fdir)
                if rec is not None and made.get("hash") and rec.get("hash") != made.get("hash"):
                    stale = f"{fdir.name}/ holds a later render"
                elif changed:
                    stale = f"the project changed since ({', '.join(changed[:4])})"
            return {"kind": "master", "file": master, "frames": int(v["frames"]), "duration": v["frames"] / fps,
                    "size": (v["width"], v["height"]), "start": int(sp[0]), "stretch": [int(sp[0]), int(sp[1])],
                    "stale": stale, "why": [f"out/{master.name} is the stretch {sp[0] / fps:.2f}–{sp[1] / fps:.2f} s"]}
    idx = frame_indices(fdir) if fdir.is_dir() else []
    if idx:
        rec, changed = check_fresh(pdir, fdir)
        dur = float((rec or {}).get("duration") or 0) or (P.render_duration(pdir, bool((rec or {}).get("timemap"))) or 0)
        n = P.frame_count(dur, fps) if dur else 0
        if rec is None:
            why.append(f"{fdir.name}/ has no .inputs.json")
        elif changed:
            why.append(f"{fdir.name}/ is stale ({', '.join(changed[:4])})")
        elif rec.get("placeholders"):
            why.append(f"{fdir.name}/ was drawn with --allow-missing")
        elif not n or not set(range(n)) <= set(idx):
            why.append(f"{fdir.name}/ is incomplete ({len(idx)} of {n} frames)")
        else:
            from PIL import Image
            with Image.open(fdir / "f00000.jpg") as im:
                size = im.size
            return {"kind": "frames", "dir": fdir, "frames": n, "duration": n / fps, "size": size, "why": why,
                    "hash": rec.get("hash")}
    else:
        why.append(f"no frames in {fdir.name}/")
    if master.is_file():
        v = verify(master, want_audio=False)
        if v["ok"] and v.get("frames"):
            return {"kind": "master", "file": master, "frames": int(v["frames"]), "duration": v["frames"] / fps,
                    "size": (v["width"], v["height"]), "why": why}
        why.append(f"{master.name} fails verification ({'; '.join(v.get('problems', [])[:2])})")
    else:
        why.append(f"no out/{master.name}")
    step = "vertical" if vertical else "frames` and `slop render encode"
    raise SlopError(f"nothing to make the share copy from ({'; '.join(why)}) — run `slop render {step}` first, "
                    f"then `slop render encode --share{' --vertical' if vertical else ''}`")


def master_state(pdir: Path, vertical: bool, src: dict) -> dict:
    """Is out/master.mp4 (out/vertical.mp4) the film the share copy would show? {file, picture, audio, why}:
    picture — encoded from the frames now on disk (its <video>.inputs.json names their .inputs.json hash), or it IS the
    share's source; audio — encoded from the song now in audio/ (content hash). Only a current master may cap the share
    copy's bitrate or be copied as the share copy: a master from an earlier render (stand-in plates, then the real
    ones) says nothing about how many bits the frames on disk need."""
    m = pdir / "out" / ("vertical.mp4" if vertical else "master.mp4")
    name = f"out/{m.name}"
    if not m.is_file():
        return {"file": m, "picture": False, "audio": False, "why": f"no {name}"}
    made = read_made_from(m) or {}
    if src["kind"] == "master":
        picture, why = True, ""
    elif isinstance(made.get("span"), list) and len(made["span"]) == 2:
        fps = P.project_fps(pdir)
        picture, why = False, f"{name} is the stretch {made['span'][0] / fps:.2f}–{made['span'][1] / fps:.2f} s, not the whole film"
    elif not made.get("hash"):
        picture, why = False, f"{name} has no record of the frames it was encoded from"
    elif made["hash"] != src.get("hash"):
        picture, why = False, f"{name} was encoded from an earlier render of the frames"
    else:
        picture, why = True, ""
    song = P.audio_path(pdir)
    audio = bool(made.get("audio")) and song.is_file() and made["audio"] == audio_sig(song)
    if picture and not audio and not why:
        why = (f"{name} was encoded with another version of {song.name}" if made.get("audio")
               else f"{name} has no record of the song it was encoded with")
    return {"file": m, "picture": picture, "audio": audio, "why": why}


def share(pdir: Path, vertical: bool = False, max_mib: float = SHARE_DEFAULT_MIB, frames: Path | None = None,
          out: Path | None = None) -> dict:
    with _ProjectLock(pdir):
        return _share(pdir, vertical, max_mib, frames, out)


def _share(pdir: Path, vertical: bool = False, max_mib: float = SHARE_DEFAULT_MIB, frames: Path | None = None,
           out: Path | None = None) -> dict:
    """out/share.mp4 (out/share-vertical.mp4), sized to send in Grok chat (≤ max_mib MiB; the chat's limit is 200 MiB).
    When the current master (encoded from the frames now on disk and the song now in audio/) already fits, it is a
    verified byte copy of it. Otherwise a two-pass x264 encode: bitrate from the duration — never above the current
    master's own bitrate (a master from an earlier render is not used) — the master's colour tags (BT.709 primaries
    and matrix, sRGB transfer, tv range), AAC 192k, +faststart, 2-second GOP; verified with ffprobe, file size
    included."""
    import os
    import time
    try:
        max_mib = float(max_mib)
    except (TypeError, ValueError):
        raise SlopError(f"--max-mib must be a number of MiB, e.g. 190 (got {max_mib!r})") from None
    if not 8 <= max_mib <= SHARE_CAP_MIB:
        raise SlopError(f"--max-mib must be between 8 and {SHARE_CAP_MIB} (Grok chat takes videos up to 200 MiB); "
                        f"got {max_mib:g}")
    ffmpeg = _need("ffmpeg")
    fps = P.project_fps(pdir)
    src = _share_source(pdir, vertical, frames)
    n, dur = src["frames"], src["duration"]
    kbps = share_bitrate(dur, max_mib)
    if kbps <= 200:
        raise SlopError(f"{dur:.0f} s does not fit in {max_mib:g} MiB at a watchable bitrate ({kbps} kbit/s): raise "
                        f"--max-mib (up to {SHARE_CAP_MIB}) or share the master another way")
    warns: list[str] = []
    mname = "out/vertical.mp4" if vertical else "out/master.mp4"
    if src.get("stretch"):
        a_s, b_s = (x / fps for x in src["stretch"])
        if src.get("stale"):
            warns.append(f"{mname} is the stretch {a_s:.2f}–{b_s:.2f} s as it was encoded, and {src['stale']}: for the "
                         f"current cut run `slop render vertical --from {a_s:.2f} --to {b_s:.2f}` first, then this again")
    elif src["kind"] == "master" and not any(w.startswith("no frames in") for w in src["why"]):
        warns.append(f"made from {mname} because {'; '.join(src['why'])}: it shows the film as it was when {mname} was "
                     f"encoded — for the current cut run `slop render {'vertical' if vertical else 'frames'}`"
                     f"{'' if vertical else ' and `slop render encode`'} first, then this again")
    if kbps < SHARE_MIN_KBPS:
        warns.append(f"only {kbps} kbit/s fits {max_mib:g} MiB over {dur:.0f} s: small type will smear — the share copy "
                     f"is for chat; post the master ({mname}) where size allows")
    ms = master_state(pdir, vertical, src)
    song = P.audio_path(pdir)
    out = Path(out) if out else pdir / "out" / ("share-vertical.mp4" if vertical else "share.mp4")
    out.parent.mkdir(parents=True, exist_ok=True)
    rel = out.relative_to(pdir).as_posix() if out.is_relative_to(pdir) else str(out)
    limit = int(max_mib * 1048576)
    blank = shots_without_picture(pdir)
    if blank:
        warns.append(no_picture_text(blank))
    # the current master already fits: send it as it is (a copy — no second generation, no 2.5 minutes of x264)
    if ms["picture"] and (ms["audio"] or (src["kind"] == "master" and not song.is_file())) \
            and 0 < ms["file"].stat().st_size <= limit and Path(ms["file"]).resolve() != out.resolve():
        return _share_copy(ms["file"], out, rel, src, n, fps, max_mib, limit, warns)
    if ms["why"] and src["kind"] == "frames" and ms["file"].is_file():
        redo = f"`slop render {'encode --vertical' if vertical else 'encode'}`"
        warns.append(f"{ms['why']}: the share copy is encoded with the song now in audio/ (run {redo} to update "
                     f"{mname} too)" if ms["picture"] else
                     f"{ms['why']}: not used as the share copy or as its size cap (run {redo} to bring it up to date)")
    # never bigger than the CURRENT master: simple pictures compress far below the budget at CRF 16 (measured on the
    # full 5:06 song with synthetic plates: master 79 MB, an uncapped share 185 MiB) — then the share takes its rate
    mkbps = _video_kbps(ms["file"]) if ms["picture"] else None
    capped = bool(mkbps and mkbps < kbps)
    if capped:
        kbps = max(201, mkbps)
    scratch = pdir / "render" / "scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    plog = scratch / f"share{'-vertical' if vertical else ''}-x264"
    if src["kind"] == "frames":
        vin, vf = ["-framerate", f"{fps:g}", "-start_number", "0", "-i", str(src["dir"] / "f%05d.jpg")], VF
    else:
        vin, vf = ["-i", str(src["file"])], "scale=out_range=tv,format=yuv420p," + TAG_ONLY   # never full range out
    if song.is_file():
        st = int(src.get("start") or 0)                  # a stretch hears the song from its own first frame
        ain, amap = [*(["-ss", f"{st / fps:.6f}"] if st else []), "-i", str(song)], ["-map", "0:v:0", "-map", "1:a:0"]
    elif src["kind"] == "master":
        ain, amap = [], ["-map", "0:v:0", "-map", "0:a:0"]
        warns.append(f"audio taken from {src['file'].name} ({song.name} is missing)")
    else:
        raise SlopError(f"audio missing: {song} — add the song (slop song ingest), then run this again")
    gop = str(max(1, int(round(fps * 2))))

    def x264(rate: int) -> list[str]:
        return ["-c:v", "libx264", "-preset", "slow", "-profile:v", "high", "-b:v", f"{rate}k",
                "-maxrate", f"{int(rate * 1.5)}k", "-bufsize", f"{rate * 2}k", "-g", gop, "-pix_fmt", "yuv420p"]

    t0 = time.monotonic()
    base = [ffmpeg, "-y", "-loglevel", "error", *vin]
    r1 = run_ffmpeg([*base, "-map", "0:v:0", "-vf", vf, *TAGS, *x264(kbps), "-frames:v", str(n), "-pass", "1",
                     "-passlogfile", str(plog), "-an", "-f", "mp4", os.devnull], n, "encode share pass 1/2")
    if r1.returncode != 0:
        raise SlopError(f"ffmpeg (share, pass 1) failed: {r1.stderr.strip()[-600:]}")
    t1 = time.monotonic()

    def pass2(rate: int, stage: str = "encode share pass 2/2") -> dict:
        cmd = [*base, *ain, *amap, "-vf", vf, *TAGS, *x264(rate), "-frames:v", str(n), "-pass", "2",
               "-passlogfile", str(plog), "-c:a", "aac", "-b:a", f"{SHARE_AUDIO_KBPS}k", "-af", one_frame_pad(fps), "-shortest",
               "-movflags", "+faststart", str(out)]
        r = run_ffmpeg(cmd, n, stage)
        if r.returncode != 0:
            raise SlopError(f"ffmpeg (share, pass 2) failed: {r.stderr.strip()[-600:]}")
        return verify(out, expect_frames=n, want_audio=True, size=tuple(src["size"]), expect_duration=n / fps)

    v = pass2(kbps)
    passes = 2
    if v.get("bytes", 0) > limit:          # two-pass rarely overshoots; once more, scaled to the measured size
        first = v["bytes"]
        kbps = max(201, int(kbps * limit / first * .97))
        warns.append(f"pass 2 came out at {first / 1048576:.1f} MiB: encoded again at {kbps} kbit/s")
        v = pass2(kbps, "encode share pass 2/2 again (smaller)")
        passes = 3
    for f in scratch.glob(plog.name + "*"):
        f.unlink(missing_ok=True)
    size_ok = 0 < v.get("bytes", 0) <= limit
    if not size_ok:
        v["problems"] = list(v.get("problems", [])) + [f"{v.get('bytes', 0) / 1048576:.1f} MiB is over --max-mib {max_mib:g}"]
    ok = bool(v["ok"]) and size_ok
    mib = v.get("bytes", 0) / 1048576
    text = (f"{rel} — {v.get('width')}x{v.get('height')} {v.get('frames')} frames {v.get('video_duration')}s, "
            f"{mib:.1f} MiB (target ≤ {max_mib:g}; Drive takes ≤ 100 MB), two-pass x264 {kbps} kbit/s "
            f"+ AAC {SHARE_AUDIO_KBPS}k{' (the master is smaller: capped at its own bitrate)' if capped else ''}, "
            f"from the {src['kind']}"
            + (", verified (BT.709 / sRGB transfer / tv, frames, duration, audio, size)" if ok
               else " — WRONG: " + "; ".join(v["problems"])))
    if ok:
        text += f"\nnext: send {rel} in the chat; when out/master.mp4 is final, free the disk with `slop render clean`"
    if warns:
        text += "\n" + "\n".join("  ! " + w for w in warns)
    return {"ok": ok, "out": str(out), "profile": "share", "bytes": v.get("bytes", 0), "mib": round(mib, 2),
            "max_mib": max_mib, "kbps": kbps, "capped_at_master": capped, "copied": False, "audio_kbps": SHARE_AUDIO_KBPS,
            "source": src["kind"], "source_notes": src["why"], "master_current": bool(ms["picture"] and ms["audio"]),
            "passes": passes, "verify": v, "seconds": round(time.monotonic() - t0, 1),
            "seconds_pass1": round(t1 - t0, 1), "warnings": warns, "text": text}


def _share_copy(master: Path, out: Path, rel: str, src: dict, n: int, fps: float, max_mib: float, limit: int,
                warns: list[str]) -> dict:
    """out/share.mp4 as a byte copy of the current master (it already fits under --max-mib), verified like an
    encoded share copy: tags, size, frames, duration, audio and the file size."""
    import os
    import time
    t0 = time.monotonic()
    v0 = verify(master, expect_frames=n, want_audio=True, size=tuple(src["size"]), expect_duration=n / fps)
    if not v0["ok"]:
        raise SlopError(f"{master.name} fails the master check ({'; '.join(v0['problems'][:3])}) — run `slop render "
                        f"{'encode --vertical' if master.name == 'vertical.mp4' else 'encode'}` again, then this")
    progress.report(0, 1, f"encode share: copying {master.name} (it fits)", stage="encode share copy", force=True)
    tmp = out.with_name(out.name + ".tmp")
    shutil.copyfile(master, tmp)
    os.replace(tmp, out)
    progress.end(1, 1, f"encode share: copied {master.name}", stage="encode share copy")
    v = verify(out, expect_frames=n, want_audio=True, size=tuple(src["size"]), expect_duration=n / fps)
    size_ok = 0 < v.get("bytes", 0) <= limit
    ok = bool(v["ok"]) and size_ok
    mib = v.get("bytes", 0) / 1048576
    text = (f"{rel} — a copy of out/{master.name} ({mib:.1f} MiB already fits under {max_mib:g} MiB: no re-encode, "
            f"no quality lost), {v.get('width')}x{v.get('height')} {v.get('frames')} frames {v.get('video_duration')}s"
            + (", verified (BT.709 / sRGB transfer / tv, frames, duration, audio, size)" if ok
               else " — WRONG: " + "; ".join(v["problems"] + ([] if size_ok else ["over --max-mib"]))))
    if ok:
        text += f"\nnext: send {rel} in the chat; when out/master.mp4 is final, free the disk with `slop render clean`"
    if warns:
        text += "\n" + "\n".join("  ! " + w for w in warns)
    return {"ok": ok, "out": str(out), "profile": "share", "bytes": v.get("bytes", 0), "mib": round(mib, 2),
            "max_mib": max_mib, "kbps": _video_kbps(out) or 0, "capped_at_master": False, "copied": True,
            "audio_kbps": None, "source": "master", "source_notes": src["why"], "master_current": True, "passes": 0,
            "verify": v, "seconds": round(time.monotonic() - t0, 1), "seconds_pass1": 0.0, "warnings": warns,
            "text": text}

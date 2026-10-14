"""`slop gen …` (models, estimates, images, edits, songs, hosting) and `slop clip …` (the clip lifecycle).

Every command returns a JSON-serialisable dict with a short "text"; --json (root flag) prints it whole.
Spending commands need a project (the ledger is per project) and --yes; nothing spends without an estimate shown first.
"""
from __future__ import annotations

import argparse
import functools
from pathlib import Path

from ..config import SlopError, load_project, resolve_project


def _project_or_none(a) -> Path | None:
    try:
        return resolve_project(getattr(a, "project", None))
    except SlopError:
        return None


def _hinted(fn):
    """every hint line of a gen/clip command's result or error names the project (`slop -p NAME clip …`)."""
    @functools.wraps(fn)
    def wrapper(a):
        from . import hints
        try:
            out = fn(a)
        except SlopError as e:
            pdir = _project_or_none(a)
            if pdir is not None:
                hints.stamp_error(e, pdir)
            raise
        pdir = _project_or_none(a) if isinstance(out, dict) else None
        return hints.stamp(out, pdir) if pdir is not None else out
    return wrapper


def _in(pdir: Path | None, s: str | None) -> str | None:
    """an input path: as given (absolute, or relative to the current directory), else relative to the project."""
    if not s:
        return s
    p = Path(s)
    if p.is_absolute() or p.exists() or pdir is None:
        return str(p)
    q = pdir / p
    return str(q) if q.exists() else str(p)


def _in_ref(pdir: Path | None, s: str | None) -> str | None:
    """a --ref: an http(s) or data: URL exactly as given (a path helper would collapse its '//'), else as _in."""
    if s and str(s).lower().startswith(("http://", "https://", "data:")):
        return s
    return _in(pdir, s)


def _out(pdir: Path, s: str | None) -> str | None:
    """an output path: absolute as given, relative ones inside the project."""
    if not s:
        return s
    p = Path(s)
    return str(p if p.is_absolute() else pdir / p)


def _read_text(text: str | None, path: str | None, what: str) -> str:
    if path:
        p = Path(path)
        if not p.is_file():
            raise SlopError(f"{what} file not found: {path}")
        return p.read_text(encoding="utf-8")
    if text:
        return text
    raise SlopError(f"give the {what}: as text or with --{what}-file FILE")


# ================================================================================================= gen
@_hinted
def cmd_models(a) -> dict:
    from . import models as reg
    rows = reg.rows(a.kind, resolution=a.res, duration=a.duration, quality=a.quality, refresh=a.refresh)
    if a.no_free:
        rows = [r for r in rows if r["est_usd"] > 0]
    rows = rows[: a.limit] if a.limit else rows
    unit = {"video": f"per {a.duration:g} s clip", "image": "per image", "vlm": "per 1-image judge call (1.7k in/300 out)",
            "text": "per call (3k in/1k out)"}[a.kind]
    lines = [f"{a.kind} models on OpenRouter, cheapest first ({unit}; estimates — real cost comes back as usage.cost):"]
    for r in rows:
        extra = []
        if a.kind == "video":
            extra = [f"${r['per_s']:.3f}/s @{r['resolution']}", r.get("durations") or "", r.get("note") or ""]
        elif a.kind == "image":
            extra = [f"refs<={r['refs_max']}" if r.get("refs_max") else "", r.get("note") or ""]
        else:
            extra = [f"${r['per_m_in']:g}/${r['per_m_out']:g} per M", r.get("note") or ""]
        lines.append(f"  ${r['est_usd']:<8.4f} {r['id']:<48} " + "  ".join(x for x in extra if x))
    return {"kind": a.kind, "models": rows, "text": "\n".join(lines)}


@_hinted
def cmd_estimate(a) -> dict:
    from . import models as reg
    if a.kind == "video":
        usd = reg.estimate_video(a.model, a.duration, a.res or "720p", generate_audio=not a.no_audio,
                                 video_input_s=a.video_input_s)
        txt = f"{a.model}: {a.duration:g} s @ {a.res or '720p'} ≈ ${usd:.4f}"
    elif a.kind == "edit":
        usd = reg.estimate_edit(a.model, 1 + a.refs)
        txt = (f"{a.model}: one image edit (the plate + {a.refs} reference(s)) ≈ ${usd:.4f} (conservative: the priciest "
               "listed endpoint, as `slop gen edit` budgets it)")
    else:
        usd = reg.estimate_image(a.model, a.res or "1K", a.quality, a.n, a.refs)
        txt = f"{a.model}: {a.n} image(s) @ {a.res or '1K'} ≈ ${usd:.4f}"
    return {"model": a.model, "est_usd": usd, "text": txt}


def _csv(vals: list[str] | None) -> list[str]:
    out: list[str] = []
    for v in vals or []:
        out += [x.strip() for x in str(v).split(",") if x.strip()]
    return out


@_hinted
def cmd_image(a) -> dict:
    from . import images
    pdir = resolve_project(a.project)
    if a.jobs:
        if a.prompt or a.prompt_file or a.plate or a.out or a.n != 1:
            raise SlopError("--jobs runs every job of the jobs file (each job has its own plate, prompt and n): drop the "
                            "prompt / --plate / --out / --n, or run one plate without --jobs")
        r = images.run_jobs(pdir, Path(_in(pdir, a.jobs)), only=_csv(a.only) or None, missing=a.missing, yes=a.yes,
                            model=a.model, quality=a.quality, resolution=a.res, refs=[_in_ref(pdir, x) for x in a.ref],
                            seed=a.seed, workers=a.workers)
        return r
    if a.only or a.missing:
        raise SlopError("--only / --missing pick jobs from a jobs file: add --jobs (default plates/jobs.json)")
    prompt = _read_text(a.prompt, _in(pdir, a.prompt_file), "prompt")
    from . import models as M, images as IM
    model = a.model or M.resolve(load_project(pdir), "image", IM.DEFAULT_MODEL, "image")
    if not (a.plate or a.out):
        raise SlopError("say where the image goes: --plate NAME (plates/cands/NAME/<k>.png) or --out FILE")
    out_dir = (pdir / "plates" / "cands" / a.plate) if a.plate else None
    r = images.generate(pdir, model=model, prompt=prompt, out_dir=out_dir, out=Path(_out(pdir, a.out)) if a.out else None,
                        aspect_ratio=a.aspect_ratio, resolution=a.res, quality=a.quality, n=a.n,
                        refs=[_in_ref(pdir, x) for x in a.ref], seed=a.seed,
                        yes=a.yes)
    cost = r["cost_usd"] if r["cost_usd"] is not None else r["est_usd"]
    return {**r, "text": f"{len(r['files'])} image(s) from {model} (${cost:.4f}): " + ", ".join(r["files"])}


@_hinted
def cmd_edit(a) -> dict:
    from . import imgedit
    pdir = resolve_project(a.project)
    instr = imgedit.compose(a.instruction, a.change, a.keep)
    proj = load_project(pdir)
    from . import models as M
    model = a.model or M.resolve(proj, "edit", imgedit.DEFAULT_MODEL, "image")
    note = None
    if a.medium:
        medium = imgedit.norm_medium(a.medium)
    else:
        medium, note = imgedit.project_medium(proj)
    r = imgedit.edit(pdir, Path(_in(pdir, a.src)), Path(_out(pdir, a.out)), instr, refs=[Path(_in(pdir, x)) for x in a.ref],
                     model=model, yes=a.yes, medium=medium)
    if note:
        r["warnings"] = [note] + list(r.get("warnings") or [])
    cost = r["cost_usd"] if r["cost_usd"] is not None else r["est_usd"]
    return {**r, "text": f"edited ({medium}) -> {r['out']} {r['size'][0]}x{r['size'][1]} (${cost:.3f}). Re-check it for new "
                         "canon errors." + "".join("\n  ! " + w for w in r.get("warnings") or [])}


@_hinted
def cmd_song(a) -> dict:
    from . import song
    pdir = resolve_project(a.project)
    prompt = _read_text(a.prompt, _in(pdir, a.prompt_file), "prompt")
    r = song.generate(pdir, prompt, kind="clip" if a.clip else "pro", model=a.model, yes=a.yes, as_song=a.as_song, seed=a.seed)
    return {**r, "text": f"Lyria song -> {r['mp3']}" + (f" (master: {r['song']})" if r.get("song") else "")
                         + f"; text -> {r['text_file']}. Licence: Google does not claim the output but grants no explicit "
                           "commercial licence — tell the user. Audition it before analysis."}


@_hinted
def cmd_host(a) -> dict:
    from . import clips, hosting, store
    from . import higgsfield as hf
    pdir = resolve_project(a.project)
    c = store.load(pdir, a.clip)
    hosted = c.setdefault("hosted", {})
    win = c.setdefault("window", {})
    role = a.role
    src = store.absp(pdir, win.get("wav") or win.get("file")) if role == "audio" else store.absp(pdir, c.get("start"))
    if a.url or a.media_id:
        rec = hosted.setdefault(role, {})
        if a.url:
            rec["url"] = hosting.check_https(a.url)
        if a.media_id:
            rec["media_id"] = a.media_id.strip()
        if a.url and src and src.is_file():
            rec["sha1"] = store.file_sha1(src)                      # submit refuses if the file changes after this
        if role == "audio" and a.url:
            win["url"] = rec["url"]; win["url_mode"] = "url"
        store.save(pdir, c)
        req = hf.refresh_uploads(pdir, c)
        return {"clip": c["id"], "hosted": hosted, "request_file": req,
                "text": f"{c['id']}: {role} hosted " + ", ".join(f"{k}={v}" for k, v in rec.items())
                        + (f" (updated {req})" if req else "")}
    if a.tunnel:
        what = "window audio" if role == "audio" else "start image"
        if not src or not src.is_file():
            raise SlopError(f"{c['id']} has no {what} to host: " + (f"slop clip set {c['id']} --recut" if role == "audio"
                                                                    else f"slop clip set {c['id']} --start IMAGE"))
        st = hosting.status()
        if not st["running"]:
            st = hosting.start(verify=not a.no_verify)
        url = clips.tunnel_host(pdir, c, role, src)
        store.save(pdir, c)
        req = hf.refresh_uploads(pdir, c)
        note = f"\n  ! {st['note']}" if st.get("note") else ""
        if role == "audio":
            text = f"{c['id']}: window hosted at {url} — keep the tunnel running until the job leaves 'pending'"
        else:
            text = (f"{c['id']}: start image hosted at {url} — for Higgsfield: media_import_url {{url, type: image}} gives "
                    f"its media_id (record it: slop gen host {c['id']} --role start --media-id ID); keep the tunnel "
                    "running until it is imported")
        if req:
            text += f"\n  updated {req}: its uploads now use media_import_url for the hosted file(s)"
        return {"clip": c["id"], "role": role, "url": url, "verified": st.get("verified"), "request_file": req,
                "text": text + note}
    if role != "audio":
        raise SlopError("--data-uri is for the audio window only; host the start image with --tunnel (or --url/--media-id)")
    if a.data_uri:
        if not a.experimental:
            raise SlopError("data: audio URLs are rejected by OpenRouter (verified 2026-10-01). Use --tunnel or --url. "
                            "(--data-uri --experimental keeps it for re-testing only)")
        win["url"] = None; win["url_mode"] = "data"
        store.save(pdir, c)
        return {"clip": c["id"], "text": f"{c['id']}: window will be sent as a data: URL (EXPERIMENTAL, known rejected)"}
    raise SlopError("say how to host: --url URL [--media-id ID] (Higgsfield upload), --tunnel, or --media-id ID")


@_hinted
def cmd_tunnel(a) -> dict:
    from . import hosting
    if a.action == "start":
        st = hosting.start(verify=not a.no_verify)
        txt = f"tunnel {'already ' if st.get('reused') else ''}up: {st['url']} (serving {st['share_dir']})"
        if st.get("verified") is True:
            txt += "; reachable through the public URL"
        elif st.get("note"):
            txt += "\n  ! " + st["note"]
        return {**st, "text": txt}
    if a.action == "stop":
        st = hosting.stop()
        return {**st, "text": "tunnel stopped" if st["stopped"] else "no tunnel was running"}
    st = hosting.status()
    if st["running"] and a.verify:
        st = {**st, **hosting.probe()}
    txt = f"tunnel running at {st['url']}" if st["running"] else "tunnel not running (slop gen tunnel start)"
    if st.get("verified") is True:
        txt += "; reachable through the public URL"
    elif st.get("note"):
        txt += f" ({st['note']})"
    return {**st, "text": txt}


# ================================================================================================= clip
def _pd(a) -> Path:
    return resolve_project(a.project)


@_hinted
def cmd_clip_new(a) -> dict:
    from . import clips
    pdir = _pd(a)
    r = clips.new(pdir, a.shot, a.kind, cid=a.id, t0=a.t0, t1=a.t1, song_t0=a.song_t0, duration=a.duration, start=_in(pdir, a.start),
                  frame=a.frame, style=a.style, provider=a.provider, model=a.model, resolution=a.res, force=a.force,
                  window_mode=a.window, words=a.words, aspect_ratio=a.aspect_ratio, reuse_start=a.reuse_start)
    return {"clip_id": r["clip"]["id"], "created": r["created"], "warnings": r.get("warnings", []), "clip": r["clip"],
            "text": r["text"]}


@_hinted
def cmd_clip_set(a) -> dict:
    from . import clips
    pdir = _pd(a)
    prompt = _read_text(a.prompt, _in(pdir, a.prompt_file), "prompt") if (a.prompt or a.prompt_file) else None
    ga = True if a.audio_on else (False if a.no_audio else None)
    r = clips.set_fields(pdir, a.clip, prompt=prompt, requote=a.requote, words=a.words, duration=a.duration, song_t0=a.song_t0,
                         resolution=a.res, model=a.model, provider=a.provider, frame=a.frame, start=_in(pdir, a.start),
                         refs=[_in(pdir, x) for x in a.ref], clear_refs=a.clear_refs, audio=_in(pdir, a.audio),
                         audio_mode=a.audio_mode, generate_audio=ga, recut=a.recut,
                         why=a.why, aspect_ratio=a.aspect_ratio, reuse_start=a.reuse_start, needed=[a.t0, a.t1] if (a.t0 is not None and a.t1 is not None) else None)
    return {"clip_id": a.clip, "changed": r["changed"], "warnings": r["warnings"], "text": r["text"]}


@_hinted
def cmd_clip_lock(a) -> dict:
    from . import clips
    r = clips.lock(_pd(a), a.clip)
    return {"clip_id": a.clip, "status": r["clip"]["status"], "text": r["text"]}


@_hinted
def cmd_clip_submit(a) -> dict:
    from . import clips
    r = clips.submit(_pd(a), a.clip, provider=a.provider, yes=a.yes, resolution=a.res, no_audio_ref=a.no_audio_ref,
                     experimental_data=a.experimental_data, resubmit_unknown=a.resubmit_unknown, dry=a.dry_run,
                     finalize_from=a.finalize_from, again=a.again,
                     hedra_cost=a.hedra_cost, hedra_currency=a.hedra_currency, quote_only=a.quote_only)
    r.pop("request", None)
    return r


@_hinted
def cmd_clip_poll(a) -> dict:
    from . import clips
    return clips.poll(_pd(a), a.clip or None, wait_s=a.wait, job_id=a.job_id)


@_hinted
def cmd_clip_ingest(a) -> dict:
    from . import clips
    pdir = _pd(a)
    return clips.ingest(pdir, a.clip, file=_in(pdir, a.file), url=a.url, job_id=a.job_id, credits=a.credits, pending=a.pending,
                        failed=a.failed, declined=a.declined, provider=a.provider, cost_usd=a.cost_usd)


@_hinted
def cmd_clip_sync(a) -> dict:
    from . import clips
    return clips.sync(_pd(a), a.clip, a.take, png=not a.no_png)


@_hinted
def cmd_clip_frame(a) -> dict:
    from . import clips
    pdir = _pd(a)
    return clips.take_frame(pdir, a.clip, a.at, take_n=a.take, out=_out(pdir, a.out))


@_hinted
def cmd_clip_coverage(a) -> dict:
    from ..sync.coverage import chain_report, project_report
    from ..sync.songdata import SongData
    from . import store
    pdir = _pd(a)
    song = SongData(pdir)
    if not song.has_words:
        raise SlopError("no aligned words (analysis/words.json): run slop analyze first")
    if a.clip:
        rows = [chain_report(pdir, store.load(pdir, c), song, a.min_gap) for c in a.clip]
        sung = sum(r["sung_s"] for r in rows); cov = sum(r["covered_s"] for r in rows)
        rep = {"clips": rows, "sung_s": round(sung, 3), "covered_s": round(cov, 3),
               "share": round(cov / sung, 3) if sung else None, "min_gap_s": a.min_gap}
    else:
        rep = project_report(pdir, song, store.all_clips(pdir), a.min_gap)
    lines = [f"sung seconds held in sync: {rep['covered_s']:.2f} / {rep['sung_s']:.2f}"
             + (f" ({rep['share']:.0%})" if rep.get("share") is not None else "") + f"  (gaps >= {a.min_gap:g} s)"]
    for r in rep["clips"]:
        st = ("not measured yet (slop clip sync)" if not r["measured"] and r["delivered"] else
              "no take yet" if not r["delivered"] else f"{r['covered_s']:.2f}/{r['sung_s']:.2f} s")
        lines.append(f"  {r['root']:<12} {st}" + (f"  gaps {r['gaps']}" if r["gaps"] and r["measured"] else "")
                     + (f"  cut away {r['fallback']}" if r["fallback"] else ""))
    return {**rep, "text": "\n".join(lines)}


@_hinted
def cmd_clip_cover(a) -> dict:
    from ..sync.coverage import propose
    from ..sync.songdata import SongData
    from . import clips, store
    pdir = _pd(a)
    song = SongData(pdir)
    root = store.load(pdir, a.clip)
    if root.get("parent"):
        root = store.load(pdir, root["parent"])
    if root.get("kind") != "sung":
        raise SlopError(f"{root['id']} is a motion clip: covers are for sung clips")
    pr = propose(pdir, root, song, min_gap=a.min_gap, max_covers=a.max_covers)
    lines = [f"{root['id']}: {pr['covered_s']:.2f}/{pr['sung_s']:.2f} sung s in sync"
             + (f", gaps {pr['gaps']}" if pr["gaps"] else ", no gaps — nothing to cover")]
    if pr.get("note"):
        lines.append("  " + pr["note"])
    for pc in pr.get("pending_covers") or []:
        lines.append(f"  gap {pc['gap']} already has cover(s) {', '.join(pc['covers'])} waiting for a take + sync "
                     "(submit/poll/sync them first)")
    made = []
    for p in pr["proposals"]:
        sf = p.get("start_frame") or {}
        lines.append(f"  {p['id']}: window {p['song_t0']:.2f} s +{p['duration']} s, words \"{p['words']}\", start = frame "
                     f"{sf.get('frame')} of {sf.get('clip')} (t {sf.get('t')} s)" + (f" ! {p['start_problem']}" if p.get("start_problem") else ""))
        if a.make:
            m = clips.make_cover(pdir, root["id"], p, lock_it=a.lock, start=a.start)
            made.append(m)
            lines.append(f"    written {m['id']} ({'locked' if m['locked'] else 'draft'}; {m['prompt_source']})")
    if pr.get("exhausted"):
        r2 = store.load(pdir, root["id"])
        if a.make:
            r2["fallback"] = pr["fallback"]; store.save(pdir, r2)
        lines.append(f"  covers used up ({a.max_covers}): cut away in the edit for {pr['fallback']} (no lip-sync model fallback)")
    if pr["proposals"] and not a.make:
        lines.append(f"  write them: slop clip cover {root['id']} --make [--lock]")
    return {**pr, "made": made, "text": "\n".join(lines)}


@_hinted
def cmd_clip_list(a) -> dict:
    from . import clips
    return clips.listing(_pd(a))


@_hinted
def cmd_clip_status(a) -> dict:
    from . import clips, store
    pdir = _pd(a)
    c = store.load(pdir, a.clip)
    r = clips.row(c)
    lines = [f"{c['id']} · {c.get('kind')} · {c.get('status')} · {c.get('provider')} {c.get('model')} · shot {c.get('shot')}",
             f"window {c.get('song_t0')} s +{c['body'].get('duration')} s ({(c.get('window') or {}).get('mode')}, "
             f"{(c.get('window') or {}).get('file')}) · needed {c.get('needed')} · start {c.get('start')} · frame {c.get('frame')}",
             f"words: {c.get('words')!r}", f"estimate: {clips.describe_cost(c)}", "prompt:", c["body"].get("prompt", "")]
    for tk in c.get("takes") or []:
        sy = tk.get("sync") or {}
        res = (tk.get("body") or {}).get("resolution")
        lines.append(f"take {tk['n']}: {tk.get('provider')} {tk.get('status')} {tk.get('file') or ''}"
                     + (f" {res}{' draft' if (tk.get('body') or {}).get('draft') else ''}" if res else "")
                     + (f" (finalize of take {tk['finalize_of']})" if tk.get("finalize_of") else "")
                     + (" NEEDS SYNC: slop clip sync " + c["id"] + f" --take {tk['n']}"
                        if tk.get("needs_sync") and tk.get("status") == "delivered" else "")
                     + (f" lag {sy.get('lag_s')} ncc {sy.get('ncc')} synced {sy.get('synced')} cut {sy.get('cut_at')}" if sy else "")
                     + (f" error: {tk.get('error')[:120]}" if tk.get("error") else ""))
    probs = clips.lock_problems(pdir, c) if c.get("status") == "draft" else []
    if probs:
        lines.append("to lock: " + "; ".join(probs))
    return {"clip": c, "summary": r, "lock_problems": probs, "text": "\n".join(lines)}


# ================================================================================================= register
def register(sub) -> None:
    g = sub.add_parser("gen", help="generation: models + prices, images, image edits, songs (Lyria), hosting")
    gs = g.add_subparsers(dest="gen_cmd", metavar="ACTION")

    p = gs.add_parser("models", help="OpenRouter models cheapest-first with per-call estimates")
    p.add_argument("--kind", choices=["image", "video", "vlm", "text"], default="video")
    p.add_argument("--res", default=None, help="video: 480p|720p|1080p (default 720p); image: 1K|2K|4K")
    p.add_argument("--duration", type=float, default=5.0, help="video clip seconds for the estimate (default 5)")
    p.add_argument("--quality", default=None, help="image quality for token-priced models (low|medium|high)")
    p.add_argument("--limit", type=int, default=25); p.add_argument("--refresh", action="store_true")
    p.add_argument("--no-free", action="store_true", help="hide $0 models (free tiers are rate-limited: 20/min, 50-1000/day)")
    p.set_defaults(func=cmd_models)

    p = gs.add_parser("estimate", help="price of one call for a model")
    p.add_argument("--model", required=True)
    p.add_argument("--kind", choices=["video", "image", "edit"], default="video",
                   help="edit = one `slop gen edit` call (the plate + --refs references)")
    p.add_argument("--duration", type=float, default=5.0); p.add_argument("--res", default=None)
    p.add_argument("--quality", default=None); p.add_argument("--n", type=int, default=1); p.add_argument("--refs", type=int, default=0)
    p.add_argument("--no-audio", action="store_true"); p.add_argument("--video-input-s", type=float, default=0.0)
    p.set_defaults(func=cmd_estimate)

    p = gs.add_parser("image", help="generate image(s) via OpenRouter (spends; needs --yes over confirm_over_usd); "
                                    "--jobs runs the plates/jobs.json batch (dry run without --yes)")
    p.add_argument("prompt", nargs="?"); p.add_argument("--prompt-file")
    p.add_argument("--jobs", nargs="?", const="plates/jobs.json", default=None,
                   help="run the API plate jobs from this file (default plates/jobs.json): one estimate, one --yes, "
                        "resumable (re-run continues where it stopped)")
    p.add_argument("--only", action="append", default=[], help="--jobs: only these plates (P1,P2 or repeat the flag)")
    p.add_argument("--missing", action="store_true", help="--jobs: skip plates that already have any candidate image")
    p.add_argument("--workers", type=int, default=4, help="--jobs: calls in parallel (default 4, max 8)")
    p.add_argument("--model", help="default: project models.image, else openai/gpt-image-2")
    p.add_argument("--aspect-ratio", default="16:9"); p.add_argument("--res", default=None, help="512|1K|2K|4K")
    p.add_argument("--quality", default=None); p.add_argument("--n", type=int, default=1)
    p.add_argument("--ref", action="append", default=[],
                   help="reference image (repeatable): an image file, an https or data: URL, or a plate candidate "
                        "PLATE[:K] (no K: the plate's pick); with --jobs added to every job's own refs")
    p.add_argument("--seed", type=int); p.add_argument("--plate", help="write to plates/cands/PLATE/<k>.<ext>")
    p.add_argument("--out", help="explicit output file"); p.add_argument("--yes", action="store_true")
    p.set_defaults(func=cmd_image)

    p = gs.add_parser("edit", help='fix a plate with the edit model: "Change only X … Keep Y" + the keep-everything clause')
    p.add_argument("src"); p.add_argument("out"); p.add_argument("instruction", nargs="?")
    p.add_argument("--change", help='what changes (composes "Change only X.")'); p.add_argument("--keep", help="what must stay")
    p.add_argument("--ref", action="append", default=[], help="reference image after the plate (\"the second image\")")
    p.add_argument("--medium", choices=["photo", "illustration", "cel"],
                   help="how the edit is worded (default project look.medium, else inferred from the lead canon, else "
                        "photo); illustrated / cel-shaded plates: illustration (cel = illustration)")
    p.add_argument("--model"); p.add_argument("--yes", action="store_true")
    p.set_defaults(func=cmd_edit)

    p = gs.add_parser("song", help="generate a song with Lyria via OpenRouter (~$0.08; --clip 30 s ~$0.04)")
    p.add_argument("--prompt"); p.add_argument("--prompt-file"); p.add_argument("--clip", action="store_true")
    p.add_argument("--model"); p.add_argument("--seed", type=int)
    p.add_argument("--as-song", action="store_true", help="also write audio/song.wav (44.1 kHz stereo master)")
    p.add_argument("--yes", action="store_true")
    p.set_defaults(func=cmd_song)

    p = gs.add_parser("host", help="give a clip's window (or start image) an HTTPS URL for OpenRouter / Higgsfield "
                                   "media_import_url, or record a media_id",
                      description="--tunnel puts the window (--role audio, default) or the start image (--role start) on "
                                  "the quick tunnel (starting it when needed); the Higgsfield bot then imports it with "
                                  "media_import_url {url, type}. clip submit does this itself while the tunnel runs.")
    p.add_argument("clip"); p.add_argument("--url"); p.add_argument("--media-id")
    p.add_argument("--role", default="audio", choices=["audio", "start"]); p.add_argument("--tunnel", action="store_true")
    p.add_argument("--no-verify", action="store_true", help="--tunnel: skip the reachability probe when it starts the tunnel")
    p.add_argument("--data-uri", action="store_true"); p.add_argument("--experimental", action="store_true")
    p.set_defaults(func=cmd_host)

    p = gs.add_parser("tunnel", help="Cloudflare quick tunnel for HTTPS hosting (start|stop|status)")
    p.add_argument("action", choices=["start", "stop", "status"])
    p.add_argument("--no-verify", action="store_true", help="start: skip fetching a probe file through the public URL")
    p.add_argument("--verify", action="store_true", help="status: fetch a probe file through the public URL")
    p.set_defaults(func=cmd_tunnel)

    c = sub.add_parser("clip", help="video clips: new, set, lock, submit, poll, ingest, sync, frame, coverage, cover, list, status")
    cs = c.add_subparsers(dest="clip_cmd", metavar="ACTION")

    p = cs.add_parser("new", help="draft clips/<id>.json for a storyboard shot (window, exact words, prompt scaffold)")
    p.add_argument("shot"); p.add_argument("--kind", choices=["sung", "motion"], required=True)
    p.add_argument("--id"); p.add_argument("--t0", type=float, help="needed span start (default: the shot's t0)")
    p.add_argument("--t1", type=float, help="needed span end (default: the shot's t1)")
    p.add_argument("--song-t0", type=float, help="window start (default: word gap before the shot / the shot start)")
    p.add_argument("--duration", type=int); p.add_argument("--start", help="start image (default: the plate's pick)")
    p.add_argument("--reuse-start", action="store_true", help="allow an intentional repeat of another clip's start image")
    p.add_argument("--frame", choices=["ref", "first"], help="reference mode (default) or first-frame mode (motion only)")
    p.add_argument("--style", choices=["screenplay", "short"], default=None,
                   help="prompt grammar (default by kind: sung short, motion screenplay; docs/60-clips.md §4)")
    p.add_argument("--window", choices=["clean", "vocal", "mix"],
                   help="@Audio1: clean vocal (sung default), raw vocal stem, or the mix (motion default)")
    p.add_argument("--provider", choices=["openrouter", "higgsfield", "hedra"]); p.add_argument("--model")
    p.add_argument("--aspect-ratio", choices=["16:9", "9:16", "1:1", "4:3", "3:4", "21:9", "adaptive"],
                   help="output shape; Hedra defaults to adaptive to the reference image")
    p.add_argument("--res", choices=["480p", "720p", "1080p"]); p.add_argument("--force", action="store_true")
    p.add_argument("--words", help="sung: quote only these words (her words only; the clean window holds just them)")
    p.set_defaults(func=cmd_clip_new)

    p = cs.add_parser("set", help="change a clip (back to draft; re-lock after)")
    p.add_argument("clip"); p.add_argument("--prompt"); p.add_argument("--prompt-file")
    p.add_argument("--requote", action="store_true", help="quote EVERY word of the window in the sung head")
    p.add_argument("--words", help="quote only these words (sung, in order, inside the window); re-cuts the clean window "
                                   "to hold just them")
    p.add_argument("--duration", type=int); p.add_argument("--song-t0", type=float)
    p.add_argument("--t0", type=float); p.add_argument("--t1", type=float)
    p.add_argument("--res", choices=["480p", "720p", "1080p"]); p.add_argument("--model")
    p.add_argument("--provider", choices=["openrouter", "higgsfield", "hedra"]); p.add_argument("--frame", choices=["ref", "first"])
    p.add_argument("--aspect-ratio", choices=["16:9", "9:16", "1:1", "4:3", "3:4", "21:9", "adaptive"],
                   help="output shape; Hedra defaults to adaptive to the reference image")
    p.add_argument("--reuse-start", action="store_true", help="allow --start to reuse another clip's image")
    p.add_argument("--start"); p.add_argument("--ref", action="append", default=[]); p.add_argument("--clear-refs", action="store_true")
    p.add_argument("--audio", help="use this file as the window audio (e.g. the clean vocal window)")
    p.add_argument("--audio-mode", choices=["clean", "vocal", "mix"]); p.add_argument("--recut", action="store_true")
    p.add_argument("--no-audio", action="store_true", help="generate_audio false (motion clips after a copyright refusal)")
    p.add_argument("--audio-on", action="store_true"); p.add_argument("--why")
    p.set_defaults(func=cmd_clip_set)

    p = cs.add_parser("lock", help="draft -> locked (checks: start, window, no [[slots]], exact quoted words)")
    p.add_argument("clip"); p.set_defaults(func=cmd_clip_lock)

    p = cs.add_parser("submit", help="spend: OpenRouter job, or the Higgsfield request file for the bot (locked + --yes)")
    p.add_argument("clip"); p.add_argument("--provider", choices=["openrouter", "higgsfield", "hedra"])
    p.add_argument("--yes", action="store_true"); p.add_argument("--res", choices=["480p", "720p", "1080p"])
    p.add_argument("--no-audio-ref", action="store_true", help="motion only: submit without the song window")
    p.add_argument("--resubmit-unknown", action="store_true",
                   help="the last submit got no clear answer and no job shows at openrouter.ai/activity: submit again")
    p.add_argument("--dry-run", action="store_true",
                   help="show the exact request (mode, references, prompt) and the estimate; nothing is sent or spent")
    p.add_argument("--finalize-from", type=int, metavar="TAKE",
                   help="Higgsfield: finalize this kept 480p draft take at 1080p (draft_job_id; get_cost first; ~12 "
                        "credits/s); a sung clip's finalized take must be measured again with clip sync")
    p.add_argument("--again", action="store_true",
                   help="with --finalize-from: a SECOND paid finalize of a draft that was already finalized (only when "
                        "the owner asks; the first finalized take is kept)")
    p.add_argument("--experimental-data", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--quote-only", action="store_true", help="Hedra: upload/prepare a free quote; no generation or reservation")
    p.add_argument("--hedra-cost", type=float, help="MCP: fresh Hedra estimate cost")
    p.add_argument("--hedra-currency", choices=["USD", "credits"], help="MCP: currency from the same estimate")
    p.set_defaults(func=cmd_clip_submit)

    p = cs.add_parser("poll", help="check OpenRouter jobs (all in flight when no CLIP); download completed takes")
    p.add_argument("clip", nargs="*"); p.add_argument("--wait", type=float, default=0.0, help="seconds to keep polling")
    p.add_argument("--job-id", help="attach this job (from openrouter.ai/activity) to CLIP's take whose outcome is unknown")
    p.set_defaults(func=cmd_clip_poll)

    p = cs.add_parser("ingest", help="add a take from a file or a result URL (Higgsfield), or mark a request pending/failed")
    p.add_argument("clip"); p.add_argument("--file"); p.add_argument("--url"); p.add_argument("--job-id")
    p.add_argument("--credits", type=float); p.add_argument("--provider", choices=["higgsfield", "openrouter", "hedra", "manual"])
    p.add_argument("--pending", action="store_true"); p.add_argument("--failed"); p.add_argument("--declined")
    p.add_argument("--cost-usd", type=float, help="Hedra: confirmed net job cost in USD (including 0 for a refund)")
    p.set_defaults(func=cmd_clip_ingest)

    p = cs.add_parser("sync", help="measure lip sync of a take (avsync) -> take.sync + PNG")
    p.add_argument("clip"); p.add_argument("--take", type=int); p.add_argument("--no-png", action="store_true")
    p.set_defaults(func=cmd_clip_sync)

    p = cs.add_parser("frame", help="a still from a take at a song time (default: its last in-sync frame) to start a clip from")
    p.add_argument("clip"); p.add_argument("--at", type=float, help="song time in seconds (default: last in-sync frame)")
    p.add_argument("--take", type=int); p.add_argument("--out", help="output image (default clips/CLIP/take-N-frame-F.png)")
    p.set_defaults(func=cmd_clip_frame)

    p = cs.add_parser("coverage", help="sung seconds held in sync (all sung clips, or the given chains)")
    p.add_argument("clip", nargs="*"); p.add_argument("--min-gap", type=float, default=.6)
    p.set_defaults(func=cmd_clip_coverage)

    p = cs.add_parser("cover", help="propose (and --make) cover clips for a chain's uncovered sung gaps")
    p.add_argument("clip"); p.add_argument("--make", action="store_true"); p.add_argument("--lock", action="store_true")
    p.add_argument("--max-covers", type=int, default=2); p.add_argument("--min-gap", type=float, default=.6)
    p.add_argument("--start", help="explicit start image for the cover (default: the frame at the cut)")
    p.set_defaults(func=cmd_clip_cover)

    p = cs.add_parser("list", help="all clips, status and expected spend"); p.set_defaults(func=cmd_clip_list)
    p = cs.add_parser("status", help="one clip in full (prompt, takes, sync, lock problems)")
    p.add_argument("clip"); p.set_defaults(func=cmd_clip_status)

    def _need(parser):
        return lambda a: (_ for _ in ()).throw(SlopError(f"missing action: slop {parser} --help"))
    g.set_defaults(func=_need("gen")); c.set_defaults(func=_need("clip"))

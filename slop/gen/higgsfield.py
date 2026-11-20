"""Higgsfield path: the CLI writes a request file; the BOT executes it with its Higgsfield connector (MCP); the CLI ingests
the result. (Template users have the connector, not an API key — so the CLI never calls Higgsfield itself.)

Request shape (the one that ran 81 takes in production, field rules verbatim):
  model "seedance_2_5"; mode "omni_reference" ALWAYS explicit (the model default is t2v and silently ignores media);
  resolution "720p" (7 credits/s) or "480p" + draft:true (3 credits/s, can be finalized to 1080p within 7 days);
  aspect_ratio explicit; duration integer 4–8; medias [{role, value: media_id}] ordered start_image, image_references,
  video_references, audio_references — a start_image is @Image1, so a reference beside it is @Image2 (the prompt is
  renumbered for that); generate_audio omitted (= true) for sung clips, false only for motion clips; use_unlim omitted
  (an `unlim_choice` reply is a question for the user, never answered for them).
Preflight: estimate_video_cost {params} with the request's own params returns the credits and submits nothing (the
connector's generate_video no longer takes get_cost, and generate_video_batch never did; images: estimate_image_cost,
audio: estimate_audio_cost). The request file keeps that call as `estimate` {tool, params}; a file written before 0.3.7
has a `get_cost` object instead, which read_request reads as the same quote. Submit verbatim with generate_video_batch
{requests:[...]} — never edit the prompt; write the job id down immediately; on a transport timeout the outcome is
unknown: do NOT resubmit (check `transactions` first; retry only once the outcome is known).
Failures: "failed" with no reason = the silent input filter (refunded; identical resubmits fail — reword without changing
the beat); "nsfw" = the output was flagged (refunded; change the staging, not the image); a preset recommendation
instead of a job = resubmit that item once with declined_preset_id set to the named preset.
Result URLs are public CloudFront links (no auth): `slop clip ingest CLIP --url URL --job-id ID [--credits N]`.
Uploads (verified 2026-10-01): media_import_url on an https URL works for images AND audio and is preferred; `slop clip
submit` puts the start image, references and window on the running quick tunnel itself, and `slop gen host CLIP --role
start|audio --tunnel` does it later (both fill uploads[].https_url, method "media_import_url", in the open request
file). The fallback media_upload presigned PUT needs the signed header `If-None-Match: *` or it answers 403.
Finalize (`slop clip submit CLIP --finalize-from TAKE`): a kept 480p draft (draft:true) can be finalized at 1080p within 7
days with draft_job_id = the draft's job id; observed 12 credits/s (estimate_video_cost is the truth). A finalize may
not keep the draft's lip sync, so a sung clip's finalized take must be measured again (`slop clip sync`).
Credits per second (seedance_2_5, observed 2026-09/10; estimate_video_cost is the truth): 480p draft 3, 720p 7, 1080p 12.
Refused or failed, never left "requested" (Studio run: a refused finalize read "submitted" and its 48 credits stayed in
the ledger, 114 logged vs 66 real): when estimate_video_cost or generate_video_batch answers an error instead of a price
/ a job id, or the balance is too low, nothing was charged and the bot records it at once: `slop clip ingest CLIP --failed
"rejected: <the reply, verbatim>"` (the REJECTED step comes after the unlim_choice / timeout step: neither of those is a
refusal, and a timeout may have run and been charged); a job that ends failed / nsfw: `--failed "<reason>"`. The ledger then
records that take as failed with 0 credits (ledger.record turns the refund into a settlement) and `slop status` shows
a finalize as rejected / failed while the clip keeps its draft. A take delivered free (use_unlim) is ingested with
`--credits 0`.
Motion clips on Higgsfield default to a start_image (`slop clip new … --provider higgsfield`: frame "first") plus the
audio_references window — the second video ran its Higgsfield motion clips that way (exact plate composition, the beat
still conditioned). OpenRouter's "a first frame drops the audio" limit does not apply here.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

from ..config import SlopError
from . import store

MODEL = "seedance_2_5"
CREDITS_PER_S = {"480p": 3, "720p": 7, "1080p": 12}
USD_PER_CREDIT = 0.0526                       # 2,000-credit pack price (2026-10-01), for the confirm-over-$ gate only
ROLES = ("start_image", "image_references", "video_references", "audio_references")
VIDEO_ESTIMATE = "estimate_video_cost"        # the connector's free quote: generate_video's own params, submits nothing


def credits(duration: int, resolution: str) -> float:
    return float(CREDITS_PER_S.get(resolution, 7) * int(duration))


def renumber_images(prompt: str, offset: int) -> str:
    """@ImageN -> @Image(N+offset) (a start_image takes @Image1 on Higgsfield)."""
    if not offset:
        return prompt
    return re.sub(r"@Image(\d+)", lambda m: f"@Image{int(m.group(1)) + offset}", prompt)


def placeholder(cid: str, role: str, k: int) -> str:
    return f"<<MEDIA_ID:{cid}__{role}__{k}>>"


UPLOAD_STEP = (
    "UPLOAD (free), one item of `uploads` at a time: method media_import_url (the item has an https_url) -> call "
    "media_import_url {{url: https_url, type}} (preferred: one call, nothing to PUT; a tunnel URL works only after "
    "`slop gen tunnel status --verify` says 'reachable through the public URL', and while it keeps running). Method media_upload (no https_url) -> better first: slop gen tunnel start, "
    "then slop gen host {cid} --role start --tunnel and slop gen host {cid} --tunnel (they add https_url to this file); "
    "only if the tunnel cannot start: media_upload {{filename}}, PUT the file bytes to upload_url with curl ADDING the "
    "header -H 'If-None-Match: *' (a signed header: without it the PUT answers 403), check it printed 200, then "
    "media_confirm {{type, media_ids:[id]}} (images and audio in SEPARATE media_confirm calls). Put each media_id in "
    "place of its placeholder in request.params.medias, and record it: slop gen host {cid} --role start|audio "
    "--media-id ID.")


def _stamp(text: str, pdir: Path) -> str:
    try:
        from .hints import stamp_text
    except ImportError:
        return text
    return stamp_text(text, pdir)


def upload_method(rec: dict, src: Path | None) -> dict:
    """How the bot gets a media_id for one upload: media_import_url on a live https URL of the CURRENT file (a tunnel
    URL only while that tunnel runs; a recorded sha1 must match the file), else media_upload (+ the signed header)."""
    from . import hosting
    url = (rec or {}).get("url")
    ok = bool(url) and str(url).startswith("https://") and hosting.url_is_live_tunnel(url)
    if ok and rec.get("sha1") and src is not None and Path(src).is_file() and store.file_sha1(Path(src)) != rec["sha1"]:
        ok = False                                                 # the file changed after it was hosted
    if ok:
        return {"method": "media_import_url", "https_url": url}
    return {"method": "media_upload", "https_url": None, "curl_header": "If-None-Match: *"}


def estimate(params: dict) -> dict:
    """The request file's price check: estimate_video_cost with exactly the params the batch submits (no get_cost flag:
    the connector's generate_video no longer takes it, and the estimate tool submits nothing)."""
    return {"tool": VIDEO_ESTIMATE, "params": {k: v for k, v in params.items() if k != "get_cost"}}


def _preflight_step(cr: float) -> str:
    return (f"PREFLIGHT (free): {VIDEO_ESTIMATE} {{params: <request.params, unchanged>}} (= the `estimate` object in "
            f"this file; it submits nothing) — expect about {cr:g} credits; stop and tell the user if it differs. "
            "medias[].value must be a media_id (from media_import_url, or media_upload + media_confirm; never an https "
            "URL).")


def _finalize_preflight_step(cr: float) -> str:
    return (f"PREFLIGHT (free): {VIDEO_ESTIMATE} {{params: <request.params, unchanged>}} (= the `estimate` object; it "
            f"submits nothing) - expect about {cr:g} credits (finalize prices are not published: {VIDEO_ESTIMATE} is "
            "the truth). If it differs: stop and tell the user. If it refuses the finalize instead of a price (asks for "
            "medias, refuses the draft_job_id, any error): do not invent other params and do not submit - REJECTED "
            "below.")


# the words of a pre-0.3.7 REJECTED step that named the old generate_video + get_cost step
_OLD_WORDS = (("get_cost or the batch refuses", f"{VIDEO_ESTIMATE} or the batch refuses"),
              ("after get_cost", "after the estimate"))


def upgrade_request(req: dict, pdir: Path | None = None) -> dict:
    """A request file written before 0.3.7 priced itself with generate_video + get_cost, which the connector no longer
    takes: its `get_cost` object is read as `estimate` (the same params, without the flag) and its PREFLIGHT and
    REJECTED steps name estimate_video_cost, so an old project's open request still runs. A current file: unchanged."""
    old = req.pop("get_cost", None)
    if old is not None and "estimate" not in req:
        prm = (old.get("params") if isinstance(old, dict) else None) or (req.get("request") or {}).get("params") or {}
        req["estimate"] = estimate(prm)
    if not isinstance(req.get("how_to_run"), list):
        return req
    cr = float(req.get("expected_credits") or 0)
    pre = _finalize_preflight_step(cr) if req.get("kind") == "finalize" else _preflight_step(cr)
    steps = []
    for s in req["how_to_run"]:
        if isinstance(s, str) and "get_cost" in s:
            if s.startswith("PREFLIGHT"):
                s = _stamp(pre, pdir) if pdir else pre
            else:
                for a, b in _OLD_WORDS:
                    s = s.replace(a, b)
        steps.append(s)
    req["how_to_run"] = steps
    return req


def read_request(p: Path, pdir: Path | None = None) -> dict | None:
    """A request file as this version writes it (an older file's generate_video + get_cost step is upgraded:
    upgrade_request); None when it is missing or not a JSON object."""
    import json
    try:
        req = json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return upgrade_request(req, pdir) if isinstance(req, dict) else None


def refresh_uploads(pdir: Path, clip: dict) -> str | None:
    """After `slop gen host` recorded a URL or a media_id: update the open request file of the clip's requested
    Higgsfield take (its uploads' method/https_url, and a media_id in place of its placeholder). Returns its path.
    A file written before 0.3.7 is rewritten in the current shape (read_request)."""
    import json
    tk = next((t for t in reversed(clip.get("takes") or []) if t.get("provider") == "higgsfield"
               and t.get("status") == "requested" and t.get("request_file")), None)
    if not tk:
        return None
    p = store.absp(pdir, tk["request_file"])
    if not p or not p.is_file():
        return None
    req = read_request(p, pdir)
    if req is None:
        return None
    hosted = clip.get("hosted") or {}
    win = clip.get("window") or {}
    medias = ((req.get("request") or {}).get("params") or {}).get("medias") or []
    cost_medias = ((req.get("estimate") or {}).get("params") or {}).get("medias") or []
    keep = []
    for u in req.get("uploads") or []:
        rec = hosted.get(u.get("hosted_key") or "") or {}
        if rec.get("media_id"):                                    # known now: straight into medias
            for m in medias + cost_medias:
                if m.get("value") == u.get("placeholder"):
                    m["value"] = rec["media_id"]
            continue
        key = u.get("hosted_key")
        src = store.absp(pdir, win.get("wav") or win.get("file")) if key == "audio" else Path(u.get("file") or "")
        u.update(upload_method(rec, src))
        keep.append(u)
    req["uploads"] = keep
    p.write_text(json.dumps(req, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return store.rel(pdir, p)


FINALIZE_CREDITS_PER_S = 12        # observed: finalizing 10 s / 12 s drafts at 1080p cost 120 / 144 credits
FINALIZE_DAYS = 7


def build_finalize(pdir: Path, clip: dict, draft: dict, *, index: int = 0) -> dict:
    """The request that finalizes a 480p draft take at 1080p (`draft_job_id`): the draft's own model, mode, prompt,
    duration and aspect, no medias (the draft job carries them). estimate_video_cost is the truth for the price."""
    cid = clip["id"]
    b = draft.get("body") or {}
    dur = int(b.get("duration") or (clip.get("body") or {}).get("duration") or 5)
    params = {"model": b.get("model") or MODEL, "mode": b.get("mode") or "omni_reference", "draft_job_id": draft["id"],
              "resolution": "1080p", "aspect_ratio": b.get("aspect_ratio") or (clip.get("body") or {}).get("aspect_ratio")
              or "16:9", "duration": dur, "prompt": b.get("prompt") or (clip.get("body") or {}).get("prompt") or ""}
    if b.get("generate_audio") is False:
        params["generate_audio"] = False
    cr = float(FINALIZE_CREDITS_PER_S * dur)
    sung = clip.get("kind") == "sung"
    steps = [
        _finalize_preflight_step(cr),
        "SUBMIT (spends credits): generate_video_batch {requests: [request]} with every key and value VERBATIM. Then record "
        f"the job id at once: slop clip ingest {cid} --job-id JOB_ID --pending",
        "If the reply is an `unlim_choice` question (nothing was submitted): ask the user, then send the same request with "
        "use_unlim set to their answer (never choose for them). On a transport timeout the outcome is unknown: do NOT "
        "resubmit and do NOT record it as rejected; check `transactions` first (a charge or a job there: it ran, record "
        "that job id); retry only once the outcome is known.",
        f"REJECTED (an error instead of a price or a job id: {VIDEO_ESTIMATE} or the batch refuses the finalize, or the "
        f"balance is too low; NOT an unlim_choice question or a timeout): nothing was charged and the draft stays the "
        f"clip's take. Tell the user and record it at once, never leave it requested (the ledger then counts 0, status "
        f"shows it rejected): slop clip ingest {cid} --failed \"rejected: <the reply, verbatim>\" (the user says not to "
        "send it after the estimate: --failed \"rejected: not sent, <why>\"). Then stop: do not re-lock or resubmit the "
        "clip (any retry advice that command prints is for a new take, not for a finalize).",
        "POLL: jobs_wait {jobs:[{index:0, job_id}], timeout_seconds:15}; repeat after poll_after_seconds until terminal.",
        f"INGEST: completed -> slop clip ingest {cid} --url RESULT_URL --job-id JOB_ID --credits <the credits really "
        f"charged: 0 if it ran on use_unlim>; failed -> slop clip ingest {cid} --failed \"<the reason, verbatim>\" "
        "(finalize failures are refunded).",
    ]
    if sung:
        steps.append(f"REQUIRED after the ingest: slop clip sync {cid} - a finalize may not keep the draft's lip sync, "
                     "and the edit uses the newest take at once with no lag correction until it is measured: sync it "
                     "before edit edl or render.")
    steps = [_stamp(s, pdir) for s in steps]
    return {"clip": cid, "provider": "higgsfield", "kind": "finalize", "created": store.now(), "finalize_of": draft["n"],
            "draft_job_id": draft["id"], "expected_credits": cr, "expected_usd_at_pack_price": round(cr * USD_PER_CREDIT, 2),
            "how_to_run": steps, "uploads": [], "request": {"index": index, "params": params},
            "estimate": estimate(params),
            "rules": ["finalize only a draft that was kept (sung: a measured copy)", "within 7 days of the draft",
                      "a refused finalize is recorded at once (clip ingest --failed \"rejected: ...\"), never left requested",
                      "never set use_unlim yourself", "measure the finalized take (clip sync) before edit edl or render",
                      "never finalize the same draft twice unless the owner asks (--again)"]}


def draft_age_days(take: dict) -> float | None:
    import time
    for k in ("submitted", "delivered"):
        s = take.get(k)
        if not s:
            continue
        try:
            return (time.time() - time.mktime(time.strptime(str(s)[:19], "%Y-%m-%dT%H:%M:%S"))) / 86400
        except (ValueError, OverflowError):
            continue
    return None


def build_request(pdir: Path, clip: dict, *, resolution: str = "720p", index: int = 0) -> dict:
    cid = clip["id"]
    body = clip.get("body") or {}
    dur = int(body.get("duration") or 5)
    if not 4 <= dur <= 8:
        raise SlopError(f"Higgsfield windows are 4–8 s; {cid} is {dur} s: slop clip set {cid} --duration 4..8")
    if resolution not in CREDITS_PER_S:
        raise SlopError("--res must be 480p (draft), 720p or 1080p for Higgsfield")
    start = clip.get("start")
    if not start:
        raise SlopError(f"{cid} has no start image")
    hosted = clip.get("hosted") or {}
    first = clip.get("frame") == "first"
    files: list[tuple[str, str | None, str]] = []                  # (role, local path, hosted key)
    files.append(("start_image" if first else "image_references", start, "start"))
    for i, r in enumerate(clip.get("refs") or []):
        files.append(("image_references", r, f"ref{i}"))
    for i, v in enumerate(clip.get("videos") or []):
        files.append(("video_references", v, f"video{i}"))
    win = clip.get("window") or {}
    if win.get("file") or (hosted.get("audio") or {}).get("media_id"):
        files.append(("audio_references", win.get("mp3") or win.get("file"), "audio"))
    medias, uploads, counters = [], [], {r: 0 for r in ROLES}
    for role in ROLES:                                             # fixed order: start, images, videos, audio
        for r, path, key in files:
            if r != role:
                continue
            k = counters[role]; counters[role] += 1
            rec = hosted.get(key) or {}
            if rec.get("media_id"):
                medias.append({"role": role, "value": rec["media_id"]})
                continue
            ap = store.absp(pdir, path) if path else None
            if not ap or not ap.is_file():
                raise SlopError(f"{cid}: the {role} file is missing ({path}); fix the clip (slop clip set) first")
            ext = ap.suffix.lower()
            ph = placeholder(cid, role, k)
            kind = "audio" if role == "audio_references" else ("video" if role == "video_references" else "image")
            src = store.absp(pdir, win.get("wav") or win.get("file")) if key == "audio" else ap   # what gen host hosts
            uploads.append({"role": role, "file": str(ap), "filename": f"{cid}__{role}__{k}{ext}", "type": kind,
                            "placeholder": ph, "hosted_key": key, **upload_method(rec, src)})
            medias.append({"role": role, "value": ph})
    prompt = body.get("prompt") or ""
    note = None
    if first and "@Image" in prompt:
        prompt = renumber_images(prompt, 1)
        note = "Higgsfield: the start image is @Image1, so the references are numbered from @Image2 (renumbered here)"
    params = {"model": MODEL, "mode": "omni_reference", "resolution": resolution, "aspect_ratio": body.get("aspect_ratio") or "16:9",
              "duration": dur, "medias": medias, "prompt": prompt}
    if resolution == "480p":
        params["draft"] = True
    if clip.get("kind") != "sung":
        params["generate_audio"] = False
    cr = credits(dur, resolution)
    steps = []
    if uploads:
        steps.append(UPLOAD_STEP.format(cid=cid))
    steps += [
        _preflight_step(cr),
        "SUBMIT (spends credits): generate_video_batch {requests: [request]} with every key and value VERBATIM (never edit the "
        "prompt; never add get_cost or count inside the batch). Then immediately record the job id: slop clip ingest " + cid
        + " --job-id JOB_ID --pending",
        "If the reply is an `unlim_choice` question instead of a job (the account holds free generations; nothing was "
        "submitted): ask the user, then send the same request again with use_unlim set to their answer (true or false). "
        "Never choose for them. If the item is refused with a preset recommendation: resubmit only that item once with "
        "declined_preset_id set to that preset id. On a transport timeout the outcome is unknown: do NOT resubmit and do "
        "NOT record it as rejected; check `transactions` first (a charge or a job there: it ran, record that job id); "
        "retry only once the outcome is known.",
        f"REJECTED (an error instead of a price or a job id: {VIDEO_ESTIMATE} or the batch refuses the request, or the "
        f"balance is too low; NOT an unlim_choice question, the one preset resubmit above, or a timeout): nothing was "
        f"charged. Stop, tell the user, and record it at once (the ledger then counts 0): slop clip ingest {cid} --failed "
        "\"rejected: <the reply, verbatim>\". The same when the user says not to send it after the estimate: --failed "
        "\"rejected: not sent, <why>\".",
        "POLL: jobs_wait {jobs:[{index:0, job_id}], timeout_seconds:15}; repeat after poll_after_seconds until terminal.",
        f"INGEST: completed -> slop clip ingest {cid} --url RESULT_URL --job-id JOB_ID --credits {cr:g} (the credits "
        f"really charged: 0 if it ran on use_unlim); "
        f"failed (no reason = silent input filter) -> slop clip ingest {cid} --failed \"filter\" (reword without changing the "
        f"beat); nsfw -> slop clip ingest {cid} --failed nsfw; a reason that names 'sensitive information' or 'copyright' "
        f"-> slop clip ingest {cid} --failed \"<the reason, verbatim>\" (it answers with the one next step).",
    ]
    steps = [_stamp(s, pdir) for s in steps]
    return {"clip": cid, "provider": "higgsfield", "created": store.now(), "expected_credits": cr,
            "expected_usd_at_pack_price": round(cr * USD_PER_CREDIT, 2), "how_to_run": steps, "uploads": uploads,
            "request": {"index": index, "params": params},
            "estimate": estimate(params), "prompt_note": note,
            "rules": ["mode omni_reference is always explicit", "never set use_unlim yourself (ask the user on unlim_choice)",
                      "never alter an image to pass a filter", "one take per request; keep the job id"]}


JOB_ID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def job_id_problem(job_id: str | None) -> str | None:
    """Higgsfield job ids are UUIDs (jobs_wait / show_generation_by_ids refuse anything else)."""
    if job_id and not JOB_ID_RE.match(job_id.strip()):
        return (f"{job_id!r} is not a Higgsfield job id (a UUID such as 0f8fad5b-d9cb-469f-a165-70867728950e, from "
                "generate_video_batch's jobs[].job_id): check it, jobs_wait needs the exact id")
    return None


def write_request(pdir: Path, clip: dict, req: dict) -> Path:
    p = store.clip_folder(pdir, clip["id"]) / "higgsfield-request.json"
    import json
    p.write_text(json.dumps(req, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return p


def fetch_result(url: str, out: Path, session=None) -> Path:
    """download a Higgsfield result (public CloudFront URL, no auth header — never send provider keys to it)."""
    if not url.startswith("https://"):
        raise SlopError("the result URL must be https://")
    if session is None:
        import requests
        session = requests.Session()
    r = session.request("GET", url, timeout=600, stream=False, headers={"User-Agent": "claudia"})
    code = int(getattr(r, "status_code", 0) or 0)
    if code != 200:
        raise SlopError(f"download failed (HTTP {code}) for the result URL — the link may have expired; open the job in "
                        "Higgsfield (show_generation_by_ids) and pass the fresh URL")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(r.content)
    return out


def copy_file(src: Path, out: Path) -> Path:
    if not Path(src).is_file():
        raise SlopError(f"file not found: {src}")
    out.parent.mkdir(parents=True, exist_ok=True)
    if Path(src).resolve() != out.resolve():
        shutil.copyfile(src, out)
    return out

"""Seedance 2.5 clips through Hedra v3 or the Hedra MCP connector.

The two transports share a request builder and the clip/ledger lifecycle. MCP tools
are executed by the bot, never by this CLI. No price or credit conversion is guessed.
API contract: https://www.hedra.com/docs/pages/developer/v3/quickstart
MCP contract: https://hedra.com/mcp (tool schemas checked 2026-10-14).
"""
from __future__ import annotations

import copy
import json
import math
import time
import uuid
from pathlib import Path
from urllib.parse import quote

from .. import ledger
from ..config import SlopError, require_env
from . import store, higgsfield

MODEL = "seedance-25"
BASE = "https://api.hedra.com/v3"


class HedraError(SlopError):
    def __init__(self, message, *, unknown=False):
        super().__init__(message)
        self.unknown = unknown


class Hedra:
    def __init__(self, *, session=None, key=None):
        self.session = session
        self._key = key

    def request(self, method, path, *, paid=False, **kwargs):
        import requests
        key = self._key or require_env("HEDRA_API_KEY", "needed for Hedra API transport")
        if self.session is None:
            self.session = requests.Session()
        try:
            r = self.session.request(method, BASE + path, headers={"Authorization": "Key " + key},
                                     timeout=60, allow_redirects=False, **kwargs)
        except requests.RequestException as e:
            # Do not print exception bodies/URLs: they can contain credentials.
            raise HedraError(f"Hedra network error ({type(e).__name__}); " +
                             ("outcome unknown: do not submit again; locate the job and attach its id" if paid
                              else "retry this free operation"), unknown=paid) from None
        if not 200 <= r.status_code < 300:
            raise HedraError(f"Hedra HTTP {r.status_code}; check the account/job in the Hedra dashboard",
                             unknown=paid and (r.status_code >= 500 or r.status_code in (408, 409)))
        try:
            value = r.json()
            if not isinstance(value, dict):
                raise ValueError()
            return value
        except ValueError:
            raise HedraError("Hedra returned an invalid response", unknown=paid) from None

    def upload(self, path):
        with Path(path).open("rb") as f:
            r = self.request("POST", "/files", files={"file": (Path(path).name, f)})
        url = r.get("url")
        if not isinstance(url, str) or not url.startswith("https://"):
            raise SlopError("Hedra upload returned no HTTPS file handle")
        return url

    def estimate(self, body):
        return self.request("POST", f"/models/{MODEL}/estimate", json={"input": body})

    def submit(self, body, key):
        return self.request("POST", f"/models/{MODEL}", paid=True,
                            json={"input": body, "idempotency_key": key})

    def get(self, job_id):
        return self.request("GET", "/jobs/" + quote(job_id, safe=""))


def price(cost, currency):
    if currency not in ("USD", "credits") or isinstance(cost, bool):
        raise SlopError("Hedra needs an estimate with currency USD or credits; never convert between wallets")
    try:
        n = float(cost)
    except (ValueError, TypeError):
        raise SlopError("Hedra needs a numeric estimate cost") from None
    if not math.isfinite(n) or n < 0:
        raise SlopError("Hedra cost must be finite and nonnegative")
    return n, currency


def build(pdir, c, *, resolution=None, no_audio_ref=False):
    """Return raw v3 input, MCP named arguments, and local uploads. No I/O to providers."""
    from . import clips
    b = c["body"]
    model = c.get("model") or MODEL
    if model != MODEL:
        raise SlopError(f"Hedra clips currently support {MODEL}; use clip set {c['id']} --model {MODEL}")
    dur = float(b.get("duration") or 0)
    res = resolution or b.get("resolution") or "720p"
    if not dur.is_integer() or not 4 <= dur <= 30 or res not in ("480p", "720p", "1080p"):
        raise SlopError("Hedra Seedance 2.5 needs integer 4–30 s and 480p, 720p or 1080p")
    aspect = b.get("aspect_ratio") or "16:9"
    if aspect not in ("1:1", "3:4", "4:3", "16:9", "21:9", "9:16", "adaptive"):
        raise SlopError("unsupported Hedra aspect ratio")
    first = c.get("frame") == "first"
    if c.get("kind") == "sung" and (no_audio_ref or first or b.get("generate_audio") is False):
        raise SlopError("Hedra sung clips need reference mode, their audio window and generated audio")
    # Keep start-frame numbering out of the reference prompt until that combination is verified.
    if first and (c.get("refs") or c.get("videos") or c.get("video_urls")):
        raise SlopError("Hedra first-frame clips cannot also use references; use --frame ref")
    if c.get("video_urls"):
        raise SlopError("Hedra needs local video references to upload; external video_urls are not file handles")
    body = {"prompt": b.get("prompt") or "", "duration_ms": int(dur * 1000), "resolution": res,
            "aspect_ratio": aspect, "generate_audio": bool(b.get("generate_audio", True))}
    args = {"model": MODEL, **body}
    uploads = []
    for key, src, kind in clips.hosted_files(pdir, c):
        if key == "audio" and no_audio_ref:
            continue
        if not src or not src.is_file():
            raise SlopError(f"Hedra {key} file is missing; fix the clip before submitting")
        limit = {"image": 30_000_000, "audio": 104_857_600, "video": 524_288_000}[kind]
        if src.stat().st_size > limit:
            raise SlopError(f"Hedra {key} exceeds the {kind} file size limit")
        ph = f"<<HEDRA_UPLOAD:{key}>>"
        field = "start_image" if key == "start" and first else {"image": "images", "video": "videos", "audio": "audios"}[kind]
        arg = "start_keyframe_url" if field == "start_image" else f"reference_{kind}_urls"
        ref = {"source": "url", "url": ph}
        if field == "start_image":
            body[field] = ref; args[arg] = ph
        else:
            body.setdefault(field, []).append(ref); args.setdefault(arg, []).append(ph)
        hosted = (c.get("hosted") or {}).get(key) or {}
        source_url = higgsfield.upload_method(hosted, src).get("https_url")
        uploads.append({"key": key, "file": str(src), "placeholder": ph, "source_url": source_url,
                        "sha1": store.file_sha1(src), "tool": "upload_file"})
    if c.get("kind") == "sung" and not body.get("audios"):
        raise SlopError("Hedra sung clips need their audio window")
    if len(body.get("images", [])) > 30 or len(body.get("videos", [])) > 10:
        raise SlopError("Hedra accepts at most 30 reference images and 10 reference videos")
    return {"input": body, "request": args, "uploads": uploads}


def replace_uploads(value, urls):
    if isinstance(value, dict):
        return {k: replace_uploads(v, urls) for k, v in value.items()}
    if isinstance(value, list):
        return [replace_uploads(v, urls) for v in value]
    return urls.get(value, value) if isinstance(value, str) else value


def dry_run(pdir, c, *, transport, resolution=None, no_audio_ref=False):
    from . import clips
    req = build(pdir, c, resolution=resolution, no_audio_ref=no_audio_ref)
    problems = clips.lock_problems(pdir, c)
    if c.get("status") == "submitted":
        problems.append("a take is already in flight")
    return {"dry_run": True, "clip": c["id"], "provider": "hedra", "transport": transport,
            "would_send": req["input"], "mcp_request": req["request"], "uploads": req["uploads"],
            "lock_problems": problems, "estimate": {"generation_tool": "generate_video", "input": req["request"]},
            "text": f"{c['id']}: Hedra {MODEL} via {transport}; no uploads or paid calls. "
                    "Price comes from Hedra's estimate, in its returned currency. "
                    + ("Before submit: " + "; ".join(problems) if problems else
                       "API: submit with --yes to upload, quote and check the budget. MCP: upload the files, "
                       "replace placeholders, estimate generation_tool=generate_video, then submit with "
                       "--hedra-cost COST --hedra-currency USD|credits --yes.")}


def submit(pdir, c, *, transport, yes, resolution=None, no_audio_ref=False, cost=None, currency=None, client=None,
           quote_only=False):
    from . import clips
    req = build(pdir, c, resolution=resolution, no_audio_ref=no_audio_ref)
    if not quote_only:
        ledger.assert_spend_allowed("hedra", pdir)
    if transport == "api":
        if cost is not None or currency is not None:
            raise SlopError("API transport obtains its own live estimate; omit --hedra-cost/--hedra-currency")
        client = client or Hedra()
        urls = {u["placeholder"]: client.upload(u["file"]) for u in req["uploads"]}
        req["input"] = replace_uploads(req["input"], urls)
        est = client.estimate(req["input"])
        cost, currency = price(est.get("cost"), est.get("currency"))
        if currency != "USD":
            raise SlopError("Hedra API estimate must be in USD")
    else:
        clips.auto_host(pdir, c)
        req = build(pdir, c, resolution=resolution, no_audio_ref=no_audio_ref)
        if quote_only:
            path = store.clip_folder(pdir, c["id"]) / "hedra-preflight.json"
            req["estimate"] = {"generation_tool": "generate_video", "input": req["request"]}
            path.write_text(json.dumps(req, indent=2) + "\n")
            store.save(pdir, c)  # retain source URLs only; no take or spend reservation
            return {"clip": c["id"], "request_file": str(path), "quote_only": True,
                    "text": f"{c['id']}: wrote {path}. Upload its source URLs with Hedra upload_file, replace "
                    "placeholders with file.url, then call estimate. No generation or spend reservation. "
                    "Submit with --hedra-transport mcp --hedra-cost COST --hedra-currency USD|credits --yes."}
        cost, currency = price(cost, currency)
    if quote_only:
        return {"clip": c["id"], "cost": cost, "currency": currency, "quote_only": True,
                "text": f"{c['id']}: Hedra quote {cost:g} {currency}; no generation submitted. "
                "Set budget.hedra_usd to the approved total, then submit with --yes (the price is checked again)."}
    usd, cr = (cost, None) if currency == "USD" else (0, cost)
    ledger.check_budget(pdir, "hedra", add_usd=usd, add_credits=cr or 0, yes=yes)
    key = str(uuid.uuid4())
    tk = clips._new_take(c, provider="hedra", transport=transport, model=MODEL, id=None,
                         status="unknown" if transport == "api" else "requested", est_usd=usd,
                         credits_est=cr, currency=currency, idempotency_key=key,
                         body=copy.deepcopy(req["input"]), ref_audio=store.rel(pdir, clips.window_src(pdir, c)))
    c["provider"] = "hedra"
    c["status"] = "submitted"
    store.save(pdir, c)  # durable before the paid POST; a crash cannot silently repeat it
    ledger.record(pdir, provider="hedra", model=MODEL, kind="video", est_usd=usd, credits=cr,
                  units={"clip": c["id"], "take": tk["n"]}, note=f"Hedra {transport} estimate ({currency})")
    if transport == "mcp":
        req["request"]["idempotency_key"] = key
        req.update(provider="hedra", transport="mcp", cost=cost, currency=currency,
                   estimate={"generation_tool": "generate_video", "input": req["request"]})
        cid = c["id"]
        req["how_to_run"] = [
            "Use the Hedra connector at https://hedra.com/mcp. get_balance: show both wallets and billing_mode. "
            "Do not switch billing mode or workspace without the owner's instruction.",
            "For every upload, call upload_file {url: source_url}; if missing, start the tunnel and host the local "
            "file first. Verify the file sha1. Replace placeholders with the returned file.url in request and estimate. "
            "Reuse the handles from the preflight estimate while unexpired; otherwise upload and estimate again.",
            f"Call estimate with generation_tool=generate_video and input=request. Require cost={cost:g} and "
            f"currency={currency}; if either changed, do not generate: record --failed 'rejected: quote changed' "
            f"{'--cost-usd' if currency == 'USD' else '--credits'} 0 for this unsubmitted take, "
            "then obtain a new reservation with the new quote.",
            "Call generate_video with request exactly as written, including idempotency_key. A timeout has an "
            "unknown outcome: do not create a new request or mark failed. Recover the job in Hedra; keep the reservation.",
            f"Record job.job_id immediately: slop clip ingest {cid} --provider hedra --pending --job-id JOB_ID.",
            "Poll get_generations {job_ids:[JOB_ID], wait_seconds:20}; follow poll_after_seconds. Never regenerate to poll.",
            f"COMPLETED: slop clip ingest {cid} --provider hedra --url OUTPUT_URL --job-id JOB_ID. "
            "Record net cost when known with --cost-usd N or --credits N, matching the quoted currency.",
            f"FAILED: slop clip ingest {cid} --provider hedra --failed REASON. Retain the estimate unless the provider "
            "confirms the net cost: pass --cost-usd N or --credits N (0 for a confirmed full refund). "
            "An explicit rejection before a job exists may use a confirmed zero cost.",
            f"For sung clips, measure the delivered take with slop clip sync {cid} before using it in the edit.",
        ]
        path = store.clip_folder(pdir, cid) / f"hedra-take-{tk['n']}-request.json"
        path.write_text(json.dumps(req, indent=2) + "\n")
        tk["request_file"] = store.rel(pdir, path)
        store.save(pdir, c)
        return {"clip": cid, "take": tk["n"], "request_file": str(path), "cost": cost, "currency": currency,
                "text": f"{cid}: reserved {cost:g} {currency}; run the Hedra MCP steps in {path}, then ingest the result."}
    try:
        ack = client.submit(req["input"], key)
        if not isinstance(ack.get("job_id"), str) or not ack["job_id"]:
            raise HedraError("Hedra returned no job id; outcome unknown", unknown=True)
    except HedraError as e:
        if not e.unknown:
            tk["status"] = "failed"; c["status"] = "locked"
            ledger.settle(pdir, provider="hedra", clip=c["id"], take=tk["n"], note="submit rejected")
        tk["error"] = str(e)
        store.save(pdir, c)
        raise
    tk.update(id=ack["job_id"], status="submitted")
    store.save(pdir, c)
    return {"clip": c["id"], "take": tk["n"], "job": tk["id"], "cost": cost, "currency": currency,
            "text": f"{c['id']}: Hedra job {tk['id']} submitted (~${cost:.4f}); slop clip poll {c['id']}"}


def settle_cost(pdir, c, tk, *, cost=None, currency=None):
    if cost is None:
        return
    cost, currency = price(cost, currency)
    if currency != tk.get("currency"):
        raise SlopError("Hedra result currency differs from its reserved wallet; reconcile before ingest")
    field = "est_usd" if currency == "USD" else "credits"
    old = sum(float(r.get(field) or 0) for r in ledger.open_charges(pdir, "hedra", c["id"], tk["n"]))
    if abs(cost - old) > 1e-9:
        ledger.record(pdir, provider="hedra", model=MODEL, kind="video-adjust", status="ok",
                      est_usd=cost - old if currency == "USD" else 0,
                      credits=cost - old if currency == "credits" else None,
                      request_id=tk.get("id"), units={"clip": c["id"], "take": tk["n"]})
    tk["cost_usd" if currency == "USD" else "credits"] = cost


def ingest(pdir, c, *, file=None, url=None, job_id=None, credits=None, cost_usd=None,
           pending=False, failed=None, declined=None, session=None):
    from . import clips
    active = [t for t in c.get("takes", []) if t.get("provider") == "hedra"
              and t.get("status") in ("unknown", "submitted", "requested", "pending")]
    tk = active[-1] if active else None
    if job_id:
        known = next((t for t in c.get("takes", []) if t.get("provider") == "hedra" and t.get("id") == job_id), None)
        if known:
            tk = known
    if not tk:
        raise SlopError("no Hedra take to ingest; submit/reserve the clip first")
    if job_id and tk.get("id") and tk["id"] != job_id:
        raise SlopError("job id does not match this Hedra take")
    if credits is not None and cost_usd is not None:
        raise SlopError("use one cost unit: --credits or --cost-usd")
    cost = cost_usd if cost_usd is not None else credits
    currency = "USD" if cost_usd is not None else "credits"
    if cost is not None:
        price(cost, currency)
        if currency != tk.get("currency"):
            raise SlopError("cost unit does not match the reserved Hedra wallet")
    if tk.get("status") in ("delivered", "failed", "declined"):
        settle_cost(pdir, c, tk, cost=cost, currency=currency)
        store.save(pdir, c)
        return {"clip": c["id"], "take": tk["n"], "text": f"{c['id']}: take already {tk['status']}"}
    if pending:
        if not job_id:
            raise SlopError("--pending needs --job-id")
        tk.update(id=job_id, status="pending")
    elif failed or declined:
        tk.update(status="declined" if declined else "failed", error=failed or declined, id=job_id or tk.get("id"))
        c["status"] = "declined" if declined else "locked"
        if declined:
            c.setdefault("declined", []).append({"provider": "hedra", "start": c.get("start"), "note": declined})
    else:
        if not (file or url):
            raise SlopError("Hedra ingest needs --file/--url, --pending, or --failed/--declined")
        out = store.take_path(pdir, c["id"], tk["n"])
        if url:
            higgsfield.fetch_result(url, out, session=session)  # public URL: never send the API credential
        else:
            higgsfield.copy_file(Path(file), out)
        duration = clips.probe_duration(out)
        if duration is not None and duration <= .2:
            raise SlopError("Hedra result is not a playable video")
        tk.update(status="delivered", id=job_id or tk.get("id"), file=store.rel(pdir, out),
                  source_url=url, duration_s=duration, sha1=store.file_sha1(out), delivered=store.now())
        c["status"] = "delivered"
    settle_cost(pdir, c, tk, cost=cost, currency=currency)
    store.save(pdir, c)
    nxt = (f"; slop clip sync {c['id']}" if tk["status"] == "delivered" and c["kind"] == "sung" else "")
    return {"clip": c["id"], "take": tk["n"], "status": tk["status"], "file": tk.get("file"),
            "text": f"{c['id']}: Hedra take {tk['n']} {tk['status']}" + nxt}


def poll(pdir, c, *, wait_s=0, job_id=None, client=None, sleep=None):
    tk = next((t for t in reversed(c.get("takes", [])) if t.get("provider") == "hedra"
               and t.get("status") in ("unknown", "submitted", "requested", "pending")), None)
    if not tk:
        return {"clip": c["id"], "text": f"{c['id']}: no Hedra take in flight"}
    if job_id:
        if tk.get("id") and tk["id"] != job_id:
            raise SlopError("job id does not match the Hedra take")
        tk.update(id=job_id, status="pending"); store.save(pdir, c)
    if tk["transport"] == "mcp":
        if not tk.get("id"):
            return {"clip": c["id"], "text": f"{c['id']}: read {tk.get('request_file')}; if generation was already "
                    "attempted, recover its job id without resubmitting. Record it with clip ingest "
                    f"{c['id']} --provider hedra --pending --job-id JOB_ID, then poll with get_generations."}
        return {"clip": c["id"], "text": f"{c['id']}: use Hedra get_generations with job_ids "
                f"[{tk.get('id')!r}], wait_seconds:20; follow poll_after_seconds, then clip ingest"}
    if not tk.get("id"):
        raise SlopError(f"{c['id']}: outcome unknown; locate the job in Hedra, then clip poll {c['id']} --job-id ID")
    client = client or Hedra()
    deadline = time.monotonic() + max(0, wait_s)
    while True:
        r = client.get(tk["id"])
        state = r.get("status")
        kw = {}
        if r.get("cost") is not None:
            cost, currency = price(r["cost"], r.get("currency"))
            kw["cost_usd" if currency == "USD" else "credits"] = cost
        if state == "COMPLETED":
            outputs = r.get("outputs") or []
            out = next((x for x in outputs if x.get("status", "COMPLETED") == "COMPLETED"
                        and x.get("url") and str(x.get("content_type") or "").startswith("video/")), None)
            if not out:
                raise SlopError("Hedra completed without a retrievable video; keep the job id and check its outputs")
            return ingest(pdir, c, url=out["url"], job_id=tk["id"], **kw)
        if state == "FAILED":
            code = (r.get("error") or {}).get("code") or "FAILED"
            return ingest(pdir, c, failed=f"Hedra job failed ({code}); inspect the job in Hedra", **kw)
        if time.monotonic() >= deadline:
            return {"clip": c["id"], "status": state, "text": f"{c['id']}: Hedra {state}; clip poll {c['id']}"}
        (sleep or time.sleep)(min(5, max(0, deadline - time.monotonic())))

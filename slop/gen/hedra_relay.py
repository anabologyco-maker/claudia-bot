"""Durable handoff between the production and Grok's Hedra MCP connector.

The CLI never invokes MCP. Grok reports the quote/job/result through `relay hedra`;
a start claim is persisted before Grok is told to make the paid call.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .. import ledger, util
from ..config import SlopError
from . import clips, hedra, store


def fingerprint(req):
    request = {k: v for k, v in req["request"].items() if k != "idempotency_key"}
    refs = [{k: u[k] for k in ("key", "sha1")} for u in req["uploads"]]
    return hashlib.sha256(json.dumps([request, refs], sort_keys=True).encode()).hexdigest()


def prepare(pdir, cid, phase):
    if not cid or phase not in ("quote", "generate"):
        raise SlopError("Hedra relay needs --clip CLIP --what quote|generate")
    c = store.load(pdir, cid)
    if c.get("provider") != "hedra":
        raise SlopError("set and lock the clip with --provider hedra first")
    if phase == "quote":
        result = clips.submit(pdir, cid, quote_only=True)
        path = Path(result["request_file"])
        req = json.loads(path.read_text())
        take = None
    else:
        tk = next((t for t in reversed(c["takes"]) if t.get("provider") == "hedra"), None)
        if not tk or tk.get("status") != "requested" or tk.get("relay_attempted"):
            raise SlopError("reserve the approved Hedra quote with clip submit --hedra-cost COST "
                            "--hedra-currency USD|credits --yes first; never repeat an attempted generation")
        path = pdir / tk["request_file"]
        req = json.loads(path.read_text())
        qpath = store.clip_folder(pdir, cid) / "hedra-quote.json"
        q = json.loads(qpath.read_text()) if qpath.exists() else {}
        if (q.get("fingerprint") != fingerprint(req) or q.get("cost") != req["cost"]
                or q.get("currency") != req["currency"]):
            raise SlopError("the reservation needs a matching completed Hedra quote relay job")
        take = tk["n"]
    current = hedra.build(pdir, c, resolution=req["request"]["resolution"],
                          no_audio_ref=not bool(req["request"].get("reference_audio_urls")))
    if fingerprint(current) != fingerprint(req):
        raise SlopError("Hedra inputs changed; prepare a new quote and approval")
    return {"project_dir": str(pdir.resolve()), "clip": cid, "take": take,
            "request_file": str(path.resolve()), "fingerprint": fingerprint(req)}


def instruction(j):
    jid = j["job"]
    prefix = f"Run Hedra connector job {jid} ({j['what']}) using docs/63-hedra.md and {j['request_file']}. "
    if j["what"] == "quote":
        return prefix + ("Upload references, call estimate; never generate. Report using "
                         f"slop relay hedra {jid} --action quote --cost COST --currency USD|credits.")
    state = j.get("hedra_state")
    if j.get("provider_job_id"):
        return prefix + (f"Resume get_generations for {j['provider_job_id']}; never generate again. "
                         f"When completed: slop relay hedra {jid} --action complete --job-id ID --url URL; "
                         "include confirmed --cost COST --currency UNIT when available.")
    if state == "started":
        return prefix + ("Generation was attempted but its id is unknown. Recover the existing Hedra job; "
                         f"record it with slop relay hedra {jid} --action pending --job-id ID. Do not generate again.")
    return prefix + ("Upload references and re-estimate with estimate.input (exclude idempotency_key). Before generate_video, claim once with "
                     f"slop relay hedra {jid} --action start --cost COST --currency UNIT. "
                     "Only a successful start authorizes the saved request; immediately record the returned job id "
                     f"with slop relay hedra {jid} --action pending --job-id ID. Follow poll_after_seconds.")


def _take(pdir, j):
    c = store.load(pdir, j["clip"])
    tk = next((t for t in c["takes"] if t["n"] == j.get("take") and t.get("provider") == "hedra"), None)
    if not tk:
        raise SlopError("Hedra relay take no longer exists")
    return c, tk


def cancel(j):
    """Only an unattempted reservation can be released locally."""
    if j["what"] == "quote":
        return
    pdir = Path(j["project_dir"])
    c, tk = _take(pdir, j)
    if tk["status"] == "failed" and tk.get("error") == "cancelled before generation":
        return
    if tk.get("relay_attempted") or tk.get("id") or tk["status"] != "requested":
        raise SlopError("Hedra generation was attempted; recover/poll its job before closing it. "
                        "Local relay cancellation cannot cancel or refund a Hedra job.")
    cost = {"cost_usd": 0} if tk["currency"] == "USD" else {"credits": 0}
    hedra.ingest(pdir, c, failed="cancelled before generation", **cost)


def report(a):
    from .. import relay as R
    _, rd = R._dirs()
    finish = None
    with R._lock(rd):
        jobs = R._jobs(rd, open_only=False)
        j = next((x for x in jobs if x["job"] == a.job.upper()), None)
        if not j or j["job_kind"] != "hedra":
            raise SlopError("name a Hedra relay job (J-NNNN)")
        if j["status"] != "queued":
            return {"job": j["job"], "text": f"{j['job']}: already {j['status']}"}
        pdir = Path(j["project_dir"])
        state = R._read_json(rd / "jobs.json")
        rec = state.get(j["job"], {"status": "queued"})
        cost = None
        if a.cost is not None or a.currency is not None:
            cost, currency = hedra.price(a.cost, a.currency)
        if a.action == "quote":
            if j["what"] != "quote":
                raise SlopError("quote reports require a quote job")
            if cost is None:
                raise SlopError("quote report requires --cost and --currency")
            req = json.loads(Path(j["request_file"]).read_text())
            c = store.load(pdir, j["clip"])
            current = hedra.build(pdir, c, resolution=req["request"]["resolution"],
                          no_audio_ref=not bool(req["request"].get("reference_audio_urls")))
            if fingerprint(current) != j["fingerprint"]:
                raise SlopError("clip changed while quoting; cancel and prepare a fresh quote")
            q = {"cost": cost, "currency": currency, "fingerprint": j["fingerprint"], "job": j["job"]}
            path = store.clip_folder(pdir, j["clip"]) / "hedra-quote.json"
            R._write_json(path, q)
            rec.update(status="done", files=[str(path)], quote=q, ended=util.iso_now())
            finish = f"Hedra quote for {j['clip']}: {cost:g} {currency}. Ask the director to approve before reserving " \
                     "and posting a generate job. Quote: " + str(path)
        elif a.action == "failed" and j["what"] == "quote":
            if not a.reason:
                raise SlopError("--failed needs --reason")
            rec.update(status="failed", reason=a.reason, ended=util.iso_now())
            finish = f"Hedra quote failed: {a.reason}"
        else:
            if j["what"] != "generate":
                raise SlopError("this action needs a generate job")
            c, tk = _take(pdir, j)
            if a.action == "start":
                if tk.get("relay_attempted") or tk.get("id") or tk["status"] != "requested":
                    raise SlopError("Hedra generation already attempted; recover its job id, never generate again")
                req = json.loads(Path(j["request_file"]).read_text())
                reserved = tk["est_usd"] if tk["currency"] == "USD" else tk["credits_est"]
                if (cost is None or cost != req["cost"] or currency != req["currency"]
                        or cost != reserved or currency != tk["currency"]):
                    raise SlopError("fresh quote differs from reservation; do not generate. Cancel this unstarted "
                                    "job, then request a new quote and approval")
                current = hedra.build(pdir, c, resolution=req["request"]["resolution"],
                          no_audio_ref=not bool(req["request"].get("reference_audio_urls")))
                if (fingerprint(current) != j["fingerprint"] or fingerprint(req) != j["fingerprint"]
                        or req["request"].get("idempotency_key") != tk["idempotency_key"]):
                    raise SlopError("Hedra inputs changed; do not generate")
                ledger.assert_spend_allowed("hedra", pdir)
                ledger.check_budget(pdir, "hedra", yes=True)  # reservation is already counted
                tk.update(status="unknown", relay_attempted=True)
                store.save(pdir, c)  # persists before returning permission to call generate_video
                rec.update(hedra_state="started")
                state[j["job"]] = rec; R._write_json(rd / "jobs.json", state)
                return {"job": j["job"], "request_file": j["request_file"], "idempotency_key": tk["idempotency_key"],
                        "text": "Start claimed once. Call generate_video with the saved request and resolved "
                                "file handles; immediately record job.job_id using relay hedra --action pending."}
            if a.action == "pending":
                if not tk.get("relay_attempted"):
                    raise SlopError("claim start before submitting the generation")
                out = hedra.ingest(pdir, c, pending=True, job_id=a.job_id)
                rec.update(hedra_state="pending", provider_job_id=a.job_id)
                state[j["job"]] = rec; R._write_json(rd / "jobs.json", state)
                return {**out, "job": j["job"]}
            if a.action not in ("complete", "failed"):
                raise SlopError("unsupported Hedra relay action")
            if a.action == "complete" or tk.get("relay_attempted"):
                if not a.job_id or not tk.get("id") or a.job_id != tk["id"]:
                    raise SlopError("record the provider job id with --action pending before reporting its result")
            kw = {} if cost is None else {"cost_usd" if currency == "USD" else "credits": cost}
            if a.action == "complete":
                if not a.url:
                    raise SlopError("completed generation needs --url OUTPUT_URL")
                out = hedra.ingest(pdir, c, url=a.url, job_id=a.job_id, **kw)
                files = [str(pdir / out["file"])]
                rec.update(status="done", files=files, ended=util.iso_now())
                finish = f"Hedra {j['clip']} delivered: {files[0]}. Run clip sync before using a sung take."
            else:
                if not a.reason:
                    raise SlopError("failed result needs --reason; an unknown outcome must stay open")
                if not tk.get("relay_attempted"):
                    kw = {"cost_usd" if tk["currency"] == "USD" else "credits": 0}
                hedra.ingest(pdir, c, failed=a.reason, job_id=a.job_id, **kw)
                rec.update(status="failed", reason=a.reason, ended=util.iso_now())
                finish = f"Hedra {j['clip']} failed: {a.reason}. Retain estimated spend unless net cost is confirmed."
        # deliver writes the terminal job state and inbox message atomically, and wakes production.
    out = R.deliver(f"[grok] {j['job']}: {finish}", "grok", (j["job"], rec), optional_runner=True)
    return {**out, "job": j["job"]}

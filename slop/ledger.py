"""Spend ledger. CONTRACT — every paid call goes through `record()`; budget checks through `check_budget()`.

The ledger is an estimate. Real spend is read from the provider (OpenRouter /api/v1/key usage) by `slop spend`.
Declined / failed submissions are recorded with status so they are not counted as spend.

Integration changes: est_usd keeps 6 decimals (per-second Whisper and $0.004 images rounded away at 4); check_budget
refuses every paid call while the owner's quality flag is set (project.json budget.frozen, `slop spend --freeze`,
ARCHITECTURE §7 rule 8).
Hardening: check_budget also refuses every paid call while env SLOP_FREE_ONLY is set (`slop next --free-only`,
`slop job start --free-only`): a hard no-spend lock for unattended runs. A paid call made WITHOUT a project (no
check_budget possible) must call assert_spend_allowed(provider) instead, which needs no project.
Studio run (Higgsfield credits logged 114 vs 66 real: a rejected 1080p finalize stayed counted): a take reported failed,
rejected or uncharged is recorded AS failed with 0 spend. A refund row (kind "*-refund") for a take whose charge is
still counted (same provider + units.clip + units.take) is written as a settlement instead: status "failed", 0 credits
/ $0, the charge's kind, units.settles = true and units.refunded_credits / refunded_usd. A settlement voids every
EARLIER counted row of that take (its submit estimate and any adjustment), so the take adds 0 to every total
(spent_usd, spent_credits, `slop status` / `slop spend`), and a later take of the same number counts again.
`settle()` writes one directly. A refund with no counted charge is kept as written (a negative row). A request with no
job id recorded still counts (it may have run); when it pushes the Higgsfield cap, the cap error names it and how to
record a refusal.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from .config import SlopError, load_project


def ledger_path(pdir: Path) -> Path:
    return pdir / "ledger.jsonl"


COUNTED = frozenset({"submitted", "delivered", "done", "ok"})     # statuses that count as spend


def take_key(row: dict) -> tuple[str, str, str] | None:
    """(provider, clip, take) of a row about one generation take (units.clip + units.take), else None."""
    u = row.get("units") if isinstance(row, dict) else None
    if not isinstance(u, dict) or u.get("clip") in (None, "") or u.get("take") in (None, ""):
        return None
    return (str(row.get("provider") or ""), str(u["clip"]), str(u["take"]))


def voided(rs: list[dict]) -> set[int]:
    """Indexes of the rows that a LATER settlement row (units.settles: the take was reported failed / rejected /
    uncharged) cancels: every earlier counted row of the same provider + clip + take."""
    out: set[int] = set()
    open_rows: dict[tuple, list[int]] = {}
    for i, r in enumerate(rs):
        k = take_key(r) if isinstance(r, dict) else None
        if k is None:
            continue
        if (r.get("units") or {}).get("settles"):
            out.update(open_rows.pop(k, []))
        elif r.get("status") in COUNTED:
            open_rows.setdefault(k, []).append(i)
    return out


def counted(rs: list[dict]) -> list[dict]:
    """The rows that count as spend: a counted status and not voided by a later settlement."""
    v = voided(rs)
    return [r for i, r in enumerate(rs) if i not in v and isinstance(r, dict) and r.get("status") in COUNTED]


def _readable_rows(pdir: Path) -> list[dict]:
    p = ledger_path(pdir)
    if not p.is_file():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line) if line.strip() else None
        except ValueError:
            continue
        if isinstance(r, dict):
            out.append(r)
    return out


def open_charges(pdir: Path, provider: str, clip, take) -> list[dict]:
    """The counted, not yet settled rows of one take (its submit estimate and any adjustment)."""
    key = (str(provider or ""), str(clip), str(take))
    rs = _readable_rows(pdir)
    v = voided(rs)
    return [r for i, r in enumerate(rs) if i not in v and r.get("status") in COUNTED and take_key(r) == key]


def record(pdir: Path | None, *, provider: str, model: str, kind: str, est_usd: float = 0.0,
           units: dict | None = None, request_id: str | None = None, status: str = "submitted",
           credits: float | None = None, note: str = "") -> dict:
    units = dict(units or {})
    if pdir is not None and str(kind).endswith("-refund") and status in COUNTED and not units.get("settles"):
        k = take_key({"provider": provider, "units": units})
        charges = open_charges(pdir, provider, k[1], k[2]) if k else []
        if charges:                       # the take was reported failed / uncharged: record it AS failed, 0 spend
            kind = str(charges[0].get("kind") or kind)
            if credits:
                units["refunded_credits"] = round(abs(float(credits)), 2)
            if est_usd:
                units["refunded_usd"] = round(abs(float(est_usd)), 6)
            units["settles"] = True
            status, est_usd = "failed", 0.0
            credits = 0.0 if (credits is not None or any(c.get("credits") for c in charges)) else None
    row = {"ts": round(time.time(), 3), "provider": provider, "model": model, "kind": kind,
           "est_usd": round(float(est_usd), 6), "units": units, "request_id": request_id,
           "status": status, "credits": credits, "note": note}
    if pdir is not None:
        with ledger_path(pdir).open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def settle(pdir: Path, *, provider: str, clip: str, take, note: str, model: str = "", status: str = "failed",
           request_id: str | None = None) -> dict | None:
    """Record that one take was reported failed / rejected / uncharged (a refused finalize, a failed job): a row with
    `status`, 0 credits and $0 that voids the take's counted rows. None when nothing of that take is counted."""
    charges = open_charges(pdir, provider, clip, take)
    if not charges:
        return None
    cr = round(sum(float(c.get("credits") or 0) for c in charges), 2)
    usd = round(sum(float(c.get("est_usd") or 0) for c in charges), 6)
    units = {"clip": clip, "take": take, "settles": True, "refunded_credits": cr, "refunded_usd": usd}
    return record(pdir, provider=provider, model=model or str(charges[0].get("model") or ""),
                  kind=str(charges[0].get("kind") or "video"), est_usd=0.0, units=units, request_id=request_id,
                  status=status, credits=0.0 if any(c.get("credits") is not None for c in charges) else None, note=note)


def rows(pdir: Path) -> list[dict]:
    p = ledger_path(pdir)
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def spent_usd(pdir: Path, provider: str | None = None) -> float:
    return round(sum(float(r.get("est_usd") or 0.0) for r in counted(rows(pdir))
                     if provider is None or r.get("provider") == provider), 6)


def spent_credits(pdir: Path, provider: str | None = None) -> float:
    return round(sum(float(r.get("credits") or 0.0) for r in counted(rows(pdir))
                     if provider is None or r.get("provider") == provider), 2)


def free_only() -> bool:
    """True while the run's spend lock is set (env SLOP_FREE_ONLY, by `slop next --free-only` / `job start --free-only`)."""
    return os.environ.get("SLOP_FREE_ONLY", "").strip() not in ("", "0")


def assert_spend_allowed(provider: str = "paid", pdir: Path | None = None) -> None:
    """Raise SlopError while no paid call may be made: the spend lock (SLOP_FREE_ONLY), and with a project the owner's
    quality flag (budget.frozen). Needs NO project: a paid call made without one (e.g. an embedding run outside a
    project) must call this, since check_budget needs a project. check_budget calls it first."""
    if free_only():
        raise SlopError(f"spending is locked for this run (SLOP_FREE_ONLY is set, e.g. by `slop next --free-only` or "
                        f"`slop job start --free-only`): this {provider} call was refused. Run the paid step yourself, "
                        "after the estimate and the owner's OK, without the lock.")
    if pdir is not None:
        fr = (load_project(pdir).get("budget", {}) or {}).get("frozen")
        if fr:
            why = fr.get("reason") if isinstance(fr, dict) else fr
            raise SlopError(f"spending is frozen by the owner's quality flag: {why}. Resolve the flag with the owner "
                            "first, then `slop spend --unfreeze` (logged in DECISIONS.md).")


def _requested_hint(pdir: Path) -> str:
    """Names the Higgsfield takes whose request file was written but no job id recorded: their estimate is in `spent`
    until the bot records what happened (a refused one then counts 0). "" when there are none."""
    try:
        from .core_cli import clip_docs, requested_takes
        rs = _readable_rows(pdir)
        v = voided(rs)
        open_keys = {take_key(r) for i, r in enumerate(rs) if i not in v and r.get("status") in COUNTED
                     and (r.get("credits") or 0)}
        names = [f"{cid} take {t.get('n')}" for cid, c in clip_docs(pdir) if c for t in requested_takes(c)
                 if ("higgsfield", str(c.get("id") or cid), str(t.get("n"))) in open_keys]
    except Exception:  # noqa: BLE001 - a hint must never hide the cap error itself
        return ""
    if not names:
        return ""
    one = names[0].split(" ", 1)[0] if len({n.split(" ", 1)[0] for n in names}) == 1 else "CLIP"
    return (f" Of that, {', '.join(names)} {'is' if len(names) == 1 else 'are'} only requested (no job id recorded): if "
            f"the connector refused it, record it - slop clip ingest {one} --failed \"rejected: <its reply, verbatim>\" "
            f"- and it counts 0; if it ran, record its job id (slop clip ingest {one} --job-id JOB_ID --pending).")


def check_budget(pdir: Path, provider: str, add_usd: float = 0.0, add_credits: float = 0.0,
                 yes: bool = False) -> None:
    """Raise SlopError if this spend would exceed the project budget, or needs confirmation and yes is False."""
    assert_spend_allowed(provider)
    proj = load_project(pdir)
    b = proj.get("budget", {}) or {}
    fr = b.get("frozen")
    if fr:
        why = fr.get("reason") if isinstance(fr, dict) else fr
        raise SlopError(f"spending is frozen by the owner's quality flag: {why}. Resolve the flag with the owner first, "
                        "then `slop spend --unfreeze` (logged in DECISIONS.md).")
    if provider == "openrouter":
        cap = float(b.get("openrouter_usd", 0) or 0)
        now = spent_usd(pdir, "openrouter")
        if cap and now + add_usd > cap + 1e-9:
            raise SlopError(f"OpenRouter budget cap ${cap:.2f} would be exceeded (spent ~${now:.2f} + ${add_usd:.2f}). "
                            "Raise budget.openrouter_usd in project.json only if the owner agrees.")
    if provider == "higgsfield":
        cap = float(b.get("higgsfield_credits", 0) or 0)
        now = spent_credits(pdir, "higgsfield")
        if cap and now + add_credits > cap + 1e-9:
            raise SlopError(f"Higgsfield credit cap {cap:g} would be exceeded (spent ~{now:g} + {add_credits:g})."
                            + _requested_hint(pdir))
    if provider == "hedra":
        for key, spent, add, unit in (("hedra_usd", spent_usd(pdir, "hedra"), add_usd, "USD"),
                                      ("hedra_credits", spent_credits(pdir, "hedra"), add_credits, "credits")):
            cap = float(b.get(key, 0) or 0)
            if cap and spent + add > cap + 1e-9:
                raise SlopError(f"Hedra {unit} cap {cap:g} would be exceeded ({spent:g} + {add:g}); budget.{key}")
        if add_credits and not yes:
            raise SlopError("Hedra credits require --yes after the owner approves the quoted credit amount")
    confirm = float(b.get("confirm_over_usd", 2) or 0)
    if not yes and add_usd > confirm:
        raise SlopError(f"this call is estimated at ${add_usd:.2f} (> confirm_over_usd ${confirm:.2f}); "
                        "show the estimate to the user and re-run with --yes after they agree.")

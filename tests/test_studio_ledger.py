"""Studio run, ledger track (offline): a Higgsfield take reported failed / rejected / uncharged is recorded AS failed
with 0 credits and voids its counted estimate (live: a refused 1080p finalize kept 48 credits in the log, 114 logged vs
66 real); the finalize request tells the bot how to record a refusal; `slop status` reads a rejected finalize as
rejected (the clip stays delivered on its draft), never "submitted", and names a request left without a job id."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest

_H = Path(__file__).parent / "fixtures" / "gen" / "helpers.py"
_spec = importlib.util.spec_from_file_location("gen_test_helpers", _H)
H = importlib.util.module_from_spec(_spec); sys.modules.setdefault("gen_test_helpers", H); _spec.loader.exec_module(H)

from slop import core_cli, ledger  # noqa: E402
from slop.cli import main  # noqa: E402
from slop.config import SlopError  # noqa: E402
from slop.gen import higgsfield as hf, hosting, store, templates as tpl  # noqa: E402

needs_ffmpeg = pytest.mark.skipif(not H.FFMPEG, reason="ffmpeg is required")
DRAFT_JOB = "0f8fad5b-d9cb-469f-a165-70867728950e"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SLOP_PROJECTS", str(tmp_path / "projects"))
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-test-not-a-real-key")
    monkeypatch.delenv("SLOP_PROJECT", raising=False)
    monkeypatch.delenv("SLOP_FREE_ONLY", raising=False)
    H.write_cache(tmp_path / "home")
    return H.make_project(tmp_path / "projects", audio=bool(H.FFMPEG),
                          budget={"openrouter_usd": 40, "higgsfield_credits": 120, "confirm_over_usd": 2})


def run(pdir, *argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(["--json", "--project", str(pdir), *argv])
    return rc, json.loads(buf.getvalue())


def hf_row(pdir, clip, take, credits, kind="video", status="submitted"):
    return ledger.record(pdir, provider="higgsfield", model=hf.MODEL, kind=kind, credits=credits, status=status,
                         units={"clip": clip, "take": take})


# ------------------------------------------------------------------------------------------------ ledger
def test_live_numbers_a_refused_finalize_counts_zero(tmp_path):
    """66 real credits of drafts + a 48-credit finalize request the connector refused: 114 before, 66 after."""
    for take, cr in enumerate((15, 15, 12, 12, 12), start=1):
        hf_row(tmp_path, f"c0{take}", 1, cr)
    hf_row(tmp_path, "c01", 2, 48, kind="video-finalize")
    assert ledger.spent_credits(tmp_path) == 114
    row = ledger.record(tmp_path, provider="higgsfield", model=hf.MODEL, kind="video-refund", credits=-48.0,
                        est_usd=0.0, status="ok", units={"clip": "c01", "take": 2}, note="rejected: no draft: refunded")
    assert row["status"] == "failed" and row["credits"] == 0 and row["kind"] == "video-finalize"
    assert row["units"]["settles"] is True and row["units"]["refunded_credits"] == 48
    assert ledger.rows(tmp_path)[-1] == row                       # what is written is what was returned
    assert ledger.spent_credits(tmp_path) == 66
    assert ledger.open_charges(tmp_path, "higgsfield", "c01", 2) == []
    assert ledger.settle(tmp_path, provider="higgsfield", clip="c01", take=2, note="again") is None   # nothing left


def test_settle_voids_the_estimate_and_its_adjustment_only(tmp_path):
    hf_row(tmp_path, "W01", 1, 28)
    ledger.record(tmp_path, provider="higgsfield", model=hf.MODEL, kind="video-adjust", credits=2.0, status="ok",
                  units={"clip": "W01", "take": 1})
    hf_row(tmp_path, "W02", 1, 21)
    ledger.record(tmp_path, provider="higgsfield", model="higgsfield-image", kind="image", credits=4.0,
                  status="delivered", units={"plate": "hall"})
    assert ledger.spent_credits(tmp_path) == 55
    row = ledger.settle(tmp_path, provider="higgsfield", clip="W01", take=1, note="job reported uncharged")
    assert row["status"] == "failed" and row["credits"] == 0.0 and row["units"]["refunded_credits"] == 30
    assert ledger.spent_credits(tmp_path) == 25                   # W02 and the still are untouched
    hf_row(tmp_path, "W01", 1, 28)                                # a later row of the same take counts again
    assert ledger.spent_credits(tmp_path) == 53


def test_openrouter_failed_job_is_recorded_failed_and_usd_stays_exact(tmp_path):
    ledger.record(tmp_path, provider="openrouter", model="bytedance/seedance-2.5", kind="video", est_usd=1.155,
                  status="submitted", units={"clip": "W01", "take": 1})
    row = ledger.record(tmp_path, provider="openrouter", model="bytedance/seedance-2.5", kind="video-refund",
                        est_usd=-1.155, status="ok", units={"clip": "W01", "take": 1}, note="job failed")
    assert row["status"] == "failed" and row["est_usd"] == 0 and row["credits"] is None
    assert row["units"]["refunded_usd"] == pytest.approx(1.155)
    assert ledger.spent_usd(tmp_path) == 0 and ledger.spent_usd(tmp_path, "openrouter") == 0


def test_a_refund_without_a_counted_charge_is_kept_as_written(tmp_path):
    row = ledger.record(tmp_path, provider="higgsfield", model=hf.MODEL, kind="video-refund", credits=-10.0,
                        status="ok", units={"clip": "X", "take": 3})
    assert row["status"] == "ok" and row["credits"] == -10 and "settles" not in row["units"]
    assert ledger.voided([{"provider": "a"}, "junk", {"units": {"clip": "c", "take": 1, "settles": True}}]) == set()


def test_the_budget_check_frees_the_refused_finalize(env):
    hf_row(env, "c01", 1, 66)
    hf_row(env, "c01", 2, 48, kind="video-finalize")
    with pytest.raises(SlopError, match="credit cap 120"):
        ledger.check_budget(env, "higgsfield", add_credits=12, yes=True)
    ledger.settle(env, provider="higgsfield", clip="c01", take=2, note="rejected: draft_job_id refused")
    ledger.check_budget(env, "higgsfield", add_credits=12, yes=True)   # 66 + 12 <= 120


# ------------------------------------------------------------------------------------------------ status
def _clip(cid="W01", status="locked", takes=None, **extra) -> dict:
    return {"id": cid, "kind": "sung", "status": status, "provider": "higgsfield", "start": "plates/x.png",
            "body": {"prompt": "p", "duration": 4}, "takes": takes or [], **extra}


DRAFT = {"n": 1, "provider": "higgsfield", "status": "delivered", "file": "clips/W01/take-1.mp4", "id": DRAFT_JOB,
         "submitted": "2026-10-02T07:10:00", "credits": 12, "sync": {"mode": "copy", "ncc": 0.49, "lag_s": 0.47},
         "body": {"resolution": "480p", "draft": True}}
FIN = {"n": 2, "provider": "higgsfield", "status": "failed", "finalize_of": 1, "credits_est": 48, "id": None,
       "submitted": "2026-10-02T07:40:00", "error": "rejected: draft_job_id is not a finalizable draft",
       "request_file": "clips/W01/higgsfield-take-2-finalize-of-1.json"}


def test_status_reads_a_rejected_finalize_as_rejected(env):
    c = _clip(takes=[DRAFT, FIN], locked_at="2026-10-02T07:00:00")       # `clip ingest --failed` left it locked
    assert core_cli.clip_state(c) == "delivered"
    st = core_cli._clips_stage(env, "studio", [("W01", c)], None)
    assert st["done"], st
    assert "1 delivered" in st["detail"] and "locked" not in st["detail"] and "submitted" not in st["detail"]
    assert "finalize rejected: W01 take 2 (1080p, of take 1: draft_job_id is not a finalizable draft)" in st["detail"]
    assert "not charged, the edit keeps take 1" in st["detail"] and "rejected: rejected" not in st["detail"]
    # it ran and failed (a job id): "failed", still not charged and still delivered
    c2 = _clip(takes=[DRAFT, {**FIN, "id": "7c9e6679-7425-40de-944b-e07fc1f90ae7", "error": "nsfw"}])
    st = core_cli._clips_stage(env, "studio", [("W01", c2)], None)
    assert st["done"] and "finalize failed: W01 take 2 (1080p, of take 1: nsfw)" in st["detail"]
    # locked again by the owner after the refusal (a new take is wanted): really locked
    c3 = _clip(takes=[DRAFT, FIN], locked_at="2026-10-02T08:00:00")
    assert core_cli.clip_state(c3) == "locked"
    assert not core_cli._clips_stage(env, "studio", [("W01", c3)], None)["done"]
    # an owner-rejected DELIVERED finalize was charged: not read as a refused finalize
    c4 = _clip(status="delivered", takes=[DRAFT, {**FIN, "status": "rejected", "file": "clips/W01/take-2.mp4"}])
    assert core_cli.failed_finalize(c4) is None
    # a regular take that failed keeps the clip locked (ready for a retry)
    c5 = _clip(takes=[DRAFT, {**FIN, "finalize_of": None}])
    assert core_cli.clip_state(c5) == "locked"
    # recorded with --declined instead: the same reading
    c6 = _clip(status="declined", takes=[DRAFT, {**FIN, "status": "declined", "error": "refused the draft_job_id"}])
    assert core_cli.clip_state(c6) == "delivered" and core_cli.finalize_label(c6["takes"][1]) == "rejected"


def test_status_names_a_request_left_without_a_job_id(env):
    req = {**FIN, "status": "requested", "error": None}
    c = _clip(status="submitted", takes=[DRAFT, req])
    st = core_cli._clips_stage(env, "studio", [("W01", c)], None)
    assert not st["done"] and "W01 take 2 (the finalize of take 1) is only requested, no job id recorded" in st["detail"]
    assert "clip ingest W01 --failed \"rejected: <its reply, verbatim>\"" in st["detail"]
    assert "clip ingest W01 --job-id JOB_ID --pending" in st["detail"]
    # `slop next` prints only do + cmd (never the detail): do names the request and both ways to close it
    assert st["do"].startswith("close the Higgsfield request with no job id (W01 take 2): record the job id (")
    assert "see above" not in st["do"] and "clip ingest W01 --job-id JOB_ID --pending" in st["do"]
    assert "clip ingest W01 --failed \"rejected: <its reply, verbatim>\" (it then counts 0)" in st["do"]
    assert core_cli.requested_takes({**c, "takes": [DRAFT, {**req, "id": DRAFT_JOB}]}) == []
    # two clips each with a request: both named, the commands keep the CLIP placeholder
    st = core_cli._clips_stage(env, "studio", [("W01", c), ("W02", {**c, "id": "W02"})], None)
    assert "(W01 take 2, W02 take 2)" in st["do"] and "clip ingest CLIP --failed" in st["do"]


def test_the_standing_yes_does_not_cover_a_new_take_after_a_refused_finalize():
    c = _clip(takes=[DRAFT, FIN], locked_at="2026-10-02T07:00:00")       # locked only by `clip ingest --failed`
    proj = {"gates": {"prompts_approved": True},
            "gates_meta": {"prompts_approved": {"covers": {"clips/W01.json": core_cli.clip_prompt_sig(c)}}}}
    assert core_cli.clip_prompt_approved(proj, c) is False
    relocked = {**c, "locked_at": "2026-10-02T08:00:00"}                  # the owner locked it again for a new take
    assert core_cli.clip_prompt_approved(proj, relocked) is True
    assert core_cli.clip_prompt_approved(proj, _clip(takes=[DRAFT, {**FIN, "finalize_of": None}])) is True


def test_spend_shows_requested_credits_apart_and_settled_ones_as_failed(env):
    (env / "clips").mkdir(exist_ok=True)
    c = _clip(status="submitted", takes=[DRAFT, {**FIN, "status": "requested", "error": None}])
    (env / "clips" / "W01.json").write_text(json.dumps(c), encoding="utf-8")
    hf_row(env, "W01", 1, 12)
    hf_row(env, "W01", 2, 48, kind="video-finalize")
    proj = json.loads((env / "project.json").read_text(encoding="utf-8"))
    hfs = core_cli.ledger_summary(env, proj)["by_provider"]["higgsfield"]
    assert hfs["credits"] == 60 and hfs["requested"] == 48 and hfs["requested_takes"] == ["W01 take 2"]
    assert "(48 of them only requested, no job id yet: W01 take 2)" in core_cli._requested_note(hfs)
    with pytest.raises(SlopError) as e:                     # the cap error says what holds the credits, and the fix
        ledger.check_budget(env, "higgsfield", add_credits=70, yes=True)
    assert "Of that, W01 take 2 is only requested (no job id recorded)" in str(e.value)
    assert "slop clip ingest W01 --failed \"rejected: <its reply, verbatim>\"" in str(e.value)
    ledger.record(env, provider="higgsfield", model=hf.MODEL, kind="video-refund", credits=-48.0, status="ok",
                  units={"clip": "W01", "take": 2}, note="rejected: refunded")
    c["takes"][1].update(status="failed", error="rejected"); c["status"] = "locked"
    (env / "clips" / "W01.json").write_text(json.dumps(c), encoding="utf-8")
    led = core_cli.ledger_summary(env, proj)
    hfs = led["by_provider"]["higgsfield"]
    assert hfs["credits"] == 12 and "requested" not in hfs and hfs["failed"] == 1 and hfs["calls"] == 2
    assert led["budget"]["higgsfield_left"] == 108
    with pytest.raises(SlopError) as e:                     # nothing left only requested: the plain cap error
        ledger.check_budget(env, "higgsfield", add_credits=200, yes=True)
    assert "only requested" not in str(e.value)


# ------------------------------------------------------------------------------------------------ end to end
def _sung_locked(env, tmp_path, cid="W01"):
    assert run(env, "clip", "new", "s002", "--kind", "sung", "--id", cid, "--provider", "higgsfield")[0] == 0
    c = store.load(env, cid)
    f = tmp_path / f"{cid}.txt"
    f.write_text(tpl.SLOT_RE.sub("she sings it softly", c["body"]["prompt"]), encoding="utf-8")
    assert run(env, "clip", "set", cid, "--prompt-file", str(f))[0] == 0
    assert run(env, "clip", "lock", cid)[0] == 0


@needs_ffmpeg
def test_refused_finalize_end_to_end(env, tmp_path, monkeypatch):
    monkeypatch.setattr(hosting, "status", lambda: {"running": False, "url": None})
    monkeypatch.setattr(hosting, "ensure_verified", lambda wait_s=20.0: {"verified": False, "error": "down"})
    _sung_locked(env, tmp_path)
    assert run(env, "gate", "prompts", "--approve")[0] == 0              # the owner's standing yes covers W01
    assert run(env, "clip", "submit", "W01", "--res", "480p")[0] == 0
    _rejected_after_unlim_and_timeout(json.loads((env / "clips/W01/higgsfield-request.json").read_text("utf-8")))
    c = store.load(env, "W01")
    mp4 = H.make_mp4(tmp_path / "draft.mp4", env / c["window"]["wav"], duration=4)
    assert run(env, "clip", "ingest", "W01", "--job-id", DRAFT_JOB, "--pending")[0] == 0
    assert run(env, "clip", "ingest", "W01", "--file", str(mp4), "--job-id", DRAFT_JOB, "--credits", "12")[0] == 0
    c = store.load(env, "W01")
    c["takes"][0]["sync"] = {"mode": "copy", "ncc": .49, "lag_s": .475, "synced": [[10.0, 11.5]]}
    store.save(env, c)
    rc, out = run(env, "clip", "submit", "W01", "--provider", "higgsfield", "--finalize-from", "1", "--yes")
    assert rc == 0 and out["expected_credits"] == 48, out
    req = json.loads(Path(out["request_file"]).read_text(encoding="utf-8"))
    rej = [s for s in req["how_to_run"] if s.startswith("REJECTED")]
    assert rej and "slop -p demo clip ingest W01 --failed \"rejected: <the reply" in rej[0]
    assert "REJECTED below" in req["how_to_run"][0] and "do not re-lock or resubmit" in rej[0]
    _rejected_after_unlim_and_timeout(req)
    assert any("--credits <the credits really charged: 0 if it ran on use_unlim>" in s for s in req["how_to_run"])
    assert ledger.spent_credits(env) == 60
    rc, st = run(env, "status")
    assert rc == 0 and "only requested, no job id recorded" in st["text"]
    assert "(48 of them only requested, no job id yet: W01 take 2)" in st["text"]
    rc, sp = run(env, "spend", "--offline")
    assert "requests with no job id recorded (W01 take 2)" in sp["text"]
    assert "clip ingest W01 --job-id JOB_ID --pending" in sp["text"] and "CLIP" not in sp["text"]
    # the connector refused the draft_job_id: the bot records it as the request file says
    rc, out = run(env, "clip", "ingest", "W01", "--failed", "rejected: draft_job_id is not a finalizable draft")
    assert rc == 0, out
    assert "counts 0 credits" in out["text"] and "take 1 stays W01's take" in out["text"], out   # integration: clips
    assert "clip lock" not in out["text"] and "--finalize-from 1 --yes" in out["text"]   # no new paid draft offered
    row = ledger.rows(env)[-1]
    assert (row["kind"], row["status"], row["credits"], row["units"]["take"]) == ("video-finalize", "failed", 0.0, 2)
    assert ledger.spent_credits(env) == 12                                    # only the draft was charged
    rc, st = run(env, "status")
    clips = next(s for s in st["stages"] if s["stage"] == "clips")
    assert "finalize rejected: W01 take 2 (1080p, of take 1: draft_job_id is not a finalizable" in clips["detail"], clips
    assert "submitted" not in clips["detail"] and "only requested" not in clips["detail"]
    assert "higgsfield 12 of 120 credits" in st["text"] and "only requested" not in st["text"]
    rc, sp = run(env, "spend", "--offline")
    assert sp["ledger"]["by_provider"]["higgsfield"]["failed"] == 1 and sp["ledger"]["budget"]["higgsfield_left"] == 108
    # the draft stays the clip's take: the clip file says "delivered" (integration), so no submit can buy a new draft
    # behind the owner's back (a new take needs a deliberate re-lock)
    assert store.load(env, "W01")["status"] == "delivered"
    rc, out = run(env, "clip", "status", "W01")
    assert rc == 0 and "delivered" in out["text"], out
    rc, out = run(env, "clip", "submit", "W01", "--res", "480p")
    assert rc != 0 and "not locked" in out["error"], out
    assert len(store.load(env, "W01")["takes"]) == 2 and ledger.spent_credits(env) == 12


def _rejected_after_unlim_and_timeout(req: dict) -> None:
    """A refusal is recorded only after the unlim_choice / timeout step: neither is a refusal, and a timed-out job may
    have run and been charged (recording it as rejected would under-count)."""
    steps = req["how_to_run"]
    i_rej = next(i for i, s in enumerate(steps) if s.startswith("REJECTED"))
    i_unl = next(i for i, s in enumerate(steps) if "unlim_choice" in s and "timeout" in s)
    assert i_unl < i_rej, steps
    assert "NOT an unlim_choice question" in steps[i_rej] and "or a timeout" in steps[i_rej]
    assert "--failed \"rejected: not sent, <why>\"" in steps[i_rej]        # the owner said no after the estimate: closed too
    assert "after the estimate" in steps[i_rej] and "estimate_video_cost or the batch refuses" in steps[i_rej]
    assert "do NOT record it as rejected" in steps[i_unl] and "`transactions`" in steps[i_unl]
    assert "never choose for them" in steps[i_unl].lower() and "retry only once the outcome is known" in steps[i_unl]

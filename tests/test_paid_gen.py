"""Phase-2 (paid track) hardening of slop.gen / slop.sync, tested offline against recorded provider shapes.

Fixtures: tests/fixtures/gen/openrouter_real_shapes.json (real OpenRouter responses and bills from the 2026-10-01 probes,
job ids replaced) and tests/fixtures/gen/higgsfield_mcp_tools.json (the request side of the Higgsfield connector's tool
definitions). Covered: the plates/jobs.json batch runner (one estimate, one --yes, resumable), `clip submit --dry-run`
(reference mode for sung clips), the output-audio refusal protocol (retry once, then the other provider), the Lyria
stream decoder (independently padded base64 chunks), the image-edit medium, the calibrated image estimate, explicit
tokens to the audio window, the Higgsfield request against the connector schema (priced with estimate_video_cost).
"""
from __future__ import annotations

import base64
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

from slop import ledger  # noqa: E402
from slop.cli import main  # noqa: E402
from slop.gen import clips, higgsfield as hf, imgedit, models as reg, song, store, templates as tpl  # noqa: E402
from slop.gen.openrouter import classify  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "gen"
REAL = json.loads((FIX / "openrouter_real_shapes.json").read_text(encoding="utf-8"))
MCP = json.loads((FIX / "higgsfield_mcp_tools.json").read_text(encoding="utf-8"))
KEY = "sk-or-v1-test-not-a-real-key"
needs_ffmpeg = pytest.mark.skipif(not H.FFMPEG, reason="ffmpeg is required")


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SLOP_PROJECTS", str(tmp_path / "projects"))
    monkeypatch.setenv("OPENROUTER_API_KEY", KEY)
    monkeypatch.delenv("SLOP_PROJECT", raising=False)
    H.write_cache(tmp_path / "home")
    return H.make_project(tmp_path / "projects", audio=bool(H.FFMPEG))


def run(pdir, *argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(["--json", "--project", str(pdir), *argv])
    return rc, json.loads(buf.getvalue())


def fake(monkeypatch, routes):
    s = H.FakeSession(routes)
    import requests
    monkeypatch.setattr(requests, "Session", lambda: s)
    return s


def images_ok(method, url, body):
    n = int(body.get("n") or 1)
    return H.FakeResp(200, {"data": [{"b64_json": H.b64(H.png_bytes((10 * i, 20, 30))), "media_type": "image/png"}
                                     for i in range(n)], "usage": {"cost": round(.004 * n, 6)}})


def write_jobs(pdir: Path, jobs: list[dict]) -> Path:
    (pdir / "plates" / "api").mkdir(parents=True, exist_ok=True)
    (pdir / "plates" / "api" / "street.txt").write_text("Wide shot of a wet street at night, illustrated.\n", encoding="utf-8")
    p = pdir / "plates" / "jobs.json"
    p.write_text(json.dumps({"batch": "b1", "jobs": jobs}), encoding="utf-8")
    return p


JOBS = [{"plate": "hall", "prompt": "Wide shot of a long concrete hall, fog, clean cel-shaded illustration. No text.",
         "aspect": "16:9", "n": 2},
        {"plate": "roof", "prompt": "Wide shot of a rooftop at dusk, clean cel-shaded illustration. No text.", "aspect": "16:9",
         "n": 1},
        {"plate": "street", "prompt_file": "plates/api/street.txt", "aspect": "16:9", "n": 1}]


# ------------------------------------------------------------------------------------------------ batch runner
def test_jobs_dry_run_sends_nothing(env, monkeypatch):
    write_jobs(env, JOBS)
    s = fake(monkeypatch, {})                                            # any request would raise
    rc, out = run(env, "gen", "image", "--jobs", "--quality", "low")
    assert rc == 0, out
    assert out["dry_run"] is True and out["planned_images"] == 4 and not s.calls and not ledger.rows(env)
    assert out["est_usd"] == pytest.approx(sum(j["est_usd"] for j in out["jobs"]))
    assert "DRY RUN" in out["text"] and f"slop -p {env.name} gen image --jobs plates/jobs.json --quality low --yes" in out["text"]


def test_jobs_run_once_then_resume(env, monkeypatch):
    write_jobs(env, JOBS)
    s = fake(monkeypatch, {("POST", "/images"): images_ok})
    rc, out = run(env, "gen", "image", "--jobs", "--quality", "low", "--yes", "--workers", "1")
    assert rc == 0, out
    assert len(s.calls) == 3 and {c["body"]["n"] if "n" in c["body"] else 1 for c in s.calls} == {1, 2}
    assert all(c["body"]["quality"] == "low" and c["body"]["aspect_ratio"] == "16:9" for c in s.calls)
    street = next(c for c in s.calls if "wet street" in c["body"]["prompt"])
    assert street["body"]["prompt"] == "Wide shot of a wet street at night, illustrated."      # prompt_file read
    hall = sorted(p.name for p in (env / "plates" / "cands" / "hall").glob("*.png"))
    assert hall == ["1.png", "2.png", "3.png"]                           # 1.png = the fixture's existing pick
    side = json.loads((env / "plates" / "cands" / "hall" / "2.json").read_text())
    assert side["job"] == "hall" and side["jobs_file"] == "plates/jobs.json" and side["model"] == "openai/gpt-image-2"
    assert len([r for r in ledger.rows(env) if r["kind"] == "image"]) == 3
    assert out["cost_usd"] == pytest.approx(.016)
    # re-run: everything is done, nothing is sent
    rc, out = run(env, "gen", "image", "--jobs", "--quality", "low", "--yes")
    assert rc == 0 and len(s.calls) == 3 and "nothing to do" in out["text"]
    # resume: a job that needs one more image makes exactly one
    jobs = [dict(j) for j in JOBS]; jobs[0]["n"] = 3
    write_jobs(env, jobs)
    rc, out = run(env, "gen", "image", "--jobs", "--quality", "low", "--yes")
    assert rc == 0 and len(s.calls) == 4 and s.calls[-1]["body"].get("n", 1) == 1
    assert out["jobs"][0]["done"] == 2 and out["jobs"][0]["need"] == 1


def test_jobs_only_missing_and_flags(env, monkeypatch):
    write_jobs(env, JOBS + [{"plate": "hero-cu", "prompt": "Close-up of the lead.", "n": 1}])
    s = fake(monkeypatch, {("POST", "/images"): images_ok})
    rc, out = run(env, "gen", "image", "--jobs", "--only", "roof,street")
    assert rc == 0 and out["planned_images"] == 2 and [j["plate"] for j in out["jobs"] if not j["skip"]] == ["roof", "street"]
    rc, out = run(env, "gen", "image", "--jobs", "--missing")
    skipped = {j["plate"]: j["skip"] for j in out["jobs"]}
    assert "candidates" in skipped["hero-cu"] and "candidates" in skipped["hall"] and skipped["roof"] is None
    rc, out = run(env, "gen", "image", "--jobs", "--only", "nope")
    assert rc == 1 and "not in the jobs file" in out["error"]
    rc, out = run(env, "gen", "image", "a prompt", "--jobs")
    assert rc == 1 and "drop the prompt" in out["error"]
    rc, out = run(env, "gen", "image", "a prompt", "--plate", "x", "--only", "roof")
    assert rc == 1 and "--jobs" in out["error"]
    rc, out = run(env, "gen", "image", "--jobs", "plates/none.json")
    assert rc == 1 and "slop -p demo plates book" in out["error"]
    assert not s.calls


def test_jobs_budget_is_checked_for_the_whole_batch_first(env, monkeypatch):
    write_jobs(env, JOBS)
    proj = json.loads((env / "project.json").read_text()); proj["budget"]["openrouter_usd"] = .01
    (env / "project.json").write_text(json.dumps(proj))
    s = fake(monkeypatch, {})
    rc, out = run(env, "gen", "image", "--jobs", "--quality", "low")
    assert rc == 0 and "does not fit the budget" in out["text"]
    rc, out = run(env, "gen", "image", "--jobs", "--quality", "low", "--yes")
    assert rc == 1 and "budget cap" in out["error"] and not s.calls


def test_jobs_stop_on_account_problems_and_go_on_after_a_refusal(env, monkeypatch):
    write_jobs(env, JOBS)

    def credits_out(method, url, body):
        return H.FakeResp(402, {"error": {"code": 402, "message": "Insufficient credits"}})
    s = fake(monkeypatch, {("POST", "/images"): credits_out})
    rc, out = run(env, "gen", "image", "--jobs", "--yes", "--workers", "1")
    assert rc == 1 and out["stopped"] and "STOPPED" in out["error"] and len(s.calls) == 1
    assert [r["status"] for r in out["results"]] == ["credits", "not run", "not run"]

    def refuse_roof(method, url, body):
        if "rooftop" in body["prompt"]:
            return H.FakeResp(400, {"error": {"message": "Your request was rejected by the safety system (moderation)"}})
        return images_ok(method, url, body)
    s = fake(monkeypatch, {("POST", "/images"): refuse_roof})
    rc, out = run(env, "gen", "image", "--jobs", "--yes", "--workers", "1")
    assert rc == 1 and not out["stopped"] and len(s.calls) == 3 and "refused" in out["error"]
    assert {r["plate"]: r["status"] for r in out["results"]} == {"hall": "ok", "roof": "moderation", "street": "ok"}


# ------------------------------------------------------------------------------------------------ estimates vs real bills
def test_estimates_match_the_real_bills():
    for b in REAL["billed"]:
        if b["model"].startswith("bytedance/"):
            est = reg.estimate_video(b["model"], b["duration"], b["resolution"])
            assert abs(est - b["usd"]) / b["usd"] < .01, (b, est)
    img = next(b for b in REAL["billed"] if b["model"] == "openai/gpt-image-2")
    prompt = ("Close-up of a young woman drawn in clean anime cel-shading: straight black bob with blunt bangs and one "
              "red streak, a thin black headset microphone at her cheek, a white shirt. She sings on a dark stage with "
              "one red spotlight. Clean anime cel-shaded illustration, flat colours. No text, no letters, no logos.")
    est = reg.estimate_image("openai/gpt-image-2", "1K", "low", 1, 0, prompt=prompt)
    assert abs(est - img["usd"]) / img["usd"] < .15, est
    assert reg.prompt_tokens(None) is None and reg.prompt_tokens("abcd" * 10) == 10


def test_real_error_texts_classify():
    assert classify(400, REAL["audio_data_uri_rejected"]["message"]) == "bad_request"
    assert classify(None, "job failed: " + REAL["job_failed_sensitive_text"]) == "sensitive"


# ------------------------------------------------------------------------------------------------ clips
def sung_locked(env, tmp_path, cid="W01", shot="s002", *extra) -> dict:
    rc, out = run(env, "clip", "new", shot, "--kind", "sung", "--id", cid, *extra)
    assert rc == 0, out
    c = store.load(env, cid)
    f = tmp_path / f"{cid}.txt"; f.write_text(tpl.SLOT_RE.sub("she sings it softly", c["body"]["prompt"]), encoding="utf-8")
    assert run(env, "clip", "set", cid, "--prompt-file", str(f))[0] == 0
    rc, out = run(env, "clip", "lock", cid)
    assert rc == 0, out
    return store.load(env, cid)


@needs_ffmpeg
def test_dry_run_shows_reference_mode_and_changes_nothing(env, tmp_path, monkeypatch):
    sung_locked(env, tmp_path)
    before = (env / "clips" / "W01.json").read_bytes()
    s = fake(monkeypatch, {})
    rc, out = run(env, "clip", "submit", "W01", "--dry-run", "--res", "480p")
    assert rc == 0, out
    assert out["dry_run"] and out["mode"] == "reference" and not s.calls and not ledger.rows(env)
    ws = out["would_send"]
    assert "frame_images" not in ws and ws["refs"] == ["image_url:data", "audio_url:https://HOSTED-AT-SUBMIT/W01.wav"]
    assert ws["resolution"] == "480p" and ws["prompt"].startswith("@Image1 sings @Audio1.")
    assert out["est_usd"] == pytest.approx(reg.estimate_video("bytedance/seedance-2.5", 4, "480p"))
    assert "slop -p demo gen host W01 --tunnel" in out["text"] and "frame_images: none" in out["text"]
    assert (env / "clips" / "W01.json").read_bytes() == before                  # nothing saved, hosted or spent
    run(env, "gen", "host", "W01", "--url", "https://cdn.example.com/W01.wav")
    rc, out = run(env, "clip", "submit", "W01", "--dry-run")
    assert out["would_send"]["refs"][-1] == "audio_url:https://cdn.example.com/W01.wav" and not out["warnings"]
    # a cheap-draft model keeps reference mode
    run(env, "clip", "set", "W01", "--model", "bytedance/seedance-2.0-mini")
    rc, out = run(env, "clip", "submit", "W01", "--dry-run", "--res", "720p")
    assert out["mode"] == "reference" and out["model"] == "bytedance/seedance-2.0-mini" and out["lock_problems"] == []
    assert "slop -p demo clip lock W01" in out["text"]                                  # the change made it a draft


@needs_ffmpeg
def test_dry_run_first_frame_motion_and_higgsfield(env, tmp_path, monkeypatch):
    s = fake(monkeypatch, {})
    rc, out = run(env, "clip", "new", "s004", "--kind", "motion", "--frame", "first")
    rc, out = run(env, "clip", "submit", "M-s004", "--dry-run")
    assert rc == 0 and out["mode"] == "first-frame" and out["would_send"]["refs"] == ["first_frame:image"]
    assert out["lock_problems"] and "before submit" in out["text"]               # a draft with [[slots]]
    c = sung_locked(env, tmp_path, "W02", "s003", "--provider", "higgsfield")
    rc, out = run(env, "clip", "submit", "W02", "--dry-run", "--res", "480p")
    assert rc == 0 and out["provider"] == "higgsfield" and out["mode"] == "omni_reference"
    assert out["would_send"]["model"] == "seedance_2_5" and out["would_send"]["draft"] is True
    assert out["expected_credits"] == 3 * c["body"]["duration"]
    assert not (env / "clips" / "W02" / "higgsfield-request.json").exists() and not s.calls


@needs_ffmpeg
def test_sensitive_refusal_retries_once_then_switches_provider(env, tmp_path, monkeypatch):
    sung_locked(env, tmp_path)
    run(env, "gen", "host", "W01", "--url", "https://cdn.example.com/W01.wav")
    ids = iter(["gen-vid-a", "gen-vid-b"])

    def post(method, url, body):
        return H.FakeResp(202, {**REAL["videos_submit_response"], "id": next(ids)})

    def get(method, url, body):
        return H.FakeResp(200, {"status": "failed", "error": "The request failed because the " + REAL["job_failed_sensitive_text"]})
    fake(monkeypatch, {("POST", "/videos"): post, ("GET", "/videos/"): get})
    assert run(env, "clip", "submit", "W01", "--yes")[0] == 0
    rc, out = run(env, "clip", "poll", "W01")
    assert "retry once with a changed request" in out["text"] and "--prompt-file FILE" in out["text"]
    c = store.load(env, "W01")
    assert c["status"] == "locked" and c["takes"][0]["error_class"] == "sensitive" and len(c["refusals"]) == 1
    assert abs(ledger.spent_usd(env)) < 1e-9                                   # failed jobs are not billed
    assert run(env, "clip", "submit", "W01", "--yes")[0] == 0
    rc, out = run(env, "clip", "poll", "W01")
    assert "refused 2 times" in out["text"] and "--provider higgsfield" in out["text"]
    assert store.load(env, "W01")["takes"][1]["next"].startswith("NEXT (openrouter refused 2 times")


@needs_ffmpeg
def test_refusal_at_submit_and_copyright_first_retry(env, tmp_path, monkeypatch):
    sung_locked(env, tmp_path)
    run(env, "gen", "host", "W01", "--url", "https://cdn.example.com/W01.wav")
    fake(monkeypatch, {("POST", "/videos"): H.FakeResp(400, {"error": {"code": 400, "message":
                       "The request failed because the output audio may be related to copyright restrictions"}})})
    rc, out = run(env, "clip", "submit", "W01", "--yes")
    assert rc == 1 and out["status"] == "copyright" and "retry once as it is" in out["text"]
    c = store.load(env, "W01")
    assert c["status"] == "locked" and c["refusals"][0]["status"] == "copyright" and ledger.spent_usd(env) == 0


@needs_ffmpeg
def test_real_completed_shape_settles_to_usage_cost(env, tmp_path, monkeypatch):
    sung_locked(env, tmp_path)
    run(env, "clip", "set", "W01", "--model", "bytedance/seedance-2.0-mini", "--res", "480p", "--duration", "5")
    c = store.load(env, "W01")
    f = tmp_path / "p.txt"; f.write_text(tpl.SLOT_RE.sub("she sings", c["body"]["prompt"]), encoding="utf-8")
    run(env, "clip", "set", "W01", "--prompt-file", str(f))
    assert run(env, "clip", "lock", "W01")[0] == 0
    run(env, "gen", "host", "W01", "--url", "https://cdn.example.com/W01.wav")
    take = H.make_mp4(tmp_path / "take.mp4", env / store.load(env, "W01")["window"]["wav"])
    done = REAL["videos_poll_completed"]
    s = fake(monkeypatch, {("POST", "/videos"): H.FakeResp(202, REAL["videos_submit_response"]),
                           ("GET", "/content?index=0"): H.FakeResp(200, content=take.read_bytes()),
                           ("GET", "/videos/gen-vid-fixture-0001"): H.FakeResp(200, done)})
    rc, out = run(env, "clip", "submit", "W01", "--yes")
    assert rc == 0 and abs(out["est_usd"] - done["usage"]["cost"]) / done["usage"]["cost"] < .01
    rc, out = run(env, "clip", "poll", "W01")
    assert out["results"][0]["status"] == "delivered" and out["results"][0]["cost_usd"] == done["usage"]["cost"]
    assert s.calls[-1]["url"] == done["unsigned_urls"][0]                     # the URL the real response names
    assert ledger.spent_usd(env, "openrouter") == pytest.approx(done["usage"]["cost"])


# ------------------------------------------------------------------------------------------------ Higgsfield vs the connector
@needs_ffmpeg
def test_higgsfield_request_matches_the_connector_schema(env, tmp_path, monkeypatch):
    sung_locked(env, tmp_path, "W01", "s002", "--provider", "higgsfield")
    rc, out = run(env, "clip", "submit", "W01", "--yes", "--res", "480p")
    assert rc == 0, out
    req = json.loads(Path(out["request_file"]).read_text())
    item = req["request"]
    assert set(item) == set(MCP["generate_video_batch"]["requests_item"]["required"])      # additional_properties false
    prm = item["params"]
    allowed = set(MCP["generate_video"]["params"]["properties"]) | set(MCP["model_params_used_by_slop"]["keys"])
    assert set(prm) <= allowed and "model" in prm and "get_cost" not in prm and "count" not in prm
    assert "use_unlim" not in prm                                               # omitted: the server asks the user
    for m in prm["medias"]:
        assert set(m) == set(MCP["generate_video"]["params"]["medias_item"]["required"])
        assert not m["value"].startswith("https://")                           # media ids only, never URLs
    # the price: generate_video no longer takes get_cost; estimate_video_cost takes the same params and submits nothing
    assert "get_cost" not in MCP["generate_video"]["params"]["properties"]
    assert "estimate_video_cost" in MCP["generate_video"]["pricing"]
    est = req["estimate"]
    assert "get_cost" not in req and est == {"tool": "estimate_video_cost", "params": prm}
    tool = MCP[est["tool"]]
    assert tool["required"] == ["params"] and tool["params"]["same_as"] == "generate_video"
    assert set(tool["params"]["required"]) <= set(est["params"]) and tool["submits"].startswith("nothing")
    steps = " ".join(req["how_to_run"])
    assert "estimate_video_cost {params: <request.params, unchanged>}" in steps and "generate_video {" not in steps
    assert "timeout_seconds:15" in steps and MCP["jobs_wait"]["timeout_seconds"]["maximum"] == 15
    assert "unlim_choice" in steps and "media_confirm" in steps and "media_import_url" in steps
    assert "do NOT resubmit" in steps and "retry only once the outcome is known" in steps    # the connector's own rule
    assert "retry only after the original outcome is known" in MCP["generate_video"]["transport_timeout"]
    # job ids: Higgsfield ids are UUIDs (jobs_wait refuses anything else) - a warning, the id is kept
    rc, out = run(env, "clip", "ingest", "W01", "--pending", "--job-id", "job-1")
    assert rc == 0 and out["warnings"] and "UUID" in out["warnings"][0]
    assert hf.job_id_problem("0f8fad5b-d9cb-469f-a165-70867728950e") is None


# ------------------------------------------------------------------------------------------------ Lyria stream
def test_padded_chunks_decode_in_full():
    raw = bytes(range(256)) * 41 + b"tail!"                                  # not a multiple of 3
    parts = [raw[i:i + 1000] for i in range(0, len(raw), 1000)]                # 1000 % 3 != 0: every chunk is padded
    chunks = [base64.b64encode(p).decode() for p in parts]
    assert "=" in chunks[0]
    assert base64.b64decode("".join(chunks)) == parts[0]                      # the old join stops at the first pad
    assert song.b64_chunks(chunks) == raw
    one = base64.b64encode(raw).decode()                                       # one string split anywhere
    assert song.b64_chunks([one[:1001], one[1001:2002], one[2002:]]) == raw
    assert song.b64_chunks(["data:audio/mpeg;base64," + chunks[0]] + chunks[1:]) == raw
    ev = [{"choices": [{"delta": {"content": [{"type": "text", "text": "[Verse 1] "}, {"type": "text", "text": "Go"}]}}]},
          *[{"choices": [{"delta": {"audio": {"data": c, "transcript": ""}}}]} for c in chunks],
          {"choices": [], "usage": {"cost": .04}}]
    audio, text, usage = song.collect(ev)
    assert audio == raw and text == "[Verse 1] Go" and usage["cost"] == .04


def test_song_cli_with_padded_stream(env, monkeypatch, tmp_path):
    raw = b"ID3" + bytes(range(256)) * 20
    lines = [b": OPENROUTER PROCESSING"] + [
        b"data: " + json.dumps({"choices": [{"delta": {"audio": {"data": base64.b64encode(raw[i:i + 700]).decode()}}}]}).encode()
        for i in range(0, len(raw), 700)] + [b"data: " + json.dumps({"choices": [], "usage": {"cost": 0.04}}).encode(),
                                             b"data: [DONE]"]
    fake(monkeypatch, {("POST", "/chat/completions"): H.FakeResp(200, content=b"", lines=lines)})
    rc, out = run(env, "gen", "song", "--prompt", "Trance, 132 BPM, one female voice. Lyrics: [Chorus] Go", "--clip", "--yes")
    assert rc == 0, out
    assert Path(out["mp3"]).read_bytes() == raw and out["cost_usd"] == .04
    assert ledger.rows(env)[-1]["est_usd"] == pytest.approx(.04)


# ------------------------------------------------------------------------------------------------ image edit medium
def test_edit_medium_illustration(env, monkeypatch, tmp_path):
    src = H.write_png(tmp_path / "plate.png", (120, 30, 30), (96, 54))
    (tmp_path / "plate.json").write_text(json.dumps({"prompt": "Close-up of the lead, clean anime cel-shaded illustration"}))
    out_png = H.png_bytes((30, 30, 120), (96, 54))
    resp = H.FakeResp(200, {"id": "gen-1", "choices": [{"message": {"content": "", "images": [
        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + H.b64(out_png)}}]}}], "usage": {"cost": .1352}})
    s = fake(monkeypatch, {("POST", "/chat/completions"): resp})
    rc, out = run(env, "gen", "edit", str(src), str(tmp_path / "a.png"), "--change", "her shirt: make it red", "--yes")
    assert rc == 0 and out["medium"] == "photo" and "--medium illustration" in out["warnings"][0]
    rc, out = run(env, "gen", "edit", str(src), str(tmp_path / "b.png"), "--change", "her shirt: make it red", "--yes",
                  "--medium", "illustration")
    assert rc == 0 and not out["warnings"]
    text = s.calls[-1]["body"]["messages"][0]["content"][0]["text"]
    assert text.startswith("Edit this illustration. Change only her shirt: make it red.")
    assert "Photorealistic" not in text and "photograph" not in text.replace("Not a photograph", "")
    proj = json.loads((env / "project.json").read_text()); proj["look"]["medium"] = "illustration"
    (env / "project.json").write_text(json.dumps(proj))
    rc, out = run(env, "gen", "edit", str(src), str(tmp_path / "c.png"), "make it night", "--yes")
    assert out["medium"] == "illustration"
    assert imgedit.message_text("x").startswith("Edit this photograph. ")              # default unchanged


# ------------------------------------------------------------------------------------------------ explicit window tokens
def test_tokens_go_to_the_audio_window_when_it_takes_them(env, monkeypatch):
    import slop.audio.window as aw
    seen = {}

    def with_tokens(pdir, clip, t0, t1, mode="clean", quoted=None, listen=False, tokens=None):
        seen["tokens"] = tokens
        return {"file": f"audio/windows/{clip}.mp3", "wav": f"audio/windows/{clip}.wav", "warnings": []}

    def without(pdir, clip, t0, t1, mode="clean", quoted=None, listen=False):
        seen["called"] = True
        return {"file": f"audio/windows/{clip}.mp3", "wav": f"audio/windows/{clip}.wav", "warnings": []}
    toks = [[10.35, 10.55, "up"], [10.6, 11.0, "darling"]]
    monkeypatch.setattr(aw, "make_window", with_tokens)
    w, _ = clips.cut_window(env, "X1", 9.3, 4, "sung", "clean", quoted="up, darling,", tokens=toks)
    assert seen["tokens"] == toks and w["quoted"] == "up, darling,"
    seen.clear()
    clips.cut_window(env, "X1", 9.3, 4, "sung", "clean", quoted=None, tokens=toks)
    assert seen["tokens"] is None                                              # no quote: every word, no tokens
    monkeypatch.setattr(aw, "make_window", without)
    seen.clear()
    clips.cut_window(env, "X1", 9.3, 4, "sung", "clean", quoted="up, darling,", tokens=toks)
    assert seen == {"called": True}                                            # an older audio module: not passed


def test_her_words_takes_the_tight_match_not_an_earlier_repeat():
    from slop.sync.songdata import SongData
    s = SongData(None, words=H.words_doc(), beats=H.beats_doc(), hits=H.hits_doc())
    hw, ok = s.her_words("here it comes", 13.3, 17.3)                   # "here we go now, here it comes so fast"
    assert ok and [round(w["t0"], 2) for w in hw] == [14.8, 15.15, 15.3]   # the greedy port took "here" at 13.40
    hw, ok = s.her_words("here we go", 13.3, 17.3)                         # unrepeated start: unchanged
    assert ok and [round(w["t0"], 2) for w in hw] == [13.4, 13.75, 13.9]
    assert s.her_words("nothing here", 13.3, 17.3)[1] is False


@needs_ffmpeg
def test_her_words_window_keeps_the_right_repeat_end_to_end(env):
    import inspect
    from slop.audio.window import make_window
    rc, out = run(env, "clip", "new", "s003", "--kind", "sung", "--words", "here it comes")
    assert rc == 0, out
    c = out["clip"]
    assert [w[0] for w in c["her_words"]] == [14.8, 15.15, 15.3]
    meta = json.loads((env / "audio" / "windows" / f"{c['id']}.json").read_text())
    if "tokens" in inspect.signature(make_window).parameters:              # the audio module keeps exactly these words
        assert [w["t0"] for w in meta["words"]] == [14.8, 15.15, 15.3]
    assert tpl.quoted_words(c["body"]["prompt"]) == "here it comes"


# ------------------------------------------------------------------------------------------------ prompt scaffold
def test_motion_hits_merge_near_duplicates():
    lead = tpl.lead_words({})
    p = tpl.motion_prompt(t0=20.0, duration=4, shot={}, lead=lead, kicks=[20.32, 21.68, 23.51], downbeats=[21.70, 23.52])
    assert "On the hits (0.32, 1.68, 3.51 s)" in p

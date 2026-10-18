"""Integration locks for the polish round after the live Quick run inside a real Grok Bot (e2e/QUICK-E2E.md).

1. The identity anchor reaches every stills route the skills offer: the ChatGPT-plan route (`gen image --provider
   codex`, which `slop agents use codex --for images` makes the default and skill mv-quick offers for $0 stills) sends
   a jobs.json job's "refs" (written by `slop plates book --anchor PLATE`) as `codex exec -i` images, resolves `--ref
   PLATE[:K]`, refuses links it cannot attach, and resumes only images made with the same references.
2. `gen image --ref` passes URLs (https and data:) to the OpenRouter path unchanged.
3. The skills and docs say what the shipped flags do (`plates book --anchor/--no-anchor`, the full book for G5, ingest
   of GenerateImage outputs), and the public contract (docs/ARCHITECTURE.md) allows the approved close-up as a
   reference on API stills.

Every provider is faked: nothing here spends or calls the network.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shlex
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_K = ROOT / "tests" / "fixtures" / "agents" / "kit.py"
_spec = importlib.util.spec_from_file_location("agents_kit", _K)
K = importlib.util.module_from_spec(_spec); sys.modules.setdefault("agents_kit", K); _spec.loader.exec_module(K)
K = sys.modules["agents_kit"]
_H = ROOT / "tests" / "fixtures" / "gen" / "helpers.py"
_hs = importlib.util.spec_from_file_location("gen_test_helpers", _H)
H = importlib.util.module_from_spec(_hs); sys.modules.setdefault("gen_test_helpers", H); _hs.loader.exec_module(H)
H = sys.modules["gen_test_helpers"]

from slop import cli, ledger, util  # noqa: E402

posix_only = pytest.mark.skipif(os.name == "nt", reason="POSIX fake CLI")
SKILLS = ROOT / "skills"
DOCS = ROOT / "docs"


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# ------------------------------------------------------------------------------------------- 1. the ChatGPT-plan route
@pytest.fixture
def cx(tmp_path, monkeypatch):
    e = K.setup(tmp_path, monkeypatch, engines=("codex",), logged=("codex",))
    e["proj"] = H.make_project(tmp_path / "projects", audio=False)     # hero-cu #1 (picked) / #2, hall #1 (picked)
    monkeypatch.setenv("SLOP_CODEX_IMAGE_FOREGROUND", "1")
    return e


def crun(env, *argv):
    return K.run("--project", str(env["proj"]), *argv)


def execs(env):
    return [c for c in K.calls(env["state"], "codex") if c["argv"][:1] == ["exec"]]


def attached(call) -> list[str]:
    a = call["argv"]
    return [a[i + 1] for i, x in enumerate(a) if x == "-i"]


def anchored_jobs(proj: Path) -> None:
    (proj / "plates" / "jobs.json").write_text(json.dumps({"batch": "b01", "anchor": {
        "ref": "hero-cu:2", "plate": "hero-cu", "k": 2, "file": "plates/cands/hero-cu/2.png"}, "anchored": ["lead-ms"],
        "jobs": [{"plate": "lead-ms", "prompt": "medium shot of her in the hall", "aspect": "16:9", "n": 1,
                  "refs": ["plates/cands/hero-cu/2.png"], "anchor": "hero-cu:2"},
                 {"plate": "roof", "prompt": "an empty rooftop at dawn", "aspect": "16:9", "n": 1}]}))


@posix_only
def test_codex_batch_sends_the_anchor_of_each_job(cx):
    proj = cx["proj"]
    anchored_jobs(proj)
    rc, out = crun(cx, "gen", "image", "--jobs", "--provider", "codex")
    assert rc == 0 and out["dry_run"] and not execs(cx), out
    rows = {r["plate"]: r for r in out["jobs"]}
    assert rows["lead-ms"]["refs"] == ["plates/cands/hero-cu/2.png"] and rows["lead-ms"]["anchor"] == "hero-cu:2"
    assert not rows["roof"].get("refs") and out["anchored"] == ["lead-ms"]
    assert "anchored on hero-cu:2" in out["text"] and "ref_src" not in json.dumps(out) and str(proj) not in json.dumps(
        out["jobs"])
    rc, out = crun(cx, "gen", "image", "--jobs", "--provider", "codex", "--yes")
    assert rc == 0 and len(out["made"]) == 2, out
    with_ref = [c for c in execs(cx) if attached(c)]
    assert len(execs(cx)) == 2 and len(with_ref) == 1, "only the anchored job attaches the close-up"
    assert attached(with_ref[0]) == [str((proj / "plates/cands/hero-cu/2.png").resolve())]
    assert "attached image" in with_ref[0]["stdin_head"]
    assert json.loads((proj / "plates/cands/roof/1.json").read_text())["refs"] == []
    side = json.loads((proj / "plates/cands/lead-ms/1.json").read_text())
    assert side["refs"] == ["plates/cands/hero-cu/2.png"], "project-relative, so a resume compares the same ids"
    n = len(execs(cx))
    rc, out = crun(cx, "gen", "image", "--jobs", "--provider", "codex", "--yes")
    assert rc == 0 and out["planned_images"] == 0 and len(execs(cx)) == n, "resumable with the anchor"
    jobs = json.loads((proj / "plates/jobs.json").read_text())
    jobs["jobs"][0].pop("refs"); jobs["jobs"][0].pop("anchor")                  # `plates book --no-anchor`
    (proj / "plates/jobs.json").write_text(json.dumps(jobs))
    rc, out = crun(cx, "gen", "image", "--jobs", "--provider", "codex")
    assert rc == 0 and out["planned_images"] == 1, "an image made with the anchor is not one made without it"
    assert sum(1 for r in ledger.rows(proj) if r["provider"] == "codex") == 2 and ledger.spent_usd(proj) == 0.0


@posix_only
def test_smoke_the_skill_order_on_the_chatgpt_plan(tmp_path, monkeypatch):
    """mv-quick step 7 with stills on the ChatGPT plan (`agents use codex --for images`, so every `gen image` without
    --quality goes to Codex): lead batch alone, G3 pick, the anchored FULL book, the G5 gate, then the batch. The lead
    plates made after G3 attach the approved close-up; the others attach nothing. Fake codex, $0."""
    pil = pytest.importorskip("PIL.Image")
    env = K.setup(tmp_path, monkeypatch, engines=("codex",), logged=("codex",))
    monkeypatch.setenv("SLOP_PROJECTS", str(tmp_path / "projects"))
    monkeypatch.setenv("SLOP_CODEX_IMAGE_FOREGROUND", "1")
    monkeypatch.delenv("SLOP_PROJECT", raising=False)
    assert K.run("new", "demo", "--tier", "quick")[0] == 0
    assert K.run("-p", "demo", "lead", "--canon", "a woman, 30, orange streak in black hair", "--far", "a woman")[0] == 0
    rc, out = K.run("agents", "use", "codex", "--for", "images")
    assert rc == 0, out
    proj = tmp_path / "projects" / "demo"
    spec = [("lead-cu", "CU", True), ("lead-mcu", "MCU", True), ("lead-fs", "FS", True), ("lead-ws", "WS", True),
            ("hall-ws", "WS", False), ("lead-ms", "MS", True)]
    shots = [{"id": f"s{i + 1:03d}", "t0": 2 * i, "t1": 2 * i + 2, "plate": pl, "lead_on_screen": lead, "framing": fr,
              "img_prompt": ("close-up of {lead} in a hall" if fr in ("CU", "MCU", "MS") else
                             "wide shot of {far} crossing a hall" if lead else "wide shot of an empty hall")}
             for i, (pl, fr, lead) in enumerate(spec)]
    (proj / "board").mkdir(exist_ok=True)
    (proj / "board" / "shots.json").write_text(json.dumps({"version": 1, "duration": 12, "chapters": [], "seedance": [],
                                                           "plates": [], "shots": shots}), encoding="utf-8")
    leads = "lead-cu,lead-mcu,lead-fs,lead-ws"
    assert K.run("-p", "demo", "plates", "book")[0] == 0
    rc, out = K.run("-p", "demo", "gen", "image", "--jobs", "--only", leads, "--yes")
    assert rc == 0 and out["provider"] == "codex" and out.get("provider_note"), out
    assert {Path(f).parent.name for f in out["made"]} == set(leads.split(",")), "the lead batch runs alone"
    assert not any(attached(c) for c in execs(env)), "before G3 nothing is anchored"
    assert K.run("-p", "demo", "plates", "pick", "lead-cu", "1")[0] == 0
    rc, out = K.run("-p", "demo", "plates", "book", "--anchor", "lead-cu")
    assert rc == 0 and out["anchored"] == ["lead-fs", "lead-mcu", "lead-ms", "lead-ws"], out
    rc, out = K.run("-p", "demo", "gate", "prompts", "--approve", "--note", "yes, go")
    assert rc == 0, out
    rc, out = K.run("-p", "demo", "gen", "image", "--jobs", "--missing")
    assert rc == 0 and out["dry_run"] and out["anchored"] == ["lead-ms"], out
    need = {r["plate"]: r["need"] for r in out["jobs"] if not r.get("skip")}
    assert set(need) == {"hall-ws", "lead-ms"}, "the G5 batch skips the 4 lead test plates"
    n = len(execs(env))
    rc, out = K.run("-p", "demo", "gen", "image", "--jobs", "--missing", "--yes")
    assert rc == 0 and len(out["made"]) == sum(need.values()), out
    new = execs(env)[n:]
    picked = next(p for p in (proj / "plates/cands/lead-cu").glob("1.*") if p.suffix != ".json").resolve()
    assert [attached(c) for c in new if attached(c)] == [[str(picked)]] * need["lead-ms"]
    assert sum(1 for c in new if not attached(c)) == need["hall-ws"]
    side = json.loads(next((proj / "plates/cands/lead-ms").glob("*.json")).read_text())
    assert side["refs"] == [picked.relative_to(proj.resolve()).as_posix()] and side["model"] == "codex/imagegen"
    assert ledger.spent_usd(proj) == 0.0


@posix_only
def test_codex_job_refs_are_the_projects_files_and_broken_ones_name_the_fix(cx, tmp_path, monkeypatch):
    proj = cx["proj"]
    anchored_jobs(proj)
    other = tmp_path / "elsewhere"
    H.write_png(other / "plates/cands/hero-cu/2.png", (9, 9, 9))
    monkeypatch.chdir(other)
    rc, out = crun(cx, "gen", "image", "--jobs", "--provider", "codex", "--only", "lead-ms", "--yes")
    assert rc == 0, out
    assert attached(execs(cx)[-1]) == [str((proj / "plates/cands/hero-cu/2.png").resolve())]
    (proj / "plates/cands/hero-cu/2.png").unlink()                       # the anchor image is gone from THIS project
    n = len(execs(cx))
    rc, out = crun(cx, "gen", "image", "--jobs", "--provider", "codex", "--yes")
    assert rc == 1 and "job lead-ms" in out["error"] and "plates book --anchor" in out["error"], out
    assert len(execs(cx)) == n, "refused before any image run, never the other folder's same-named image"


@posix_only
@pytest.mark.parametrize("ref,cand", [("hero-cu:2", 2), ("hero-cu", 1), ("hero-cu#2", 2), ("hero-cu~2", 2)])
def test_codex_single_image_resolves_plate_refs(cx, ref, cand):
    rc, out = crun(cx, "gen", "image", "same lead, new angle", "--plate", "lead-ms", "--provider", "codex", "--ref", ref)
    assert rc == 0, out
    assert attached(execs(cx)[-1]) == [str((cx["proj"] / f"plates/cands/hero-cu/{cand}.png").resolve())]
    side = json.loads((cx["proj"] / "plates/cands/lead-ms/1.json").read_text())
    assert side["refs"] == [f"plates/cands/hero-cu/{cand}.png"]


@posix_only
@pytest.mark.parametrize("ref", ["https://cdn.example.com/a.png", "data:image/png;base64,iVBORw0KGgo="])
def test_codex_refuses_links_before_any_run(cx, ref):
    rc, out = crun(cx, "gen", "image", "x", "--plate", "p1", "--provider", "codex", "--ref", ref)
    assert rc == 1 and "image files" in out["error"] and "slop -p" in out["error"] and "fetch" in out["error"], out
    assert not execs(cx)


@posix_only
def test_codex_background_job_keeps_plate_refs_and_makes_files_absolute(cx, monkeypatch, tmp_path):
    monkeypatch.delenv("SLOP_CODEX_IMAGE_FOREGROUND")
    from slop import job
    got = {}

    def fake_start(words, project=None, **kw):
        got.update(words=words)
        return {"job": {"id": "gen-image-abcd", "wait": "slop job wait gen-image-abcd --max 25"}, "existing": False}
    monkeypatch.setattr(job, "start", fake_start)
    elsewhere = tmp_path / "elsewhere"; elsewhere.mkdir(); monkeypatch.chdir(elsewhere)
    rc, out = crun(cx, "gen", "image", "x", "--plate", "lead-ms", "--provider", "codex", "--ref", "hero-cu:2",
                   "--ref", "plates/cands/hall/1.png")
    assert rc == 0, out
    w = got["words"]
    refs = [w[i + 1] for i, x in enumerate(w) if x == "--ref"]
    assert refs == ["hero-cu:2", str((cx["proj"] / "plates/cands/hall/1.png").resolve())]
    assert job.check_argv(w).provider == "codex"
    rc, out = crun(cx, "gen", "image", "x", "--plate", "lead-ms", "--provider", "codex", "--ref", "nobody:3")
    assert rc == 1 and "nobody" in out["error"], "a bad reference fails now, not inside the background job"


# ------------------------------------------------------------------------------------------- 2. URLs through the CLI
def test_gen_image_ref_urls_pass_the_cli_unchanged(tmp_path, monkeypatch):
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SLOP_PROJECTS", str(tmp_path / "projects"))
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-test-not-a-real-key")
    monkeypatch.delenv("SLOP_PROJECT", raising=False)
    H.write_cache(tmp_path / "home")
    proj = H.make_project(tmp_path / "projects", audio=False)
    s = H.FakeSession({("POST", "/images"): lambda m, u, b: H.FakeResp(200, {"data": [
        {"b64_json": H.b64(H.png_bytes((5, 5, 5))), "media_type": "image/png"}], "usage": {"cost": 0.004}})})
    import requests
    monkeypatch.setattr(requests, "Session", lambda: s)
    weird = "data:image/png;base64,AAAA//BBBB//CCCC=="
    rc, out = K.run("--project", str(proj), "gen", "image", "x", "--plate", "roof", "--ref", weird,
                    "--ref", "https://cdn.example.com/a.png?Signature=abc")
    assert rc == 0, out
    sent = [r["image_url"]["url"] for r in s.calls[0]["body"]["input_references"]]
    assert sent == [weird, "https://cdn.example.com/a.png?Signature=abc"], "'//' inside a data: URL survives"


# ------------------------------------------------------------------------------------------- 3. skills and docs
def test_skills_teach_the_shipped_anchor_flags():
    pl = read(SKILLS / "plates" / "SKILL.md")
    line = next(ln for ln in pl.splitlines() if "Identity anchor" in ln)
    for cmd in re.findall(r"`slop --json -p NAME ([^`]+)`", line):
        argv = ["--json", "-p", "demo", *shlex.split(cmd.replace("PLATE", "lead-cu").replace(" K", " 2"))]
        cli.build_parser().parse_args(util.hoist_global_flags(argv))
    assert "plates book --no-anchor" in line and "plates book --anchor PLATE" in line


def test_docs_match_the_book_and_the_anchor():
    api = read(DOCS / "51-plates-api.md")
    s25 = api[api.index("### 2.5"):api.index("## 3.")]
    assert "prompts-<batch>.md" in s25 and "gate prompts --approve" in s25, "a subset book is not the G5 book"
    s3 = api[api.index("## 3."):api.index("### 3.1")]
    assert "plates book --anchor" in s3 and "--no-anchor" in s3 and "--ref PLATE:K" in s3
    arch = read(DOCS / "ARCHITECTURE.md")
    rule4 = next(ln for ln in arch.splitlines() if ln.startswith("4. Lead identity"))
    assert "never face images as the identity reference" not in arch
    assert "approved" in arch[arch.index(rule4):arch.index("5. Generation inputs")]
    assert '"refs"' in arch and '"anchor"' in arch

"""Delivery steps on the 8-second demo project through the real CLI: progress while rendering, the chat copy
(`render encode --share`), the layer check (`render check --layers`), the chapter review sheet, the image cache, and
`render clean`. Marked slow (browser + ffmpeg; ≈ 1–2 min on 4 cores)."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "engine"
sys.path.insert(0, str(FIX))
pytest.importorskip("playwright.sync_api")
pytestmark = [pytest.mark.slow,
              pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="ffmpeg not installed")]


def slop(capsys, *args) -> dict:
    from slop.cli import main
    rc = main(["--json", *args])
    out = capsys.readouterr().out.strip().splitlines()[-1]
    d = json.loads(out)
    if rc != 0 and "could not start a browser" in str(d.get("error", "")):
        pytest.skip(d["error"])
    d["_rc"] = rc
    return d


@pytest.fixture(autouse=True)
def _pin_engine_hash(monkeypatch):
    """Other tracks edit engine/src while tests run; pin the engine part of the frame fingerprint (as test_engine_e2e)."""
    from slop.render import project as P
    monkeypatch.setattr(P, "engine_code_hash", lambda: "pinned-for-deliver")


@pytest.fixture(scope="module")
def demo(tmp_path_factory) -> Path:
    import make_demo
    d = tmp_path_factory.mktemp("deliver") / "demo-project"
    shutil.copytree(FIX / "demo-project", d)
    make_demo.write_audio(d / "audio" / "song.wav")
    return d


@pytest.fixture(scope="module")
def rendered(demo, tmp_path_factory):
    """Frames (with a progress file) and a verified master, once for the module."""
    from slop.cli import main
    import contextlib
    import io
    import os
    pf = tmp_path_factory.mktemp("prog") / "progress.json"
    os.environ["SLOP_PROGRESS_FILE"] = str(pf)
    try:
        from slop.render import project as P
        keep = P.engine_code_hash
        P.engine_code_hash = lambda: "pinned-for-deliver"
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc1 = main(["--json", "--project", str(demo), "render", "frames", "--workers", "2"])
            rc2 = main(["--json", "--project", str(demo), "render", "encode"])
        P.engine_code_hash = keep
    finally:
        os.environ.pop("SLOP_PROGRESS_FILE", None)
    outs = [json.loads(x) for x in buf.getvalue().strip().splitlines() if x.startswith("{")]
    if any("could not start a browser" in str(o.get("error", "")) for o in outs):
        pytest.skip("no browser")
    assert rc1 == 0 and rc2 == 0, outs
    return {"progress": json.loads(pf.read_text(encoding="utf-8")), "frames": outs[0], "encode": outs[1]}


def test_progress_file_after_frames(rendered):
    p = rendered["progress"]
    # the last command was the master encode (ffmpeg -progress): it ended complete, and only its end says "done"
    assert p["stage"] == "encode master" and p["state"] == "done" and p["done"] == p["total"] == 192
    assert p["command"] == "render encode" and p["step"] == "1/1"


def _made_from(demo) -> Path:
    return demo / "out" / "master.mp4.inputs.json"


def test_share_copy(demo, rendered, capsys):
    """Reviewer repro: a master encoded from an EARLIER render (stand-in plates) capped the share copy of the frames
    on disk at its own low bitrate. Such a master is neither the size cap nor the copy: two passes at the budget."""
    rec = _made_from(demo).read_text(encoding="utf-8")
    old = json.loads(rec)
    old["hash"] = "an-earlier-render"
    _made_from(demo).write_text(json.dumps(old), encoding="utf-8")
    try:
        r = slop(capsys, "--project", str(demo), "render", "encode", "--share", "--max-mib", "8")
    finally:
        _made_from(demo).write_text(rec, encoding="utf-8")
    assert r["_rc"] == 0 and r["ok"], r.get("text")
    assert not r["capped_at_master"] and not r["copied"] and not r["master_current"]
    assert "earlier render" in r["text"] and "not used as the share copy or as its size cap" in r["text"]
    from slop.render.encode import _video_kbps, share_bitrate
    assert r["kbps"] == share_bitrate(8.0, 8) > (_video_kbps(demo / "out" / "master.mp4") or 0)
    assert r["source"] == "frames" and Path(r["out"]) == demo / "out" / "share.mp4"
    v = r["verify"]
    assert v["tags"] == {"codec_name": "h264", "pix_fmt": "yuv420p", "color_space": "bt709", "color_primaries": "bt709",
                         "color_transfer": "iec61966-2-1", "color_range": "tv"}
    assert (v["width"], v["height"], v["frames"], v["audio"]) == (1920, 1080, 192, "aac")
    assert 0 < r["bytes"] <= 8 * 1048576 and r["passes"] == 2
    assert not list((demo / "render" / "scratch").glob("share-x264*"))          # pass logs removed


def test_share_after_new_plates_is_not_capped_by_the_old_master(demo, rendered, capsys, tmp_path):
    """Reviewer repro end to end: a master encoded from the stand-in plates, then busier plates and a re-render of the
    frames: the share copy must get its own budget, not the old master's bitrate."""
    import os
    from PIL import Image
    from slop.render.encode import share_bitrate
    d = tmp_path / "p" / "demo-project"
    shutil.copytree(demo, d)
    for f in ("grad-a.jpg", "grad-b.jpg", "grad-c.jpg"):          # noise: far more bits than the smooth gradients
        Image.frombytes("RGB", (1280, 720), os.urandom(1280 * 720 * 3)).save(d / "plates" / f, quality=95)
    fr = slop(capsys, "--project", str(d), "render", "frames", "--workers", "2")
    assert fr["ok"] and fr["stale_discarded"], fr.get("text")
    s = slop(capsys, "--project", str(d), "render", "encode", "--share", "--max-mib", "8")
    assert s["ok"] and s["source"] == "frames", s.get("text")
    assert not s["capped_at_master"] and not s["copied"] and s["kbps"] == share_bitrate(8.0, 8)
    assert "earlier render of the frames" in s["text"] and "slop render encode" in s["text"]


def test_share_copies_a_current_master_that_fits(demo, rendered, capsys, tmp_path):
    """The master made from these frames and this song already fits under --max-mib: a verified copy, no re-encode."""
    import os
    pf = tmp_path / "p.json"
    os.environ["SLOP_PROGRESS_FILE"] = str(pf)
    try:
        r = slop(capsys, "--project", str(demo), "render", "encode", "--share", "--max-mib", "8", "--out",
                 str(tmp_path / "share.mp4"))
    finally:
        os.environ.pop("SLOP_PROGRESS_FILE", None)
    assert r["_rc"] == 0 and r["ok"] and r["copied"] and r["passes"] == 0, r.get("text")
    assert r["bytes"] == (demo / "out" / "master.mp4").stat().st_size and "no re-encode" in r["text"]
    assert r["verify"]["frames"] == 192 and r["verify"]["tags"]["color_transfer"] == "iec61966-2-1"
    p = json.loads(pf.read_text(encoding="utf-8"))
    assert p["state"] == "done" and p["command"] == "render encode --share" and p["step"] == "2/2"


def test_share_from_master_when_frames_are_gone(demo, rendered, capsys, tmp_path):
    frames = demo / "render" / "frames"
    hold = tmp_path / "frames-held"
    shutil.move(str(frames), str(hold))
    try:
        r = slop(capsys, "--project", str(demo), "render", "encode", "--share", "--max-mib", "8",
                 "--out", str(tmp_path / "s.mp4"))
        assert r["ok"] and r["source"] == "master", r.get("text")
        assert r["verify"]["tags"]["color_transfer"] == "iec61966-2-1" and r["verify"]["frames"] == 192
    finally:
        shutil.move(str(hold), str(frames))


def test_share_flag_errors(demo, capsys):
    assert "between 8 and 200" in slop(capsys, "--project", str(demo), "render", "encode", "--share", "--max-mib", "250")["error"]
    assert "--max-mib goes with --share" in slop(capsys, "--project", str(demo), "render", "encode", "--max-mib", "100")["error"]
    assert "drop --review" in slop(capsys, "--project", str(demo), "render", "encode", "--share", "--review")["error"]


def test_layer_check(demo, capsys):
    r = slop(capsys, "--project", str(demo), "render", "check", "--layers", "--workers", "2")
    rep = json.loads((demo / "render" / "layers.json").read_text(encoding="utf-8"))
    # the 9:16 check writes its own report: the 16:9 one is not overwritten
    v = slop(capsys, "--project", str(demo), "render", "check", "--layers", "--vertical", "--workers", "2")
    assert Path(v["report"]).name == "layers-vertical.json" and "render/layers-vertical.json" in v["text"]
    assert json.loads(Path(v["report"]).read_text(encoding="utf-8"))["size"] == [1080, 1920]
    assert json.loads((demo / "render" / "layers.json").read_text(encoding="utf-8"))["size"] == [1920, 1080]
    assert rep["checked"] == len(rep["frames"]) >= 3 and rep["rule"] == 3
    by = {f["scene"]: f for f in rep["frames"]}
    # s001 and s002 carry plate + lyric + chrome (+ the lead mark): at least 3 ordered layers
    for sid in ("s001", "s002"):
        assert {"media", "lyric", "chrome"} <= set(by[sid]["layers"]) and by[sid]["count"] >= 3, by[sid]
    # s003 has no sung words at its mid-point; it still has the plate, the chrome and the lead's CV mark
    assert "lyric" not in by["s003"]["layers"] and "media" in by["s003"]["layers"]
    assert r["ok"] == (not rep["failing"])


def test_layer_check_fails_a_bare_shot(tmp_path, capsys):
    d = tmp_path / "demo-project"
    shutil.copytree(FIX / "demo-project", d)
    B = json.loads((d / "board" / "shots.json").read_text(encoding="utf-8"))
    s3 = B["shots"][2]
    s3.update(chrome="off", lead_on_screen=False, devices=[])
    (d / "board" / "shots.json").write_text(json.dumps(B), encoding="utf-8")
    r = slop(capsys, "--project", str(d), "render", "check", "--layers", "--workers", "1")
    assert r["_rc"] == 1 and not r["ok"]
    bad = {f["scene"]: f for f in r["layers"]["failing"]}
    assert "s003" in bad and bad["s003"]["count"] < 3 and "slop board device add s003" in bad["s003"]["fix"]
    assert "chrome is off" in bad["s003"]["fix"] and "FAIL" in r["text"]
    assert "--kind marks" in bad["s003"]["fix"] and "--line" not in bad["s003"]["fix"]     # s003 sings no line


def test_layer_check_bespoke_chapter_scenes(tmp_path, capsys):
    """A chapter scene drawn by the project's own code: below the rule and silent → UNVERIFIED (not a board fix);
    one that declares its layers with ENGINE.noteLayer is judged like any shot."""
    d = tmp_path / "demo-project"
    shutil.copytree(FIX / "demo-project", d)
    # <project>/engine/scenes.js is the project layer the page loads before the default renderer (index.html step 3)
    (d / "engine" / "scenes.js").write_text("""// bespoke chapter scenes: s002 declares what it draws, s003 does not
scene('s002', 3, 6, async (b, o, t) => { b.fillStyle = '#234'; b.fillRect(0, 0, ENGINE.W, ENGINE.H);
  ENGINE.noteLayer('graphic'); ENGINE.noteLayer('annotation'); ENGINE.noteLayer('micro'); ENGINE.noteLayer('nonsense'); });
scene('s003', 6, 8, async (b, o, t) => { b.fillStyle = '#123'; b.fillRect(0, 0, ENGINE.W, ENGINE.H); });
""", encoding="utf-8")
    r = slop(capsys, "--project", str(d), "render", "check", "--layers", "--workers", "1")
    rep = r["layers"]
    by = {f["scene"]: f for f in rep["frames"]}
    assert not by["s001"]["bespoke"] and by["s002"]["bespoke"] and by["s003"]["bespoke"], by
    assert by["s002"]["layers"] == ["graphic", "annotation", "micro"] and by["s002"]["count"] == 3     # declared: counted
    assert [u["scene"] for u in rep["unverified"]] == ["s003"] and not rep["failing"], rep["failing"]
    assert r["ok"] and "UNVERIFIED" in r["text"] and "ENGINE.noteLayer" in r["text"]


def test_info_reports_frame_layers_and_cache(demo, capsys):
    from slop.render import project as P
    from slop.render.browser import EnginePage
    from slop.render.frames import _sync_playwright
    spec = P.page_spec(demo)
    with _sync_playwright()() as p:
        with EnginePage(p, spec) as pg:
            pg.frame_jpeg(1.5)
            info = pg.info()
    fl = info.get("frameLayers")
    assert fl and fl["shot"] == "s001" and fl["count"] >= 3 and fl["ok"] and "media" in fl["layers"], fl
    assert info["layerRule"] == 3 and info["imageCache"]["budget"] == 320 * 1048576


def test_image_cache_byte_budget_keeps_pixels(demo, monkeypatch):
    """A 1 MiB budget evicts on every shot change and never changes a pixel."""
    from slop.render import project as P
    from slop.render.browser import EnginePage
    from slop.render.frames import _sync_playwright
    ts = [1.0, 4.5, 7.0, 1.0, 4.5]
    with _sync_playwright()() as p:
        with EnginePage(p, P.page_spec(demo)) as pg:
            big = [pg.frame_jpeg(t) for t in ts]
            c_big = pg.page.evaluate("() => Object.assign({}, ENGINE.cache)")
        monkeypatch.setenv("SLOP_CACHE_MIB", "1")
        with EnginePage(p, P.page_spec(demo)) as pg:
            small = [pg.frame_jpeg(t) for t in ts]
            c = pg.page.evaluate("() => Object.assign({}, ENGINE.cache)")
            gc = pg.page.evaluate("() => typeof window.gc")
    assert c["budget"] == 1048576 and c["evicted"] > 0 and c_big["evicted"] == 0
    assert gc == "function" and c["gcs"] > 0                    # --js-flags=--expose-gc: freed at once
    assert big == small                                         # pixels never depend on the cache


def test_decode_refusal_fallback(demo):
    """A loaded image whose decode() is refused still resolves; a file that does not load still rejects."""
    from slop.render import project as P
    from slop.render.browser import EnginePage
    from slop.render.frames import _sync_playwright
    plate = (demo / "plates" / "grad-a.jpg").resolve().as_uri()
    with _sync_playwright()() as p:
        with EnginePage(p, P.page_spec(demo)) as pg:
            r = pg.page.evaluate("""async (good) => {
              const out = {patched: !!HTMLImageElement.prototype.decode._slop};
              // Chromium refusing the async decode (its decode budget), as measured with 2912x1632 plates 6 at a time
              const refuse = ENGINE.robustDecode(function () {
                return Promise.reject(new DOMException('The source image cannot be decoded.', 'EncodingError')); });
              const im = new Image(); im.src = good; await new Promise(r => im.onload = r);
              out.loaded = await refuse.call(im).then(() => 'resolved', e => 'rejected');
              const late = new Image(); late.src = good;          // refused while still loading: waits for the load
              out.loading = await refuse.call(late).then(() => 'resolved', e => 'rejected');
              const bad = new Image(); bad.src = good.replace('grad-a.jpg', 'nope.jpg');
              out.bad = await refuse.call(bad).then(() => 'resolved', e => e.name);
              out.realBad = await (new Image()).decode().then(() => 'resolved', e => 'rejected');
              return out; }""", plate)
    assert r == {"patched": True, "loaded": "resolved", "loading": "resolved", "bad": "EncodingError", "realBad": "rejected"}


def test_chapter_review_sheet(demo, rendered, capsys):
    from PIL import Image
    r = slop(capsys, "--project", str(demo), "render", "sheet", "--chapter", "one", "--review")
    assert r["ok"], r.get("text")
    assert Path(r["sheet"]).name == "sheet-1-review.jpg" and r["chapter"]["name"] == "one" and r["review"]
    labels = " | ".join(r["labels"])
    for sid in ("s001", "s002", "s003"):
        for tag in ("first", "mid", "last"):
            assert f"{sid} {tag}" in labels
    assert "L00 first" in labels and "L01 last" in labels
    assert r["times"] == sorted(r["times"]) and len(set(r["times"])) == len(r["times"])
    w, h = Image.open(r["sheet"]).size
    assert w == 6 * 320
    bad = slop(capsys, "--project", str(demo), "render", "sheet", "--chapter", "nine")
    assert bad["_rc"] == 1 and "no chapter 'nine'" in bad["error"] and "one" in bad["error"]
    assert "--review needs --chapter" in slop(capsys, "--project", str(demo), "render", "sheet", "--review")["error"]


def test_clean(demo, rendered, capsys, tmp_path):
    d = tmp_path / "c" / "demo-project"
    shutil.copytree(demo, d)
    scratch = d / "render" / "scratch"
    (scratch / "scan" / "0").mkdir(parents=True, exist_ok=True)
    (scratch / "scan" / "0" / "sheet.jpg").write_bytes(b"0" * 1000)          # a workflow's live scratch: kept
    (scratch / "share-x264-0.log").write_bytes(b"0" * 1000)                  # a stopped share encode's pass log
    (d / "out" / "draft.mp4").write_bytes(b"0" * 10)
    dry = slop(capsys, "--project", str(d), "render", "clean", "--dry")
    assert dry["ok"] and dry["dry"] and (d / "render" / "frames").is_dir(), dry
    assert {x["path"] for x in dry["would_delete"]} >= {"render/frames", "render/scratch/share-x264-0.log", "out/draft.mp4"}
    assert not any(x["path"].startswith("render/scratch/scan") for x in dry["would_delete"])
    keep = slop(capsys, "--project", str(d), "render", "clean", "--keep-master")
    assert keep["ok"] and (d / "render" / "frames").is_dir() and not (scratch / "share-x264-0.log").exists()
    assert (scratch / "scan" / "0" / "sheet.jpg").is_file()
    assert (d / "out" / "master.mp4").is_file() and not (d / "out" / "draft.mp4").exists()
    full = slop(capsys, "--project", str(d), "render", "clean")
    assert full["ok"] and not (d / "render" / "frames").exists() and full["freed_bytes"] > 0
    assert (d / "out" / "master.mp4").is_file() and (d / "out" / "share.mp4").is_file()


def test_clean_refuses_without_a_verified_master(demo, rendered, capsys, tmp_path):
    d = tmp_path / "r" / "demo-project"
    shutil.copytree(demo, d)
    (d / "out" / "master.mp4").write_bytes(b"not a video")
    r = slop(capsys, "--project", str(d), "render", "clean")
    assert r["_rc"] == 1 and "nothing deleted" in r["error"] and (d / "render" / "frames").is_dir()
    shutil.copy2(demo / "out" / "master.mp4", d / "out" / "master.mp4")
    rec = json.loads((d / "render" / "frames" / ".inputs.json").read_text(encoding="utf-8"))
    rec["hash"] = "a-later-render"                              # the frames on disk are not the ones the master was made from
    (d / "render" / "frames" / ".inputs.json").write_text(json.dumps(rec), encoding="utf-8")
    r = slop(capsys, "--project", str(d), "render", "clean")
    assert r["_rc"] == 1 and "newer render than master.mp4" in r["error"] and (d / "render" / "frames").is_dir()


def test_master_keeps_the_last_frame_when_the_song_ends_inside_it(demo, rendered, capsys, tmp_path):
    """A song of 7.99 s at 24 fps ends inside frame 191: the audio is padded to that frame's end (apad); before,
    -shortest cut the picture to the audio and the master came out one frame short (seen on the full 306.4 s song)."""
    import subprocess
    song = demo / "audio" / "song.wav"
    keep = tmp_path / "song-8s.wav"
    shutil.copy2(song, keep)
    try:
        subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", str(keep), "-t", "7.99", str(song)], check=True)
        r = slop(capsys, "--project", str(demo), "render", "encode", "--out", str(tmp_path / "m.mp4"))
        assert r["ok"], r.get("text") or r.get("error")
        assert r["verify"]["frames"] == 192 and r["verify"]["audio"] == "aac"
        s = slop(capsys, "--project", str(demo), "render", "encode", "--share", "--out", str(tmp_path / "s.mp4"))
        assert s["ok"] and s["max_mib"] == 95 and s["verify"]["frames"] == 192, s.get("text") or s.get("error")
        # out/master.mp4 has these frames but the earlier song: not copied (the share takes the song now in audio/),
        # still the size cap (same pictures): the demo's CRF 16 master is far below 190 MiB's bitrate
        assert not s["copied"] and "another version of song.wav" in s["text"]
        assert s["capped_at_master"] and s["bytes"] <= 1.25 * (demo / "out" / "master.mp4").stat().st_size
    finally:
        shutil.copy2(keep, song)

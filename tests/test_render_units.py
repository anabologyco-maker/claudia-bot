"""Render-track units without a browser: the share bitrate, chapter review times, layer-check hints, worker defaults
under taskset / cgroup limits, and the CLI wiring of the new flags."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "engine"


@pytest.fixture()
def demo(tmp_path) -> Path:
    d = tmp_path / "demo-project"
    shutil.copytree(FIX / "demo-project", d)
    return d


def test_share_bitrate_fits_the_cap():
    from slop.render.encode import SHARE_AUDIO_KBPS, SHARE_MAX_KBPS, SHARE_OVERHEAD, share_bitrate
    from slop.config import SlopError
    k = share_bitrate(306.4, 190)                       # the 5:06 reference song under the default target
    assert 4700 < k < 5000
    total_bytes = (k + SHARE_AUDIO_KBPS) * 1000 / 8 * 306.4
    assert total_bytes <= 190 * 1048576 * (1 - SHARE_OVERHEAD) + 1
    assert share_bitrate(8.0, 190) == SHARE_MAX_KBPS     # short films stop at the useful maximum
    assert share_bitrate(600, 190) < share_bitrate(300, 190)
    with pytest.raises(SlopError):
        share_bitrate(0, 190)


def test_chapter_review_times(demo):
    from slop.render.chapter import chapter_times, find_chapter
    assert find_chapter(demo, "one")["index"] == 1 and find_chapter(demo, "1")["name"] == "one"
    lyr = [{"line": 0, "kind": "lyric", "tokens": [{"txt": "Hello", "t0": 0.5, "t1": 0.9}, {"txt": "world.", "t0": 1.4, "t1": 1.5}]},
           {"line": 9, "kind": "adlib", "tokens": [{"txt": "ah", "t0": 2.0, "t1": 2.2}]}]
    ch, picks = chapter_times(demo, "one", True, 24.0, lyr=lyr)
    labels = {lab for _, lab in picks}
    ts = [t for t, _ in picks]
    assert ts == sorted(ts) and len(ts) == len(set(ts))
    assert all(abs(t * 24 - round(t * 24)) < 1e-6 for t in ts)                    # on frame boundaries
    assert {"s001 first", "s002 mid", "s003 last"} <= {x for lab in labels for x in lab.split(" · ")}
    # the gate time of a word: t0 + clamp((t1 - t0) / 2, .03, .12) — "Hello" 0.5 → 0.62 → frame 15 = 0.625
    assert any("L00 first 'Hello'" in lab and abs(t - 15 / 24) < 1e-6 for t, lab in picks)
    assert any("L00 last 'world.'" in lab for lab in labels) and not any("L09" in lab for lab in labels)
    _, mids = chapter_times(demo, "one", False, 24.0)
    assert [lab for _, lab in mids] == ["s001", "s002", "s003"] and mids[0][0] == pytest.approx(1.5)


def test_chapter_errors(demo):
    from slop.config import SlopError
    from slop.render.chapter import find_chapter
    with pytest.raises(SlopError, match="no chapter 'x'"):
        find_chapter(demo, "x")
    B = json.loads((demo / "board" / "shots.json").read_text(encoding="utf-8"))
    B["chapters"] = []
    (demo / "board" / "shots.json").write_text(json.dumps(B), encoding="utf-8")
    with pytest.raises(SlopError, match="has no chapters"):
        find_chapter(demo, "1")


def test_layer_fix_hints():
    from slop.render.layers import fix_hint
    assert "hole in the storyboard" in fix_hint("gap03", ["chrome"], None)
    assert "hole in the storyboard" in fix_hint("fill0", ["chrome"], None)
    assert "slop render info" in fix_hint("s004", ["chrome", "lyric"], {"id": "s004"})
    # an intro shot with no sung line: a device that needs no line (no "--line N" placeholder)
    h = fix_hint("s005", ["media"], {"id": "s005", "lines": []})
    assert "slop board device add s005 --kind marks --param style=ruler" in h and "--line" not in h
    assert "chrome is off" in h and "no board command sets it" in h and h.endswith("run this again")
    # a shot with a line: a callout on THAT line (a real number, not N)
    h = fix_hint("s007", ["media", "chrome"], {"id": "s007", "lines": [12, 13]})
    assert "slop board device add s007 --kind callout --line 12" in h and "chrome is off" not in h
    # annotation already there: the hint adds a layer the shot lacks (micro), never a second annotation
    h = fix_hint("s006", ["media", "annotation"], {"id": "s006", "lines": [3]})
    assert "--kind marks" in h and "callout" not in h


def test_layer_report_names_by_layout(demo):
    from slop.render.frames import _suffix
    assert _suffix(demo, 1920, 1080) == "" and _suffix(demo, 1080, 1920) == "-vertical"     # layers-vertical.json


def _fake_cgroup(root, meminfo_gib: float, mx, current: int, stat: dict | None, rel: str = "user.slice/run.scope",
                 parent_max=None) -> tuple:
    proc, cg = root / "proc", root / "cgroup"
    (proc / "self").mkdir(parents=True)
    (proc / "meminfo").write_text(f"MemTotal: 32000000 kB\nMemAvailable: {int(meminfo_gib * 1024 * 1024)} kB\n")
    (proc / "self" / "cgroup").write_text(f"0::/{rel}\n")
    d = cg / rel
    d.mkdir(parents=True)
    (d / "memory.max").write_text(f"{mx}\n")
    (d / "memory.current").write_text(f"{current}\n")
    if stat is not None:
        (d / "memory.stat").write_text("".join(f"{k} {v}\n" for k, v in stat.items()))
    if parent_max is not None:
        (d.parent / "memory.max").write_text(f"{parent_max}\n")
        (d.parent / "memory.current").write_text(f"{current}\n")
    return proc, cg


def test_avail_gib_does_not_count_page_cache(tmp_path):
    """Reviewer repro: MemoryMax=8G, a 6 GB file written (page cache 5.86 GiB, anon 0) → max − current said 1.96 GiB
    and 1 worker; the page cache is reclaimable, so ~8 GiB is left and 4 workers run."""
    from slop.render import frames as F
    G = 1024 ** 3
    proc, cg = _fake_cgroup(tmp_path / "a", 30.0, 8 * G, int(6.04 * G),
                            {"anon": 0, "file": int(5.86 * G), "active_file": int(1.2 * G),
                             "inactive_file": int(4.66 * G), "shmem": 0})
    gib = F._avail_gib(proc, cg)
    assert gib == pytest.approx(8 - (6.04 - 5.86), abs=.01)
    # no limit: MemAvailable; a limit with no memory.stat: max − current (the old, conservative rule)
    proc, cg = _fake_cgroup(tmp_path / "b", 12.5, "max", 3 * G, None)
    assert F._avail_gib(proc, cg) == pytest.approx(12.5, abs=.01)
    proc, cg = _fake_cgroup(tmp_path / "c", 30.0, 8 * G, 5 * G, None)
    assert F._avail_gib(proc, cg) == pytest.approx(3.0, abs=.01)
    # a tighter limit on a parent cgroup wins
    proc, cg = _fake_cgroup(tmp_path / "d", 30.0, "max", 1 * G, {"active_file": 0, "inactive_file": 0},
                            parent_max=3 * G)
    assert F._avail_gib(proc, cg) == pytest.approx(2.0, abs=.01)
    # chromium's shared memory (shmem: swap-backed, on the anon lists) is NOT reclaimable
    proc, cg = _fake_cgroup(tmp_path / "e", 30.0, 8 * G, 6 * G, {"anon": 2 * G, "shmem": 3 * G, "file": 4 * G,
                                                                  "active_file": G // 2, "inactive_file": G // 2})
    assert F._avail_gib(proc, cg) == pytest.approx(3.0, abs=.01)


def test_default_workers_under_a_cache_filled_cgroup(tmp_path, monkeypatch):
    from slop.render import frames as F
    G = 1024 ** 3
    proc, cg = _fake_cgroup(tmp_path, 30.0, 8 * G, int(6.04 * G),
                            {"active_file": int(1.2 * G), "inactive_file": int(4.66 * G)})
    real = F._avail_gib
    monkeypatch.setattr(F, "_cpus", lambda: 8)
    monkeypatch.setattr(F, "_avail_gib", lambda: real(proc, cg))
    assert F.default_workers() == 1                 # (7.8 GiB left - 3 GiB for Grok's browser) / 3.5 GiB a worker
    monkeypatch.setattr(F, "_avail_gib", lambda: 20.0)
    assert F.default_workers() == 4                 # (20 - 3) / 3.5 = 4, and cpus // 2 = 4


def test_share_uses_the_master_only_when_it_is_current(demo, monkeypatch):
    """Reviewer repro: a master from an earlier render (2,372 kbit/s, stand-in plates) capped the share copy of busier
    frames at an eighth of its budget. Only a master made from the frames on disk caps or replaces the share copy."""
    from slop.render import encode as E
    (demo / "out").mkdir(exist_ok=True)
    m = demo / "out" / "master.mp4"
    m.write_bytes(b"0" * 1000)
    song = demo / "audio" / "song.wav"
    song.parent.mkdir(parents=True, exist_ok=True)
    song.write_bytes(b"RIFF-a-song")
    src = {"kind": "frames", "hash": "frames-now"}
    E.write_made_from(m, demo / "render" / "frames", {"hash": "frames-before"}, 10, audio=E.audio_sig(song))
    ms = E.master_state(demo, False, src)
    assert not ms["picture"] and "earlier render" in ms["why"]
    E.write_made_from(m, demo / "render" / "frames", {"hash": "frames-now"}, 10, audio=E.audio_sig(song))
    ms = E.master_state(demo, False, src)
    assert ms["picture"] and ms["audio"] and ms["why"] == ""
    song.write_bytes(b"RIFF-another-mix")                      # same frames, a new mix: not a copy, still a size cap
    ms = E.master_state(demo, False, src)
    assert ms["picture"] and not ms["audio"] and "another version of song.wav" in ms["why"]
    E.made_from_path(m).unlink()                               # a master with no record: never trusted
    assert not E.master_state(demo, False, src)["picture"]
    assert E.master_state(demo, False, {"kind": "master"})["picture"]          # the share's own source



def test_default_workers_follow_affinity_and_cgroup(monkeypatch):
    from slop.render import frames as F
    monkeypatch.setattr(F, "_cpus", lambda: 8)
    monkeypatch.setattr(F, "_avail_gib", lambda: 13.0)          # (13 - 3 for Grok's browser) / 3.5 = 2
    assert F.default_workers() == 2
    monkeypatch.setattr(F, "_avail_gib", lambda: 20.0)
    assert F.default_workers() == 4
    monkeypatch.setattr(F, "_avail_gib", lambda: 3.5)          # a tight cgroup: still one worker
    assert F.default_workers() == 1
    monkeypatch.setattr(F, "_cpus", lambda: 2)
    monkeypatch.setattr(F, "_avail_gib", lambda: None)
    assert F.default_workers() == 1 and F.default_workers(10) == 1


def test_cache_budget_env(monkeypatch, demo):
    from slop.config import SlopError
    from slop.render import project as P
    monkeypatch.delenv("SLOP_CACHE_MIB", raising=False)
    assert '"cacheMiB"' not in P.page_spec(demo)["init"]
    monkeypatch.setenv("SLOP_CACHE_MIB", "64")
    assert '"cacheMiB": 64.0' in P.page_spec(demo)["init"]
    monkeypatch.setenv("SLOP_CACHE_MIB", "lots")
    with pytest.raises(SlopError, match="SLOP_CACHE_MIB"):
        P.page_spec(demo)


def test_cache_mib_is_not_a_pixel_input(demo, monkeypatch):
    from slop.render import project as P
    monkeypatch.delenv("SLOP_CACHE_MIB", raising=False)
    spec = P.page_spec(demo)
    a = P.inputs_fingerprint(demo, spec)["hash"]
    pj = json.loads((demo / "project.json").read_text(encoding="utf-8"))
    pj["cache_mib"] = 128
    (demo / "project.json").write_text(json.dumps(pj), encoding="utf-8")
    spec = P.page_spec(demo)
    assert '"cache_mib": 128' in spec["init"]                     # the page gets it
    assert P.inputs_fingerprint(demo, spec)["hash"] == a           # frames stay fresh


def test_cli_flags_parse():
    from slop.cli import build_parser
    ap = build_parser()
    a = ap.parse_args(["render", "encode", "--share", "--max-mib", "150", "--vertical"])
    assert a.share and a.max_mib == 150 and a.vertical
    a = ap.parse_args(["render", "check", "--layers", "--workers", "2"])
    assert a.layers and a.workers == 2
    a = ap.parse_args(["render", "sheet", "--chapter", "C3", "--review"])
    assert a.chapter == "C3" and a.review and a.cols is None and a.w is None
    a = ap.parse_args(["render", "clean", "--keep-master", "--dry"])
    assert a.keep_master and a.dry


@pytest.mark.skipif(sys.platform.startswith("win"), reason="POSIX signals")
def test_ffmpeg_killed_by_a_signal_runs_once_more(tmp_path, monkeypatch):
    from slop import progress
    from slop.render.encode import run_ffmpeg
    monkeypatch.setenv("SLOP_PROGRESS_FILE", str(tmp_path / "p.json"))
    monkeypatch.setattr(progress, "_state", {"stage": None, "t0": 0.0, "last": 0.0, "done0": 0})
    count = tmp_path / "count"
    fake = tmp_path / "fakeff"
    fake.write_text("#!/bin/sh\nn=$(cat %s 2>/dev/null || echo 0); n=$((n+1)); echo $n > %s\n"
                    "if [ $n -le $KILLS ]; then echo 'frame=3'; kill -9 $$; fi\necho 'frame=5'\nexit 0\n" % (count, count))
    fake.chmod(0o755)
    monkeypatch.setenv("KILLS", "1")
    r = run_ffmpeg([str(fake), "-y", "out.mp4"], 5, "encode test")
    assert r.returncode == 0 and count.read_text().strip() == "2"
    assert json.loads((tmp_path / "p.json").read_text())["state"] == "done"
    count.unlink()
    monkeypatch.setenv("KILLS", "2")
    r = run_ffmpeg([str(fake), "-y", "out.mp4"], 5, "encode test")
    assert r.returncode == -9 and "killed by SIGKILL twice" in r.stderr and "run the same command again" in r.stderr
    assert json.loads((tmp_path / "p.json").read_text())["state"] == "stopped"


def test_layer_judge_bespoke_scenes(demo):
    from slop.render.layers import judge
    shots = {"s001": {"id": "s001", "lines": [0]}}
    rows = [{"scene": "s001", "t0": 0, "t1": 3, "t": 1.5, "count": 2, "layers": ["media", "chrome"], "noted": []},
            {"scene": "ch2a", "t0": 3, "t1": 6, "t": 4.5, "count": 1, "layers": ["chrome"], "noted": [], "bespoke": True},
            {"scene": "ch2b", "t0": 6, "t1": 8, "t": 7.0, "count": 2, "layers": ["graphic", "chrome"], "noted": ["graphic"],
             "bespoke": True},
            {"scene": "ch2c", "t0": 8, "t1": 9, "t": 8.5, "count": 3, "layers": ["media", "graphic", "micro"],
             "noted": ["graphic", "micro"], "bespoke": True}]
    failing, allowed, unverified = judge(rows, shots, demo)
    assert [r["scene"] for r in unverified] == ["ch2a"] and "ENGINE.noteLayer" in unverified[0]["note"]
    assert "slop render stills --times 4.5" in unverified[0]["note"]
    fail = {r["scene"]: r for r in failing}
    assert set(fail) == {"s001", "ch2b"} and not allowed
    assert "--kind callout --line 0" in fail["s001"]["fix"]
    assert "chapter code (it declares graphic)" in fail["ch2b"]["fix"] and "board device" not in fail["ch2b"]["fix"]


def test_clean_waits_for_a_running_job(demo):
    """`render clean` deleting frames under a running render/encode/scan broke it: refuse while another job runs."""
    import os
    import time
    from slop import job
    from slop.config import SlopError
    from slop.render.clean import clean, running_jobs
    if job.proc_start(os.getpid()) is None:
        pytest.skip("no /proc process start times here")
    jd = demo / "jobs"
    jd.mkdir()
    me = os.getpid()
    rec = {"id": "j0001-render-frames", "seq": 1, "state": "running", "argv": ["render", "frames"],
           "cmd": "slop render frames", "project": str(demo), "pid": me, "pid_start": job.proc_start(me),
           "supervisor_pid": me, "supervisor_start": job.proc_start(me), "started_ts": time.time()}
    (jd / "j0001-render-frames.json").write_text(json.dumps(rec), encoding="utf-8")
    with pytest.raises(SlopError) as e:
        clean(demo)
    assert "still running" in str(e.value) and "j0001-render-frames" in str(e.value) and "job wait" in str(e.value)
    # the clean job itself is not a reason to wait
    rec.update(argv=["render", "clean"], cmd="slop render clean")
    (jd / "j0001-render-frames.json").write_text(json.dumps(rec), encoding="utf-8")
    assert running_jobs(demo) == []
    with pytest.raises(SlopError, match="nothing deleted: out/master.mp4 does not exist"):
        clean(demo)

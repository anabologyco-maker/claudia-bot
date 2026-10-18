"""`slop doctor` checks: is this machine ready to make a video?

Each check returns {"name", "status": "ok"|"warn"|"fail"|"skip", "detail", "fix", "data"}. "fail" = a stage of the
active profile cannot run; "warn" = degraded or optional. Nothing here spends money: the only network calls are the
FREE OpenRouter GET /api/v1/key and /api/v1/credits (and, with --net, plain GETs to public hosts).

Profiles (bin/setup.sh --minimal | --full; the installed one is recorded as SLOP_PROFILE in $SLOP_HOME/env.sh):
  minimal  numpy pillow requests soundfile scipy playwright==1.60.0   (Quick tier: API stills/clips, 2.5D, render)
  full     + CPU torch/torchaudio/torchvision 2.11, demucs 4.1.0, transformers 5.17, librosa 1.0.0,
           opencv-python-headless, safetensors, accelerate, wordfreq    (local stems + forced alignment on CPU)
           + the raw CMU Pronouncing Dictionary in $SLOP_HOME/cache/cmudict (scansion / lyric lint)

Model/weight licences used by the full profile are recorded by the modules that download them (audio: htdemucs
code MIT / weights untagged - flagged; wav2vec2 Apache-2.0; board/plates: Depth-Anything-V2-Small Apache-2.0 only).
Lyric-lint data: cmudict.dict data BSD-2-Clause (the raw file; the `cmudict` PyPI wrapper is GPL-3.0 and is NOT
installed); wordfreq code Apache-2.0, its word-frequency data CC-BY-SA 4.0 (used locally, never redistributed).

Heavy imports run in a child process (`--quick` skips them) so a broken wheel cannot crash doctor.
"""
from __future__ import annotations

import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .config import on_box, projects_root, slop_home, toolkit_root
from . import util

# (import name, pip name, expected version prefix or None)
MINIMAL_DEPS = [("numpy", "numpy", None), ("PIL", "pillow", None), ("requests", "requests", None),
                ("soundfile", "soundfile", None), ("scipy", "scipy", None), ("playwright", "playwright", "1.60.")]
FULL_DEPS = [("torch", "torch", "2.11."), ("torchaudio", "torchaudio", "2.11."), ("torchvision", "torchvision", "0.26."),
             ("demucs", "demucs", "4.1.0"), ("transformers", "transformers", "5.17."), ("librosa", "librosa", "1.0.0"),
             ("cv2", "opencv-python-headless", None), ("safetensors", "safetensors", None),
             ("accelerate", "accelerate", None)]

NET_HOSTS = [  # (url, what needs it, required-for)
    ("https://pypi.org/simple/", "pip packages", "setup"),
    ("https://files.pythonhosted.org/", "pip package files", "setup"),
    ("https://github.com/", "uv, python, cloudflared downloads; code", "setup"),
    ("https://release-assets.githubusercontent.com/", "GitHub release files", "setup"),
    ("https://api.github.com/", "release checksums for the cloudflared download", "optional"),
    ("https://download.pytorch.org/whl/cpu/", "CPU torch wheels (--full)", "full"),
    ("https://huggingface.co/", "model weights (--full: wav2vec2, htdemucs, depth)", "full"),
    ("https://raw.githubusercontent.com/", "CMU Pronouncing Dictionary for lyric lint (--full; else on first use)",
     "full"),
    ("https://cdn.playwright.dev/", "Playwright chromium download", "render"),
    ("https://openrouter.ai/api/v1/models", "API images/clips/song (OpenRouter)", "api"),
    ("https://api.are.na/v2/", "Are.na taste import (optional, ARENA_TOKEN)", "optional"),
    ("https://fonts.gstatic.com/", "web fonts (optional)", "optional"),
]
LYRIC_TOOLS = [("wordfreq", "wordfreq", None)]  # optional extras of the full profile (rare-word check in lyric lint)
CMUDICT_MIN_BYTES = 1_000_000  # the raw cmudict.dict is ~3.6 MB


def _check(name: str, state: str, detail: str, fix: str | None = None, **data) -> dict:
    return {"name": name, "status": state, "detail": detail, "fix": fix, "data": data}


def active_profile(explicit: str | None = None) -> str:
    p = (explicit or os.environ.get("SLOP_PROFILE") or "").strip().lower()
    if p in ("minimal", "full"):
        return p
    marker = slop_home() / "profile"
    try:
        p = marker.read_text(encoding="utf-8").strip().lower()
    except OSError:
        p = ""
    return p if p in ("minimal", "full") else "minimal"


# ---------------------------------------------------------------- checks
def check_python() -> dict:
    v = sys.version_info
    ver = f"{v.major}.{v.minor}.{v.micro}"
    venv = slop_home() / "venv"
    in_venv = Path(sys.prefix).resolve() == venv.resolve() if venv.exists() else False
    where = f"{sys.executable}" + (" (claudia venv)" if in_venv else "")
    if (v.major, v.minor) < (3, 11):
        return _check("python", "fail", f"Python {ver} at {where}; claudia needs 3.11+ (3.13 recommended)",
                      "run: bash bin/setup.sh (installs Python 3.13 with uv under $SLOP_HOME), then use "
                      "$SLOP_HOME/bin/slop (or: sh bin/slop)",
                      version=ver, executable=sys.executable, in_venv=in_venv)
    if not in_venv:
        return _check("python", "warn", f"Python {ver} at {where} - not the claudia venv ({venv})",
                      "run: bash bin/setup.sh, then call slop through $SLOP_HOME/bin/slop (or: sh bin/slop)",
                      version=ver, executable=sys.executable, in_venv=False)
    return _check("python", "ok", f"Python {ver} at {where}", version=ver, executable=sys.executable, in_venv=True)


_PROBE = r"""
import importlib, json, sys
out = {}
for mod, pip in json.loads(sys.argv[1]):
    try:
        m = importlib.import_module(mod)
        v = getattr(m, "__version__", None)
        if v is None:
            try:
                from importlib.metadata import version
                v = version(pip)
            except Exception:
                v = "?"
        extra = {}
        if mod == "torch":
            extra["cuda"] = getattr(getattr(m, "version", None), "cuda", None)
        out[mod] = {"ok": True, "version": str(v), **extra}
    except Exception as e:
        out[mod] = {"ok": False, "error": f"{type(e).__name__}: {e}"[:300]}
print(json.dumps(out))
"""


def import_probe(deps: list[tuple[str, str, str | None]], timeout: float = 300) -> dict:
    """Import each module in a child interpreter; {mod: {ok, version|error}}."""
    pairs = [[m, p] for m, p, _ in deps]
    rc, out, err = util.run([sys.executable, "-c", _PROBE, json.dumps(pairs)], timeout=timeout)
    try:
        return json.loads(out.strip().splitlines()[-1])
    except (ValueError, IndexError):
        msg = (err or out or f"exit {rc}").strip()[-300:]
        return {m: {"ok": False, "error": f"import probe failed: {msg}"} for m, _, _ in deps}


def spec_probe(deps: list[tuple[str, str, str | None]]) -> dict:
    """Fast: is the package installed (no import)."""
    import importlib.util
    from importlib.metadata import PackageNotFoundError, version
    res = {}
    for mod, pip, _ in deps:
        try:
            found = importlib.util.find_spec(mod) is not None
        except (ImportError, ValueError):
            found = False
        if not found:
            res[mod] = {"ok": False, "error": "not installed"}
            continue
        try:
            res[mod] = {"ok": True, "version": version(pip)}
        except PackageNotFoundError:
            res[mod] = {"ok": True, "version": "?"}
    return res


def check_deps(profile: str, quick: bool = False) -> list[dict]:
    checks = []
    groups = [("deps:minimal", MINIMAL_DEPS, True), ("deps:full", FULL_DEPS, profile == "full")]
    probe_all = MINIMAL_DEPS + FULL_DEPS
    res = spec_probe(probe_all) if quick else import_probe(probe_all)
    for name, deps, required in groups:
        missing, mism, have = [], [], {}
        for mod, pip, want in deps:
            r = res.get(mod, {"ok": False, "error": "not probed"})
            if not r.get("ok"):
                missing.append(f"{pip} ({r.get('error', 'missing')})")
                continue
            have[pip] = r.get("version")
            if want and not str(r.get("version", "")).startswith(want):
                mism.append(f"{pip} {r.get('version')} (calibrated on {want.rstrip('.')}*)")
        torch_cuda = res.get("torch", {}).get("cuda")
        if missing:
            status = "fail" if required else ("skip" if len(missing) == len(deps) else "warn")
            prof = name.split(":")[1]
            if status == "skip":
                detail = f"{prof} profile not installed (only needed for local stems/alignment on CPU)"
            else:
                detail = f"missing/broken: {'; '.join(missing)}"
            checks.append(_check(name, status, detail, f"run: bash bin/setup.sh --{prof}", installed=have,
                                 missing=missing))
        elif mism:
            checks.append(_check(name, "warn", "installed, but versions differ from the tested pins: " + "; ".join(mism),
                                 f"re-run: bash bin/setup.sh --{name.split(':')[1]} (restores the pins)",
                                 installed=have))
        else:
            detail = ", ".join(f"{k} {v}" for k, v in have.items())
            if name == "deps:full" and torch_cuda:
                detail += f" (torch is a CUDA {torch_cuda} build; CPU build is smaller - fine)"
            checks.append(_check(name, "ok", detail, installed=have))
    return checks


def check_ffmpeg() -> dict:
    ff = util.find_tool("ffmpeg")
    if not ff:
        return _check("ffmpeg", "fail", "ffmpeg not found on PATH",
                      "the Grok Bot computer ships ffmpeg; elsewhere install ffmpeg >= 6 with libx264 (e.g. a static "
                      "build) and put it on PATH")
    rc, out, err = util.run([ff, "-hide_banner", "-version"], timeout=30)
    m = re.search(r"ffmpeg version (\S+)", out)
    ver = m.group(1) if m else "?"
    rc2, enc, _ = util.run([ff, "-hide_banner", "-encoders"], timeout=30)
    has_x264 = bool(re.search(r"\blibx264\b", enc))
    probe = util.find_tool("ffprobe")
    if not has_x264:
        return _check("ffmpeg", "fail", f"ffmpeg {ver} has no libx264 encoder (masters are H.264 CRF 16)",
                      "use an ffmpeg build with libx264 (the box image and most static builds have it)",
                      version=ver, path=ff, libx264=False, ffprobe=bool(probe))
    if not probe:
        return _check("ffmpeg", "fail", f"ffmpeg {ver} found but ffprobe is missing (masters are verified with it)",
                      "install the matching ffprobe next to ffmpeg", version=ver, path=ff, libx264=True, ffprobe=False)
    return _check("ffmpeg", "ok", f"ffmpeg {ver} with libx264; ffprobe present", version=ver, path=ff,
                  libx264=True, ffprobe=True)


_LAUNCH = r"""
import json, sys
from playwright.sync_api import sync_playwright
kw = json.loads(sys.argv[1])
with sync_playwright() as p:
    b = p.chromium.launch(**kw)
    pg = b.new_page()
    pg.set_content("<canvas id=c width=8 height=8></canvas>")
    ok = pg.evaluate("() => !!document.getElementById('c').getContext('2d')")
    v = b.version
    b.close()
print(json.dumps({"ok": bool(ok), "version": v}))
"""


def try_browser(channel: str, timeout: float = 120) -> dict:
    kw = util.browser_launch_kwargs(channel)
    rc, out, err = util.run([sys.executable, "-c", _LAUNCH, json.dumps(kw)], timeout=timeout, env=util.playwright_env())
    try:
        r = json.loads(out.strip().splitlines()[-1])
        if r.get("ok"):
            return {"ok": True, "channel": channel, "version": r.get("version")}
    except (ValueError, IndexError):
        pass
    return {"ok": False, "channel": channel, "error": launch_error(err + "\n" + out, rc)}


_LAUNCH_ERRORS = [  # (regex on the launch log, short explanation)
    (r"error while loading shared libraries: (\S+?):", "system library {0} is missing (Chromium's OS dependencies)"),
    (r"Executable doesn't exist at (\S+)", "browser not downloaded ({0}); run: bash bin/setup.sh"),
    (r"Host system is missing dependencies", "host is missing Chromium's OS dependencies"),
    (r"Chromium distribution 'chrome' is not found", "google-chrome is not installed"),
    (r"(No module named [^\n]+)", "{0}"),
]


def launch_error(log: str, rc: int = 1) -> str:
    """The one meaningful line of a failed Playwright launch (its log ends with useless cleanup lines)."""
    for rx, msg in _LAUNCH_ERRORS:
        m = re.search(rx, log)
        if m:
            return msg.format(*m.groups())
    if rc == 124:
        return "launch timed out"
    lines = [x.strip() for x in log.strip().splitlines() if x.strip() and "cleanup" not in x and "<" not in x[:12]]
    return (" | ".join(lines[-2:]) or f"exit {rc}")[:300]


def check_chromium() -> dict:
    try:
        import importlib.util
        if importlib.util.find_spec("playwright") is None:
            return _check("chromium", "fail", "playwright (python) is not installed, so the renderer cannot start",
                          "run: bash bin/setup.sh --minimal")
    except (ImportError, ValueError):
        return _check("chromium", "fail", "playwright import check failed", "run: bash bin/setup.sh --minimal")
    pref = util.browser_channel()
    order = [pref] + [c for c in ("chromium", "chrome") if c != pref]
    tried = []
    for ch in order:
        r = try_browser(ch)
        tried.append(r)
        if r["ok"]:
            if ch == pref:
                return _check("chromium", "ok", f"headless {ch} launches (version {r.get('version')})",
                              channel=ch, version=r.get("version"))
            return _check("chromium", "warn",
                          f"configured channel {pref!r} failed; {ch!r} works (version {r.get('version')})",
                          f"export SLOP_BROWSER_CHANNEL={ch} (re-running bash bin/setup.sh records it in env.sh)",
                          channel=ch, version=r.get("version"), tried=tried)
    fix = "run: bash bin/setup.sh (installs Playwright chromium, or falls back to the system google-chrome)"
    if any("missing" in (t.get("error") or "") for t in tried):
        fix = ("Chromium's OS libraries are missing. On the Grok Bot computer use the preinstalled google-chrome "
               "(re-run bash bin/setup.sh; it records SLOP_BROWSER_CHANNEL=chrome). Elsewhere install them with root: "
               "python -m playwright install-deps chromium")
    return _check("chromium", "fail", "no headless browser launches: " + "; ".join(
        f"{t['channel']}: {t.get('error')}" for t in tried), fix, tried=tried)


CLOUDFLARED_NEED = ("REQUIRED for OpenRouter sung clips (they take the song window only as an HTTPS URL, served by "
                    "the quick tunnel), for Higgsfield media_import_url of the plate and window, and for the phone "
                    "tap app")


def check_cloudflared() -> dict:
    cf = util.find_tool("cloudflared")
    setup = toolkit_root() / "bin" / "setup.sh"
    fix = (f"install it: bash {setup} --cloudflared (downloads the checksum-verified binary from "
           "GitHub into $SLOP_HOME/bin; the full setup does it too). Without it the only fallback is uploading each "
           "window with the Higgsfield connector (media_upload, PUT with 'If-None-Match: *', then slop gen host CLIP "
           "--url URL)")
    if not cf:
        return _check("cloudflared", "warn", f"cloudflared not installed - {CLOUDFLARED_NEED}", fix, required_for=
                      ["openrouter sung clips", "higgsfield media_import_url", "tap app"])
    rc, out, err = util.run([cf, "--version"], timeout=20)
    m = re.search(r"version (\S+)", out + err)
    if rc != 0:
        return _check("cloudflared", "warn", f"{cf} does not run: {(err or out).strip()[:200]} - {CLOUDFLARED_NEED}",
                      f"delete it and re-run: bash {setup} --cloudflared", path=cf)
    return _check("cloudflared", "ok", f"cloudflared {m.group(1) if m else '?'} at {cf} (the tunnel for sung-clip audio "
                  "and the tap app; test it: slop gen tunnel start)", path=cf, version=m.group(1) if m else None)


def check_openrouter(offline: bool = False) -> dict:
    if not util.env_present("OPENROUTER_API_KEY"):
        return _check("openrouter", "warn", "OPENROUTER_API_KEY is not set: API images, clips and songs are off",
                      "ask the bot to request OPENROUTER_API_KEY with its secure secret card (never paste keys in chat)",
                      present=False)
    if offline:
        return _check("openrouter", "skip", "OPENROUTER_API_KEY is set (not checked: --offline)", present=True)
    info = util.openrouter_key_info()
    data = {k: v for k, v in info.items() if k not in ("error",)}
    if not info.get("ok"):
        status = "warn" if info.get("status") == 0 else "fail"
        return _check("openrouter", status, info.get("error") or "key check failed",
                      util.OPENROUTER_REPLACE if status == "fail" else
                      "allow openrouter.ai on the network, then re-run slop doctor", **data)
    lim, rem, used = info.get("limit"), info.get("limit_remaining"), info.get("usage")
    if lim is None:
        detail = f"key valid; used {util.money(used)}; no key spend limit set"
        fix = "set a key spend limit in the OpenRouter dashboard (above the project budget)"
        status = "ok"
    else:
        detail = f"key valid; used {util.money(used)} of key limit {util.money(lim)} ({util.money(rem)} left)"
        fix = None
        status = "ok"
        if isinstance(rem, (int, float)) and rem < 2:
            status, fix = "warn", "the key is nearly at its spend limit: raise it in the OpenRouter dashboard"
    eb = info.get("effective_budget") if isinstance(info.get("effective_budget"), dict) else {}
    if isinstance(eb.get("remaining_usd"), (int, float)) and eb["remaining_usd"] < 2:
        detail += (f"; its {eb.get('reset_interval') or ''} budget has {util.money(eb['remaining_usd'])} left"
                   + (f" (resets {str(eb['resets_at'])[:10]})" if eb.get("resets_at") else ""))
        status = "warn"
        fix = fix or "raise the budget in the OpenRouter dashboard (or wait for it to reset)"
    if info.get("is_free_tier"):
        detail += "; FREE tier (paid models will fail until credits are added)"
        status = "warn"
    exp = util.parse_iso(info.get("expires_at"))
    if exp is not None:
        from datetime import datetime, timezone
        days = (exp - datetime.now(tz=timezone.utc)).total_seconds() / 86400
        if days < 14:
            detail += f"; the key EXPIRES {exp.strftime('%Y-%m-%d')} ({max(days, 0):.0f} days)"
            status = "warn"
            fix = util.OPENROUTER_REPLACE + (f"; {fix}" if fix else "")
    return _check("openrouter", status, detail, fix, **data)


def cmudict_cache() -> Path:
    """Where bin/setup.sh --full (or the audio module on first use) keeps the raw CMU dictionary."""
    return slop_home() / "cache" / "cmudict" / "cmudict.dict"


def check_lyric_tools(profile: str, quick: bool = False) -> dict:
    """Optional lyric-lint data: wordfreq (rare-word check) and the CMU dictionary (pronunciations)."""
    res = spec_probe(LYRIC_TOOLS) if quick else import_probe(LYRIC_TOOLS, timeout=120)
    wf = res.get("wordfreq", {}).get("ok", False)
    cmu = cmudict_cache()
    try:
        cmu_ok = cmu.is_file() and cmu.stat().st_size >= CMUDICT_MIN_BYTES
    except OSError:
        cmu_ok = False
    have = [x for x, ok in (("wordfreq", wf), ("CMU dictionary", cmu_ok)) if ok]
    miss = [x for x, ok in (("wordfreq (no rare-word check)", wf), ("CMU dictionary (pronunciations guessed from "
                                                                   "spelling until it downloads)", cmu_ok)) if not ok]
    data = {"wordfreq": wf, "cmudict": str(cmu) if cmu_ok else None}
    if not miss:
        return _check("lyrics:lint-data", "ok", "wordfreq and the CMU dictionary present", **data)
    if profile != "full":
        return _check("lyrics:lint-data", "skip", "minimal profile: " + "; ".join(miss) +
                      " (optional; slop lyrics lint downloads the dictionary on first use)", **data)
    return _check("lyrics:lint-data", "warn", "missing: " + "; ".join(miss) + (f" (present: {', '.join(have)})"
                                                                              if have else ""),
                  "re-run: bash bin/setup.sh --full (installs wordfreq, downloads cmudict.dict from "
                  "raw.githubusercontent.com)", **data)


def check_disk() -> list[dict]:
    out = []
    seen = set()
    for label, path in (("disk:slop_home", slop_home()), ("disk:projects", projects_root())):
        d = util.disk_info(path)
        key = d.get("measured_at")
        if key in seen:
            continue
        seen.add(key)
        free = d.get("free")
        if free is None:
            out.append(_check(label, "warn", f"cannot measure free space at {path}: {d.get('error')}", **d))
            continue
        gb = free / 1024 ** 3
        if gb < 5:
            st, fix = "fail", "free space: delete old render/frames folders (keep out/*.mp4) or caches under $SLOP_HOME/cache"
        elif gb < 20:
            st, fix = "warn", "a full install + one render cut needs ~20 GB; delete render/frames after encoding"
        else:
            st, fix = "ok", None
        out.append(_check(label, st, f"{util.human_bytes(free)} free at {d['measured_at']}", fix, **d))
    return out


def check_ram() -> dict:
    m = util.mem_info()
    tot, av = m.get("total"), m.get("available")
    if tot is None:
        return _check("ram", "warn", "could not read total RAM", **m)
    det = f"{util.human_bytes(tot)} total" + (f", {util.human_bytes(av)} available" if av else "")
    if tot < 7.5 * 1024 ** 3:
        return _check("ram", "warn", det + " - under 8 GB: render with --workers 2 and run one heavy step at a time",
                      **m)
    w = max(1, int(max(0.0, av / 1024 ** 3 - 3.0) // 3.5)) if av else None   # = render.frames.memory_workers()
    return _check("ram", "ok", det + (f" (render workers now: {w}, about 3.5 GB each)" if w else ""), **m)


def check_cpu() -> dict:
    c = util.cpu_info()
    det = f"{c.get('usable')} usable CPUs" + (f" ({c.get('model')})" if c.get("model") else "")
    if (c.get("usable") or 0) < 4:
        return _check("cpu", "warn", det + " - fewer than 4: stems/alignment and renders will be slow", **c)
    return _check("cpu", "ok", det, **c)


LF_FILES = ("bin/setup.sh", "bin/slop")  # + every *.sh / *.mjs under bin/ and runner/


def check_line_endings(root: Path | None = None) -> dict:
    """The shell scripts must have LF line endings (a Windows checkout or editor can turn them into CRLF; then
    `bash bin/setup.sh` and the slop shim fail with "$'\\r': command not found")."""
    root = Path(root) if root else toolkit_root()
    files = [root / f for f in LF_FILES]
    for d, pat in (("bin", "*.sh"), ("runner", "*.mjs")):
        files += sorted((root / d).glob(pat)) if (root / d).is_dir() else []
    bad, seen = [], set()
    for f in files:
        if f in seen or not f.is_file():
            continue
        seen.add(f)
        try:
            if b"\r\n" in f.read_bytes():
                bad.append(f.relative_to(root).as_posix())
        except OSError:
            continue
    if bad:
        return _check("line-endings", "fail", "Windows (CRLF) line endings in " + ", ".join(bad) +
                      " - they fail on Linux", "run in the toolkit folder: sed -i 's/\\r$//' " + " ".join(bad),
                      crlf=bad)
    return _check("line-endings", "ok", f"LF in the {len(seen)} shell/runner scripts", crlf=[])


def check_paths() -> dict:
    home, proj = slop_home(), projects_root()
    env_sh = home / "env.sh"
    data = {"slop_home": str(home), "projects": str(proj), "toolkit": str(toolkit_root()), "on_box": on_box(),
            "env_sh": env_sh.is_file(), "hf_home": os.environ.get("HF_HOME")}
    if not env_sh.is_file():
        return _check("paths", "warn", f"SLOP_HOME={home} has no env.sh (setup has not run here)",
                      "run: bash bin/setup.sh", **data)
    return _check("paths", "ok", f"SLOP_HOME={home}; projects in {proj}" + (" (Grok Bot computer)" if on_box() else ""),
                  **data)


def check_optional_secrets() -> dict:
    names = ["HIGGSFIELD_API_KEY", "ARENA_TOKEN"]
    present = {n: util.env_present(n) for n in names}
    det = ", ".join(f"{n} {'set' if v else 'not set'}" for n, v in present.items())
    return _check("secrets:optional", "ok", det + " (optional; Higgsfield normally runs through the bot's connector)",
                  **present)


def check_net(timeout: float = 8) -> list[dict]:
    def probe(item):
        url, what, need = item
        ok, status, err = util.http_reachable(url, timeout=timeout)
        return url, what, need, ok, status, err
    with ThreadPoolExecutor(max_workers=8) as ex:
        res = list(ex.map(probe, NET_HOSTS))
    out = []
    for url, what, need, ok, status, err in res:
        host = url.split("/")[2]
        if ok:
            out.append(_check(f"net:{host}", "ok", f"reachable (HTTP {status}) - {what}", url=url, status=status))
        else:
            st = "warn" if need in ("optional", "full", "render") else "fail"
            fix = {"full": "use --minimal (API alignment/stems) or ask the team admin to allow this host",
                   "render": "setup falls back to the system google-chrome (SLOP_BROWSER_CHANNEL=chrome)",
                   "api": "ask the team admin to allow openrouter.ai, or use the Higgsfield connector",
                   "setup": "setup cannot download packages: allow this host or install from a local mirror",
                   "optional": None}.get(need)
            out.append(_check(f"net:{host}", st, f"unreachable ({err}) - {what}", fix, url=url))
    return out


def run_doctor(profile: str | None = None, quick: bool = False, offline: bool = False, net: bool = False) -> dict:
    prof = active_profile(profile)
    checks: list[dict] = [check_python(), check_paths(), check_line_endings()]
    checks += check_deps(prof, quick=quick)
    checks.append(check_lyric_tools(prof, quick=quick))
    checks.append(check_ffmpeg())
    checks.append(check_chromium() if not quick else _check("chromium", "skip", "not launched (--quick)"))
    checks.append(check_cloudflared())
    checks.append(check_openrouter(offline=offline))
    checks.append(check_optional_secrets())
    checks += check_disk()
    checks.append(check_ram())
    checks.append(check_cpu())
    if net and not offline:
        checks += check_net()
    fails = [c for c in checks if c["status"] == "fail"]
    warns = [c for c in checks if c["status"] == "warn"]
    mark = {"ok": "ok  ", "warn": "WARN", "fail": "FAIL", "skip": "skip"}
    lines = [f"slop doctor - profile {prof}" + (" (quick)" if quick else "")]
    w = min(max(len(c["name"]) for c in checks), 40)
    for c in checks:
        lines.append(f"  {mark[c['status']]}  {c['name']:<{w}}  {c['detail']}")
        if c.get("fix") and c["status"] in ("fail", "warn"):
            lines.append(f"        -> {c['fix']}")
    if fails:
        lines.append(f"{len(fails)} failing, {len(warns)} warnings. Fix the FAIL lines first, then re-run: slop doctor")
    elif warns:
        lines.append(f"ready ({len(warns)} warnings)")
    else:
        lines.append("ready")
    out = {"ok": not fails, "profile": prof, "checks": checks,
           "summary": {"fail": len(fails), "warn": len(warns), "ok": sum(c["status"] == "ok" for c in checks)},
           "text": "\n".join(lines)}
    if fails:
        out["error"] = "doctor found problems: " + ", ".join(c["name"] for c in fails)
    return out

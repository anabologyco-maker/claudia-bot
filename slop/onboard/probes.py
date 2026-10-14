"""The checks behind the onboarding items. Each returns a plain dict and never raises for an expected failure.

Nothing here spends money. Network: only the FREE OpenRouter GET /api/v1/key (skipped with offline=True). The agents
and GPU checks run the other modules' OWN CLI (`slop --json agents status`, `slop --json gpu status`) in a child
process with a time limit, found with importlib without importing them here, so a missing or broken module can never
break `slop onboard`. Their JSON is read shape-tolerantly (normalize_agents / normalize_gpu): only installed, logged
in, version and plan (agents) and mode, health, GPU name/VRAM, profiles (GPU) are kept - never an account address,
a token or the raw output. Tests monkeypatch the functions of this module.
"""
from __future__ import annotations

import argparse
import contextlib
import importlib
import importlib.util
import io
import json
import os
import re
import shlex
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from .. import util
from ..config import on_box, projects_root, slop_home, toolkit_root
from .state import AGENT_ENGINES, EMAIL_RE, PROFILE_RE, SECRET_RE, TIERS

# A child CLI that does not answer in time is reported as an error item; both run in parallel, so `slop onboard`
# stays well under the bot shell's 25 s per-call limit (SLOP_WAIT_MAX: a box that allows less gets less).
PROBE_TIMEOUT_S = 15.0
SHORT_RE = re.compile(r"[^A-Za-z0-9 ._+()-]")


def probe_timeout() -> float:
    try:
        wait_max = float(os.environ.get("SLOP_WAIT_MAX") or 25)
    except ValueError:
        wait_max = 25.0
    return max(5.0, min(PROBE_TIMEOUT_S, wait_max - 10))


def scrub(text, n: int = 200) -> str:
    """Free text from another tool, safe to show and store: no key/token shapes, no mail addresses, one line, short."""
    s = " ".join(str(text or "").split())
    s = SECRET_RE.sub("[hidden]", s)
    s = EMAIL_RE.sub("[account]", s)
    return s[:n]


def _short(v, n: int = 40) -> str | None:
    if v is None or isinstance(v, (dict, list, bool)):
        return None
    s = SHORT_RE.sub("", str(v)).strip()[:n]
    return s or None


# ---------------------------------------------------------------- toolkit / doctor / keys
def toolkit() -> dict:
    """Installed by bin/setup.sh (env.sh + bin/slop in $SLOP_HOME)? version, profile, PATH."""
    from .. import __version__
    from ..doctor import active_profile
    home = slop_home()
    env_sh, shim = home / "env.sh", home / "bin" / "slop"
    rc_hits = []
    for f in (Path.home() / ".bashrc", Path.home() / ".profile"):
        try:
            t = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if str(env_sh) in t or "claudia/env.sh" in t:
            rc_hits.append(f.name)
    return {"version": __version__, "profile": active_profile(), "profile_marker": (home / "profile").is_file(),
            "installed": env_sh.is_file() and shim.is_file(), "env_sh": str(env_sh), "shim": str(shim),
            "has_env_sh": env_sh.is_file(), "has_shim": shim.is_file(), "slop_home": str(home),
            "toolkit": str(toolkit_root()), "on_path": bool(shutil.which("slop")), "shell_rc": rc_hits,
            "on_box": on_box()}


SETUP_CALL_RE = re.compile(r"setup\.sh\b[^&|;)\n]*")


def setup_running() -> list[dict]:
    """bin/setup.sh installs running now, from shell command lines (Linux /proc; elsewhere []). full = a --full
    install is running or queued in the same shell (`setup.sh --minimal && setup.sh --full`)."""
    out: list[dict] = []
    proc = Path("/proc")
    if not proc.is_dir():
        return out
    try:
        pids = [p for p in proc.iterdir() if p.name.isdigit()]
    except OSError:
        return out
    for p in pids:
        try:
            words = [a.decode("utf-8", "replace") for a in (p / "cmdline").read_bytes().split(b"\0") if a]
        except OSError:
            continue
        hit = setup_call(words)
        if hit:
            out.append({"pid": int(p.name), **hit})
    return out


def setup_call(words: list[str]) -> dict | None:
    """{full: bool} when this command line (argv words) is a shell running bin/setup.sh to install; else None.
    `setup.sh --check` only reads, so it does not count."""
    if not words or Path(words[0]).name not in ("bash", "sh", "dash"):
        return None
    calls = [c for c in SETUP_CALL_RE.findall(" ".join(words)) if "--check" not in c]
    return {"full": any("--full" in c for c in calls)} if calls else None


def doctor() -> dict:
    """`slop doctor --quick --offline` reduced to its failures (the OpenRouter key is its own item here)."""
    try:
        from ..doctor import run_doctor
        r = run_doctor(quick=True, offline=True)
    except Exception as e:  # a broken doctor must not break onboarding
        return {"ok": False, "error": scrub(f"{type(e).__name__}: {e}")}
    checks = [c for c in (r.get("checks") or []) if c.get("name") not in ("openrouter", "secrets:optional")]
    fails = [{"name": c.get("name"), "detail": scrub(c.get("detail")), "fix": scrub(c.get("fix"), 300) or None}
             for c in checks if c.get("status") == "fail"]
    warns = [c.get("name") for c in checks if c.get("status") == "warn"]
    full = next((c for c in checks if c.get("name") == "deps:full"), None)
    return {"ok": True, "profile": r.get("profile"), "fails": fails, "warns": warns,
            "passed": sum(c.get("status") == "ok" for c in checks), "deps_full": full.get("status") if full else None}


def openrouter(offline: bool = False) -> dict:
    """OPENROUTER_API_KEY present? valid (FREE GET /api/v1/key)? limit, usage, expiry. Never the key or its label."""
    if not util.env_present("OPENROUTER_API_KEY"):
        return {"present": False, "checked": False, "valid": False}
    if offline:
        return {"present": True, "checked": False, "valid": None}
    info = util.openrouter_key_info()
    ok = bool(info.get("ok"))
    out = {"present": True, "checked": True, "valid": ok, "status": info.get("status"),
           "error": None if ok else scrub(info.get("error"), 300)}
    for k in ("limit", "limit_remaining", "usage", "expires_at", "is_free_tier", "limit_reset"):
        if k in info:
            out[k] = info.get(k)
    exp = util.parse_iso(info.get("expires_at"))
    if exp is not None:
        out["days_left"] = round((exp - datetime.now(tz=timezone.utc)).total_seconds() / 86400, 1)
    return out


def env_names() -> dict:
    """Presence of the optional secrets, by NAME only."""
    return {n: util.env_present(n) for n in ("ARENA_TOKEN", "HIGGSFIELD_API_KEY", "HEDRA_API_KEY", "GEMINI_API_KEY",
                                              "CLAUDE_CODE_OAUTH_TOKEN")}


# ---------------------------------------------------------------- other modules' CLIs
def _spec(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:  # a parent package that fails to import counts as absent
        return False


def module_for(family: str) -> str | None:
    """The module that registers `slop FAMILY` with the router: listed in cli.modules() (cli.MODULES, or the subset
    $SLOP_MODULES names) and present. None when the `slop` command cannot run it here, even if the package exists
    (see package_present). Found with importlib's finder: the module itself is not imported here."""
    try:
        from .. import cli
        listed = [m for m in cli.modules() if m == f"slop.{family}" or m.startswith(f"slop.{family}.")]
    except Exception:
        listed = []
    for m in listed:
        if _spec(m):
            return m
    return None


def package_present(family: str) -> bool:
    """slop/FAMILY/cli.py exists (it may not be registered with the router yet)."""
    return _spec(f"slop.{family}.cli")


def run_cli(module: str, words: list[str], timeout: float | None = None) -> dict:
    """`python -m slop --json WORDS` with only MODULE loaded, in a child process. -> {ok, data, error, rc,
    unregistered}: unregistered = the module does not provide that command (yet)."""
    root = str(toolkit_root())
    env = dict(os.environ)
    env["SLOP_MODULES"] = module
    env["PYTHONPATH"] = root + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env.pop("SLOP_PROGRESS_FILE", None)
    label = "slop " + " ".join(words)
    timeout = probe_timeout() if timeout is None else timeout
    rc, out, err = util.run([sys.executable, "-m", "slop", "--json", *words], timeout=timeout, env=env, cwd=root)
    data = None
    for line in reversed(out.strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                data = json.loads(line)
                break
            except ValueError:
                continue
    if rc == 124:
        return {"ok": False, "data": data if isinstance(data, dict) else None, "rc": rc,
                "error": f"`{label}` did not answer within {timeout:g} s"}
    if not isinstance(data, dict):
        tail = [x.strip() for x in (err or out).strip().splitlines() if x.strip()]
        return {"ok": False, "data": None, "rc": rc,
                "error": f"`{label}` printed no JSON (exit {rc}): {scrub(tail[-1] if tail else 'no output')}"}
    msg = str(data.get("error") or "")
    if rc != 0 and "invalid choice" in msg and repr(words[0]) in msg:
        return {"ok": False, "data": None, "rc": rc, "unregistered": True,
                "error": f"this toolkit version has no `{label}`"}
    ok = bool(data.get("ok", rc == 0)) and rc == 0
    return {"ok": ok, "data": data, "rc": rc, "error": None if ok else scrub(msg or f"exit {rc}", 300)}


_PARSERS: dict[str, argparse.ArgumentParser | None] = {}     # module name -> its parser (None: failed to load)
PLACEHOLDER_RE = re.compile(r"^[A-Z][A-Z_]+$")              # JOB, NAME, PROFILE ... (never runs as printed)


def command_parses(cmd: str | None) -> bool:
    """True when `cmd` (a `slop FAMILY ...` line another module suggested) parses with that module's own parser, so
    the checklist never passes on a step that cannot run. Imports only that one CLI module (argparse only)."""
    try:
        words = shlex.split(cmd or "")
    except ValueError:
        return False
    if len(words) < 3 or words[0] != "slop" or any(PLACEHOLDER_RE.match(w) for w in words):
        return False
    args = util.hoist_global_flags(words[1:])
    i = 0
    while i < len(args) and args[i].startswith("-"):           # --json, --project X, -p X, --project=X
        i += 2 if args[i] in util.GLOBAL_FLAGS_WITH_VALUE else 1
    if i >= len(args):
        return False
    mod = module_for(args[i])
    if not mod:
        return False
    if mod not in _PARSERS:
        ap = None
        try:
            ap = argparse.ArgumentParser(prog="slop", add_help=False)
            ap.add_argument("--json", action="store_true")
            ap.add_argument("--project", "-p")
            importlib.import_module(mod).register(ap.add_subparsers(dest="cmd"))
        except Exception:
            ap = None
        _PARSERS[mod] = ap
    ap = _PARSERS[mod]
    if ap is None:
        return False
    try:
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            ap.parse_args(args)
    except (SystemExit, Exception):
        return False
    return True


# ---------------------------------------------------------------- agents
LOGIN_KEYS = ("logged_in", "loggedIn", "signed_in", "signedIn", "authenticated", "authed", "auth_ok", "login_ok")
PLAN_KEYS = ("plan", "plan_type", "planType", "subscription", "subscription_type", "subscriptionType", "tier")
INSTALLED_KEYS = ("installed", "present", "found")
NESTED = ("auth", "login", "account", "session")
TRUE_WORDS = {"logged_in", "loggedin", "signed_in", "signedin", "authenticated", "ok", "yes", "true", "active",
              "ready", "valid"}
FALSE_WORDS = {"logged_out", "loggedout", "signed_out", "not_logged_in", "no", "false", "none", "expired", "missing",
               "unauthenticated", "invalid", "needs_login", "login_required"}


def _word_bool(s: str) -> bool | None:
    w = s.strip().lower().replace("-", "_").replace(" ", "_")
    return True if w in TRUE_WORDS else False if w in FALSE_WORDS else None


def _as_bool(v) -> bool | None:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        return _word_bool(v)
    return None


def _login(v: dict, depth: int = 0) -> bool | None:
    for k in LOGIN_KEYS:
        if v.get(k) is not None:
            b = _as_bool(v[k])
            if b is not None:
                return b
    if depth > 1:
        return None
    for nk in NESTED:
        n = v.get(nk)
        if isinstance(n, dict):
            b = _login(n, depth + 1)
            if b is None:
                stt = n.get("state") or n.get("status")
                b = _word_bool(stt) if isinstance(stt, str) else None
            if b is not None:
                return b
        elif n is not None and not isinstance(n, list):
            b = _as_bool(n)
            if b is not None:
                return b
    for k in ("login_state", "auth_state", "auth_status", "login_status"):
        if isinstance(v.get(k), str):
            b = _word_bool(v[k])
            if b is not None:
                return b
    return None


def _plan(v: dict, depth: int = 0):
    for k in PLAN_KEYS:
        p = v.get(k)
        if isinstance(p, dict):
            p = p.get("name") or p.get("type") or p.get("id")
        s = _short(p, 30)
        if s:
            return s
    if depth > 1:
        return None
    for nk in NESTED:
        if isinstance(v.get(nk), dict):
            s = _plan(v[nk], depth + 1)
            if s:
                return s
    return None


def engine_key(name) -> str | None:
    n = str(name or "").strip().lower()
    for pre, eng in (("claude", "claude"), ("codex", "codex"), ("chatgpt", "codex"), ("openai", "codex"),
                     ("muse", "muse"), ("gemini", "gemini")):
        if n.startswith(pre):
            return eng
    return None


VERSION_RE = re.compile(r"\d+(?:\.\d+)+(?:[-+][0-9A-Za-z.]+)?")
AGENTS_CMD_RE = re.compile(r"slop agents [a-z]+ [a-z]+(?: --[a-z-]+)*")   # their own `next` (no placeholders)


def normalize_agents(data) -> dict[str, dict]:
    """{engine: {installed, logged_in, version, plan, error, detail, next, login_pending}} from `slop agents status
    --json` (slop.agents: {"agents": [{"engine", "installed", "version", "logged_in", "plan", "next", ...}]}), read
    shape-tolerantly:
    {"engines": {name: {...}}} | {"engines": [{"engine": name, ...}]} | {"agents": ...} | {name: {...}} at top level.
    logged_in is True / False / None (unknown)."""
    if not isinstance(data, dict):
        return {}
    src = None
    for key in ("engines", "agents", "status", "items", "results"):
        if isinstance(data.get(key), (dict, list)):
            src = data[key]
            break
    if src is None:
        src = {k: v for k, v in data.items() if engine_key(k) and isinstance(v, dict)}
    rows: list[tuple[str, dict]] = []
    if isinstance(src, dict):
        rows = [(k, v) for k, v in src.items() if isinstance(v, dict)]
    elif isinstance(src, list):
        rows = [(v.get("engine") or v.get("name") or v.get("id") or "", v) for v in src if isinstance(v, dict)]
    out: dict[str, dict] = {}
    for name, v in rows:
        eng = engine_key(name)
        if eng not in AGENT_ENGINES or eng in out:
            continue
        inst = None
        for k in INSTALLED_KEYS:
            if v.get(k) is not None:
                inst = _as_bool(v[k])
                break
        version = _short(v.get("version"))
        m = VERSION_RE.search(version or "")
        version = m.group(0) if m else version                 # "codex-cli 0.155.1" -> "0.155.1"
        if inst is None:
            inst = bool(version or v.get("path") or v.get("bin"))
        err, det = v.get("error"), v.get("detail")
        nxt = v.get("next")
        out[eng] = {"installed": bool(inst), "logged_in": _login(v), "version": version, "plan": _plan(v),
                    "error": scrub(err) if isinstance(err, str) and err.strip() else None,
                    "detail": scrub(det) if isinstance(det, str) and det.strip() else None,
                    "next": nxt.strip() if isinstance(nxt, str) and AGENTS_CMD_RE.fullmatch(nxt.strip()) else None,
                    "login_pending": bool(v.get("login_pending"))}
    return out


def agents(timeout: float | None = None) -> dict:
    """`slop agents status` (slop.agents) -> {available, module, ok, engines, error}. unregistered = the package is
    in this toolkit but the `slop` command does not load it (cli.MODULES / $SLOP_MODULES)."""
    mod = module_for("agents")
    if not mod:
        return {"available": False, "module": None, "engines": {}, "unregistered": package_present("agents")}
    r = run_cli(mod, ["agents", "status"], timeout)
    if r.get("unregistered"):
        return {"available": False, "module": mod, "engines": {}, "error": r.get("error")}
    engines = normalize_agents(r.get("data"))
    for row in engines.values():
        if row.get("next") and not command_parses(row["next"]):
            row["next"] = None
    return {"available": True, "module": mod, "ok": bool(r.get("ok")) or bool(engines), "engines": engines,
            "error": None if engines else (r.get("error") or "no engines in its output")}


# ---------------------------------------------------------------- gpu
HEALTH_KEYS = ("healthy", "worker_alive", "alive", "online", "worker_online", "connected", "fresh")
GPU_CMD_RE = re.compile(r"`(slop gpu [^`]+)`")
GOOD_WORDS = {"ok", "healthy", "online", "alive", "idle", "busy", "running", "ready", "connected"}
BAD_WORDS = {"offline", "dead", "stale", "stopped", "down", "unreachable", "lost", "error", "failed", "disconnected"}


def _first_str(*vals) -> str | None:
    for v in vals:
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _vram_gb(g: dict) -> float | None:
    for k in ("vram_gb", "vram_gib", "memory_gb", "mem_gb", "total_gb"):
        if isinstance(g.get(k), (int, float)):
            return round(float(g[k]), 1)
    for k in ("vram_mib", "vram_mb", "memory_total_mib", "memory_mib", "memory_mb", "memory_total", "vram",
              "total_mib"):
        v = g.get(k)
        if isinstance(v, (int, float)):
            return round(float(v) / 1024, 1)
        if isinstance(v, str):
            m = re.match(r"\s*([\d.]+)\s*(gib|gb|mib|mb)?", v, re.I)
            if m:
                x = float(m.group(1))
                unit = (m.group(2) or "mib").lower()
                return round(x if unit in ("gib", "gb") else x / 1024, 1)
    return None


def _gpus(d: dict) -> list[dict]:
    cand = []
    for holder in (d, d.get("worker") if isinstance(d.get("worker"), dict) else {}):
        for k in ("gpus", "gpu", "devices", "device"):
            v = holder.get(k)
            if isinstance(v, list):
                cand += v
            elif isinstance(v, (dict, str)):
                cand.append(v)
        if cand:
            break
    out = []
    for g in cand:
        if isinstance(g, str):
            out.append({"name": _short(g, 60), "vram_gb": None})
        elif isinstance(g, dict):
            name = _short(g.get("name") or g.get("model") or g.get("product"), 60)
            if name or _vram_gb(g):
                out.append({"name": name, "vram_gb": _vram_gb(g)})
    return out[:4]


def _ready(p: dict) -> bool:
    for k in ("ready", "installed"):
        if p.get(k) is not None:
            return bool(_as_bool(p[k]))
    return True


def _profiles(d: dict) -> list[str]:
    v = d.get("profiles")
    if v is None and isinstance(d.get("worker"), dict):
        v = d["worker"].get("profiles")
    names: list[str] = []
    if isinstance(v, list):
        for p in v:
            if isinstance(p, str):
                names.append(p)
            elif isinstance(p, dict) and _ready(p):
                n = p.get("name") or p.get("id")
                if n:
                    names.append(str(n))
    elif isinstance(v, dict):
        for k, p in v.items():
            if (_ready(p) if isinstance(p, dict) else _as_bool(p)):
                names.append(str(k))
    return [s for s in (_short(n, 30) for n in names) if s][:12]


def normalize_gpu(d) -> dict:
    """{mode: none|direct|paired, healthy: bool|None, gpus: [{name, vram_gb}], profiles: [ready names], last_seen,
    error, why, hint_cmd} from `slop gpu status --json`, whatever its shape (slop.gpu's health record: {mode, why,
    next, worker: {gpus: [{name, total_mib}], profiles: {name: {ready}}, fresh, age_s}}). hint_cmd = the first
    `slop gpu ...` command its `next` names."""
    if not isinstance(d, dict):
        return {"mode": "none", "healthy": None, "gpus": [], "profiles": []}
    top = d
    for k in ("health", "status", "gpu_status"):          # a status that nests the health record
        if isinstance(d.get(k), dict):
            d = {**d[k], **{x: y for x, y in top.items() if x not in (k, "ok", "text") and y is not None}}
            break
    pairing = d.get("pairing") if isinstance(d.get("pairing"), dict) else {}
    worker = d.get("worker") if isinstance(d.get("worker"), dict) else {}
    raw = (_first_str(d.get("mode"), d.get("connection"), d.get("link"), pairing.get("mode"), worker.get("mode"))
           or "").lower()
    if raw in ("paired", "pair", "tunnel", "worker", "remote"):
        mode = "paired"
    elif raw in ("direct", "local", "local-exec", "local_exec", "machine"):
        mode = "direct"
    elif raw in ("none", "off", "no", "unpaired", "cpu"):
        mode = "none"
    elif _as_bool(d.get("paired")) or (pairing and _as_bool(pairing.get("active")) is not False):
        mode = "paired"
    elif _as_bool(d.get("direct")):
        mode = "direct"
    else:
        mode = "none"
    healthy = None
    for holder in (d, worker, pairing):
        for k in HEALTH_KEYS:
            if holder.get(k) is not None:
                healthy = _as_bool(holder[k])
                break
        if healthy is None:
            s = _first_str(holder.get("state"), holder.get("status"), holder.get("health"))
            if s:
                w = s.lower()
                healthy = True if w in GOOD_WORDS else False if w in BAD_WORDS else None
        if healthy is not None:
            break
    last = _first_str(d.get("last_seen"), worker.get("last_seen"), d.get("heartbeat"), worker.get("heartbeat"),
                      pairing.get("last_seen"))
    if last is None and isinstance(worker.get("age_s"), (int, float)):
        last = f"{worker['age_s']:.0f} s ago"
    err = d.get("error")
    why = d.get("why") if isinstance(d.get("why"), str) else None
    nxt = d.get("next").strip() if isinstance(d.get("next"), str) else ""
    hints = gpu_hints(nxt)
    return {"mode": mode, "healthy": healthy, "gpus": _gpus(d), "profiles": _profiles(d),
            "last_seen": _short(last, 40), "error": scrub(err) if isinstance(err, str) and err.strip() else None,
            "why": scrub(why) if why and why.strip() else None, "hint_cmd": hints[0] if hints else None,
            "hint_cmds": hints}


def gpu_hints(nxt: str) -> list[str]:
    """Every `slop gpu ...` command slop.gpu's `next` text names, in order (the whole text when it is one bare
    command). Positional words are kept: `slop gpu install audio`."""
    nxt = " ".join(str(nxt or "").split())
    if nxt.startswith("slop gpu ") and "`" not in nxt:
        return [nxt]
    return [" ".join(c.split()) for c in GPU_CMD_RE.findall(nxt)]


def pick_gpu_hint(hints: list[str]) -> str | None:
    """The first hint that parses with slop.gpu's own parser; else the first that parses once its flags are dropped
    (`slop gpu serve --tunnel` -> `slop gpu serve`: the tunnel is the default); else None."""
    for h in hints:
        if command_parses(h):
            return h
    for h in hints:
        bare = " ".join(w for w in h.split() if not w.startswith("-"))
        if bare != h and command_parses(bare):
            return bare
    return None


def gpu(timeout: float | None = None) -> dict:
    """`slop gpu status` (slop.gpu) -> {available, module, ok, mode, healthy, gpus, profiles, error, hint_cmd}."""
    mod = module_for("gpu")
    if not mod:
        return {"available": False, "module": None, "unregistered": package_present("gpu")}
    r = run_cli(mod, ["gpu", "status"], timeout)
    if r.get("unregistered"):
        return {"available": False, "module": mod, "error": r.get("error")}
    data = r.get("data")
    g = normalize_gpu(data)
    g["hint_cmd"] = pick_gpu_hint(g.pop("hint_cmds", None) or [])
    known = isinstance(data, dict) and bool(data)
    return {"available": True, "module": mod, "ok": bool(r.get("ok")), **g,
            "error": g.get("error") or (None if r.get("ok") or known else r.get("error"))}


# ---------------------------------------------------------------- taste / projects
def taste() -> dict:
    """The USER taste profile ($SLOP_HOME/taste): images, taps, last meter. No numpy, nothing created."""
    try:
        from ..taste.profile import counts
        from ..taste.store import user_profile_dir
    except Exception as e:
        return {"available": False, "error": scrub(f"{type(e).__name__}: {e}")}
    root = user_profile_dir()
    try:
        c = counts(root) if root.is_dir() else {"images": 0, "taps": 0, "pairs": 0, "font_picks": 0, "meter": None}
    except Exception as e:
        return {"available": True, "root": str(root), "taps": 0, "meter": None, "error": scrub(e)}
    return {"available": True, "root": str(root), **c}


def projects() -> list[dict]:
    """Projects under $SLOP_PROJECTS, newest first: {name, tier, mj_profile_set, mj_plan, broken}. mj_plan = the plan
    the plate book uses (project.json mj.plan, else its default 'standard')."""
    root = projects_root()
    rows: list[dict] = []
    try:
        dirs = [d for d in root.iterdir() if d.is_dir()] if root.is_dir() else []
    except OSError:
        return rows
    for d in dirs:
        pj = d / "project.json"
        if not pj.is_file():
            continue
        broken = False
        try:
            data = json.loads(pj.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("not an object")
        except (OSError, ValueError):
            data, broken = {}, True
        mj = data.get("mj") if isinstance(data.get("mj"), dict) else {}
        try:
            mt = pj.stat().st_mtime
        except OSError:
            mt = 0.0
        rows.append({"name": d.name, "tier": data.get("tier") if data.get("tier") in TIERS else None,
                     "mj_profile_set": bool(PROFILE_RE.fullmatch(str(mj.get("profile") or "").strip())),
                     "mj_plan": str(mj.get("plan") or "standard").strip().lower(),
                     "broken": broken, "mtime": mt})
    rows.sort(key=lambda r: r["mtime"], reverse=True)
    return rows

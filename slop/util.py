"""Small shared helpers (stdlib only, so `slop doctor` runs before the venv exists).

Other modules may import these; signatures are kept stable:

  stamp() / today() / iso_now()     UTC timestamps for DECISIONS.md / RUNS.md / project.json; parse_iso(s)
  add_common_flags(parser)          lets `slop <cmd> --json` / `--project X` work after the subcommand too
  hoist_global_flags(argv)          moves --json / --project X / -p X written after the command to the front, so the
                                    root parser sees them for EVERY module (for slop/cli.py main(); see its docstring)
  json_usage_errors(parser)         argparse usage errors print {"ok": false, "error", "usage"} on stdout when --json
                                    is on the command line (applied to every subparser below `parser`)
  atomic_write_text/json, read_json safe file IO (write to *.tmp then rename); file_sig(path) = content signature
  load_env_file(path)               KEY=VALUE reader (port of the original envload.py; env values win)
  read_lyric_lines(path)            content lines of lyrics/lyrics.txt or lyrics/display.txt (see FORMAT below);
  lyric_lines(text), is_lyric_noise(line)   the same rule on text / one line. THE one lyric-line parser: the audio,
                                    board, taste and core modules all use it, so their line numbers always agree
  find_tool(name)                   $SLOP_HOME/bin first, then PATH
  input_path(pdir, s), not_found(pdir, s, what)   an input file named on the command line: found from the current
                                    folder first, else the same relative path inside the project folder (a bot that
                                    is not cd'ed into the project can pass "lyrics/draft.txt"); the error names both
  with_project_flag(text, ref)      `slop clip …` hint lines -> `slop -p REF clip …` (a hint pasted verbatim then runs
                                    from any folder; lines that already name a project are left alone)
  run(cmd, timeout)                 subprocess that never raises; returns (rc, stdout, stderr)
  http_json(url, headers, timeout)  GET -> (status, json|None, error|None); the one place tests mock
  openrouter_key_info / openrouter_credits   FREE OpenRouter account endpoints (never print the key or its label)
  browser_launch_kwargs()           Playwright launch kwargs from SLOP_BROWSER_CHANNEL (written by bin/setup.sh)
  mem_info / cpu_info / disk_info   machine facts for doctor

Lyric file FORMAT (lyrics/lyrics.txt and lyrics/display.txt), identical to the audio module's reader and to the
original analyze.py: blank lines and every line starting with "[" (section tags like [Chorus], and notes) are
ignored; the Nth remaining line of display.txt is the on-screen version of the Nth remaining line of lyrics.txt.

Ported from: tools/envload.py (load_env only; the `require` half is config.require_env). Change: nothing is loaded
implicitly - secrets come from the environment (Grok Bot secret cards); load_env_file is for explicit local use.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .config import SlopError, slop_home

OPENROUTER_API = "https://openrouter.ai/api/v1"
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")


# ---------------------------------------------------------------- time
STAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}(?: \d{2}:\d{2} UTC)?")


def stamp(ts: float | None = None) -> str:
    """'2026-10-01 14:03 UTC' - always UTC, so logs written on different machines sort and parse the same."""
    d = datetime.fromtimestamp(ts if ts is not None else time.time(), tz=timezone.utc)
    return d.strftime("%Y-%m-%d %H:%M UTC")


def today() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")


def iso_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")


def parse_iso(s: Any) -> datetime | None:
    """ISO-8601 text ('2026-10-08T00:00:00Z', '...+00:00', '2026-10-08') -> aware UTC datetime, else None."""
    if not isinstance(s, str) or not s.strip():
        return None
    t = s.strip().replace("Z", "+00:00").replace("z", "+00:00")
    try:
        d = datetime.fromisoformat(t)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------- argparse
def add_common_flags(parser) -> None:
    """Accept --json and --project/-p AFTER the subcommand as well (`slop status --json`).

    default=SUPPRESS keeps the root parser's value when the flag is not repeated here.
    """
    import argparse
    parser.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                        help="machine-readable JSON on stdout")
    parser.add_argument("--project", "-p", default=argparse.SUPPRESS,
                        help="project name or path (else $SLOP_PROJECT or cwd)")


GLOBAL_FLAGS_WITH_VALUE = ("--project", "-p")
GLOBAL_FLAGS = ("--json",)


def hoist_global_flags(argv: list[str]) -> list[str]:
    """Move the root flags --json, --project X, --project=X and -p X found AFTER the command name to the front.

    `slop status --json -p x` becomes `slop --json -p x status`, so every module accepts the flags in either place
    without each one calling add_common_flags. Tokens after a bare `--` are left alone; a trailing `-p` with no value
    is left in place for argparse to report. The value of -p/--project is taken verbatim (it may start with '-').
    """
    argv = list(argv)
    front: list[str] = []
    rest: list[str] = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--":
            rest += argv[i:]
            break
        if a in GLOBAL_FLAGS:
            front.append(a)
        elif a in GLOBAL_FLAGS_WITH_VALUE and i + 1 < len(argv):
            front += [a, argv[i + 1]]
            i += 1
        elif a.startswith("--project="):
            front.append(a)
        else:
            rest.append(a)
        i += 1
    return front + rest


def json_usage_errors(parser, argv: list[str] | None = None) -> None:
    """Make argparse usage errors honour --json for `parser` and every subparser below it.

    Without this, `slop --json new` (missing NAME) prints usage on stderr and exits 2 with nothing on stdout, so the
    bot gets no {"ok": false} object. With it, when --json is on the command line (argv, else sys.argv) the error is
    printed as {"ok": false, "error": "<prog>: <message>", "usage": "<usage>"} on stdout; the exit code stays 2.
    """
    import argparse

    def patch(p) -> None:
        if getattr(p, "_slop_json_errors", False):
            return

        def error(message: str, _p=p) -> None:
            words = argv if argv is not None else sys.argv[1:]
            if "--json" in words:
                print(json.dumps({"ok": False, "error": f"{_p.prog}: {message}", "usage": _p.format_usage().strip(),
                                  "hint": f"{_p.prog} --help shows the options"}, ensure_ascii=False))
                sys.exit(2)
            argparse.ArgumentParser.error(_p, message)
        p.error = error
        p._slop_json_errors = True
        for act in p._actions:
            if isinstance(act, argparse._SubParsersAction):
                for sp in act.choices.values():
                    patch(sp)
    patch(parser)


# ---------------------------------------------------------------- files
def file_sig(path: Path, max_hash_bytes: int = 8 * 1024 * 1024) -> str | None:
    """A cheap content signature: 'sha1:<16 hex>' for files up to 8 MB, else 'size:<n>:mtime:<int>'. None if missing."""
    path = Path(path)
    try:
        st = path.stat()
    except OSError:
        return None
    if not path.is_file():
        return None
    if st.st_size <= max_hash_bytes:
        import hashlib
        try:
            return "sha1:" + hashlib.sha1(path.read_bytes()).hexdigest()[:16]
        except OSError:
            return None
    return f"size:{st.st_size}:mtime:{int(st.st_mtime)}"


def atomic_write_text(path: Path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    tmp.replace(path)


def atomic_write_json(path: Path, data: Any, indent: int | None = 1) -> None:
    atomic_write_text(path, json.dumps(data, indent=indent, ensure_ascii=False) + "\n")


def read_json(path: Path, default: Any = None) -> Any:
    """Parsed JSON, or `default` when the file is missing. Malformed JSON raises SlopError naming the file."""
    path = Path(path)
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise SlopError(f"{path} is not valid JSON ({e.msg} at line {e.lineno}); fix or delete it") from e


def append_text(path: Path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(text)


def human_bytes(n: float | int | None) -> str:
    if n is None:
        return "?"
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


# ---------------------------------------------------------------- names, env
def validate_name(name: str) -> str:
    if not NAME_RE.fullmatch(name or ""):
        raise SlopError(f"bad project NAME {name!r}: use lowercase letters, digits and dashes, start with a letter "
                        "or digit, at most 63 characters (e.g. my-song)")
    return name


def load_env_file(path: str | Path, override: bool = False) -> dict[str, str]:
    """Parse KEY=VALUE lines (quotes optional, '# comments', optional 'export ') into os.environ.

    Values already in the environment win unless override=True. Returns the dict read (callers must never print it).
    Missing file -> {}. Port of the original envload.load_env.
    """
    got: dict[str, str] = {}
    p = Path(path).expanduser()
    if not p.is_file():
        return got
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        if k.startswith("export "):
            k = k[len("export "):].strip()
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1].replace('\\"', '"')
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", k):
            continue
        got[k] = v
        if override or k not in os.environ:
            os.environ[k] = v
    return got


def env_present(name: str) -> bool:
    return bool(os.environ.get(name, "").strip())


# ---------------------------------------------------------------- lyrics
def is_lyric_noise(line: str) -> bool:
    """True for lines the aligner ignores: blank, or starting with "[" (section tags, notes)."""
    s = line.strip()
    return not s or s.startswith("[")


def lyric_lines(text: str) -> list[str]:
    """The lyric lines of a lyrics.txt / display.txt text (see module FORMAT), stripped, in order: line k of the
    result is lyric line k (0-based) everywhere in the toolkit."""
    return [ln.strip() for ln in text.splitlines() if not is_lyric_noise(ln)]


def read_lyric_lines(path: str | Path) -> list[str]:
    """Content lines of a lyric file (see module FORMAT). Missing file -> []."""
    p = Path(path)
    if not p.is_file():
        return []
    return lyric_lines(p.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- the edit
_CODE_TREATMENTS = {"pure-motion", "motion-design", "pure-motion-design", "code", "motion", "pm", "none"}


def shots_without_picture(pdir: Path) -> list[str] | None:
    """Ids of storyboard shots that edit/edl.json gives no picture (no plate, no clip segment), code-drawn shots
    excepted. None when there is no board or no EDL yet. Such a shot renders as a bare background behind the type, so
    status, `slop render frames` and `slop render encode` report it (integration: a master with no plates at all used
    to render, encode and pass every check)."""
    S = read_json(Path(pdir) / "board/shots.json")
    E = read_json(Path(pdir) / "edit/edl.json")
    if not isinstance(S, dict) or not isinstance(E, dict):
        return None
    out = []
    for s in S.get("shots") or []:
        if not isinstance(s, dict) or not s.get("id"):
            continue
        t = s.get("treatment")
        t = (t.get("family") if isinstance(t, dict) else t) or ""
        if s.get("code") or s.get("motion_tier") == "code" or str(t).strip().lower() in _CODE_TREATMENTS:
            continue
        if s["id"] not in E:
            out.append(s["id"])
    return out


def no_picture_text(ids: list[str]) -> str:
    return (f"{len(ids)} shot(s) have no picture in edit/edl.json (no picked plate, no clip): {', '.join(ids[:10])}"
            + (" …" if len(ids) > 10 else "") + " — they render as a bare background. Pick plates (`slop plates pick`) "
            "or mark code-drawn shots (\"treatment\": \"pure-motion\"), then `slop edit edl` and `slop edit export`")


# ---------------------------------------------------------------- input paths + hint lines
def input_path(pdir: Path | str | None, s: str | Path | None) -> Path | None:
    """An input file/folder named on the command line: as given when it exists (absolute, ~, or relative to the
    current folder); else, for a relative path, the same path inside the project folder when it exists there; else
    as given (so the caller's "not found" error shows what was typed). The bot's shell is rarely cd'ed into the
    project, so `lyrics/draft.txt` or `plates/dl/` must work from anywhere."""
    if s is None or str(s) == "":
        return None
    p = Path(str(s)).expanduser()
    if p.is_absolute() or p.exists() or pdir is None:
        return p
    q = Path(pdir) / p
    return q if q.exists() else p


def not_found(pdir: Path | str | None, s: str | Path, what: str = "file") -> str:
    """The error text for an input that input_path() could not find (names both places it looked)."""
    where = f"the current folder ({Path.cwd()})" + (f" or the project folder ({pdir})" if pdir else "")
    return (f"{what} {s} not found in {where}: give its full path, or a path relative to the project folder "
            "(e.g. lyrics/draft.txt)")


HINT_FAMILIES = ("clip", "gen", "plates", "board", "analyze", "song", "lyrics", "audio", "edit", "render", "review",
                 "taste", "status", "next", "spend", "gate", "decide", "job", "lead", "brief", "runs", "sync", "fetch",
                 "project")
_HINT_RE = re.compile(r"(?<![\w$/.-])slop (?!-p |--project[ =])(?=(?:--json )?(?:" + "|".join(HINT_FAMILIES)
                      + r")\b)")


def with_project_flag(text: Any, ref: str | None) -> Any:
    """`slop clip submit W01 --yes` -> `slop -p REF clip submit W01 --yes` in every hint line of `text` (strings only;
    anything else is returned unchanged). Idempotent: a line that already names a project keeps it."""
    if not ref or not isinstance(text, str) or "slop " not in text:
        return text
    return _HINT_RE.sub(lambda _m: f"slop -p {ref} ", text)


# ---------------------------------------------------------------- processes
def find_tool(name: str) -> str | None:
    """Absolute path of an executable: $SLOP_HOME/bin first (setup.sh installs cloudflared/uv there), then PATH."""
    for d in (slop_home() / "bin",):
        for cand in (d / name, d / (name + ".exe")):
            if cand.is_file() and os.access(cand, os.X_OK):
                return str(cand)
    return shutil.which(name)


def run(cmd: list[str], timeout: float = 60, env: dict | None = None, cwd: str | Path | None = None
        ) -> tuple[int, str, str]:
    """Run a command; never raises. rc 127 = not found, 124 = timeout."""
    try:
        cp = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env, cwd=cwd,
                            encoding="utf-8", errors="replace")
        return cp.returncode, cp.stdout or "", cp.stderr or ""
    except FileNotFoundError as e:
        return 127, "", str(e)
    except subprocess.TimeoutExpired as e:
        out = e.stdout.decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        return 124, out, f"timed out after {timeout:g} s"
    except OSError as e:
        return 126, "", str(e)


# ---------------------------------------------------------------- http (free endpoints only)
def http_json(url: str, headers: dict | None = None, timeout: float = 20, method: str = "GET"
              ) -> tuple[int, Any, str | None]:
    """(status, parsed JSON or None, error text or None). status 0 = network error. Never raises."""
    req = urllib.request.Request(url, headers={"User-Agent": "claudia", **(headers or {})}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            status = r.status
    except urllib.error.HTTPError as e:
        try:
            body = e.read()
        except Exception:
            body = b""
        data = None
        try:
            data = json.loads(body.decode("utf-8", "replace")) if body else None
        except ValueError:
            pass
        msg = None
        if isinstance(data, dict):
            err = data.get("error")
            msg = err.get("message") if isinstance(err, dict) else (err if isinstance(err, str) else None)
        return e.code, data, msg or f"HTTP {e.code}"
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        reason = getattr(e, "reason", e)
        return 0, None, f"network error: {reason}"
    try:
        return status, json.loads(body.decode("utf-8", "replace")) if body else None, None
    except ValueError:
        return status, None, "response was not JSON"


def http_reachable(url: str, timeout: float = 8) -> tuple[bool, int, str | None]:
    """Any HTTP answer (even 4xx) counts as reachable. Returns (reachable, status, error)."""
    status, _, err = http_json(url, timeout=timeout, method="GET")
    return status != 0, status, (err if status == 0 else None)


_KEY_FIELDS = ("limit", "limit_remaining", "limit_reset", "usage", "usage_daily", "usage_weekly", "usage_monthly",
               "is_free_tier", "expires_at", "include_byok_in_limit", "byok_usage", "effective_budget")
OPENROUTER_REPLACE = ("the person makes a new OpenRouter key at openrouter.ai/settings/keys (with a credit limit) and "
                      "sends it on the masked secure secret card, OPENROUTER_API_KEY (never in chat)")


def openrouter_key_info(key: str | None = None, timeout: float = 20) -> dict:
    """FREE GET /api/v1/key. Returns {present, ok, status, error, limit, limit_remaining, usage, ...}.

    Never returns the key or its label. present=False when OPENROUTER_API_KEY is unset.
    """
    key = key if key is not None else os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        return {"present": False, "ok": False, "status": None,
                "error": "OPENROUTER_API_KEY is not set (ask the bot to request it with its secure secret card)"}
    status, data, err = http_json(f"{OPENROUTER_API}/key", {"Authorization": f"Bearer {key}"}, timeout=timeout)
    out: dict[str, Any] = {"present": True, "status": status}
    if status == 200 and isinstance(data, dict) and isinstance(data.get("data"), dict):
        d = data["data"]
        out.update({k: d.get(k) for k in _KEY_FIELDS if k in d})
        out["ok"] = True
        out["error"] = None
        if out.get("limit_remaining") is None and isinstance(d.get("limit"), (int, float)) \
                and isinstance(d.get("usage"), (int, float)):
            out["limit_remaining"] = round(d["limit"] - d["usage"], 6)
        return out
    out["ok"] = False
    if status in (401, 403):
        out["error"] = f"OpenRouter rejected the key (HTTP {status}): it is wrong, disabled or expired"
    elif status == 0:
        out["error"] = f"openrouter.ai unreachable ({err}); on a team network allowlist, add openrouter.ai"
    else:
        out["error"] = f"OpenRouter /key answered HTTP {status}: {err}"
    return out


def openrouter_key_trouble(info: dict) -> str | None:
    """One sentence when the key fails now or soon (rejected, expired or expiring within 14 days, under $2 left of its
    limit or budget); None when it is fine, unset or unreachable. Never the key or its label."""
    if not info.get("present") or info.get("status") == 0:
        return None
    if not info.get("ok"):
        return f"the OpenRouter key no longer works ({info.get('error') or 'rejected'})"
    exp = parse_iso(info.get("expires_at"))
    if exp is not None:
        days = (exp - datetime.now(tz=timezone.utc)).total_seconds() / 86400
        if days <= 0:
            return f"the OpenRouter key expired on {exp.strftime('%Y-%m-%d')}"
        if days < 14:
            return f"the OpenRouter key expires on {exp.strftime('%Y-%m-%d')} ({days:.0f} days)"
    rem = info.get("limit_remaining")
    if info.get("limit") is not None and isinstance(rem, (int, float)) and rem < 2:
        return f"the OpenRouter key has {money(rem)} left of its {money(info.get('limit'))} limit"
    eb = info.get("effective_budget") if isinstance(info.get("effective_budget"), dict) else {}
    if isinstance(eb.get("remaining_usd"), (int, float)) and eb["remaining_usd"] < 2:
        return f"the OpenRouter key's {eb.get('reset_interval') or ''} budget has {money(eb['remaining_usd'])} left"
    return None


def openrouter_credits(key: str | None = None, timeout: float = 20) -> dict:
    """FREE GET /api/v1/credits -> {ok, total_credits, total_usage, balance} (account level, all keys)."""
    key = key if key is not None else os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        return {"ok": False, "error": "OPENROUTER_API_KEY is not set"}
    status, data, err = http_json(f"{OPENROUTER_API}/credits", {"Authorization": f"Bearer {key}"}, timeout=timeout)
    if status == 200 and isinstance(data, dict) and isinstance(data.get("data"), dict):
        d = data["data"]
        tc, tu = d.get("total_credits"), d.get("total_usage")
        bal = round(tc - tu, 6) if isinstance(tc, (int, float)) and isinstance(tu, (int, float)) else None
        return {"ok": True, "total_credits": tc, "total_usage": tu, "balance": bal}
    return {"ok": False, "status": status, "error": err or f"HTTP {status}"}


# ---------------------------------------------------------------- browser
def browser_channel() -> str:
    """'chrome' when SLOP_BROWSER_CHANNEL=chrome (setup.sh fallback to the system google-chrome), else 'chromium' (bundled)."""
    ch = os.environ.get("SLOP_BROWSER_CHANNEL", "").strip().lower()
    return ch if ch in ("chromium", "chrome") else "chromium"


def browser_launch_kwargs(channel: str | None = None) -> dict:
    """kwargs for playwright `p.chromium.launch(**kw)`; renders must use this so the setup.sh fallback works."""
    ch = channel or browser_channel()
    kw: dict[str, Any] = {"headless": True}
    if ch == "chrome":
        kw["channel"] = "chrome"
    return kw


def playwright_env() -> dict:
    """os.environ plus PLAYWRIGHT_BROWSERS_PATH=$SLOP_HOME/ms-playwright when setup.sh installed browsers there."""
    env = dict(os.environ)
    if not env.get("PLAYWRIGHT_BROWSERS_PATH"):
        p = slop_home() / "ms-playwright"
        if p.is_dir():
            env["PLAYWRIGHT_BROWSERS_PATH"] = str(p)
    return env


# ---------------------------------------------------------------- machine facts
def mem_info() -> dict:
    """{'total': bytes|None, 'available': bytes|None}."""
    total = avail = None
    try:
        with open("/proc/meminfo", encoding="utf-8") as f:
            vals = {}
            for line in f:
                k, _, rest = line.partition(":")
                parts = rest.split()
                if parts:
                    vals[k] = int(parts[0]) * 1024
        total, avail = vals.get("MemTotal"), vals.get("MemAvailable")
    except OSError:
        pass
    if total is None and hasattr(os, "sysconf"):
        try:
            total = os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
        except (ValueError, OSError, AttributeError):
            pass
    if total is None and sys.platform == "win32":  # pragma: no cover - dev convenience only
        import ctypes

        class MS(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        m = MS()
        m.dwLength = ctypes.sizeof(MS)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
            total, avail = int(m.ullTotalPhys), int(m.ullAvailPhys)
    return {"total": total, "available": avail}


def cpu_info() -> dict:
    count = os.cpu_count()
    usable = None
    if hasattr(os, "sched_getaffinity"):
        try:
            usable = len(os.sched_getaffinity(0))
        except OSError:
            pass
    model = None
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as f:
            for line in f:
                if line.lower().startswith("model name"):
                    model = line.split(":", 1)[1].strip()
                    break
    except OSError:
        pass
    if not model:
        import platform
        model = platform.processor() or platform.machine() or None
    return {"count": count, "usable": usable or count, "model": model}


def existing_parent(path: Path) -> Path:
    p = Path(path).expanduser()
    while not p.exists() and p != p.parent:
        p = p.parent
    return p


def disk_info(path: Path) -> dict:
    p = existing_parent(path)
    try:
        u = shutil.disk_usage(p)
        return {"path": str(path), "measured_at": str(p), "total": u.total, "free": u.free}
    except OSError as e:
        return {"path": str(path), "measured_at": str(p), "total": None, "free": None, "error": str(e)}


# ---------------------------------------------------------------- text tables
def table(rows: Iterable[Iterable[Any]], header: Iterable[str] | None = None) -> str:
    rows = [[("" if c is None else str(c)) for c in r] for r in rows]
    if header is not None:
        rows = [[str(h) for h in header]] + rows
    if not rows:
        return ""
    w = [max(len(r[i]) if i < len(r) else 0 for r in rows) for i in range(max(len(r) for r in rows))]
    out = ["  ".join(c.ljust(w[i]) for i, c in enumerate(r)).rstrip() for r in rows]
    if header is not None:
        out.insert(1, "  ".join("-" * x for x in w))
    return "\n".join(out)


def money(x: float | int | None) -> str:
    return "?" if x is None else f"${x:,.2f}"

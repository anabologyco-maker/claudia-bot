"""`slop relay`: Grok passes the person's words; the production (Claude Code, or Codex, on this computer) does the work.

One relay per bot, no project name needed. Grok's side:
  slop --json relay setup [--engine claude|codex] [--model M]    check the engine; register the claudia.gallery MCP;
                                                                 install the Claudia skill; write the production brief
  slop --json relay send '<words>' [--from grok] | --file F      the person's words, verbatim; starts a production turn
                                                                 when the production is idle (returns in seconds)
  slop --json relay read [--wait S] [--all]                      what to show next, open jobs, and one `grok_next` line
  slop --json relay done JOB --file PATH [--file PATH ...]       a job's files are saved: tells the production
  slop --json relay fail JOB --reason '<words>' [--declined]     a job could not be done: tells the production
  slop --json relay status | stop | log [--lines N]
The production's side (it works in the projects folder and picks or creates the project itself):
  slop relay say TEXT [--show FILE ...]                          a message for the director
  slop relay ask QUESTION [--default X] [--show FILE ...]        one question, with its default
  slop relay job --kind grok-imagine|midjourney|suno|browser|person ...   browser work for Grok (all of it), or a step
                                                                 only the person can
                                                                 do; numbered J-0003
  slop relay inbox                                               new messages, marked read

Files, in $SLOP_HOME/relay/ (all LF; appends for the logs, atomic renames for the rest; a short lock folder guards
every change):
  config.json        engine, model, what setup did
  inbox.jsonl        {id, ts, t, from, text}: every message to the production, verbatim
  decisions.md       every director message, dated, append-only (the production copies decisions into a project's
                     DECISIONS.md with `slop -p NAME decide`)
  outbox.jsonl       {id, ts, t, kind say|ask|job, text, default, files[], turn, auto}: every message for the director
                     and every job (job J-NNNN = outbox id NNNN, with all its fields; absolute paths)
  jobs.json          {J-NNNN: {status done|failed|declined|cancelled, files[], reason, ended}}; a job not in it is open
  state.json         cursors (delivered = last inbox id given to the production, read = last outbox id Grok showed),
                     turns, sessions {engine: id}, last_error, last_turn
  runner.json        the supervisor: starting | running | idle | failed | stopped (+ pid, job id)
  turn.json          the running turn: number, start, pid, last progress line (written by the supervisor only)
  relay.log          one line per event; turns/turn-NNNN.jsonl (+ .err): each turn's raw stream and stderr
  bin/               a `slop` command for the production (this toolkit's Python)
The brief (CLAUDE.md and AGENTS.md) goes into the projects folder, the production's working folder.

The supervisor is a `slop job` (`relay _run`): it takes the pending messages, runs one engine turn with them as the
prompt (resuming the same session), and repeats until nothing is pending; a message that arrives during a turn waits
for the next one. A failed turn puts its messages back and stops; the next `send` starts again.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from . import util
from .config import SlopError, projects_root, resolve_project, slop_home, toolkit_root

MCP_NAME = "claudia"
MCP_URL = "https://claudia.gallery/mcp"
SKILL_URL = "https://claudia.gallery/skill/claudia-skill.zip"
ENGINES = ("claude", "codex")
DEFAULT_MODEL = {"claude": "opus", "codex": None}
WAIT_CAP_S = 240.0
READ_SETTLE = 5                # a production that stops working must stay stopped this many polls (2 s) to end a wait
WAKE_KEY_ENV = "CLAUDIA_WAKE_KEY"   # the wake-up routine's webhook key: a masked secure secret card, never a file
WAKE_BASE = "https://api2.cursor.sh"   # Grok Bot's backend: a routine's webhook is <backend>/automations/webhook/<id>
WAKE_QUIET_S = 8.0             # posts in a burst (a say, then an ask) wake Grok once
WAKE_TICK_S = 2.0
WAKE_RETRY_S = (30.0, 120.0)   # a failed wake-up is tried again after these, then given up for that batch
PROMPT_ARG_MAX = 6000          # longer prompts go through a file (Windows command lines max out at 32,767 chars)
START_GRACE_S = 30.0           # a "starting" claim without a supervisor is given up after this
LOCK_WAIT_S = 20.0
LOCK_STALE_S = 60.0            # every change holds the lock for milliseconds; an older lock is a crashed caller's
BRIEF_MARK = "<!-- slop relay: production brief"
BRIEF_FILES = {"claude": "CLAUDE.md", "codex": "AGENTS.md"}
JOB_ENV = ("SLOP_JOB_ID", "SLOP_PROGRESS_FILE", "SLOP_JOB_FILE", "SLOP_FREE_ONLY", "SLOP_PROJECT")
NO_SESSION_RE = re.compile(r"(?i)no conversation found|session[^.\n]{0,40}not found|thread[^.\n]{0,40}not found")
SIGNIN_RE = re.compile(r"(?i)\b401\b|authenticat|not logged in|please (?:log|sign) ?in|invalid[^.\n]{0,30}token")
LIMIT_RE = re.compile(r"(?i)usage limit|rate limit|session limit|hit your limit|limit reached")
EFFORT_DEFAULT = "xhigh"       # both engines; a level the engine or its model does not take falls back to its default
EFFORT_ENV = {"claude": "SLOP_CLAUDE_EFFORT", "codex": "SLOP_CODEX_EFFORT"}
EFFORT_USUAL = {"claude": ("low", "medium", "high", "xhigh", "max"), "codex": ("low", "medium", "high", "xhigh")}
EFFORT_RE = re.compile(r"(?i)effort")
EFFORT_FAST_S = 90.0           # an effort complaint only counts when the turn failed this fast (before any real work)


# ================================================================================================== files and lock
def relay_dir() -> Path:
    return slop_home() / "relay"


def work_dir() -> Path:
    """The production's working folder: the projects folder (it picks or creates the project itself)."""
    return projects_root()


def _dirs() -> tuple[Path, Path]:
    rd, wd = relay_dir(), work_dir()
    rd.mkdir(parents=True, exist_ok=True)
    wd.mkdir(parents=True, exist_ok=True)
    return wd, rd


def _break_stale(lk: Path) -> bool:
    """Remove a lock whose owner process is gone (or, with no owner recorded, one older than LOCK_STALE_S; the wall
    clock can step, so a live owner is never judged by age)."""
    try:
        pid = int((lk / "owner").read_text().strip() or 0)
    except (OSError, ValueError):
        pid = 0
    try:
        if pid:
            if _alive(pid):
                return False
        elif time.time() - lk.stat().st_mtime < LOCK_STALE_S:
            return False
        for f in lk.iterdir():
            f.unlink()
        os.rmdir(lk)
        return True
    except OSError:
        return False


@contextlib.contextmanager
def _lock(rd: Path):
    """A lock folder (mkdir is atomic on every OS) with its owner's pid. Held for milliseconds."""
    rd.mkdir(parents=True, exist_ok=True)
    lk = rd / "lock"
    t0 = time.monotonic()
    while True:
        try:
            os.mkdir(lk)
            break
        except (FileExistsError, PermissionError):
            pass
        if _break_stale(lk):
            continue
        if time.monotonic() - t0 > LOCK_WAIT_S:
            raise SlopError(f"the relay is busy ({lk} is held); try again in a few seconds")
        time.sleep(0.02)
    try:
        (lk / "owner").write_text(str(os.getpid()), encoding="utf-8")
    except OSError:
        pass
    try:
        yield
    finally:
        try:
            (lk / "owner").unlink()
        except OSError:
            pass
        try:
            os.rmdir(lk)
        except OSError:
            pass


def _read_json(p: Path) -> dict:
    for _ in range(5):
        try:
            d = json.loads(Path(p).read_text(encoding="utf-8"))
            return d if isinstance(d, dict) else {}
        except FileNotFoundError:
            return {}
        except (OSError, ValueError):        # Windows: a rename in progress; elsewhere: never half-written
            time.sleep(0.02)
    return {}


def _write_json(p: Path, d: dict) -> None:
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(d, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    for _ in range(50):
        try:
            tmp.replace(p)
            return
        except PermissionError:              # Windows: a reader has the file open for a moment
            time.sleep(0.02)
    tmp.replace(p)


def _rows(p: Path) -> list[dict]:
    """Complete lines of a .jsonl file (a last line without its newline is still being written: skipped)."""
    try:
        data = Path(p).read_text(encoding="utf-8")
    except OSError:
        return []
    out = []
    for ln in data.split("\n")[:-1]:
        try:
            d = json.loads(ln)
        except ValueError:
            continue
        if isinstance(d, dict):
            out.append(d)
    return out


def _append(p: Path, rec: dict) -> None:
    util.append_text(p, json.dumps(rec, ensure_ascii=False) + "\n")


def _next_id(p: Path) -> int:
    return max((int(r.get("id") or 0) for r in _rows(p)), default=0) + 1


def _seq(rd: Path) -> int:
    """One order across the inbox and the outbox (never the wall clock: it can step, e.g. in WSL or a resumed VM)."""
    return max((int(r.get("seq") or 0) for n in ("inbox.jsonl", "outbox.jsonl") for r in _rows(rd / n)), default=0) + 1


def _log(rd: Path, msg: str) -> None:
    try:
        util.append_text(rd / "relay.log", f"{util.stamp()} {' '.join(str(msg).split())[:500]}\n")
    except OSError:
        pass


def _tail(p: Path, n: int) -> str:
    try:
        return "\n".join(Path(p).read_text(encoding="utf-8", errors="replace").splitlines()[-n:])
    except OSError:
        return ""


def _cfg(rd: Path, need: bool = True) -> dict:
    c = _read_json(rd / "config.json")
    if need and not c.get("engine"):
        raise SlopError("the relay is not set up on this computer: run  slop --json relay setup  first")
    return c


# ================================================================================================== production state
def _alive(pid, start=None) -> bool:
    from .job import alive
    try:
        return alive(int(pid), start) if pid else False
    except (TypeError, ValueError):
        return False


def _runner(rd: Path) -> dict:
    r = _read_json(rd / "runner.json")
    st = r.get("state")
    if st == "starting":                  # the monotonic clock is shared by every process and never steps
        age = time.monotonic() - float(r.get("since_mono") or 0)
        r["alive"] = 0 <= age < START_GRACE_S
    elif st == "running":
        r["alive"] = _alive(r.get("pid"), r.get("pid_start"))
    else:
        r["alive"] = False
    return r


def _pending(rd: Path, st: dict) -> list[dict]:
    seen = int(st.get("delivered") or 0)
    return [m for m in _rows(rd / "inbox.jsonl") if int(m.get("id") or 0) > seen]


def job_id(oid: int) -> str:
    return f"J-{int(oid):04d}"


def _jobs(rd: Path, open_only: bool = True) -> list[dict]:
    """Jobs the production asked for (outbox items of kind "job"), with their status from jobs.json."""
    done = _read_json(rd / "jobs.json")
    out = []
    for r in _rows(rd / "outbox.jsonl"):
        if r.get("kind") != "job":
            continue
        st = done.get(r.get("job")) or {}
        j = {**r, "status": st.get("status") or "queued"}
        for k in ("reason", "ended", "hedra_state", "provider_job_id"):
            if st.get(k):
                j[k] = st[k]
        if st.get("files"):
            j["result_files"] = st["files"]
        if j.get("job_kind") == "hedra" and j.get("what") == "generate" and j["status"] == "queued":
            from .gen import store as clip_store
            c = clip_store.load(Path(j["project_dir"]), j["clip"])
            tk = next((t for t in c["takes"] if t["n"] == j.get("take")), {})
            if tk.get("relay_attempted"):
                j["hedra_state"] = "pending" if tk.get("id") else "started"
                j["provider_job_id"] = tk.get("id")
        if not open_only or j["status"] == "queued":
            out.append(j)
    return out


def production(rd: Path) -> dict:
    """{state: working|waiting|idle|failed|stopped|queued|not set up, since, turn, last, error, summary}."""
    from .job import dur
    if not (rd / "config.json").is_file():
        return {"state": "not set up", "summary": "the relay is not set up (slop --json relay setup)"}
    r = _runner(rd)
    tj = _read_json(rd / "turn.json")
    st = _read_json(rd / "state.json")
    pend = _pending(rd, st)
    out: dict = {"pending": len(pend)}
    if r["alive"]:
        running = tj.get("state") == "running" and r.get("state") == "running"
        since = float((tj.get("started_ts") if running else r.get("since_ts")) or time.time())
        out.update(state="working", since=(tj.get("started") if running else r.get("since")),
                   turn=tj.get("n") if running else None, last=(tj.get("last") if running else "starting a turn"),
                   last_at=tj.get("last_at"), working_s=round(time.time() - since, 1))
        out["summary"] = (f"working for {dur(out['working_s'])}" + (f" (turn {out['turn']})" if out.get("turn") else "")
                          + (f": {out['last']}" if out.get("last") else "")
                          + (f"; {len(pend)} message(s) wait for the next turn" if pend else ""))
        return out
    state = r.get("state")
    if state == "running":                # its process is gone without a record
        state, r["error"] = "failed", ("the production's process ended without a record (killed, out of memory, or "
                                         "the computer restarted)")
    if state == "failed":
        out.update(state="failed", error=r.get("error"), since=r.get("since"), log_tail=_tail(rd / "relay.log", 8),
                   stderr_tail=_tail(rd / "turns" / f"turn-{int(tj.get('n') or 0):04d}.err", 8))
        out["summary"] = f"failed: {str(r.get('error') or '?')[:300]}"
        return out
    if state == "stopped":
        out.update(state="stopped", since=r.get("since"), summary="stopped (the next `relay send` starts it again)")
        return out
    if pend:
        out.update(state="queued", summary=f"{len(pend)} message(s) wait, but no turn is running")
        return out
    talk = [m for m in _rows(rd / "outbox.jsonl") if m.get("kind") in ("say", "ask")]
    last = talk[-1] if talk else None
    said = [m for m in _rows(rd / "inbox.jsonl") if m.get("from") == "director"]
    if last and last.get("kind") == "ask" and (not said or int(said[-1].get("seq") or 0) < int(last.get("seq") or 0)):
        out.update(state="waiting", question=last.get("text"), default=last.get("default"),
                   summary=f"waiting for the director: {str(last.get('text'))[:200]}")
        return out
    out.update(state="idle", since=r.get("since"), summary="idle (waiting for the person's next words)")
    return out


# ================================================================================================== setup
def _mcp_claude() -> dict:
    from .agents import engines as E
    add = ["mcp", "add", "--transport", "http", "--scope", "user", MCP_NAME, MCP_URL]
    cmd = "claude " + " ".join(add)
    rc, out, err = E.run_cli("claude", ["mcp", "get", MCP_NAME], timeout=60)
    if rc == 0 and MCP_URL in out + err:
        return {"ok": True, "already": True, "command": cmd}
    if rc == 0:                                       # a `claudia` server with another address: replace it
        E.run_cli("claude", ["mcp", "remove", MCP_NAME, "--scope", "user"], timeout=60)
    rc, out, err = E.run_cli("claude", add, timeout=60)
    if rc == 0 or "already exists" in (out + err):
        return {"ok": True, "already": rc != 0, "command": cmd}
    return {"ok": False, "command": cmd, "error": (err or out).strip()[-400:] or f"exit {rc}"}


def _mcp_codex() -> dict:
    from .agents import engines as E
    f = E.codex_home() / "config.toml"
    block = f'[mcp_servers.{MCP_NAME}]\nurl = "{MCP_URL}"\n'
    try:
        text = f.read_text(encoding="utf-8") if f.is_file() else ""
    except OSError as e:
        return {"ok": False, "file": str(f), "error": str(e)}
    m = re.search(r"(?m)^\[mcp_servers\.\"?%s\"?\]\s*$" % MCP_NAME, text)
    if m:
        nxt = re.search(r"(?m)^\[", text[m.end():])
        end = m.end() + nxt.start() if nxt else len(text)
        if MCP_URL in text[m.end():end]:
            return {"ok": True, "already": True, "file": str(f)}
        text = text[:m.start()] + block + ("\n" if nxt else "") + text[end:]
    else:
        text = text.rstrip("\n") + ("\n\n" if text.strip() else "") + block
    try:
        util.atomic_write_text(f, text.replace("\r\n", "\n"))
    except OSError as e:
        return {"ok": False, "file": str(f), "error": str(e)}
    return {"ok": True, "already": False, "file": str(f)}


def _install_skill() -> dict:
    """The official Claudia skill (a zip) into ~/.claude/skills/. Offline: skipped, and said so."""
    import urllib.request
    import zipfile
    from .agents import engines as E
    url = os.environ.get("SLOP_RELAY_SKILL_URL") or SKILL_URL
    dest = E.claude_config_dir() / "skills"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "slop-relay"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = r.read()
        z = zipfile.ZipFile(io.BytesIO(data))
    except Exception as e:  # noqa: BLE001 - offline, blocked, or not a zip: the MCP has the same knowledge
        return {"ok": False, "skipped": True, "url": url,
                "why": f"could not download it ({type(e).__name__}: {str(e)[:160]}); the claudia MCP has the same "
                       "knowledge. Later: slop relay setup again"}
    files = []
    for info in z.infolist():
        name = info.filename.replace("\\", "/")
        if ".." in name.split("/") or name.startswith("/") or re.match(r"^[A-Za-z]:", name):
            continue                                  # never write outside the skills folder
        target = dest / name
        if info.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(z.read(info))
        files.append(name)
    tops = sorted({n.split("/")[0] for n in files if "/" in n})
    return {"ok": True, "dir": str(dest), "skills": tops, "files": len(files), "url": url}


def _brief_text(eng: str) -> str:
    tpl = toolkit_root() / "templates" / "production-brief.md"
    if not tpl.is_file():
        raise SlopError(f"the brief template is missing ({tpl}): the toolkit checkout is incomplete")
    subs = {"{{WORK}}": work_dir().as_posix(), "{{TOOLKIT}}": toolkit_root().as_posix(), "{{DATE}}": util.today(),
            "{{ENGINE}}": eng}
    text = tpl.read_text(encoding="utf-8").replace("\r\n", "\n")
    for k, v in subs.items():
        text = text.replace(k, v)
    return text


def _write_briefs(wd: Path, eng: str, force: bool) -> list[dict]:
    text = _brief_text(eng)
    out = []
    for e, name in BRIEF_FILES.items():
        f = wd / name
        try:
            cur = f.read_text(encoding="utf-8") if f.is_file() else None
        except OSError:
            cur = None
        if cur is not None and BRIEF_MARK not in cur[:400] and not force:
            out.append({"file": str(f), "engine": e, "written": False,
                        "why": f"{name} exists and was not written by slop relay (--force replaces it)"})
            continue
        util.atomic_write_text(f, text)
        out.append({"file": str(f), "engine": e, "written": True})
    return out


def _shim(rd: Path) -> Path:
    """$SLOP_HOME/relay/bin/slop: this toolkit's `slop` for the production (whatever else PATH holds)."""
    d = rd / "bin"
    d.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        util.atomic_write_text(d / "slop.cmd", f'@"{sys.executable}" -m slop %*\n')
    else:                                 # a Python that is gone (a temporary env) falls back to python3
        f = d / "slop"
        util.atomic_write_text(f, f'#!/bin/sh\nPY="{sys.executable}"\n[ -x "$PY" ] || PY=python3\n'
                                  'exec "$PY" -m slop "$@"\n')
        f.chmod(0o755)
    return d


def _setup_engine(a_engine: str | None, rd: Path) -> str:
    """--engine; else the engine the relay already runs; else the one installed and signed in here (Claude Code
    first); else the person's plans (`onboard set coding-agents`: ChatGPT only means Codex); else Claude Code."""
    from .agents import engines as E
    from .agents import status as S
    if a_engine:
        return E.norm_engine(a_engine)
    cur = _read_json(rd / "config.json").get("engine")
    if cur in ENGINES:
        return cur
    for e in ENGINES:
        try:
            s = S.engine_status(e)
        except Exception:  # noqa: BLE001 - an engine that cannot be checked is not the one
            continue
        if s.get("installed") and s.get("logged_in"):
            return e
    try:
        from .onboard import state as OS
        plans = (OS.load().get("settings") or {}).get("coding_agents") or []
    except Exception:  # noqa: BLE001
        plans = []
    return "codex" if "codex" in plans and "claude" not in plans else "claude"


def _login_path_hook() -> list[str]:
    """Codex runs its commands in login shells, and a login shell may reset PATH (Debian's /etc/profile does): load
    the toolkit's env.sh from ~/.profile and ~/.bashrc too, as the onboarding `path` item does. -> the files changed."""
    env_sh = slop_home() / "env.sh"
    if not env_sh.is_file():
        return []
    done = []
    for f in (".profile", ".bashrc"):
        p = Path.home() / f
        try:
            text = p.read_text(encoding="utf-8") if p.is_file() else ""
            if str(env_sh) in text:
                continue
            with open(p, "a", encoding="utf-8", newline="\n") as fh:
                fh.write(("" if not text or text.endswith("\n") else "\n") + f". {env_sh}\n")
            done.append(f)
        except OSError:
            pass
    return done


def cmd_setup(a) -> dict:
    from .agents import engines as E
    from .agents import status as S
    wd, rd = _dirs()
    eng = _setup_engine(a.engine, rd)
    if eng not in ENGINES:
        raise SlopError(f"the relay runs Claude Code (claude) or Codex (codex), not {eng}")
    title = E.SPEC[eng]["title"]
    s = S.engine_status(eng)
    if not s["installed"] or not s["logged_in"]:
        nxt = f"slop agents install {eng}" if not s["installed"] else (s.get("next") or f"slop agents login {eng}")
        what = "is not installed" if not s["installed"] else "is not signed in"
        return {"ok": False, "engine": eng, "error": f"{title} {what}", "next": nxt,
                "text": f"{title} {what} on this computer, so the relay was not set up.\n  next: {nxt}   (then: "
                        f"slop --json relay setup --engine {eng})"}
    mcp = _mcp_claude() if eng == "claude" else _mcp_codex()
    also = {}                         # the other engine gets the claudia MCP too: either one may produce later
    for e in ENGINES:
        if e == eng:
            continue
        if e == "codex":
            also[e] = _mcp_codex()    # a config file: ready the day Codex is installed
        elif S.engine_status(e)["installed"]:
            also[e] = _mcp_claude()
    skill = _install_skill() if (eng == "claude" and not a.no_skill) else {
        "ok": False, "skipped": True, "why": "--no-skill" if a.no_skill else "Codex reads the MCP and AGENTS.md"}
    briefs = _write_briefs(wd, eng, a.force)
    _shim(rd)
    hooked = _login_path_hook()
    model = a.model if a.model is not None else DEFAULT_MODEL[eng]
    with _lock(rd):
        _write_json(rd / "config.json", {"engine": eng, "model": model or None, "set_up": util.iso_now(),
                                         "work_dir": str(wd), "mcp": mcp, "mcp_also": also, "skill": skill,
                                         "briefs": briefs,
                                         "toolkit": str(toolkit_root())})
    _log(rd, f"setup: engine {eng} model {model or 'default'}; mcp {'ok' if mcp.get('ok') else 'FAILED'}; skill "
             f"{'ok' if skill.get('ok') else 'skipped'}")
    mine = next(b for b in briefs if b["engine"] == eng)
    ok = bool(mcp.get("ok")) and mine["written"]
    mcp_line = "  claudia MCP: " + ("already registered" if mcp.get("already") else "registered" if mcp.get("ok")
                                    else f"FAILED ({mcp.get('error')})") \
        + (f"  ({mcp['command']})" if mcp.get("command") else f"  ({mcp.get('file')})")
    lines = [f"relay set up: the production is {title}" + (f" ({model})" if model else "") + f", working in {wd}",
             f"  signed in: {s.get('auth_text') or 'yes'}" + (f", plan {s['plan']}" if s.get("plan") else ""),
             mcp_line] + [f"  claudia MCP for {E.SPEC[e]['title']} too: "
                          + ("ready" if m.get("ok") else f"FAILED ({m.get('error')})") for e, m in also.items()] + [
             "  Claudia skill: " + (f"installed in {skill['dir']} ({', '.join(skill['skills']) or 'files'})"
                                    if skill.get("ok") else f"skipped: {skill.get('why')}")]
    lines += [f"  brief: {b['file']}" + ("" if b["written"] else f" NOT written: {b['why']}") for b in briefs]
    if hooked:
        lines.append("  login shells now load env.sh too: " + ", ".join(f"~/{f}" for f in hooked))
    nxt = "slop --json relay send '<the person's words, verbatim>'"
    err = None
    if not mcp.get("ok"):
        nxt, err = mcp.get("command") or "slop --json relay setup", mcp_line.strip()
    elif not mine["written"]:
        nxt, err = f"slop --json relay setup --engine {eng} --force", f"brief not written: {mine['why']}"
    lines.append(f"next: {nxt}")
    return {"ok": ok, "engine": eng, "model": model, "work_dir": str(wd), "relay_dir": str(rd), "mcp": mcp,
            "mcp_also": also,
            "skill": skill, "briefs": briefs, "next": nxt, **({"error": err} if err else {}), "text": "\n".join(lines)}


# ================================================================================================== send / inbox
def _words(a, what: str) -> str:
    text = " ".join(a.text or [])
    f = getattr(a, "file", None)
    if f:
        if text:
            raise SlopError(f"give the {what} as TEXT or --file, not both")
        try:
            text = Path(f).expanduser().read_text(encoding="utf-8")
        except OSError as e:
            raise SlopError(f"cannot read {f}: {e}") from None
    if not text.strip():
        raise SlopError(f"nothing to {what}: slop --json relay {what} '<the words>'")
    return text


def _start_runner(wd: Path, rd: Path, claim: str) -> dict:
    from . import job
    try:
        r = job.start(["relay", "_run"], project=None, again=True, cwd=str(wd), status_sig="relay")
    except SlopError as e:
        with _lock(rd):
            if _read_json(rd / "runner.json").get("claim") == claim:
                _write_json(rd / "runner.json", {"state": "failed", "error": f"could not start the production: {e}",
                                                 "since": util.iso_now(), "since_ts": time.time()})
        raise
    s = r["job"]
    with _lock(rd):
        cur = _read_json(rd / "runner.json")
        if cur.get("claim") == claim:
            cur["job_id"] = s["id"]
            _write_json(rd / "runner.json", cur)
    return s


def cmd_send(a) -> dict:
    return deliver(_words(a, "send"), a.sender)


def deliver(text: str, who: str, job_update: tuple | None = None) -> dict:
    """Append a message to the inbox (director words also to decisions.md, dated) and start a turn when nothing runs.
    job_update = (job id, record): written to jobs.json under the same lock."""
    wd, rd = _dirs()
    cfg = _cfg(rd)
    claim = None
    with _lock(rd):
        if job_update:
            jobs = _read_json(rd / "jobs.json")
            if (jobs.get(job_update[0]) or {}).get("status") in ("done", "failed", "declined", "cancelled"):
                return {"ok": True, "job": job_update[0], "text": f"{job_update[0]}: already closed"}
            jobs[job_update[0]] = job_update[1]
            _write_json(rd / "jobs.json", jobs)
        mid = _next_id(rd / "inbox.jsonl")
        _append(rd / "inbox.jsonl", {"id": mid, "seq": _seq(rd), "ts": util.iso_now(), "t": round(time.time(), 3),
                                     "from": who, "text": text})
        if who == "director":
            dl = rd / "decisions.md"
            head = "" if dl.is_file() else ("# The director's words (slop relay; dated, append-only, never edited)\n\n")
            util.append_text(dl, head + f"- {util.stamp()} - [director, relay #{mid}] "
                             + re.sub(r"\s*\n\s*", " / ", text.strip()) + "\n")
        run = _runner(rd)
        if not run["alive"]:
            claim = uuid.uuid4().hex[:10]
            _write_json(rd / "runner.json", {"state": "starting", "claim": claim, "since": util.iso_now(),
                                             "since_ts": time.time(), "since_mono": time.monotonic()})
    _log(rd, f"in #{mid} from {who}: {text[:120]}")
    out = {"ok": True, "id": mid, "from": who, "engine": cfg["engine"], "next": "slop --json relay read --wait 200"}
    if claim:
        try:
            s = _start_runner(wd, rd, claim)
        except SlopError as e:
            return {**out, "ok": False, "error": str(e),
                    "text": f"message #{mid} saved, but the production did not start: {e}"}
        out.update(started=True, job=s["id"], text=f"message #{mid} passed on; the production started a turn "
                   f"(job {s['id']}). Next: slop --json relay read --wait 200")
    else:
        p = production(rd)
        out.update(started=False, queued=True, text=f"message #{mid} passed on; the production is busy "
                   f"({p.get('summary')}): the next turn picks it up. Next: slop --json relay read --wait 200")
    return out


def cmd_inbox(a) -> dict:
    _, rd = _dirs()
    with _lock(rd):
        st = _read_json(rd / "state.json")
        new = _pending(rd, st)
        if new:
            st["delivered"] = max(int(m["id"]) for m in new)
            _write_json(rd / "state.json", st)
    msgs = [{k: m.get(k) for k in ("id", "ts", "from", "text")} for m in new]
    if not msgs:
        return {"messages": [], "count": 0, "text": "no new messages"}
    text = "\n\n".join(f"#{m['id']} from the {m['from']} ({m['ts']}):\n{m['text']}" for m in msgs)
    return {"messages": msgs, "count": len(msgs), "text": text}


# ================================================================================================== say / ask / job
def _abs_file(f: str, *roots: Path) -> Path | None:
    p = Path(f).expanduser()
    cands = [p] if p.is_absolute() else [Path.cwd() / p] + [r / p for r in roots if r]
    hit = next((c for c in cands if c.is_file()), None)
    return hit.resolve() if hit else None


def _turn_no() -> int | None:
    t = os.environ.get("SLOP_RELAY_TURN") or ""
    return int(t) if t.isdigit() else None


def _post(a, kind: str) -> dict:
    wd, rd = _dirs()
    text = " ".join(a.text or [])
    if not text.strip():
        raise SlopError(f"nothing to {kind}: slop relay {kind} \"the words\" [--show FILE ...]")
    files, missing = [], []
    for f in a.show or []:
        hit = _abs_file(f, wd)
        (files.append(str(hit)) if hit else missing.append(f))
    if missing:
        raise SlopError(f"--show: no such file: {', '.join(missing)} (nothing was posted; give files that exist)")
    if not getattr(a, "as_is", False):
        bad = [(f, why) for f in files if (why := _video_issue(Path(f)))]
        if bad:
            f, why = bad[0]
            raise SlopError(f"{Path(f).name} is {why}: phones play it washed out or not at all, so nothing was posted. "
                            f"Show a phone copy: ffmpeg -i '{f}' -vf scale=out_range=tv,format=yuv420p -color_range tv "
                            "-c:v libx264 -crf 18 -preset medium -c:a aac -movflags +faststart '<name>-phone.mp4' "
                            "(or post it as it is with --as-is)")
    rec = {"ts": util.iso_now(), "t": round(time.time(), 3), "kind": kind, "text": text, "files": files,
           "turn": _turn_no()}
    if kind == "ask":
        rec["default"] = a.default
    with _lock(rd):
        oid = _next_id(rd / "outbox.jsonl")
        _append(rd / "outbox.jsonl", {"id": oid, "seq": _seq(rd), **rec})
    _log(rd, f"out #{oid} {kind}: {text[:120]}" + (f" (+{len(files)} files)" if files else ""))
    return {"id": oid, "kind": kind, "files": files,
            "text": f"posted #{oid} ({kind}{f', {len(files)} file(s)' if files else ''}): Grok shows it to the "
                    "director verbatim"}


def _video_issue(path: Path) -> str | None:
    """Why a video plays badly on phones (full range yuvj420p, 4:4:4, 10-bit), else None (ffprobe; unknown: None)."""
    if path.suffix.lower() not in VIDEO_EXT:
        return None
    import shutil
    exe = shutil.which("ffprobe")
    if not exe:
        return None
    try:
        r = subprocess.run([exe, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=pix_fmt,color_range",
                            "-of", "json", str(path)], capture_output=True, text=True, timeout=30)
        st = (json.loads(r.stdout or "{}").get("streams") or [{}])[0]
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    pix, rng = str(st.get("pix_fmt") or ""), str(st.get("color_range") or "")
    if not pix:
        return None
    if pix.startswith("yuvj") or rng == "pc":
        return f"full range ({pix}{', pc range' if rng == 'pc' else ''})"
    if pix not in ("yuv420p", "nv12"):
        return f"{pix} (phones play yuv420p)"
    return None


def cmd_say(a) -> dict:
    return _post(a, "say")


def cmd_ask(a) -> dict:
    return _post(a, "ask")


def _save_base(a, wd: Path) -> Path:
    """Where a job's downloads go by default: the production's project (-p / $SLOP_PROJECT / the folder it works in),
    else the projects folder; then inbox/<kind>/."""
    try:
        return resolve_project(getattr(a, "project", None))
    except SlopError:
        return wd


def _job_path(p: str | Path, base: Path, wd: Path) -> Path:
    """A path a job names. Relative: to the project, unless it already starts at the projects folder (the production
    works there, so `NAME/inbox` from it is the project's inbox, never NAME/NAME/inbox)."""
    q = Path(p).expanduser()
    if q.is_absolute():
        return q.absolute()
    via_wd, proj = (wd / q).absolute(), base.absolute()
    if proj != wd.absolute() and (via_wd == proj or proj in via_wd.parents):
        return via_wd
    return (base / q).absolute()


def _read_text(text: str | None, path: str | None, what: str) -> str | None:
    if path:
        if text:
            raise SlopError(f"give the {what} as text or as a file, not both")
        try:
            return Path(path).expanduser().read_text(encoding="utf-8").strip()
        except OSError as e:
            raise SlopError(f"cannot read {path}: {e}") from None
    return text


def _project_mj(base: Path) -> dict:
    try:
        mj = json.loads((base / "project.json").read_text(encoding="utf-8")).get("mj")
    except (OSError, ValueError, AttributeError):
        return {}
    return mj if isinstance(mj, dict) else {}


def cmd_job(a) -> dict:
    """(the production) ask Grok for browser work: Grok Imagine, Midjourney, Suno or any other site, all in Grok's own
    signed-in browser; --kind person only for what only a person can do (a sign-in Grok cannot finish)."""
    wd, rd = _dirs()
    base = _save_base(a, wd)
    rec: dict = {"kind": "job", "job_kind": a.kind, "what": a.what, "note": a.note}
    adjusted: list[str] = []
    if a.kind == "hedra":
        from .gen import hedra_relay
        base = resolve_project(getattr(a, "project", None))
        # Repeated posts reuse the open job; they never create a second generation.
        with _lock(rd):
            prior = next((j for j in _jobs(rd) if j.get("job_kind") == "hedra"
                          and j.get("project_dir") == str(base.resolve()) and j.get("clip") == a.clip), None)
            if prior:
                return {"job": prior["job"], "text": hedra_relay.instruction(prior)}
        rec.update(hedra_relay.prepare(base, a.clip, a.what))
    elif a.kind == "midjourney":
        if not a.text:
            raise SlopError("a midjourney job needs its prompts: --text '<one full prompt with its parameters>', once "
                            "per prompt (each becomes its own Midjourney job of four images)")
        if any(re.search(r"\{[^{}]*,[^{}]*\}", t.replace("\\,", "")) for t in a.text):
            raise SlopError("one prompt per --text: a {a, b} permutation block runs several Midjourney jobs; send each "
                            "Sheet A line as its own --text (plates/mj/BATCH.lines.txt)")
        plates_ = [p.strip() for p in (a.plate or []) if p.strip()]
        if plates_ and len(plates_) != len(a.text):
            raise SlopError(f"--plate: one per --text, in the same order ({len(a.text)} prompts, {len(plates_)} "
                            "plates)")
        # the person's Midjourney setup, whatever the prompt says: no --v (its default is its newest model), no
        # profile code (Grok presses the P button), --raw / --hd as they chose (project.json mj)
        from .board.plates import mj_line
        mj = _project_mj(base)
        texts = []
        for t in a.text:
            line, did = mj_line(t, mj)
            texts.append(line)
            adjusted += [d for d in did if d not in adjusted]
        pers = a.personalize or ("on" if mj.get("personalize", True) else "off")
        rec.update(text=texts, expect_count=4 * len(texts), personalize=pers == "on", plates=plates_ or None)
        for i, t in enumerate(texts, 1):             # Midjourney shortens long prompts (a "Long Prompt" badge)
            n_chars = len(t.split(" --")[0].strip())
            if n_chars > MJ_PROMPT_MAX:
                adjusted.append(f"prompt {i} is {n_chars} characters before its parameters: Midjourney shortens "
                                f"prompts over about {MJ_PROMPT_MAX}, so trim it and send the job again")
    elif a.kind == "suno":
        lyrics = _read_text(a.lyrics, a.lyrics_file, "lyrics")
        if not (a.style or "").strip():
            raise SlopError("a suno job needs --style '<the Style of Music field>'")
        if not (lyrics or "").strip() and not a.instrumental:
            raise SlopError("a suno job needs --lyrics / --lyrics-file, or --instrumental")
        rec.update(title=a.title, style=a.style, lyrics=lyrics, exclude=a.exclude, instrumental=bool(a.instrumental),
                   expect_count=2)
    elif a.kind == "browser":
        if not (a.note or "").strip():
            raise SlopError("a browser job needs --note '<what Grok should do there, in one or two sentences>'")
        rec.update(url=a.url, text=list(a.text or []))
    elif a.kind == "grok-imagine":
        if a.what not in ("still", "clip"):
            raise SlopError("--what still|clip: what Grok Imagine should make")
        prompt = a.prompt
        if a.prompt_file:
            if prompt:
                raise SlopError("give --prompt or --prompt-file, not both")
            try:
                prompt = Path(a.prompt_file).expanduser().read_text(encoding="utf-8").strip()
            except OSError as e:
                raise SlopError(f"cannot read {a.prompt_file}: {e}") from None
        if not (prompt or "").strip():
            raise SlopError("a grok-imagine job needs its prompt: --prompt TEXT or --prompt-file FILE")
        img = None
        if a.image:
            img = _abs_file(a.image, base, wd)
            if img is None:
                raise SlopError(f"--image: no such file: {a.image} (nothing was posted)")
        rec.update(prompt=prompt, image=str(img) if img else None, aspect=a.aspect, seconds=a.seconds)
        default_save = base / "inbox" / "grok-imagine"
    else:
        if not a.text and not a.note:
            raise SlopError("a person job needs its copy blocks (--text, once per block) or a --note saying what to do")
        rec.update(text=list(a.text or []), expect=[str(_job_path(e, base, wd)) for e in a.expect or []])
    if a.kind != "grok-imagine":
        default_save = base / "inbox" / a.kind
    save = _job_path(a.save, base, wd) if a.save else default_save.absolute()
    save.mkdir(parents=True, exist_ok=True)
    for e in rec.get("expect") or []:
        Path(e).parent.mkdir(parents=True, exist_ok=True)
    with _lock(rd):
        if a.kind == "hedra":
            prior = next((j for j in _jobs(rd) if j.get("job_kind") == "hedra"
                          and j.get("project_dir") == rec["project_dir"] and j.get("clip") == a.clip), None)
            if prior:
                return {"job": prior["job"], "text": hedra_relay.instruction(prior)}
        oid = _next_id(rd / "outbox.jsonl")
        jid = job_id(oid)
        if a.kind == "hedra":
            # Each job owns an immutable request snapshot; later quote attempts cannot overwrite it.
            request = _read_json(Path(rec["request_file"]))
            snapshot = base / "clips" / a.clip / f"hedra-relay-{jid}.json"
            _write_json(snapshot, request)
            rec["request_file"] = str(snapshot.resolve())
        rec.update(id=oid, seq=_seq(rd), job=jid, ts=util.iso_now(), t=round(time.time(), 3), save=str(save),
                   name=a.name or jid, files=[], turn=_turn_no())
        _append(rd / "outbox.jsonl", {k: v for k, v in rec.items() if v is not None})
    _log(rd, f"out #{oid} job {jid} ({a.kind}{' ' + a.what if a.what else ''})")
    who = ("Grok uses the Hedra MCP connector" if a.kind == "hedra" else
           "Grok gives it to the person" if a.kind == "person" else "Grok runs it in its own browser")
    extra = ""
    if a.kind == "midjourney":
        extra = (f" Personalization: {'on (Grok presses the P button)' if rec['personalize'] else 'off'}."
                 + (" The prompts follow the person's Midjourney setup: " + "; ".join(adjusted) + "." if adjusted
                    else ""))
    return {"id": oid, "job": jid, "save": str(save), "adjusted": adjusted,
            "text": f"posted job {jid} ({a.kind}): {who}; the result comes back as an inbox message "
                    f"(\"[grok] {jid} done: files ...\").{extra} End the turn now if nothing else can go on "
                    "meanwhile."}


def _open_job(rd: Path, jid: str) -> dict:
    jid = jid.strip().upper()
    if re.fullmatch(r"(?:J-?)?\d+", jid):
        jid = job_id(int(re.sub(r"\D", "", jid)))
    for j in _jobs(rd, open_only=False):
        if j.get("job") == jid:
            if j["status"] != "queued":
                raise SlopError(f"job {jid} is already {j['status']}")
            return j
    raise SlopError(f"no job {jid} (open jobs: {', '.join(x['job'] for x in _jobs(rd)) or 'none'})")


def _media_size(path: Path) -> str | None:
    """'1280x704' for a picture or a clip (ffprobe, else Pillow for pictures); None when unknown."""
    import shutil
    exe = shutil.which("ffprobe")
    if exe:
        try:
            r = subprocess.run([exe, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                                "-of", "csv=s=x:p=0", str(path)], capture_output=True, text=True, timeout=30)
            m = re.match(r"(\d+)x(\d+)", (r.stdout or "").strip())
            if m and int(m.group(1)) > 0 and int(m.group(2)) > 0:     # a broken file reads as 0x0: unknown
                return f"{m.group(1)}x{m.group(2)}"
        except (OSError, subprocess.SubprocessError):
            pass
    try:
        from PIL import Image
        with Image.open(path) as im:
            return f"{im.width}x{im.height}" if im.width and im.height else None
    except Exception:  # noqa: BLE001 - not a picture, or no Pillow
        return None


def _mj_provenance(j: dict, files: list[str], model: str | None) -> None:
    """Which prompt made each saved Midjourney image (and its plate, personalization and model):
    midjourney-prompts.json beside the images, so a picked image can always be traced back."""
    texts, plates = j.get("text") or [], j.get("plates") or []
    name = str(j.get("name") or j.get("job"))
    by_dir: dict[Path, dict] = {}
    for f in files:
        p = Path(f)
        k = None
        m = re.fullmatch(re.escape(name) + r"-(\d+)-\d+", p.stem)
        if m:
            k = int(m.group(1))
        elif plates:
            m2 = re.fullmatch(r"(.+)-\d+", p.stem)
            if m2 and m2.group(1) in plates:
                k = plates.index(m2.group(1)) + 1
        if k is None and len(texts) == 1:
            k = 1
        ok = bool(k) and k <= len(texts)
        idx = by_dir.setdefault(p.parent, _read_json(p.parent / "midjourney-prompts.json"))
        idx[p.name] = {"job": j["job"], "k": k if ok else None, "prompt": texts[k - 1] if ok else None,
                       "plate": plates[k - 1] if ok and k <= len(plates) else None,
                       "personalize": j.get("personalize"), "model": model, "saved": util.iso_now()}
    for d, idx in by_dir.items():
        _write_json(d / "midjourney-prompts.json", idx)


def _area(size: str) -> int:
    w, h = size.split("x")
    return int(w) * int(h)


def cmd_done(a) -> dict:
    """(Grok) a job's files are saved: mark it done and tell the production (a turn starts when it is idle)."""
    wd, rd = _dirs()
    j = _open_job(rd, a.job)
    if j.get("job_kind") == "hedra":
        raise SlopError("use relay hedra JOB --action quote|complete|failed so the clip and ledger stay in sync")
    files, missing = [], []
    for f in a.file or []:
        hit = _abs_file(f, Path(j.get("save") or wd), wd)
        (files.append(str(hit)) if hit else missing.append(f))
    if missing:
        raise SlopError(f"--file: no such file: {', '.join(missing)} (save the downloads into {j.get('save')} first)")
    if not files and not (j.get("job_kind") == "browser" and a.note):
        raise SlopError(f"name the saved files: slop --json relay done {j['job']} --file PATH [--file PATH ...]"
                        + (" (a browser job with no files: --note '<what you found or did>')"
                           if j.get("job_kind") == "browser" else ""))
    model = (getattr(a, "model", None) or "").strip() or None
    if j.get("job_kind") == "midjourney" and files:
        _mj_provenance(j, files, model)
    sizes = {f: s for f in files if (s := _media_size(Path(f)))}      # the real pixel size, for the production
    top = max((_area(s) for s in sizes.values()), default=0)
    small = [f for f, s in sizes.items() if _area(s) < 0.8 * top]
    text = (f"[grok] {j['job']} done: files " + ", ".join(files) if files else f"[grok] {j['job']} done") \
        + ("\nsizes: " + ", ".join(f"{Path(f).name} {s}" for f, s in sizes.items()) if sizes else "") \
        + (f"\nmodel: {model}" if model else "") + (f"\n{a.note}" if a.note else "")
    out = deliver(text, "grok", (j["job"], {"status": "done", "files": files, "sizes": sizes or None,
                                             "model": model, "ended": util.iso_now()}))
    out.update(job=j["job"], files=files, sizes=sizes,
               text=f"job {j['job']} done ({len(files)} file(s)"
                    + (f", {', '.join(sorted(set(sizes.values())))}" if sizes else "") + "); " + out["text"])
    if small:
        out["warn"] = (f"{', '.join(Path(f).name for f in small)} came out smaller than the rest: the page may have "
                       "rendered a lower resolution than it showed. Before the next Generate, switch the resolution "
                       "down and back up")
        out["text"] += "\nwarning: " + out["warn"]
    return out


def cmd_cancel(a) -> dict:
    """A job no one needs any more: closed as cancelled, never as failed. From the production: nothing goes back to
    it. From Grok (the person said so): the production hears it."""
    _, rd = _dirs()
    j = _open_job(rd, a.job)
    if j.get("job_kind") == "hedra":
        from .gen import hedra_relay
        with _lock(rd):
            hedra_relay.cancel(j)
    reason = (a.reason or "").strip()
    rec = {"status": "cancelled", "reason": reason or None, "ended": util.iso_now()}
    if os.environ.get("SLOP_RELAY_TURN"):              # the production's own job: it knows
        with _lock(rd):
            jobs = _read_json(rd / "jobs.json")
            jobs[j["job"]] = rec
            _write_json(rd / "jobs.json", jobs)
        _log(rd, f"job {j['job']} cancelled by the production" + (f": {reason}" if reason else ""))
        return {"job": j["job"], "status": "cancelled", "text": f"job {j['job']} cancelled: Grok will not run it"}
    out = deliver(f"[grok] {j['job']} cancelled" + (f": {reason}" if reason else ""), "grok", (j["job"], rec))
    out.update(job=j["job"], status="cancelled", text=f"job {j['job']} cancelled; " + out["text"])
    return out


def cmd_fail(a) -> dict:
    """(Grok) a job could not be done: mark it failed (or declined) and tell the production."""
    _, rd = _dirs()
    j = _open_job(rd, a.job)
    if j.get("job_kind") == "hedra":
        raise SlopError("use relay hedra JOB --action failed with the provider result; unknown outcomes stay open")
    status = "declined" if a.declined else "failed"
    text = (f"[grok] {j['job']} declined by the service (final for that image on that service): {a.reason}"
            if a.declined else f"[grok] {j['job']} failed: {a.reason}")
    out = deliver(text, "grok", (j["job"], {"status": status, "reason": a.reason, "ended": util.iso_now()}))
    out.update(job=j["job"], status=status, text=f"job {j['job']} {status}; " + out["text"])
    return out


# ================================================================================================== read / status
def _item(r: dict) -> dict:
    return {k: r.get(k) for k in ("id", "ts", "kind", "text", "default", "files", "turn", "auto")
            if r.get(k) is not None or k in ("id", "kind", "text", "files")}


def _render_item(r: dict) -> str:
    head = f"#{r['id']} {r['kind']}" + (" (the production's own words; it posted nothing)" if r.get("auto") else "")
    s = f"{head}: {r['text']}"
    if r.get("kind") == "ask" and r.get("default"):
        s += f"\n   (default: {r['default']})"
    for f in r.get("files") or []:
        s += f"\n   file: {f}"
    return s


JOB_FIELDS = ("id", "job", "job_kind", "what", "prompt", "image", "aspect", "seconds", "save", "name", "note", "text",
              "expect", "title", "style", "lyrics", "exclude", "instrumental", "url", "personalize", "plates",
              "expect_count", "project_dir", "clip", "take", "request_file", "fingerprint",
              "hedra_state", "provider_job_id", "status", "ts")
SKILL_FOR = {"grok-imagine": "grok-imagine", "midjourney": "midjourney", "suno": "suno"}


def _job_item(j: dict) -> dict:
    return {k: j.get(k) for k in JOB_FIELDS if j.get(k) not in (None, [], "")}


def _render_job(j: dict) -> str:
    s = f"job {j['job']} ({j.get('job_kind')}{', ' + j['what'] if j.get('what') else ''}): {j.get('status')}"
    for k in ("prompt", "image", "aspect", "seconds", "url", "title", "style", "exclude", "instrumental", "plates",
              "save", "name", "note", "clip", "request_file", "hedra_state", "provider_job_id"):
        if j.get(k) not in (None, "", [], False):
            s += f"\n   {k}: {', '.join(j[k]) if isinstance(j[k], list) else j[k]}"
    if j.get("lyrics"):
        s += "\n   lyrics:\n" + str(j["lyrics"])
    if j.get("job_kind") == "midjourney":
        s += f"\n   personalization (the P button): {'on' if j.get('personalize', True) else 'off'}"
    for i, block in enumerate(j.get("text") or [], 1):
        s += f"\n   copy block {i}:\n{block}"
    for e in j.get("expect") or []:
        s += f"\n   expect: {e}"
    return s


VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"}
MJ_PROMPT_MAX = 800                     # characters before the parameters (docs/50 §3: longer prompts get shortened)
LINK_OVER_B = 20 * 1024 * 1024          # bigger files (and every video) reach the person as a Drive link (skill drive)


def _by_link(f: str) -> bool:
    p = Path(f)
    try:
        return p.suffix.lower() in VIDEO_EXT or p.stat().st_size > LINK_OVER_B
    except OSError:
        return p.suffix.lower() in VIDEO_EXT


def _grok_next(items: list, prod: dict, jobs: list) -> str:
    steps = []
    if items:
        n, nf = len(items), sum(len(i.get("files") or []) for i in items)
        steps.append(("Post this message" if n == 1 else f"Post these {n} messages") + " verbatim"
                     + ((" with its files" if n == 1 else " with their files") if nf else ""))
        big = [f for i in items for f in i.get("files") or [] if _by_link(f)]
        if big:                                 # chat attachments often fail for videos: the person's Drive instead
            steps[-1] += (" (send " + ", ".join(Path(f).name for f in big) + " as Google Drive links: skill drive)")
    for j in jobs:
        k = j.get("job_kind")
        if k == "hedra":
            from .gen import hedra_relay
            steps.append(hedra_relay.instruction(j))
        elif k in SKILL_FOR or k == "browser":
            how = (f"skill {SKILL_FOR[k]}" if k in SKILL_FOR else
                   f"your browser at {j.get('url') or 'the page its note names'}, doing what its note says")
            if k == "midjourney":
                how += f", the P button {'on' if j.get('personalize', True) else 'off'}"
            steps.append(f"run job {j['job']} with {how} (save into {j.get('save')}, then `slop --json "
                         f"relay done {j['job']} --file PATH`, or `slop --json relay fail {j['job']} --reason '...'`)")
        else:
            steps.append(f"give job {j['job']} to the person (its copy blocks verbatim; save what they upload"
                         + (f" to {j['expect'][0]}" if j.get("expect") else f" into {j.get('save')}")
                         + f", then `slop --json relay done {j['job']} --file PATH`)")
    read = "`slop --json relay read --wait 200`"
    send = "`slop --json relay send '<their words>'`"
    s = prod.get("state")
    if s == "working":
        if not steps:
            steps.append(f"Nothing new yet ({prod.get('summary')}). Post one status line and \"Say continue\"")
        steps.append(read)
    elif s == "waiting":
        steps.append(f"wait for the person's answer and pass it verbatim with {send}")
    elif s == "failed":
        err = str(prod.get("error") or "")
        fix = ("its sign-in was rejected: `slop agents status` shows the fix" if SIGNIN_RE.search(err) else
               "the plan's usage limit is reached: wait for the reset" if LIMIT_RE.search(err) else
               "details: `slop --json relay log`")
        steps.append(f"tell the person in one line that the production stopped ({err[:160]}; {fix}); after the fix, "
                     "`slop --json relay send 'continue' --from grok` runs the waiting messages again")
    elif s == "queued":
        steps.append("run `slop --json relay send 'continue' --from grok` (messages wait, but no turn runs)")
    elif s == "not set up":
        steps.append("run `slop --json relay setup` first")
    else:
        steps.append(f"wait for the person's next words and pass them verbatim with {send}")
    out = steps[0][0].upper() + steps[0][1:]
    for st in steps[1:]:
        out += ", then " + st
    return out + "."


def _snapshot(rd: Path) -> tuple:
    st = _read_json(rd / "state.json")
    outbox = _rows(rd / "outbox.jsonl")
    prod = production(rd)
    q = len(_jobs(rd))
    new = [r for r in outbox if int(r.get("id") or 0) > int(st.get("read") or 0)]
    sig = (prod.get("state"), q, len(outbox))
    return new, prod, q, sig


def cmd_read(a) -> dict:
    _, rd = _dirs()
    wait = max(0.0, min(float(a.wait or 0), WAIT_CAP_S))
    t0 = time.monotonic()
    calm = 0
    if wait > 0:                                      # Grok is waiting: the waker leaves the news to this read
        _write_json(rd / "reader.json", {"pid": os.getpid(), "until_m": time.monotonic() + wait + 3,
                                         "since": util.iso_now()})
    while True:
        # the wait holds its full time unless there is something for Grok: a new item, an open job, or a production
        # that stopped working (waiting, idle, failed) and stays stopped - a blip in its state never ends a wait
        new, prod, q, _sig = _snapshot(rd)
        left = wait - (time.monotonic() - t0)
        if not new and not q and left > 0:
            calm = calm + 1 if prod.get("state") != "working" else 0
            if calm < READ_SETTLE:
                time.sleep(0.4)
                continue
        with _lock(rd):                               # take the new items and mark them read in one step
            st = _read_json(rd / "state.json")
            rows = _rows(rd / "outbox.jsonl")
            new = [r for r in rows if int(r.get("id") or 0) > int(st.get("read") or 0)]
            if new:
                st["read"] = max(int(r["id"]) for r in new)
                _write_json(rd / "state.json", st)
        if new or _jobs(rd) or wait - (time.monotonic() - t0) <= 0 or production(rd).get("state") != "working":
            break
        calm = 0                                      # a misread, nothing new after all: keep waiting
    if wait > 0:
        _write_json(rd / "reader.json", {"pid": os.getpid(), "until_m": 0, "last": util.iso_now()})
    shown = [r for r in (rows if a.all else new) if r.get("kind") in ("say", "ask")]
    items = [_item(r) for r in shown]
    prod = production(rd)
    jobs = [_job_item(j) for j in _jobs(rd)]
    nxt = _grok_next(items, prod, jobs)
    lines = [_render_item(r) for r in shown] or ["(no new messages from the production)"]
    lines += [_render_job(j) for j in jobs]
    lines.append(f"production: {prod.get('summary')}")
    if prod.get("state") == "failed" and prod.get("log_tail"):
        lines.append("  log tail:\n" + "\n".join("    " + ln for ln in prod["log_tail"].splitlines()))
    lines.append(f"grok_next: {nxt}")
    try:
        from .update import reminder
        upd = reminder()                              # once per new release, one network call a day at most
    except Exception:  # noqa: BLE001 - a reminder never breaks the relay
        upd = None
    if upd:
        lines.append(f"update: {upd['line']} (add this line once at the end of your reply)")
    return {"items": items, "count": len(items), "new": len(new), "jobs": jobs, "production": prod,
            "waited_s": round(time.monotonic() - t0, 2), "grok_next": nxt, **({"update": upd} if upd else {}),
            "text": "\n".join(lines)}


def cmd_status(a) -> dict:
    wd, rd = _dirs()
    cfg = _cfg(rd, need=False)
    st = _read_json(rd / "state.json")
    prod = production(rd)
    inbox, outbox = _rows(rd / "inbox.jsonl"), _rows(rd / "outbox.jsonl")
    unread = sum(1 for r in outbox if int(r.get("id") or 0) > int(st.get("read") or 0))
    jobs = _jobs(rd)
    eng = cfg.get("engine")
    sess = (st.get("sessions") or {}).get(eng) if eng else None
    lines = [f"relay: production {prod.get('summary')}",
             f"  engine: {eng or 'not set up'}" + (f" ({cfg.get('model')})" if cfg.get("model") else "")
             + (f", session {sess}" if sess else "") + f"; working in {wd}",
             f"  inbox: {len(inbox)} message(s), {prod.get('pending', 0)} not yet read by the production",
             f"  outbox: {len(outbox)} item(s), {unread} not yet shown",
             f"  turns: {st.get('turns', 0)}; open jobs: {', '.join(j['job'] for j in jobs) or 'none'}"]
    eff = effort_for(eng, rd) if eng in ENGINES else (None, "")
    if eng in ENGINES:
        lines.insert(2, f"  effort: {eff[0] or 'the engine default'} ({eff[1]}); `slop relay effort` changes it")
    wk = _read_json(rd / "wake.json")
    lines.insert(3, "  wake-ups: " + (f"on ({_mask_url(wk.get('url'))})" + ("" if os.environ.get(WAKE_KEY_ENV) else
                                                                          f", no ${WAKE_KEY_ENV}")
                                     if wk.get("url") else "off (Grok hears only while it waits; slop relay wake)"))
    return {"production": prod, "engine": eng, "model": cfg.get("model"), "effort": eff[0], "session": sess,
            "turns": st.get("turns", 0),
            "inbox": len(inbox), "outbox": len(outbox), "unread": unread, "jobs": [_job_item(j) for j in jobs],
            "work_dir": str(wd), "relay_dir": str(rd), "text": "\n".join(lines)}


def cmd_effort(a) -> dict:
    """How hard the production thinks, per engine: Claude Code's --effort, Codex's reasoning effort. No level: what
    each engine uses and the levels it offers; a level: set it for the next turns ('default' = xhigh again, 'auto' =
    the engine decides)."""
    from .agents import engines as E
    wd, rd = _dirs()
    cfg = _cfg(rd, need=False)
    eng = E.norm_engine(a.engine) if a.engine else (cfg.get("engine") if cfg.get("engine") in ENGINES else "claude")
    if eng not in ENGINES:
        raise SlopError(f"--engine claude or codex (the production's engines), not {a.engine}")
    levels, src = effort_levels(eng)
    changed = None
    if a.level:
        lv = a.level.strip().lower()
        if lv not in ("default", "auto"):
            if not re.fullmatch(r"[a-z]{2,16}", lv):
                raise SlopError(f"an effort level is one word ({', '.join(levels)}), or default, or auto")
            if src == "claude --help" and lv not in levels:
                raise SlopError(f"Claude Code offers {', '.join(levels)} (from claude --help), not {lv}")
        with _lock(rd):
            data = _read_json(rd / "effort.json")
            if lv == "default":
                data.pop(eng, None)
            else:
                data[eng] = lv
            for k in ("rejected", "rejected_why"):
                (data.get(k) or {}).pop(eng, None)
            _write_json(rd / "effort.json", data)
        changed = lv
        _log(rd, f"effort: {eng} set to {lv}")
    data = _read_json(rd / "effort.json")
    engines = {}
    lines = []
    for e in ENGINES:
        cur, where = effort_for(e, rd)
        engines[e] = {"effort": cur or "auto", "source": where}
        title = E.SPEC[e]["title"]
        lines.append(f"{title} effort: {cur or 'the engine decides (auto)'} ({where})"
                     + (" - the relay runs this engine" if e == cfg.get("engine") else ""))
        why = (data.get("rejected_why") or {}).get(e)
        if why:
            lines.append(f"  {(data.get('rejected') or {}).get(e)} was turned down: {why[:160]}")
        if os.environ.get(EFFORT_ENV[e]):
            lines.append(f"  ${EFFORT_ENV[e]} sets it; `slop relay effort` changes nothing while it is set")
    lines.append(f"levels for {E.SPEC[eng]['title']}: {', '.join(levels)} ({src}); higher = better work, slower, more "
                 "of the plan's usage; default = xhigh; auto = the engine decides")
    if changed:
        lines.insert(0, f"effort for {E.SPEC[eng]['title']} set to {changed}: it applies from the production's next "
                        "turn")
    return {"engine": eng, "effort": engines[eng]["effort"], "levels": levels, "levels_from": src,
            "default": EFFORT_DEFAULT, "engines": engines, "changed": changed, "text": "\n".join(lines)}


def cmd_log(a) -> dict:
    _, rd = _dirs()
    tail = _tail(rd / "relay.log", max(1, int(a.lines)))
    tj = _read_json(rd / "turn.json")
    err = _tail(rd / "turns" / f"turn-{int(tj.get('n') or 0):04d}.err", 15) if tj.get("n") else ""
    text = tail or f"(the log {rd / 'relay.log'} is empty)"
    if err.strip():
        text += f"\n--- stderr of turn {tj.get('n')} ---\n{err}"
    return {"log": str(rd / "relay.log"), "tail": tail, "stderr_tail": err, "text": text}


def cmd_stop(a) -> dict:
    _, rd = _dirs()
    r = _runner(rd)
    if not r["alive"]:
        return {"stopped": False, "text": "the production is not working; nothing to stop"}
    util.atomic_write_text(rd / "stop", util.iso_now() + "\n")
    from . import job
    jid = r.get("job_id")
    if jid:
        try:
            path, rec = job.find_job(jid, None)
            job.stop_job(path, rec, grace=float(a.grace))
        except SlopError:
            jid = None
    if not jid and r.get("pid"):
        import signal
        job._signal_group({"pid": r.get("pid"), "pid_start": r.get("pid_start")},
                          signal.SIGTERM if os.name != "nt" else 0)
    with _lock(rd):
        _write_json(rd / "runner.json", {"state": "stopped", "since": util.iso_now(), "since_ts": time.time(),
                                         "job_id": r.get("job_id")})
        tj = _read_json(rd / "turn.json")
        if tj.get("state") == "running":
            tj.update(state="stopped", ended=util.iso_now())
            _write_json(rd / "turn.json", tj)
    _log(rd, "stopped by `relay stop`")
    return {"stopped": True, "job": r.get("job_id"),
            "text": "the production is stopped. The person's next words (`relay send`) start a new turn."}


# ================================================================================================== the supervisor
def _prompt(wd: Path, cfg: dict, n: int, msgs: list[dict], prev_err: dict | None) -> str:
    brief = BRIEF_FILES.get(cfg.get("engine"), "CLAUDE.md")
    read_it = "read it now if this session has not"
    try:                                              # an update rewrites the brief: a resumed session reads it again
        import hashlib
        sha = hashlib.sha1((wd / brief).read_bytes()).hexdigest()
        mark = relay_dir() / "brief.sha"
        old = mark.read_text(encoding="utf-8").strip() if mark.is_file() else None
        if old != sha:
            if old:
                read_it = "it changed since you last read it: read it again now"
            util.atomic_write_text(mark, sha + "\n")
    except OSError:
        pass
    lines = [f"[slop relay] Production turn {n}. You work in {wd.as_posix()} (the projects folder).",
             f"You are the production; your brief is {brief} in this folder ({read_it}).", ""]
    if prev_err:
        lines += [f"Note: turn {prev_err.get('turn')} ended with an error ({str(prev_err.get('error'))[:300]}). It may "
                  "have done part of the work: check before redoing it.", ""]
    lines.append("New messages (verbatim, oldest first):")
    for m in msgs:
        who = {"director": "the director", "grok": "Grok (the relay)"}.get(m.get("from"), str(m.get("from")))
        lines += ["", f"--- message #{m['id']} from {who} ({m.get('ts')}) ---", str(m.get("text")),
                  f"--- end of message #{m['id']} ---"]
    lines += ["", "The director sees ONLY what you post with `slop relay say \"...\" --show FILE` or `slop relay ask "
              "\"...\" --default X --show FILE`; your replies here reach no one. Run `slop relay inbox` between steps "
              "for new messages. End the turn when you wait for the director or for a job."]
    return "\n".join(lines) + "\n"


def _summ(inp) -> str:
    if not isinstance(inp, dict):
        return ""
    v = inp.get("command") or inp.get("file_path") or inp.get("path") or inp.get("pattern") or inp.get("url") \
        or inp.get("query") or inp.get("description") or inp.get("prompt") or ""
    return " ".join(str(v).split())[:140]


def _parse_claude(ev: dict, ps: dict) -> str | None:
    t = ev.get("type")
    if t == "system" and ev.get("subtype") == "init":
        ps["session"] = ev.get("session_id") or ps.get("session")
        mcp = {m.get("name"): m.get("status") for m in ev.get("mcp_servers") or [] if isinstance(m, dict)}
        return f"started ({ev.get('model')}; claudia MCP {mcp.get(MCP_NAME) or 'missing'})"
    if t == "assistant":
        line = None
        for b in (ev.get("message") or {}).get("content") or []:
            if b.get("type") == "tool_use":
                line = f"{b.get('name')} {_summ(b.get('input'))}".strip()
            elif b.get("type") == "text" and str(b.get("text") or "").strip():
                ps["text"] = str(b["text"])
                line = line or "wrote: " + " ".join(str(b["text"]).split())[:140]
        return line
    if t == "result":
        ps["final"] = ev.get("subtype") or "success"
        ps["is_error"] = bool(ev.get("is_error")) or ps["final"] != "success"
        res = str(ev.get("result") or "")
        if res.strip():
            ps["text"] = res
        if ps["is_error"]:
            ps["error"] = res[:600] or ps["final"]
        return f"turn ended ({ps['final']}{', ERROR' if ps['is_error'] else ''}, {ev.get('num_turns')} steps)"
    if t == "rate_limit_event" and (ev.get("rate_limit_info") or {}).get("status") == "rejected":
        return "usage limit reached"
    return None


def _parse_codex(ev: dict, ps: dict) -> str | None:
    t = ev.get("type")
    if t == "thread.started":
        ps["session"] = ev.get("thread_id") or ps.get("session")
        return "started"
    if t in ("item.started", "item.completed"):
        it = ev.get("item") or {}
        k = it.get("type")
        if k == "command_execution" and t == "item.started":
            return "run " + " ".join(str(it.get("command")).split())[:140]
        if k == "mcp_tool_call" and t == "item.started":
            return f"mcp {it.get('server')}.{it.get('tool')}"
        if k == "agent_message" and t == "item.completed":
            ps["text"] = str(it.get("text") or "")
            return "wrote: " + " ".join(ps["text"].split())[:140]
        if k == "file_change" and t == "item.completed":
            return "files " + ", ".join(f"{c.get('kind')} {c.get('path')}" for c in it.get("changes") or [])[:160]
    if t == "turn.completed":
        ps["final"], ps["is_error"] = "success", False
        return "turn ended"
    if t in ("turn.failed", "error"):
        e = ev.get("error") if t == "turn.failed" else ev
        msg = e.get("message") if isinstance(e, dict) else str(e)
        ps.update(final="error", is_error=True, error=str(msg)[:600])
        return f"error: {str(msg)[:160]}"
    return None


def engine_argv(eng: str, base: list[str], prompt_arg: str, prompt: str, model: str | None, session: str | None,
                wd: Path, effort: str | None = None) -> tuple[list[str], str | None]:
    """(argv, stdin text) of one production turn."""
    if eng == "claude":
        argv = base + ["-p", prompt_arg, "--output-format", "stream-json", "--verbose", "--permission-mode",
                       "bypassPermissions"]
        if model:
            argv += ["--model", model]
        if effort:
            argv += ["--effort", effort]
        if session:
            argv += ["--resume", session]
        return argv, None
    common = ["--json", "--skip-git-repo-check", "-c", 'forced_login_method="chatgpt"',
              "-c", 'sandbox_mode="danger-full-access"', "-c", 'approval_policy="never"',
              "-c", "shell_environment_policy.ignore_default_excludes=true"]   # keep the toolkit's keys for its commands
    if model:
        common += ["-m", model]
    if effort:
        common += ["-c", f'model_reasoning_effort="{effort}"']
    if session:                                       # `exec resume` takes no -C: the turn runs in wd anyway
        return base + ["exec", "resume", *common, session, "-"], prompt
    return base + ["exec", *common, "-C", str(wd), "-"], prompt


def effort_levels(eng: str) -> tuple[list[str], str]:
    """The effort levels the engine offers -> (levels, where from). Claude Code lists them in its own help, so a new
    level shows up the day it ships; Codex does not list them: the usual ones (it may take more, e.g. on newer models)."""
    if eng == "claude":
        from .agents import engines as E
        try:
            rc, out, err = E.run_cli("claude", ["--help"], timeout=30)
        except Exception:                                   # noqa: BLE001 - no help: the usual levels
            rc, out = 1, ""
        m = re.search(r"--effort\b.{0,240}?\(([a-z]+(?:,\s*[a-z]+)+)\)", out or "", re.S)
        if rc == 0 and m:
            return [x.strip() for x in m.group(1).split(",")], "claude --help"
    return list(EFFORT_USUAL.get(eng, ())), "the usual levels"


def effort_for(eng: str, rd: Path) -> tuple[str | None, str]:
    """(the level a turn passes, or None for the engine's own default; where it came from):
    $SLOP_CLAUDE_EFFORT / $SLOP_CODEX_EFFORT, else the person's `slop relay effort`, else xhigh. A level the engine
    turned down (recorded by a turn) is not passed again until a new level is set."""
    env = os.environ.get(EFFORT_ENV.get(eng, ""), "").strip().lower()
    if env:
        return (None if env == "auto" else env), EFFORT_ENV[eng]
    data = _read_json(rd / "effort.json")
    lv = str(data.get(eng) or "").strip().lower() or EFFORT_DEFAULT
    if lv == "auto":
        return None, "set to auto"
    if (data.get("rejected") or {}).get(eng) == lv:
        return None, f"{lv} was turned down by the engine"
    return lv, ("slop relay effort" if data.get(eng) else "default")


def _engine_run(wd: Path, rd: Path, cfg: dict, n: int, prompt: str, session: str | None, msgs: list[dict],
                attempt: int = 1, effort: str | None = "") -> dict:
    from .agents import engines as E
    eng = cfg["engine"]
    b = E.find(eng)
    if not b:
        return {"ok": False, "error": f"{E.SPEC[eng]['title']} is not installed: slop agents install {eng}",
                "session": session}
    tdir = rd / "turns"
    tdir.mkdir(parents=True, exist_ok=True)
    stem = f"turn-{n:04d}" + (f"-{attempt}" if attempt > 1 else "")
    prompt_arg = prompt
    if len(prompt) > PROMPT_ARG_MAX:
        pf = tdir / f"{stem}.prompt.md"
        util.atomic_write_text(pf, prompt)
        prompt_arg = f"Read the file {pf.as_posix()} and do what it says."
    if effort == "":                                  # "" = the setting; None = the engine's own default
        effort = effort_for(eng, rd)[0]
    argv, stdin_text = engine_argv(eng, b["argv"], prompt_arg, prompt, cfg.get("model"), session, wd, effort)
    shim = _shim(rd)
    pp = os.environ.get("PYTHONPATH", "")
    root = str(toolkit_root())
    env = E.base_env(eng, plan_only=True, extra={
        "SLOP_RELAY_TURN": str(n), "PYTHONUNBUFFERED": "1",
        "PYTHONPATH": root + (os.pathsep + pp if pp and root not in pp.split(os.pathsep) else "")})
    for k in JOB_ENV:
        env.pop(k, None)
    for k in E.TOOLKIT_SECRETS:       # the production is the spender: each paid step asks --yes, its gate and its caps
        if os.environ.get(k):
            env[k] = os.environ[k]
    env["PATH"] = str(shim) + os.pathsep + env.get("PATH", "")
    ps: dict = {"session": session, "final": None, "is_error": False, "error": None, "text": ""}
    t0 = time.time()
    tj = {"n": n, "attempt": attempt, "state": "running", "engine": eng, "effort": effort, "started": util.iso_now(),
          "started_ts": round(t0, 3), "messages": [m["id"] for m in msgs], "session": session, "pid": None,
          "last": "starting", "last_at": util.iso_now()}
    kw = {"creationflags": 0x08000000} if os.name == "nt" else {}       # CREATE_NO_WINDOW
    max_s = float(os.environ.get("SLOP_RELAY_TURN_MAX_S") or 4 * 3600)
    with open(tdir / f"{stem}.err", "ab") as ef, open(tdir / f"{stem}.jsonl", "ab") as rf:
        try:
            p = subprocess.Popen(argv, cwd=str(wd), env=env, stdout=subprocess.PIPE, stderr=ef,
                                 stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL, **kw)
        except OSError as e:
            return {"ok": False, "error": f"could not start {eng}: {e}", "session": session}
        tj["pid"] = p.pid
        _write_json(rd / "turn.json", tj)
        _log(rd, f"turn {n}: {eng} started (pid {p.pid}" + (f", resuming {session}" if session else ", new session")
             + f") with message(s) {', '.join('#' + str(m['id']) for m in msgs)}")
        if stdin_text is not None:
            def feed():
                try:
                    p.stdin.write(stdin_text.encode("utf-8"))
                    p.stdin.close()
                except OSError:
                    pass
            threading.Thread(target=feed, daemon=True).start()
        timer = threading.Timer(max_s, lambda: (ps.update(timeout=True), p.kill()))
        timer.daemon = True
        timer.start()
        last_w = 0.0
        for raw in p.stdout:
            raw = raw.replace(b"\r\n", b"\n")
            rf.write(raw if raw.endswith(b"\n") else raw + b"\n")
            rf.flush()
            try:
                ev = json.loads(raw.decode("utf-8", "replace"))
            except ValueError:
                continue
            if not isinstance(ev, dict):
                continue
            line = _parse_claude(ev, ps) if eng == "claude" else _parse_codex(ev, ps)
            tj["session"] = ps.get("session") or tj.get("session")
            if line:
                _log(rd, f"turn {n}: {line}")
                tj.update(last=line, last_at=util.iso_now())
                if time.monotonic() - last_w > 0.5:
                    _write_json(rd / "turn.json", tj)
                    last_w = time.monotonic()
        rc = p.wait()
        timer.cancel()
    ok = rc == 0 and ps.get("final") is not None and not ps.get("is_error")
    err = None
    if not ok:
        etail = _tail(tdir / f"{stem}.err", 3).replace("\n", " ")[-300:]
        err = (f"the turn took longer than {max_s:g} s and was stopped" if ps.get("timeout") else
               ps.get("error") or (f"{eng} exited with code {rc}" + (f": {etail}" if etail else "")))
    tj.update(state="done" if ok else "failed", ended=util.iso_now(), elapsed_s=round(time.time() - t0, 1), exit=rc,
              error=err, session=ps.get("session"))
    _write_json(rd / "turn.json", tj)
    return {"ok": ok, "error": err, "session": ps.get("session"), "text": ps.get("text") or "", "exit": rc,
            "elapsed_s": tj["elapsed_s"], "effort": effort}


def _turn(wd: Path, rd: Path, cfg: dict, n: int, msgs: list[dict], prev_err: dict | None,
          session: str | None) -> dict:
    prompt = _prompt(wd, cfg, n, msgs, prev_err)
    res = _engine_run(wd, rd, cfg, n, prompt, session, msgs)
    if not res["ok"] and session and NO_SESSION_RE.search(str(res.get("error") or "")):
        _log(rd, f"turn {n}: the saved session {session} is gone; starting a new session")
        session = None
        res = _engine_run(wd, rd, cfg, n, prompt, None, msgs, attempt=2)
    lv = res.get("effort")
    if (not res["ok"] and lv and float(res.get("elapsed_s") or 0) < EFFORT_FAST_S
            and EFFORT_RE.search(str(res.get("error") or ""))):
        eng = cfg["engine"]                             # the engine (or its model) does not take this level
        _log(rd, f"turn {n}: {eng} did not take effort {lv} ({str(res.get('error'))[:160]}); running at its own "
                 "default; `slop relay effort` picks another level")
        with _lock(rd):
            data = _read_json(rd / "effort.json")
            data.setdefault("rejected", {})[eng] = lv
            data.setdefault("rejected_why", {})[eng] = str(res.get("error") or "")[:300]
            _write_json(rd / "effort.json", data)
        res = _engine_run(wd, rd, cfg, n, prompt, session, msgs, attempt=3, effort=None)
    return res


def _mask_url(url: str | None) -> str:
    from urllib.parse import urlsplit
    u = urlsplit(url or "")
    return f"{u.scheme}://{u.hostname}/...{(u.path or '')[-4:]}" if u.scheme and u.hostname else ""


def _wake_url(text: str) -> tuple[str, bool]:
    """The routine's webhook URL from what Grok passes -> (url, built). Its POST to address as pasted ("POST to
    https://...", quotes, a trailing dot); or Grok's own link to the routine (grokbot://app/v1/agent?...&automation=ID,
    or the routine's id alone): the app builds the URL as <backend>/automations/webhook/<id>, and so does this
    ($CLAUDIA_WAKE_BASE overrides the backend)."""
    from urllib.parse import quote, urlsplit
    text = (text or "").strip()
    m = re.search(r"https?://[^\s\"'<>`]+", text)
    url = m.group(0).rstrip(".,;:)]}") if m else ""
    rid = None
    if "/automations/webhook/" not in url:
        hit = re.search(r"[?&#;]automation(?:Id|_id)?=([A-Za-z0-9_-]{4,128})", text)
        rid = hit.group(1) if hit else (text if re.fullmatch(r"[A-Za-z0-9_-]{8,128}", text) else None)
    if rid:
        base = os.environ.get("CLAUDIA_WAKE_BASE", "").strip().rstrip("/") or WAKE_BASE
        url = f"{base}/automations/webhook/{quote(rid, safe='')}"
    u = urlsplit(url)
    local = u.hostname in ("127.0.0.1", "localhost", "::1")
    if not u.hostname or not (u.scheme == "https" or (u.scheme == "http" and local)):
        raise SlopError("give your link to the routine (it carries automation=...), or its POST to address "
                        "(https://...), or say off or test")
    return url, bool(rid)


def _wake_key() -> str:
    """$CLAUDIA_WAKE_KEY: the routine's key, or its whole Authorization header line (both are offered to copy)."""
    k = os.environ.get(WAKE_KEY_ENV, "").strip().strip("\"'`")
    k = re.sub(r"(?i)^authorization\s*:\s*", "", k)
    return re.sub(r"(?i)^bearer\s+", "", k).strip()


def _reader_active(rd: Path) -> bool:
    r = _read_json(rd / "reader.json")
    return float(r.get("until_m") or 0) > time.monotonic() and _alive(r.get("pid"))


def wake_send(rd: Path, event: str, unread: list[dict] | None = None) -> dict:
    """POST to the wake-up routine's webhook, so Grok starts a run that reads the relay. The body names the kind of
    news only, never its words; the key comes from $CLAUDIA_WAKE_KEY and is never printed. -> {ok, status, error}"""
    import urllib.error
    import urllib.request
    cfg = _read_json(rd / "wake.json")
    if not cfg.get("url"):
        return {"ok": False, "status": None, "error": "wake-ups are off (slop relay wake URL)"}
    unread = unread or []
    body = json.dumps({"source": "claudia-relay", "event": event, "unread": len(unread),
                       "kinds": sorted({str(r.get("kind")) for r in unread if r.get("kind")}),
                       "production": production(rd).get("state")}).encode("utf-8")
    req = urllib.request.Request(cfg["url"], data=body, method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": "claudia-relay"})
    key = _wake_key()
    if key:
        req.add_header("Authorization", f"Bearer {key}")
    status, err = None, None
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            status = resp.status
    except urllib.error.HTTPError as e:
        status = e.code
    except (urllib.error.URLError, OSError, ValueError) as e:
        err = str(getattr(e, "reason", None) or e)[:200]
    ok = status is not None and 200 <= status < 300
    err = None if ok else (err or f"HTTP {status}" + (" (is the key in the secure secret card "
                                                       f"{WAKE_KEY_ENV}?)" if status in (401, 403) else ""))
    if err and cfg.get("built") and status not in (401, 403):
        err += ("; the URL was built from the routine's id: ask the person for the routine's POST to address "
                "(Webhook URL) and run `slop --json relay wake '<what they pasted>'`")
    cfg = _read_json(rd / "wake.json")
    cfg["last"] = {"at": util.iso_now(), "event": event, "unread": len(unread), "ok": ok, "status": status,
                   "error": err}
    _write_json(rd / "wake.json", cfg)
    _log(rd, f"wake: {event} ({len(unread)} unread) -> {'ok ' + str(status) if ok else err}")
    return {"ok": ok, "status": status, "error": err}


class _Waker(threading.Thread):
    """In the supervisor: wakes Grok when the production posted something Grok has not read and Grok is not waiting
    in `relay read --wait`, once per burst of posts; and when a turn failed. The same for Claude Code and Codex: it
    watches the relay's outbox, not the engine. Never takes the relay lock (its POST may take seconds)."""

    def __init__(self, rd: Path):
        super().__init__(daemon=True, name="relay-waker")
        self.rd, self.halt = rd, threading.Event()
        self.newest, self.changed = -1, time.monotonic()
        self.fails, self.retry_at = 0, 0.0

    def run(self) -> None:
        while not self.halt.wait(WAKE_TICK_S):
            try:
                self.tick()
            except Exception as e:  # noqa: BLE001 - a wake-up never breaks the production
                _log(self.rd, f"wake: error {e}")

    def finish(self, event: str | None, turn: int | None = None) -> None:
        self.halt.set()
        self.join(timeout=WAKE_TICK_S + 12)
        if event:
            try:
                self.tick(final=event, turn=turn)
            except Exception as e:  # noqa: BLE001
                _log(self.rd, f"wake: error {e}")

    def tick(self, final: str | None = None, turn: int | None = None) -> None:
        cfg = _read_json(self.rd / "wake.json")
        if not cfg.get("url"):
            return
        rows = _rows(self.rd / "outbox.jsonl")
        newest = max((int(r.get("id") or 0) for r in rows), default=0)
        now = time.monotonic()
        if newest != self.newest:
            self.newest, self.changed = newest, now
        if _reader_active(self.rd):
            return                                    # Grok is waiting in relay read: it gets the news itself
        read = int(_read_json(self.rd / "state.json").get("read") or 0)
        unread = [r for r in rows if int(r.get("id") or 0) > read]
        fresh = bool(unread) and newest > int(cfg.get("woken_id") or 0)
        failed = final == "failed" and turn is not None and cfg.get("woken_failed") != turn
        if not (fresh or failed):
            return
        if final is None and (now - self.changed < WAKE_QUIET_S or now < self.retry_at):
            return                                    # it may post more (a say, then an ask), or a retry comes later
        r = wake_send(self.rd, final or "posted", unread)
        cfg = _read_json(self.rd / "wake.json")
        if r["ok"] or final or self.fails >= len(WAKE_RETRY_S):
            cfg["woken_id"] = max(newest, int(cfg.get("woken_id") or 0))
            if failed:
                cfg["woken_failed"] = turn
            self.fails, self.retry_at = 0, 0.0
        else:
            self.retry_at = now + WAKE_RETRY_S[self.fails]
            self.fails += 1
        _write_json(self.rd / "wake.json", cfg)


def cmd_wake(a) -> dict:
    """The wake-up routine: Grok's webhook, called when the production posts while Grok is not waiting. No argument:
    the setting; a URL: turn wake-ups on; off; test (one wake-up now)."""
    _, rd = _dirs()
    arg = (a.url or "").strip()
    head = None
    if arg.lower() == "off":
        cfg = _read_json(rd / "wake.json")
        cfg.pop("url", None)
        _write_json(rd / "wake.json", cfg)
        head = "wake-ups are off: Grok hears from the production only while it waits"
        _log(rd, "wake: off")
    elif arg.lower() == "test":
        r = wake_send(rd, "test")
        head = ("test wake-up sent: the routine should run once and find nothing new" if r["ok"] else
                f"test wake-up FAILED: {r['error']}")
        if not r["ok"] and not _read_json(rd / "wake.json").get("url"):
            raise SlopError(r["error"])
    elif arg:
        url, built = _wake_url(arg)
        rows = _rows(rd / "outbox.jsonl")
        cfg = _read_json(rd / "wake.json")
        cfg.update(url=url, built=built, set=util.iso_now(),
                   woken_id=max((int(r.get("id") or 0) for r in rows), default=0))
        _write_json(rd / "wake.json", cfg)
        head = (f"wake-ups on: {_mask_url(url)}" + (" (built from the routine's id)" if built else "")
                + "; next: the key in the secure card, then slop --json relay wake test")
        _log(rd, f"wake: on ({_mask_url(url)})")
    cfg = _read_json(rd / "wake.json")
    on, key = bool(cfg.get("url")), bool(_wake_key())
    last = cfg.get("last") or {}
    lines = ([head] if head else []) + [
        "wake-ups: " + (f"on ({_mask_url(cfg.get('url'))})" if on else "off"),
        f"  key: {'set' if key else 'not set'} (the masked secure secret card {WAKE_KEY_ENV})",
        "  last: " + (f"{last.get('event')} at {last.get('at')}: " + ("ok" if last.get("ok") else str(last.get("error")))
                      if last else "never")]
    out = {"on": on, "url": _mask_url(cfg.get("url")), "key": key, "last": last or None, "text": "\n".join(lines)}
    if arg.lower() == "test":
        out["ok"] = bool(last.get("ok"))
        if not out["ok"]:
            out["error"] = f"the test wake-up failed: {last.get('error')}"
    return out


def cmd_run(a) -> dict:
    """The supervisor (a `slop job`): turns until nothing is pending."""
    wd, rd = _dirs()
    from .job import proc_start
    me = os.getpid()
    jid = os.environ.get("SLOP_JOB_ID")
    with _lock(rd):
        r = _runner(rd)
        if r.get("state") == "running" and r["alive"] and int(r.get("pid") or 0) != me:
            return {"skipped": True, "text": f"another production supervisor is running (pid {r.get('pid')})"}
        _write_json(rd / "runner.json", {"state": "running", "pid": me, "pid_start": proc_start(me), "job_id": jid,
                                         "since": util.iso_now(), "since_ts": time.time()})
        try:
            (rd / "stop").unlink()
        except OSError:
            pass
    turns = 0
    waker = _Waker(rd)
    waker.start()
    while True:
        with _lock(rd):
            cfg = _cfg(rd)
            st = _read_json(rd / "state.json")
            pend = _pending(rd, st)
            if not pend:
                _write_json(rd / "runner.json", {"state": "idle", "since": util.iso_now(), "since_ts": time.time(),
                                                 "job_id": jid, "turns_run": turns})
                break
            n = int(st.get("turns") or 0) + 1
            st.update(turns=n, delivered=max(int(m["id"]) for m in pend))
            prev_err = st.pop("last_error", None)
            session = (st.get("sessions") or {}).get(cfg["engine"])
            _write_json(rd / "state.json", st)
        res = _turn(wd, rd, cfg, n, pend, prev_err, session)
        turns += 1
        with _lock(rd):
            st = _read_json(rd / "state.json")
            if res.get("session"):
                st.setdefault("sessions", {})[cfg["engine"]] = res["session"]
            st["last_turn"] = {"n": n, "ok": res["ok"], "error": res.get("error"), "ended": util.iso_now(),
                               "elapsed_s": res.get("elapsed_s"), "messages": [m["id"] for m in pend]}
            stopped = (rd / "stop").exists()
            posted = [r for r in _rows(rd / "outbox.jsonl") if r.get("turn") == n]
            if res["ok"] and not posted and str(res.get("text") or "").strip():
                oid = _next_id(rd / "outbox.jsonl")         # it forgot `relay say`: its last words still reach Grok
                _append(rd / "outbox.jsonl", {"id": oid, "seq": _seq(rd), "ts": util.iso_now(),
                                              "t": round(time.time(), 3), "kind": "say",
                                              "text": str(res["text"]).strip()[:4000], "files": [], "turn": n,
                                              "auto": True})
            if not res["ok"]:
                if not stopped:                              # its messages wait for the next turn
                    st["delivered"] = min(int(m["id"]) for m in pend) - 1
                    st["last_error"] = {"turn": n, "error": res.get("error"), "messages": [m["id"] for m in pend]}
                _write_json(rd / "state.json", st)
                _write_json(rd / "runner.json", {"state": "stopped" if stopped else "failed", "error": res.get("error"),
                                                 "turn": n, "since": util.iso_now(), "since_ts": time.time(),
                                                 "job_id": jid})
                _log(rd, f"turn {n}: {'stopped' if stopped else 'FAILED'}: {res.get('error')}")
                end = ({"turns": turns, "stopped": True, "text": f"stopped during turn {n}"} if stopped else
                       {"ok": False, "turns": turns, "error": f"turn {n} failed: {res.get('error')}"})
            else:
                _write_json(rd / "state.json", st)
                end = None
        if end is not None:                           # outside the lock: a wake-up may take seconds
            waker.finish(None if end.get("stopped") else "failed", turn=n)
            return end
        _log(rd, f"turn {n}: done in {res.get('elapsed_s')} s")
    _log(rd, f"idle after {turns} turn(s)")
    waker.finish("finished")
    return {"turns": turns, "text": f"the production ran {turns} turn(s) and is idle"}


# ================================================================================================== register
def register(sub) -> None:
    g = sub.add_parser("relay", help="Grok passes the person's words; the production (Claude Code or Codex here) "
                                     "does all the work: setup, send, read, done, fail, say, ask, job, inbox, status, "
                                     "stop, log",
                       description="Grok is a relay: it passes the person's words verbatim (send), shows what the "
                                   "production posts (read), and runs the jobs it asks for (done / fail). The "
                                   "production (Claude Code, or Codex) does all the creative and technical work in the "
                                   "projects folder. One relay per computer; no project name. See docs/96-relay.md.")
    rs = g.add_subparsers(dest="relay_cmd", metavar="ACTION", required=True)
    mine = [g]

    def add(name: str, **kw) -> argparse.ArgumentParser:
        sp = rs.add_parser(name, **kw)
        util.add_common_flags(sp)
        mine.append(sp)
        return sp

    p = add("setup", help="check the engine is signed in, register the claudia.gallery MCP, install the Claudia "
                          "skill, write the production brief (CLAUDE.md, AGENTS.md in the projects folder)")
    p.add_argument("--engine", default=None, help="claude | codex (default: the engine the relay runs, else the "
                                                  "one signed in here, Claude Code first; ChatGPT only: codex)")
    p.add_argument("--model", default=None, help="the production's model (default: opus for Claude Code; Codex's own)")
    p.add_argument("--no-skill", action="store_true", help="do not download the Claudia skill")
    p.add_argument("--force", action="store_true", help="replace a CLAUDE.md / AGENTS.md that slop relay did not write")
    p.set_defaults(func=cmd_setup)

    p = add("send", help="pass words to the production verbatim; starts a turn when it is idle (returns in seconds)")
    p.add_argument("text", nargs="*", help="the words, verbatim (or --file)")
    p.add_argument("--file", help="read the words from this file")
    p.add_argument("--from", dest="sender", choices=["director", "grok"], default="director",
                   help="director (default: the person's words, also logged, dated) | grok (a relay note)")
    p.set_defaults(func=cmd_send)

    p = add("read", help="what Grok shows next: new messages with their files, open jobs, the production's state, "
                         "grok_next")
    p.add_argument("--wait", type=float, default=0, metavar="S",
                   help=f"wait up to S seconds (cap {WAIT_CAP_S:g}) while the production works; returns on anything "
                        "new")
    p.add_argument("--all", action="store_true", help="show every message, not only the new ones")
    p.set_defaults(func=cmd_read)

    p = add("done", help="(Grok) a job's files are saved: mark it done and tell the production")
    p.add_argument("job", help="the job id, e.g. J-0003")
    p.add_argument("--file", action="append", help="a saved file (repeat per file)")
    p.add_argument("--note", help="one line for the production")
    p.add_argument("--model", help="the model or version the page used (Midjourney's version, Suno's model), recorded "
                                   "with the files")
    p.set_defaults(func=cmd_done)

    p = add("cancel", help="close a job no one needs any more (cancelled, not failed): the production's own, or "
                           "Grok's when the person says so")
    p.add_argument("job", help="the job id, e.g. J-0003")
    p.add_argument("--reason", help="why, in a few words")
    p.set_defaults(func=cmd_cancel)

    p = add("fail", help="(Grok) a job could not be done: mark it failed (--declined: the service refused it)")
    p.add_argument("job", help="the job id, e.g. J-0003")
    p.add_argument("--reason", required=True, help="what happened, verbatim")
    p.add_argument("--declined", action="store_true", help="the service declined it (final for that image there)")
    p.set_defaults(func=cmd_fail)

    p = add("say", help="(the production) post a message for the director, with files to show")
    p.add_argument("text", nargs="+", help="the message")
    p.add_argument("--show", nargs="+", metavar="FILE",
                   help="files Grok shows with it (contact sheets, stills, proofs)")
    p.add_argument("--as-is", action="store_true", help="post a video even if phones will play it badly")
    p.set_defaults(func=cmd_say)

    p = add("ask", help="(the production) ask the director one question, with its default")
    p.add_argument("text", nargs="+", help="the question")
    p.add_argument("--default", default=None, help="the answer when they just say go")
    p.add_argument("--show", nargs="+", metavar="FILE", help="files Grok shows with it")
    p.add_argument("--as-is", action="store_true", help="post a video even if phones will play it badly")
    p.set_defaults(func=cmd_ask)

    p = add("job", help="(the production) ask Grok for browser work, all of it in Grok's own signed-in browser "
                        "(--kind grok-imagine | midjourney | suno | browser); --kind person only for what only a "
                        "person can do")
    p.add_argument("--kind", choices=["grok-imagine", "midjourney", "suno", "browser", "person", "hedra"], required=True)
    p.add_argument("--what", help="grok-imagine: still | clip; hedra: quote | generate")
    p.add_argument("--clip", help="hedra: locked clip id in the selected project")
    p.add_argument("--prompt", help="grok-imagine: the prompt, verbatim")
    p.add_argument("--prompt-file", help="grok-imagine: read the prompt from this file")
    p.add_argument("--image", help="grok-imagine: a start image (must exist)")
    p.add_argument("--aspect", choices=["16:9", "9:16", "1:1", "2:3", "3:2"])
    p.add_argument("--seconds", type=int, help="grok-imagine clip length")
    p.add_argument("--save", help="where the downloads go (default: the project's inbox/<kind>/)")
    p.add_argument("--name", help="file stem for the downloads (default: the job id)")
    p.add_argument("--note", help="one line for Grok or the person")
    p.add_argument("--text", action="append", help="midjourney: one full prompt per --text (each is its own "
                                                   "Midjourney job); browser: text to paste; person: a copy block")
    p.add_argument("--title", help="suno: the song title")
    p.add_argument("--style", help="suno: the Style of Music field, verbatim")
    p.add_argument("--lyrics", help="suno: the lyrics field, verbatim")
    p.add_argument("--lyrics-file", help="suno: read the lyrics field from this file")
    p.add_argument("--exclude", help="suno: the Exclude styles field")
    p.add_argument("--instrumental", action="store_true", help="suno: an instrumental (no lyrics)")
    p.add_argument("--url", help="browser: the page to start on")
    p.add_argument("--plate", action="append", help="midjourney: the plate each --text is for (one per --text, in "
                                                    "order); Grok names the downloads PLATE-N.png for plates ingest")
    p.add_argument("--personalize", choices=["on", "off"],
                   help="midjourney: Grok switches the person's personalization on with the P button (default: the "
                        "project's mj.personalize, else on); a profile code never goes into a prompt")
    p.add_argument("--expect", action="append", help="person: where their upload is saved (repeatable)")
    p.set_defaults(func=cmd_job)

    p = add("hedra", help="(Grok) report a Hedra connector quote, claim a generation once, or return its result")
    p.add_argument("job", help="Hedra relay job J-NNNN")
    p.add_argument("--action", choices=["quote", "start", "pending", "complete", "failed"], required=True)
    p.add_argument("--cost", type=float, help="confirmed estimate or net cost; always include currency")
    p.add_argument("--currency", choices=["USD", "credits"])
    p.add_argument("--job-id", help="Hedra job.job_id")
    p.add_argument("--url", help="completed video URL")
    p.add_argument("--reason", help="confirmed failure; never use for an uncertain submission")
    from .gen.hedra_relay import report as report_hedra
    p.set_defaults(func=report_hedra)

    p = add("inbox", help="(the production) new messages from the director and Grok, marked read")
    p.set_defaults(func=cmd_inbox)

    p = add("status", help="the production's state, engine, session, message counts and open jobs")
    p.set_defaults(func=cmd_status)

    p = add("wake", help="the wake-up routine: Grok's webhook, called when the production posts while Grok is "
                         "not waiting (a URL turns it on; off; test); its key: $CLAUDIA_WAKE_KEY")
    p.add_argument("url", nargs="?", help="the routine's webhook URL (https), off, or test")
    p.set_defaults(func=cmd_wake)

    p = add("effort", help="how hard the production thinks, per engine (Claude Code --effort, Codex reasoning "
                           "effort): show the levels, or set one for the next turns")
    p.add_argument("level", nargs="?", help="a level the engine offers (shown without one), default (xhigh) or auto "
                                            "(the engine decides)")
    p.add_argument("--engine", help="claude | codex (default: the engine the relay runs)")
    p.set_defaults(func=cmd_effort)

    p = add("stop", help="stop the running production turn (waiting messages stay)")
    p.add_argument("--grace", type=float, default=10.0, help="seconds between SIGTERM and SIGKILL (default 10)")
    p.set_defaults(func=cmd_stop)

    p = add("log", help="the tail of the relay log (and the last turn's stderr)")
    p.add_argument("--lines", type=int, default=40)
    p.set_defaults(func=cmd_log)

    p = add("_run")                         # internal: the supervisor job (no help = not in the command list)
    p.set_defaults(func=cmd_run)
    for q in mine:
        util.json_usage_errors(q)

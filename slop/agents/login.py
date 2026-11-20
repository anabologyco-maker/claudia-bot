"""Headless sign-in for the agent CLIs, spread over several bot turns.

A sign-in waits for the user (open a link, approve, maybe copy a code back), which takes longer than one shell call.
So `slop agents login ENGINE` starts a KEEPER as a background `slop job` (`slop agents _login-session ENGINE`, detached:
it outlives the shell call and the bot's turn). The keeper runs the CLI's own login command, reads what it prints,
writes the link (and the device code) to $SLOP_HOME/agents/login/<engine>/state.json, and keeps the CLI waiting.

  paste flows (claude; gemini under a pseudo-terminal): the user approves and copies the code the page shows; the bot
    asks for it with the SECURE SECRET CARD (e.g. CLAUDE_LOGIN_CODE), which arrives as an environment variable; then
    `slop agents login claude --code-from-env CLAUDE_LOGIN_CODE` writes it into the keeper's FIFO
    (agents/login/<engine>/code.fifo, mode 0600; a drop file code.in where FIFOs do not exist) and the keeper types it
    into the waiting CLI. The code is never printed, logged or stored on disk.
  device flows (codex, muse): the user enters the code shown at the link; the CLI notices by itself;
    `slop agents login codex --check` waits up to 25 s for the result.

state.json: {engine, state, url, user_code, started, expires_at, keeper_pid, message, tail[], logged_in, plan}
state: starting -> waiting_code | waiting_approval -> code_sent -> done | failed | expired | cancelled.
A session lives 15 minutes (Codex device codes expire after 15 minutes).
"""
from __future__ import annotations

import hashlib
import os
import queue
import re
import signal
import subprocess
import threading
import time
from pathlib import Path

from .. import util
from ..config import SlopError
from . import engines as E

SESSION_TTL_S = 15 * 60
AFTER_CODE_S = 120                       # how long the CLI may take to accept a pasted code
CODE_RE = re.compile(r"^[A-Za-z0-9._~#/+=-]{8,4096}$")
ENV_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
WAITING = ("starting", "waiting_code", "waiting_approval", "code_sent")
TERMINAL = ("done", "failed", "expired", "cancelled")
ANSI_RE = re.compile(r"\x1b\[[0-9;?<>=]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[()][A-Za-z0-9]|\x1b[=>78]|\r")
REJECT_RE = re.compile(r"(?i)\b(invalid|error|failed|expired|denied|incorrect)\b|paste code here|wasn.t accepted|"
                       r"couldn.t log in")     # 2.1.3xx: "Couldn't log in: That code wasn't accepted..."
GEMINI_FAIL_RE = re.compile(r"(?i)failed to (?:authenticate|login|sign in)|invalid_grant|authentication failed")


def _not_set(env_name: str, cmd: str, ask: str) -> SlopError:
    """A secret from the secure card reaches NEW shells: try a fresh login shell once before asking the user again."""
    return SlopError(f"{env_name} is not set in this shell. If the user just saved it with the secure secret card, a new "
                     f"shell sees it: run `bash -lc '{cmd}'` once before asking again. Not saved yet: {ask}")


# ------------------------------------------------------------------------------------------------- state files
def session_dir(engine: str) -> Path:
    return E.agents_dir() / "login" / engine


def state_path(engine: str) -> Path:
    return session_dir(engine) / "state.json"


def pid_alive(pid) -> bool:
    if not pid:
        return False
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if os.name == "nt":  # pragma: no cover - Windows only
        try:
            from ..job import alive
            return alive(pid)
        except Exception:  # noqa: BLE001
            return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:                                          # a zombie (exited, not yet reaped) is not alive
        with open(f"/proc/{pid}/stat", "rb") as f:
            return f.read().split(b")")[-1].split()[0] != b"Z"
    except OSError:
        return True


def _used_codes_file(engine: str) -> Path:
    """sha256 of every sign-in code already handed to ENGINE (never the codes themselves)."""
    return state_path(engine).parent / f"{engine}-used-codes.txt"


def read_state(engine: str) -> dict | None:
    st = E.read_json_quiet(state_path(engine))
    if not st:
        return None
    st["alive"] = pid_alive(st.get("keeper_pid"))
    if st.get("state") in WAITING and not st["alive"]:
        st["state"] = "failed"
        st["message"] = st.get("message") or "the sign-in keeper stopped (the computer restarted or it was killed)"
    return st


def _write_state(engine: str, st: dict) -> None:
    st = {k: v for k, v in st.items() if k != "alive"}
    st["updated"] = util.iso_now()
    util.atomic_write_json(state_path(engine), st)


def _clean(b: bytes) -> str:
    return ANSI_RE.sub("", b.decode("utf-8", "replace"))


def _short_url(u: str) -> str:
    return re.sub(r"\?.*$", "?…", u)


def _safe_tail(text: str, secret: str | None = None, n: int = 6) -> list[str]:
    if secret:
        text = text.replace(secret, "[code]")
    lines = [re.sub(r"https://\S+", lambda m: _short_url(m.group(0)), ln).strip() for ln in text.splitlines()]
    return [ln[:200] for ln in lines if ln][-n:]


# ------------------------------------------------------------------------------------------------- code channel
def _open_channel(d: Path):
    """('fifo', fd) on POSIX (O_RDWR keeps it open, so a writer that closes never gives EOF), else ('file', path)."""
    fifo = d / "code.fifo"
    if hasattr(os, "mkfifo"):
        try:
            if fifo.exists() or fifo.is_symlink():
                fifo.unlink()
            os.mkfifo(fifo, 0o600)
            return ("fifo", os.open(str(fifo), os.O_RDWR | os.O_NONBLOCK))
        except OSError:
            pass
    return ("file", d / "code.in")


def _take_code(chan, pending: list[str]) -> str | None:
    kind, ref = chan
    if kind == "fifo":
        try:
            data = os.read(ref, 8192)
        except (BlockingIOError, InterruptedError):
            data = b""
        except OSError:
            data = b""
        if data:
            pending.append(data.decode("utf-8", "replace"))
        joined = "".join(pending)
        if "\n" in joined:
            line, rest = joined.split("\n", 1)
            pending[:] = [rest] if rest else []
            return line.strip()
        return None
    p: Path = ref
    if p.is_file():
        try:
            code = p.read_text(encoding="utf-8").strip()
        finally:
            try:
                p.unlink()
            except OSError:
                pass
        return code or None
    return None


def put_code(engine: str, code: str) -> str:
    """Hand a code to the waiting keeper. Returns the channel used. The code is never written to a log."""
    d = session_dir(engine)
    fifo = d / "code.fifo"
    if fifo.exists() and hasattr(os, "mkfifo"):
        try:
            fd = os.open(str(fifo), os.O_WRONLY | os.O_NONBLOCK)
        except OSError as e:
            raise SlopError(f"the {E.SPEC[engine]['title']} sign-in is not listening any more ({e.strerror}): start "
                            f"again with `slop agents login {engine}`") from None
        try:
            os.write(fd, (code + "\n").encode())
        finally:
            os.close(fd)
        return "fifo"
    tmp = d / "code.in.tmp"
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, code.encode())
    finally:
        os.close(fd)
    tmp.replace(d / "code.in")
    return "file"


# ------------------------------------------------------------------------------------------------- the CLI process
class _Proc:
    """The login CLI on pipes or on a pseudo-terminal; output arrives on a queue from a reader thread (portable)."""

    def __init__(self, argv: list[str], env: dict, cwd: str, use_pty: bool, want_stdin: bool):
        self.q: queue.Queue = queue.Queue()
        self.master = None
        kw = {"start_new_session": True} if os.name != "nt" else {"creationflags": 0x00000200}
        if use_pty:
            import pty
            import struct
            master, slave = pty.openpty()
            try:
                import fcntl
                import termios
                fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 50, 220, 0, 0))
            except (ImportError, OSError):
                pass
            env = {**env, "TERM": env.get("TERM") or "xterm-256color", "COLUMNS": "220", "LINES": "50"}
            self.p = subprocess.Popen(argv, stdin=slave, stdout=slave, stderr=slave, env=env, cwd=cwd,
                                      close_fds=True, **kw)
            os.close(slave)
            self.master = master
            src = master
        else:
            self.p = subprocess.Popen(argv, stdin=subprocess.PIPE if want_stdin else subprocess.DEVNULL,
                                      stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, cwd=cwd, bufsize=0,
                                      **kw)
            src = self.p.stdout.fileno()
        threading.Thread(target=self._reader, args=(src,), daemon=True).start()

    def _reader(self, fd: int) -> None:
        while True:
            try:
                b = os.read(fd, 65536)
            except OSError:
                b = b""
            if not b:
                self.q.put(None)
                return
            self.q.put(b)

    def read(self, timeout: float) -> bytes | None:
        """bytes, b"" when nothing arrived in time, None at end of output."""
        try:
            return self.q.get(timeout=timeout)
        except queue.Empty:
            return b""

    def send_line(self, text: str) -> None:
        if self.master is not None:
            os.write(self.master, (text + "\r").encode())
        else:
            self.p.stdin.write((text + "\n").encode())
            self.p.stdin.flush()

    def poll(self):
        return self.p.poll()

    def kill(self) -> None:
        if self.p.poll() is None:
            try:
                if os.name != "nt":
                    os.killpg(self.p.pid, signal.SIGTERM)
                else:  # pragma: no cover
                    subprocess.run(["taskkill", "/PID", str(self.p.pid), "/T", "/F"], capture_output=True)
            except OSError:
                pass
            try:
                self.p.wait(3)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(self.p.pid, signal.SIGKILL) if os.name != "nt" else self.p.kill()
                except OSError:
                    pass
        if self.master is not None:
            try:
                os.close(self.master)
            except OSError:
                pass
        if self.p.stdin:
            try:
                self.p.stdin.close()
            except OSError:
                pass


def _parse_prompt(engine: str, text: str) -> tuple[str | None, str | None]:
    spec = E.SPEC[engine]
    m = re.search(spec["url_re"], text)
    if not m:
        return None, None
    url = m.group(1).rstrip(".,;)")
    code = None
    if spec.get("code_re"):
        after = text[m.start():]
        c = re.search(spec["code_re"], after) or re.search(spec["code_re"], text)
        if not c:
            return None, None                      # the code line has not arrived yet
        code = c.group(1)
    return url, code


# ------------------------------------------------------------------------------------------------- the keeper
def run_session(engine: str, ttl: float = SESSION_TTL_S) -> dict:
    """The keeper (run as a background job): drive one sign-in from start to finish. Any error is also written to
    state.json, so `slop agents login ENGINE --check` can say what went wrong."""
    try:
        return _session(engine, ttl)
    except Exception as e:
        st = E.read_json_quiet(state_path(engine)) or {"engine": engine, "title": E.SPEC[engine]["title"]}
        if st.get("state") not in TERMINAL:
            st.update(state="failed", message=str(e)[:300], keeper_pid=None, ended=util.iso_now())
            _write_state(engine, st)
        raise


def _session(engine: str, ttl: float) -> dict:
    spec = E.SPEC[engine]
    d = session_dir(engine)
    d.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass
    for f in ("code.fifo", "code.in", "code.in.tmp", "cancel"):
        try:
            (d / f).unlink()
        except OSError:
            pass
    b = E.find(engine)
    if not b:
        raise SlopError(f"{spec['title']} is not installed: run `slop agents install {engine}` first")
    t_start = time.time()
    st = {"engine": engine, "title": spec["title"], "flow": spec["login"], "state": "starting", "url": None,
          "user_code": None, "keeper_pid": os.getpid(), "job_id": os.environ.get("SLOP_JOB_ID"),
          "started": util.iso_now(), "expires_at": util.stamp(t_start + ttl),
          "expires_ts": round(t_start + ttl, 1), "message": None, "tail": []}
    _write_state(engine, st)
    stop = {"sig": None}

    def on_sig(signum, _frame):
        stop["sig"] = signum
    if os.name != "nt":
        for s in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            try:
                signal.signal(s, on_sig)
            except ValueError:                      # not the main thread (tests run the keeper in a thread)
                pass
    env = E.base_env(engine, plan_only=True, extra=spec.get("login_env"))
    creds = None
    if engine == "gemini":
        E.gemini_settings_set("oauth-personal")
        creds = E.gemini_dir() / "oauth_creds.json"
    paste = spec["login"] in ("paste", "paste-pty")
    use_pty = spec["login"] == "paste-pty"
    if use_pty and os.name == "nt":
        raise SlopError("the Gemini sign-in needs a terminal on Windows: the user runs `gemini` once in a terminal, "
                        "or uses a GEMINI_API_KEY (slop agents login gemini --key-from-env GEMINI_API_KEY)")
    chan = _open_channel(d) if paste else None
    proc = _Proc(b["argv"] + list(spec["login_args"]), env, str(d), use_pty, want_stdin=paste)
    buf, pending, secret = "", [], None
    sent_at, sent_mark = None, 0
    result, why = None, None
    try:
        while True:
            chunk = proc.read(0.4)
            eof = chunk is None
            if chunk:
                buf = (buf + _clean(chunk))[-200_000:]
            if not st["url"]:
                url, code = _parse_prompt(engine, buf)
                if url:
                    st.update(url=url, user_code=code, state="waiting_code" if paste else "waiting_approval")
                    _write_state(engine, st)
            elif paste and st["state"] == "waiting_code":
                got = _take_code(chan, pending)
                if got:
                    if CODE_RE.fullmatch(got):
                        secret = got
                        sent_mark = len(buf)
                        proc.send_line(got)
                        sent_at = time.monotonic()
                        st.update(state="code_sent", message=None)
                    else:
                        st["message"] = "that code did not look right (no spaces; copy the whole code again)"
                    _write_state(engine, st)
            if stop["sig"] or (d / "cancel").exists():
                result, why = "cancelled", "cancelled (slop agents login --cancel)"
                break
            if creds is not None and creds.is_file() and creds.stat().st_mtime >= t_start - 1:
                result = "done"
                break
            if sent_at and engine == "claude" and REJECT_RE.search(buf[sent_mark:]):
                time.sleep(0.5)
                result, why = "failed", "Claude Code did not accept the code (wrong or expired); start again"
                break
            if sent_at and engine == "gemini" and GEMINI_FAIL_RE.search(buf[sent_mark:]):
                result, why = "failed", "Google did not accept the code (wrong or expired); start again"
                break
            rc = proc.poll()
            if rc is not None and (eof or proc.q.empty()):
                while True:                                  # drain what is left
                    rest = proc.read(0.2)
                    if not rest:
                        break
                    buf = (buf + _clean(rest))[-200_000:]
                if rc == 0:
                    result = "done"                          # the status probe below confirms the login
                else:
                    result, why = "failed", f"the login command ended with exit code {rc}" + \
                        ("" if st["url"] else " before it printed a sign-in link")
                break
            if sent_at and time.monotonic() - sent_at > AFTER_CODE_S:
                result, why = "failed", f"no answer {AFTER_CODE_S} s after the code was sent; start again"
                break
            if time.time() - t_start > ttl:
                result, why = "expired", f"nobody finished the sign-in within {int(ttl // 60)} minutes; start again"
                break
            if eof and rc is None:
                time.sleep(0.3)
    finally:
        proc.kill()
        if chan and chan[0] == "fifo":
            try:
                os.close(chan[1])
            except OSError:
                pass
        for f in ("code.fifo", "code.in", "code.in.tmp", "cancel"):
            try:
                (d / f).unlink()
            except OSError:
                pass
    s = {}
    try:
        from .status import engine_status
        s = engine_status(engine)
    except Exception as e:  # noqa: BLE001 - the status probe is advisory here
        s = {"logged_in": None, "error": str(e)}
    if result == "done" and s.get("logged_in") is False:
        result, why = "failed", "the sign-in ended but the CLI still reports no login"
    st.update(state=result, message=why, logged_in=s.get("logged_in"), plan=s.get("plan"), auth=s.get("auth"),
              tail=_safe_tail(buf, secret), ended=util.iso_now(), keeper_pid=None)
    _write_state(engine, st)
    out = {"ok": result == "done", "engine": engine, "state": result, "logged_in": s.get("logged_in"),
           "plan": s.get("plan"),
           "text": f"{spec['title']} sign-in {result}" + (f": {why}" if why else "")
                   + (f" (plan: {s.get('plan')})" if s.get("plan") else "")}
    if result != "done":
        out["error"] = out["text"]
    return out


# ------------------------------------------------------------------------------------------------- client side
def _wait_for(engine: str, cond, wait: float) -> dict | None:
    t0 = time.monotonic()
    st = read_state(engine)
    while True:
        if st and cond(st):
            return st
        if time.monotonic() - t0 >= wait:
            return st
        time.sleep(0.25)
        st = read_state(engine)


def _mins_left(st: dict) -> int:
    return max(0, -int(-(float(st.get("expires_ts") or 0) - time.time()) // 60))


def describe(engine: str, st: dict | None) -> dict:
    """The JSON + text for a session state, with the exact next step."""
    spec = E.SPEC[engine]
    t = spec["title"]
    if not st:
        return {"ok": False, "engine": engine, "state": None, "error": f"no {t} sign-in was started",
                "next": f"slop agents login {engine}", "text": f"no {t} sign-in was started. Next: slop agents login {engine}"}
    state = st.get("state")
    base = {"engine": engine, "state": state, "url": st.get("url"), "user_code": st.get("user_code"),
            "expires_in_min": _mins_left(st) if state in WAITING else None, "logged_in": st.get("logged_in"),
            "plan": st.get("plan"), "message": st.get("message")}
    if state == "waiting_code":
        sec = spec.get("code_secret", "LOGIN_CODE")
        nxt = f"slop agents login {engine} --code-from-env {sec}"
        return {**base, "ok": True, "code_secret": sec, "next": nxt, "text": "\n".join([
            f"{t} sign-in is waiting (expires in {_mins_left(st)} min). With the user:",
            f"  1. The user opens this link, signs in with {spec['signin']} and approves:",
            f"     {st.get('url')}",
            f"  2. The page then shows a code. Ask for it with the SECURE SECRET CARD named {sec} (never in chat).",
            f"  3. Then run:  {nxt}"] + ([f"  note: {st['message']}"] if st.get("message") else []))}
    if state == "waiting_approval":
        nxt = f"slop agents login {engine} --check"
        return {**base, "ok": True, "next": nxt, "text": "\n".join([
            f"{t} sign-in is waiting (expires in {_mins_left(st)} min). With the user:",
            f"  1. The user opens {st.get('url')}",
            f"  2. signs in with {spec['signin']} and enters this code: {st.get('user_code')}",
            "     (only if they started this sign-in themselves - never a code someone else sent them)",
            f"  3. Then run:  {nxt}   (waits up to 25 s; run it again if it is still waiting)"])}
    if state in ("starting", "code_sent"):
        nxt = f"slop agents login {engine} --check"
        what = "starting" if state == "starting" else "checking the code"
        return {**base, "ok": True, "next": nxt, "text": f"{t} sign-in is {what}. Next: {nxt}"}
    if state == "done":
        nxt = f"slop agents test {engine}"
        plan = f" (plan: {st.get('plan')})" if st.get("plan") else ""
        return {**base, "ok": True, "next": nxt, "text": f"{t} is signed in{plan}. Next: {nxt}   (one tiny run that "
                                                          "proves it works)"}
    msg = st.get("message") or state
    nxt = f"slop agents login {engine}"
    return {**base, "ok": False, "error": f"{t} sign-in {state}: {msg}", "next": nxt,
            "tail": st.get("tail") or [],
            "text": f"{t} sign-in {state}: {msg}. Start a new one with: {nxt}"}


def start(engine: str, force: bool = False, wait: float | None = None) -> dict:
    spec = E.SPEC[engine]
    if not E.find(engine):
        raise SlopError(f"{spec['title']} is not installed: run `slop agents install {engine}` first")
    if spec["login"] == "paste-pty" and os.name == "nt":
        raise SlopError("on Windows the user signs in to Gemini CLI by running `gemini` once in a terminal, or the bot "
                        "uses a key: slop agents login gemini --key-from-env GEMINI_API_KEY")
    st = read_state(engine)
    if st and st.get("alive") and st.get("state") in WAITING:
        out = describe(engine, st)
        out["reused"] = True
        out["text"] = "(a sign-in is already waiting - not started twice)\n" + out["text"]
        return out
    if force and engine == "claude" and os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "").strip():
        from .status import TOKEN_REJECTED
        raise SlopError("CLAUDE_CODE_OAUTH_TOKEN is set in this shell, and Claude Code uses it before any account "
                        "sign-in, so a new sign-in would change nothing. If that token is rejected: "
                        + TOKEN_REJECTED.split(". ", 1)[1])
    if not force:
        from .status import engine_status
        s = engine_status(engine)
        if s.get("logged_in"):
            return {"ok": True, "engine": engine, "already": True, "plan": s.get("plan"), "auth": s.get("auth"),
                    "next": f"slop agents test {engine}",
                    "text": f"{spec['title']} is already signed in ({s.get('auth_text') or s.get('auth')}). "
                            f"--force starts a new sign-in. Next: slop agents test {engine}"}
    from .. import job
    try:
        (session_dir(engine) / "state.json").unlink()
    except OSError:
        pass
    r = job.start(["agents", "_login-session", engine])
    jid = (r.get("job") or {}).get("id")
    wait = min(30.0, job.default_wait()) if wait is None else wait
    st = _wait_for(engine, lambda s: s.get("url") or s.get("state") in TERMINAL, wait)
    out = describe(engine, st)
    out["job"] = jid
    if not st or (not st.get("url") and st.get("state") not in TERMINAL):
        out.update(ok=True, next=f"slop agents login {engine} --check",
                   text=f"{spec['title']} sign-in is starting (job {jid}). Next: slop agents login {engine} --check")
    return out


def check(engine: str, wait: float | None = None) -> dict:
    """Wait (at most `wait` s) for the sign-in to move on: the link while it starts, else its end. A paste flow
    waiting for its code returns at once (only the code moves it on)."""
    from .. import job
    wait = job.default_wait() if wait is None else wait
    first = read_state(engine)
    if first and first.get("state") == "starting":
        cond = lambda s: bool(s.get("url")) or s.get("state") in TERMINAL  # noqa: E731
    else:
        cond = lambda s: s.get("state") in TERMINAL or s.get("state") == "waiting_code"  # noqa: E731
    return describe(engine, _wait_for(engine, cond, wait))


def send_code(engine: str, env_name: str, wait: float | None = None) -> dict:
    spec = E.SPEC[engine]
    if spec["login"] not in ("paste", "paste-pty"):
        raise SlopError(f"{spec['title']} does not take a pasted code: the user enters the code that "
                        f"`slop agents login {engine}` showed at its link; then run `slop agents login {engine} --check`")
    if not ENV_NAME_RE.fullmatch(env_name or ""):
        raise SlopError(f"--code-from-env takes the NAME of an environment variable (like {spec['code_secret']}), "
                        "not the code itself")
    if env_name != spec["code_secret"]:
        # only the sign-in code's own secret: any other variable (an API key, a plan token) would be typed into the
        # vendor's sign-in page and sent to its servers
        raise SlopError(f"--code-from-env for {spec['title']} reads only {spec['code_secret']} (refused: {env_name}). "
                        f"Ask the user for the code the sign-in page showed with the secure secret card named "
                        f"{spec['code_secret']}, then: slop agents login {engine} --code-from-env {spec['code_secret']}")
    code = os.environ.get(env_name, "").strip()
    if not code:
        raise _not_set(env_name, f"slop agents login {engine} --code-from-env {env_name}",
                       f"ask the user for the code with the secure secret card named {env_name}, then run this "
                       "command again.")
    if not CODE_RE.fullmatch(code):
        raise SlopError(f"the value of {env_name} does not look like a sign-in code (it should be one word with no "
                        "spaces, as the page shows it). Ask the user to copy the code again with the secure card.")
    st = read_state(engine)
    if not st or not st.get("alive") or st.get("state") != "waiting_code":
        now = (st or {}).get("state")
        raise SlopError(f"no {spec['title']} sign-in is waiting for a code (state: {now or 'none'}). Start a new one "
                        f"with `slop agents login {engine}`: it shows a NEW link, and only the code from that new link "
                        "works.")
    used = _used_codes_file(engine)
    digest = hashlib.sha256(code.encode()).hexdigest()
    if used.is_file() and digest in used.read_text(encoding="utf-8").split():
        # the secure-card secret outlives its sign-in: an old, consumed code would only be rejected by the vendor
        raise SlopError(f"{env_name} still holds the code from an EARLIER sign-in (each code works once). Ask the user "
                        f"for the NEW code with the secure secret card named {env_name} (saving the card again "
                        f"replaces it), then run: slop agents login {engine} --code-from-env {env_name}")
    put_code(engine, code)
    used.parent.mkdir(parents=True, exist_ok=True)
    with used.open("a", encoding="utf-8") as f:              # hashes only: the code itself is never stored
        f.write(digest + "\n")
    from .. import job
    wait = job.default_wait() if wait is None else wait
    st = _wait_for(engine, lambda s: s.get("state") in TERMINAL, wait)
    out = describe(engine, st)
    out["code_from_env"] = env_name
    if st and st.get("state") in ("waiting_code", "code_sent", "starting"):
        out.update(ok=True, next=f"slop agents login {engine} --check",
                   text=f"the code from {env_name} was handed to {spec['title']}; it is still checking it. "
                        f"Next: slop agents login {engine} --check")
    elif st and st.get("state") == "done":
        out["text"] += f"\n  ({env_name} was single-use; the user may delete that secret now.)"
    return out


def cancel(engine: str) -> dict:
    d = session_dir(engine)
    st = read_state(engine)
    if not st or st.get("state") in TERMINAL:
        return {"ok": True, "engine": engine, "state": (st or {}).get("state"),
                "text": f"no {E.SPEC[engine]['title']} sign-in is running"}
    d.mkdir(parents=True, exist_ok=True)
    (d / "cancel").write_text("cancel\n", encoding="utf-8")
    st = _wait_for(engine, lambda s: s.get("state") in TERMINAL, 8.0)
    if st and st.get("state") not in TERMINAL and st.get("keeper_pid"):
        try:
            os.kill(int(st["keeper_pid"]), signal.SIGTERM)
        except (OSError, ValueError):
            pass
        st = _wait_for(engine, lambda s: s.get("state") in TERMINAL, 5.0)
    return {"ok": True, "engine": engine, "state": (st or {}).get("state"),
            "text": f"{E.SPEC[engine]['title']} sign-in: {(st or {}).get('state')}"}


# ------------------------------------------------------------------------------------------------- env-based logins
def token_from_env(engine: str, env_name: str) -> dict:
    """Claude Code's long-lived token (`claude setup-token` on the user's own computer -> secret CLAUDE_CODE_OAUTH_TOKEN)."""
    if engine != "claude":
        raise SlopError("--token-from-env is for Claude Code (CLAUDE_CODE_OAUTH_TOKEN from `claude setup-token`)")
    if env_name != "CLAUDE_CODE_OAUTH_TOKEN":
        raise SlopError("Claude Code reads its token only from CLAUDE_CODE_OAUTH_TOKEN: store the secret under that "
                        "name with the secure secret card, then run `slop agents login claude --token-from-env "
                        "CLAUDE_CODE_OAUTH_TOKEN`")
    if not os.environ.get(env_name, "").strip():
        raise _not_set(env_name, f"slop agents login claude --token-from-env {env_name}",
                       "the user runs `claude setup-token` on their own computer (it needs their Claude plan) and gives "
                       f"the result with the secure secret card named {env_name}; then run this command again.")
    from .status import engine_status
    s = engine_status("claude")
    if not s.get("installed"):
        raise SlopError("Claude Code is not installed: run `slop agents install claude` first")
    ok = bool(s.get("logged_in")) and s.get("auth") == "oauth_token"
    return {"ok": ok, "engine": "claude", "auth": s.get("auth"), "token_env": env_name, "next": "slop agents test claude",
            **({} if ok else {"error": f"Claude Code does not report the token login ({s.get('auth')})"}),
            "text": (f"Claude Code will use the secret {env_name} (a long-lived plan token) in every shell. The status "
                     "check does not contact Anthropic, so prove it with: slop agents test claude") if ok else
                    f"Claude Code did not pick up {env_name} (auth: {s.get('auth')})."}


def key_from_env(engine: str, env_name: str) -> dict:
    """Gemini CLI with an API key (GEMINI_API_KEY from Google AI Studio, given with the secure secret card)."""
    if engine != "gemini":
        raise SlopError("--key-from-env is for Gemini CLI (GEMINI_API_KEY). Claude Code, Codex and Muse sign in with "
                        "the user's plan: slop agents login ENGINE")
    if env_name != "GEMINI_API_KEY":
        raise SlopError("Gemini CLI signs in with GEMINI_API_KEY: store the key under that name with the secure secret "
                        "card, then: slop agents login gemini --key-from-env GEMINI_API_KEY")
    if not os.environ.get(env_name, "").strip():
        raise _not_set(env_name, f"slop agents login gemini --key-from-env {env_name}",
                       "the user creates a key at aistudio.google.com and gives it with the secure secret card named "
                       f"{env_name}; then run this command again.")
    f = E.gemini_settings_set("gemini-api-key")
    from .cli import GEMINI_KEY_JOBS
    return {"ok": True, "engine": "gemini", "auth": "api_key", "key_env": env_name, "settings": str(f),
            "next": "slop agents test gemini", "jobs_note": GEMINI_KEY_JOBS,
            "text": f"Gemini CLI will use {env_name} (set as its sign-in method in {f}). A key can bill the Google Cloud "
                    "project behind it if billing is on there; a free AI Studio key cannot. "
                    f"{GEMINI_KEY_JOBS}. Next: slop agents test gemini"}

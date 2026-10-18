"""A free stand-in for the four agent CLIs, for tests/test_agents_*.py and tests/test_gen_codex_image.py.

    python fakecli.py <claude|codex|muse|gemini> <args...>

It prints what the real CLIs print in the flows `slop agents` drives (verified 2026-10-01: Claude Code 2.1.287,
codex-cli 0.160.0, Muse Code 1.4.2, Gemini CLI 0.62.0) and keeps its "account" in files under $FAKE_STATE:
  <engine>_logged_in      present = signed in
  codex_approve / muse_approve   the test "approves" a device code by creating it
  calls.jsonl             one line per call: {engine, argv, env_present[], browser, no_browser, stdin_head}
Model runs (`claude -p`, `codex exec` without the image prompt, `muse exec`, `gemini -p`) are handed to
runner/fake-engine.mjs when $FAKE_ROUTE_ENGINE is set; with $FAKE_RELAY, `claude -p` and `codex exec` play the
production of `slop relay` (relay_turn). `claude mcp get|add|remove` keep $FAKE_STATE/claude_mcp.json. `codex exec`
with the image prompt plays the image tool
($FAKE_CODEX_IMG = ok | nosaved | noimage | limit | slow). Nothing here touches the network.
"""
from __future__ import annotations

import json
import os
import sys
import time
import uuid
import zlib
from pathlib import Path

ENGINE = sys.argv[1]
ARGS = sys.argv[2:]
STATE = Path(os.environ.get("FAKE_STATE") or ".")
WATCH = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "CODEX_API_KEY", "META_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY",
         "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDECODE")
VERSIONS = {"claude": "2.1.287 (Claude Code)", "codex": "codex-cli 0.160.0", "muse": "Muse Code 1.4.2 (1.4.2-R4684.1)",
            "gemini": "0.62.0"}
ROOT = Path(__file__).resolve().parents[3]


def record(**extra):
    STATE.mkdir(parents=True, exist_ok=True)
    rec = {"engine": ENGINE, "argv": ARGS, "env_present": [k for k in WATCH if os.environ.get(k)],
           "browser": os.environ.get("BROWSER"), "no_browser": os.environ.get("NO_BROWSER"),
           "muse_no_auto_update": os.environ.get("MUSE_NO_AUTO_UPDATE"), **extra}
    with open(STATE / "calls.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")


def out(s: str = "", end: str = "\n") -> None:
    sys.stdout.write(s + end)
    sys.stdout.flush()


def logged(engine: str) -> bool:
    return (STATE / f"{engine}_logged_in").exists()


def png(w: int = 48, h: int = 27) -> bytes:
    raw = b"".join(b"\x00" + b"\x80\x40\x20" * w for _ in range(h))

    def chunk(t, d):
        return len(d).to_bytes(4, "big") + t + d + zlib.crc32(t + d).to_bytes(4, "big")
    ihdr = w.to_bytes(4, "big") + h.to_bytes(4, "big") + b"\x08\x02\x00\x00\x00"
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def to_engine(as_: str) -> None:
    node = os.environ.get("FAKE_NODE") or "node"
    os.execvp(node, [node, str(ROOT / "runner" / "fake-engine.mjs"), "--as", as_, "--", *ARGS])


def wait_for(path: Path, secs: float = 60) -> bool:
    t0 = time.time()
    while time.time() - t0 < secs:
        if path.exists():
            return True
        time.sleep(0.1)
    return False


# --------------------------------------------------------------------------------------------------- claude
def claude() -> int:
    if ARGS[:1] == ["--version"]:
        out(VERSIONS["claude"]); return 0
    if ARGS[:2] == ["auth", "status"]:
        if logged("claude"):
            out(json.dumps({"loggedIn": True, "authMethod": "claude.ai", "apiProvider": "firstParty",
                            "email": "user@example.com", "subscriptionType": "max"}, indent=2)); return 0
        if os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
            out(json.dumps({"loggedIn": True, "authMethod": "oauth_token", "apiProvider": "firstParty"}, indent=2)); return 0
        out(json.dumps({"loggedIn": False, "authMethod": "none", "apiProvider": "firstParty"}, indent=2)); return 1
    if ARGS[:2] == ["auth", "login"]:
        record()
        out("Opening browser to sign in…")
        out("If the browser didn't open, visit: https://claude.com/cai/oauth/authorize?code=true&client_id=fake"
            "&response_type=code&state=s123")
        out("Paste code here if prompted > ", end="")
        code = sys.stdin.readline().strip()
        record(stdin_head=f"len={len(code)}")
        if code == os.environ.get("FAKE_GOOD_CODE", "good-code#0123456789abcdef"):
            (STATE / "claude_logged_in").write_text("1")
            out("Login successful."); return 0
        out("Login failed: Request failed with status code 400")
        time.sleep(30); return 1                     # like the real CLI: it does not exit at once
    if ARGS[:1] == ["mcp"]:
        return claude_mcp()
    if "-p" in ARGS and os.environ.get("FAKE_RELAY"):
        return relay_turn("claude", ARGS[ARGS.index("-p") + 1])
    if "-p" in ARGS and os.environ.get("FAKE_ROUTE_ENGINE"):
        to_engine("claude")
    out("fake claude: unsupported " + " ".join(ARGS)); return 2


def claude_mcp() -> int:
    """`claude mcp get|add|remove` against $FAKE_STATE/claude_mcp.json (what the real CLI prints, in short)."""
    f = STATE / "claude_mcp.json"
    servers = json.loads(f.read_text()) if f.is_file() else {}
    record()
    if ARGS[1:2] == ["get"]:
        s = servers.get(ARGS[2])
        if not s:
            out(f"No MCP server found with name: {ARGS[2]}"); return 1
        if s.get("command"):                          # stdio
            out(f"{ARGS[2]}:\n  Scope: User config (available in all your projects)\n  Type: stdio\n  Command: "
                f"{s['command']}\n  Args: {' '.join(s['args'])}\n  Environment:\n"
                + "".join(f"    {k}={v}\n" for k, v in s["env"].items()))
            return 0
        out(f"{ARGS[2]}:\n  Scope: User config (available in all your projects)\n  Type: http\n  URL: {s['url']}")
        return 0
    if ARGS[1:2] == ["add"]:
        head, cmd = (ARGS[2:ARGS.index("--")], ARGS[ARGS.index("--") + 1:]) if "--" in ARGS else (ARGS[2:], [])
        env = {head[i + 1].split("=", 1)[0]: head[i + 1].split("=", 1)[1] for i, a in enumerate(head)
               if a in ("-e", "--env")}
        pos = [a for i, a in enumerate(head) if not a.startswith("-")
               and (i == 0 or head[i - 1] not in ("--transport", "--scope", "-s", "-t", "-e", "--env"))]
        name = pos[0]
        if name in servers:
            sys.stderr.write(f"MCP server {name} already exists in user config\n"); return 1
        if cmd:
            servers[name] = {"command": cmd[0], "args": cmd[1:], "env": env, "argv": ARGS}
            f.write_text(json.dumps(servers))
            out(f"Added stdio MCP server {name} with command: {' '.join(cmd)} to user config"); return 0
        url = pos[1]
        servers[name] = {"url": url, "argv": ARGS}
        f.write_text(json.dumps(servers))
        out(f"Added HTTP MCP server {name} with URL: {url} to user config"); return 0
    if ARGS[1:2] == ["remove"]:
        servers.pop(ARGS[2], None)
        f.write_text(json.dumps(servers))
        out(f"Removed MCP server {ARGS[2]}"); return 0
    out("fake claude mcp: unsupported"); return 2


def relay_turn(engine: str, prompt: str | None = None) -> int:
    """The production of `slop relay`, played: for each message in the prompt it runs `slop relay say "heard #N: ..."`
    through the `slop` on PATH (the relay's shim), plus `relay ask` when a message ends with "?". $FAKE_RELAY_SLEEP
    (seconds) makes the turn slow; $FAKE_RELAY_FAIL=1 ends it with an error; $FAKE_RELAY_SHOW = a file for --show."""
    import re
    import shutil
    import subprocess
    if prompt is None:
        prompt = sys.stdin.read()
    resume = ARGS[ARGS.index("--resume") + 1] if "--resume" in ARGS else None
    if engine == "codex" and ARGS[1:2] == ["resume"]:
        resume = ARGS[-2]
    sid = resume or str(uuid.uuid4())
    msgs = re.findall(r"--- message #(\d+) from [^\n]*---\n(.*?)\n--- end of message #\1 ---", prompt, re.S)
    record(relay=True, session=sid, resumed=bool(resume), messages=[int(m[0]) for m in msgs],
           cwd=os.getcwd(), slop=shutil.which("slop"), turn=os.environ.get("SLOP_RELAY_TURN"))
    if os.environ.get("FAKE_REJECT_EFFORT"):         # $FAKE_REJECT_EFFORT: this engine takes no effort level
        if engine == "claude" and "--effort" in ARGS:
            sys.stderr.write("error: unknown option '--effort'" + chr(10))
            return 1
        if engine == "codex" and any("model_reasoning_effort" in a for a in ARGS):
            out(json.dumps({"type": "thread.started", "thread_id": sid}))
            out(json.dumps({"type": "turn.failed", "error": {"message": "Unsupported value: 'xhigh' is not "
                                                                        "supported with this model (reasoning.effort)"}}))
            return 1
    if engine == "claude":
        out(json.dumps({"type": "system", "subtype": "init", "session_id": sid, "model": "fake-opus",
                        "mcp_servers": [{"name": "claudia", "status": "connected"}], "tools": ["Bash"]}))
    else:
        out(json.dumps({"type": "thread.started", "thread_id": sid}))
    time.sleep(float(os.environ.get("FAKE_RELAY_SLEEP") or 0))
    if os.environ.get("FAKE_RELAY_FAIL"):
        if engine == "claude":
            out(json.dumps({"type": "result", "subtype": "error_during_execution", "is_error": True,
                            "result": "fake failure: usage limit reached", "session_id": sid}))
        else:
            out(json.dumps({"type": "turn.failed", "error": {"message": "fake failure: usage limit reached"}}))
        return 1
    for mid, text in msgs:
        argv = ["slop", "relay", "say", f"heard #{mid}: {text}"]
        if os.environ.get("FAKE_RELAY_SHOW"):
            argv += ["--show", os.environ["FAKE_RELAY_SHOW"]]
        ask = [["slop", "relay", "ask", "Which one?", "--default", "A"]] if text.rstrip().endswith("?") else []
        cmds = [argv] + ask
        for c in cmds:
            if engine == "claude":
                out(json.dumps({"type": "assistant", "session_id": sid, "message": {"content": [
                    {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": " ".join(c)}}]}}))
            else:
                out(json.dumps({"type": "item.started",
                                "item": {"type": "command_execution", "command": " ".join(c)}}))
            exe = shutil.which(c[0])
            r = subprocess.run([exe] + c[1:], capture_output=True, text=True)
            record(relay_cmd=c, rc=r.returncode, err=r.stderr[-300:])
    if engine == "claude":
        out(json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "Posted.", "num_turns": 2,
                        "session_id": sid}))
    else:
        out(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "Posted."}}))
        out(json.dumps({"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 5}}))
    return 0


# --------------------------------------------------------------------------------------------------- codex
def app_server() -> int:
    for line in sys.stdin:
        try:
            m = json.loads(line)
        except ValueError:
            continue
        i, meth = m.get("id"), m.get("method")
        if i is None:
            continue
        if meth == "initialize":
            res = {"userAgent": "fake/0.160.0", "codexHome": os.environ.get("CODEX_HOME", "~/.codex")}
        elif meth == "account/read":
            res = ({"account": {"type": "chatgpt", "email": "user@example.com", "planType": "pro"},
                    "requiresOpenaiAuth": True} if logged("codex") else {"account": None, "requiresOpenaiAuth": True})
        elif meth == "account/rateLimits/read":
            if not logged("codex"):
                out(json.dumps({"error": {"code": -32600, "message": "codex account authentication required to read "
                                          "rate limits"}, "id": i})); continue
            res = {"rateLimits": {"limitId": "codex", "primary": {"usedPercent": 18.0, "windowDurationMins": 300,
                                                                  "resetsAt": 1790000000},
                                  "secondary": {"usedPercent": 42.5, "windowDurationMins": 10080, "resetsAt": 1790500000},
                                  "planType": "pro"}}
        else:
            out(json.dumps({"error": {"code": -32601, "message": "unknown"}, "id": i})); continue
        out(json.dumps({"id": i, "result": res}))
    return 0


def image_exec() -> int:
    prompt = sys.stdin.read()
    record(stdin_head=prompt[:400], codex_home=os.environ.get("CODEX_HOME"))
    mode = os.environ.get("FAKE_CODEX_IMG", "ok")
    tid = str(uuid.uuid4())
    out(json.dumps({"type": "thread.started", "thread_id": tid}))
    out(json.dumps({"type": "turn.started"}))
    if mode == "limit":
        out(json.dumps({"type": "turn.failed", "error": {"message": "You've hit your usage limit. Try again at 5:00 PM."}}))
        return 1
    if mode == "slow":
        time.sleep(60); return 0
    if mode == "noimage":
        out(json.dumps({"type": "item.completed", "item": {"id": "item_0", "type": "agent_message",
                                                           "text": "I can't make that image."}}))
        out(json.dumps({"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 5}})); return 0
    d = Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex")) / "generated_images" / tid
    d.mkdir(parents=True, exist_ok=True)
    f = d / "ig_0001.png"
    out(json.dumps({"type": "item.started", "item": {"id": "item_1", "type": "image_generation", "status": "in_progress"}}))
    f.write_bytes(png())
    if mode == "nosaved":
        out(json.dumps({"type": "item.completed", "item": {"id": "item_2", "type": "agent_message", "text": "Done."}}))
    else:
        out(json.dumps({"type": "item.completed", "item": {"id": "item_1", "type": "image_generation", "saved_path": str(f),
                                                           "revised_prompt": "a revised prompt"}}))
        out(json.dumps({"type": "item.completed", "item": {"id": "item_2", "type": "agent_message", "text": f"SAVED {f}"}}))
    o = ARGS[ARGS.index("-o") + 1] if "-o" in ARGS else None
    if o:
        Path(o).write_text("Done." if mode == "nosaved" else f"SAVED {f}")
    out(json.dumps({"type": "turn.completed", "usage": {"input_tokens": 900, "output_tokens": 30}}))
    return 0


def codex() -> int:
    if ARGS[:1] == ["--version"]:
        out(VERSIONS["codex"]); return 0
    if ARGS[:2] == ["login", "status"]:
        if logged("codex"):
            out("Logged in using ChatGPT"); return 0
        sys.stderr.write("Not logged in\n"); return 1
    if ARGS[:1] == ["login"] and "--device-auth" in ARGS:
        record()
        out("\nWelcome to Codex [v0.160.0]\nOpenAI's command-line coding agent\n")
        out("Follow these steps to sign in with ChatGPT using device code authorization:\n")
        out("1. Open this link in your browser and sign in to your account\n   https://auth.openai.com/codex/device\n")
        out("2. Enter this one-time code (expires in 15 minutes)\n   ABCD-EFGHI\n")
        if wait_for(STATE / "codex_approve", float(os.environ.get("FAKE_APPROVE_WAIT", "60"))):
            (STATE / "codex_logged_in").write_text("1")
            out("Successfully logged in"); return 0
        out("Error: device code expired"); return 1
    if ARGS[:1] == ["app-server"]:
        return app_server()
    if ARGS[:1] == ["exec"]:
        if os.environ.get("FAKE_RELAY"):
            return relay_turn("codex")
        if os.environ.get("FAKE_ROUTE_ENGINE"):
            to_engine("codex")
        return image_exec()
    out("fake codex: unsupported " + " ".join(ARGS)); return 2


# --------------------------------------------------------------------------------------------------- muse
def muse() -> int:
    if ARGS[:1] in (["--version"], ["-V"]):
        out(VERSIONS["muse"]); return 0
    if ARGS[:1] == ["login"]:
        record()
        out("Open this page to sign in:\n  https://auth.meta.com/oauth/device/?code=WXYZ-ABCD\nconfirm this code matches:\n"
            "  WXYZ-ABCD\n\nWaiting for approval…")
        if wait_for(STATE / "muse_approve", float(os.environ.get("FAKE_APPROVE_WAIT", "60"))):
            f = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")) / "muse" / "auth.json"
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps({"schema_version": 1, "providers": {"meta": {"access_token": "x", "refresh_token": "y"}}}))
            out("Logged in."); return 0
        return 1
    if ARGS[:1] == ["exec"] and os.environ.get("FAKE_ROUTE_ENGINE"):
        to_engine("muse")
    out("fake muse: unsupported " + " ".join(ARGS)); return 2


# --------------------------------------------------------------------------------------------------- gemini
def gemini() -> int:
    if ARGS[:1] in (["--version"], ["-v"]):
        out(VERSIONS["gemini"]); return 0
    if "-p" in ARGS:
        if os.environ.get("FAKE_ROUTE_ENGINE"):
            to_engine("gemini")
        out("fake gemini: no route"); return 2
    if not sys.stdin.isatty():
        sys.stderr.write("Manual authorization is required but the current session is non-interactive.\n"); return 41
    record()
    out("Please visit the following URL to authorize the application:\n\nhttps://accounts.google.com/o/oauth2/v2/auth?"
        "redirect_uri=https%3A%2F%2Fcodeassist.google.com%2Fauthcode&state=s1\n\nEnter the authorization code: ", end="")
    code = sys.stdin.readline().strip()
    if code == os.environ.get("FAKE_GEMINI_CODE", "4/good-gemini-code-123"):
        d = Path(os.environ.get("GEMINI_CLI_HOME") or Path.home()) / ".gemini"
        d.mkdir(parents=True, exist_ok=True)
        (d / "google_accounts.json").write_text(json.dumps({"active": "user@example.com", "old": []}))
        (d / "oauth_creds.json").write_text(json.dumps({"access_token": "x", "refresh_token": "y"}))
        out("Authentication succeeded")
        time.sleep(120); return 0                       # the interactive UI keeps running
    out("Failed to authenticate with authorization code:invalid_grant"); return 1


sys.exit({"claude": claude, "codex": codex, "muse": muse, "gemini": gemini}[ENGINE]())

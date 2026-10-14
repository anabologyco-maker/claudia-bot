"""Engine facts and binary discovery for `slop agents`.

Facts verified against the real CLIs on Linux (2026-10-01; installed into a throwaway SLOP_HOME, never logged in):

  claude  Claude Code 2.1.287 (official installer https://claude.ai/install.sh -> ~/.local/bin/claude ->
          ~/.local/share/claude/versions/<v>; npm @anthropic-ai/claude-code gave an older 2.1.197, so the installer is
          the default). `claude auth login --claudeai` with BROWSER=false prints
          "If the browser didn't open, visit: https://claude.com/cai/oauth/authorize?..." then "Paste code here if
          prompted >" and waits for the code on stdin (works with plain pipes). `claude auth status --json` prints
          {"loggedIn": false, "authMethod": "none", ...} and exits 1 when logged out; with CLAUDE_CODE_OAUTH_TOKEN set
          it reports {"loggedIn": true, "authMethod": "oauth_token"} (offline: the token is not checked).
  codex   codex-cli 0.160.0 (npm @openai/codex; bin -> codex.js, a node script). `codex login --device-auth` prints
          https://auth.openai.com/codex/device and a one-time code like ABCD-EFGHI ("expires in 15 minutes"), then
          waits until the user approves. `codex login status` exits 1 ("Not logged in") when logged out.
          `codex app-server --listen stdio://` answers initialize / account/read / account/rateLimits/read
          (JSON-RPC lines) in about 0.2 s.
  muse    Muse Code 1.4.2 (installer https://dev.meta.ai/install.sh; MUSE_INSTALL_DIR puts the launcher and its
          versioned binary in one folder, MUSE_NO_MODIFY_PATH=1 leaves shell profiles alone, MUSE_NO_AUTO_UPDATE=1
          stops self-updates). `muse login` = "Log in with your Meta account: approve a code in your browser": it
          prints https://auth.meta.com/oauth/device/?code=... and the code, then "Waiting for approval...".
          META_API_KEY always takes priority over the account login.
  gemini  Gemini CLI 0.62.0 (npm @google/gemini-cli, needs Node 20+). Headless (-p) refuses a manual sign-in
          ("Manual authorization is required but the current session is non-interactive"); the interactive CLI under
          a pseudo-terminal with NO_BROWSER=true prints "Please visit the following URL to authorize the
          application: https://accounts.google.com/..." and "Enter the authorization code:". Or GEMINI_API_KEY.
          Headless runs need --skip-trust (or GEMINI_CLI_TRUST_WORKSPACE=true) outside a trusted folder.

Layout under $SLOP_HOME (/workspace/.claudia on the bot's computer). Only /workspace is verified to survive a
computer update there ("installed apps and packages are removed"), so every engine's COMMAND lives under it:
  bin/<engine>      a symlink to the real CLI (bin/ is on PATH via $SLOP_HOME/env.sh)
  npm/              the npm prefix for npm installs (npm/bin/<engine>, npm/lib/node_modules/...)
  muse/             Muse Code's launcher + binary
  claude/versions/<v>/claude   on the bot's computer only: a copy of the native Claude Code binary (the official
                    installer puts it in ~/.local, outside /workspace; the binary is self-contained and runs from here)
  agents/           login sessions (agents/login/<engine>/), install logs, test jobs, box job slots
The engines' SIGN-INS stay where each CLI keeps them, in the home folder (~/.claude, ~/.codex, ~/.gemini,
~/.config/muse). The platform says logins are kept on an update, but that is not verified for these files: if a reset
clears them, `slop agents status` shows "not signed in" and `slop agents login ENGINE` signs in again.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
from pathlib import Path

from ..config import SlopError, on_box, slop_home

ENGINES = ("claude", "codex", "muse", "gemini")
ALIASES = {"claude-code": "claude", "claudecode": "claude", "cc": "claude", "chatgpt": "codex", "openai": "codex",
           "muse-code": "muse", "musecode": "muse", "meta": "muse", "gemini-cli": "gemini", "google": "gemini"}
WIN = os.name == "nt"

# Env vars that switch an engine from the user's plan to pay-per-token API billing (stripped for plan runs).
BILLING_ENV = {
    "claude": ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "CLAUDE_CODE_USE_BEDROCK",
               "CLAUDE_CODE_USE_VERTEX"),
    "codex": ("OPENAI_API_KEY", "CODEX_API_KEY", "OPENAI_BASE_URL"),
    "muse": ("META_API_KEY",),
    "gemini": ("GOOGLE_API_KEY",),      # GEMINI_API_KEY is one of Gemini's two documented sign-ins (SIGNIN_ENV)
}
# Each engine's own sign-in variables (a plan token or the key the user chose as the sign-in). They reach ONLY that
# engine: another vendor's agent (which may run shell commands) never sees the user's Claude plan token.
SIGNIN_ENV = {
    "claude": ("CLAUDE_CODE_OAUTH_TOKEN",),
    "codex": (),
    "muse": (),
    "gemini": ("GEMINI_API_KEY",),
}
# One-time sign-in codes from the secure card: typed into the waiting login only (through the keeper's FIFO), never
# handed to any engine run.
LOGIN_CODE_ENV = ("CLAUDE_LOGIN_CODE", "GEMINI_LOGIN_CODE")
# Set by a parent Claude Code session; a child CLI must not see them (it would attach to the parent).
PARENT_SESSION_RE = re.compile(r"^(CLAUDECODE|CLAUDE_CODE_(ENTRYPOINT|SESSION_ID|CHILD_SESSION|HOST_SESSION_ID|"
                               r"OAUTH_SCOPES|SDK_HAS_HOST_AUTH_REFRESH|MESSAGING_\w+))$")
# The toolkit's own secrets never reach an agent CLI.
TOOLKIT_SECRETS = ("OPENROUTER_API_KEY", "HIGGSFIELD_API_KEY", "HEDRA_API_KEY", "ARENA_TOKEN")


def other_engines_env(engine: str) -> set[str]:
    """Credential variables of every OTHER engine (their API keys and sign-in tokens) + Google's second key name."""
    out: set[str] = set()
    for e in ENGINES:
        if e != engine:
            out.update(BILLING_ENV.get(e, ()))
            out.update(SIGNIN_ENV.get(e, ()))
    if engine != "gemini":
        out.add("GOOGLE_API_KEY")
    return out - set(SIGNIN_ENV.get(engine, ())) - set(BILLING_ENV.get(engine, ()))

SPEC: dict[str, dict] = {
    "claude": {
        "title": "Claude Code", "plan": "a Claude plan (Pro or Max)", "bin": "claude",
        "signin": "their Claude account (Pro or Max plan)",
        "methods": ("native", "npm"), "default_method": "native",
        "installer": "https://claude.ai/install.sh", "installer_ps1": "https://claude.ai/install.ps1",
        "npm": "@anthropic-ai/claude-code", "node_min": 18,
        "login": "paste", "login_args": ["auth", "login", "--claudeai"], "login_env": {"BROWSER": "false"},
        "code_secret": "CLAUDE_LOGIN_CODE", "token_env": "CLAUDE_CODE_OAUTH_TOKEN",
        "url_re": r"(https://\S+/oauth/authorize\?\S+)\s",
        "docs": "https://code.claude.com/docs",
    },
    "codex": {
        "title": "Codex CLI", "plan": "a ChatGPT plan (Plus, Pro, Business, Edu or Enterprise)", "bin": "codex",
        "signin": "their ChatGPT account (Plus, Pro, Business, Edu or Enterprise plan)",
        "methods": ("npm",), "default_method": "npm", "npm": "@openai/codex", "node_min": 18,
        "login": "device", "login_args": ["login", "--device-auth", "-c", 'forced_login_method="chatgpt"'],
        "login_env": {},
        "url_re": r"(https://auth\.openai\.com/\S+)\s", "code_re": r"\b([A-Z0-9]{4}-[A-Z0-9]{4,6})\b",
        "docs": "https://developers.openai.com/codex",
    },
    "muse": {
        "title": "Muse Code", "plan": "a Meta account with Muse Code access", "bin": "muse",
        "signin": "their Meta account",
        "methods": ("native",), "default_method": "native", "installer": "https://dev.meta.ai/install.sh",
        "login": "device", "login_args": ["login"], "login_env": {"BROWSER": "false", "MUSE_NO_AUTO_UPDATE": "1"},
        "url_re": r"(https://\S+/oauth/device/?\S*)\s", "code_re": r"\b([A-Z0-9]{4}-[A-Z0-9]{4})\b",
        "docs": "https://dev.meta.ai",
    },
    "gemini": {
        "title": "Gemini CLI", "plan": "a Google account (free tier or a Gemini plan), or a GEMINI_API_KEY",
        "signin": "their Google account",
        "bin": "gemini", "methods": ("npm",), "default_method": "npm", "npm": "@google/gemini-cli", "node_min": 20,
        "login": "paste-pty", "login_args": [], "login_env": {"NO_BROWSER": "true", "GEMINI_CLI_TRUST_WORKSPACE": "true"},
        "code_secret": "GEMINI_LOGIN_CODE", "key_env": "GEMINI_API_KEY",
        "url_re": r"(https://accounts\.google\.com/\S+)\s",
        "docs": "https://geminicli.com/docs",
    },
}


def norm_engine(name: str | None, allow_all: bool = False) -> str:
    n = (name or "").strip().lower()
    n = ALIASES.get(n, n)
    if n in ENGINES or (allow_all and n == "all"):
        return n
    choices = "|".join(ENGINES) + ("|all" if allow_all else "")
    raise SlopError(f"unknown agent {name!r}: use one of {choices} (claude = Claude Code, codex = Codex with a ChatGPT "
                    "plan, muse = Muse Code, gemini = Gemini CLI)")


# ------------------------------------------------------------------------------------------------------------ paths
def agents_dir() -> Path:
    return slop_home() / "agents"


def bin_dir() -> Path:
    return slop_home() / "bin"


def npm_prefix() -> Path:
    return slop_home() / "npm"


def npm_bin_dir() -> Path:
    return npm_prefix() if WIN else npm_prefix() / "bin"


def muse_dir() -> Path:
    return slop_home() / "muse"


def native_bin(engine: str) -> Path:
    """Where the engine's own installer puts its command."""
    if engine == "muse":
        return muse_dir() / ("muse.cmd" if WIN else "muse")
    return Path.home() / ".local" / "bin" / ("claude.exe" if WIN else "claude")


def claude_versions_dir() -> Path:
    """$SLOP_HOME/claude/versions: the bot's computer keeps its copy of the native Claude Code binary here."""
    return slop_home() / "claude" / "versions"


def kept_claude() -> Path | None:
    """The newest copy under $SLOP_HOME/claude/versions/<v>/claude, or None."""
    d = claude_versions_dir()
    try:
        cands = [p / "claude" for p in d.iterdir() if (p / "claude").is_file()]
    except OSError:
        return None
    return max(cands, key=lambda p: p.stat().st_mtime) if cands else None


def _exts() -> tuple[str, ...]:
    return (".exe", ".cmd", ".bat", "") if WIN else ("",)


def candidates(engine: str) -> list[tuple[Path, str]]:
    """Where to look, in order: $SLOP_HOME/bin (our links), our npm prefix, the native install place, PATH."""
    name = SPEC[engine]["bin"]
    out: list[tuple[Path, str]] = []
    for d, via in ((bin_dir(), "slop_home/bin"), (npm_bin_dir(), "slop_home/npm")):
        out += [(d / (name + e), via) for e in _exts()]
    if engine == "claude" and not WIN:
        kept = kept_claude()
        if kept:
            out.append((kept, "slop_home/claude"))
    if engine in ("claude", "muse"):
        out.append((native_bin(engine), "native"))
    if engine == "muse":
        out.append((Path.home() / ".local" / "bin" / "muse", "native"))
    w = shutil.which(name)
    if w:
        out.append((Path(w), "PATH"))
    return out


def _usable(p: Path) -> bool:
    try:
        return p.is_file() and (WIN or os.access(p, os.X_OK))
    except OSError:
        return False


def find(engine: str) -> dict | None:
    """{"path", "via", "real", "argv"} for the first usable binary, or None. A dangling link is skipped."""
    for p, via in candidates(engine):
        if _usable(p):
            real = Path(os.path.realpath(p))
            return {"path": str(p), "via": via, "real": str(real), "argv": command(p)}
    return None


def survives_update(path: str) -> bool:
    """On the bot's computer only /workspace is verified to survive a computer update (installed apps and packages are
    removed; the home folder is not counted on), so only a command under /workspace or $SLOP_HOME counts there.
    Elsewhere (the user's own computer): always True."""
    if not on_box():
        return True
    real = os.path.realpath(path)
    roots = ["/workspace", os.path.realpath(str(slop_home()))]
    return any(real == r or real.startswith(r.rstrip("/") + "/") for r in roots)


def command(p: Path | str) -> list[str]:
    """argv prefix that runs a CLI: node scripts (codex.js, gemini.js) run through node directly, so a minimal PATH
    without `node` (or a Windows .cmd shim) cannot break them."""
    real = os.path.realpath(str(p))
    if real.endswith((".js", ".mjs", ".cjs")):
        node = node_path()
        if node:
            return [node, real]
    return [str(p)]


def node_path() -> str | None:
    return shutil.which("node")


def node_info() -> dict:
    node = node_path()
    if not node:
        return {"path": None, "version": None, "major": 0}
    from .. import util
    rc, out, _ = util.run([node, "--version"], timeout=15)
    v = out.strip() if rc == 0 else None
    m = re.match(r"v?(\d+)", v or "")
    return {"path": node, "version": v, "major": int(m.group(1)) if m else 0}


# -------------------------------------------------------------------------------------------------------------- env
def base_env(engine: str, plan_only: bool = True, extra: dict | None = None) -> dict:
    """Environment for running an engine's CLI: our bin dirs first on PATH; parent-session variables, the toolkit's
    secrets, one-time login codes and every OTHER engine's keys and tokens removed; and (plan_only) this engine's
    API-key variables that would bill per token instead of the user's plan."""
    env = dict(os.environ)
    others = other_engines_env(engine)
    for k in list(env):
        if PARENT_SESSION_RE.match(k) or k in TOOLKIT_SECRETS or k in LOGIN_CODE_ENV or k in others:
            env.pop(k, None)
    if plan_only:
        for k in BILLING_ENV.get(engine, ()):
            env.pop(k, None)
    path = [str(bin_dir()), str(npm_bin_dir())]
    node = node_path()
    if node:
        path.append(str(Path(node).parent))
    env["PATH"] = os.pathsep.join(path + [env.get("PATH", "")])
    env["SLOP_HOME"] = str(slop_home())
    env["MUSE_NO_AUTO_UPDATE"] = "1"
    if engine == "claude" and on_box():
        env.setdefault("DISABLE_AUTOUPDATER", "1")      # the kept copy is updated by `slop agents install --upgrade`
    env.update({k: str(v) for k, v in (extra or {}).items()})
    return env


def run_cli(engine: str, args: list[str], timeout: float = 30, plan_only: bool = True, extra_env: dict | None = None,
            cwd: str | None = None) -> tuple[int, str, str]:
    """Run the engine's CLI; (127, "", why) when it is not installed. Never raises."""
    from .. import util
    b = find(engine)
    if not b:
        return 127, "", f"{SPEC[engine]['title']} is not installed"
    return util.run(b["argv"] + list(args), timeout=timeout, env=base_env(engine, plan_only, extra_env), cwd=cwd)


def version(engine: str) -> str | None:
    """The CLI's version number ("2.1.287", "0.160.0", "1.4.2"), or its first --version line; None when it does not run."""
    rc, out, err = run_cli(engine, ["--version"], timeout=30)
    if rc != 0:
        return None
    line = (out.strip() or err.strip()).splitlines()
    if not line:
        return None
    m = re.search(r"\d+\.\d+(?:\.\d+)?(?:-[\w.]+)?", line[0])
    return m.group(0) if m else line[0].strip()[:80]


def link(engine: str, target: Path) -> Path | None:
    """$SLOP_HOME/bin/<engine> -> target (replaced if it points elsewhere). None on Windows (no symlinks without
    admin rights: `find` searches the npm prefix and the native place there instead)."""
    if WIN:
        return None
    d = bin_dir()
    d.mkdir(parents=True, exist_ok=True)
    dst = d / SPEC[engine]["bin"]
    try:
        if dst.is_symlink() or dst.exists():
            if dst.is_symlink() and os.readlink(dst) == str(target):
                return dst
            dst.unlink()
        dst.symlink_to(target)
    except OSError as e:
        raise SlopError(f"could not link {dst} -> {target}: {e}. Check that {d} is writable.") from e
    return dst


def keep_claude_copy(src: Path, ver: str) -> Path:
    """Bot's computer: copy the native Claude Code binary (the file ~/.local/bin/claude points at) to
    $SLOP_HOME/claude/versions/<ver>/claude, so a computer update that removes ~/.local keeps it. Verified: the copied
    binary runs from there (`--version`, `auth status`). Keeps the two newest copies."""
    real = Path(os.path.realpath(str(src)))
    if real.suffix in (".js", ".mjs", ".cjs"):
        raise SlopError(f"{src} is a node script, not the native Claude Code binary: install with the default method "
                        "(slop agents install claude --upgrade)")
    vdir = claude_versions_dir() / re.sub(r"[^\w.-]", "_", ver or "unknown")
    dst = vdir / "claude"
    if dst.is_file() and real == dst.resolve():
        return dst
    try:
        vdir.mkdir(parents=True, exist_ok=True)
        tmp = vdir / ".claude.slop-tmp"
        shutil.copyfile(real, tmp)
        tmp.chmod(0o755)
        tmp.replace(dst)
    except OSError as e:
        raise SlopError(f"could not keep a copy of Claude Code in {vdir}: {e}. Check the free space on /workspace, then "
                        "run `slop agents install claude` again.") from e
    try:
        olds = sorted((p for p in claude_versions_dir().iterdir() if p.is_dir() and p != vdir),
                      key=lambda p: p.stat().st_mtime, reverse=True)
        for p in olds[1:]:
            shutil.rmtree(p, ignore_errors=True)
    except OSError:
        pass
    return dst


def config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))


def claude_config_dir() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or (Path.home() / ".claude"))


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex"))


def gemini_dir() -> Path:
    return Path(os.environ.get("GEMINI_CLI_HOME") or Path.home()) / ".gemini"


def muse_auth_file() -> Path:
    return Path(os.environ.get("MUSE_AUTH_PATH") or (config_home() / "muse" / "auth.json"))


def read_json_quiet(p: Path) -> dict | None:
    try:
        d = json.loads(Path(p).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def gemini_settings_set(auth_type: str) -> Path:
    """Merge security.auth.selectedType into ~/.gemini/settings.json (keeps every other setting)."""
    f = gemini_dir() / "settings.json"
    data = read_json_quiet(f) or {}
    data.setdefault("security", {}).setdefault("auth", {})["selectedType"] = auth_type
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_name(f.name + ".slop-tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(f)
    return f


def python() -> str:
    return sys.executable

"""The onboarding checklist: item catalogue, each item's state for a tier, the next item, tier readiness, unlocks.

`report()` gathers the probes (slop/onboard/probes.py; the slow ones run in parallel) and `build()` turns them plus
onboard.json into items. `build`, `pick_next`, `readiness`, `stuck` and `unlocks` are pure functions of their inputs,
so tests feed them probe results directly.

State of an item for a tier (the item functions below return a raw state; `_finalize` applies the tier):
  done      measured or recorded as working
  todo      needed (required or recommended) for this tier and not done
  optional  not needed for this tier (or skipped by the user: `slop onboard mark ID --skip`)
  blocked   waits for another item (`blocked_by`), or not available in this toolkit version (`available: false`)
  error     measured as broken (a failing doctor check, a rejected or expired key, an offline GPU worker ...)

`next` = the first item in the priority order (`report()["priority"]`: PRIORITY with the agent items ordered by the
user's own engines) that is todo, or an error on an item the tier needs; items whose install is running right now are
passed over (the bot does something else meanwhile). "All set" means the tier is READY (`tiers[tier].ready`) and
nothing is left to pick; a tier that cannot become ready right now (a required item skipped, blocked or installing)
is reported with `stuck` reasons instead, never as all set.

Questions first: the tier (`tier`), the user's coding-agent plans (`coding-agents`) and the home GPU (`gpu`) are
asked once (each carries ask + answers, one exact command per answer), so agents and the GPU are offered in every tier.

Tier readiness (owner decision 2026-10-02, after the live Quick run inside a Grok Bot):
  quick     toolkit + doctor. No account at all: stills from Grok's own image tool (GenerateImage), motion = 2.5D +
            devices, the song = the user's upload (Lyria only when OpenRouter exists). OpenRouter / Higgsfield only add
            routes (API stills, clips, Lyria), so both are recommended, never required.
  studio    quick + full-profile + `video` = OpenRouter OR Higgsfield (either one; both recommended: OpenRouter is
            cheaper per second, Higgsfield copies the vocals more reliably on stubborn windows). The last route left
            (the other one skipped) becomes required. An expired OpenRouter key is no route (it still passes the
            free key check). Quick with both routes skipped: video, api-images and lyria are declined, not blocked.
  director  studio + one Director-capable coding agent signed in, on the box or on the user's own computer.
`routes()` says what works now (stills, clips, song) and `install_summary()` whether the toolkit is ready, installing
or still to install (so the setup never announces an install that is already done).
"""
from __future__ import annotations

import functools
import os
import re
import shlex
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from .. import util
from ..config import SlopError, toolkit_root
from . import probes
from . import state as st

TIERS = st.TIERS
TIER_INDEX = {t: i for i, t in enumerate(TIERS)}
STATES = ("done", "todo", "error", "blocked", "optional")
NEED = {"r": "required", "c": "recommended", "o": "optional"}
GROUPS = [("start", "Start"), ("toolkit", "Toolkit"), ("keys", "Keys (secure secret card)"),
          ("connectors", "Connectors"), ("music", "Music"), ("stills", "Stills"),
          ("agents-box", "Coding agents on the box"), ("agents-home", "Coding agents on your own computer"),
          ("gpu", "Home GPU"), ("taste", "Taste"), ("project", "Project")]
ENGINES = st.AGENT_ENGINES
ENGINE_NAMES = {"claude": "Claude Code", "codex": "Codex", "muse": "Muse Code", "gemini": "Gemini CLI"}
PLAN_NAMES = {"claude": "Claude (Claude Code)", "codex": "ChatGPT (Codex)", "muse": "Meta (Muse Code)",
              "gemini": "Google (Gemini CLI)"}
# the engines runner/deleg.mjs drove before it learned Gemini: used only when the runner cannot be read
FALLBACK_DIRECTOR_ENGINES = ("claude", "codex", "muse")
TASTE_TAPS = 150                                 # the recommended first session (docs/30-taste)
HAND_OFF = {"quick": "claudia-relay", "studio": "claudia-relay", "director": "claudia-relay"}
# skills planned for this phase; until the repository ships them, the closest existing skill is named instead, or
# none at all (setup-agents / setup-gpu: no existing skill covers `slop agents` / `slop gpu`; their commands print
# their own next step)
SKILL_FALLBACK = {"setup-accounts": "claudia-setup", "setup-agents": None, "setup-gpu": None}
PAID_SUNO = ("pro", "premier")
PAID_MJ = ("basic", "standard", "pro", "mega")
SYMBOL = {"done": "[x]", "todo": "[ ]", "optional": "[-]", "blocked": "[~]", "error": "[!]"}
RECORD_WHEN = "ONLY after you saw it working yourself (the connector answered, the check showed the user signed in)"

# kind: check = measured on every call (cannot be marked done, only skipped); record = the bot records what it saw
# (`slop onboard mark`); plan = recorded with `slop onboard set`.  need = (quick, studio, director).
CATALOG = [
    dict(id="tier", group="start", title="Tier chosen", kind="plan", need="rrr",
         cost="free; the tier sets each new project's spend caps (change it any time)",
         unlocks="Tier chosen: the checklist shows what that tier needs"),
    dict(id="toolkit", group="toolkit", title="Toolkit installed", kind="check", need="rrr",
         cost="free; about 5 min (minimal install)", unlocks="Toolkit installed: every slop command runs here"),
    dict(id="path", group="toolkit", title="slop on PATH", kind="check", need="rrr",
         cost="free", unlocks="`slop` works in every new shell"),
    dict(id="doctor", group="toolkit", title="Machine check (slop doctor)", kind="check", need="rrr",
         cost="free; no network spend", unlocks="Machine ready: renders, analysis and encodes run here"),
    dict(id="full-profile", group="toolkit", title="Full analysis install", kind="check", need="crr",
         cost="free; about 5 min of downloads (CPU torch, demucs, transformers; 2-3 min measured on the box)",
         unlocks="Local stems and word-level alignment on CPU (no API cost for analysis)"),
    dict(id="openrouter", group="keys", title="OpenRouter key (OPENROUTER_API_KEY)", kind="check", need="ccc",
         cost="pay as you go; give the key its own credit limit (Quick $25, Studio $110, Director $160)",
         unlocks="API stills, sung and motion clips (the cheapest per second) and Lyria songs, capped by the key's "
                 "own limit"),
    dict(id="arena", group="keys", title="Are.na token (ARENA_TOKEN)", kind="check", need="ooo",
         cost="free", unlocks="Your own Are.na channels feed the taste profile"),
    dict(id="higgsfield", group="connectors", title="Higgsfield connector", kind="record", need="ccc",
         cost="your Higgsfield credits; every video is priced before it is made (get_cost)",
         unlocks="Higgsfield video: Seedance 2.5 sung clips (copies the vocals more reliably on stubborn windows), "
                 "Kling, Veo and more on your credits"),
    dict(id="hedra", group="connectors", title="Hedra (API or MCP)", kind="record", need="ooo",
         cost="Hedra live estimate: API USD wallet or MCP USD/credits; separate caps",
         unlocks="Seedance 2.5 sung and motion clips via --provider hedra; choose --hedra-transport api|mcp"),
    dict(id="drive", group="connectors", title="Google Drive connector", kind="record", need="ooo",
         cost="free", unlocks="Finished videos and big files sent to you as links in your own Google Drive (big "
                               "videos often fail as chat attachments)"),
    # derived: OpenRouter OR Higgsfield (the Studio and Director tiers need one of them)
    dict(id="video", group="connectors", title="Video clips (OpenRouter or Higgsfield)", kind="check", need="crr",
         cost="OpenRouter: Seedance 2.0 Mini 480p about $0.14 for 4 s, Seedance 2.5 about $0.10 a second at 480p; "
              "Higgsfield: about 3 credits a second (480p draft)",
         unlocks="Video clips: sung clips with measured lip sync and cheap motion clips"),
    dict(id="suno", group="music", title="Suno plan", kind="plan", need="occ",
         cost="your Suno plan; Free plan songs are for non-commercial use only",
         unlocks="Songs from your own Suno account (the bot writes paste-ready song packs)"),
    dict(id="suno-signin", group="music", title="Suno signed in (Grok's browser)", kind="record", need="ooo",
         cost="free; Suno's terms limit automated use (a one-line heads-up at sign-in)",
         unlocks="Grok makes Opus's songs on suno.com in its browser and saves both takes for Opus"),
    dict(id="lyria", group="music", title="Lyria songs (fallback)", kind="check", need="coo",
         cost="about $0.08 a full song, $0.04 a 30 s clip (OpenRouter)",
         unlocks="Songs without Suno: Lyria through OpenRouter"),
    dict(id="midjourney", group="stills", title="Midjourney plan", kind="plan", need="occ",
         cost="your Midjourney subscription",
         unlocks="Midjourney stills: the bot writes the prompt book, you paste, it ingests"),
    dict(id="mj-profile", group="stills", title="Midjourney personalization", kind="plan", need="ooo",
         cost="free; no code needed",
         unlocks="Your own Midjourney style, switched on with the P button when you want it (Opus asks per project)"),
    dict(id="mj-signin", group="stills", title="Midjourney signed in (Grok's browser)", kind="record", need="ooo",
         cost="free; Midjourney's terms limit automated use (a one-line heads-up at sign-in)",
         unlocks="Grok runs Opus's Midjourney prompts in its browser and saves every image for Opus"),
    dict(id="api-images", group="stills", title="API image models", kind="check", need="ccc",
         cost="from about $0.004 an image (gpt-image-2, low quality)",
         unlocks="Stills from API image models (no Midjourney needed)"),
    dict(id="codex-images", group="stills", title="ChatGPT-plan images (Codex)", kind="check", need="ooo",
         cost="no API cost: your ChatGPT plan's limits; 1-4 min an image",
         unlocks="Images on your ChatGPT plan, no API key"),
    dict(id="coding-agents", group="agents-box", title="Coding-agent plans", kind="plan", need="ccr",
         cost="free to record; the agents run on your own plans' limits (no API cost)",
         unlocks="Your coding-agent plans: the checklist sets up the matching agents"),
] + [
    dict(id=f"agent-{e}", group="agents-box", title=f"{ENGINE_NAMES[e]} on the box", kind="check", need="ooo",
         cost=cost, unlocks=unl)
    for e, cost, unl in (
        ("claude", "no API cost: your Claude plan's usage limits",
         "Claude Code logged in on the box: delegated storyboards, motion design and reviews"),
        ("codex", "no API cost: your ChatGPT plan's Codex limits",
         "Codex logged in on the box: delegated work and ChatGPT-plan images"),
        ("muse", "no API cost: your own Muse Code account's limits",
         "Muse Code logged in on the box: delegated work"),
        ("gemini", "Google sign-in, or GEMINI_API_KEY (billed by Google)",
         "Gemini CLI on the box: research and one-off jobs (--engine gemini; not the Director agent)"))
] + [
    dict(id=f"home-{e}", group="agents-home", title=f"{ENGINE_NAMES[e]} on your computer", kind="record",
         need="ooo", cost="your own plan; every command on your computer needs your approval in Grok Bot "
                          "(unless you chose Always allow)",
         unlocks=f"{ENGINE_NAMES[e]} on your own computer, reached through Grok Bot local exec")
    for e in ENGINES
] + [
    dict(id="gpu", group="gpu", title="Home GPU", kind="check", need="ccc",
         cost="free (your computer and electricity)",
         unlocks="Home GPU: stems, lyric alignment and depth maps on your own graphics card"),
    dict(id="taste", group="taste", title="Taste profile", kind="check", need="occ",
         cost="free; about 7 min of taps on your phone",
         unlocks="Taste profile: looks, fonts and prompts tuned to you, in every project"),
    dict(id="first-project", group="project", title="First project", kind="check", need="rrr",
         cost="free to create; its tier sets the spend caps",
         unlocks="First project: `slop status` leads every step from here"),
]
SPEC = {c["id"]: c for c in CATALOG}
ITEM_IDS = [c["id"] for c in CATALOG]
# the static order; report() puts the agent items in the user's engine order (see priority())
PRIORITY = ["tier", "toolkit", "path", "doctor", "openrouter", "higgsfield", "hedra", "api-images", "video", "suno", "lyria",
            "midjourney", "mj-profile", "full-profile", "coding-agents", "agent-claude", "agent-codex", "agent-muse",
            "agent-gemini", "home-claude", "home-codex", "home-muse", "home-gemini", "gpu", "first-project", "taste",
            "arena", "drive", "suno-signin", "mj-signin", "codex-images"]
# `video` is said by the tier unlocks and by openrouter / higgsfield themselves
HEADLINE = set(ITEM_IDS) - {"tier", "toolkit", "path", "doctor", "coding-agents", "video"}
# items that follow other items (done as soon as one of them is): never marked done by hand, never a step of their own
DERIVED = {"api-images": ("openrouter", "higgsfield"), "video": ("openrouter", "higgsfield", "hedra"),
           "lyria": ("openrouter",), "codex-images": ("agent-codex",)}
# the two ways to make clips: Studio and Director need one of them (item video), both are recommended
ROUTES = ("openrouter", "higgsfield")
ROUTE_NAMES = {"openrouter": "OpenRouter", "higgsfield": "Higgsfield"}
ROUTE_WHY = {"openrouter": "cheaper per second, plus API stills and Lyria songs",
             "higgsfield": "it copies the vocals more reliably on stubborn windows"}
BOTH_WHY = ("both recommended: OpenRouter is cheaper per second, Higgsfield copies the vocals more reliably on "
            "stubborn windows")
QUICK_BARE = ("Quick needs no account; stills come from Grok's image tool, motion is 2.5D with devices, the song is "
              "the user's upload")
# what works now (routes()): ids -> words
WAY_NAMES = {"openrouter": "OpenRouter", "higgsfield": "Higgsfield", "codex": "Codex (ChatGPT plan)",
             "midjourney": "Midjourney", "grok-image": "Grok's image tool", "upload": "your own upload",
             "lyria": "Lyria", "suno": "Suno"}
MISSING_LABEL = {"video": "video (OpenRouter or Higgsfield)"}
ALIASES = {"claude": "agent-claude", "codex": "agent-codex", "muse": "agent-muse", "gemini": "agent-gemini",
           "claude-code": "agent-claude", "muse-code": "agent-muse", "gemini-cli": "agent-gemini",
           "chatgpt": "agent-codex", "mj": "midjourney", "midjourney-plan": "midjourney", "mj-plan": "midjourney",
           "suno-plan": "suno", "hf": "higgsfield", "gdrive": "drive", "google-drive": "drive", "home-gpu": "gpu",
           "project": "first-project", "key": "openrouter", "openrouter-key": "openrouter", "are.na": "arena",
           "doctor-check": "doctor", "taste-profile": "taste", "install": "toolkit", "full": "full-profile",
           "agents": "coding-agents", "agent-plans": "coding-agents", "plans": "coding-agents", "clips": "video",
           "video-clips": "video"}
# checks that run on the user's OWN computer through Grok Bot local exec: (Windows PowerShell, Mac/Linux terminal,
# what "signed in" looks like). Each shows the sign-in, not just the install. Codex on Windows: codex.cmd, because
# PowerShell resolves codex.ps1 first and the default execution policy blocks scripts.
HOME_CHECK = {
    "claude": ("claude auth status --json", "claude auth status --json", 'it prints "loggedIn": true'),
    "codex": ("codex.cmd login status", "codex login status", 'it prints "Logged in using ChatGPT"'),
    "muse": ("Test-Path $HOME\\.config\\muse\\auth.json", "test -s ~/.config/muse/auth.json && echo signed-in",
             "True / signed-in (the Meta sign-in Muse Code saves after `muse login`)"),
    "gemini": ("Test-Path $HOME\\.gemini\\oauth_creds.json", "test -s ~/.gemini/oauth_creds.json && echo signed-in",
               "True / signed-in (a saved Google sign-in; or GEMINI_API_KEY is set on that computer)"),
}
HOME_LOGIN = {"claude": "claude auth login", "codex": "codex login", "muse": "muse login",
              "gemini": "gemini (then choose Sign in with Google)"}
LOGIN_DO = {
    "claude": "It prints a claude.ai sign-in link: the user opens it, approves and copies the code shown; ask for "
              "that code with the secure secret card (CLAUDE_LOGIN_CODE), never in chat. Or: the user runs `claude "
              "setup-token` on their own computer and you ask for CLAUDE_CODE_OAUTH_TOKEN with the secure secret card.",
    "codex": "It prints a URL and a one-time code: the user opens the URL, signs in with their ChatGPT account and "
             "enters the code (ChatGPT plan; no API key).",
    "muse": "It prints a Meta sign-in link or code: the user approves it in their own browser.",
    "gemini": "It prints a Google sign-in link: the user approves it; the code comes back only through the secure "
              "secret card. Or: ask for GEMINI_API_KEY with the secure secret card.",
}
TIER_ASK = ("Which tier do you want? Quick: needs no account - stills from my own image tool, 2.5D motion, your own "
            "song (an OpenRouter key adds API stills, cheap clips and Lyria songs), about $0-20 a video. Studio: sung "
            "clips with real lip sync through OpenRouter or Higgsfield (either; both is best), your own Suno and "
            "Midjourney, and the full analysis install, about $50-110. Director: Studio plus your own coding agent "
            "(Claude Code, Codex on a ChatGPT plan, or Muse Code) signed in, on my computer or yours, for storyboards "
            "and bespoke motion design. Unsure: Quick (it can change later).")
AGENTS_ASK = ("Which coding-agent plans do you have? Claude (Pro or Max: Claude Code), ChatGPT (Plus or Pro: Codex), "
              "Meta (Muse Code), Google (Gemini CLI), or none. The bot installs and signs in the matching agent on its "
              "own computer; it runs on the plan's own limits (no API cost).")
AGENTS_ANSWERS = {"claude": "slop onboard set coding-agents claude", "chatgpt": "slop onboard set coding-agents codex",
                  "muse": "slop onboard set coding-agents muse", "gemini": "slop onboard set coding-agents gemini",
                  "none": "slop onboard set coding-agents none"}
ANSWER_ENGINE = {"claude": "claude", "chatgpt": "codex", "muse": "muse", "gemini": "gemini"}
AGENTS_DO = ("ask, then run the command for the answer. Several plans: name them all, comma-separated, the main one "
             "first, e.g. slop onboard set coding-agents claude,codex")
GPU_ASK = ("Do you have a computer with an NVIDIA graphics card (or an Apple Silicon Mac) that can stay on while the "
           "bot works? Paired (recommended): it runs a small worker that fetches GPU jobs from the bot's computer - "
           "you paste ONE line on it. Direct: no link; the bot runs each GPU step on it through Grok Bot local exec "
           "(you approve the commands). Or none.")
GPU_ANSWERS = {"paired": "slop gpu serve", "direct-windows": "slop gpu direct-plan",
               "direct-mac-linux": "slop gpu direct-plan --os mac_linux", "none": "slop onboard mark gpu --skip"}
GPU_OFFLINE_RE = re.compile(r"(?i)checked in|offline|asleep|unreachable|not reachable|stale|tunnel url")


def resolve_item(name: str) -> str:
    n = str(name or "").strip().lower()
    n = ALIASES.get(n, n)
    if n not in SPEC:
        raise SlopError(f"unknown onboarding item {name!r}. Items: {', '.join(ITEM_IDS)}")
    return n


# ---------------------------------------------------------------- context + helpers
@dataclass
class Ctx:
    tier: str
    s: dict = field(default_factory=st.empty)          # onboard.json
    tk: dict = field(default_factory=dict)              # probes.toolkit()
    doc: dict = field(default_factory=dict)             # probes.doctor()
    key: dict = field(default_factory=dict)             # probes.openrouter()
    env: dict = field(default_factory=dict)             # probes.env_names()
    agents: dict = field(default_factory=dict)          # probes.agents()
    gpu: dict = field(default_factory=dict)             # probes.gpu()
    taste: dict = field(default_factory=dict)           # probes.taste()
    projects: list = field(default_factory=list)        # probes.projects()
    running: list = field(default_factory=list)         # probes.setup_running()
    offline: bool = False
    tier_source: str = ""


def skill(name: str) -> str | None:
    if name in SKILL_FALLBACK and not (toolkit_root() / "skills" / name / "SKILL.md").is_file():
        return SKILL_FALLBACK[name]
    return name


def _q(s) -> str:
    return shlex.quote(str(s))


def setup_cmd(flag: str) -> str:
    return f"bash {_q((toolkit_root() / 'bin' / 'setup.sh').as_posix())} {flag}"


def _pcmd(name: str, rest: str) -> str:
    return f"slop --project {_q(name)} {rest}"


def _mark(ctx: Ctx, iid: str) -> dict | None:
    m = (ctx.s.get("marks") or {}).get(iid)
    return m if isinstance(m, dict) else None


def _date(m: dict | None) -> str:
    return str((m or {}).get("at") or "")[:10] or "earlier"


def _note(m: dict | None) -> str:
    """A recorded note, scrubbed again on the way out (an older file may predate the note rules)."""
    n = probes.scrub(m.get("note")) if m and m.get("note") else ""
    return f" ({n})" if n else ""


def _settings(ctx: Ctx) -> dict:
    s = ctx.s.get("settings")
    return s if isinstance(s, dict) else {}


def key_expired(k: dict) -> bool:
    days = (k or {}).get("days_left")
    return isinstance(days, (int, float)) and days <= 0


def key_ok(ctx: Ctx) -> bool:
    """The OpenRouter key can make calls: valid and not expired (an expired key still reads as valid on the free
    check), or present and unchecked (--offline). Mirrors the openrouter item being done."""
    k = ctx.key or {}
    if key_expired(k):
        return False
    return bool(k.get("valid")) or bool(k.get("present") and not k.get("checked"))


def _newest(ctx: Ctx) -> dict | None:
    return next((p for p in ctx.projects if not p.get("broken")), None)


# ---------------------------------------------------------------- the two clip routes (Studio needs one of them)
def route_ok(ctx: Ctx, rid: str) -> bool:
    """OpenRouter: a valid (or, offline, present) key. Higgsfield: HIGGSFIELD_API_KEY or the connector recorded."""
    if rid == "hedra":
        return bool((ctx.env or {}).get("HEDRA_API_KEY")) or (_mark(ctx, "hedra") or {}).get("state") == "done"
    if rid == "openrouter":
        return key_ok(ctx)
    return bool((ctx.env or {}).get("HIGGSFIELD_API_KEY")) or (_mark(ctx, "higgsfield") or {}).get("state") == "done"


def other_route(rid: str) -> str:
    return "higgsfield" if rid == "openrouter" else "openrouter"


def _route_skipped(ctx: Ctx, rid: str) -> bool:
    return (_mark(ctx, rid) or {}).get("state") == "skip" and not route_ok(ctx, rid)


def route_need(ctx: Ctx, rid: str) -> str | None:
    """Studio / Director: each route is recommended; the last one left (the other skipped, not working) is required.
    None = the catalogue's (recommended)."""
    if route_ok(ctx, "hedra"):
        return None
    o = other_route(rid)
    if ctx.tier != "quick" and not route_ok(ctx, o) and _route_skipped(ctx, o):
        return "r"
    return None


def route_note(ctx: Ctx, rid: str) -> str:
    """Why this route matters for the tier, in one clause."""
    if route_ok(ctx, "hedra"):
        return "Hedra already makes clips; this route is optional"
    o, name = other_route(rid), ROUTE_NAMES[rid]
    if ctx.tier == "quick":
        return f"recommended, not required: {QUICK_BARE}"
    if route_ok(ctx, o):
        return f"{ROUTE_NAMES[o]} already makes the clips; {name} is recommended too: {ROUTE_WHY[rid]}"
    if _route_skipped(ctx, o):
        return (f"{ROUTE_NAMES[o]} is skipped, so the {ctx.tier} tier needs {name} for its clips (or {ROUTE_NAMES[o]} "
                f"after all, with the user's OK: slop onboard mark {o} --todo)")
    return f"the {ctx.tier} tier needs OpenRouter or Higgsfield for its clips; {BOTH_WHY}"


def _unavailable(family: str, probe: dict | None = None) -> dict:
    if (probe or {}).get("unregistered"):
        return {"raw": "blocked", "available": False, "next_skill": "claudia-toolkit",
                "why": f"`slop {family}` is in this toolkit, but the slop command does not load it yet (slop/cli.py "
                       f"MODULES, or $SLOP_MODULES when that is set)",
                "do": f"update the toolkit as skill claudia-toolkit says (git pull + bash bin/setup.sh); if "
                      f"$SLOP_MODULES is set, add slop.{family}.cli to it; then: slop onboard status"}
    return {"raw": "blocked", "available": False, "next_skill": "claudia-toolkit",
            "why": f"not available in this toolkit version (no `slop {family}`): update the toolkit (skill "
                   "claudia-toolkit), then check again",
            "do": "update the toolkit as skill claudia-toolkit says (git pull + bash bin/setup.sh), then: slop "
                  "onboard status"}


def _installing(ctx: Ctx, full: bool = False) -> bool:
    return any((r.get("full") if full else True) for r in ctx.running or [])


def _answers(setting: str, values) -> dict:
    return {v: f"slop onboard set {setting} {v}" for v in values}


# ---------------------------------------------------------------- coding agents: who does Director work
def _runner_engines(root: Path) -> tuple[str, ...]:
    """The engines runner/deleg.mjs drives (its `const ENGINES = [...]`, without 'raw'); () when unreadable."""
    try:
        text = (root / "runner" / "deleg.mjs").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ()
    m = re.search(r"const\s+ENGINES\s*=\s*\[([^\]]*)\]", text)
    names = set(re.findall(r"['\"]([a-z]+)['\"]", m.group(1))) if m else set()
    return tuple(e for e in ENGINES if e in names)


def _brief_engines(root: Path) -> tuple[str, ...]:
    """Engines named on any delegation brief's `engines:` line (templates/briefs/*.md). The runner uses the preferred
    engine of `slop agents use` only for a brief that lists it (runner/deleg.mjs preferredEngine)."""
    found: set[str] = set()
    d = root / "templates" / "briefs"
    for f in sorted(d.glob("*.md")) if d.is_dir() else []:
        try:
            head = f.read_text(encoding="utf-8", errors="replace").split("-->", 1)[0]
        except OSError:
            continue
        m = re.search(r"^\s*engines:\s*(.*)$", head, re.M)
        if m:
            found |= {e for e in ENGINES if re.search(rf"\b{e}\b", m.group(1))}
    return tuple(e for e in ENGINES if e in found)


@functools.lru_cache(maxsize=4)
def _director_engines(root: str) -> tuple[str, ...]:
    r = Path(root)
    runner, briefs = _runner_engines(r), _brief_engines(r)
    if not briefs:
        return ()
    return tuple(e for e in briefs if not runner or e in runner)


def director_engines() -> tuple[str, ...]:
    """Engines that can do Director work: listed by a delegation brief AND driven by the runner (today claude, codex,
    muse: Gemini CLI runs one job with --engine gemini, but no brief lists it). Read from the repository, so it follows
    the briefs; the fallback is used only when they cannot be read."""
    return _director_engines(str(toolkit_root())) or FALLBACK_DIRECTOR_ENGINES


def director_capable(ctx: Ctx) -> tuple[str, ...]:
    return director_engines()


def chosen_engines(ctx: Ctx) -> list[str]:
    """The user's coding-agent plans (`slop onboard set coding-agents ...`), main first."""
    return st.coding_agents(ctx.s) or []


def _engines(ctx: Ctx) -> dict:
    return (ctx.agents or {}).get("engines") or {}


def _box_logged_in(ctx: Ctx, e: str) -> bool:
    return bool((ctx.agents or {}).get("available")) and bool((_engines(ctx).get(e) or {}).get("logged_in"))


def _home_done(ctx: Ctx, e: str) -> bool:
    return (_mark(ctx, f"home-{e}") or {}).get("state") == "done"


def runner_default(ctx: Ctx) -> str:
    """The engine a new delegated job uses when none is named: `slop agents use ... --for director` when a brief can
    use it, else Claude Code (the runner's own default)."""
    use = st.agent_use("director", ctx.s)
    return use if use in director_capable(ctx) else "claude"


def _director_agents(ctx: Ctx) -> list[tuple[str, str]]:
    """(engine, 'box'|'home') for each Director agent that is ready. On the box it must also be the engine new jobs
    use (runner_default): a logged-in Codex does not help while jobs still default to Claude Code."""
    out = []
    for e in director_capable(ctx):
        if _box_logged_in(ctx, e) and e == runner_default(ctx):
            out.append((e, "box"))
        if _home_done(ctx, e):
            out.append((e, "home"))
    return out


def pref_engine(ctx: Ctx) -> str | None:
    """The engine Director setup works towards: `agents use --for director`, else the user's main plan, else one
    already logged in / installed on the box, else one ready at home; None = unknown (coding-agents asks)."""
    cap = director_capable(ctx)
    use = st.agent_use("director", ctx.s)
    if use in cap:
        return use
    for e in chosen_engines(ctx):
        if e in cap:
            return e
    eng = _engines(ctx) if (ctx.agents or {}).get("available") else {}
    for key in ("logged_in", "installed"):
        for e in cap:
            if (eng.get(e) or {}).get(key):
                return e
    return next((e for e in cap if _home_done(ctx, e)), None)


def _box_route(ctx: Ctx, e: str) -> bool:
    """An agent comes from the box (slop agents) unless that is unavailable or the user skipped it there."""
    return bool((ctx.agents or {}).get("available")) and (_mark(ctx, f"agent-{e}") or {}).get("state") != "skip"


def agent_need(ctx: Ctx, e: str, where: str) -> str | None:
    """Director tier: the preferred engine is REQUIRED on one route (box, else the user's own computer) until a
    Director agent is ready. Every tier: the user's own plans are RECOMMENDED on that route. None = the catalogue's."""
    box = _box_route(ctx, e)
    on_route = box if where == "box" else not box
    if ctx.tier == "director" and not _director_agents(ctx) and e == pref_engine(ctx):
        return "r" if on_route else "o"
    if e in chosen_engines(ctx) and on_route:
        return "c"
    return None


def priority(ctx: Ctx) -> list[str]:
    """PRIORITY with the agent items in the user's order: the Director engine, their plans, then the rest."""
    pref = pref_engine(ctx)
    order = list(dict.fromkeys(([pref] if pref else []) + chosen_engines(ctx) + list(ENGINES)))
    out: list[str] = []
    for iid in PRIORITY:
        if iid == "agent-claude":
            out += [f"agent-{e}" for e in order]
        elif iid == "home-claude":
            out += [f"home-{e}" for e in order]
        elif not iid.startswith(("agent-", "home-")):
            out.append(iid)
    return out


# ---------------------------------------------------------------- items: start and toolkit
def _tier(ctx: Ctx) -> dict:
    t = ctx.s.get("tier")
    if t in TIERS:
        return {"raw": "done", "data": {"tier": t},
                "why": f"{t.title()} tier chosen (change any time: slop onboard set tier quick|studio|director)"}
    src = (ctx.tier_source or "default").split(";")[0]
    return {"raw": "todo", "why": f"no tier chosen yet (judged for {ctx.tier} for now: {src})",
            "ask": TIER_ASK, "answers": _answers("tier", TIERS),
            "do": "ask, then run the command for the answer (unsure: quick)"}


def _toolkit(ctx: Ctx) -> dict:
    tk = ctx.tk
    data = {"version": tk.get("version"), "profile": tk.get("profile"), "slop_home": tk.get("slop_home"),
            "on_box": tk.get("on_box")}
    if tk.get("installed"):
        return {"raw": "done", "data": data,
                "why": f"claudia {tk.get('version')}, {tk.get('profile')} profile, installed in {tk.get('slop_home')}"}
    r = {"raw": "todo", "data": data, "next_cmd": setup_cmd("--minimal"), "long": True,
         "why": f"claudia {tk.get('version')} runs from {tk.get('toolkit')}, but bin/setup.sh has not installed it in "
                f"{tk.get('slop_home')} yet (no env.sh / bin/slop)",
         "do": "run it in ONE background shell (about 5 min; the full analysis install can follow with --full), "
               "then check again: slop onboard status"}
    if _installing(ctx):
        r.update(running=True, why="bin/setup.sh is running now; check again when it ends: slop onboard status")
    return r


def _path(ctx: Ctx) -> dict:
    tk = ctx.tk
    if not tk.get("installed"):
        return {"raw": "blocked", "blocked_by": ["toolkit"], "why": "after the install (toolkit)"}
    if tk.get("on_path"):
        return {"raw": "done", "why": "`slop` is on PATH"}
    env_sh, rc = tk.get("env_sh"), tk.get("shell_rc") or []
    if ".bashrc" in rc and ".profile" in rc:
        # this shell may simply be older than the lines (or not a login shell): done, with the way round it
        return {"raw": "done", "why": f"{env_sh} is loaded by ~/.bashrc and ~/.profile (new shells find `slop`)",
                "warn": f"this shell does not find `slop`: start a new shell, or call {tk.get('shim')} by its full "
                        "path"}
    line = ". " + str(env_sh)
    cmd = "; ".join(f"grep -qsF {_q(env_sh)} ~/{f} || echo {_q(line)} >> ~/{f}" for f in (".bashrc", ".profile"))
    return {"raw": "todo", "next_cmd": cmd,
            "why": "new shells do not find `slop` yet" + (f" (only ~/{rc[0]} loads env.sh)" if rc else ""),
            "do": f"adds env.sh to ~/.bashrc and ~/.profile (login shells skip .bashrc). Then start a new shell; until "
                  f"`slop --version` works there, call {tk.get('shim')} by its full path"}


def _doctor(ctx: Ctx) -> dict:
    d = ctx.doc or {}
    if not d.get("ok"):
        return {"raw": "error", "why": f"slop doctor could not run: {d.get('error') or 'unknown error'}",
                "next_cmd": "slop doctor", "do": "read its output; fix what it names, then: slop onboard status"}
    fails, warns = d.get("fails") or [], d.get("warns") or []
    data = {"fails": [f.get("name") for f in fails], "warns": warns, "passed": d.get("passed")}
    if fails:
        first = fails[0]
        r = {"raw": "error", "data": data, "next_cmd": "slop doctor",
             "why": f"{len(fails)} failing: {', '.join(data['fails'][:5])}" + (
                 f" - first fix: {first['fix']}" if first.get("fix") else ""),
             "do": "run slop doctor and fix its FAIL lines in order (each prints its fix), then: slop onboard status"}
        if not ctx.tk.get("installed"):
            r.update(raw="blocked", blocked_by=["toolkit"], why="after the install (toolkit); now " + r["why"])
        return r
    w = f" ({len(warns)} warnings: {', '.join(warns[:4])})" if warns else ""
    return {"raw": "done", "data": data, "why": f"no failing checks{w}"}


def _full(ctx: Ctx) -> dict:
    tk, d = ctx.tk, ctx.doc or {}
    if not tk.get("installed"):
        return {"raw": "blocked", "blocked_by": ["toolkit"], "why": "after the minimal install (toolkit)"}
    deps = d.get("deps_full")
    if tk.get("profile") == "full" and deps in ("ok", None):
        return {"raw": "done", "why": "full profile installed (local stems and alignment on CPU)" + (
            "" if deps else "; packages not verified (doctor did not run)")}
    if tk.get("profile") == "full":
        r = {"raw": "error", "next_cmd": setup_cmd("--full"), "long": True,
             "why": "the full profile is recorded but its packages are missing or broken (slop doctor: deps:full)",
             "do": "re-run it in ONE background shell (about 5 min; renders keep working meanwhile)"}
        if _installing(ctx, full=True):     # the re-run is going: never start a second one
            r.update(running=True, why="the full install is running again now (bin/setup.sh --full); check again "
                                       "later")
        return r
    r = {"raw": "todo", "next_cmd": setup_cmd("--full"), "long": True,
         "why": "minimal profile: the song analysis (stems, word timing, beat map) runs after the full install",
         "do": "run it in ONE background shell (about 5 min; the song, lyrics, lead and look steps go on meanwhile)"}
    if _installing(ctx, full=True):
        r.update(running=True, why="the full install is running now (bin/setup.sh --full); check again later")
    return r


# ---------------------------------------------------------------- items: keys and connectors
def _openrouter(ctx: Ctx) -> dict:
    k = ctx.key or {}
    data = {x: k.get(x) for x in ("present", "valid", "limit", "limit_remaining", "usage", "expires_at", "days_left",
                                  "is_free_tier") if x in k}
    sk = skill("setup-accounts")
    need = route_need(ctx, "openrouter")
    if not k.get("present"):
        ask = ("only if the user wants API stills (about $0.004 each), cheap motion clips or a Lyria song (not "
               "wanted: slop onboard mark openrouter --skip): " if ctx.tier == "quick" else "")
        return {"raw": "todo", "need": need, "data": data, "next_skill": sk,
                "why": f"OPENROUTER_API_KEY is not set; {route_note(ctx, 'openrouter')}",
                "do": ask + "ask for OPENROUTER_API_KEY with the masked secure secret card (never in chat). Suggest a "
                      "NEW key with its own credit limit a little above one video's budget (Quick $25, Studio $110, "
                      "Director $160): that limit is the hard cap. Then: slop onboard status (checks it for free)"}
    if not k.get("checked"):
        return {"raw": "done", "data": data, "why": "OPENROUTER_API_KEY is set (not checked: --offline)"}
    if not k.get("valid"):
        if k.get("status") == 0:
            return {"raw": "error", "need": need, "data": data, "next_cmd": "slop doctor --net",
                    "why": k.get("error") or "openrouter.ai is unreachable",
                    "do": "check the network (team allowlists must allow openrouter.ai), then: slop onboard status"}
        return {"raw": "error", "need": need, "data": data, "next_skill": sk,
                "why": k.get("error") or "the key was rejected",
                "do": "the user checks the key at openrouter.ai/settings/keys (or makes a new one with a credit "
                      "limit); then ask for OPENROUTER_API_KEY again with the secure secret card"}
    parts, warn = ["key valid"], []
    lim, rem, used = k.get("limit"), k.get("limit_remaining"), k.get("usage")
    if lim is None:
        parts.append(f"used {util.money(used)}; no credit limit on the key")
        warn.append("set a credit limit on the key in the OpenRouter dashboard (it is the hard spend cap)")
    else:
        parts.append(f"used {util.money(used)} of its {util.money(lim)} limit ({util.money(rem)} left)")
        if isinstance(rem, (int, float)) and rem < 2:
            warn.append("the key is nearly at its credit limit: raise it in the OpenRouter dashboard")
    if k.get("is_free_tier"):
        warn.append("FREE tier: paid models fail until credits are added")
    days = k.get("days_left")
    raw = "done"
    if isinstance(days, (int, float)):
        when = str(k.get("expires_at") or "")[:10]
        if days <= 0:
            raw = "error"
            parts.append(f"EXPIRED {when}")
        elif days < 14:
            parts.append(f"expires {when} ({days:.0f} days)")
            warn.append("ask the user for a new key before it expires (new secure secret card)")
        else:
            parts.append(f"expires {when}")
    r = {"raw": raw, "data": data, "why": "; ".join(parts),
         "cost": f"pay as you go; {parts[1]}"}
    if warn:
        r["warn"] = "; ".join(warn)
    if raw == "error":
        r.update(need=need, next_skill=sk, do="the key has expired: the user makes a new key with a credit limit; "
                                              "ask for OPENROUTER_API_KEY again with the secure secret card")
    return r


def _arena(ctx: Ctx) -> dict:
    if (ctx.env or {}).get("ARENA_TOKEN"):
        return {"raw": "done", "why": "ARENA_TOKEN is set"}
    return {"raw": "todo", "next_skill": skill("setup-accounts"),
            "why": "ARENA_TOKEN is not set (only for importing your own Are.na channels)",
            "do": "only if the user has Are.na channels: ask for ARENA_TOKEN with the secure secret card"}


def _connector(ctx: Ctx, iid: str, name: str, extra: str) -> dict:
    m = _mark(ctx, iid)
    if m and m.get("state") == "done":
        return {"raw": "done", "why": f"connected (recorded {_date(m)}){_note(m)}"}
    return {"raw": "todo", "next_skill": skill("setup-accounts"), "record_cmd": f"slop onboard mark {iid} --connected",
            "why": "not recorded yet (the bot sees its connectors; slop cannot)",
            "do": f"SearchPlugins for {name}. Connected: {extra}then run the record command. Missing and wanted: "
                  "offer the install widget and install only after a yes; the user signs in on its card."}


def _higgsfield(ctx: Ctx) -> dict:
    if (ctx.env or {}).get("HIGGSFIELD_API_KEY"):
        return {"raw": "done", "why": "HIGGSFIELD_API_KEY is set"}
    r = _connector(ctx, "higgsfield", "Higgsfield", "call its balance tool; when it answers, ")
    if r["raw"] != "done":
        r["need"] = route_need(ctx, "higgsfield")
        r["why"] += f"; {route_note(ctx, 'higgsfield')}"
    return r


def _hedra(ctx: Ctx) -> dict:
    if (ctx.env or {}).get("HEDRA_API_KEY"):
        return {"raw": "done", "why": "HEDRA_API_KEY is set (API transport; key not verified)"}
    return _connector(ctx, "hedra", "Hedra (https://hedra.com/mcp)", "call get_model for seedance-25; when it answers, ")


def _drive(ctx: Ctx) -> dict:
    r = _connector(ctx, "drive", "Google Drive", "list one folder; when it answers, ")
    if r["raw"] != "done":
        r["do"] = "only if the user keeps songs or references in Google Drive. " + r["do"]
    return r


# ---------------------------------------------------------------- items: music and stills
def _suno(ctx: Ctx) -> dict:
    plan = _settings(ctx).get("suno_plan")
    if plan in PAID_SUNO:
        return {"raw": "done", "why": f"Suno {plan.title()} recorded", "data": {"plan": plan}}
    if plan == "free":
        return {"raw": "done", "data": {"plan": plan}, "why": "Suno Free recorded",
                "warn": "Suno Free songs are for non-commercial use only (docs/10-song.md); for a commercial "
                        "release: a Suno upgrade or Lyria"}
    if plan == "none":
        return {"raw": "skipped", "data": {"plan": plan}, "why": "no Suno: songs come from an upload or Lyria"}
    return {"raw": "todo", "next_skill": skill("setup-accounts"),
            "why": "Suno plan not recorded", "ask": "Which Suno plan do you have: Free, Pro, Premier, or none?",
            "answers": _answers("suno-plan", st.SUNO_PLANS),
            "do": "ask, then run the command for the answer"}


def _signin(ctx: Ctx, iid: str, site: str, plan_item: str, plan: str | None, paid: tuple, button: str) -> dict:
    m = _mark(ctx, iid)
    if plan == "none":
        return {"raw": "skipped", "why": f"no {site} account"}
    if plan not in paid + (("free",) if site == "Suno" else ()):
        return {"raw": "blocked", "blocked_by": [plan_item], "why": f"record the {site} plan first ({plan_item})"}
    if m and m.get("state") == "done":
        return {"raw": "done", "why": f"signed in on the bot's browser (recorded {_date(m)}){_note(m)}; if a page asks "
                                     "to sign in again, the user signs in again themselves"}
    return {"raw": "todo", "next_skill": skill("setup-accounts"), "record_cmd": f"slop onboard mark {iid} --done",
            "why": f"Grok runs Opus's {site} jobs in its own browser; the user signs in there once",
            "do": f"open {site} in your browser with a one-line heads-up that its terms limit automated use; the user "
                  f"signs in THEMSELVES (never type a password). When you see them signed in, run the record "
                  f"command."}


def _suno_signin(ctx: Ctx) -> dict:
    return _signin(ctx, "suno-signin", "Suno", "suno", _settings(ctx).get("suno_plan"), PAID_SUNO, "Create")


def _lyria(ctx: Ctx) -> dict:
    need = "o" if _settings(ctx).get("suno_plan") in PAID_SUNO or ctx.tier != "quick" else "c"
    if key_ok(ctx):
        return {"raw": "done", "need": need,
                "why": "Lyria through OpenRouter: `slop gen song` (estimate printed first; Suno stays the quality "
                       "path)"}
    if _quick_declined(ctx, ("openrouter",)):
        return {"raw": "skipped", "need": need,
                "why": "OpenRouter is skipped: the song is the user's own upload (or Suno)"}
    return {"raw": "blocked", "need": need, "blocked_by": ["openrouter"],
            "why": "needs a valid OpenRouter key; without it the song is the user's own upload (or Suno)"}


def _mj_gaps(ctx: Ctx) -> tuple[dict | None, list[str]]:
    """The newest project and which recorded Midjourney settings it does not use yet ('plan', 'profile')."""
    p, sets = _newest(ctx), _settings(ctx)
    if not p:
        return None, []
    gaps = []
    if sets.get("mj_plan") in PAID_MJ and (p.get("mj_plan") or "standard") != sets["mj_plan"]:
        gaps.append("plan")
    return p, gaps


def _midjourney(ctx: Ctx) -> dict:
    plan = _settings(ctx).get("mj_plan")
    if plan in PAID_MJ:
        r = {"raw": "done", "why": f"Midjourney {plan.title()} plan recorded", "data": {"plan": plan}}
        p, gaps = _mj_gaps(ctx)
        if "plan" in gaps:
            r.update(raw="todo", next_cmd=_pcmd(p["name"], "onboard apply"),
                     why=f"Midjourney {plan.title()} plan recorded, but project {p['name']} still sizes its prompt "
                         f"batches for {(p.get('mj_plan') or 'standard').title()}",
                     do="copies the recorded plan (and profile code) into that project's project.json")
        return r
    if plan == "none":
        return {"raw": "skipped", "data": {"plan": plan}, "why": "no Midjourney: stills come from API image models"}
    return {"raw": "todo", "next_skill": skill("setup-accounts"), "why": "Midjourney plan not recorded",
            "ask": "Do you have a Midjourney plan (Basic, Standard, Pro or Mega), or none?",
            "answers": _answers("mj-plan", st.MJ_PLANS), "do": "ask, then run the command for the answer"}


def _mj_profile(ctx: Ctx) -> dict:
    sets = _settings(ctx)
    plan, code = sets.get("mj_plan"), sets.get("mj_profile")
    need = "c" if plan in PAID_MJ and ctx.tier != "quick" else "o"
    if code:
        return {"raw": "done", "need": need, "data": {"code": st.mask(code)},
                "why": f"recorded in your user settings ({st.mask(code)}); never shipped. Prompts never carry it: "
                       "personalization is the P button"}
    if plan == "none":
        return {"raw": "skipped", "need": need, "why": "no Midjourney"}
    if plan not in PAID_MJ:
        return {"raw": "blocked", "need": need, "blocked_by": ["midjourney"],
                "why": "record the Midjourney plan first (midjourney)"}
    return {"raw": "skipped", "need": "o",
            "why": "no code needed: Grok switches your personalization on with the P button, and Opus asks per project "
                   "whether to use it (make a profile any time on midjourney.com's Personalize page)"}


def _mj_signin(ctx: Ctx) -> dict:
    return _signin(ctx, "mj-signin", "Midjourney", "midjourney", _settings(ctx).get("mj_plan"), PAID_MJ, "Submit")


def _vias(ctx: Ctx) -> list[str]:
    return [ROUTE_NAMES[x] for x in ROUTES if route_ok(ctx, x)]


def _free_tier_warn(ctx: Ctx, r: dict, what: str) -> dict:
    """A FREE-tier OpenRouter key passes the free check, but paid models (every clip and API still) fail until the
    user adds credits: say so on what depends on it."""
    if (ctx.key or {}).get("is_free_tier") and "OpenRouter" in ((r.get("data") or {}).get("via") or []):
        r["warn"] = (f"the OpenRouter key is on the FREE tier: {what} through it fail until the user adds credits "
                     "(openrouter.ai/settings/credits)")
    return r


def _quick_declined(ctx: Ctx, rids=ROUTES) -> bool:
    """Quick, and the user skipped every one of these routes: what follows from them is declined, not blocked (it
    can never come, and Quick does not need it). Studio and Director keep it blocked: their `stuck` says why."""
    return ctx.tier == "quick" and all(_route_skipped(ctx, x) for x in rids)


def _api_images(ctx: Ctx) -> dict:
    via = _vias(ctx)
    if via:
        return _free_tier_warn(ctx, {"raw": "done", "data": {"via": via},
                                     "why": f"API image models via {' and '.join(via)} (`slop gen image`; Higgsfield "
                                            "through the connector); Grok's image tool stays the no-key fallback"},
                               "API stills")
    if _quick_declined(ctx):
        return {"raw": "skipped", "data": {"via": []},
                "why": "OpenRouter and Higgsfield are both skipped: stills come from Grok's own image tool "
                       "(GenerateImage), all the Quick tier needs"}
    return {"raw": "blocked", "blocked_by": list(ROUTES), "any_of": True, "data": {"via": []},
            "why": "needs the OpenRouter key or the Higgsfield connector; until then stills come from Grok's own image "
                   "tool (GenerateImage), which is all the Quick tier needs"}


def _video(ctx: Ctx) -> dict:
    if route_ok(ctx, "hedra"):
        return {"raw": "done", "data": {"via": _vias(ctx) + ["Hedra"]},
                "why": "Hedra Seedance 2.5 clips: --provider hedra --hedra-transport api|mcp; measure sung lip sync"}
    via = _vias(ctx)
    if len(via) == 2:
        return _free_tier_warn(ctx, {"raw": "done", "data": {"via": via},
                                     "why": "sung and motion clips via OpenRouter (cheaper per second) and Higgsfield "
                                            "(copies the vocals more reliably: after 2 OpenRouter misses on a window, "
                                            "re-route it there)"}, "clips")
    if via:
        o = next(x for x in ROUTES if not route_ok(ctx, x))
        extra = (f"{ROUTE_NAMES[o]} is skipped" if _route_skipped(ctx, o)
                 else f"{ROUTE_NAMES[o]} is recommended too: {ROUTE_WHY[o]}")
        return _free_tier_warn(ctx, {"raw": "done", "data": {"via": via},
                                     "why": f"sung and motion clips via {via[0]}; {extra}"}, "clips")
    if _quick_declined(ctx):
        return {"raw": "skipped", "data": {"via": []},
                "why": "OpenRouter and Higgsfield are both skipped: Quick goes without clips (2.5D motion and devices "
                       "carry every shot)"}
    why = ("no OpenRouter key and no Higgsfield connector: Quick goes without clips (2.5D motion and devices carry "
           "every shot)" if ctx.tier == "quick" else
           f"the {ctx.tier} tier needs OpenRouter or Higgsfield for its sung clips; {BOTH_WHY}")
    return {"raw": "blocked", "blocked_by": list(ROUTES), "any_of": True, "data": {"via": []}, "why": why}


def _codex_images(ctx: Ctx) -> dict:
    if not (ctx.agents or {}).get("available"):
        return _unavailable("agents", ctx.agents)
    e = _engines(ctx).get("codex") or {}
    if e.get("logged_in"):
        return {"raw": "done", "why": "Codex is logged in on the box: images on the ChatGPT plan, no API key "
                                     "(1-4 min an image; plan limits apply)"}
    return {"raw": "blocked", "blocked_by": ["agent-codex"], "why": "needs Codex logged in on the box (agent-codex)"}


# ---------------------------------------------------------------- items: agents
def _coding_agents(ctx: Ctx) -> dict:
    v = st.coding_agents(ctx.s)
    cap = director_capable(ctx)

    def names(es) -> str:
        return ", ".join(ENGINE_NAMES[e] for e in es)
    director_open = ctx.tier == "director" and not _director_agents(ctx)
    plans = ", ".join(PLAN_NAMES[e] for e in cap)
    director_answers = {**{k: c for k, c in AGENTS_ANSWERS.items() if ANSWER_ENGINE.get(k) in cap},
                        "studio": "slop onboard set tier studio"}
    if v:
        data = {"engines": v}
        if director_open and not any(e in cap for e in v):
            return {"raw": "todo", "data": data,
                    "why": f"recorded: {names(v)}, but none of them can be the Director agent (the delegation "
                           f"briefs run on {names(cap)})",
                    "ask": f"The Director tier needs one of these plans: {plans}. Do you have one, or should we "
                           "use the Studio tier (everything except delegated agent work)?",
                    "answers": director_answers,
                    "do": "ask, then run the command for the answer (a plan: add it to the ones recorded, the main "
                          f"one first, e.g. slop onboard set coding-agents {cap[0]},{','.join(v)})"}
        return {"raw": "done", "data": data,
                "why": f"recorded: {names(v)} (main: {ENGINE_NAMES[v[0]]}); change: slop onboard set coding-agents "
                       "with every plan, the main one first"}
    if v == []:
        if director_open:
            return {"raw": "todo", "data": {"engines": []},
                    "why": "recorded: no coding-agent plan, but the Director tier needs one",
                    "ask": f"The Director tier needs one of these plans: {plans}. Record your plan, or use the "
                           "Studio tier (everything except delegated agent work)?",
                    "answers": director_answers, "do": "ask, then run the command for the answer"}
        return {"raw": "skipped", "data": {"engines": []},
                "why": "no coding-agent plan (agents stay optional; change: slop onboard set coding-agents claude)"}
    ready = [e for e in ENGINES if _box_logged_in(ctx, e) or _home_done(ctx, e)]
    if ready and (not director_open or any(e in cap for e in ready)):
        return {"raw": "done", "data": {"engines": ready},
                "why": f"{names(ready)} already signed in; to record more plans, name them all, the main one "
                       f"first, e.g. slop onboard set coding-agents {','.join(ready)}"}
    return {"raw": "todo", "why": "the user's coding-agent plans are not recorded",
            "ask": AGENTS_ASK, "answers": AGENTS_ANSWERS, "do": AGENTS_DO}


def _use_hint(ctx: Ctx, e: str, need: str | None) -> str:
    """Director: the extra step that makes E the engine new delegated jobs use."""
    if ctx.tier == "director" and need == "r" and e != runner_default(ctx):
        return (f" Then make it the Director agent (new jobs use {ENGINE_NAMES[runner_default(ctx)]} until then): "
                f"slop agents use {e} --for director")
    return ""


def _agent(ctx: Ctx, e: str) -> dict:
    name = ENGINE_NAMES[e]
    need = agent_need(ctx, e, "box")
    ag = ctx.agents or {}
    if not ag.get("available"):
        r = _unavailable("agents", ag)
        r["need"] = need
        return r
    sk = skill("setup-agents")
    row = _engines(ctx).get(e)
    if row is None:
        if ag.get("error"):
            return {"raw": "error", "need": need, "next_cmd": "slop agents status", "next_skill": sk,
                    "why": f"slop agents status failed: {ag['error']}",
                    "do": "run it and read the error; it names its own next step"}
        return {"raw": "todo", "need": need, "next_cmd": f"slop agents install {e}", "next_skill": sk,
                "why": "not reported by slop agents status (not installed?)",
                "do": f"installs under $SLOP_HOME (survives box updates); then: slop agents login {e}"
                      + _use_hint(ctx, e, need)}
    ver = f" {row['version']}" if row.get("version") else ""
    data = {k: row.get(k) for k in ("installed", "logged_in", "version", "plan")}
    where = "on the box" if (ctx.tk or {}).get("on_box", True) else "on this computer"
    if row.get("logged_in"):
        plan = f" ({row['plan']} plan)" if row.get("plan") else ""
        if ctx.tier == "director" and need == "r" and e != runner_default(ctx):
            return {"raw": "todo", "need": need, "data": data, "next_cmd": f"slop agents use {e} --for director",
                    "next_skill": sk,
                    "why": f"{name}{ver} logged in {where}{plan}, but new Director jobs still use "
                           f"{ENGINE_NAMES[runner_default(ctx)]}",
                    "do": f"makes {name} the default engine of delegated Director jobs (runner/deleg.mjs); then "
                          f"check it: slop agents test {e}"}
        return {"raw": "done", "need": need, "data": data, "why": f"{name}{ver} logged in {where}{plan}"}
    note = row.get("error") or row.get("detail")
    note = f" ({note})" if note else ""
    if row.get("installed"):
        theirs = row.get("next") or ""
        if row.get("login_pending"):
            cmd = theirs if f"login {e}" in theirs else f"slop agents login {e} --check"
            return {"raw": "todo", "need": need, "data": data, "next_cmd": cmd, "next_skill": sk,
                    "why": f"{name}{ver}: sign-in started, waiting for the user{note}",
                    "do": "the user finishes the sign-in with the link (and code) `slop agents status` shows; then "
                          f"run the command. To start over: slop agents login {e} --cancel"}
        how = "not logged in" if row.get("logged_in") is False else "login state unknown"
        return {"raw": "todo", "need": need, "data": data, "next_cmd": f"slop agents login {e}", "next_skill": sk,
                "why": f"{name}{ver} installed, {how}{note}",
                "do": LOGIN_DO[e] + f" Then check: slop agents test {e}." + _use_hint(ctx, e, need)}
    if row.get("error"):
        return {"raw": "error", "need": need, "data": data, "next_cmd": f"slop agents install {e}", "next_skill": sk,
                "why": f"{name}: {row['error']}", "do": "re-run the install; then log in: slop agents login " + e}
    return {"raw": "todo", "need": need, "data": data, "next_cmd": f"slop agents install {e}", "next_skill": sk,
            "why": f"{name} is not installed {where}{note}",
            "do": f"installs under $SLOP_HOME (survives box updates); then: slop agents login {e}"
                  + _use_hint(ctx, e, need)}


def _home(ctx: Ctx, e: str) -> dict:
    name = ENGINE_NAMES[e]
    need = agent_need(ctx, e, "home")
    m = _mark(ctx, f"home-{e}")
    if m and m.get("state") == "done":
        return {"raw": "done", "need": need,
                "why": f"{name} ready on your own computer (recorded {_date(m)}){_note(m)}"}
    win, nix, signal = HOME_CHECK[e]
    return {"raw": "todo", "need": need, "next_skill": skill("setup-agents"),
            "record_cmd": f"slop onboard mark home-{e} --done", "why": "not recorded",
            "do": f"only if the user has {name} on their own computer: through Grok Bot local exec (the user approves "
                  f"each command, or chose Always allow) run the sign-in check there - Windows PowerShell: `{win}`; "
                  f"Mac or Linux terminal: `{nix}`. Signed in when {signal}. Only then run the record command (a "
                  f"--note may name the plan, never an account address). Not signed in: the user runs "
                  f"`{HOME_LOGIN[e]}` there themselves, then check again. Not installed: leave it, or offer "
                  f"{name} on the box instead (agent-{e})."}


# ---------------------------------------------------------------- items: gpu, taste, project
def _gpu_do(cmd: str, why: str) -> str:
    if cmd == "slop gpu pair":
        return ("it prints the ONE line the user pastes on the GPU computer (Windows PowerShell, or a Mac/Linux "
                "terminal); when the worker checks in: slop onboard next")
    if cmd.startswith("slop gpu pair"):
        return ("the paired computer is not checking in (asleep, worker stopped, or the tunnel URL changed): ask the "
                "user to wake it, then give them the short re-pair line this prints" if GPU_OFFLINE_RE.search(why)
                else "it prints the short re-pair line the user pastes on the GPU computer")
    if cmd.startswith("slop gpu serve"):
        return "starts the box's GPU job server and its tunnel again; then: slop onboard next"
    if cmd.startswith("slop gpu install "):
        return "queues the profile install on the user's computer (several minutes); watch: slop gpu status"
    return "run it and follow what it prints"


def gpu_enabled() -> bool:
    """The home-GPU link is parked until the relay ships (the bot's computer cannot open a quick tunnel):
    SLOP_GPU_LINK=1 turns the checklist item back on. (SLOP_GPU is the analysis mode: auto, off or require.)"""
    return os.environ.get("SLOP_GPU_LINK", "0").strip() == "1"


def _gpu(ctx: Ctx) -> dict:
    if not gpu_enabled():
        return {"raw": "skipped", "data": {}, "why": "the home-GPU link comes in a later update; analysis runs on the "
                                                     "bot's computer meanwhile (nothing to do)"}
    g = ctx.gpu or {}
    if not g.get("available"):
        return _unavailable("gpu", g)
    sk = skill("setup-gpu")
    names = ", ".join(f"{x.get('name') or 'GPU'}" + (f" {x['vram_gb']:g} GB" if x.get("vram_gb") else "")
                      for x in g.get("gpus") or [])
    prof = f"; profiles: {', '.join(g['profiles'])}" if g.get("profiles") else "; no profiles installed yet"
    data = {k: g.get(k) for k in ("mode", "healthy", "gpus", "profiles", "last_seen")}
    mode = g.get("mode") or "none"
    if mode == "paired":
        if g.get("healthy") is False:
            seen = f" (last seen {g['last_seen']})" if g.get("last_seen") else ""
            why = g.get("why") or f"paired worker{(' on ' + names) if names else ''} is offline{seen}"
            if re.search(r"(?i)\bbusy\b", why):
                return {"raw": "done", "data": data, "why": f"{names or 'GPU worker'} paired{prof}", "warn": why}
            cmd = g.get("hint_cmd") or ("slop gpu pair --refresh" if GPU_OFFLINE_RE.search(why) else "slop gpu status")
            raw = "todo" if cmd == "slop gpu pair" or cmd.startswith("slop gpu install ") else "error"
            return {"raw": raw, "data": data, "next_cmd": cmd, "next_skill": sk, "why": why, "do": _gpu_do(cmd, why)}
        health = "" if g.get("healthy") else " (health unknown: slop gpu status)"
        return {"raw": "done", "data": data, "why": f"{names or 'GPU worker'} paired{health}{prof}"}
    if mode == "direct":
        return {"raw": "done", "data": data,
                "why": f"direct mode: jobs run on your computer through Grok Bot local exec{(' (' + names + ')') if names else ''}{prof}"}
    if g.get("error") and not g.get("ok"):
        return {"raw": "error", "data": data, "next_cmd": "slop gpu status", "next_skill": sk,
                "why": f"slop gpu status failed: {g['error']}", "do": "run it and read the error"}
    return {"raw": "todo", "data": data, "next_skill": sk, "why": g.get("why") or "no home GPU connected",
            "ask": GPU_ASK, "answers": GPU_ANSWERS,
            "do": "ask, then run the command for the answer. Paired: `slop gpu serve` starts the box's job server and "
                  "tunnel, then `slop gpu pair` prints the ONE line the user pastes on their computer. Direct: the "
                  "plan lists the exact commands for their computer."}


def _taste(ctx: Ctx) -> dict:
    t = ctx.taste or {}
    if not t.get("available"):
        return {"raw": "error", "why": f"taste profile unreadable: {t.get('error')}", "next_cmd": "slop doctor"}
    taps, m = int(t.get("taps") or 0), t.get("meter") or None
    meter = ""
    if m and m.get("accuracy") is not None:
        meter = f", meter {m['accuracy'] * 100:.0f} %" + (f" ± {m['margin'] * 100:.0f}" if m.get("margin") else "")
    data = {"taps": taps, "images": t.get("images"), "meter": m, "font_picks": t.get("font_picks")}
    if taps >= TASTE_TAPS:
        return {"raw": "done", "data": data, "why": f"{taps} taps{meter} (your user profile; it follows you to every "
                                                    "project)"}
    p = _newest(ctx)
    if not p:
        return {"raw": "blocked", "data": data, "blocked_by": ["first-project"],
                "why": f"{taps} taps so far; the tap app runs inside a project (first-project)"}
    return {"raw": "todo", "data": data, "next_skill": "claudia-relay",
            "why": f"{taps} of {TASTE_TAPS} recommended taps{meter}",
            "do": "the taste session is the production's: pass 'start my taste session' with `slop --json relay send` "
                  "(it posts the phone link: about 7 min of taps)"}


def _first_project(ctx: Ctx) -> dict:
    ps = [p for p in ctx.projects if not p.get("broken")]
    if ps:
        p = ps[0]
        more = f"{len(ps)} projects; newest" if len(ps) > 1 else "project"
        return {"raw": "done", "next_cmd": _pcmd(p["name"], "status"),
                "why": f"{more} {p['name']}" + (f" ({p['tier']} tier)" if p.get("tier") else "")}
    return {"raw": "todo", "next_skill": "claudia-relay", "why": "no project yet",
            "do": "the production makes the project with the person's first request: pass their words with "
                  "`slop --json relay send`"}


FUNCS = {"tier": _tier, "toolkit": _toolkit, "path": _path, "doctor": _doctor, "full-profile": _full,
         "openrouter": _openrouter, "arena": _arena, "higgsfield": _higgsfield, "hedra": _hedra, "drive": _drive, "suno": _suno,
         "suno-signin": _suno_signin, "lyria": _lyria, "midjourney": _midjourney, "mj-profile": _mj_profile,
         "mj-signin": _mj_signin, "api-images": _api_images, "codex-images": _codex_images, "video": _video,
         "coding-agents": _coding_agents, "gpu": _gpu, "taste": _taste, "first-project": _first_project}
DIRECTOR_NEEDS = "the Director tier needs one coding agent signed in, on the box or on your own computer"


def _director_note(ctx: Ctx, r: dict) -> dict:
    """The agent the Director tier waits for says so in its `why`."""
    if ctx.tier == "director" and r.get("need") == "r" and r.get("raw") in ("todo", "error"):
        r["why"] = f"{r.get('why') or ''} ({DIRECTOR_NEEDS})".strip()
    return r


FUNCS.update({f"agent-{e}": (lambda c, e=e: _director_note(c, _agent(c, e))) for e in ENGINES})
FUNCS.update({f"home-{e}": (lambda c, e=e: _director_note(c, _home(c, e))) for e in ENGINES})
EXTRA_KEYS = ("record_cmd", "ask", "answers", "blocked_by", "any_of", "warn", "long", "running", "available", "data")


def _finalize(ctx: Ctx, spec: dict, r: dict) -> dict:
    iid = spec["id"]
    need = r.pop("need", None) or spec["need"][TIER_INDEX[ctx.tier]]
    raw = r.pop("raw")
    m = _mark(ctx, iid)
    skipped = raw == "skipped"
    if raw not in ("done", "skipped") and m and m.get("state") == "skip" and r.get("available") is not False:
        skipped = True
        r["why"] = f"skipped on {_date(m)}{_note(m)}; undo: slop onboard mark {iid} --todo"
        for k in ("ask", "answers", "record_cmd", "blocked_by", "any_of", "next_cmd"):
            r.pop(k, None)
    if skipped:
        state = "optional"
    elif raw in ("done", "error"):
        state = raw
    elif raw == "blocked":
        state = "blocked" if (need != "o" or r.get("available") is False) else "optional"
    else:
        state = "todo" if need != "o" else "optional"
    item = {"id": iid, "group": spec["group"], "title": spec["title"], "state": state, "need": NEED[need],
            "check": "auto" if spec["kind"] == "check" else "recorded", "why": r.get("why") or "",
            "do": r.get("do"), "next_cmd": r.get("next_cmd"), "next_skill": r.get("next_skill"),
            "cost_note": r.get("cost") or spec["cost"], "unlocks": spec["unlocks"]}
    for k in EXTRA_KEYS:
        if r.get(k) is not None:
            item[k] = r[k]
    if skipped:
        item["skipped"] = True
    return item


def build(ctx: Ctx) -> list[dict]:
    if ctx.tier not in TIERS:
        raise SlopError(f"tier must be one of {', '.join(TIERS)}")
    return [_finalize(ctx, spec, FUNCS[spec["id"]](ctx)) for spec in CATALOG]


def pick_next(items: list[dict], exclude=(), order: list[str] | None = None) -> dict | None:
    by = {i["id"]: i for i in items}
    for iid in order or PRIORITY:
        it = by.get(iid)
        if not it or iid in exclude or it.get("running"):
            continue
        if it["state"] == "todo" or (it["state"] == "error" and it["need"] != "optional"):
            return it
    return None


def readiness(items: list[dict], ctx: Ctx) -> dict:
    """Quick: the toolkit and doctor (no account: Grok's image tool, 2.5D, the user's song). Studio: + the full
    analysis install + video (OpenRouter OR Higgsfield). Director: + one Director agent signed in (box or home)."""
    by = {i["id"]: i for i in items}

    def missing(ids, base=()):
        return list(base) + [i for i in ids if by[i]["state"] != "done" and i not in base]
    q = missing(["toolkit", "doctor"])
    s = missing(["video", "full-profile"], q)
    agents = _director_agents(ctx)
    pref = pref_engine(ctx)
    if agents:
        extra = []
    elif pref:
        extra = [f"agent-{pref}" if _box_route(ctx, pref) else f"home-{pref}"]
    else:
        extra = ["coding-agents"]
    d = s + extra
    return {"quick": {"ready": not q, "missing": q}, "studio": {"ready": not s, "missing": s},
            "director": {"ready": not d, "missing": d, "agents": [f"{e} ({w})" for e, w in agents]}}


def _stuck_reason(by: dict, it: dict, exclude, seen: frozenset) -> str:
    iid = it["id"]
    if it.get("running"):
        return "installing now; check again later: slop onboard status"
    if it.get("skipped"):
        return f"skipped; undo only if the user agrees: slop onboard mark {iid} --todo"
    if it.get("available") is False:
        return it["why"]
    if iid in exclude:
        return "passed over with --except; run slop onboard next without it"
    if it["state"] == "blocked" and iid not in seen:
        parts = [f"{b} ({_stuck_reason(by, by[b], exclude, seen | {iid})})" for b in it.get("blocked_by") or []
                 if b in by and by[b]["state"] != "done"]
        lead = "waits for one of: " if it.get("any_of") and len(parts) > 1 else "waits for "
        return (lead + "; ".join(parts)) if parts else it["why"]
    if it["state"] in ("todo", "error"):
        return f"{it['state']}: {it['why']}"
    return it["why"]


def stuck(items: list[dict], tiers: dict, tier: str, exclude=()) -> list[dict]:
    """Why each item the tier still misses cannot be done right now (skipped, installing, blocked, excluded)."""
    by = {i["id"]: i for i in items}
    return [{"id": iid, "state": by[iid]["state"], "reason": _stuck_reason(by, by[iid], exclude, frozenset())}
            for iid in tiers[tier]["missing"] if iid in by]


def _words(ids, sep: str) -> str:
    return sep.join(WAY_NAMES[i] for i in ids)


def routes(items: list[dict], ctx: Ctx) -> dict:
    """What works now: {stills, clips, song: [ids], text}. Grok's image tool (stills, listed last: the fallback) and
    the user's own song upload (listed first) are always there - all the Quick tier needs; clips [] = 2.5D motion
    with devices only. Lyria only with OpenRouter."""
    by = {i["id"]: i for i in items}
    prov = [x for x in ROUTES if route_ok(ctx, x)]
    sets = _settings(ctx)
    stills = prov + (["codex"] if by["codex-images"]["state"] == "done" else []) + (
        ["midjourney"] if sets.get("mj_plan") in PAID_MJ else []) + ["grok-image"]
    song = ["upload"] + (["suno"] if sets.get("suno_plan") in PAID_SUNO + ("free",) else []) + (
        ["lyria"] if by["lyria"]["state"] == "done" else [])
    clips = f" plus {_words(prov, ' and ')} clips" if prov else ""
    text = (f"stills from {_words(stills, ' or ')}, 2.5D motion with devices{clips}, the song from "
            f"{_words(song, ' or ')}")
    return {"stills": stills, "clips": prov, "song": song, "text": text}


def install_summary(items: list[dict], ctx: Ctx) -> dict:
    """{state: ready|installing|minimal|broken|missing, text}: probe first, so the setup says "ready" instead of
    announcing an install that is already done."""
    by = {i["id"]: i for i in items}
    tk, fp = by["toolkit"], by["full-profile"]
    ver = (ctx.tk or {}).get("version") or "?"
    if tk.get("running") or fp.get("running"):
        return {"state": "installing", "text": "bin/setup.sh is installing now; go on with other steps and check "
                                               "again later: slop onboard status"}
    if tk["state"] != "done":
        return {"state": "missing", "text": "not installed yet: bin/setup.sh --minimal (about 5 min), then --full for "
                                            "the song analysis (about 5 min in all)"}
    if fp["state"] == "done":
        return {"state": "ready", "text": f"ready: claudia {ver}, full profile; nothing to install"}
    if fp["state"] == "error":
        return {"state": "broken", "text": f"claudia {ver} installed, but the full analysis install is broken: "
                                           "bin/setup.sh --full again (about 5 min)"}
    return {"state": "minimal", "text": f"claudia {ver} installed (minimal profile); the full analysis install "
                                        "(about 5 min) is still to do"}


def unlocks(items: list[dict], tiers: dict, ctx: Ctx) -> list[dict]:
    out: list[dict] = []
    box = "on the box" if (ctx.tk or {}).get("on_box", True) else "on this computer"
    if tiers["quick"]["ready"]:
        out.append({"key": "tier:quick",
                    "text": f"Quick tier ready: {routes(items, ctx)['text']}, render and master here"})
    if tiers["studio"]["ready"]:
        via = " and ".join(_vias(ctx))
        out.append({"key": "tier:studio",
                    "text": f"Studio tier unlocked: sung clips with measured lip sync via {via}, full analysis "
                            "install"})
    if tiers["director"]["ready"]:
        agents = _director_agents(ctx)
        pref = pref_engine(ctx)
        e, where = sorted(agents, key=lambda a: (a[0] != pref, a[1] != "box"))[0]
        out.append({"key": "tier:director", "text": f"Director tier unlocked: {ENGINE_NAMES[e]} logged in "
                                                    + (box if where == "box" else "on your computer")})
    seen = {u["text"] for u in out}
    for it in items:
        text = it["unlocks"].replace("on the box", box)
        if it["state"] == "done" and it["id"] in HEADLINE and text not in seen:
            out.append({"key": f"item:{it['id']}", "text": text})
            seen.add(text)
    return out


# ---------------------------------------------------------------- the report
def _safe(fn, default, *a):
    try:
        return fn(*a)
    except Exception as e:  # one broken probe must not hide the rest of the checklist
        d = dict(default)
        d["error"] = probes.scrub(f"{type(e).__name__}: {e}")
        return d


def gather(offline: bool = False) -> dict:
    """Run every probe (doctor, key, agents, GPU in parallel). Returns the Ctx fields."""
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = {"doc": ex.submit(_safe, probes.doctor, {"ok": False}),
                "key": ex.submit(_safe, probes.openrouter, {"present": util.env_present("OPENROUTER_API_KEY"),
                                                            "checked": False, "valid": None}, offline),
                "agents": ex.submit(_safe, probes.agents, {"available": True, "engines": {}}),
                "gpu": ex.submit(_safe, probes.gpu, {"available": True, "mode": "none", "ok": False})}
        out = {"tk": probes.toolkit(), "env": _safe(probes.env_names, {}),
               "taste": _safe(probes.taste, {"available": False}), "projects": probes.projects(),
               "running": _safe(probes.setup_running, {}) or []}
        for k, f in futs.items():
            out[k] = f.result()
    return out


def resolve_tier(tier: str | None, s: dict, projects: list[dict]) -> tuple[str, str]:
    if tier:
        if tier not in TIERS:
            raise SlopError(f"--tier must be one of {', '.join(TIERS)}")
        return tier, "--tier"
    if s.get("tier") in TIERS:
        return s["tier"], "chosen"
    for p in projects:
        if p.get("tier") in TIERS:
            return p["tier"], f"from project {p['name']}; choose: slop onboard set tier quick|studio|director"
    return "quick", "default; choose: slop onboard set tier quick|studio|director"


def report(tier: str | None = None, offline: bool = False, record: bool = True, data: dict | None = None) -> dict:
    s = st.load()
    data = data if data is not None else gather(offline)
    t, src = resolve_tier(tier, s, data.get("projects") or [])
    ctx = Ctx(tier=t, s=s, offline=offline, tier_source=src, **data)
    items = build(ctx)
    tiers = readiness(items, ctx)
    unl = unlocks(items, tiers, ctx)
    new: dict = {}
    if record and unl:
        try:
            new = st.record_unlocks([u["key"] for u in unl])
        except (OSError, SlopError):
            new = {}
    order = priority(ctx)
    nxt = pick_next(items, order=order)
    ready = tiers[t]["ready"]
    counts = {x: sum(1 for i in items if i["state"] == x) for x in STATES}
    return {"ok": True, "tier": t, "tier_source": src, "ready": ready, "counts": counts, "items": items,
            "tiers": tiers, "unlocked": [u["text"] for u in unl],
            "new_unlocks": [u["text"] for u in unl if u["key"] in new],
            "next_item": nxt["id"] if nxt else None, "priority": order,
            "stuck": [] if (nxt or ready) else stuck(items, tiers, t),
            "running": [i["id"] for i in items if i.get("running")],
            "routes": routes(items, ctx), "install": install_summary(items, ctx),
            "hand_off": HAND_OFF[t] if ready else None, "state_file": str(st.path())}


# ---------------------------------------------------------------- text
def action_text(it: dict) -> str:
    parts = []
    if it.get("ask"):
        parts.append(f"ask: {it['ask']}")
    if it.get("next_skill"):
        parts.append(f"skill {it['next_skill']}")
    if it.get("next_cmd"):
        parts.append(f"run: {it['next_cmd']}")
    if it.get("record_cmd"):
        parts.append(f"after you saw it working: {it['record_cmd']}")
    return "; ".join(parts) or (it.get("do") or "")


def extras_text(rep: dict) -> str:
    """Optional items still open, by group: agents and the GPU first (so they are always offered)."""
    order = ["agents-box", "agents-home", "gpu", "music", "stills", "connectors", "keys", "taste", "toolkit",
             "project", "start"]
    by_group: dict[str, list[str]] = {}
    for i in rep["items"]:
        if i["state"] == "optional" and not i.get("skipped") and i.get("available") is not False:
            by_group.setdefault(i["group"], []).append(i["id"])
    labels = dict(GROUPS)
    return "; ".join(f"{labels[g]}: {', '.join(by_group[g])}" for g in order if g in by_group)


def render_status(rep: dict, group: str | None = None) -> str:
    c = rep["counts"]
    L = [f"Claudia setup - {rep['tier']} tier ({rep['tier_source']}): {c['done']} done, {c['todo']} to do, "
         f"{c['error']} errors, {c['blocked']} blocked, {c['optional']} optional"]
    if rep.get("new_unlocks"):
        L.append("NEW: " + "; ".join(rep["new_unlocks"]))
    for gid, label in GROUPS:
        if group and gid != group:
            continue
        L.append(label)
        for i in (x for x in rep["items"] if x["group"] == gid):
            L.append(f"  {SYMBOL[i['state']]} {i['id']:<13} {i['why']}")
            if i.get("warn"):
                L.append(f"        ! {i['warn']}")
            if i["state"] in ("todo", "error") and not i.get("running"):
                a = action_text(i)
                if a:
                    L.append(f"        -> {a}")
    L.append("Tiers: " + " | ".join(f"{k} " + ("ready" if v["ready"] else "needs " + ", ".join(
        MISSING_LABEL.get(m, m) for m in v["missing"])) for k, v in rep["tiers"].items()))
    if rep.get("routes"):
        L.append("Works now: " + rep["routes"]["text"])
    if rep.get("unlocked"):
        L.append("Unlocked: " + "; ".join(rep["unlocked"]))
    if rep.get("running"):
        L.append("Installing now: " + ", ".join(rep["running"]) + " (check again later)")
    nx = next((i for i in rep["items"] if i["id"] == rep.get("next_item")), None)
    if nx:
        L.append(f"Next: {nx['id']} ({nx['title']}) - the details: slop onboard next")
    elif rep["tiers"][rep["tier"]]["ready"]:
        L.append(f"Next: everything the {rep['tier']} tier needs is set up - skill {HAND_OFF[rep['tier']]}")
    else:
        L.append(f"Next: the {rep['tier']} tier is NOT ready and nothing can be done for it right now: "
                 + "; ".join(f"{s['id']} - {s['reason']}" for s in rep.get("stuck") or []))
    return "\n".join(L)


def render_next(it: dict | None, rep: dict, exclude=()) -> str:
    tier = rep["tier"]
    ready = rep["tiers"][tier]["ready"]
    if it is None:
        if not ready:
            L = [f"The {tier} tier is NOT ready yet, and nothing can be done for it right now:"]
            L += [f"  {s['id']}: {s['reason']}" for s in stuck(rep["items"], rep["tiers"], tier, exclude)]
            L.append("Tell the user what is missing. To go on: wait for an install to end, undo a skip only with the "
                     "user's OK, or choose another tier with the user (slop onboard set tier quick|studio|director).")
            return "\n".join(L)
        L = [f"Everything the {tier} tier needs is set up."]
        if rep.get("routes"):
            L.append("Works now: " + rep["routes"]["text"])
        if rep.get("running"):
            L.append("Still installing: " + ", ".join(rep["running"]) + " (check again later: slop onboard status)")
        extras = extras_text(rep)
        if extras:
            L.append("Optional extras to offer (slop onboard status shows each): " + extras)
        L.append(f"Make something with Claudia: skill {HAND_OFF[tier]}")
        return "\n".join(L)
    L = [f"Next for the {tier} tier: {it['id']} - {it['title']} [{it['state']}, {it['need']}]",
         f"  why: {it['why']}"]
    if it.get("warn"):
        L.append(f"  note: {it['warn']}")
    if it.get("ask"):
        L.append(f"  ask: {it['ask']}")
        for k, v in (it.get("answers") or {}).items():
            L.append(f"    {k}: {v}")
    if it.get("do"):
        L.append(f"  do: {it['do']}")
    if it.get("next_skill"):
        L.append(f"  skill: {it['next_skill']}")
    if it.get("next_cmd"):
        L.append(f"  run: {it['next_cmd']}" + ("   (long: run it in a background shell)" if it.get("long") else ""))
    if it.get("record_cmd"):
        L.append(f"  record, {RECORD_WHEN}: {it['record_cmd']}")
    L.append(f"  cost: {it['cost_note']}")
    L.append(f"  unlocks: {it['unlocks']}")
    left = rep["counts"]["todo"] + sum(1 for i in rep["items"] if i["state"] == "error" and i["need"] != "optional")
    tail = f"Then: slop onboard next ({left} left for this tier). Pass over it for now: slop onboard next --except " \
           f"{it['id']}"
    if it["need"] != "required":
        tail += f"; the user does not want it: slop onboard mark {it['id']} --skip"
    L.append(tail)
    if ready:
        L.append(f"The {tier} tier is already ready: the user may also start a video now (skill {HAND_OFF[tier]}) and "
                 "finish the setup later.")
    return "\n".join(L)

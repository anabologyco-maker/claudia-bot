"""slop.onboard - one checklist for "set up literally everything" (KITOUT section 1; module owner: onboard).

  slop onboard [status] [--tier quick|studio|director] [--offline] [--group G]   every item, its state, next step
  slop onboard next   [--tier ...] [--offline] [--except ID]   the ONE best next item (what the setup skill runs)
  slop onboard mark ITEM --done|--connected|--skip|--todo [--note TEXT]        record what the bot saw / the user said
  slop onboard set KEY VALUE | --clear       tier, suno-plan, mj-plan, mj-profile, coding-agents (no secrets)
  slop onboard apply --project NAME          copy the recorded Midjourney plan and profile code into that project

Items (id - group): tier (start) | toolkit, path, doctor, full-profile (toolkit) | openrouter, arena (keys) |
higgsfield, drive, video (connectors; video = clips through OpenRouter or Higgsfield) | suno, suno-mcp (Suno's
own connector), suno-signin (its browser fallback), lyria (music) | midjourney, mj-profile, mj-signin, api-images, codex-images (stills) | coding-agents, agent-claude,
agent-codex, agent-muse, agent-gemini (agents on the box) |
home-claude, home-codex, home-muse, home-gemini (agents on the user's own computer) | gpu (home GPU) | taste (user-level
taste profile) | first-project.

Each item: {id, group, title, state: done|todo|optional|blocked|error, need: required|recommended|optional (for the
tier), why, do, next_cmd, next_skill, record_cmd, ask/answers, cost_note, unlocks, blocked_by, data}. `next_cmd` is a
command that runs as printed (no placeholders) and DOES the step; `ask` + `answers` is a question with one exact command
per answer; `record_cmd` records a step only the bot can see (a connector, a browser sign-in, an agent on the user's
own computer) and runs ONLY after the bot saw it working. `slop onboard next --json` therefore keeps them apart: `next`
is only ever a next_cmd (null for a question or a record step), `record_cmd` + `record_when` stand on their own.

The first questions are the tier, the user's coding-agent plans (Claude, ChatGPT/Codex, Muse Code, Gemini) and the
home GPU (paired, direct or none): asked once in every tier, so the agents and the GPU are always offered. The plans
decide which agent items are recommended, and in the Director tier which engine is REQUIRED (on the box, else on the
user's own computer). Director-capable engines are read from the repository: named on a delegation brief's
`engines:` line (templates/briefs) and driven by runner/deleg.mjs - today claude, codex, muse. A box agent counts for
Director only when it is the engine new delegated jobs use (`slop agents use X --for director`, else Claude Code).

Tier readiness (owner decision 2026-10-02): Quick = toolkit + doctor, no account (stills from Grok's own image tool,
2.5D motion with devices, the user's song upload; Lyria only with OpenRouter). Studio = Quick + the full analysis
install + `video`: OpenRouter OR Higgsfield (both recommended: OpenRouter is cheaper per second, Higgsfield copies the
vocals more reliably on stubborn windows; the last one left is required; an expired key is no route). Director =
Studio + one Director-capable coding agent signed in, on the box or at home. `routes` (status and next) says what works now: stills, clips, song.
`install` says ready | installing | minimal | broken | missing, so the setup probes before announcing an install.

"All set" (`all_set`, `hand_off`) means the tier is READY. When nothing can be picked but the tier is not ready (a
required item skipped, blocked or installing), `next` lists `stuck` reasons and hands off to nothing.

Two kinds of item:
  * checked items are measured on every call (re-checkable after a box wipe): the toolkit install, PATH, `slop
    doctor --quick`, OPENROUTER_API_KEY via the FREE GET /api/v1/key (limit, usage, expiry), ARENA_TOKEN present,
    `slop agents status` and `slop gpu status` (when the slop command loads those modules), the user taste profile
    (taps, meter) and the projects folder. They cannot be marked done by hand, only skipped.
  * recorded items come from $SLOP_HOME/onboard.json (marks and settings): the tier, connectors (the bot sees them),
    Suno and Midjourney plans, coding-agent plans, browser-assist sign-ins, agents on the home computer.

State file: $SLOP_HOME/onboard.json (slop/onboard/state.py documents the schema). It NEVER holds a secret: notes that
look like a key or token, hold an account address or mention a password / token / one-time code are refused, env vars
are reported by NAME and presence only, and agent/GPU probes keep only installed / logged in / plan / version (never
an account address or a token).

Integration with slop.agents and slop.gpu is defensive: a family counts as available only when the router loads it
(slop/cli.py MODULES or $SLOP_MODULES); its own CLI (`slop --json agents status`, `slop --json gpu status`) runs in a
child process with a time limit (15 s, under the bot shell's limit), and the JSON is read shape-tolerantly
(probes.normalize_agents / normalize_gpu). A command another module suggests is used only when it parses with that
module's own parser. Absent module -> the items say "not available in this toolkit version" (state blocked).

Retention: `unlocked` lists what the user can do now ("Director tier unlocked: Claude Code logged in on the box");
`new_unlocks` lists what became possible since the last check (first-seen times are kept in onboard.json).
"""

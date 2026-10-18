# 96 · Setup and hardware: the onboarding checklist, coding agents, a home GPU

Read this when you set a user up for the first time, when the user says "setup", after the bot's computer was updated
or wiped, and whenever a coding agent or the home GPU stops working. It covers three command families:

- `slop onboard`: one checklist of everything a user can set up (tier, toolkit, keys, connectors, music, stills,
  coding agents, a home GPU, taste, first project), with the single next step for their tier.
- `slop agents`: Claude Code, Codex (on a ChatGPT plan), Muse Code and Gemini CLI installed and signed in on the bot's
  computer, so the Director tier no longer needs the user's own PC.
- `slop gpu`: the user's own NVIDIA GPU (or Apple Silicon Mac) doing the heavy analysis steps for the box.

The Grok Bot skills that drive these are `claudia-setup` (the checklist loop), `setup-accounts`, `setup-agents` and
`setup-gpu`. The skills are short; this doc is the long form. The help text of each command is authoritative
(`slop onboard --help`, `slop agents login --help`, `slop gpu pair --help`).

Words used here: **the box** = the Grok Bot's cloud computer (8 vCPU, 15 GiB, no GPU; only `/workspace` survives a
computer update). **The home computer** = the user's own PC or Mac. **The secure secret card** = Grok Bot's masked
input that stores a secret as an environment variable on the box.

---

## 1. The order of setup, and what each tier needs

`slop onboard next` always knows the order; this is what it walks through:

1. **Tier** (asked first): quick, studio or director. It decides which items are required.
2. **Toolkit**: `bin/setup.sh --minimal`, `slop` on PATH, `slop doctor` clean, and the full analysis install
   (`bin/setup.sh --full`: required for Studio and Director, recommended for Quick, whose song analysis needs it).
   Both together take about 5 min (2-3 min measured on the box; the analysis models download with the first
   analysis). The setup probes first (`setup.sh --check --json`) and says "ready" when nothing is left to install;
   it runs the two installs detached, so no shell call times out.
3. **Keys** through the secure secret card: `OPENROUTER_API_KEY` (with its own credit limit), optional `ARENA_TOKEN`
   and `ELEVENLABS_API_KEY` (the production's ElevenLabs tools; `slop relay setup` turns them on).
4. **Connectors** the bot sees: Higgsfield (sung clips on the user's credits), optional Google Drive.
5. **Music and stills plans**: Suno plan and Midjourney plan and personal profile code (never published); the user
   signs in to each once in Grok's browser, and from then on Grok runs them.
6. **Coding-agent plans** (asked in every tier): Claude, ChatGPT (Codex), Meta (Muse Code), Google (Gemini), none.
   Each plan the user has becomes a recommended item: install and sign in that agent on the box.
7. **Home GPU** (asked in every tier): paired, direct or none.
8. **Taste profile** (about 7 min of taps on the phone) and the **first project**.

A tier is READY when these items are done:

| Tier | Ready when | Usually also recommended |
|---|---|---|
| Quick | toolkit, doctor (no account: stills from Grok's GenerateImage, 2.5D motion, the user's own song) | full analysis install, OpenRouter, Higgsfield, Lyria, home GPU |
| Studio | the Quick items plus full-profile and video: OpenRouter or Higgsfield (either; the last one left after a skip is required; an expired OpenRouter key does not count) | both video routes, Suno and Midjourney plans, taste, home GPU |
| Director | the Studio items plus one Director-capable agent signed in (box or home computer) | a second agent, home GPU |

Director-capable engines are the ones named on a delegation brief's `engines:` line and driven by `runner/deleg.mjs`:
today **Claude Code, Codex and Muse Code**. Gemini CLI runs one-off jobs only (§4.5).

Measured: `slop onboard next` takes about 2.0-2.1 s on a Linux box and 2.7 s on Windows (real probes, nothing paid);
`slop --json onboard status` is about 24 KB, `next` about 4 KB. The only network call is OpenRouter's free key check.

---

## 2. The checklist: `slop onboard`

| Command | What it does |
|---|---|
| `slop onboard status` | every item: state, why, the next step; add `--tier studio` to see another tier, `--group agents-box` for one group, `--offline` to skip the network check |
| `slop onboard next` | the ONE best next item for the user's tier (what the setup skill runs every reply); `--except ID` passes over an item that is installing |
| `slop onboard mark ID --done` | records a step only the bot can see (a connector answered, a browser sign-in, an agent on the home computer); `--connected` for connectors, `--skip` and `--todo` to skip or undo |
| `slop onboard set KEY VALUE` | the user's settings: `tier`, `suno-plan`, `mj-plan`, `mj-profile`, `coding-agents` (`--clear` removes one) |
| `slop onboard apply` | copies the recorded Midjourney plan and profile code into a project (`--project NAME`) |

Item states: `done`, `todo`, `optional`, `blocked` (waits for another item, listed in `blocked_by`) and `error`.
Each item also says how much the tier needs it: `required`, `recommended` or `optional`.

### 2.1 Reading `slop --json onboard next`

The fields, in the order you act on them:

- `new_unlocks`: what became possible since the last check ("Director tier unlocked: Claude Code logged in on the
  box"). Say it first, in one line. `unlocked` lists everything that works now.
- `item.next_skill`: a skill to read before acting (`setup-accounts`, `setup-agents`, `setup-gpu`, `taste`). Its
  order wins over `next`.
- `ask` + `answers`: a question for the user, with one exact command per answer. Ask it, then run the command of
  the answer they chose. A code or a name is asked in plain text, never with a widget.
- `next`: a command that runs as printed (no placeholders) and DOES the step. It is null when the step is a question
  or something only the bot can check.
- `record_cmd` + `record_when`: the command that records a step only the bot can see. Run it ONLY after you saw the
  step working yourself (the connector answered, the sign-in check showed the user signed in).
- `item.long`: the step runs for minutes; start it detached and continue with
  `slop onboard next --except ID` meanwhile.
- `ready`: the tier is ready. Offer once to start the video now; the optional items can wait.
- `stuck`: nothing can be picked but the tier is not ready. Each entry names the item and why (skipped, installing
  now, waits for another item, passed over with `--except`). Tell the user and ask: fix it, choose another tier, or go
  on without it. `all_set` and `hand_off` stay empty until the tier is really ready.
- `hand_off`: the skill that takes over when the tier is ready (`mv-quick`, `mv-studio`, `mv-director`).
- `warn`: something the user should know (for example, a required item was skipped: the tier cannot become ready).

### 2.2 Checked items and recorded items

- **Checked** items are measured on every call, so they are right again after a box wipe: the toolkit install, PATH,
  `slop doctor --quick`, the OpenRouter key (the free GET /api/v1/key: limit, usage, expiry), `ARENA_TOKEN` present,
  `slop agents status`, `slop gpu status`, the taste profile and the projects folder. They cannot be marked done by
  hand, only skipped.
- **Recorded** items come from `$SLOP_HOME/onboard.json`: the tier, the plans, the connectors, browser sign-ins and
  agents on the home computer.

### 2.3 What onboard.json may hold

Never a secret. Notes that look like a key or token, hold an account address, or mention a password, a one-time code
or a token are refused with "NOT saved". Environment variables are reported by NAME and presence only. Agent and GPU
probes keep only installed / signed in / plan / version, never an account address or a token. The Midjourney
profile code is a style code, not a secret: it is kept in the user settings and copied into projects with
`slop onboard apply`; never post it anywhere public.

---

## 3. Secrets: the one rule

You never see, type, paste or store a secret. Keys, tokens and sign-in codes reach the box only through the **secure
secret card**, which saves them as an environment variable. The toolkit then reads that variable by its NAME:

| Variable | What it is | Read by |
|---|---|---|
| `OPENROUTER_API_KEY` | the user's OpenRouter key (give it its own credit limit) | `slop gen`, `slop spend`, the onboard check |
| `ARENA_TOKEN` | Are.na personal access token (optional) | `slop taste` import |
| `ELEVENLABS_API_KEY` | ElevenLabs API key (optional) | the production's ElevenLabs MCP tools (passed by name, never written) |
| `CLAUDE_LOGIN_CODE` | the code the claude.ai sign-in page shows | `slop agents login claude --code-from-env CLAUDE_LOGIN_CODE` |
| `CLAUDE_CODE_OAUTH_TOKEN` | a long-lived token from `claude setup-token` on the user's computer | `slop agents login claude --token-from-env CLAUDE_CODE_OAUTH_TOKEN`; Claude jobs |
| `GEMINI_LOGIN_CODE` | the code Google's sign-in page shows | `slop agents login gemini --code-from-env GEMINI_LOGIN_CODE` |
| `GEMINI_API_KEY` | a Gemini API key (billed by Google) | `slop agents login gemini --key-from-env GEMINI_API_KEY`; Gemini jobs started with `--pass-env GEMINI_API_KEY` |

Rules the code enforces:

- `--code-from-env` reads only the engine's own code variable; `--key-from-env` accepts only `GEMINI_API_KEY`.
- A one-time sign-in code is typed into the waiting sign-in and never printed, logged or stored on disk.
- Each engine sees only its own sign-in variable: another vendor's agent (which may run shell commands) never sees
  the user's Claude token. The toolkit's own secrets (`OPENROUTER_API_KEY`, `ARENA_TOKEN`, `ELEVENLABS_API_KEY`)
  never reach any agent except the relay's production, the one spender.
- Variables that would switch an agent from the user's plan to pay-per-token API billing are removed from every agent
  run (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `CODEX_API_KEY`, `META_API_KEY`, `GOOGLE_API_KEY` and similar). Codex
  runs with `forced_login_method="chatgpt"`.
- A key pasted in chat by mistake is burned: ask the user to revoke it and make a new one.

"not set in this shell" right after the card: the card's variable reaches NEW shells. Run the same command again in a
new shell, for example
`bash -lc '/workspace/claudia/bin/slop --json agents login claude --code-from-env CLAUDE_LOGIN_CODE'`,
before asking the user again.

---

## 4. Coding agents on the box: `slop agents`

The agents do the heavy Director work (the storyboard panel, chapter motion design, reviews, the safety scan) on the
user's own plan: no API cost, the plan's own limits. Running them **on the box** means no approval cards and jobs that
keep running while the user is away. The order is always install, sign in, test, choose:

```bash
slop --json agents status                 # installed? version? signed in, which plan?
slop --json agents install claude         # a background job; then: slop --json job wait ID
slop --json agents login claude           # prints the link (and code) for the user
slop --json agents test claude            # one tiny "reply OK" run through runner/deleg.mjs
slop --json agents use claude --for director
```

### 4.1 Which engine for what

| Engine | Plan | Install (box) | Sign-in flow | Director agent | Notes |
|---|---|---|---|---|---|
| Claude Code | Claude Pro or Max | the official native installer; copied under `$SLOP_HOME` | link, then the code back through the card; or a `claude setup-token` token | yes, the best: its Workflow tool runs the panel, chapters and reviews | Workflow may be off on Pro |
| Codex | ChatGPT Plus or Pro | npm (`@openai/codex`) into `$SLOP_HOME/npm` | device code: open the link, enter the code | yes: the same briefs run step by step | also stills on the ChatGPT plan (§4.7) |
| Muse Code | Meta account | the installer from dev.meta.ai into `$SLOP_HOME/muse` | device code: open the link, approve | yes, for the storyboard panel, reviews and safety scan | research-lyrics, prompt-book and chapter-motion need Claude Code or Codex |
| Gemini CLI | Google sign-in, or `GEMINI_API_KEY` | npm (`@google/gemini-cli`, needs Node 20+) | link, then the code back through the card; or the key | no | one-off jobs with `--engine gemini` only |

### 4.2 Install

`slop agents install ENGINE` (or `all`) runs as a background `slop job`. Install only the engines the user has a plan
for, one after another, after one yes from the user ("I install ENGINE on my computer with the maker's own installer,
under /workspace, and you sign it in to your plan").

Where things go (`$SLOP_HOME` is `/workspace/.claudia` on the box, so a computer update keeps them):

- `bin/<engine>`: a link to the real command; `$SLOP_HOME/env.sh` puts `bin/` on PATH.
- `npm/`: the npm prefix for Codex and Gemini CLI.
- `muse/`: Muse Code's launcher and binary (`MUSE_NO_AUTO_UPDATE=1`).
- `claude/versions/<v>/claude`: a copy of the native Claude Code binary (the official installer puts it under the home
  folder, which an update may remove; the two newest copies are kept). Claude jobs on the box run with
  `DISABLE_AUTOUPDATER=1` so the kept copy stays the one in use.
- `agents/`: sign-in sessions, install logs, test jobs and the box's job slots.

Disk: all four engines take about 1.3 GB (the Claude Code copy alone about 234 MB). `--dry-run` prints the plan
without installing; `--upgrade` installs the newest version again.

**Sign-ins stay in the home folder** (`~/.claude`, `~/.codex`, `~/.gemini`, `~/.config/muse`). The platform says
sign-ins survive an update, but that is not verified for these files. If an update clears them,
`slop agents status` says "not signed in": run `slop agents login ENGINE` again.

### 4.3 Sign in, per engine

`slop agents login ENGINE` starts a keeper in the background (it outlives the shell call and the turn), prints the
link (and code), and keeps the CLI waiting for up to 15 minutes. Several engines: start every sign-in in one reply
and send the links together.

- **Claude Code.** Send the link: "Open it, approve, and copy the code the page shows." Ask for the code with the card
  named `CLAUDE_LOGIN_CODE`, then `slop agents login claude --code-from-env CLAUDE_LOGIN_CODE`.
  Alternative for a user at their own computer: they run `claude setup-token` there and you ask for the result with
  the card named `CLAUDE_CODE_OAUTH_TOKEN`, then `slop agents login claude --token-from-env CLAUDE_CODE_OAUTH_TOKEN`.
  While that variable is set, `slop agents login claude --force` refuses (the token is the sign-in).
- **Codex (ChatGPT plan).** Send the link and the one-time code: "Open the link, sign in with ChatGPT, enter this
  code." Then `slop agents login codex --check` (waits up to 25 s; still pending: check again next turn). If ChatGPT
  refuses the code, the user may have to allow device-code sign-in in ChatGPT's security settings (not verified with a
  real account); then `slop agents login codex --cancel` and start again.
- **Muse Code.** Send the link and code: "Open the link and approve this code with your Meta account." Then
  `slop agents login muse --check`.
- **Gemini CLI.** Send the link; the code comes back through the card named `GEMINI_LOGIN_CODE`:
  `slop agents login gemini --code-from-env GEMINI_LOGIN_CODE`. Or a key through the card named `GEMINI_API_KEY`:
  `slop agents login gemini --key-from-env GEMINI_API_KEY` (Google bills it; a Gemini job then needs
  `--pass-env GEMINI_API_KEY` on its start command, after the user's yes).

A sign-in that is stuck: `slop agents login ENGINE --cancel`, then start again. `--check` waits up to 25 s for a
waiting sign-in to finish and says where it is.

### 4.4 Test and plan limits

- `slop agents test ENGINE` runs one tiny "reply OK" job through `runner/deleg.mjs`. A rejected sign-in (401 or
  similar) gives a `next` such as `slop agents login claude --force`. When it sets `ask_user`, ask the user for that
  (for example a new `claude setup-token`) through the card.
- `slop agents status --limits` reads the plan's usage without spending a token: Claude Code through the same usage
  read its own /usage screen makes, Codex through `codex app-server` (account and rate limits). Muse Code and Gemini
  CLI have no account-level usage read. Near a limit: wait for its reset, or use another engine.

### 4.5 Choosing who does what: `slop agents use`

`slop agents use ENGINE --for director|review|images` saves the choice in `$SLOP_HOME/onboard.json`. With no
arguments it shows the current choice.

- **director**: `runner/deleg.mjs new` without `--engine` uses this engine whenever the brief's `engines:` line lists
  it. A brief that runs a Claude Workflow (storyboard panel, research-lyrics, chapter-motion, safety scan) then runs
  step by step without the Workflow (the brief's own method for Codex and Muse). A brief that does not list the engine
  stays on Claude Code, and `new` says so (`engine_from`, `engine_note`). `slop agents use codex --for director`
  prints exactly which briefs run as they are, which run step by step and which stay on Claude.
- **review**: the same for the review and safety-scan briefs (else they follow the director choice).
- **images**: `codex` makes `slop gen image` without `--provider` use the ChatGPT plan (§4.7).

Gemini CLI is refused as director or review agent: no brief lists it, and headless Gemini may run without shell
commands, which every brief's checks need (not verified; `new --engine gemini` warns for briefs that need the shell).
`node runner/deleg.mjs new … --engine gemini` still runs a single job on it.

### 4.6 How many agent jobs run at once

At most **2 agent jobs** run at the same time on the whole box, across every project (renders share the 8 vCPU and
15 GiB). More jobs wait as queued. The slots are lock files in `$SLOP_HOME/agents/slots`; a dead job's slot is taken
over. `DELEG_BOX_SLOTS` changes the number. The tiny preflight of `slop agents test` does not take a slot.

### 4.7 Stills on the ChatGPT plan (experimental)

With Codex signed in: `slop agents use codex --for images`. Then `slop --project my-song gen image --jobs` (a dry
run) and, after the owner's G5 yes, the same with `--yes`: the stills are made by `codex exec` with its built-in
image tool on the ChatGPT plan ($0, 1-4 min an image, the plan's image limits), one at a time on the box. Leave out
`--model`, `--res`, `--quality` and `--seed`: any of them keeps the paid OpenRouter models. One image:
`slop --project my-song gen image "PROMPT" --provider codex --plate p001`. This path has not yet made an image on a
real plan: show the owner the first image before a batch.

### 4.8 Agents on the user's own computer

Items `home-claude`, `home-codex`, `home-muse`, `home-gemini`. The bot reaches that computer through Grok Bot local
exec; every command is an approval card unless the user chose "Always allow" (their choice; never push it). The
item's `do` field has the sign-in check for Windows PowerShell and for a Mac or Linux terminal (for example
`claude auth status --json`, or `codex.cmd login status` in Windows PowerShell). Not signed in: the user signs in
there themselves (`claude auth login`, `codex login`, `muse login`, or `gemini`). Once you saw it signed in:
`slop onboard mark home-claude --done`. Running delegated jobs there needs the toolkit runtime on that computer
(`runner/README.md` §1).

---

## 5. A home GPU: `slop gpu`

The box has no GPU. A home NVIDIA GPU (driver 570 or newer, Windows or Linux) or an Apple Silicon Mac (audio and matte
steps only) can run the heavy analysis steps. Everything still works without one, on the box's CPU. It saves minutes,
not money: about 1-2 minutes per song analysis, less on a slow home upload. AMD GPUs are reported as "found, not
supported yet". The full operator guide, with the troubleshooting table, is `slop/gpu/README.md`.

### 5.1 What it speeds up (measured)

Measured with an RTX 3090 Ti on a Windows 11 worker and a Linux box (32 threads), through the Cloudflare tunnel.
Box and worker sat on the same fast home line, so these are best cases for the transfer:

| Step | Box CPU (32 / 8 threads) | GPU, cold worker | GPU, warm worker |
|---|---|---|---|
| analyze stems + align, 60 s excerpt (wall) | 27.5-33.5 s / 32.5 s | 23.1-27.0 s (15.1 s without the tunnel) | 13.0 s (11.3-11.6 s without the tunnel) |
| analyze stems + align, full 5:06 song | 126 s on 8 threads | 41 s | not measured |
| depth maps, 5 plates (edit export) | 6.3 / 7.8 s | 10.5 s | 3.0 s |
| Whisper large-v3 word times, 60 s | paid OpenRouter call instead | 63 s first use (3 GB download) | 7.3 s |
| FILM frame interpolation x2, 12 frames 720p | not available | 10.0 s | not measured |

Results match the CPU path: 92 of 92 word start times identical on the excerpt (447 of 447 on the full song), stems
equal to floating-point level (41-62 dB SNR), depth PNGs within 1/255.

The upload matters: stems for a 5-minute song are about 184 MB. At 10-20 Mbit/s up that alone takes 74-147 s, so
`--gpu auto` measures the PC's upload speed and keeps stems on the CPU when the GPU route would be slower. Depth for
fewer than 8 plates stays on the CPU (as fast as a cold GPU), unless the box cannot run depth at all (a minimal
install without torch).

### 5.2 Paired or direct

| | Paired (recommended) | Direct |
|---|---|---|
| How | the box runs a job server behind a Cloudflare quick tunnel; the PC runs a small worker that polls it | the bot runs each GPU step on the PC through Grok Bot local exec and moves files with CopyFromBox / CopyToBox |
| User does | pastes ONE line in a terminal on the PC, once | approves each command (or sets "Always allow") |
| Works when | the PC is on and the worker runs, also while the user is away | the user's desktop app is open |
| Network | outbound HTTPS from both sides | none between box and PC |

### 5.3 Paired, step by step

1. `slop gpu serve`: the job server and its tunnel start in the background (the public address answers after
   10-30 s).
2. `slop gpu pair`: prints a line for Windows PowerShell and one for macOS / Linux. Send only the one for their
   system, in its own code block: "Paste this once in a terminal on your GPU computer." The first install takes about
   a minute, needs no admin rights and installs everything under `.claudia-gpu` in their home folder (a pinned uv, a
   private Python 3.12, the worker).
3. The line holds a ONE-TIME pairing code: the worker trades it for its own secret within seconds, so the copy in the
   PC's shell history stops working; an unused line expires after 24 h. Share it only with the user.
4. When they say it ran: `slop gpu status` must say healthy and list the GPUs. Not yet: end the turn and check when
   they write. Never poll.
5. `slop gpu install audio matte`: queued installs on the PC (about 4.5 GB; measured 121 s for audio and 34 s for
   matte on a fast line). Check `slop gpu status` when the user writes: both `ready`.
6. Done: `slop analyze` and `slop edit export` use the GPU by themselves.

While a worker is paired, plain `slop gpu pair` refuses (a new code would cut that worker off). To replace the PC or
update the worker code: `slop gpu pair --new` and send the new line. When the box restarts, the tunnel address
changes: `slop gpu serve`, then `slop gpu pair --refresh`, and send its short line (no code needed).

### 5.4 Direct, step by step

1. `slop gpu direct-plan` (a Mac or Linux PC: `slop gpu direct-plan --os mac_linux`) copies the installer and worker
   into the box's kit folder and prints the steps: two CopyFromBox moves, one installer command, one profile install.
   It switches to direct mode only when no mode is set yet (or with `--use-direct`).
2. Run the GPU step as a background job with `--gpu require` (for analysis, `analyze --steps stems,align --gpu require`
   under `slop job start --`). It queues a GPU job, waits, and names it.
3. `slop gpu direct-plan JOB`: packs the job in parts of at most 95 MiB (CopyToBox and CopyFromBox carry at most
   100 MiB a file) and prints every step: copy the parts over, `slopgpu run-bundle JOB --detach`, then
   `slopgpu bundle-status JOB` once per turn until finished, copy the output parts back, then
   `slop gpu direct-ingest JOB`.
4. Switch modes any time: `slop gpu mode paired` or `slop gpu mode direct`.

### 5.5 Routing: `--gpu auto | off | require`

`slop analyze` and `slop edit export` take `--gpu`; without it the mode comes from `$SLOP_GPU`, else `auto`.

- `auto`: the GPU when `slop gpu status` is healthy for that profile, else the CPU with a `note:` saying why. A GPU job
  that fails or meets a busy GPU falls back to the CPU, and so does a step that finds another GPU job ahead of it. A
  missing profile gets an install queued (after a failed install, not again for 6 hours).
- `require`: the GPU or an error that names the next step.
- `off`: the CPU.

A step stopped while it waits (`slop job stop`) cancels its GPU job. Library calls and tests never touch a GPU
unless `SLOP_GPU` or `--gpu` asks for it.

### 5.6 Profiles and licences

| Profile | Runs | VRAM | Download | Licences | Tested on real hardware |
|---|---|---|---|---|---|
| audio | Demucs stems, wav2vec2 alignment, faster-whisper word times | 4 GB or more | about 4.5 GB (shared with matte) | htdemucs code MIT, weights flagged (no licence tag); wav2vec2 Apache-2.0; faster-whisper MIT | yes |
| matte | Depth-Anything-V2-**Small** depth, BiRefNet_HR mattes, SAM 2.1 masks | 6 GB or more | about 4 GB | Apache-2.0 / MIT / Apache-2.0; never the Large depth model | yes |
| interp | FILM frame interpolation | 6 GB or more | about 3 GB | Apache-2.0 | yes |
| lipsync | LatentSync 1.6 | 18 GB or more | about 12 GB | code Apache-2.0, weights OpenRAIL++-M: opt-in only, `slop gpu install lipsync --accept-licence` after the user agrees | no |
| video-local | open-weight video models | 24 GB or more | per model | per model | documented only |

The default rule stays "cut away, no lip-sync fallbacks" (61-lipsync); LatentSync is only for a user who opts in.
Upscaling has no GPU profile yet.

### 5.7 Safety (tell the user once)

- The worker runs only the toolkit's own GPU steps (`proto.ENTRIES`). The box cannot send it a command, a package or a
  model name; parameters are schema-checked; files stay inside the job folder, size-capped (2 GiB a file, 6 GiB a job).
- No API key or account secret ever goes to the PC. The box keeps only hashes of the pairing code and the worker's
  secret. Wrong codes from one address are throttled (HTTP 429 after 30 a minute); a valid code never is.
- The line installs the worker code THIS box serves: the user should paste only lines from their own bot.
- The worker runs hidden; a window popping up on the PC is a bug (`slopgpu stop` there).
- Stop any time: `slop gpu unpair` revokes the pairing (the worker stops by itself), cancels open GPU jobs and stops
  the server and tunnel. Uninstall on the PC: `slopgpu unpair`, then delete the `.claudia-gpu` folder.

---

## 6. After a computer update or a box wipe

Only `/workspace` survives an update. Run `slop onboard status`: checked items are measured again, so it shows what is
gone. Then:

1. The toolkit: `bash /workspace/claudia/bin/setup.sh --check` (it only fetches what is missing when run again).
2. Agents: `slop agents status`. A missing command: `slop agents install ENGINE` (the Claude Code copy under
   `$SLOP_HOME` is found again without a download). "not signed in": `slop agents login ENGINE`.
3. GPU: `slop gpu status`. The server is not running: `slop gpu serve`, then `slop gpu pair --refresh` and the short
   line on the PC. The PC keeps its profiles.
4. Keys: `slop onboard next` checks them again for free; a key that is gone goes through the secure secret card
   again.

---

## 7. Checklists

**First setup, any tier**

- [ ] Tier recorded (`slop onboard set tier quick`).
- [ ] Toolkit installed detached; `slop doctor` clean; `slop job selftest` passed once.
- [ ] Plans recorded: `slop onboard set coding-agents claude,codex` (main first, or `none`), Suno and Midjourney plans.
- [ ] Keys only through the secure secret card; nothing secret in chat, notes or files.
- [ ] Each connector marked only after it answered (`slop onboard mark higgsfield --connected`).
- [ ] Every `stuck` reason told to the user before any hand-off.

**Director on the box**

- [ ] The user said yes to installing the engines they have plans for, and only those.
- [ ] `slop agents install ENGINE` job finished; `slop agents status` shows the version.
- [ ] Signed in (codes only through the card); `slop agents test ENGINE` says OK.
- [ ] `slop agents use ENGINE --for director` when the main engine is not Claude Code; its output read (which briefs
      stay on Claude).
- [ ] `slop agents status --limits` checked before a long job.

**Home GPU**

- [ ] Mode chosen with the user (paired, direct or none); safety told once.
- [ ] Paired: `slop gpu status` healthy; `audio` and `matte` profiles ready.
- [ ] Lip-sync profile installed only after the user accepted its licence.
- [ ] A slow home upload is fine: auto mode keeps stems on the CPU when that is faster.

---

## 8. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| "not set in this shell" right after the card | the card's variable reaches new shells only | the same command in `bash -lc '…'` with `/workspace/claudia/bin/slop` |
| `slop agents test` says the sign-in was rejected | expired or revoked sign-in | its `next` (`slop agents login ENGINE --force`), or the new token it asks for |
| a sign-in session "expired" | 15 minutes passed | `slop agents login ENGINE --cancel`, then start again |
| `slop agents status` "not signed in" after an update | the home folder was cleared | `slop agents login ENGINE` |
| a delegated job stays queued | 2 agent jobs already run on the box | wait; `node runner/deleg.mjs status JOB` says why it waits |
| `gpu status`: the job server is not running | the box restarted | `slop gpu serve`, then `slop gpu pair --refresh` |
| `gpu status`: has not checked in for N s | PC asleep, worker stopped, or the tunnel address changed | the user wakes it or runs `slopgpu start`; else `slop gpu pair --refresh` |
| `gpu pair` says already paired | a worker is paired | nothing to do; replace the PC or update the worker: `slop gpu pair --new` |
| PC: the box refused this pairing code | the line was used, replaced or is older than 24 h | `slop gpu pair --new` and send the new line |
| `gpu status`: BUSY | another program uses the GPU | auto mode uses the CPU meanwhile; or the user closes that program |
| profile install: the cuda device does not work | NVIDIA driver older than 570 | update the driver, install again |
| the quick tunnel never starts | the box blocks Cloudflare | direct mode |
| `onboard next` lists `stuck` | a required item skipped, installing or blocked | tell the user each reason; fix it, choose another tier, or go on without it |

---

## 9. Common mistakes

| Mistake | What it costs | Do instead |
|---|---|---|
| Asking for a key or sign-in code in chat | a leaked secret that must be revoked | the secure secret card, always |
| Writing an account address or a code into an onboard note | refused, or a leak in an old file | notes name the plan only |
| Marking a connector or home agent done without seeing it work | a checklist that lies; the video stalls later | `record_cmd` only after the connector answered or the sign-in check passed |
| Installing all four agents for a user with one plan | about 1.3 GB and four vendors' installers for nothing | only the engines they have plans for |
| Assuming `use codex --for director` moves every brief | a brief that does not list Codex silently stays on Claude | read what `slop agents use` prints |
| Polling the GPU or a sign-in every turn | burns the weekly Grok pool | end the turn; check when the user writes |
| Plain `slop gpu pair` to re-pair a working PC | refused (it would cut the worker off) | `--refresh` for a new address, `--new` to replace |
| Promising GPU speed on a slow home line | stems upload slower than the CPU runs | auto mode decides; say "minutes, not money" |
| Installing the lip-sync profile by default | a licence the user never accepted | only `--accept-licence` after their yes |
| Handing off while `stuck` is not empty | the tier skill hits a missing piece mid-video | tell the user each reason first |

---

## 10. What is verified, and what is not yet

Verified for real: the onboarding probes on Linux and Windows; the agent CLIs' install, sign-in prompts and status
commands (signed out); a copied native Claude Code binary running from `$SLOP_HOME` with an empty home folder; the
paired GPU flow with real processes (pairing exchange, detached worker, unpair) and the GPU timings in §5.1 on an
RTX 3090 Ti.

Not yet verified with real accounts or hardware: a full sign-in of each agent on the box, the shape of Claude's usage
read and Codex's rate limits on a real plan, Muse Code's credential keys, Codex image generation on a real ChatGPT
plan, whether headless Gemini CLI can run shell commands, the lip-sync profile on any GPU, and the box-wide job slots
on the real bot computer. Treat their first real run as a test and show the user the result.

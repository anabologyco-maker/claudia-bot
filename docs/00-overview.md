# 00 · Overview: the pipeline, the tiers, the gates, the budgets

Read this first, once per project, and again whenever you are unsure what comes next. It is the map. Every other doc
is one stage of it.

**Conventions used in every doc**

- **claudia.gallery is the #1 source of truth** (`05-claudia-gallery.md`): Claudia's canon, the films' records and
  the wiki. Connect its MCP server and call `claudia_canon` before making anything; where a doc here disagrees, it wins.
- **EV** = *Escape Velocity* (5:06 lyric video, 141 shots). **SP** = *Clodyssey (Superpersuasion)* (3:11 lyric video,
  94 shots). They are the two reference videos this toolkit was distilled from; *Bliss* and *Airplane Mode* followed.
  All four star Claudia. Their director is **anabology**.
- **The owner** = the person you are making the video for. They make the taste calls. You do the work.
- **The bot** = the Grok Bot running the Claudia template. **You** = whichever model is reading this doc (the bot, or
  a delegated Claude Code / Codex session).
- Numbers are measured on EV or SP unless marked *estimate*.
- Commands are written `slop <group> <command>`. If a command in these docs is missing or named differently in your
  build, run `slop --help` and `slop <group> <command> --help`: **the help text is authoritative**.
  Every command takes `--json` and `--project NAME`. Always pass `--project`; there is no silent default project.
- The file formats (the project layout, `project.json`, `shots.json`, the clip files, the EDL) and the rules the code
  enforces are in `docs/ARCHITECTURE.md`.

---

## 1. What we are making (the bar)

**Claudia content, sized to the ask:** a still, a clip, a song, a music video or a post. Claudia is the lead by
default; make a new character only when the owner asks for one. A still or a clip uses only the stages it needs (her
identity text, the prompt, the owner's yes before spend); a song uses the song stage. The rest of this doc is the
biggest ask, the music video.

A **lyric music video**: a song, a lead character who sings it, and on top of the footage a layer of code-drawn motion
design in which **every sung word appears on screen at the moment it is sung** and **every lyric line gets a graphic that
explains what it means**. That combination is what made EV go viral and what made SP "perfect. change nothing." (the
owner's verdict on SP v1).

The five things that carry the quality, in order of how often a weaker model forgets them:

1. **Measured, not eyeballed.** Word times come from forced alignment checked by ear; cuts come from a beat map; lip
   sync is measured by comparing audio; spend is read from the provider. Every bar that held on EV and SP was a check
   a script could run.
2. **Templates with slots, not improvisation.** The Suno pack, the Midjourney prompt order, the video-prompt
   screenplay format, the display-token syntax and the shot schema are fixed formats. Fill the slots; don't invent new
   phrasings.
3. **One explaining graphic per lyric line**, entering on the word that names it. Animated lyrics alone are not the
   product. The owner's words: "not just animated lyrics but things that fit the words being said … almost explaining
   the words with visuals."
4. **A through-line device** that every shot carries (EV: a split-flap countdown and a LOOK counter; SP: a safety
   card, a rope load readout and an instance counter). It is what makes 100+ shots feel like one object.
5. **The owner's attention is spent only at the gates** (§4). Everything between gates runs without asking.

### 1.1 The twelve non-negotiable rules

Read them once; every later doc tells you how to obey one of them. Where a rule can be checked by a command, the
command refuses to go on until it holds.

1. **Every sung word is on screen at its forced-alignment `t0`** (the lyric gate prints N/N), and the alignment itself
   is checked against the audio (confidence flags and the ear-check list, 20-analysis).
2. **A variable beat map, never one BPM.** Cuts land on beats or hits; motion moves on the beat, words follow the voice.
3. **One explaining graphic per lyric line**; at least 3 ordered layers in every frame; a 2.5D treatment never repeats
   on two shots in a row.
4. **The lead's identity is a pinned text canon** (framing first; a short "far" variant for full-length shots). Never
   use face images as the identity reference. By default the lead is Claudia: her identity text from the canon in
   every image prompt (the full form close and medium, the short form full length and wider), photographic film
   stills, never illustrated (her avatar tier only for game or simulation worlds), an adult in her late twenties,
   never the word "young", and her never-list (`05-claudia-gallery.md` §3).
5. **Generation inputs stay in colour**; any grade happens in post (a look per clip from sampled frames).
6. **Sung clips** get the plate as `@Image1` and the exact song window as `@Audio1`, and the prompt quotes the exact
   words. Measure the sync; cut at the last eighth note before the mouth diverges; cover from that frame. No lip-sync
   model as a fallback by default: cut away instead.
7. **Screenplay for acting and motion, short for copy.** Motion clips (and the board) are screenplays (timestamps to
   0.01 s on real word and kick times, blocking, action and reaction, camera tied to hits, mouth rules). Sung (lip-sync)
   clips take the short sung form: the head quoting every word, one line of framing and light, at most 2 timed beats
   (a long prompt makes the model re-sing instead of copy; `60-clips.md` §4.0). The lead writes all of them in one
   context, and the owner reads the book before any spend.
8. **Spend gates:** estimate before spending; a clip must be `locked` and confirmed; real spend is read from the
   provider; an owner quality flag stops all spending.
9. **Never alter a declined reference to get past a safety filter. Never type the owner's credentials.** Every
   job is Grok's: Grok Imagine on Grok's own tool, Suno through Suno's own connector, Midjourney in Grok's own
   browser, where the owner signed in once (`slop relay job --kind midjourney|suno|grok-imagine`). The owner decides;
   they never paste, press Create or download.
10. **The master** is tagged BT.709 primaries and matrix with the sRGB transfer (`iec61966-2-1`), as the reference
    videos' encoder tagged it (the frames are sRGB pixels), CRF ≤ 16, verified with ffprobe; at most 3 flashes a
    second.
11. **Licences:** Depth-Anything-V2-**Small** only; OFL fonts only (never Nimbus Sans, Junicode, Pilcrow Rounded or
    Alchimia); the htdemucs weights are flagged; the owner is told about Suno's output-use clause. Songs go out under
    the owner's own artist name, never "anabology", with Claudia's credit and an AI label (`90-master-publish.md` §6).
12. **Privacy:** nothing you publish or share (posts, descriptions, shared docs, public repos) carries the owner's real
    identity (unless they choose to show it), their Midjourney profile code, private hostnames or provider job ids
    (Midjourney images carry their job id in XMP metadata: strip it).

---

## 2. The pipeline map

```
 setup ─► brief + taste ─► CONCEPT (G1) ─► lyrics ─► Suno/Lyria takes ─► SONG BY EAR (G2) ─► ingest + analysis
                                                                                               │ (ear-check)
                        ┌──────────────────────────────────────────────────────────────────────┘
                        ▼
              lead canon + 4 test plates ─► FACE/LEAD (G3) ─► storyboard ─► BOARD (G4) ─► plates (MJ or API)
                                                                                               │
                        ┌──────────────────────────────────────────────────────────────────────┘
                        ▼
              clip prompt book ─► PROMPTS BEFORE SPEND (G5) ─► clips + sync check ─► edit (EDL) ─► motion design
                                                                                               │
                        ┌──────────────────────────────────────────────────────────────────────┘
                        ▼
              lyric gate N/N + flash check + safety/canon scan ─► render v1 ─► V1 (G6) ─► master + vertical + publish
```

| # | Stage | What you do | Main command(s) | Output (project files) | Gate | Doc |
|---|---|---|---|---|---|---|
| 0 | Setup | install, check, ask for secrets on the secure card | `bin/setup.sh`, `slop doctor` | `$SLOP_HOME` | — | README |
| 1 | Brief + taste | interview the owner; run the taste capture (tap app, or pair sheets in the chat) | `slop taste serve --tunnel` or `slop taste sheet` + `slop taste record`, `slop taste tokens`, `slop taste verdict`, `slop taste apply` | `DECISIONS.md`, `taste/taste-tokens.json` | — | 30-taste |
| 2 | Concept | research, pitch three concepts, owner picks one | (research) | `DECISIONS.md` | **G1** | 10-song |
| 3 | Lyrics | write for Suno's delivery; lint the scansion | `slop lyrics lint` | `lyrics/lyrics.txt`, `lyrics/display.txt` | — | 10-song |
| 4 | Song | write the Suno pack (or call Lyria); owner generates and auditions | `slop gen song` (Lyria only) | `suno/` pack, `suno/takes.md` | **G2** | 10-song |
| 5 | Ingest + analysis | stems, alignment, beat map, hits, report; ear-check; confirm the sections and bar lines; a generated song's words | `slop fetch`, `slop song ingest`, `slop analyze`, `slop song sections`, `slop song bars`, `slop lyrics check` | `audio/`, `analysis/*.json`, `analysis/report.md` | — | 20-analysis |
| 6 | Lead + look | canon text, look mode, accent, 4 test plates | (prompt book) | `project.json` lead/look | **G3** | 50-plates-midjourney |
| 7 | Storyboard | set the tier's pace (`board.pace`), then shots on beats, one graphic per line, motion budget | `slop board draft`, `slop board set` / `slop board fill` / `slop board device add`, `slop board audit`, `slop board sheet`, `slop board approve` | `board/shots.json`, `board/board.pdf` | **G4** | 40-storyboard |
| 8 | Plates | prompt book → Grok runs it in Midjourney (or the API batch) → ingest → pick | `slop plates book`, `slop gen image --jobs`, `slop plates ingest`, `slop plates pick`, `slop plates vary`, `slop plates box` | `plates/prompts.md`, `plates/picks.json` | — | 50/51 |
| 9 | Clip prompts | the lead writes every video prompt in one context: the short sung form for sung clips, a screenplay for motion clips | `slop clip new`, `slop clip lock` | `clips/<clip>.json` (status `locked`) | **G5** | 60-clips |
| 10 | Clips | submit, poll, measure lip sync, cover divergences | `slop clip submit --yes`, `slop clip poll`, `slop clip sync`, `slop clip cover` | `clips/<clip>/take-N.mp4` | — | 60/61/62 |
| 11 | Edit | resolve every shot to a source | `slop edit edl`, `slop edit export` | `edit/edl.json`, `engine/` | — | 40/70 |
| 12 | Motion design | type, explaining graphics, chrome, transitions | (engine / delegated chapters) | engine chapter files | — | 70-motion-design |
| 13 | QA + render | lyric gate N/N, contact sheets, safety/canon scan, render v1, the review copy, flash + history check | `slop render lyrics`, `slop render sheet`, `slop review scan-sheets` / `slop review record` / `slop review status`, `slop render frames`, `slop render encode --review`, `slop render check` | `out/review.mp4` (v1, what the owner watches) | **G6** | 80-review-qa |
| 14 | Master + publish | the approved master, vertical cut, chat copy, AI label, posting copy | `slop render encode`, `slop render vertical`, `slop render encode --share`, `slop render clean` | `out/master.mp4`, `out/vertical.mp4`, `out/share.mp4` | — | 90-master-publish |

**Stage order rules**

1. Lock the song (G2) **before** the storyboard. Every shot time is a beat or a word time of one specific take. A new
   take means re-timing, and if the take changes the song's shape (SP's final take moved the first line to 0.2 s and
   removed an instrumental), it means restructuring by hand.
2. The lead (G3) can run in parallel with the song. Do it before any plate batch.
3. The ear-check (20-analysis) happens **before** the storyboard. On EV one word aligned 2.6 s early passed the global
   lyric gate and was caught only when one chapter's own lyric check failed; it is cheap to catch now and expensive
   later.
4. Nothing is generated for money until the owner has read the prompts (G5).
5. The film must render end to end at every stage: plates stand in for missing clips, the default renderer stands in
   for missing chapter code. Never wait for "all assets" before the first render.

### 2.1 Running the stages: `status`, `next` and background jobs

One command tells you where the project is, and a second one runs the next step when nobody needs to decide anything:

1. `slop --project my-song status` lists every stage (done, missing or STALE), the gates, the spend and the **next
   step as a ready-to-run command** (`next.cmd` in `--json`).
2. `slop --project my-song next` runs that command when it is free (no provider spend), is not an owner gate and needs
   no writing or choosing first. Otherwise it prints the command and why it stopped (an owner gate, a creative step,
   a paid step, the sections still guessed). `--steps 3` runs up to three steps in a row; `--dry-run` only says what
   it would run; `--free-only` refuses any paid call inside what it runs.
3. **Long steps run as background jobs** (analysis, engine export, frames, the lyric gate, encodes, checks, sheets,
   downloads), because the bot's shell call times out. For a long step `next.cmd` already IS the job form, e.g.
   `slop --project my-song job start -- analyze`. It prints a job id and its wait command at once.
4. Run the printed wait command, `slop --project my-song job wait ID`. It blocks at most 25 s (`SLOP_WAIT_MAX`), then
   says "still running" (run it again) or prints the step's own result. Never start the same step again while its job
   runs: `slop --project my-song job list --running` shows what is running, `slop --project my-song job status ID` one
   job, `slop --project my-song job stop ID` stops one.
5. `next` does not restart a step whose last job failed, was stopped or changed nothing: read that job first
   (`slop --project my-song job status ID`), fix the cause, then `slop --project my-song next --retry`.

Downloads: an owner's shared link (Google Drive, Dropbox, a plain HTTPS file) is fetched with
`slop --project my-song fetch "LINK" --to audio` (size and sha256 printed; a sign-in or quota web page is refused, not
saved as the file). Spend lock: `SLOP_FREE_ONLY=1` in the environment refuses every paid call, project or not; use
it for a session where nothing may cost money. `slop job selftest` checks once per computer that a job outlives the
shell call that started it.

### 2.2 Before the first project: setup, coding agents, a home GPU

Setup is one checklist, `slop onboard` (full guide: `docs/96-setup-and-hardware.md`). The setup skill runs
`slop --json onboard next` every reply and does what it says: it asks the tier first, then the user's coding-agent
plans and whether they have a home GPU, and walks the toolkit install, the keys (secure secret card only), the
connectors, the music and stills plans, the taste profile and the first project. Each item can be skipped and comes
back when the user says "setup"; `slop onboard status` shows the whole list, what each tier still misses, and what is
unlocked. The checklist never stores a secret.

- **Coding agents on the bot's computer** (`slop agents`): Claude Code, Codex on a ChatGPT plan, Muse Code and
  Gemini CLI are installed under `/workspace/.claudia` (`slop agents install claude`), signed in headless
  (`slop agents login claude`; codes only through the secure secret card), proved with one tiny run
  (`slop agents test claude`) and chosen per role (`slop agents use codex --for director`). Director work then runs on
  the box on the user's own plan, with no approval cards; at most 2 agent jobs run there at once.
- **A home GPU** (`slop gpu`): paired (the box serves GPU jobs through a quick tunnel; the user pastes one line from
  `slop gpu pair` on their PC) or direct (local exec). `slop analyze` and `slop edit export` then use it by themselves
  (`--gpu auto`), else the CPU as before. Measured: stems + alignment of a 5:06 song took 41 s on an RTX 3090 Ti
  against 126 s on 8 CPU threads. It saves minutes, not money.

---

## 3. Tiers: Quick, Studio, Director

The tier is a project setting (`project.json "tier"`). Ask the owner which one in the setup interview; recommend from
the decision rules below.

| | **Quick** | **Studio** | **Director** |
|---|---|---|---|
| Who | anyone with the bot | owner has an OpenRouter key, Higgsfield, and their own Midjourney/Suno | owner also has a Claude, ChatGPT (Codex) or Muse Code plan: the agent runs on the bot's computer (`slop agents`) or on their own machine |
| Song | owner's own Suno upload, or Lyria via OpenRouter (≤ 3 min) | Suno v6 with the full pack, auditioned by ear | Suno, plus a lyric-writing loop with research and scansion scoring |
| Stills | API images (OpenRouter / Higgsfield / the bot's own image tool) | Midjourney via the prompt book (Grok's browser), or API | Midjourney |
| Motion | a few clips on cheap models or 480p drafts, plus 2.5D plates | Seedance 2.5 sung clips with measured lip sync, plus covers | full: sung chains, screenplay motion clips, covers |
| Storyboard | auto-drafted at the Quick pace (set `board.pace` first, 40-storyboard §6.1), light edits; ≈ 14 shots a minute, about one per lyric line (measured: the draft gives 73 shots for the 5:06 reference song) | drafted at the Studio pace, one pass by the bot; ≈ 20 shots a minute (measured: 100 shots for 5:06) | delegated: three director angles + judges + merge, or the lead's board from the owner's walkthrough + a critic; EV's pace, ≈ 27 shots a minute (EV: 141 shots; the draft at this pace: 130 shots for 5:06) |
| Motion design | the data-driven default renderer (lyric modes, chrome, CV marks, readouts) | default renderer + per-shot devices from `shots.json` | bespoke chapter code: animator → art director (renders and reviews) → fixer |
| Reviews | the owner's eye on v1 | one reviewer pass per section | calibrated reviewer panel, safety/canon scan of every take |
| Typical spend | $3–20 | $50–110 | EV-class: OpenRouter ≈ $95–110 + 0–3,300 Higgsfield credits |
| Bot turns | 8–15 | 20–35 | Grok turns only at the gates; the work runs in the delegated session |
| Wall clock | one sitting: ≈ 37–41 min of the bot computer's own work for a 5-minute song (measured, below) plus waiting for generations and the owner (estimate: 2–6 h in all) | 8–16 h over 1–2 days (estimate; the same ≈ 37–41 min of the computer's work) | 19 h (EV) to 41 h (SP), measured |

**What the bot computer itself spends (measured).** The whole 5:06 reference song was rendered on a machine held to
the bot computer's limits (8 CPUs, 15 GiB, no swap). The board had 130 shots on 125 Midjourney-size plates
(2912×1632), with depth maps on and the 64-step 2.5D push on 20 % of the shots. Every step was one `slop` command:

- analysis 2 min 39 s; export with the depth maps 2 min 15 s
- 16:9 frames 13 min 12 s (4 workers, 107 ms a frame); lyric gate 1 min 4 s
- master encode 1 min 19 s; flash and history check 15 s
- 9:16 cut 13 min 47 s for the one command, frames and encode together (the frames alone ≈ 12 min at 99 ms a frame)
- chat copy (`slop render encode --share`, under 190 MiB) 2 min 33 s for the two-pass encode; a current master that
  already fits (79 MB here) is now copied instead, in seconds

That is **≈ 37 minutes in all**, or about 41 with the optional sheets, the layer check, the 9:16 lyric gate and the
9:16 chat copy. Peak memory was **4.3 GiB**, with no out-of-memory
event. These were fast desktop CPU threads, so expect up to about twice as long on slower cloud CPUs (an estimate).
When other jobs shared the CPUs, the 16:9 frames took 19 min. Run renders in the background, and read
`$SLOP_PROGRESS_FILE` for the percent done and the time left of the current step ("step": "1/2"). The command is
over only when its "state" is done, stopped or failed; "stage_done" means one step of several finished, so keep
waiting. `slop job wait` gives the final word. The frames take about 1.8 GB on disk until
`slop render clean`.

**Decision rules for recommending a tier**

1. Only the bot and its built-in tools (no OpenRouter key, no Higgsfield credits) → **Quick** with stills from the
   bot's image tool, 2.5D motion and the owner's own song upload. An OpenRouter key adds Lyria songs and cheap clips.
2. The owner wants their own Midjourney look, or a lead who sings on camera with real lip sync → **Studio** at least.
3. The owner wants EV/SP quality (bespoke graphics for every line, 90–140 shots) **and** has a Claude Max-class plan
   (EV used ≈ 29–30 % of a Max 20x week; SP ≈ 47–51 %) → **Director**. On a smaller plan, Director work spreads over
   several days because of the 5-hour windows; say so.
4. Song length matters: Lyria makes about 2–3 minutes in one take and cannot extend. Anything longer needs Suno.
5. When unsure, start Quick. A Quick project can be promoted: the project folder and every file carry over.

**What changes per stage, by tier**

| Stage | Quick | Studio | Director |
|---|---|---|---|
| Brief + taste | 5 interview questions; taste capture optional (60 taps) | full capture (150 taps + 3 style frames) | full capture + reviewer calibration |
| Concept | the bot pitches 3 concepts from a web search | same, with a short fact bank | research fan-out (topic agents) + verified bank |
| Lyrics | owner's lyrics, or the bot writes and lints them | the bot writes, lints, owner auditions | the lead writes with the owner live, flow-scored and calibrated to the owner's verdicts |
| Song | owner uploads, or Lyria | Suno pack, rounds of takes | Suno pack, voice continuity across sequels, editor fixes with a time map |
| Analysis | same everywhere (CPU): 2 min 39 s for a 5-minute song at the bot computer's limits (measured); a paired home GPU takes the stems and alignment (§2.2) | same | same |
| Lead | canon text, API stills | canon text, 4 Midjourney test plates | canon + far variant + cast bible |
| Board | Quick pace set, auto-draft, audit | Studio pace set, one pass + audit | panel or lead + critic, full audit |
| Clips | ≤ 8 clips, cheap | sung windows + motion clips, covers | full prompt book (one context), covers |
| Motion design | default renderer | default + devices | chapters |
| QA | lyric gate, flash check | + contact sheets | + reviewer panel, safety/canon scan |
| Render | the same engine for every tier: ≈ 13 min for the 16:9 frames of a 5-minute song at EV's pace, ≈ 14 min for the 9:16 cut with its encode (measured, above) | same | same, plus whatever the bespoke chapter code costs (not measured) |

---

## 4. The gates (where the owner must approve)

There are six. Everything else runs without asking. At a gate you show the owner **one artefact**, ask **one question**
with the default answer stated, and record the answer verbatim.

| Gate | When | Show | Ask (template) | Approval means | Record |
|---|---|---|---|---|---|
| **G1 Concept** | after research | 3 concepts, each ≤ 120 words: premise, through-line device, lead, arc, why it suits video models, one risk | "Which one? (Default: A.) Anything you'd change?" | the owner names one | `DECISIONS.md` |
| **G2 Song by ear** | after each round of takes | the round's takes (the owner listens in Suno, not you) | "Which take? Or what's wrong (name the line)?" | the owner names a take and delivers the WAV | `DECISIONS.md`, `suno/takes.md` |
| **G3 Face / lead** | after 4 test plates of the lead | a contact sheet of the 4 plates, numbered | "Is this her/him? Flag any wrong face." | no flags, or "these are good" | `DECISIONS.md`, `project.json` lead |
| **G4 Board** | after `slop board audit` passes | the board sheet from `slop board sheet` (one card per shot: frame, time, lyric, framing, action, motion tier) | "Approve the board? Notes by shot id. I'll proceed in N min unless you say stop." (only if the owner set a window) | "approve", notes, or the window expires | `DECISIONS.md` (notes verbatim); `slop board approve` sets `gates.board_approved` (it re-runs the audit and refuses while any audit gate fails) |
| **G5 Prompts before spend** | before any paid video/image batch | the prompt book `plates/prompts.md` (from `slop plates book`, in every tier: API stills too) + the locked clip prompts + the cost estimate | "These N prompts will cost ≈ $X / Y credits. Go?" | an explicit yes | `slop gate prompts --approve` records what the owner read (needs `plates/prompts.md`). It becomes the standing yes for clip submits (`gates.prompts_approved`) only when it covered at least one locked clip prompt and no clip was still a draft; a plate-book-only approval leaves every clip submit needing `--yes`. A clip locked or rewritten after the approval needs the owner again (`slop status` shows the gate STALE); `ledger.jsonl` |
| **G6 v1** | after the first full render | `out/review.mp4` from `slop render encode --review` (or a 20–40 s excerpt first, see below) | "Accept v1, or what's wrong?" | "accept" / "perfect" | `slop gate v1 --approve` sets `gates.v1_approved` (needs `out/review.mp4`; `slop status` also wants the lyric gate N/N, `slop render lyrics`, newer than the engine data); `DECISIONS.md` |

**Gate rules (never break these)**

1. **Spend is never approved by silence.** G5 and any paid action need an explicit yes in this project. A "silence =
   approval" window is allowed only for G4 and only if the owner set it themselves (EV: "just wait like 5 mins once you
   send it and if I don't respond take it as approval"). Record the window in `DECISIONS.md` the first time it is set.
2. **An owner quality flag stops all spending immediately.** If the owner says anything like "these are bad",
   "you're wasting money", stop every running job that can spend before you reply. On SP a background workflow kept
   spending after the owner flagged the prompts; ≈ 830 credits were burned on prompts nobody had read.
3. **Ask once, with a default.** One message per gate. Never ask the same gate twice in a row; if the owner doesn't
   answer a non-spend gate, wait. If they don't answer a spend gate, do not spend.
4. **Record the owner's words verbatim** in `DECISIONS.md`, dated: `slop decide "<the owner's words>" --by owner`.
   A later decision that replaces one gets `--supersedes "<date or words of the old one>"` instead of editing it (EV
   lesson: decisions made after a stage started were appended as dated blocks, never by re-running finished work).
   Gates are set only after the owner's yes, and each command checks that the thing the owner approved exists:

   | Gate | Command | Refuses unless |
   |---|---|---|
   | G4 | `slop board approve` (then `slop decide` with the owner's words) | every `slop board audit` gate passes (it re-runs the audit itself) |
   | G5 | `slop gate prompts --approve --note "<owner's words>"` | `plates/prompts.md` exists (`slop plates book`) |
   | G6 | `slop gate v1 --approve --note "<owner's words>"` | `out/review.mp4` exists (`slop render frames`, then `slop render encode --review`) |

   `slop gate` alone shows all gates; `slop gate <name>` says whether it is ready and, if not, what is missing. G1–G3
   have no gate key: record them with `slop decide`. `--force` records an approval whose precondition fails; use it
   only when the owner explicitly says so (it is logged).
5. **Catch global errors early.** Before the full v1, show a 20–40 s excerpt of the first finished section. EV's v1 was
   rejected as "way too.. gray … loses the Midjourney magic" after the whole film was built; a 30-second excerpt
   could have caught it about 13 hours earlier.
6. **Fix the source, never the frame.** When the owner flags a picture, fix the prompt or the plate (image-edit
   model) and re-make, never paint over the output (SP: "it should have been in the midjourney prompt from the start
   or with the edit model").
7. **Never alter a declined reference to pass a provider filter.** A decline is free, and final for that image on that
   service. Trying another provider with the same unaltered image is allowed (62-moderation).

**What to ping the owner for between gates**: a paid service failing, a human handoff (captcha, login, download), or a
decision that is theirs (taste, money, likeness of real people). Nothing else. EV's owner: "only time to ping me is if
higgsfield fails."

---

## 5. Budgets

### 5.1 Per tier

| | Quick | Studio | Director (EV-class) |
|---|---|---|---|
| Video generation | $3–20 (4–8 cheap or 480p clips, 24–60 s on screen) | OpenRouter $50–100, Higgsfield 400–1,500 credits (12–25 clips incl. lip-sync windows) | OpenRouter $95–110 (EV $93.15; SP ≈ $102–107) + Higgsfield 0 (EV) to ≈ 3,250 credits (SP) |
| Image edits / API stills | cents to a few dollars | ≈ $0.14 per image edit | SP: 16 edits, $2.22 |
| Song | Lyria ≈ $0.08 per song (verify the OpenRouter charge after the first call) | Suno Pro $10/mo (20 downloads) | Suno Premier $30/mo (60 downloads, Studio exports exempt) |
| Midjourney | not used | owner's plan | owner's plan (Pro recommended for Stealth) |
| Claude (Director only) | — | — | $626 (EV) – $1,007 (SP) API-equivalent; Max 20x: 29–47 % of a week |
| Bot turns | 8–15 | 20–35 | 50–90 if driven turn by turn (too many: run the work delegated) |

### 5.2 Unit prices to estimate with

| Item | Price |
|---|---|
| Seedance 2.5 on OpenRouter, 720p | $0.231 per second (4 s $0.92, 5 s $1.16, 8 s $1.85, 12 s $2.77) |
| Seedance 2.5 on OpenRouter, 480p | $0.103 per second |
| Seedance 2.5 on Higgsfield | 3 / 7 / 12 credits per second at 480p / 720p / 1080p |
| Higgsfield credit | $0.033 (annual top plan) to $0.059 (small top-up) |
| Image edit (Gemini 3 Pro Image via OpenRouter) | ≈ $0.14 |
| Whisper word timestamps via OpenRouter | ≈ $0.0000075 per audio second (a whole song ≈ $0.002) |
| Lyria 3.5 (Gemini API) / Lyria 3 Pro (OpenRouter) | $0.08 per song (OpenRouter lists 0; check real spend) |

### 5.3 Budget rules

1. **Plan for twice what the board uses.** Generated seconds ran ≈ 1.9× (EV) and 2.0× (SP) the seconds that ended up
   in the cut: retakes, covers and declines.
2. **Estimate before every batch and put it in the G5 message.** Estimate = Σ planned clip seconds × price × 2.
3. **Quote real spend only from the provider**: OpenRouter `/api/v1/credits` and `/api/v1/key` (`slop spend`),
   Higgsfield `balance` and `transactions`. The local `ledger.jsonl` is an estimate (EV's ledger said $97.28, the bill
   was $93.15). Provider declines are free and must not count against the cap.
4. **The OpenRouter key has its own limit**, separate from the account balance. SP hit 403s at the key's $250 limit with
   money still in the account. Set the key limit above the project cap.
5. **Owner target and cap.** Ask for both ("try to hit $70ish but if you use up to $150 i wont be mad"). Leftover
   budget at the end goes to replacing the most repetitive stills with motion.
6. **Higgsfield subscription credits do not roll over** and top-up credits expire after 90 days. A reset deadline must
   never push you into spending on prompts the owner has not read (that is exactly how SP's burn happened).
7. `project.json "budget"` holds the caps (`openrouter_usd`, `higgsfield_credits`, `confirm_over_usd`). Any single
   action over `confirm_over_usd` needs its own yes even after G5.

---

## 6. How the bot keeps Grok usage low

Grok Bot usage is a weekly pool. Measured upper bound on one Pro+ account: **≈ 1.5 % of the week per user turn**; a live
Quick run inside a Grok Bot measured **≈ 0.25 % a reply** (the whole video, install and skill import included, ≈ 3 %,
13 user turns, the owner granting autonomy to v1 at the board). Every turn re-reads the whole conversation, so cost
grows roughly with the square of the conversation length: 50 turns in one conversation re-read ≈ 3.5× more than 5
conversations of 10 turns (*estimate*). An EV-class project driven turn by turn would use more than a whole Pro+ week.
So:

1. **One `slop` command does many steps.** Run `slop analyze` once, not stems, then alignment, then beats in separate
   turns. Parse the `--json` result; reply with the one-line `text` field, not the log.
2. **Few, fat turns.** Batch everything you need from the owner into one message per gate. Combine gates that are ready
   together (the face sheet and the song round can go in one message).
3. **One phase per conversation.** State lives in the project files (`project.json`, `DECISIONS.md`, `RUNS.md`,
   `ledger.jsonl`), not in the chat. At the start of a new conversation, run `slop --project <name> status` (stages
   present, gates, spend, the next suggested step) and `slop --project <name> decide --list --last 20`, then continue.
   Record every long job's id with `slop runs add <id> --what "…" --resume "…"` so an interrupted session can resume.
4. **Never poll with turns or routines.** Long jobs run in the background and write status files; check them when the
   owner next speaks, or hand the wait to a delegated session. Routines are for the weekly idea drop, not for polling.
5. **Send pictures, not paragraphs.** A contact sheet image of 40 plates is one file; describing them is thousands of
   tokens.
6. **Don't paste big files into chat.** Point to the path. Don't read whole JSON files into context; use `slop … --json`
   summaries or `jq` for the field you need.
7. **Director tier: the bot is the gatekeeper, not the worker.** Lyrics loops, storyboard panels, chapter animation and
   reviews run in the owner's own Claude Code / Codex session through the delegation runner (95-delegation). The bot
   starts the job, the job writes to the project folder, and the bot only speaks at gates.
8. **Approval windows save turns.** If the owner sets "silence = approval" for the board, you don't need a second turn
   to hear "ok".

---

## 7. Where the state lives

A project is one folder (under `$SLOP_PROJECTS`, made by `slop new <name> --tier <tier>`). The full layout:

```
<project>/
  project.json              # name, tier, lead canon, look, models, budget, gates, audio/board overrides
  DECISIONS.md              # dated decisions, the owner's words verbatim; "UPDATE … supersedes" blocks
  RUNS.md                   # ids of long or background jobs, for resume
  ledger.jsonl              # every paid call: {ts, provider, model, kind, units, est_usd, real_usd?, request_id, status}
  suno/                     # the Suno pack: style.txt, exclude.txt, lyrics-field.txt, title.txt, settings.md,
                            #   takes.md (verdict per take), flow-calibration.txt, lyria-prompt.txt (10-song)
  audio/song.wav            # 44.1 kHz stereo master, as delivered
  audio/stems/{vocals,drums,bass,other}.wav
  audio/windows/<name>.mp3  # clip reference windows (clean vocal or mix) and ear-check windows
  lyrics/lyrics.txt         # sung words, one line per lyric line, numbers and symbols SPELLED AS SUNG; [tags] on own lines
  lyrics/display.txt        # what the viewer reads; "TEXT|n" = a token spanning n sung words (e.g. "+25%|3")
  lyrics/adlibs.json        # optional: sung words that are not on the sheet, timed by hand (20-analysis §7.3)
  analysis/beats.json       # variable-tempo beats, downbeats, sections
  analysis/words.json       # word times (forced alignment + fixes)
  analysis/hits.json        # kicks, snares, hats, impacts, risers, fills, vocal entries
  analysis/lyrics-display.json  # timed display tokens (`slop lyrics display`)
  analysis/report.md        # human summary + the EAR CHECK list
  taste/                    # taste-tokens.json, look-bible.md, verdicts.jsonl, taps.jsonl, fonts/
  board/shots.json          # the storyboard: the source of truth for the edit
  board/board.pdf, board-pNN.jpg  # the sheet the owner approves (G4)
  board/audit.json          # audit results
  board/TREATMENT.md        # optional: treatment, through-line, chapter map (40-storyboard §2)
  plates/prompts.md         # the prompt book the owner reads (G5)
  plates/cands/<plate>/<k>.jpg ; plates/picks.json
  clips/<clip>.json         # one file per clip: request, takes, sync
  clips/<clip>/take-N.mp4
  edit/edl.json             # which source plays in every shot
  edit/timemap.json         # optional: final-song time → board time after an editor fix (10-song §7)
  engine/                   # per-project engine data written by `slop edit export`
  render/frames/            # rendered frames
  out/review.mp4            # the v1 the owner watches (G6)
  out/master.mp4 ; out/vertical.mp4
```

Outside the projects, per user, in `$SLOP_HOME` (`/workspace/.claudia` on the bot's computer, so a computer update
keeps it): `onboard.json` (the setup checklist's marks and settings, the agent choices; never a secret), `agents/`
(sign-in sessions, install logs, the box's agent job slots), the agent commands (`bin/`, `npm/`, `muse/`,
`claude/versions/`), `gpu/` (the GPU job queue and the pairing, kept only as hashes) and the user's taste profile (`taste/`).

The files each stage reads and writes:

| File | Written by | Read by |
|---|---|---|
| `project.json` | setup, every gate | everything |
| `DECISIONS.md` | every gate (verbatim owner words, dated) | every stage; every delegated brief |
| `taste/taste-tokens.json` | taste capture | look, prompts, motion design, reviewers |
| `lyrics/lyrics.txt` (as sung) | lyrics stage | alignment, scansion lint |
| `lyrics/display.txt` (as read) | lyrics stage, after analysis | engine lyric export, lyric gate |
| `audio/song.wav`, `audio/stems/` | `slop song ingest`, `slop analyze` | everything timed |
| `analysis/beats.json`, `words.json`, `hits.json`, `report.md` | `slop analyze` | storyboard, clips, edit, engine |
| `board/shots.json` | storyboard | plates, clips, edit, engine, audits |
| `plates/prompts.md`, `plates/picks.json` | plates stage | clips, edit |
| `clips/<clip>.json` | clip stage | sync, edit |
| `edit/edl.json` | `slop edit edl` | engine |
| `ledger.jsonl` | every paid call | `slop spend`, budget checks |
| `RUNS.md` | every background/delegated job | resume after an interruption |
| `suno/` | the song stage (the pack, the take log) | the owner (pastes into Suno), the next round |
| `out/review.mp4` | `slop render encode --review` | the owner at G6 (`slop gate v1` needs it) |

---

## 8. The two reference videos in numbers

| | EV | SP |
|---|---|---|
| Song | Suno v6, 5:06.4, 131.5 → 133.9 BPM | Suno v6 with a Voice made from EV, 3:11.6, 129.2 → 132.1 BPM |
| Lyric | 65 lines, 417 display tokens | 51 lines + 2 ad-libs, 315 sung words |
| Shots | 141 (mean 2.17 s, median 1.83 s ≈ one bar) | 94 (mean ≈ 2.0 s) |
| Lead on screen | 83 % (target ≥ 70 %) | 60 % (a second character shares the screen) |
| Stills | Midjourney: 188 prompts, 636 images, 130 plates | Midjourney: 161 prompts, 644 images, 116 plates + 16 image edits |
| Motion | Seedance: 47 clips + 30 covers, 421 s generated, $93 | Seedance: 101 clips, 189 takes, ≈ $107 + ≈ 3,250 Higgsfield credits |
| Lip sync | ≈ 86 % of sung seconds verified | 16 windows verified by audio, 7 by eye; no lip-sync models |
| Owner messages | ≈ 50 | 68 |
| Wall clock | ≈ 19 h | ≈ 41 h (two long owner absences) |
| Owner's verdict | v1 "way too.. gray"; v2 "this is so great" | v1 "its perfect. change nothing." |

---

## 9. Common mistakes (pipeline level)

| Mistake | What it cost | Do instead |
|---|---|---|
| Starting the board before the song is locked | a full re-time (SP changed takes twice during boarding) | G2 first; board second |
| Trusting the lyric gate as proof of alignment | a word 2.6 s early passed the global gate; only one chapter's own check caught it | the ear-check in 20-analysis |
| Drafting a Quick or Studio board at EV's (Director) pace | 80+ shots and plates for a 3-minute song | check the tier and its `board.pace` first (40-storyboard §6.1) |
| Agents writing video prompts in parallel | ≈ 830 Higgsfield credits burned on "poses, not drama" | one lead writes every prompt in one context; owner reads before spend |
| Applying a taste statistic to the footage (mono grade) | EV v1 rejected as too grey, 3.5 h colour rework | footage keeps the generator's colour unless the owner asks; test on 3 style frames |
| Same image on several shots / two clips from one frame | the owner caught it on the board | one image per shot; distinct start frames |
| A silent default project | tools ran on the wrong project | always `--project NAME` |
| Reading "empty review" as "no fixes" | a usage limit looked like success | a null review is a failure |
| Polling in bot turns | burns the weekly pool | background jobs + status files |
| Asking for a key or a sign-in code in chat | a leaked secret the owner must revoke | the masked secure secret card only (96-setup-and-hardware §3) |
| Pinging the owner for every step | attention wasted | gates only |
| Writing the owner's taboo words | a public embarrassment | keep a taboo list in `DECISIONS.md` and lint every artefact against it |

---

## 10. Glossary

- **Plate**: a still image used as a shot's base (animated in 2.5D) or as a video clip's start frame / reference.
- **2.5D**: a still split into depth layers (depth map) and moved in code: parallax, rack focus, type between layers.
- **Sung clip / window**: a video clip whose audio reference is the exact song window the character sings, so the mouth
  matches the song.
- **Cover**: a continuation clip that starts in the word gap before a lip-sync divergence and covers the rest.
- **Beat map**: the list of every beat time of this take (variable tempo). Never a single BPM.
- **Display token**: what the viewer reads for one or more sung words (`+25%|3` reads "+25%" for the three sung words
  "plus twenty-five").
- **Through-line device**: a piece of always-on chrome that changes with the story (countdown, counter, load readout).
- **Explaining graphic**: the one-glance motion graphic that shows what a lyric line means.
- **Gate**: a point where the owner must approve (§4).

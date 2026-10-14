# Claudia

**Claudia content, sized to the ask.** Claudia is an open toolkit plus a Grok Bot template for making work with
Claudia, the AI popstar and open character: a still, a clip, a song, a music video or a post. Claudia is the lead by
default; a new character only when you ask. The biggest ask walks anyone from a song (their own Suno track, or one
generated on the spot) to a beat-locked, every-word-on-screen lyric video with storyboarded shots, generated stills and
clips, measured lip sync, explaining motion graphics and a broadcast-correct master. The quality bar is anabology's
Claudia films (*Escape Velocity*, *Clodyssey*, *Bliss*, *Airplane Mode*); the pipeline, thresholds and lessons here
are the ones those videos were made with, generalised for any song and any user.

**claudia.gallery is the #1 source of truth** (her canon, the films' records, the wiki), and wins over any doc here:
connect its MCP server first (`docs/05-claudia-gallery.md`).

How the Grok Bot works (three parts, one job each):

| Part | Its job |
|---|---|
| **Grok** (the bot) | sign-ins and delegation only: it passes your words to Opus word for word, shows you what Opus posts, and runs Grok Imagine on grok.com in its own signed-in browser when Opus asks (your X plan, $0). It writes no prompts and makes no taste calls. |
| **Opus** (Claude Code on the bot's computer, on your Claude plan; Codex if you only have ChatGPT) | the production: ideas, lyrics, the board, every prompt, picks, the edit and the render, with this toolkit and the claudia.gallery MCP. It asks you at most six questions on a film and spends nothing without your yes (`docs/96-relay.md`). |
| **claudia.gallery** (MCP, public, read-only) | who Claudia is and how her four films were made: the canon, the wiki, 1,927 real prompts. |

The toolkit is a single command-line program, `slop`, driven by Opus (or by you). It keeps all state in plain files
inside a project folder, so work survives restarts, can be resumed by run id, and can be handed to another agent.

| Scale (claudia.gallery's) | You need | Typical video spend |
|---|---|---|
| **Quick** | Claude (or ChatGPT) and X for Grok Imagine; your own song or a generated one | $0-20 |
| **Studio** | + an OpenRouter key or Higgsfield credits (sung clips with measured lip sync), your own Suno and Midjourney (you press Create and paste; Opus writes the fields) | $50-110 |
| **Full** | + a plan that runs multi-agent workflows for a day or two | $90-350 (the films, measured) |

Rules the code enforces: every sung word on screen at its aligned time; cuts on the variable beat map; estimate
before any paid call and confirm above the project threshold; real spend read from the provider; a declined
reference is never altered to get past a safety filter; every browser task (Midjourney, Suno, Grok Imagine) is
Grok's, in its own browser where you signed in once, and you only make the decisions; OFL fonts and Apache/MIT models
only (Depth-Anything-V2-**Small**, never Large).

## Install

The supported installer is `bin/setup.sh`. It never uses apt or sudo and installs everything under `$SLOP_HOME`:
`/workspace/.claudia` on the Grok Bot computer (only `/workspace` survives computer updates), `~/.claudia`
elsewhere (a headless-browser launch at render time may still write a font cache under `~/.cache`). It is idempotent: run it again after any computer update and it only fetches what is missing.

Repository: https://github.com/anabologyco-maker/claudia-bot

On the Grok Bot computer, one line installs the minimal profile:

```bash
git clone https://github.com/anabologyco-maker/claudia-bot /workspace/claudia && bash /workspace/claudia/bin/setup.sh --minimal
```

Then, step by step:

```bash
. /workspace/.claudia/env.sh                      # or call /workspace/.claudia/bin/slop directly
slop doctor                                        # is everything ready? (free checks only)
bash /workspace/claudia/bin/setup.sh --full       # later, for local analysis: CPU torch 2.11, demucs, wav2vec2
                                                   # alignment, librosa, lyric-lint data (several minutes)
```

Off the bot computer, clone anywhere (for example `~/claudia`) and run `bash bin/setup.sh` from the clone.

Run the scripts with `bash bin/setup.sh` and `sh bin/slop` (a fresh clone may not keep their executable bit).
setup.sh needs bash 4.4+ (Linux; macOS users install a newer bash first). Use the git checkout: a plain
`pip install .` does not ship `templates/` and `engine/`, so `slop new` and renders need the clone (setup.sh
installs it editable).

`bash bin/setup.sh --check` reports what is missing without installing anything (`--json` for the bot).
What it installs: uv (checksum-verified), a uv-managed Python 3.13, the venv with pinned packages (torch pinned on
every line, CPU wheels from the PyTorch CPU index), Playwright chromium (falls back to the system google-chrome if
the browser CDN is blocked; recorded in `env.sh` as `SLOP_BROWSER` and `SLOP_BROWSER_CHANNEL=chrome`), and the
cloudflared binary (checksum-verified) for the phone tap app. `--full` also fetches the CMU Pronouncing Dictionary
(raw data, BSD-2-Clause) and wordfreq for the lyric lint.

**Secrets** are environment variables only. In Grok Bot, the bot asks for `OPENROUTER_API_KEY` with its masked
secure secret card; never paste keys in chat or into files. Optional: `HIGGSFIELD_API_KEY` (normally the bot's
Higgsfield connector is used instead), `ARENA_TOKEN` (Are.na taste import). Coding-agent sign-in codes and tokens
(`CLAUDE_LOGIN_CODE`, `CLAUDE_CODE_OAUTH_TOKEN`, `GEMINI_LOGIN_CODE`, `GEMINI_API_KEY`) go through the same card
(`docs/96-setup-and-hardware.md` §3).

## Hedra video generation (MCP)

Use `--provider hedra` for Seedance 2.5 sung or motion clips through the
[Hedra MCP connector](https://hedra.com/mcp), connected in Grok. No Hedra API key is needed.
The production posts a `relay job --kind hedra --what quote --clip CLIP`, gets the owner's approval,
then reserves the quote and posts a `--what generate` job. Grok uploads, estimates, generates and polls;
completion ingests the video and wakes production. Separate `budget.hedra_usd` and
`budget.hedra_credits` caps preserve the quoted unit. See
[Hedra setup, commands and Grok Bot smoke test](docs/63-hedra.md).
Image/song generation and existing provider defaults are unchanged. Live generation and lip-sync
quality still need the documented smoke test.

## Quickstart (Quick tier)

Put the project on **every** command line (`--project NAME` or `SLOP_PROJECT=NAME`); there is no default project.
`slop projects` lists the existing ones (a fresh session starts there).

```bash
slop new my-song --title "My Song" --tier quick
slop --project my-song status          # stages done/missing/stale and the exact next command - run it any time
slop --project my-song next            # runs that next command when it is free and needs nobody (else prints it)
```

Long steps (analysis, export, frames, encodes) run as background jobs so no shell call times out: `next` starts them
that way, or run `slop --project my-song job start -- analyze` yourself, then repeat the printed
`slop --project my-song job wait ID` until it reports the result.

0. **Brief** - record the owner's ask verbatim: `slop --project my-song brief "<their words>"` (it goes under "The
   owner's ask" in `BRIEF.md`; add references and taboos to the other sections of that file).
1. **Song** - the owner's file becomes `audio/song.wav` (`slop --project my-song fetch "SHARE-LINK" --to audio` for a
   Drive/Dropbox link, then `slop --project my-song song ingest FILE`), or generate one (Lyria via OpenRouter, up to
   ~3 min).
2. **Lyrics** - `lyrics/lyrics.txt` as SUNG (numbers spelled out), checked with `slop --project my-song lyrics lint`;
   after the analysis, `lyrics/display.txt` as it should READ (`+25%|4`). The format is in the project's
   `lyrics/README.md`; lines starting with `[` are section tags or notes and are ignored.
3. **Analysis** - `slop --project my-song analyze`, then read `analysis/report.md`, check flagged gaps by ear and
   confirm the sections (`slop --project my-song song sections`). For a generated song,
   `slop --project my-song lyrics check` shows where the take sings other words than the sheet.
4. **Lead** - Claudia by default: her identity text from the canon (`bible/LEAD.md`, `docs/05-claudia-gallery.md`),
   photographic, never illustrated; after her 4 test plates pass,
   `slop --project my-song lead --canon "..." --far "..."`. A new character only when the owner asks for one.
5. **Storyboard** - `slop --project my-song board draft`, then write every shot's TODOs with `board set`, `board fill`
   and `board device add` (validated against the engine), until `slop --project my-song board audit` passes; send
   the contact sheet; after the owner's yes: `slop --project my-song gate board --approve`.
6. **Stills and a few clips** - the owner reads the prompt book, and later the locked clip prompts, before anything
   is generated (`gate prompts --approve` each time); every paid call is estimated, ledgered, and needs `--yes`
   above `budget.confirm_over_usd`. API stills run as one batch: `slop --project my-song gen image --jobs` (a dry
   run with the estimate), then the same command with `--yes`.
7. **Edit and render** - edit list, engine export, lyric gate N/N, frames, review encode; after the owner approves v1
   (`gate v1 --approve`), the master, the flash check (`render check`), the safety and canon scan
   (`review scan-sheets`, `review record`, `review status`), the vertical cut and the chat copy
   (`render encode --share`). Label it as AI-generated when you post it, name the tools, and credit her: "Claudia is
   an open character by anabology (claudia.gallery)" (`docs/90-master-publish.md` §5–6).

A gate approval records what the owner saw. If the board, the prompt book, a clip prompt or the review copy changes
afterwards, `slop status` shows the gate as STALE until the owner approves again.

Record the owner's decisions as they happen (`slop decide "..."`) and every long job's run id (`slop runs add ...`).
Check money with `slop spend` (ledger estimate plus the real OpenRouter usage, limit and balance).

## Setup: the onboarding checklist, coding agents, a home GPU

One checklist covers everything a user can set up, and always knows the next step for their tier:

```bash
slop onboard next                       # the ONE next step (a command, or a question with one command per answer)
slop onboard status                     # every item: done / todo / skipped, what each tier still misses, what is unlocked
```

- **Coding agents on the bot's computer:** `slop agents install claude` (or codex, muse, gemini; under `$SLOP_HOME`,
  so a computer update keeps them), `slop agents login claude` (headless: a link for the user; codes come back only
  through the secure secret card), `slop agents test claude`, `slop agents status --limits` (plan usage, no tokens
  spent) and `slop agents use codex --for director`. Codex on a ChatGPT plan can also make stills
  (`gen image --provider codex`, experimental).
- **A home GPU:** `slop gpu serve` and `slop gpu pair` print one line the user pastes on their NVIDIA PC or Apple
  Silicon Mac; then `slop analyze` and `slop edit export` use it by themselves (`--gpu auto|off|require`). Stems and
  alignment of a 5-minute song: 41 s on an RTX 3090 Ti against 126 s on 8 CPU threads. Without a GPU everything runs
  on the CPU as before.

The full guide is `docs/96-setup-and-hardware.md`; the GPU operator guide is `slop/gpu/README.md`, the agent runner's
is `runner/README.md`. The checklist never stores a secret.

## Command index

Every command accepts `--json` (one JSON object on stdout with `"ok"`; exit code is non-zero on failure; a usage
error with `--json` also prints `{"ok": false, "error", "usage"}`) and `--project NAME` (`-p NAME`). They work before
or after the command name; the documented form is `slop --json --project NAME <command> ...`.
`slop <command> --help` shows the options. The module tables below are generated from the real `--help` tree (the
`--json`/`--project` flags are left out of each line).

### Core

| Command | What it does |
|---|---|
| `slop new NAME [--title T] [--tier quick\|studio\|director]` | create a project from `templates/project` (re-running only restores missing files) |
| `slop status` | stages done/missing/stale, gates (and what each approval covered), ledger spend, and the next step as a ready-to-run command |
| `slop brief [TEXT] [--file F] [--date YYYY-MM-DD]` | record the owner's ask, verbatim and dated, under "The owner's ask" in `BRIEF.md` (no TEXT: print it); the same words are never added twice |
| `slop projects [--root DIR]` | every project with its tier and next stage |
| `slop lead [--canon T] [--far T] [--possessive T] [--noun T] [--pronoun P] [--none]` | show or set the lead's identity text in `project.json` (`--none`: the owner decided there is no lead); changes are logged in DECISIONS.md |
| `slop project set KEY VALUE [--note T] [--by WHO] [--owner-ok]` / `slop project show [KEY]` | set one dotted `project.json` key (look.accent, look.mode, tier, models.image, budget.*, ...), validated and logged in DECISIONS.md; raising or removing a money guard needs the owner's yes (`--owner-ok --by owner`); `show` prints project.json or one key |
| `slop doctor [--quick] [--offline] [--net] [--profile minimal\|full]` | python, packages, ffmpeg + libx264, headless browser, cloudflared, OpenRouter key validity/limit (free endpoint), disk, RAM, CPU; `--net` probes the hosts setup needs |
| `slop spend [--offline]` / `spend --freeze REASON` / `spend --unfreeze` | ledger estimate by provider vs budget caps, plus REAL OpenRouter key usage/limit/remaining and account balance (`"ok": false` when the key is set but real spend could not be read); `--freeze` records the owner's quality flag: no paid call until `--unfreeze` |
| `slop gate [NAME] [--approve\|--revoke] [--note T] [--force]` | show or set the owner gates `board`, `prompts`, `v1`; records what was approved, logs changes in DECISIONS.md |
| `slop decide TEXT [--supersedes REF] [--by WHO]` / `decide --list` | dated, append-only decision log (`DECISIONS.md`) |
| `slop runs add ID [--kind --what --status --resume]` / `slop runs list [--latest]` | run ids of long or delegated jobs for resume (`RUNS.md`); background `slop job` runs keep their own records (`slop job list`) |

<!-- BEGIN MODULE COMMANDS (generated from the real `slop ... --help` tree by tests/gen_cmdref.py; run it after changing a parser) -->

### Next step, background jobs and downloads

| Command | What it does |
|---|---|
| `slop next [--steps STEPS] [--free-only] [--fg] [--retry] [--dry-run]` | run the next step when it is free and needs no owner/creative input (else print it) |
| `slop job start [--wait S] [--again] [--free-only] -- COMMAND …` | run `slop <command>` detached; prints the job id at once |
| `slop job wait ID [--max S]` | wait up to --max seconds for a job, then report it |
| `slop job status ID` | a job's state, progress and result (no waiting) |
| `slop job list [--all] [--running] [--last LAST]` | this project's jobs (all job folders with --all) |
| `slop job stop ID [--grace GRACE]` | stop a running job (its whole process group) |
| `slop job log ID [--lines LINES]` | the tail of a job's log |
| `slop job selftest [--start] [--check ID]` | check that a job outlives the shell call that started it (~5 s); on a new computer use the two-call test: --start, then --check ID in the next call and after the turn |
| `slop fetch URL --to DIR [--name NAME] [--sha256 SHA256] [--force] [--max-mb MAX_MB] [--timeout TIMEOUT]` | download a shared file (Google Drive, Dropbox, HTTPS) with size + sha256 |

### Song, lyrics and analysis

| Command | What it does |
|---|---|
| `slop song ingest FILE [--force]` | copy/convert a song to audio/song.wav (44.1 kHz stereo) + loudness stats |
| `slop song sections [--set SPEC] [--clear]` | show / set the song's sections (names + starts); guesses are marked |
| `slop song bars [--phase N] [--method kick\|harmony\|auto]` | show / set where the bar lines fall (the downbeat phase; bars count from 0) |
| `slop analyze [--steps STEPS] [--whisper-fallback] [--no-whisper] [--whisper-model WHISPER_MODEL] [--stems-dir STEMS_DIR] [--allow-digits] [--force] [--yes] [--gpu auto\|off\|require]` | stems, word alignment, beat map, hits, sections + ear-check report |
| `slop lyrics lint [FILE] [--line LINE] [--mode spoken\|sung\|chant] [--bars BARS] [--section SECTION] [--bpm BPM] [--grid] [--ban BAN] [--write-fixed]` | scansion report + Suno lint + fixes for a lyrics file |
| `slop lyrics check [--yes] [--whisper-model WHISPER_MODEL] [--write] [--apply] [--apply-lines N,M]` | what the take sings vs lyrics.txt, per line, with fixes (Whisper, ~$0.002) |
| `slop lyrics display [--init] [--force]` | build/validate on-screen tokens (lyrics/display.txt, "TEXT\|n") |
| `slop lyrics fix [--word WORD] [--line LINE] [--t0 T0] [--t1 T1] [--shift SHIFT] [--note NOTE]` | fix word timing by hand (kept by later analyze runs) |
| `slop audio window CLIP --t0 T0 --t1 T1 [--mode clean\|mix] [--words WORDS] [--tokens I,J,K-L] [--listen]` | cut a clip's reference audio: clean vocal (only its words) or the mix |

### Generation, clips and lip sync

| Command | What it does |
|---|---|
| `slop gen models [--kind image\|video\|vlm\|text] [--res RES] [--duration DURATION] [--quality QUALITY] [--limit LIMIT] [--refresh] [--no-free]` | OpenRouter models cheapest-first with per-call estimates |
| `slop gen estimate --model MODEL [--kind video\|image\|edit] [--duration DURATION] [--res RES] [--quality QUALITY] [--n N] [--refs REFS] [--no-audio] [--video-input-s VIDEO_INPUT_S]` | price of one call for a model |
| `slop gen image [PROMPT] [--prompt-file PROMPT_FILE] [--jobs JOBS] [--only ONLY] [--missing] [--workers WORKERS] [--model MODEL] [--aspect-ratio ASPECT_RATIO] [--res RES] [--quality QUALITY] [--n N] [--ref REF] [--seed SEED] [--plate PLATE] [--out OUT] [--yes] [--provider openrouter\|codex]` | generate image(s) via OpenRouter (spends; needs --yes over confirm_over_usd); --jobs runs the plates/jobs.json batch (dry run without --yes) |
| `slop gen edit SRC OUT [INSTRUCTION] [--change CHANGE] [--keep KEEP] [--ref REF] [--medium photo\|illustration\|cel] [--model MODEL] [--yes]` | fix a plate with the edit model: "Change only X … Keep Y" + the keep-everything clause |
| `slop gen song [--prompt PROMPT] [--prompt-file PROMPT_FILE] [--clip] [--model MODEL] [--seed SEED] [--as-song] [--yes]` | generate a song with Lyria via OpenRouter (~$0.08; --clip 30 s ~$0.04) |
| `slop gen host CLIP [--url URL] [--media-id MEDIA_ID] [--role audio\|start] [--tunnel] [--no-verify] [--data-uri] [--experimental]` | give a clip's window (or start image) an HTTPS URL for OpenRouter / Higgsfield media_import_url, or record a media_id |
| `slop gen tunnel start\|stop\|status [--no-verify] [--verify]` | Cloudflare quick tunnel for HTTPS hosting (start\|stop\|status) |
| `slop clip new SHOT --kind sung\|motion [--id ID] [--t0 T0] [--t1 T1] [--song-t0 SONG_T0] [--duration DURATION] [--start START] [--reuse-start] [--frame ref\|first] [--style screenplay\|short] [--window clean\|vocal\|mix] [--provider openrouter\|higgsfield\|hedra] [--model MODEL] [--aspect-ratio 16:9\|9:16\|1:1\|4:3\|3:4\|21:9\|adaptive] [--res 480p\|720p\|1080p] [--force] [--words WORDS]` | draft clips/<id>.json for a storyboard shot (window, exact words, prompt scaffold) |
| `slop clip set CLIP [--prompt PROMPT] [--prompt-file PROMPT_FILE] [--requote] [--words WORDS] [--duration DURATION] [--song-t0 SONG_T0] [--t0 T0] [--t1 T1] [--res 480p\|720p\|1080p] [--model MODEL] [--provider openrouter\|higgsfield\|hedra] [--frame ref\|first] [--aspect-ratio 16:9\|9:16\|1:1\|4:3\|3:4\|21:9\|adaptive] [--reuse-start] [--start START] [--ref REF] [--clear-refs] [--audio AUDIO] [--audio-mode clean\|vocal\|mix] [--recut] [--no-audio] [--audio-on] [--why WHY]` | change a clip (back to draft; re-lock after) |
| `slop clip lock CLIP` | draft -> locked (checks: start, window, no [[slots]], exact quoted words) |
| `slop clip submit CLIP [--provider openrouter\|higgsfield\|hedra] [--yes] [--res 480p\|720p\|1080p] [--no-audio-ref] [--resubmit-unknown] [--dry-run] [--finalize-from TAKE] [--again] [--quote-only] [--hedra-cost HEDRA_COST] [--hedra-currency USD\|credits]` | spend: OpenRouter job, or the Higgsfield request file for the bot (locked + --yes) |
| `slop clip poll [CLIP] [--wait WAIT] [--job-id JOB_ID]` | check OpenRouter jobs (all in flight when no CLIP); download completed takes |
| `slop clip ingest CLIP [--file FILE] [--url URL] [--job-id JOB_ID] [--credits CREDITS] [--provider higgsfield\|openrouter\|hedra\|manual] [--pending] [--failed FAILED] [--declined DECLINED] [--cost-usd COST_USD]` | add a take from a file or a result URL (Higgsfield), or mark a request pending/failed |
| `slop clip sync CLIP [--take TAKE] [--no-png]` | measure lip sync of a take (avsync) -> take.sync + PNG |
| `slop clip frame CLIP [--at AT] [--take TAKE] [--out OUT]` | a still from a take at a song time (default: its last in-sync frame) to start a clip from |
| `slop clip coverage [CLIP] [--min-gap MIN_GAP]` | sung seconds held in sync (all sung clips, or the given chains) |
| `slop clip cover CLIP [--make] [--lock] [--max-covers MAX_COVERS] [--min-gap MIN_GAP] [--start START]` | propose (and --make) cover clips for a chain's uncovered sung gaps |
| `slop clip list` | all clips, status and expected spend |
| `slop clip status CLIP` | one clip in full (prompt, takes, sync, lock problems) |
| `slop sync check VIDEO REF [--song-t0 SONG_T0] [--png PNG] [--out-json OUT_JSON] [--title TITLE] [--need SONG_T0 SONG_T1]` | lag, synced span, divergence, cut on the last eighth; optional PNG |
| `slop sync review VIDEO REF --song-t0 SONG_T0 --out OUT [--audio AUDIO]` | render the take with our audio laid on and a divergence marker |

### Storyboard, plates and edit

| Command | What it does |
|---|---|
| `slop board draft [--force] [--out OUT] [--pace quick\|studio\|director]` | write a DRAFT board/shots.json from analysis/{beats,words}.json (cuts on beats, pace per section, clips within budget, TODO markers for the lead) |
| `slop board set SHOT [--set SET] [--framing FRAMING] [--action ACTION] [--img-prompt IMG_PROMPT] [--mj-prompt MJ_PROMPT] [--camera CAMERA] [--treatment TREATMENT] [--transition-in TRANSITION_IN] [--lead] [--no-lead] [--line LINE] [--type-mode TYPE_MODE] [--type-text TYPE_TEXT] [--type-placement TYPE_PLACEMENT] [--subject-uv SUBJECT_UV] [--notes NOTES] [--tier TIER] [--clip CLIP] [--switch-generator]` | write one shot's fields (or several: s004,s007 or s004-s009) — validated against the engine; a bad value changes nothing |
| `slop board fill FILE [--check] [--switch-generator]` | many shots at once from a TSV (header row: id, set, framing, action, img_prompt, …) or JSONL file; one bad row fails the whole fill (nothing written). An empty cell leaves the field as it is. A devices column/key REPLACES the shot's whole devices list ([] clears it; to add one device use `board device add`). |
| `slop board device add SHOT --kind KIND [--line LINE] [--anchor ANCHOR] [--key KEY] [--param NAME=VALUE] [--params PARAMS] [--at AT] [--until UNTIL] [--priority PRIORITY] [--example] [--replace I]` | add one device to a shot (e.g. --kind callout --line 3 --anchor uv:0.62,0.4 --param word=walk --param 'rows=["LINE 04", "WALK"]') |
| `slop board device rm SHOT [--index INDEX] [--kind KIND] [--line LINE] [--all]` | remove a device from a shot (by --index from `device list`, or --kind / --line) |
| `slop board device list [SHOT]` | the devices on a shot (or on every shot), each checked against the engine |
| `slop board device kinds [--kind KIND]` | the engine's device library (read from engine/src/devices: every drawable device and camera move); --kind K for one in full |
| `slop board audit [--shots SHOTS]` | run every storyboard gate -> board/audit.json + a table (exit 1 while a gate fails) |
| `slop board sheet [--shots SHOTS] [--flags FLAGS]` | contact sheet for owner approval -> board/board.pdf + board/board-pNN.jpg |
| `slop board approve [--note NOTE]` | record the owner's approval (gates.board_approved, logged in DECISIONS.md) — only when every gate passes; the same as `slop gate board --approve` |
| `slop plates book [--batch BATCH] [--only ONLY] [--missing] [--plan basic\|standard\|pro\|mega] [--anchor PLATE[:K]] [--no-anchor]` | plates/prompts.md + Midjourney permutation paste blocks + API jobs from the board's prompts |
| `slop plates ingest [SRC] [--url URL] [--plate PLATE] [--batch BATCH] [--map KEY=PLATE] [--force] [--credits CREDITS] [--job-id JOB_ID] [--model MODEL]` | downloads (zip, folder or image) or HTTPS result links (--url … --plate P) -> plates/cands/<plate>/<k>.jpg |
| `slop plates sheet [--plates PLATES]` | numbered picking sheets -> plates/sheets/pick-NN.jpg |
| `slop plates pick [PAIRS] [--all-first]` | record picks: PLATE K [PLATE K ...] (or "p001#2, p004#1") -> plates/picks.json |
| `slop plates vary [--dry]` | one image per shot: repeated plates get the other candidates; no two clips share a start frame |
| `slop plates status` | per plate: prompt state, candidates, pick, shots |
| `slop plates box PLATE [--label LABEL] [--uv UV] [--score SCORE] [--rm]` | name a region of a plate's picked image (--label 'a face' --uv u,v,w,h, 0..1) so devices can anchor to it; no --label lists the plate's boxes |
| `slop edit edl [--shots SHOTS]` | build edit/edl.json from the board, picks and synced clips (+ a per-shot report) |
| `slop edit export [--depth auto\|on\|off] [--no-frames] [--force] [--gpu auto\|off\|require]` | write engine/assets/{beats,lyrics,hits,shots,edl,plates,clips}.js, clip frames and plates |
| `slop edit look show` | show the look settings and whether they can be applied |
| `slop edit look set [--mode native\|clean-grade\|print] [--hero HERO] [--strength STRENGTH] [--contrast CONTRAST] [--accent ACCENT] [--font-lyric FONT_LYRIC] [--font-micro FONT_MICRO] [--font-display FONT_DISPLAY]` | change project.json look |
| `slop edit look sheet [PLATES] [--out OUT]` | before \| after pairs on picked plates -> board/look-sheet.jpg |
| `slop edit look grade FILES --out OUT [--width WIDTH]` | graded copies of images |
| `slop edit look lut VIDEO --out OUT [--size SIZE] [--samples SAMPLES]` | bake the grade for one video into a .cube LUT (16 sampled frames) |

### Render and delivery

| Command | What it does |
|---|---|
| `slop render info [--size SIZE]` | boot the engine page and report what it loaded |
| `slop render frames [--from T_FROM] [--to T_TO] [--every EVERY] [--workers WORKERS] [--size SIZE] [--out OUT] [--timemap] [--force] [--allow-missing]` | render frames to render/frames (resumable) |
| `slop render stills --times TIMES [--size SIZE] [--out OUT] [--allow-missing]` | full-resolution frames at given times |
| `slop render sheet [--times TIMES] [--n N] [--cols COLS] [--w W] [--chapter CHAPTER] [--review] [--size SIZE] [--vertical] [--out OUT] [--allow-missing]` | contact sheet of sampled frames (default: every shot's mid-point) |
| `slop render lyrics [--from T_FROM] [--to T_TO] [--workers WORKERS] [--size SIZE] [--vertical] [--out OUT]` | lyric gate: every sung token drawn at its time (N/N) |
| `slop render encode [--frames FRAMES] [--out OUT] [--review] [--draft] [--vertical] [--allow-gaps] [--no-audio] [--share] [--max-mib MIB]` | frames -> out/master.mp4 (CRF 16, BT.709 tags, audio) + ffprobe verify |
| `slop render check [--video VIDEO] [--pairs PAIRS] [--skip-flash] [--skip-history] [--max MAX] [--area AREA] [--delta DELTA] [--layers] [--workers WORKERS] [--size SIZE] [--vertical]` | flash check on out/master.mp4 + history check |
| `slop render clean [--keep-master] [--dry]` | free the disk: delete the frames once out/master.mp4 (and out/vertical.mp4) verify |
| `slop render vertical [--method rerender\|crop] [--workers WORKERS] [--from T_FROM] [--to T_TO] [--every EVERY] [--skip-encode] [--no-audio] [--allow-missing]` | the 9:16 cut (1080x1920) -> out/vertical.mp4 |

### Review (safety and canon scan)

| Command | What it does |
|---|---|
| `slop review scan-sheets [--plates] [--force]` | one 3x2 sheet per take the edit plays (8/25/42/58/75/92 %) -> render/scan/ |
| `slop review record FILE` | record the findings JSON (safety-scan schema) -> render/scan/scan.json |
| `slop review status` | what render/scan/scan.json says: checked takes, open blocks, the verdict |

### Taste

| Command | What it does |
|---|---|
| `slop taste serve [--port PORT] [--host HOST] [--tunnel] [--new-token] [--no-embed] [--foreground]` | start the tap app (background; idempotent); --tunnel for a phone link |
| `slop taste stop` | stop the tap app and its tunnel |
| `slop taste status` | server URLs, taps, meter, stop rule, font A/B progress |
| `slop taste pool add [--arena SLUG] [--mine] [--dir DIR] [--urls URLS] [--starter] [--kind human\|generated] [--max MAX]` | add images: --arena SLUG (own/followed channels) \| --dir DIR \| --urls FILE \| --starter |
| `slop taste pool list [--limit LIMIT]` | pool summary (+ the last N images) |
| `slop taste embed [--provider auto\|local\|openrouter] [--model MODEL] [--patches PATCHES] [--threads THREADS] [--reembed] [--yes]` | embed pool images that have no vector yet (cached per image) |
| `slop taste fit` | fit the taste model on all taps -> taste/model.npz + model.json |
| `slop taste meter [--reps REPS] [--curve]` | held-out accuracy (repeated 5-fold, nested λ), margin, self-agreement, stop rule |
| `slop taste tokens [--no-words] [--yes]` | write taste/taste-tokens.json + look-bible.md (suggestions + owner questions) |
| `slop taste board QUERY [--n N] [--refs REFS] [--text-max TEXT_MAX] [--yes]` | mood board for a text query x your taste (+ text-free refs for --sref) |
| `slop taste fonts [ACTION] [--frame FRAME] [--families FAMILIES] [--text TEXT] [--lines LINES] [--fonts-dir FONTS_DIR] [--seed SEED] [--reset] [--tunnel] [--no-serve]` | font A/B on real lyric lines over the style frame: setup (default) \| rank |
| `slop taste use [--profile user\|project] [--fork] [--merge] [--ignore-local]` | where this project's taste lives: your user profile (default) or its own |
| `slop taste sheet [--pairs PAIRS] [--per-sheet PER_SHEET] [--seed SEED] [--new] [--discard SHEET_ID]` | no tunnel? numbered pair sheets (JPG <= 2 MB) to send in the chat |
| `slop taste record ANSWERS [--sheet SHEET] [--redo] [--no-meter]` | record the reply to a pair sheet, e.g. slop taste record "1a 2b 3a" |
| `slop taste verdict [RULE] [STATUS] [--note NOTE] [--value VALUE] [--list]` | the owner's verdict on a taste rule: RULE confirmed\|rejected [--value] [--note] |
| `slop taste apply [--accent ACCENT] [--mode native\|clean-grade\|print] [--lyric-font LYRIC_FONT] [--micro-font MICRO_FONT] [--display-font DISPLAY_FONT] [--texture yes\|no] [--medium photo\|cel] [--tail TAIL] [--note NOTE] [--yes]` | write the owner-confirmed look into project.json (preview; --yes writes) |

### Setup checklist (onboarding)

| Command | What it does |
|---|---|
| `slop onboard status [--tier quick\|studio\|director] [--offline] [--group start\|toolkit\|keys\|connectors\|music\|stills\|agents-box\|agents-home\|gpu\|taste\|project]` | every item with its state, why and next step |
| `slop onboard next [--tier quick\|studio\|director] [--offline] [--except ITEM]` | the single best next item for the tier |
| `slop onboard mark ITEM --done\|--connected\|--skip\|--todo [--note NOTE]` | record an item: --done/--connected, --skip or --todo |
| `slop onboard set tier\|suno-plan\|mj-plan\|mj-profile\|coding-agents [VALUE] [--clear]` | user settings: tier, suno-plan, mj-plan, mj-profile, coding-agents |
| `slop onboard apply [--force]` | put the recorded Midjourney plan and profile code into a project |

### Coding agents (Claude Code, Codex, Muse Code, Gemini CLI)

| Command | What it does |
|---|---|
| `slop agents status [ENGINE] [--limits]` | installed? version? signed in (plan)? --limits: plan usage, no tokens spent |
| `slop agents install ENGINE [--method native\|npm] [--upgrade] [--dry-run] [--foreground]` | install into $SLOP_HOME (survives a computer update); runs as a background job |
| `slop agents login ENGINE [--code-from-env NAME] [--token-from-env NAME] [--key-from-env NAME] [--check] [--cancel] [--force]` | sign in headless: prints the link (and code) for the user; see --code-from-env |
| `slop agents test ENGINE [--job JOB]` | one tiny "reply OK" run through runner/deleg.mjs (skipped when not signed in) |
| `slop agents use [ENGINE] [--for director\|review\|images]` | which agent does what: --for director\|review\|images (no args: show) |

### Relay (Grok passes the words; the production does the work)

| Command | What it does |
|---|---|
| `slop relay setup [--engine ENGINE] [--model MODEL] [--no-skill] [--force]` | check the engine is signed in, register the claudia.gallery MCP, install the Claudia skill, write the production brief (CLAUDE.md, AGENTS.md in the projects folder) |
| `slop relay send [TEXT] [--file FILE] [--from director\|grok]` | pass words to the production verbatim; starts a turn when it is idle (returns in seconds) |
| `slop relay read [--wait S] [--all]` | what Grok shows next: new messages with their files, open jobs, the production's state, grok_next |
| `slop relay done JOB [--file FILE] [--note NOTE] [--model MODEL]` | (Grok) a job's files are saved: mark it done and tell the production |
| `slop relay cancel JOB [--reason REASON]` | close a job no one needs any more (cancelled, not failed): the production's own, or Grok's when the person says so |
| `slop relay fail JOB --reason REASON [--declined]` | (Grok) a job could not be done: mark it failed (--declined: the service refused it) |
| `slop relay say TEXT [--show FILE] [--as-is]` | (the production) post a message for the director, with files to show |
| `slop relay ask TEXT [--default DEFAULT] [--show FILE] [--as-is]` | (the production) ask the director one question, with its default |
| `slop relay job --kind grok-imagine\|midjourney\|suno\|browser\|person\|hedra [--what WHAT] [--clip CLIP] [--prompt PROMPT] [--prompt-file PROMPT_FILE] [--image IMAGE] [--aspect 16:9\|9:16\|1:1\|2:3\|3:2] [--seconds SECONDS] [--save SAVE] [--name NAME] [--note NOTE] [--text TEXT] [--title TITLE] [--style STYLE] [--lyrics LYRICS] [--lyrics-file LYRICS_FILE] [--exclude EXCLUDE] [--instrumental] [--url URL] [--plate PLATE] [--personalize on\|off] [--expect EXPECT]` | (the production) ask Grok for browser work, all of it in Grok's own signed-in browser (--kind grok-imagine \| midjourney \| suno \| browser); --kind person only for what only a person can do |
| `slop relay hedra JOB --action quote\|start\|pending\|complete\|failed [--cost COST] [--currency USD\|credits] [--job-id JOB_ID] [--url URL] [--reason REASON]` | (Grok) report a Hedra connector quote, claim a generation once, or return its result |
| `slop relay inbox` | (the production) new messages from the director and Grok, marked read |
| `slop relay status` | the production's state, engine, session, message counts and open jobs |
| `slop relay wake [URL]` | the wake-up routine: Grok's webhook, called when the production posts while Grok is not waiting (a URL turns it on; off; test); its key: $CLAUDIA_WAKE_KEY |
| `slop relay effort [LEVEL] [--engine ENGINE]` | how hard the production thinks, per engine (Claude Code --effort, Codex reasoning effort): show the levels, or set one for the next turns |
| `slop relay stop [--grace GRACE]` | stop the running production turn (waiting messages stay) |
| `slop relay log [--lines LINES]` | the tail of the relay log (and the last turn's stderr) |

### Updates (one quiet reminder per release; update in one step)

| Command | What it does |
|---|---|
| `slop update check [--force]` | this computer's version and the newest release (one network call a day at most) |
| `slop update apply [--to TO] [--force]` | fetch the releases, check out the newest, repair the install, refresh the production brief; prints what changed and the skills step for Grok |
| `slop update seen` | the reminder for the newest release was shown (it is not shown again) |

### Home GPU

| Command | What it does |
|---|---|
| `slop gpu status [--verify]` | is a home GPU paired and healthy? its GPUs, profiles, queue and the next step |
| `slop gpu serve [--tunnel] [--no-tunnel] [--port PORT] [--stop]` | start the box's GPU job server + Cloudflare quick tunnel in the background |
| `slop gpu pair [--refresh] [--new] [--gpu GPU] [--url URL]` | print the ONE line the user pastes on the GPU computer (Windows PowerShell or bash). Refused while a worker is paired: a new pairing cuts the old worker off (use --new for that) |
| `slop gpu unpair [--keep-server]` | revoke the pairing (the worker on the PC stops), cancel open GPU jobs, stop the server and its public tunnel |
| `slop gpu mode [MODE]` | show or switch the GPU mode: paired (the worker polls the box) or direct (local exec) |
| `slop gpu profiles` | the GPU profiles: what they run, VRAM, download size, licences |
| `slop gpu install PROFILE [--accept-licence]` | install GPU profiles on the paired PC (queued; watch with slop gpu status) |
| `slop gpu jobs [--all] [--limit LIMIT]` | the GPU job queue |
| `slop gpu show JOB` | one job: state, metrics, outputs, log tail |
| `slop gpu wait JOB [--timeout TIMEOUT]` | wait for a job (at most --timeout s, default 25 / SLOP_WAIT_MAX) |
| `slop gpu cancel JOB` | cancel a job (a running job's processes are killed on the PC) |
| `slop gpu fetch JOB --to TO` | copy a finished job's outputs |
| `slop gpu submit ENTRY [--input INPUT] [--param PARAM] [--force-gpu]` | run one GPU entry by hand (see slop gpu profiles for the entries) |
| `slop gpu direct-plan [JOB] [--os windows\|mac_linux] [--profile PROFILE] [--use-direct]` | direct mode: the exact local-exec steps for the PC (setup, or one JOB). The setup plan switches to direct mode only when no mode is set yet, or with --use-direct |
| `slop gpu direct-ingest JOB [--from SRC]` | direct mode: finish JOB from the output parts copied back with CopyToBox |

<!-- END MODULE COMMANDS -->

## Layout

```
bin/setup.sh  bin/slop      installer and CLI shim
bin/gpu-worker.{sh,ps1}     the home-GPU worker installers (`slop gpu pair` serves them)
slop/                       the Python package (stdlib argparse CLI; one subcommand family per module)
engine/                     the frame renderer (headless Chromium), OFL fonts with their licences
runner/                     the coding-agent delegation runner, on the bot's computer or the user's (Director tier)
docs/                       the playbooks: how each stage is done well, prompt grammars, failure catalogue
templates/project/          what `slop new` copies; templates/briefs, templates/workflows for delegation
skills/                     the design of the compact Grok Bot skill set (the template recipe)
tests/                      pytest; synthetic fixtures only
```

A project folder's layout is described in its own `README.md`. The data contracts (project layout, the JSON formats,
the module map and the rules the code enforces) are in `docs/ARCHITECTURE.md`.

## Development

```bash
bash bin/setup.sh --full --dev
~/.claudia/venv/bin/python -m pytest -q          # fast tests
SLOP_TEST_SETUP=1 ~/.claudia/venv/bin/python -m pytest -m slow tests/test_core_setup.py   # real installer run
```

`env.sh` puts only `$SLOP_HOME/bin` (slop, uv, cloudflared) on PATH, not the venv's python, so call the venv's
python by its path for development.

Tests use synthetic fixtures and mock every HTTP call; nothing in the test suite spends money.
`tests/test_scrub.py` scans every shipped file for private identifiers. After changing a parser, regenerate the
command tables above with `python tests/gen_cmdref.py` (`tests/test_release.py` fails while they are stale).

## Licence

The toolkit is MIT-licensed (`LICENSE`, copyright anabology). Third-party material keeps its own licence:

Fonts: SIL Open Font License only (licence texts ship next to the font files). Models: Depth-Anything-V2-Small
(Apache-2.0), wav2vec2 (Apache-2.0), Whisper (Apache-2.0); htdemucs code is MIT but its weights carry no explicit
licence tag (flagged). Lyric-lint data: the CMU Pronouncing Dictionary (BSD-2-Clause; the GPL `cmudict` PyPI wrapper
is not used) and wordfreq (code Apache-2.0, data CC-BY-SA 4.0), both used locally. Song outputs: check your music
generator's terms for commercial use (with Suno, downloading on a paid plan is what allows it; its output-use clause
depends on your plan). Claudia is fan work about Claude, not affiliated with or endorsed by Anthropic.

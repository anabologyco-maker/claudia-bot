# Claudia architecture: the contracts

This is the public design contract of the toolkit: what the parts are, the files they exchange, and the rules the code
enforces. The playbooks (`docs/00-overview.md` onwards) say how each stage is done well; this file says what the data
looks like. Other docs and code comments cite it as "ARCHITECTURE §N", so the section numbers stay fixed.

## 1. Product

A shareable **Grok Bot template** ("Claudia") for Claudia content, sized to the ask: a still, a clip, a song, a music
video or a post. Claudia (the open character of claudia.gallery, the #1 source of truth: `docs/05-claudia-gallery.md`)
is the lead by default; a new character only when the user asks. The biggest ask turns a song idea (or an existing
song) into a finished lyric music video. The quality bar is anabology's *Escape Velocity* (EV) and *Clodyssey* (SP)
lyric videos, at any user's depth:

| Tier | Who / what | Song | Stills | Motion | Agents | Typical cost |
|---|---|---|---|---|---|---|
| **Quick** | Grok Bot + its cloud computer only | the user's Suno upload, or Lyria via OpenRouter (≤ 3 min) | API images (OpenRouter / Higgsfield / Grok's image tool) | a few motion clips (cheap models, 480p drafts) + 2.5D, or none | none | $0–20, 10–15 turns (live run: $1.06, 13 turns) |
| **Studio** | + an OpenRouter key or Higgsfield (both recommended) + the user's own Midjourney / Suno (Grok runs Midjourney in its browser, where the user signed in once, and Suno through Suno's own connector) | Suno (the user's) | Midjourney (prompt book → Grok's browser → ingest) or API | Seedance 2.5 sung clips with measured lip sync, covers | none | $50–110, 20–35 turns |
| **Director** | + the user's own Claude Code / Codex / Muse Code | Suno | Midjourney | full | delegated workflows (storyboard panel, bespoke chapter motion design, reviews) | EV-class; Grok turns only at the gates |

Design for return visits: multi-session projects, a taste profile that improves with use and follows the user across
projects, and a fast first win (the Quick tier in one sitting).

## 2. Platform facts that shape the design

- A template is a JSON recipe `{profile{name,description}, memory[], skills[{name,description,content}], routines[],
  plugins[{pluginId}], gettingStarted{skill}}`, ≤ 25 MiB. **Import is replayed by the model**, so skills must be
  **compact** (target ≤ 60 KB in all, each ≤ 10 KB). Deep knowledge lives in this repo's docs, not in skills.
- Secrets, files, custom MCP servers and logins do **not** travel with a template. Secrets: the bot asks for them with
  its **masked secure card** (names `^[A-Z][A-Z0-9_]*$`); they arrive as environment variables in the computer's shell.
- The bot's computer: Debian, 8 vCPU, 15 GiB RAM, no GPU, Python 3.13, ffmpeg (**no whisper filter**), node 20, git,
  curl, jq, google-chrome. **Packages are wiped on a computer update; `/workspace` persists**, so everything installs
  under `/workspace/.claudia` and setup re-checks idempotently.
- MCP tool calls time out (about 120 s idle), so long generations are submit-then-poll, and long local steps run as
  background jobs (`slop job`).
- The Higgsfield connector (MCP) is the built-in video path (Seedance 2.5/2.0, Kling, Veo, Wan, MiniMax and others).
  `estimate_video_cost` (stills: `estimate_image_cost`; audio: `estimate_audio_cost`) preflights credits for free with
  the generate tool's own params. Media imported through the connector get public HTTPS URLs.
- Local exec can run commands on the user's own computer (permission per machine; short foreground timeout, so long
  work runs detached). This is how the Director tier reaches the user's own coding agents.
- The bot computer has no public preview URL, so the tap app and audio hosting use a **Cloudflare quick tunnel**
  (`cloudflared tunnel --url`, binary downloaded to `/workspace`) with a random token path.
- Grok Bot usage is a weekly pool (measured in a live Quick run: about 0.25 % of a Pro+ week a reply; an earlier upper
  bound was 1.5 % a turn). The bot must work in few, fat turns: **one `slop` command does many steps**. A bot cannot
  wake itself, so a turn keeps working (bounded `slop job wait`) up to a checkpoint, or ends asking the user to say
  "continue".
- Midjourney has no API: **Grok runs it in its own browser**, where the user signed in once (told once that its
  terms limit automated use). Suno has its own MCP server: **Grok runs Suno through that connector** (the user signs
  in to Suno once on its card; Grok's browser only while it is not set up). Grok Imagine is Grok's own tool. The
  production writes the prompt blocks, the lyric and style fields or the Imagine prompt and sends them with
  `slop relay job --kind midjourney|suno|grok-imagine`; Grok creates and downloads; the user only decides
  (`50-plates-midjourney.md` §9, `10-song.md` §5).

## 3. Components

```
claudia/
  bin/setup.sh       idempotent installer -> $SLOP_HOME: uv, Python 3.13 venv, pinned deps, fonts, chromium, cloudflared
  bin/slop           shim: exec "$SLOP_HOME/venv/bin/python" -m slop "$@"
  slop/              Python package (3.11+), stdlib argparse CLI, one subcommand family per module
  engine/            the JS frame renderer (headless Chromium), OFL fonts only (with their licence texts)
  runner/deleg.mjs   local-agent delegation runner (Claude Code / Codex / Muse Code), job-folder contract
  docs/              THE KNOWLEDGE: playbooks, prompt grammars, scrubbed exemplars, failure catalogue, this contract
  templates/         project scaffold, delegation briefs, Claude Code workflow scripts (Director tier)
  skills/            the design of the compact Grok Bot skill set
  tests/             pytest; fixtures are synthetic or tiny
```

### 3.1 Paths and environment

- `SLOP_HOME` (default `/workspace/.claudia` on the bot computer, `~/.claudia` elsewhere): venv, model cache
  (`HF_HOME=$SLOP_HOME/cache/hf`, `TORCH_HOME=$SLOP_HOME/cache/torch`), chromium, cloudflared, fonts, the user's taste
  profile.
- `SLOP_PROJECTS` (default `/workspace/slop/projects` on the bot computer, `~/slop/projects` elsewhere).
- Project resolution: `--project NAME` **or** `SLOP_PROJECT` **or** the current folder inside a project. **Never a silent
  default project.**
- Secrets come from the environment only: `OPENROUTER_API_KEY` (API generation), `ARENA_TOKEN` (optional, Are.na),
  `HIGGSFIELD_API_KEY` (optional; Higgsfield normally runs through the bot's connector).
- Run-time switches: `SLOP_FREE_ONLY=1` refuses every paid call (no project needed); `SLOP_WAIT_MAX` caps how long one
  `slop job wait` or `slop next` call blocks (default 25 s, under the bot shell's limit); `SLOP_PROGRESS_FILE` is where
  long render commands write their progress; `SLOP_MODULES` limits which command families load.
- Every command: `--json` prints one JSON object on stdout (`"ok"`, `"text"`, and the command's data; usually `"next"`,
  the command to run after it). Exit code ≠ 0 on failure with `{"ok": false, "error": ...}`. Errors say what to do next.

### 3.2 Project layout

```
<project>/
  project.json            # §4.1
  BRIEF.md PLAN.md NOTES.md  # the owner's ask (verbatim), the plan, working notes
  DECISIONS.md            # dated decisions; "UPDATE … supersedes" blocks
  RUNS.md                 # ids of long or delegated runs, for resume
  ledger.jsonl            # every paid call: {ts, provider, model, kind, units, est_usd, real_usd?, request_id, status}
  jobs/                   # `slop job` records (one folder per background job)
  audio/song.wav          # 44.1 kHz stereo master (as delivered)
  audio/stems/{vocals,drums,bass,other}.wav
  audio/windows/<clip>.mp3  # per-clip reference windows (clean vocal or mix)
  lyrics/lyrics.txt       # sung words, one line per lyric line, numbers/symbols SPELLED AS SUNG
  lyrics/display.txt      # on-screen tokens per line; "TEXT|n" = token spans n sung words (e.g. "+25%|3")
  analysis/beats.json     # §4.2
  analysis/words.json     # §4.3
  analysis/hits.json      # §4.4
  analysis/report.md      # human summary + ear-check list (gaps > 1 s, low-confidence words)
  analysis/lyrics-check.json  # `slop lyrics check`: what the take sings vs the sheet
  taste/                  # taste-tokens.json, look-bible.md, verdicts.jsonl (or a link to the user's taste profile)
  board/shots.json        # §4.5 storyboard (source of truth for the edit)
  board/board.pdf|.jpg    # contact sheet for owner approval
  board/audit.json        # gate results
  plates/prompts.md       # prompt book (Midjourney or API); plates/jobs.json = the API jobs (lead plates' jobs carry
                          # "refs" + "anchor": the approved lead image, `slop plates book --anchor PLATE[:K]`)
  plates/cands/<plate>/<k>.jpg ; plates/picks.json {plate: {file, cand_k, shot_ids[]}} ; plates/boxes.json
  clips/<clip>.json       # §4.6 one file per clip (request, takes, sync)
  clips/<clip>/take-N.mp4
  edit/edl.json           # §4.7
  engine/                 # per-project engine assets written by `slop edit export`
  render/frames/ ; render/scan/ (safety and canon scan) ; out/master.mp4 ; out/vertical.mp4 ; out/review.mp4 ; out/share.mp4
```

**Lyric file format** (one parser, `slop.util.read_lyric_lines`, used by the audio, board, taste and core modules):
blank lines and every line starting with `[` (section tags such as `[Chorus]`, and notes) are skipped; the Nth
remaining line of `display.txt` is the on-screen version of the Nth remaining line of `lyrics.txt`.

## 4. Data contracts (the formats the reference engine already reads)

### 4.1 project.json

```json
{"name":"my-song","title":"My Song","tier":"quick|studio|director","song":"audio/song.wav","fps":24,"size":[1920,1080],
 "lead":{"canon":"<pinned identity text block>","far":"<short full-length variant>","possessive":"…","noun":"…","pronoun":"…"},
 "look":{"mode":"native|clean-grade|print","accent":"#D97757","fonts":{"lyric":"…","micro":"…","display":"…"},"hero_plate":null},
 "mj":{"params":"--ar 16:9","raw":true,"hd":false,"personalize":true,"profile":""},
 "models":{"image":"openai/gpt-image-2","video":"bytedance/seedance-2.5","video_cheap":"bytedance/seedance-2.0-mini","edit":"google/gemini-3-pro-image"},
 "budget":{"openrouter_usd":20,"higgsfield_credits":300,"confirm_over_usd":2},
 "gates":{"board_approved":false,"prompts_approved":false,"v1_approved":false}}
```

Optional keys the modules read: `budget.frozen` (the owner's quality flag: no paid call), `budget.motion_s`,
`board.{pace,treatments,max_clips,lead_min}` (`pace` = `quick` | `studio` | `director` or a block of seconds per
section), `audio.{downbeat_phase,downbeat_method,sections,whisper_usd_per_s,hits.kick_click}`, `look.medium`,
`look.section_accents`, shot `subject_uv`, `gates_meta.*`, `lead.{note,none}`.

### 4.2 analysis/beats.json (engine: `window.BEATS`)

`{"duration":s, "beats":[s…], "downbeats":[s…], "tempo":[{"t":s,"bpm":x}…], "sections":[{"name":"intro|verse1|…",
"t0":s,"t1":s,"energy":x,"vocals":x,"bar0":k,"bar1":k,"source":"lyrics-tag|set|heuristic","unconfirmed"?:true}],
"source":"beatmap-v1"}`: **variable tempo, never a single BPM**;
local tempo fit in 20 s windows every 5 s; beats snapped to drum-stem onsets within ±30 ms; the downbeat phase is voted
per 32-beat block and can be set with `slop song bars --phase N`. Bars count from 0 (bar 0 starts at the first bar
line).

### 4.3 analysis/words.json (engine: `window.LYR` via export)

`{"words":[{"i":0,"w":"ladies","line":0,"t0":9.32,"t1":9.64,"conf":0.91,"src":"w2v|whisper|interp|manual"}],
"lines":[{"line":0,"text":"Ladies. Gentlemen. Agents.","t0":…,"t1":…}], "gaps":[{"t0","t1","after_word"}]}`.
Engine lyric export format: `[{line, kind:"lyric", text, t0, t1, tokens:[{txt, t0, t1, st, n}]}]`, built from
words.json + display.txt.

### 4.4 analysis/hits.json (engine: `window.HITS`)

`{"kick":[s],"snare":[s],"hat":[s],"hits":[{"t":s,"score":x}],"risers":[{"t0","t1","land"}],"fills":[{"t0","t1"}],
"vocal_entries":[s],"env24":{"drums":[…],"vocals":[…],"bass":[…]}}`.

### 4.5 board/shots.json

Top level `{version, duration, chapters, shots, seedance, plates}`. Shot fields:
`id, t0, t1 (on beats), section, lines[], set, lead_on_screen, framing (ECU|CU|MCU|MS|MWS|WS|FS|EWS|OTS), action,
camera, motion_tier ("still"|"plate3d"|"motion"|"sung"), plate (plate key), clip (clip id or null),
mj_prompt|img_prompt, type[{line, mode: subtitle|coverline|masthead|stack|mass, text, placement}],
devices[{kind, anchor, params, key:"W|B|H|F|T", at?, until?}], treatment (2.5D family), transition_in, chrome, accent,
subject_uv, notes`. The fields are written with `slop board set`, `slop board fill` and `slop board device add`, which
validate every value against the engine (device kinds, params, anchors, time keys) and refuse placeholder text.

Audits (`slop board audit`): shots tile [0, duration] with no gaps or overlaps; every cut within 0.03 s of a beat (or a
declared hit); every sung word appears in some shot's type; one explaining graphic per lyric line; the lead-on-screen
share ≥ target (default 70 %); total motion/sung seconds ≤ budget; one plate candidate per shot (two clips never start
from the same frame); no banned words; no TODO or placeholder left; a 2.5D treatment never repeats on consecutive
shots (compared by engine family).

### 4.6 clips/<clip>.json

`{id, shot, kind:"sung"|"motion", status:"draft"|"locked"|"submitted"|"delivered"|"declined"|"failed",
provider:"openrouter"|"higgsfield", model, start (plate file), song_t0, needed:[a,b], words:"exact sung words in
window", window:{t0,t1,mode:"clean"|"mix", file, url}, body:{prompt, duration, resolution, aspect_ratio,
generate_audio}, takes:[{provider,id,status,file,cost_usd|credits, sync:{lag_s, ncc, mode:"copy"|"none",
synced:[[a,b]], diverge_at, cut_at}}], covers:[clip ids], why}`.
Spending requires `status:"locked"` **and** `--yes` (or the `prompts` gate covering this clip prompt as it is now).
`slop clip submit --dry-run` runs the same checks as a real submit. Declines (face filter) are final for that
reference: **never alter an image to pass a provider filter**; trying the other provider with the same unaltered image
is allowed.

### 4.7 edit/edl.json (engine: `window.EDL`)

`{"s001":{"segs":[{"t0":0.0,"clip":"SD01-t1","in":0.0}]},"s002":{"plate":"p002"}}`; a clip's `in` = song time −
song_t0 + lag_s (the take's measured lag).

## 5. Modules

| Module | Files | Provides |
|---|---|---|
| **core** | `bin/`, `slop/{__init__,__main__,cli,config,ledger,util,doctor,core_cli,job,fetch,progress}.py`, `templates/project/` | CLI router (each `slop/<module>/cli.py` exposes `register(subparsers)`; every command is `func(args) -> dict` with `"text"`), project scaffold/resolve, `slop status` and `slop next`, background jobs (`slop job`), `slop fetch`, ledger + `slop spend` (real spend from OpenRouter `/api/v1/credits` + `/api/v1/key`), owner gates, `slop doctor`, setup.sh |
| **audio** | `slop/audio/` | `slop song ingest/sections/bars`, `slop analyze` (CPU htdemucs stems, wav2vec2 CTC alignment + Viterbi, Whisper fallback via OpenRouter, beat map, sections, hits, ear-check report), `slop lyrics lint/display/fix/check`, `slop audio window` |
| **gen** | `slop/gen/`, `slop/sync/` | OpenRouter images (single and batch `--jobs`) and image edits, OpenRouter videos (submit/poll/download, Seedance @Image1/@Audio1, cheap models), Lyria songs, audio hosting (tunnel or a connector URL), Higgsfield request files + result ingest (the bot runs the MCP calls), `slop clip sync` (avsync), covers, coverage, moderation handling |
| **board** | `slop/board/`, `slop/edit/` | board draft, `board set/fill/device`, audit, contact sheet, approval, plates (book, ingest incl. `--url`, sheet, pick, vary, box), EDL, engine export, look/LUT grade |
| **engine** | `engine/`, `slop/render/` | data-driven renderer for shots.json devices/type/transitions (no hard-coded video), OFL fonts only, `slop render info/frames/stills/sheet/lyrics/encode/check/vertical/clean` |
| **review** | `slop/review/` | the safety and canon scan: `slop review scan-sheets/record/status` |
| **taste** | `slop/taste/` | tap app (static, phone-first) + server + tunnel, chat pair sheets (`taste sheet/record`), embeddings (SigLIP 2 base on CPU, or OpenRouter), Bradley–Terry/logistic + kNN model, held-out meter, `taste-tokens.json`, owner verdicts, `taste apply` to the look, mood boards, font A/B, one profile per user (`taste use`) |
| **deleg** | `runner/`, `templates/briefs/`, `templates/workflows/` | runner (new/start/status/wait/run/stop/resume/wire/preflight/selftest) for `claude -p` (stream-json, the Workflow tool allowed), `codex exec --json`, `muse exec --json`, Gemini CLI (one-off jobs); at most 2 agent jobs at once on the box; job folder contract (BRIEF.md, job.json, outbox/, status.json); briefs; Claude Code workflow scripts (storyboard panel, chapters animator → art director → fix, research + lyrics, safety scan) |
| **onboard** | `slop/onboard/` | `slop onboard status/next/mark/set/apply`: one checklist of everything a user can set up (tier, toolkit, keys, connectors, music, stills, coding agents, home GPU, taste, first project), the next step for the user's tier, tier readiness and unlocks; state in `$SLOP_HOME/onboard.json`, never a secret |
| **agents** | `slop/agents/`, `slop/gen/codex_image.py` | `slop agents status/install/login/test/use`: Claude Code, Codex, Muse Code and Gemini CLI installed under `$SLOP_HOME` on the box (survives an update), headless sign-in (codes only via the secure secret card), plan limits without spending tokens, the director/review/images preference read by `runner/deleg.mjs`; `gen image --provider codex` (ChatGPT-plan stills, experimental) |
| **gpu** | `slop/gpu/`, `bin/gpu-worker.sh`, `bin/gpu-worker.ps1` | `slop gpu ...`: the user's own GPU, paired (job server + quick tunnel on the box, a worker on the PC that polls it) or direct (local exec); FIFO job queue, profiles (audio, matte, interp, lipsync opt-in), `--gpu auto/off/require` routing for `analyze` and `edit export` |
| **docs** | `docs/` | the playbooks (§6), written for a weaker model, scrubbed |

## 6. docs/ (the knowledge that makes quality transferable)

`00-overview` (pipeline map, tiers, gates, budgets) · `10-song` (concepts, lyric writing with scansion, Suno pack,
Lyria fallback) · `20-analysis` (stems, alignment, beat map, sections, ear-check, lyrics check) · `30-taste` (capture
protocol, tokens, verdicts, look bible, fonts) · `40-storyboard` (shot grammar, the explaining-graphic rule, hooks,
writing the board, audits, board review) · `50-plates-midjourney` (prompt grammar, lead canon + far variant, style
tails, permutations, ingest, fix-the-source edits) · `51-plates-api` (model choice, batch jobs, edits) · `60-clips`
(screenplay prompt grammar, sung/motion templates, windows, providers, costs) · `61-lipsync` (avsync method, cuts,
covers, no-fallback rule) · `62-moderation` (face filter, refusal wording, never-alter rule) · `70-motion-design`
(device library, type modes, transitions, 2.5D, look, element budget, flash rule) · `80-review-qa` (gates, contact
sheets, the safety and canon scan, reviewer scoring) · `90-master-publish` (encode tags, loudness, vertical cut, chat
copy, AI label, posting copy) · `95-delegation` (when and how to delegate, briefs) · `96-setup-and-hardware` (the onboarding
checklist, coding agents on the box, a home GPU) · `99-failures` (failure → fix
catalogue) · `examples/` (scrubbed exemplars from EV and SP).

## 7. Non-negotiable quality and safety rules (code gates where possible)

1. Every sung word on screen at its forced-alignment t0 (lyric gate N/N), and the alignment verified against the audio
   (confidence + ear-check list).
2. Variable beat map; cuts on beats/hits; motion on the beat, words on the voice.
3. One explaining graphic per lyric line; ≥ 3 ordered layers per frame; 2.5D treatments never repeat back to back.
4. Lead identity = a pinned text canon (framing first; far variant for full-length shots). By default the lead is
   Claudia: her canon's identity text, photographic, never illustrated, an adult in her late twenties, never "young"
   (`docs/05-claudia-gallery.md` §3). API stills may add one image (for Claudia only if text alone drifts and the
   owner agrees):
   the lead close-up the owner approved at G3, as a reference next to the text (`slop plates book --anchor`); never
   a photo of a real person, never on Midjourney.
5. Generation inputs stay in colour; grade in post (a LUT per clip from sampled frames).
6. Sung clips: plate @Image1 + the exact song window @Audio1, the prompt quotes the exact words; measure sync (avsync);
   cut at the last eighth before divergence; cover from that frame; no lip-sync-model fallbacks by default (cut away
   instead).
7. Screenplay for acting and motion, short for copy: motion clip prompts are screenplays (timestamps to 0.01 s on real
   word/hit times, blocking, action + reaction, camera tied to hits, mouth rules); sung clip prompts are the short sung
   form (the head quoting every word, one line of framing and light, at most 2 timed beats; §7b); all written by the
   lead in one context; the owner reads the book before any spend.
8. Spend gates: estimate before spend; `locked` + confirm; real spend from provider endpoints; on an owner quality flag
   stop all spending (`slop spend --freeze`).
9. Never alter a declined reference to pass a safety filter (a decline is free, and final on that service). Never type
   user credentials. Every job (Grok Imagine, Suno, Midjourney) is Grok's, on the user's own accounts;
   the user never pastes, presses Create or downloads.
10. Master: tagged **BT.709 primaries and matrix with the sRGB transfer (`iec61966-2-1`)**, as the source pipeline's
    encoder tagged it (the frames are sRGB canvas pixels), TV range, CRF ≤ 16, verified with ffprobe; flash check ≤ 3
    flashes a second.
11. Licences: Depth-Anything-V2-**Small** only; OFL fonts only (never Nimbus Sans, Junicode, Pilcrow Rounded or
    Alchimia); the htdemucs weights are flagged; the Suno output-use clause is flagged to the user.
12. Scrub: no owner identity, Midjourney profile code, private hostnames or provider job ids in anything shipped
    (`tests/test_scrub.py` scans every tracked file).

## 7b. Verified provider facts (real paid probes; these override any assumption)

- OpenRouter `/api/v1/videos` **rejects `data:` URIs for audio** (HTTP 400 "Only HTTPS URLs are allowed"). Audio must
  be HTTPS-hosted. A **Cloudflare quick tunnel** (`cloudflared tunnel --no-autoupdate --url http://127.0.0.1:PORT`,
  random token path) works for both images and audio; a Higgsfield connector media URL also works.
- **`frame_images` (first/last frame) OVERRIDES `input_references`: when a first frame is sent, the audio reference is
  silently ignored** (the take gets its own soundtrack). **Sung clips MUST use REFERENCE MODE**: the plate as an
  `input_references` `{type:"image_url"}` (= @Image1) + the window as `{type:"audio_url"}` (= @Audio1), **no
  frame_images**. First-frame mode is only for motion clips that need an exact start frame.
- Illustrated/stylized faces pass the OpenRouter face filter; photoreal faces are often declined → route photoreal
  sung shots to Higgsfield. Never restyle Claudia (photographic by canon) to pass it.
- Seedance 2.5 can fail with "output audio may contain sensitive information" (or a copyright refusal) on vocal
  references; failed jobs are unbilled. Retry once (re-cut window / reworded prompt), then the other provider
  (`slop clip ingest CLIP --failed "<reason>"` records a Higgsfield refusal and prints the next step).
- Costs observed: gpt-image-2 low $0.004 an image (1536×864); seedance-2.0-mini 480p 4–5 s $0.142–0.177;
  seedance-2.5 480p 5 s $0.518; job latency 70–130 s.
- Real runs through the toolkit: OpenRouter seedance-2.5 reference-mode sung clips copied the audio on 2 of 7 takes
  (one window 80 % in sync); one window that failed 4 times on OpenRouter copied on Higgsfield's first 480p draft (NCC
  0.49, 74 % in sync). The ledger matched OpenRouter's billing exactly.
- Sung prompt length is the biggest copy lever measured (Studio run, 2026-10-02): long timestamped screenplays held 44 %
  of the chorus's sung seconds in sync; three retakes in the short sung form raised it to ≈ 62 % (`c01` 0 % → 78 %).
  **Screenplay for acting and motion, short for copy:** sung clips draft the short sung form (`docs/60-clips.md` §4.0),
  motion clips the screenplay; `slop clip lock` warns past ~90 words or 2 timed beats.
- **Routing rule for a sung window that does not copy** (`docs/61-lipsync.md` §8): **short form first**: a window whose
  takes came from a long prompt is rewritten in the short sung form and retaken on the same provider; then after **2
  OpenRouter non-copies of the short form** → Higgsfield (480p draft → finalize if kept) → else cut away.
- Higgsfield takes that fail or are refused (including a 1080p finalize the connector rejects) are not charged: `slop
  clip ingest CLIP --failed "rejected: …"` records them at 0 credits; the project log counts only what `transactions`
  charged (the Studio run's log said 114 credits for 66 real before this).
- Higgsfield uploads: `media_import_url` works on tunnel URLs for audio and images (preferred). A presigned
  `media_upload` PUT needs the signed header `If-None-Match: *` or it returns 403.

## 8. Test strategy

- Unit and fixture tests per module (pytest) with synthetic audio (click tracks and sine "vocals") and tiny images;
  every HTTP call is mocked, so the suite never spends money. Opt-in tests (`SLOP_TEST_*` variables) run the real
  installer and the real Depth-Anything / SigLIP weights.
- Linux parity environment: Ubuntu 24.04, Python 3.13, CPU torch 2.11, demucs, transformers 5.17, librosa 1.0,
  Playwright 1.60 chromium. Run `pytest -q` from the repo root.
- Ground truth: the EV song and its shipped lyric and beat data → alignment and beat accuracy benchmark (target ≥ 90 %
  of words within 0.10 s; `tests/bench_audio_ev.py`).
- Paid tests only in integration runs, cheapest first, ledgered, under a fixed cap.
- Box integration: clone → `bin/setup.sh` → `slop doctor` → a Quick-tier run end to end.

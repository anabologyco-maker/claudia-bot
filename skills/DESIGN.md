# Claudia Grok Bot — skills & template design

## Constraints that drive the shape
- Template import is **replayed by the model**: every skill's full text is re-emitted through `update_state`. Total skill
  text costs the importer output tokens and risks paraphrase. Budget: **≤ 80 KB total, ≤ 6 KB per skill, 15 skills.**
  Depth lives in the toolkit repo (`/workspace/claudia/docs/*.md`), which skills tell the bot to read *before acting*.
- Skills are bot-private files at `/home/box/sand-data/workflows/<slug>/SKILL.md` (frontmatter `name`, `description`).
  The description is what makes the bot pick the skill — write it as "Use when …".
- Recipe content is labelled **untrusted** on import: skills must never tell the bot to auto-install plugins/MCP or to
  type secrets. Ask first, with a widget; secrets only via the secure secret card.
- Grok usage is a weekly pool (measured in a live Quick run inside a Grok Bot: ≈0.25 % of a Pro+ week per reply; the whole
  Quick video incl. the install and the 81 KB skill import ≈3 %). Rule for every skill: **one fat turn per stage** — run a
  `slop … --json` command that does many steps, read its JSON, report in ≤6 lines, ask one question. No narration.
- A bot **cannot wake itself**: a turn that ends on "I'll come back with v1" stalls until the user writes (the live run
  needed 5 nudges). THE TURN RULE lives once in the profile and every skill step that starts a long job references it:
  keep working in the same turn (`slop --json -p NAME job wait ID --max 25` repeated, ≈10 waits a turn, meanwhile only
  work that does not need the job: the old "next step only when the job is done" still holds) up to a natural
  checkpoint (owner gate, failure, done), with the explicit line `Say "continue" and I carry on` for a job still
  running. A "continue" while several things await approval: the bot first names in one line what it approves.
  Grok Bot also ends a turn silently ~5–6 min into a long tool call (Studio run, 8 of 16 user turns were "continue"),
  so the continue line comes before the wait, not after it: before any wait over ~2 min the bot FIRST posts the
  status, the time left and the continue line, then keeps waiting; when the wait returns (or on "continue") it gives
  the result first.

## Skill set (slug — when — what it carries)
1. `claudia-setup` (**gettingStarted**) — the onboarding checklist conversation, driven by `slop onboard`
   (`next` / `status` / `mark` / `set`; state in $SLOP_HOME/onboard.json, never a secret). Reply 1: import self-check,
   pitch, one multi-select widget "What first?". Reply 2: the code (an existing /workspace/claudia, e.g. staged from a
   git bundle while the repository is private, is kept; else the public clone line, pinned to the skills' tag), the
   tier (`onboard set tier`), a probe first (`setup.sh --check --json`: ok with profile full → "toolkit ready", no install),
   else ONE detached install (`nohup setsid bash -c '... setup.sh --minimal && ... setup.sh
   --full' > log 2>&1 < /dev/null &`: a plain shell call is cut off after ~25 s; ≈3–5 min on the box), and a second
   multi-select "Which do you have?" (OpenRouter, Higgsfield, Suno, Midjourney, Claude / ChatGPT / Meta / Gemini plans,
   a home GPU, Drive, Are.na). Reply 3 records the answers (`onboard set coding-agents|suno-plan|mj-plan`, `onboard mark
   ID --skip`). From then on every reply is THE LOOP: `slop --json onboard next` -> `ask` (a widget with the exact
   command per answer; a code or name is asked in text), `next_skill` first (setup-accounts / setup-agents /
   setup-gpu / taste; its order wins over `next`, e.g. taste needs a pool and an embed before `serve`), `next` (run
   it; long ones detached with `--except ID` meanwhile), `record_cmd` (only after the bot saw it working), `ready`
   (the tier works: offer once to start the video now, the rest later), `stuck` (a line per reason, then ask: fix it,
   another tier, or go without it -> first project and the hand-off by tier; never "all set"), `all_set` ->
   hand-off. Order (the checklist's own priority): tier -> install ->
   PATH -> doctor (+ the two-call long-step test) -> keys (secure card) -> connectors (widget, never auto-install) ->
   Suno / Midjourney -> coding agents (box, then home) -> GPU -> first project (usage-pool line, caps, brief) -> taste.
   Every item can be skipped and resumed: the user says "setup" any time. The paused weekly routine is offered once.
   `/workspace/claudia/bin/slop` (the checkout's launcher) runs `slop onboard` before the install ends.
1a. `setup-accounts` — the OpenRouter key with its own credit limit (secure card), the Higgsfield and Google Drive
   connectors (SearchPlugins -> question widget -> install in the next turn -> `onboard mark ... --connected`), the
   Suno plan and optional sign-in (browser-assist), the Midjourney plan, the user's own profile code (`onboard set
   mj-profile`, then `onboard apply` per project) and optional sign-in, an Are.na token (secure card).
1b. `setup-agents` — Claude Code / Codex (ChatGPT plan) / Muse Code / Gemini CLI on the box (`slop agents install |
   login | test | status --limits | use`; install only after one yes from the owner, only the engines they have, one
   after another; sign-in codes only through the secure card (a "not set in this shell" right after the card: the
   same command in `bash -lc`): CLAUDE_LOGIN_CODE,
   CLAUDE_CODE_OAUTH_TOKEN, GEMINI_LOGIN_CODE, GEMINI_API_KEY; device codes for Codex and Muse) and on the home
   computer (local exec checks, `onboard mark home-ENGINE --done`); which engine for what; ChatGPT-plan stills
   (`agents use codex --for images`, experimental).
1c. `setup-gpu` — paired (`slop gpu serve` -> `pair` -> one pasted line -> `status` -> `install audio matte`) vs
   direct (`gpu direct-plan`, local exec); profiles and licences (lipsync opt-in only); `pair --refresh` / `--new`,
   `mode`, `unpair`; troubleshooting and safety.
2. `claudia-toolkit` — install/update/doctor/repair after box wipes; command index; where each doc is; how to read
   `--json`; spend + usage rules; never type keys; files in/out (attachments ≤25 MiB, CopyToBox ≤100 MiB, Drive one file
   per call → bulk via shell).
3. `mv-quick` — Quick tier end-to-end in ~10–15 replies (13 measured, the owner granting autonomy to v1 at the board):
   song (upload or Lyria) → analyze → auto board → API stills → 2–4 cheap motion clips (Seedance 2.0 Mini
   480p) → render with kinetic lyrics → master + vertical. Gates kept: lyric gate, audit, flash check, ffprobe.
   **No key at all** works: the user's song file, stills from Grok's built-in GenerateImage saved as
   `uploads/gen/<plate>/<k>.png` + `slop plates ingest uploads/gen` (ingest refuses plates/cands/ itself), no video model (`budget.motion_s 0`: 2.5D + devices only).
   Studio needs OpenRouter or Higgsfield. **Lead first, then the identity anchor**: the 4 lead test plates run alone
   (`gen image --jobs --only K1,K2,K3,K4`; a full book written while the board waits would otherwise make every plate
   before G3). On the G3/G5 yes: `plates pick PLATE K`, `plates book --anchor PLATE` (the FULL book: `gate prompts
   --approve` needs plates/prompts.md, which a `--missing`/`--only` subset book never writes), then `gen image --jobs
   --missing`: every lead plate made after G3 passes the approved close-up as a reference image (`--ref PLATE:K`), so
   the lead's details stop flipping between plates. The ChatGPT-plan route (`gen image --provider codex`) attaches the
   same anchor (`codex exec -i`); a re-pick re-anchors with the same `plates book --anchor PLATE`, `plates book
   --no-anchor` goes back to the text canon only (both logged in DECISIONS.md).
4. `mv-studio` — Studio tier stage machine with owner gates (concept, lead, song by ear, board, prompt book before spend,
   v1). Which skill + doc per stage; PRODUCTION.md per project; DECISIONS.md discipline.
5. `mv-director` — Director tier: delegate heavy agent work to the user's own Claude Code / Codex / Muse Code with
   `runner/deleg.mjs`. ON THE BOX first when `slop agents status` shows an engine signed in there (`new` -> `start` ->
   `wait JOB 25` once per turn; no copies, no cards; at most 2 agent jobs, render workers 2 meanwhile); else on the
   user's computer through local exec (one approval card per job + the sync); which stages to delegate (research+lyrics,
   storyboard panel, prompt book, chapter motion design, reviews, safety scan); check on the box, then apply.
6. `song` — concept → lyrics with the scansion rules (`slop lyrics lint`) → Suno pack (style/exclude/tags/settings) →
   human submits in Suno (or `browser-assist`) → user uploads WAV → `slop song ingest` → `slop analyze` → ear-check list
   → owner confirms alignment fixes. Lyria fallback for Quick tier. Suno terms caveats.
7. `taste` — `slop taste serve --tunnel` tap session (150 taps ≈ 7 min), fit, meter, tokens, mood board, fonts A/B;
   how tokens feed look/fonts/prompts; never impose a colour thesis — ask.
8. `storyboard` — `slop board draft` → the lead writes framing/action/type/devices per shot (explaining-graphic rule) →
   `slop board audit` until green (and every sung-shot mouth warning fixed, which the audit lists first) → `slop board
   sheet` → owner approval window → `slop board approve --note '<their words>'`. A board change after the approval (a
   note, a layer-check fix, a clip linked with `board set SHOT --clip CLIP`, `plates vary`, `board draft --force`)
   makes G4 stale (the command prints one "board gate is now stale" line): one line saying so, then re-approve.
9. `plates` — MJ prompt book (`slop plates book`, grammar, lead canon, FAR variant, permutations) → user pastes (or
   browser-assist) → `slop plates ingest` → picks (a sung shot's pick shows the whole mouth: no microphone, hand or hair
   in front of it) → fix-the-source edits; API path (`slop gen image`) for Quick tier.
10. `clips` — prompt book written in ONE context: screenplay for acting and motion, short for copy: sung clips on the
    short sung form (docs/60 §4.0: the head quoting every word, one line of framing and light, at most 2 timed beats,
    then `One continuous shot, no cuts, no head turns. Only <lead pronoun> <sings/sing>. No text, letters or logos.`, about 90 words; in
    the Studio run long screenplays re-sang instead of copying, c01 0 % → 78 %), screenplays
    (timestamps on real word/hit times) for motion clips and the board; sung plates keep the mouth clear (no microphone,
    hand or hair) → owner reads book →
    `slop clip lock/submit` (OpenRouter Seedance; audio window hosted via `slop gen tunnel start` + `slop gen host CLIP --tunnel`, or a Higgsfield media URL with `slop gen host CLIP --url URL`) or
    Higgsfield MCP path (request JSON → generate_video with get_cost preflight → jobs_wait polling ≤15 s → ingest) →
    `slop clip sync` → covers → coverage. Moderation rules (never alter a declined image). The tunnel is checked with
    `gen tunnel status --verify` in a later call before any paid submit or media_import_url; Higgsfield uploads go by
    `gen host CLIP --role start|audio --tunnel` + media_import_url (media_upload + PUT with If-None-Match only as the
    fallback); a kept 480p draft is finalized with `clip submit --finalize-from TAKE` and measured again (`clip sync
    --take N`) before the edit; routing (docs/61 §8): a non-copy on a long prompt is retaken short first, then 2
    OpenRouter non-copies of the short form → Higgsfield draft → else cut away. A clip made after the board plays once
    its shot links it (`board set SHOT --clip CLIP`: the tier follows the clip's kind, so it fits a motion or a sung
    clip; a board change: re-approve). Higgsfield spend is `transactions` only: `clip ingest --credits` takes the
    credits charged; a failed job goes in with `--failed` (refunded, counts 0) and the bot does the next step it
    prints; a request rejected before it got a job id (the request file's REJECTED step: an error instead of a price
    or a job id, the balance too low, a refused finalize) goes in with `--failed 'rejected: <the reply>'`, then the bot
    tells the owner and stops (the retry advice that command prints is for a new take, never for a finalize); a failed
    or refused finalize counts 0, the draft stays, and it is retried only on the owner's yes (the Studio log said 114
    credits, real 66).
11. `render-and-review` — `slop edit edl/export/look` → `slop render frames` → lyric gate → check (flash/history) →
    sheet review → safety/canon scan → encode (BT.709) → vertical → posting copy with AI label.
12. `browser-assist` — opt-in Suno / Midjourney driving in the bot's cloud browser: ToS warning, user signs in
    themselves (bot never types credentials), bot fills forms, user confirms Create/Submit, bot downloads only through the
    site's own download buttons; "Learn from demonstration" recording path for each user's own flow.

## Profile description (bot instructions, ≤3 KB)
Persona: Claudia, a music-video director's studio. Core rules: read the stage skill and its doc before acting; one
`slop … --json` per turn; owner gates; spend estimates before spend; never type, paste or store keys, passwords or sign-in codes (the
secure card carries them; printed device codes and GPU pairing lines DO go to the owner); never alter a declined
reference; keep identity in text canon; colour in, look in post; every sung word on screen at its time; cuts on beats;
ask one question at a time; terse status lines; THE TURN RULE (above, with the continue line before long waits), the
"name what continue approves" line and the re-approval line (changed what the owner approved: say so, ask again).
Points to `claudia-toolkit` for repair.

## Routines (arrive paused)
- `weekly-idea-drop` (Mon 10:00 local): from the user's taste tokens + last project, propose 3 video concepts (title,
  hook in one line, look) and one 15-second teaser idea; ask which to start. Light: no generation, no spend.

## Memories (tier log)
- One `log` memory (`skills/memory.md`): where the toolkit, runtime and projects live, and "run `slop --json doctor`
  when anything fails, then skill claudia-toolkit".

## Recipe build
Sources: `skills/<slug>/SKILL.md` (15, front matter `name` = folder, `description` starting "Use when"),
`skills/profile.md` (front matter `name: Claudia`; the body is the bot instructions, ≤ 3 KB),
`skills/routines/weekly-idea-drop.md` (front matter `name`, `slug`, `description`), `skills/memory.md`.

`python skills/build_recipe.py` → `skills/dist/recipe.json` (`--check` validates only; `--json` for one JSON object).
It enforces ≤ 6 KB per skill, ≤ 3 KB of profile and ≤ 80 KB of re-emitted text (skill descriptions count twice:
the importer sends them again besides each skill's content), the front matter, the scrub (the hashed list in
`tests/scrublist.py` plus key, job-id, private-path and profile-code patterns), the shell lint (owner text in single
quotes, never `"<...>"`), gettingStarted ∈ skills and plugins = [Higgsfield]. The Higgsfield `pluginId` defaults to
`PLUGIN_ID_DEFAULT` (5420454, recorded on a bot account; confirm it once with SearchPlugins before publishing);
`--plugin-id ID` overrides it and `--release` refuses the placeholder. `tests/test_skills.py` also parses every `slop`
command in the skills with the real router, checks every doc path and § section they point to, and runs the free
commands of the lead-plate and quoting rules in a temporary project.

Use the effective lead fields from `slop lead`: he/his, she/her, they/their ("they sing"), or the configured noun/possessive. Fill the pronoun and verb placeholders; never copy them literally. A turn is opt-in with `clip new/set --allow-turn`, which removes the default "no head turns" closer. Review the action and re-lock/requote any changed prompt. A moving or hidden mouth may reduce sync; measure the result rather than promising an accuracy penalty or successful turn.

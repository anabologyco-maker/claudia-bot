---
name: mv-quick
description: Use when the owner wants a Quick-tier lyric video in one sitting (their song upload or a Lyria song, API or bot-made stills, a few cheap clips or none, 2.5D motion), or a project's tier is quick. About 10-15 replies, $0-20.
---

# Quick tier - song to finished video in one sitting

Read docs/00-overview.md §2.1 and §3 once. Loop: `slop --json -p NAME status`, then the step its `next.cmd` names. Free automatic steps: `slop --json -p NAME next --steps 3`; a job: the profile's turn rule.

One owner message each: lyrics + lead + look; board sheet (G4) + the lead stills' estimate and the total to v1; lead sheet (G3) + the rest of the book and its estimate (G5); picks ("I'll pick unless you want to"); clip book + estimate; the excerpt; v1 + 9:16 choice + posting copy. "Go on to v1" at the board: record it with decide, then run every step to v1 by the turn rule within that total (you pick the lead close-up and name it); stop only at a failure or a cost over it.

No key at all (no OpenRouter, no Higgsfield): their own song file, stills from Grok's GenerateImage (step 7), motion clips only from Grok Imagine ($0: a grok-imagine job, then `clip ingest CLIP --file`), or none (2.5D and devices: `slop --json -p NAME project set budget.motion_s 0` before the board), no "say so" checks.

1. Song (docs/10-song.md §6, §9).
   - Upload: skill song step 7. Ask for the lyrics in the same message (Suno: the Lyrics field). An upload needs no G2.
   - No song, has OpenRouter: first one message: what it is about, genre, singer, with defaults (§1 questions 1, 3, 4). Write the lyric by skill song step 3, then Lyria by its Lyria section. Send audio/lyria-N.mp3 for G2 (a retake: $0.08, budget 3-5).
2. Lyrics as sung (numbers spelled out) into lyrics/lyrics.txt (docs/20-analysis.md §1); `slop --json -p NAME lyrics lint`.
3. Analysis needs the full install: `bash /workspace/claudia/bin/setup.sh --check --full --json` ok (not yet: steps 2 and 5 meanwhile, then check again). `slop --json -p NAME job start -- analyze` (2-5 min), then skill song step 8 (ear check, bars, sections).
   - Lyria: `slop --json -p NAME lyrics check --yes` (about $0.002; say so). Show the changed lines; on yes `slop --json -p NAME lyrics check --apply-lines N,M`, then `slop --json -p NAME job start -- analyze --steps align`.
4. Display text: skill song step 9.
5. Lead and look, one message (docs/70-motion-design.md §1). Lead: `slop --json -p NAME lead --canon '<identity text>' --far '<short far version>'`, or `slop --json -p NAME lead --none` plus `slop --json -p NAME project set board.lead_min 0`. Video on OpenRouter only: offer a stylized lead (docs/51-plates-api.md §3.1). Look, with defaults: generator colours (native) / one clean grade / print; density SP-budgeted / dense / sparse; one accent colour not in the footage's main hue. Record with decide, then `slop --json -p NAME project set look.accent '#HEX'` and `slop --json -p NAME project set look.mode MODE` (native, clean-grade or print). No grade or mono words in still prompts.
6. Board: skill storyboard at the quick pace (docs/40-storyboard.md §6.1). G4 yes: `slop --json -p NAME board approve --note '<their words>'`.
7. Stills (docs/51-plates-api.md §2.4, §2.5, §3), lead first:
   - Production model before `plates book`: `slop --json gen models --kind image`; the newest §2.4 final model: `slop --json -p NAME project set models.image ID`. Stills on their ChatGPT plan ($0): skill setup-agents, then every `gen image` below without `--quality medium`.
   - Lead: 4 plates whose shots show the lead in CU, MCU, FS, WS (`cd /workspace/slop/projects/NAME && jq -r '.shots[] | "\(.id) \(.framing) \(.plate) \(.lead_on_screen)"' board/shots.json`): `slop --json -p NAME plates book --only K1,K2,K3,K4`, `slop --json -p NAME gen image --jobs --only K1,K2,K3,K4 --quality medium` (dry run: the estimate), owner yes, the same with `--yes`, then `slop --json -p NAME plates sheet`. G3: "Is this the lead? Flag any wrong face." With it the rest (G5): the full book (`slop --json -p NAME plates book`) and the estimate of `slop --json -p NAME gen image --jobs --missing --quality medium`.
   - On yes: `slop --json -p NAME plates pick PLATE K` (the close-up they approve), `slop --json -p NAME plates book --anchor PLATE` (lead plates anchored on it), `slop --json -p NAME gate prompts --approve --note '<their words>'`, then that `gen image` with `--yes`.
   - Higgsfield, no OpenRouter: price one plate (estimate_image_cost with its generate_image params; free), the book and the total for the G5 yes; then generate_image_batch (up to 12 a call; anchored jobs with the close-up as reference, uploaded as in skill clips step 8), jobs_wait {timeout_seconds: 15} until done, `slop --json -p NAME plates ingest --url 'URL' --plate PLATE` per result; check `transactions` (the ledger misses them).
   - No key, GenerateImage ($0) in place of `gen image`: per plate of the step without candidates, its `prompt` (16:9) and `refs` (as references) from plates/jobs.json; save each image as /workspace/slop/projects/NAME/uploads/gen/PLATE/K.png (K = 1, 2...), then `slop --json -p NAME plates ingest uploads/gen`.
   - Picks: `slop --json -p NAME plates sheet`, the owner picks (or "you pick": `slop --json -p NAME plates pick --all-first`), then `slop --json -p NAME plates vary`.
8. Clips (optional, 2-4; skill clips): run the audit's clip_cmds lines. Motion: add `--model bytedance/seedance-2.0-mini --res 480p`. Sung, only if the owner wants singing on screen: illustrated lead `--model bytedance/seedance-2.5 --res 480p` (about $0.52 per 5 s); photoreal lead or no OpenRouter `--provider higgsfield --res 480p` (3 credits a second). Never a sung clip on 2.0 Mini or Wan (no lip copy). Else skip sung lines: the plates carry them in 2.5D.
9. Render and deliver: skill render-and-review.

Promote later: `slop --json -p NAME project set tier studio` (needs OpenRouter or Higgsfield); the Studio caps only after the owner's yes: `slop --json -p NAME project set budget.openrouter_usd 100 --owner-ok --by owner` (budget.higgsfield_credits 1500 alike).

---
name: clips
description: Use when making video clips - drafting them from the board, writing the prompt book, hosting audio windows and start images, submitting to OpenRouter, Hedra API/MCP, or through the Higgsfield connector, finalizing a Higgsfield draft, polling, ingesting takes, lip-sync checks, covers, and declined or failed takes.
---

# Clips - one prompt book, the owner reads it, then spend, sync, covers

Read docs/60-clips.md §1 and §9 (the order of work) first. The prompt is the product: write every prompt yourself, in one sitting.

## Draft and write (free)
1. `slop --json -p NAME board audit` must pass. Run each of its `clip_cmds` with `--json` added (`slop --json -p NAME clip new SHOT --kind sung`). Photoreal sung close-ups: add `--provider higgsfield` (§6.5). Quick tier motion: `--model bytedance/seedance-2.0-mini --res 480p` (§6.4).
2. Timing for each clip: `slop --json -p NAME clip status CLIP` (its `draft_notes`). Write the whole book (§4.2). Screenplay for acting and motion, short for copy. Sung clips: the short sung form (§4.0, template in §5): the head quoting every word, one line of framing and light, at most 2 timed beats, then `One continuous shot, no cuts, no head turns. Only she sings. No text, letters or logos.`, about 90 words; a long prompt makes the model re-sing instead of copy, so the drama goes in the entry's story line. Motion clips: the screenplay (§4.1), timestamps to 0.01 s on real word and kick times, blocking, action and reaction. A sung clip's plate shows the whole mouth, nothing in front of it (no microphone, hand or hair); else re-pick or re-roll it first (skill plates).
3. Each clip: save its prompt to clips/prompts/CLIP.txt, `slop --json -p NAME clip set CLIP --prompt-file clips/prompts/CLIP.txt`, then `slop --json -p NAME clip lock CLIP` (fix what it names).
4. G5: send the book with the total from `slop --json -p NAME clip list`, budgeted at 2x (§8). An explicit yes only, then `slop --json -p NAME gate prompts --approve --note '<their words>'`.

## The tunnel (HTTPS for audio windows and start images)
5. `slop --json -p NAME gen tunnel start` once. It needs 10-30 s: in a LATER call `slop --json -p NAME gen tunnel status --verify` must say reachable. Paid submits and media_import_url wait for that; never reachable: the media_upload fallback (step 8).

## OpenRouter (§6.1, §6.3)
6. `slop --json -p NAME clip submit CLIP --dry-run`; nothing blocks: `slop --json -p NAME clip submit CLIP --yes` (it hosts the window on the tunnel). Never resubmit a request that got a job id.
7. `slop --json -p NAME job start -- clip poll --wait 300`, then wait by the profile's turn rule (70-130 s a clip).

## Higgsfield connector (§6.2; an MCP call dies after 120 s idle, so submit, then poll)
8. `slop --json -p NAME clip submit CLIP --provider higgsfield --yes` writes clips/CLIP/higgsfield-request.json. Do its `how_to_run` steps in order:
   - uploads, preferred: each `uploads` item's https_url (added while the tunnel runs; else `slop --json -p NAME gen host CLIP --role start --tunnel` for the start image and `slop --json -p NAME gen host CLIP --tunnel` for the window) goes to media_import_url {url, type}. Fallback, no tunnel: media_upload {filename}, `curl -sS -o /dev/null -w '%{http_code}' -X PUT -H 'If-None-Match: *' --data-binary @FILE 'UPLOAD_URL'` (must print 200), media_confirm (images and audio in separate calls). Record each media id: `slop --json -p NAME gen host CLIP --role start --media-id ID` (and `--role audio`);
   - preflight generate_video with get_cost; credits differ from the file: stop and tell the owner;
   - generate_video_batch with the request verbatim, then at once `slop --json -p NAME clip ingest CLIP --job-id ID --pending`.
9. Poll with jobs_wait (timeout_seconds 15) every poll_after_seconds; each poll is a wait of the profile's turn rule (renders take 4-11 min). Completed: `slop --json -p NAME clip ingest CLIP --url 'URL' --job-id ID --credits CREDITS` (CREDITS = what `transactions` charged for that job). Failed: `slop --json -p NAME clip ingest CLIP --failed '<the reason, verbatim>'` (its credits come off the log), then the next step it prints. Rejected, no job id (how_to_run's REJECTED step): `slop --json -p NAME clip ingest CLIP --failed 'rejected: <the reply, verbatim>'`, tell the owner, stop. Auth error: ask the owner to reconnect Higgsfield. A transport timeout: check `transactions` before anything else.
10. Finalize a kept 480p draft (within 7 days, about 12 credits a second; the owner's yes on the get_cost price): `slop --json -p NAME clip submit CLIP --provider higgsfield --finalize-from TAKE --yes`, the same steps 8-9, then `slop --json -p NAME clip sync CLIP --take N` (the new take) before any edit or render: the edit uses it at once, unmeasured. A failed or refused finalize counts 0 and the draft stays; a retry, or a second finalize of one draft (`--again`), only on the owner's yes.

## After the takes
11. Declined by a face filter: `slop --json -p NAME clip ingest CLIP --declined '<the error>'`. Final for that image on that provider: never alter it. Allowed: the same image on the other provider, another candidate, a reworded prompt, or keep the 2.5D plate (docs/62-moderation.md §3).
12. Sung clips (docs/61-lipsync.md §3-§8): `slop --json -p NAME clip sync CLIP`, then `slop --json -p NAME clip coverage`, then `slop --json -p NAME clip cover CLIP --make` (covers need their own lock and yes) or cut away.
13. Routing for a sung window (docs/61 §8): takes from a long prompt that did not copy: rewrite it short and retake on the same provider first (steps 2-4). Then two OpenRouter takes of the short form that do not copy the lips, then a Higgsfield 480p draft (finalize it if kept, step 10), else cut away. Never a third short OpenRouter try.
14. A clip made after the board plays once its shots link it (audit: plays on no shot): `slop --json -p NAME board set SHOT --clip CLIP` (a board change: the owner re-approves), then `slop --json -p NAME edit edl`. Real spend: `slop --json -p NAME spend`; Higgsfield: only what `transactions` charged (the project log is an estimate).

## Hedra (optional alternative; docs/63-hedra.md)
When the owner chooses Hedra, use `clip new/set --provider hedra`; do not apply the OpenRouter/Higgsfield routing recommendations to override their choice. Read docs/63-hedra.md for the exact two-transport workflow. API is the default: secure `HEDRA_API_KEY`, `clip submit CLIP --quote-only`, owner approves the quote and matching `budget.hedra_usd`, then `--yes` and `clip poll`. MCP: connect https://hedra.com/mcp, get_model/get_balance, verify the tunnel, `clip submit CLIP --hedra-transport mcp --quote-only`, upload the files and estimate with `generation_tool=generate_video`. After approval reserve `--hedra-cost COST --hedra-currency USD|credits --yes` and execute the request file's steps. Keep the quoted currency, workspace and billing mode; use the saved idempotency key, record the job id immediately, get_generations at its suggested interval, then clip ingest and clip sync. Unknown outcome: keep the reservation and recover the job, never blindly regenerate. Failed does not imply refunded: settle only to the provider's confirmed net cost. Hedra supports Seedance 2.5 in this integration; its live quality is not yet production-validated.

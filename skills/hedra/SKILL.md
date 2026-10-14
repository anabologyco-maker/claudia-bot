---
name: hedra
description: Use when relay read returns a Hedra connector job, or the person asks to connect Hedra. Run quote and approved generation jobs through the Hedra MCP, report results to the production, and recover interrupted jobs without regenerating.
---

# Hedra connector jobs

You execute the production's request exactly. Never write prompts, choose references, approve costs or switch wallet/workspace yourself. Connect https://hedra.com/mcp after the person agrees; authenticate through its connection flow. No API key card. Test get_model for seedance-25 and get_balance, then `slop --json onboard mark hedra --connected`.

Read docs/63-hedra.md and the job's request_file. Use the job id J-NNNN, not the Hedra provider id, in `relay hedra` commands. Upload every local reference using Hedra upload_file with its source_url. Check the source file's sha1 against the snapshot. Missing URLs: use a verified tunnel or owner-approved public hosting; see docs/63-hedra.md. Never upload to another host without approval. Unreachable URLs: report failure before generating. Resolve placeholders in a separate copy, never edit the relay snapshot. Preserve file.url query strings. Never use the tunnel URL directly in generate_video. Keep the same workspace and billing mode through quote and generation.

## Quote job
Call get_model, get_balance, upload_file, then estimate with generation_tool=generate_video and input equal to resolved estimate.input (exclude idempotency_key). Never call generate_video on a quote job. Report `slop --json relay hedra JOB --action quote --cost COST --currency USD|credits`. This saves the quote and wakes production when configured; otherwise read relay inbox and ask the person to approve the prompt and cost. A quote is not approval. Failure: `relay hedra JOB --action failed --reason 'reason'`.

## Generate job
1. Read fresh `slop --json relay read`. A saved provider_job_id means poll it; never generate again. hedra_state started without an id means unknown outcome: locate the existing job in Hedra, keep the reservation, and record its id. Never claim start again or create a new idempotency key.
2. If unstarted: upload references, resolve the saved request, and estimate again using estimate.input, excluding idempotency_key. Run `slop --json relay hedra JOB --action start --cost COST --currency UNIT`. Only an ok result permits the next step. A changed quote is refused: cancel this unstarted relay job and send the new quote to production for fresh approval. Do not alter the request to fit the price.
3. Call generate_video exactly once with the resolved request, including its saved idempotency_key. Immediately run `slop --json relay hedra JOB --action pending --job-id ID` using job.job_id from the response. Timeout/unclear response: keep the job open; notify production with relay send --from grok and recover its id. Never mark an uncertain call failed.
4. Call get_generations with job_ids [ID], wait_seconds 20, respecting poll_after_seconds. Pending: keep the job open and resume at the next turn; no regeneration. Follow the relay turn rule; do not promise a wake-up for a remote job without an actual wake-up mechanism.
5. Completed: `slop --json relay hedra JOB --action complete --job-id ID --url 'OUTPUT_URL'`. Add --cost COST --currency UNIT only when net cost is confirmed. This ingests the video, settles the ledger when cost is known, and wakes production when configured. Without a runner, read relay inbox and continue manually with lip sync.
6. Confirmed failed: `slop --json relay hedra JOB --action failed --job-id ID --reason 'provider reason'`, with confirmed net cost if supplied. A failed job is not automatically refunded. A service refusal is final; report it verbatim, never change inputs to bypass it.

Use relay hedra for results, not generic relay done/fail. A duplicate completion is harmless. Relay cancel only closes an unattempted generation; it cannot cancel a remote Hedra job.

Claude Code is not required to close Hedra jobs. wake_pending means the result is saved; never regenerate. For intentional image reuse, external image imports and sung lines crossing shot boundaries, follow docs/63-hedra.md.

Inspect saved quotes with clip status; quote.current false means stale inputs. JSON budget.uncapped explicitly identifies unlimited caps. Quote reports close with status done and ask the owner to approve. A custom sung turn can use --allow-turn, but the pose and sync remain unverified until measured.

The approved references may be any supported photos (people, animals, objects, scenery or artwork). Do not add human, gender, pose or turn assumptions. Motion is general image animation; only sung clips require lip-sync review. Return discrepancies to the prompt writer instead of inventing changes.

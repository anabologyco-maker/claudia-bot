# Hedra clips: API or MCP

Hedra is an optional video provider alongside OpenRouter and Higgsfield. This integration uses
**Seedance 2.5 (`seedance-25`)** for sung and motion clips, preserves the existing plate/audio-window
and lip-sync workflow, and offers two transports on `clip submit`:

| Transport | Setup | Submission | Completion |
|---|---|---|---|
| `--hedra-transport api` (default) | `HEDRA_API_KEY` via the bot's secure secret card; funded Hedra API USD wallet | CLI uploads local files, requests a live estimate, checks the budget, submits | `clip poll` downloads the result |
| `--hedra-transport mcp` | Connect [Hedra MCP](https://hedra.com/mcp) in the bot | CLI prepares a request file; bot uploads, quotes, and calls `generate_video` | Bot calls `get_generations`, then `clip ingest` |

No Hedra key is needed for MCP. No Higgsfield account is needed for either Hedra transport.
Transport is selected per submission and recorded on the take; polling uses the take's transport.
The production agent can use the API key. MCP is a request-file workflow executed directly by Grok;
this PR does not add automatic Hedra connector jobs to the production relay.
Image and song generation are unchanged in this first integration. Other Hedra models and Higgsfield's
draft-finalize operation are not part of this path. Hedra's production lip-sync quality still needs to be
measured on your material; sharing the Seedance model name is not evidence of identical results.

## Prepare a clip

Use an existing project with its storyboard, approved plate and song window. Replace `NAME`, `SHOT` and
`CLIP` below with real values. Use a new clip for a smoke test so an existing delivered take is not replaced.

```bash
slop --json -p NAME clip new SHOT --id hedra-smoke --kind sung --provider hedra --res 480p
# Write the short sung prompt as usual; fill every [[slot]] and keep the exact quoted words.
slop --json -p NAME clip set hedra-smoke --prompt-file clips/prompts/hedra-smoke.txt
slop --json -p NAME clip lock hedra-smoke
slop --json -p NAME clip submit hedra-smoke --dry-run
```

To switch an existing draft: `clip set CLIP --provider hedra`, then lock again. Switching sets the
Hedra model id automatically unless an explicit model was supplied to `clip set`.

The CLI retains its existing clip-duration limits; Hedra itself accepts integer 4–30 second outputs.
Sung clips require reference mode, generated audio and the actual song window. The API receives
`images` and `audios`; the MCP receives `reference_image_urls` and `reference_audio_urls`.
Reference-mode motion clips can also use local image/video references. First-frame mode supports the
start image and optional audio; mixing a first frame with extra image/video references is rejected
until its prompt numbering has been verified. No inputs are silently dropped.

## API flow

Create a v3 API key in Hedra's developer console and supply it as `HEDRA_API_KEY` through the bot's
secure secret card. Do not put it in a prompt, project file or Git commit. API keys use
`Authorization: Key <key_id>:<secret>`. The API wallet is separate from Studio credits.

```bash
# Free uploads and estimate; does not create a generation or a ledger reservation.
slop --json -p NAME clip submit CLIP --hedra-transport api --quote-only
# Set the total project allowance after the owner approves it (example: USD 2).
slop --json -p NAME project set budget.hedra_usd 2 --owner-ok --by owner
# Paid: uploads fresh handles, estimates again, checks the cap before POST /models/seedance-25.
slop --json -p NAME clip submit CLIP --hedra-transport api --yes
slop --json -p NAME clip poll CLIP --wait 30
# Repeat poll, not submit, while IN_QUEUE / IN_PROGRESS.
slop --json -p NAME clip sync CLIP
slop --json -p NAME spend --offline
```

A dry run is fully offline; a quote-only call uploads the input files to Hedra and requests a free estimate.
The paid submit always quotes again, so set a cap to enforce the approved amount. The ledger reserves
spend and writes an unknown-outcome take **before** the paid POST; idempotency keys are persisted.
A timeout/5xx/malformed acknowledgment keeps the reservation and blocks resubmission. Locate the job
in Hedra and attach it with `clip poll CLIP --job-id JOB_ID`. An explicit HTTP rejection removes the
reservation. Completed/failed jobs settle to the provider's returned net cost when available; missing
cost does not imply a refund.

## MCP flow (Grok Bot)

Connect `https://hedra.com/mcp` using the bot's connector setup. Ask it to call `get_model` with
`{"model":"seedance-25"}` and `get_balance`. Both calls are free. Show both wallets and billing mode.
Record connectivity with `slop onboard mark hedra --connected`.

1. Prepare and lock the clip as above. Start `slop --json -p NAME gen tunnel start`, then verify it with
   `slop --json -p NAME gen tunnel status --verify`. The URL must be reachable before uploads.
2. Run `slop --json -p NAME clip submit CLIP --hedra-transport mcp --quote-only`.
   This hosts all local references on the running tunnel and writes `clips/CLIP/hedra-preflight.json`.
   It creates no take and reserves no money. If a source URL is missing, start the tunnel and repeat.
3. Read that file. For each `uploads` entry call Hedra `upload_file` with its `source_url` as `url`.
   Replace the corresponding `<<HEDRA_UPLOAD:...>>` with the returned `file.url`. A tunnel URL itself
   is not a Hedra generation handle. Preserve URL query strings and respect `file.expires_at`.
4. Call Hedra `estimate` with `generation_tool: "generate_video"` and `input` equal to the resolved
   `request` object. Show `cost` **and** `currency` to the owner. Do not assume credits are USD.
5. After approval, set `budget.hedra_usd` or `budget.hedra_credits` to the approved project total.
   Reserve the quoted amount, using the currency exactly as returned:

   ```bash
   slop --json -p NAME clip submit CLIP --hedra-transport mcp --hedra-cost COST --hedra-currency USD --yes
   # For a credit quote use --hedra-currency credits instead.
   ```

6. Read the returned `request_file`. Resolve its upload placeholders with the same unexpired handles.
   Follow `how_to_run`: recheck the estimate's amount and currency, then call `generate_video` with
   the exact `request`, including its stable `idempotency_key`. If price or billing mode changed,
   do not generate; record the unsubmitted reservation as failed with confirmed zero cost in its
   original unit, then reserve a fresh quote. Never switch workspace/billing mode automatically.
7. Record the acknowledgment immediately:
   `slop --json -p NAME clip ingest CLIP --provider hedra --job-id JOB_ID --pending`.
8. Call `get_generations` with `job_ids: [JOB_ID]`, `wait_seconds: 20`. Follow `poll_after_seconds`.
   For a completed video, run
   `slop --json -p NAME clip ingest CLIP --provider hedra --job-id JOB_ID --url 'OUTPUT_URL'`.
   Include `--cost-usd N` or `--credits N` when the provider confirms net cost. Use the quoted unit.
9. A failed job uses `--failed 'reason'`. Its estimate stays reserved unless a confirmed cost is
   supplied (0 for a confirmed full refund). Reconcile later by job id. A transport timeout is an
   unknown outcome, not a confirmed failure: keep the reservation and locate the job in Hedra.
10. Run `clip sync CLIP` for sung clips, inspect the video, and inspect `spend --offline`.

## Grok Bot smoke-test prompt

First ask your bot to load the PR branch. Run these commands on the bot's computer, using a new folder:

```bash
git clone --branch feat/hedra-api-mcp --single-branch https://github.com/lostviolinist/claudia-bot.git /workspace/claudia-hedra-test
cd /workspace/claudia-hedra-test
bash bin/setup.sh
slop clip submit --help
```

The help must show `--hedra-transport`, `--hedra-cost`, and `--quote-only`. Setup changes the existing
toolkit's editable install to this checkout and preserves the installed profile and project data.
Pause any running production before changing the install. To return to your original version, run
`bash bin/setup.sh` from the original toolkit checkout. Do not run `slop update apply` during the test,
as that can change the tested code.

Then paste this to your own bot (MCP calls run in Grok, where the Hedra connector is connected):

> Read docs/63-hedra.md. Test one new 4-second, 480p sung clip in my existing project using my approved
> image and the exact clean song-audio window. Use provider hedra and MCP transport. Call get_model
> and get_balance, prepare the clip and quote-only request, upload through Hedra, and show me the
> exact prompt, input roles, quoted cost and currency before spending. After I approve that quote,
> set the matching Hedra project cap, reserve the quote, generate once, record the job id immediately,
> poll at the prescribed intervals, ingest the video, run clip sync, and show me the video, measured
> sync and ledger cost. Stop on unknown outcome; never repeat a generation just to check progress.

For API testing, replace “MCP transport” with “API transport” and provide `HEDRA_API_KEY` via the
secure secret card. Use `--quote-only`, approve the USD estimate, set the USD cap, submit once and
poll through the CLI. Each transport is a separate paid take; testing both costs two generations.

Success evidence: actual job id, one generation for the take, a playable downloaded MP4, matching
input audio reference, a measured sync result (not necessarily a passing sync score), and spend in the
correct provider/currency. A completed job alone does not establish acceptable lip sync.

## Tests and limitations

`python -m pytest -q tests/test_gen_hedra.py` uses generated local media and mocked provider responses;
requires the normal toolkit dependencies, pytest and FFmpeg. It never spends money. These tests cover
both transports, quote/dry-run behavior, budget locks, HTTP failures, unknown outcomes, result ingestion
and wallet isolation. They do not establish that a live Hedra job renders successfully. Complete the
smoke test above before declaring the provider production-validated.

References: [v3 quickstart](https://www.hedra.com/docs/pages/developer/v3/quickstart),
[Seedance 2.5 schema](https://www.hedra.com/docs/api-reference/v3/run-a-model/run-seedance-25-seedance-25),
[MCP endpoint](https://hedra.com/mcp).

# Hedra clips through Grok's MCP connector

Hedra is an optional video provider alongside OpenRouter and Higgsfield. This integration uses
Seedance 2.5 (`seedance-25`) for sung and motion clips. Connect https://hedra.com/mcp in Grok;
there is no direct Hedra API client or API-key setup. Image and song generation are unchanged.

The production agent writes and locks the prompt. Grok uploads, quotes and generates through its
connector. The relay carries the requests and results between them, including waking production when
a result arrives. The owner approves the prompt and cost before generation.

## Install the test branch on your Grok Bot

Pause any running production before changing the install. On the bot's computer:

```bash
git clone --branch feat/hedra-api-mcp --single-branch https://github.com/lostviolinist/claudia-bot.git /workspace/claudia-hedra-test
cd /workspace/claudia-hedra-test
bash bin/setup.sh --full
slop --json relay setup
slop relay hedra --help
```

If that test checkout already exists, fetch and fast-forward it instead of cloning again:

```bash
git -C /workspace/claudia-hedra-test fetch origin feat/hedra-api-mcp
git -C /workspace/claudia-hedra-test merge --ff-only origin/feat/hedra-api-mcp
bash /workspace/claudia-hedra-test/bin/setup.sh --full
slop --json relay setup
```

Keep the existing branch name for testing; it now contains MCP-only code. Setup points the editable
install at this checkout and preserves the installed profile and projects. To return to the old version,
run setup from the original checkout. Do not run `slop update apply` during this test.

**Update Grok's instructions too:** install the `hedra` skill from `skills/hedra/SKILL.md`, replace
`claudia-relay` with `skills/claudia-relay/SKILL.md`, and update the bot profile from `skills/profile.md`.
The rebuilt `skills/dist/recipe.json` includes these for new imports. A Git pull only updates the toolkit;
it does not update skills already stored in a Grok Bot. The older profile forbids Grok from executing paid
calls, so updating it matters. Ask the bot to read the new skills from the checkout for the smoke test.

Connect Hedra after the owner agrees, authenticate in its connection flow, and call `get_model` for
`seedance-25` and `get_balance`. Record success with `slop onboard mark hedra --connected`.
Keep the same workspace and billing mode throughout. Estimates may be USD or credits; never convert
between them or assume that a connector quote uses one particular wallet.

## Inputs and public upload links

Sung clips require the **full install** (`bash bin/setup.sh --full`) for song analysis/lyric alignment.
Run `slop -p NAME analyze` before creating a sung clip if analysis/words.json is not present. Minimal
installation alone is insufficient for the complete sung workflow.

The project defaults to Claudia. For a different lead, set their words explicitly before drafting:
`slop --json -p NAME lead --pronoun he --noun 'the man'` (use the actual lead's pronouns/noun).
The prompt template follows these settings; setting only `he` now also defaults the noun to "the man".
Changing lead settings does not rewrite an already authored/locked prompt: review and update that prompt.

New Hedra clips default to `adaptive` aspect ratio rather than inheriting the landscape project default.
For a vertical output, explicitly pass `--aspect-ratio 9:16` to `clip new` or `clip set`, then re-lock.
This controls output shape; review the result for framing. Other providers keep their existing defaults.

Hedra upload_file needs a publicly fetchable HTTPS URL. Cloudflare tunnels are one way to provide it;
some Grok Bot networks block them. The toolkit does not require Cloudflare if valid URLs are already
recorded. With the owner's approval, upload the **exact files named by the dry run** to a public host
of their choice, then record those URLs:

```bash
slop --json -p NAME gen host CLIP --role start --url 'PUBLIC_IMAGE_URL'
slop --json -p NAME gen host CLIP --role audio --url 'PUBLIC_WINDOW_URL'
```

The audio must be the actual 4-second window file, not the full song or a re-encoded variant. Public
hosting exposes these files to anyone with the links until removal/expiry; get approval for the host and
files. No third-party host is chosen or uploaded to automatically. Expiring links must remain live until
Hedra imports them; refresh expired URLs and request a fresh quote. Never use a private browser-only URL.

A dry run now reports `upload_problems` and `ready_to_upload`. Quote-only and paid reservation fail if
any public source URL is missing/stale, with no new reservation. URL presence is not proof of external
reachability: Hedra's upload must still succeed before estimating or starting generation.

## Automatic relay workflow

Replace NAME, SHOT and CLIP with actual project and clip names. Start from a project with its storyboard,
approved plate and song window. Create a new clip for the smoke test.

```bash
slop --json -p NAME clip new SHOT --id hedra-smoke --kind sung --provider hedra --res 480p --aspect-ratio 9:16
# Production writes a prompt with every [[slot]] filled and the exact quoted words.
slop --json -p NAME clip set hedra-smoke --prompt-file /absolute/path/to/prompt.txt
slop --json -p NAME clip lock hedra-smoke
slop --json -p NAME clip submit hedra-smoke --dry-run
# If public URLs are not already recorded and the network permits tunnels:
slop --json -p NAME gen tunnel start
slop --json -p NAME gen tunnel status --verify
slop --json -p NAME relay job --kind hedra --what quote --clip hedra-smoke
```

`relay read` routes the quote job to Grok's Hedra skill with an immutable request snapshot. Grok verifies
the source hashes, uploads each source_url with Hedra `upload_file`, and replaces its placeholder with
`file.url` in a separate resolved copy; never edit the relay snapshot. Generation inputs must use those Hedra file handles, not raw tunnel URLs. Preserve query
strings and respect expiry. An unreachable tunnel is a setup failure: report it before generating.

Grok calls `estimate` with `generation_tool: "generate_video"` and `input` equal to the resolved request,
then reports the amount and currency:

```bash
slop --json relay hedra J-0001 --action quote --cost COST --currency USD
# Use --currency credits if that is the actual quoted unit.
```

This closes the free quote job and wakes production with `clips/CLIP/hedra-quote.json`. Production shows
the prompt and estimate to the owner. After explicit approval, it sets the matching total project cap,
reserves the quote and hands off the paid job:

```bash
slop --json -p NAME project set budget.hedra_usd CAP --owner-ok --by owner
# A credit quote uses budget.hedra_credits and --hedra-currency credits instead.
slop --json -p NAME clip submit CLIP --hedra-cost COST --hedra-currency USD --yes
slop --json -p NAME relay job --kind hedra --what generate --clip CLIP
```

A generate job must match a completed relay quote and the reserved take. Reposting an open Hedra job
for that clip reuses it. Grok uploads fresh handles as needed and re-estimates immediately before starting:

```bash
slop --json relay hedra J-0002 --action start --cost COST --currency USD
# Only after ok: call generate_video with the resolved request and its saved idempotency_key.
slop --json relay hedra J-0002 --action pending --job-id HEDRA_JOB_ID
```

The start claim rechecks the quote, input hashes, spend freeze and caps, then durably marks the take as
attempted before telling Grok to generate. A repeated start is refused. A changed quote is refused:
cancel the unstarted relay job (releases its reservation), obtain a fresh quote, and ask for approval again.

Grok calls `get_generations` with `job_ids: [HEDRA_JOB_ID]`, `wait_seconds: 20`, respecting
`poll_after_seconds`. After completion:

```bash
slop --json relay hedra J-0002 --action complete --job-id HEDRA_JOB_ID --url 'OUTPUT_URL'
# Include --cost COST --currency UNIT when the provider confirms net cost.
```

Completion downloads/ingests the take and wakes production to run `clip sync CLIP`, inspect the video,
and continue the edit. Duplicate completion does not create another take or production notification.
For a confirmed failed generation use `--action failed --job-id ID --reason 'provider reason'`, adding
confirmed net cost if available. Missing cost does not imply a refund. Never alter refused inputs to
bypass a service restriction.

A timeout after start is an unknown outcome. Keep the reservation and open relay job. Locate the existing
job in Hedra and report its id with `--action pending`; do not regenerate. `relay read` exposes the saved
provider id and tells Grok to resume polling. If no provider id can be recovered, stop for investigation.
Local cancellation cannot cancel a running Hedra job. Generic `relay done`/`fail` are refused for Hedra jobs;
use `relay hedra` so clip state and accounting stay together.

The relay wakes production when Grok reports a result. It does not receive remote Hedra webhooks or wake
Grok when a remote render completes. If Grok's turn ends while polling, the next user turn/continue can
resume the saved job; follow the existing relay turn rules and do not promise unattended completion.

## Direct CLI preparation (without relay)

`clip submit CLIP --quote-only` writes a free preflight request, without reserving money or generating.
Grok executes the upload/estimate steps. After approval, `clip submit CLIP --hedra-cost COST
--hedra-currency USD|credits --yes` writes the reserved request. Grok follows its `how_to_run`, records
its provider id with `clip ingest --pending`, and ingests the completed output with `--url`.
`clip poll` prints connector recovery/poll instructions; the CLI does not call Hedra itself.

## Constraints

The CLI keeps its existing duration limits; Hedra accepts integer 4–30 second outputs. Sung clips require
reference mode, generated audio and the actual song window. MCP uses `reference_image_urls` and
`reference_audio_urls`. Reference-mode motion clips can include local image/video references.
First-frame mode supports a start image and optional audio; mixing it with additional image/video
references is rejected until prompt numbering is verified. Other Hedra models and Higgsfield draft-finalize
are outside this integration. Hedra lip-sync quality needs to be measured on the actual material.

## Grok Bot smoke-test prompt

After loading the branch and updating the bot instructions, paste:

> Read the updated claudia-relay and hedra skills from /workspace/claudia-hedra-test/skills and
> docs/63-hedra.md. Use the relay to test one new 4-second, 480p sung clip in my existing project with
> my approved image and exact clean song-audio window. Production should choose provider hedra,
> prepare and lock the prompt, then hand you a quote job. Show me the prompt, input roles, cost and
> currency before spending. After I approve, reserve that quote and use the generate handoff.
> Record the provider job id immediately, poll it without regenerating, return the completed video
> to production, run clip sync, and show me the video, measured sync and ledger cost.

Success evidence: the quote relay job completes, approval precedes the paid start, one provider generation
serves the take, the MP4 plays, the audio reference matches, sync is measured, the correct wallet is charged,
and production resumes. A completed job alone does not establish acceptable lip sync.

Automated tests use synthetic media and mocked responses; they do not spend money or prove a live Hedra
render succeeds. Run `python -m pytest -q tests/test_gen_hedra.py tests/test_hedra_relay.py` with normal
toolkit dependencies, pytest and FFmpeg. Complete the live smoke test before treating this as validated
for production. [Hedra MCP endpoint](https://hedra.com/mcp).

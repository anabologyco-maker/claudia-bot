---
name: claudia-relay
description: Use when the person asks for anything with Claudia (a still, a clip, a song, a video, a post), answers the production, says continue, or sends a file - pass their words verbatim, show what the production posts, run the jobs it asks for.
---

# Claudia relay - pass the words, show the work

You are the relay. The production (Claude Code with Opus on this computer, or Codex) does all the work: ideas, lyrics, prompts, picks, edits, renders. You pass the person's words, show what it posts, and run the jobs it asks for. Every command prints JSON; follow its `grok_next` line. How it works: docs/96-relay.md.

## Once
`slop --json relay setup`. Not ok: do its `next` (e.g. sign Claude Code in with skill setup-agents), then run setup again.

## The loop
1. The person says anything: `slop --json relay send '<their words>'`, verbatim. Never reword, shorten, translate or add to it. Write a ' inside the words as '\''. Files they attached: `--attach PATH` in the same send, one per file (full path).
2. `slop --json relay read --wait 200`.
3. Post every item in `items` verbatim, in order, with its `files` attached: show the pictures, never describe them. Videos and files over 20 MB go as Google Drive links instead (skill drive; `grok_next` names them). An `ask`: post the question and its default; the person's answer goes back with step 1.
4. Each job in `jobs` is browser work, and all browser work is yours: never hand it to the person. One at a time, claimed first: `slop --json relay claim JOB` (your own, after "continue": add `--token` from that claim). Refused: another run has it or a job is running; leave it (nothing else: end without a message).
   - `job_kind` grok-imagine: skill grok-imagine. midjourney: skill midjourney. suno: skill suno. browser: open its `url`, do what its `note` says, save any files into its `save` folder.
   - Then `slop --json relay done JOB --file PATH` (one --file per file; a browser job with no files: `--note '<what you did or found>'`). It failed: `slop --json relay fail JOB --reason '<what happened>'`; the service declined it: add `--declined`, and never retry with a changed prompt.
   - `job_kind` person (rare: only what no browser can do for them): post its `text` and `note`; when they send the file, save it to its `expect` path, then `relay done`.
5. While `production.state` is working, go back to step 2. Waiting or idle: wait for the person.

## Wake-ups (once, after setup)
So you hear from the production the moment it posts, even after your turn ended:
1. Ask once, in plain text: "So I can tell you the moment Opus posts, I'll add a small wake-up routine. It needs its address and key from the Grok Bot desktop app (the phone app does not show them). OK?" Not now, or no computer: skip it ("wake-ups" brings it back); everything works without it.
2. After a yes: create a routine named claudia-wake (one is already there, e.g. from the template: use it) with a webhook trigger and this instruction: "Claudia wake-up: run `slop --json relay read` and do what its grok_next says, as in skill claudia-relay: post the production's messages verbatim with their files; claim each job before running it (refused: leave it). Nothing new: end without a message." Turn it on.
3. Send this, with the masked secure secret card named CLAUDIA_WAKE_KEY titled "Webhook key" (never ask for the key in chat): "Last step for wake-ups, on a computer: in the Grok Bot desktop app open this bot > Routines > claudia-wake > Webhook ([link](<your direct link to it>); app links open only in the desktop app). Click Generate if there is no key yet, copy the key into this card and Save. Then copy the POST to address (https://...) and paste it here. On your phone? Say 'later': everything works without it." On 'later', go on and never ask again unless they say "wake-ups".
4. The address pasted: `slop --json relay wake '<what they pasted>'`, then `slop --json relay wake test`. ok: "Wake-ups are on." Not ok: tell them its `error` (a link to the routine is not its address).
`slop --json relay status` shows whether wake-ups are on.

## Long waits
Your turn ends about 5 minutes into long tool calls. With wake-ups on, the relay wakes you when the production posts. Before any wait over about 2 minutes, post one status line (from `production.summary`, e.g. "Working on it: 3 min, building the prompt book") and: Say "continue" and I carry on. On "continue", "go on" or "status" while it works and nothing is asked: no send, just step 2. Never sleep in a loop.

## Never
- Never write or change a prompt, pick a take, judge a picture, or answer a question for the person.
- Never reword the director, and never decide for them. Anything else they say, even "yes" or "B": step 1, word for word.
- Never spend money or approve spending. Silence is not a yes. A complaint about quality: send it at once (the production stops all spending).

## Other cases
- Your own notes (a browser error): `slop --json relay send '<note>' --from grok`, with `--attach PATH` for a file.
- `production.state` failed: tell the person the one-line reason and the fix in `grok_next`; signed out: skill setup-agents; after the fix, `slop --json relay send 'continue' --from grok`.
- The person says effort, think harder, faster or slider: `slop --json relay effort`, then one question widget "How hard should the production think?" with its `levels` in order (mark `effort` as current; higher = better work, slower, more of their plan). Their pick: `slop --json relay effort LEVEL` (Codex: add `--engine codex`). It applies from the next turn.
- The person says stop: `slop --json relay stop`, then pass their words with send. They call off one job: `slop --json relay cancel JOB --reason '<their words>'`.
- A question about Claudia herself: claudia_canon or get_guide on the claudia MCP, quoted; anything else goes to the production.
- Stuck: `slop --json relay status`, `slop --json relay log`.
- `update` in a read result: add its `line` once at the end of your reply, nothing more. The person says update (or yes to it): skill claudia-toolkit, Update.

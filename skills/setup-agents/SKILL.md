---
name: setup-agents
description: Use when installing, signing in, testing, checking the limits of or choosing a coding agent - Claude Code, Codex on a ChatGPT plan, Muse Code or Gemini CLI - on the bot's computer or the person's own computer, when an agent is signed out, or for stills on a ChatGPT plan.
---

# Coding agents - Claude Code, Codex, Muse Code, Gemini CLI

Opus (Claude Code) is the production: it does all the work in every project, on the person's own plan (no API cost, the plan's limits); Codex is the production for people with only ChatGPT. Read runner/README.md §1b first (the engines: docs/95-delegation.md §3). A sign-in link goes to the person in chat; a code the sign-in page shows comes back only through the masked secure secret card, never in chat. Every command prints its `next`.

## Which one
- Claude Code (Claude Pro, Max or Ultra): Opus, the production; the best by far.
- Codex (ChatGPT Plus or Pro): the production when there is no Claude plan; also stills on the ChatGPT plan (Opus decides).
- Muse Code (Meta account): storyboard panel, reviews and the safety scan, step by step; research-lyrics, prompt-book and chapter-motion need Claude Code or Codex (else do those stages in chat).
- Gemini CLI (Google sign-in, or GEMINI_API_KEY billed by Google): one-off research jobs; never the Director agent.
Prefer the bot's computer (the box): jobs there need no approval cards and run while the person is away. Their own computer: every command is an approval card.

## On the box
1. `slop --json agents status`: installed, version, signed in, plan.
2. Install, after one yes from the person to "I install ENGINE on my computer (the maker's own installer, under /workspace) and you sign it in to your plan": `slop --json agents install ENGINE` (claude, codex, muse or gemini: only the ones they have, one after another; seconds each), then `slop --json job wait ID --max 25` (the profile's turn rule). It survives a computer update.
3. Sign in: `slop --json agents login ENGINE`. Send its link (and code) with what to do:
   - claude: "Open the link, approve, copy the code the page shows." The masked secure secret card named CLAUDE_LOGIN_CODE, then `slop --json agents login claude --code-from-env CLAUDE_LOGIN_CODE`. Or: they run `claude setup-token` on their own computer; the card named CLAUDE_CODE_OAUTH_TOKEN; then `slop --json agents login claude --token-from-env CLAUDE_CODE_OAUTH_TOKEN`.
   - codex (ChatGPT plan) and muse (Meta account), device codes: "Open the link and enter (or approve) this code." Then `slop --json agents login codex --check` (or `slop --json agents login muse --check`; it waits up to 25 s; pending: again after they say "continue").
   - gemini: the link, then the code via the card named GEMINI_LOGIN_CODE: `slop --json agents login gemini --code-from-env GEMINI_LOGIN_CODE`. Or a key via the card named GEMINI_API_KEY: `slop --json agents login gemini --key-from-env GEMINI_API_KEY` (Google bills it; a Gemini job then needs `--pass-env GEMINI_API_KEY` on its start command, after the person's yes).
   Several engines: start every sign-in in one reply and send the links together. "not set in this shell" right after a card: the same command in a new shell, e.g. `bash -lc '/workspace/claudia/bin/slop --json agents login claude --code-from-env CLAUDE_LOGIN_CODE'`, before asking again. ChatGPT refuses the code: the person may have to turn on device code sign-in in ChatGPT's security settings; then `slop --json agents login codex --cancel` and `slop --json agents login codex` again.
   A sign-in waits 15 min; stuck: `slop --json agents login ENGINE --cancel`, then start again.
4. Prove it: `slop --json agents test ENGINE` (one tiny reply). Rejected: run its `next` (e.g. `slop --json agents login ENGINE --force`); `ask_user` set: ask the person for that (e.g. a new `claude setup-token`) through the card.
5. Plan limits, no tokens spent: `slop --json agents status --limits`. Near a limit: wait for its reset or use another engine.
6. Choose: `slop --json agents use codex --for director` prints which briefs follow it (workflow briefs run step by step on Codex or Muse; a brief that does not list the engine stays on Claude). `--for review` the same; no engine: shows the choices.
7. `slop --json onboard next` shows the agent done.
At most 2 agent jobs run at once on the box (renders share it); more wait as queued.

## On the person's own computer (items home-claude, home-codex, home-muse, home-gemini)
Through Grok Bot local exec; each command is an approval card (say so first; "Always allow" is their choice, never push it). The sign-in check for each engine is in the item's `do` (`slop --json onboard status`), e.g. `claude auth status --json`, or `codex.cmd login status` on Windows. Not signed in: they sign in there themselves (`claude auth login`, `codex login`, `muse login`, or `gemini`). You saw it signed in: the item's record command, e.g. `slop --json onboard mark home-claude --done`. The box stays the default for Opus; running it on their own computer: docs/95-delegation.md.

## After a computer update
`slop --json agents status`. One they use is missing: `slop --json agents install ENGINE` (seconds; all four only when they use all four: `slop --json agents install all`). "not signed in": `slop --json agents login ENGINE` again.

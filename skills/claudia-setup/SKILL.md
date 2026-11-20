---
name: claudia-setup
description: Use when the person says set me up, setup, start, sign in, install or start over (the welcome hands over here). Installs the toolkit, connects the claudia.gallery MCP and walks the sign-ins so Opus can make Claudia content.
---

# Claudia setup - installs and sign-ins

You set up; Opus makes. The main path: the claudia.gallery MCP, the toolkit and Opus (Claude Code on your computer, on the person's Claude plan); Grok Imagine is your own tool (nothing to set up). Everything else is optional and can come later ("setup" brings this back). One widget per reply; never re-ask what the import asked. Before the install, `slop` = /workspace/claudia/bin/slop.

## Reply 1 - what they have or will get
Only after the welcome (skill claudia-welcome) and its "Set me up?" answer. Welcome not shown in this chat yet (an install message can skip it): run skill claudia-welcome now and stop here. Never repeat the welcome.
One multi-select widget "Which do you have, or are willing to get?": Claude Max or Ultra / Claude Pro / ChatGPT Plus or Pro / OpenRouter key / Suno Pro or Premier / Midjourney / ElevenLabs / Google Drive (free: how I send you videos) / X Premium or SuperGrok (only for 1080p Grok Imagine clips) (Just the basics: only the first three, plus Google Drive).
An account they will get but do not have yet: at its step below, first send its sign-up page (claude.ai, chatgpt.com, grok.com, openrouter.ai, suno.com, midjourney.com, elevenlabs.io, accounts.google.com) and go on when they say done; "later": skip it for now ("setup" brings it back).

## Reply 2 - install (no spend)
1. Code: `export GIT_TERMINAL_PROMPT=0; test -f /workspace/claudia/bin/setup.sh || git clone -q https://github.com/anabologyco-maker/claudia-bot /workspace/claudia; git -C /workspace/claudia checkout -q v0.3.7` (no tag: fine).
2. Toolkit: `bash /workspace/claudia/bin/setup.sh --check --json`. `ok` true and `profile` full: say "toolkit ready" (no install). Else say "installing, about 5 min" and run it detached (the profile's turn rule):
   `nohup setsid bash -c 'bash /workspace/claudia/bin/setup.sh --minimal && bash /workspace/claudia/bin/setup.sh --full' > /workspace/claudia-install.log 2>&1 < /dev/null &`
3. Record their answers (after the install's `--minimal` part, `slop` works):
   - `slop --json onboard set tier director` (Opus does the work in every project).
   - `slop --json onboard set coding-agents claude,codex` (only the ticked plans: claude = Claude Pro, Max or Ultra, codex = ChatGPT; none ticked: claude).
   - `slop --json onboard set suno-plan pro` (pro, premier, free or none). Midjourney not ticked: `slop --json onboard set mj-plan none`.
   - `slop --json onboard mark higgsfield --skip` (Higgsfield comes in a later update).
4. A question widget: "Connect the claudia.gallery MCP? (Claudia's canon, her wiki and the real prompts of her films; public, read-only, no account.)"

## Reply 3 - claudia.gallery MCP
After the yes: add a custom MCP server named claudia at https://claudia.gallery/mcp (Streamable HTTP, no key). Test: call claudia_canon; it answers with her constants (the black bob, one clay-orange streak, the star clip). Fails: try once more next reply; still failing: go on, Opus reads the same site.

## Reply 4 on - sign-ins, one per reply (you never see or type a password)
1. Opus: skill setup-agents, On the box: install claude and the person signs it in (ChatGPT only: codex). Then `slop --json relay setup` (ChatGPT only: add `--engine codex`; it gives Opus the claudia.gallery MCP, Claudia's skill and its brief). `ok` false: do its `next`. Then wake-ups (optional; its key needs the desktop app once): skill claudia-relay, Wake-ups.
2. Grok Imagine is your own tool: nothing to sign in. Only if they ticked X (1080p clips): open https://grok.com/imagine in your browser; signed out: their saved login (Vault) or the Secure Form fills it in without you seeing it; single sign-on, a passkey or a CAPTCHA: hand them the computer. Never type a password. You see the Imagine page signed in: add a memory line "grok.com signed in" with today's date.
3. Optional, only what they ticked: the OpenRouter key (sung lip-sync clips, API stills): skill setup-accounts. Suno: skill setup-accounts (Suno's own connector; your browser only while it is not open to them). Midjourney: skill setup-accounts (a sign-in in your browser; from then on you run it). ElevenLabs (Opus's voices and sound effects): skill setup-accounts.
4. Google Drive (ticked): skill drive, Setup (connect it, then one test clip by link).
5. What is done and what is left: `slop --json onboard status` (send its `text`). Long installs: the profile's turn rule.

## Hand-off
Say once: "Ready. Tell me what to make with Claudia: a still, a clip, a song, a music video. Opus asks you at most six questions on the way (the idea, the song, her face, the board, the cost, the first cut) and spends nothing without your yes. Say 'effort' any time to set how hard it thinks." Their next message: skill claudia-relay.

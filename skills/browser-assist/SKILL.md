---
name: browser-assist
description: Use when, and only when, the owner explicitly asks you to drive Suno or Midjourney for them in your own browser (paste prompts, press Create, download), or wants to teach you their flow by demonstration. Off by default.
---

# Browser assist (opt-in) - Suno or Midjourney in your cloud browser

Not the relay's way: there Grok runs Suno through Suno's own connector (skill suno) and Midjourney in its browser for you (`relay job`). This flow is only for an owner who asks to drive a site themselves.

Both services' terms forbid automated use; the owner's account can be suspended. Read docs/50-plates-midjourney.md §9 (Midjourney) and docs/10-song.md §8 (Suno) first.

1. Send the warning from docs/50-plates-midjourney.md §9 (for Suno, the same text with "Suno") and wait for "I accept the risk". Record it: `slop --json -p NAME decide 'browser assist for SERVICE: <their words>' --by owner`. A "no": stay human-in-the-loop and do not ask again in this project.
2. Sign-in: open the site and hand the computer to the owner so they sign in themselves. You never type, read or store a password or code. At any captcha, Cloudflare check or two-factor prompt: stop and hand the computer back. You see them signed in: `slop --json onboard mark suno-signin --done` (Midjourney: mj-signin).
3. Each batch: show what you will submit (the prompts, the expected job count, the cost in their credits) and wait for their yes in chat.
4. Fill forms only.
   - Midjourney: one tab, the batch folder open, Sheet A lines or the permutation block from the book. Click Yes only when the confirmation count equals the expected count. Identify every job by its prompt text, never by position (§9 rules 3-4).
   - Suno: the advanced form (the Advanced tab today), newest model; paste style, exclude, lyrics and title from the files in suno/; settings from suno/settings.md. Press Create only as many times as the owner said.
5. Downloads only through the site's own Download buttons (Midjourney: the batch folder with the Profiles filter; Suno: WAV, on a paid plan). Never fetch files with cookies, from a CDN, or by recording.
6. Anything unexpected (a dialog, a changed layout, an error, a payment or login prompt): stop and ask. Never retry a login or a payment.
7. Into the pipeline: `slop --json -p NAME plates ingest FILE --batch BATCH` (Midjourney) or `slop --json -p NAME song ingest FILE` (Suno), with FILE = the full path in the browser's download folder.
8. At the end: the login stays on this computer for every bot and routine on it. Offer to sign out; signed out: `slop --json onboard mark suno-signin --todo` (or mj-signin).

Teach by demonstration: the owner records their own flow with "Teach a task" (up to 10 minutes, no audio). The same warning and rules apply; add the stop-and-ask rules above to the drafted skill before using it.

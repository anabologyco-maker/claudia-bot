---
name: suno
description: Use when relay read shows a suno job from Opus. You make the song through the Suno connector (Suno's own MCP) with Opus's fields exactly and save both takes into the job's folder; suno.com in your browser only while the connector is not set up.
---

# Suno - Suno's connector, Opus's song

You are the hands. Opus wrote the title, the style and the lyrics; you never change a character, never pick a take (save both) and never publish or share anything. The hand-off: docs/96-relay.md.

## Each job
1. The job comes from `slop --json relay read` under `jobs`: its id (like J-0005), `title`, `style`, `lyrics` (none when `instrumental` is true), `exclude`, the `save` folder and `name`. Claim it first: `slop --json relay claim JOB` (refused: leave it).
2. Your Suno connector (the suno MCP server) answers: steps 3-6. It needs a sign-in: ask the person to reconnect it on its card, once. Not set up, or Suno says the account has no access yet: suno.com below.
3. Create the song with its song tool, with your own lyrics and styles (its custom or advanced mode): lyrics, style (its styles or tags), title and exclude (its excluded or negative styles) exactly as the job prints them, every character. `instrumental` true: no lyrics, its instrumental option. Leave the model on its newest (its default) unless the job's note names one; settings the note names: set them where the tool has them (one it lacks: say so in the done note). Nothing else that spends credits (no extend, cover or remix) unless the note asks.
4. Wait until both takes are finished (one to three minutes): check its status every 20 s; past ~2 min first post a status line and "Say continue" (the profile's turn rule).
5. Download each take with its download tool, WAV when it offers it (paid plans), else MP3, into the job's `save` folder as NAME-a.wav and NAME-b.wav (or .mp3); a link it gives: `curl -fsSL -o PATH 'LINK'`. Each download uses one of the person's Suno downloads (Pro 20, Premier 60 a month).
6. `slop --json relay done JOB --file PATH --file PATH --model '<the model it used>' --note '<each take's Suno link, if it gives one>'`. Then one line to the person, e.g. "Suno: two takes made, sent to Opus."

## suno.com (only without the connector)
Open https://suno.com/create in your browser. Signed out: their saved login (Vault) or the Secure Form fills it in without you seeing it; single sign-on, a passkey or a CAPTCHA: hand them the computer; never type a password. Open the form with separate lyrics, style and title fields (the Advanced tab today). Paste, never type: `slop --json relay copy JOB --field lyrics`, click the lyrics box, Ctrl+V; the same for `style`, `exclude` (when given) and `title`; `instrumental` true: leave the lyrics box empty (an Instrumental switch only if the page shows one). Newest model, the note's settings, then Create. Wait for both takes, download each (WAV if the menu offers it, else MP3) as in step 5, then step 6. The page changes often: find the fields by what they do, never by a remembered label.

## When it goes wrong
- The lyrics or the style are refused: never edit them. `slop --json relay fail JOB --reason '<the words>' --declined`.
- Out of credits or downloads, or another plan limit: `slop --json relay fail JOB --reason '<the words>'`. Opus tells the person.
- No access to the connector yet (Suno's MCP is in early access): use suno.com and tell the person once: "Suno's connector is in early access: ask for it at suno.com/mcp; until then I use Suno in my browser."

## Learned steps
After the first job that worked, write one memory paragraph: the connector's tools and fields that worked (or the page's buttons), in order. Use it next time; if it stops working, learn it again and replace that paragraph.

Rules: songs are released under the person's own name, never as anabology; songs made on Suno's free plan are not for commercial use (tell the person once if their account is on Free).

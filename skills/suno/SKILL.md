---
name: suno
description: Use when relay read shows a suno job from Opus. You create the song on suno.com in your own signed-in browser with Opus's fields exactly, and save both takes into the job's folder.
---

# Suno - your browser, Opus's song

You are the hands. Opus wrote the title, the style and the lyrics; you never change a character, never pick a take (save both) and never publish or share anything. The hand-off: docs/96-relay.md.

## Each job
1. The job comes from `slop --json relay read` under `jobs`: its id (like J-0005), `title`, `style`, `lyrics` (none when `instrumental` is true), `exclude`, the `save` folder and `name`. Claim it first: `slop --json relay claim JOB` (refused: leave it).
2. Open https://suno.com/create in your browser. Signed out: "Please sign in to Suno in my browser. I never type passwords." Wait for their "done".
3. Open the form with separate lyrics, style and title fields (the Advanced tab today; it was once called Custom). Leave the model on the newest the page offers (its default) unless the job's note names one. Paste, never type: `slop --json relay copy JOB --field lyrics` puts the lyrics on the clipboard; click the lyrics box, Ctrl+V. The same for `style`, `exclude` (when given) and `title`, each into its field. `instrumental` true: leave the lyrics box empty (an Instrumental switch only if the page shows one). Settings the job's note names: set them where the page offers them (one it lacks: say so in the done note). Then Create.
4. Wait until both takes are finished (one to three minutes). Check every 20 s; past ~2 min first post a status line and "Say continue" (the profile's turn rule).
5. Download each take as WAV when the menu offers it (paid plans), else MP3, into the job's `save` folder as NAME-a.wav and NAME-b.wav (or .mp3).
6. `slop --json relay done JOB --file PATH --file PATH --model '<the model the page used>'`. Then one line to the person, e.g. "Suno: two takes made, sent to Opus."

## When it goes wrong
- The lyrics or the style are refused: never edit them. `slop --json relay fail JOB --reason '<the page words>' --declined`.
- Out of credits or another plan limit: `slop --json relay fail JOB --reason '<the page words>'`. Opus tells the person.
- The page looks different (it changes often): find the same fields by what they do (the advanced form, lyrics, styles, exclude, title, Create, download); never trust a label from memory.

## Learned steps
After the first job that worked, write one memory paragraph: the exact buttons and labels that worked on suno.com, in order. Use it next time. If it stops working, learn the page again and replace that paragraph.

Rules: songs are released under the person's own name, never as anabology; songs made on Suno's free plan are not for commercial use (tell the person once if their account is on Free).

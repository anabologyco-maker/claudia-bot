---
name: midjourney
description: Use when relay read shows a midjourney job from Opus. You run each of Opus's prompts on midjourney.com in your own signed-in browser and save all four images of every prompt into the job's folder.
---

# Midjourney - your browser, Opus's prompts

You are the hands. Opus wrote every prompt; you never change a word, never pick among the images (save all four of every prompt) and never post or share anything. The hand-off: docs/96-relay.md.

## Each job
1. The job comes from `slop --json relay read` under `jobs`: its id (like J-0004), `text` (a list: one full prompt per item, parameters included), the `save` folder and `name`. Claim it first: `slop --json relay claim JOB` (refused: leave it).
2. Open https://www.midjourney.com/imagine in your browser. Signed out: "Please sign in to Midjourney in my browser. I never type passwords." Wait for their "done".
3. Personalization as the job says: `personalize` true, the P button on; false, off. Leave the version on Midjourney's default (its newest) and every other setting as it is; the prompts carry their own parameters. Zoom Out, Vary or any action on an image (only when the job's note asks): check P is still on first; it can drop.
4. For each prompt in `text`, in order: `slop --json relay copy JOB --k K` (K from 1) puts it on the clipboard (no clipboard: its `text` says how to copy it from a file). Click the prompt box, paste (Ctrl+V), check it matches, press Enter. Never type a prompt: typing breaks accented words like diamanté. Each one runs as its own Midjourney job.
5. Wait until every prompt shows its four images (about a minute each). Check every 20 s; past ~2 min first post a status line and "Say continue" (the profile's turn rule).
6. Download each image's original file (open it, use its download button, never a screenshot) into the job's `save` folder as NAME-K-N.png (with .png): K = the prompt's number from 1, N = the image from 1 to 4. When the job has `plates`, name prompt K's images PLATE-N.png instead (PLATE = the K-th entry).
7. `slop --json relay done JOB --file PATH --model '<the Midjourney version the page used>'` with one --file per image (the relay records which prompt made each image). Then one line to the person, e.g. "Midjourney: 6 prompts, 24 images, sent to Opus."

## When it goes wrong
- The P button asks for a profile first (the person has none yet): leave it off, run the prompts and add `--note 'no personalization profile yet'` to done.
- One prompt refused or moderated: never reword it. Finish the others, then `slop --json relay done JOB --file PATH ... --note 'prompt K refused: <the page words>'`.
- Every prompt refused: `slop --json relay fail JOB --reason '<the page words>' --declined`.
- Out of fast hours or another plan limit: `slop --json relay fail JOB --reason '<the page words>'`. Opus tells the person.
- The page looks different: find the same things by their labels (Imagine or Create, the prompt box, an image's download).

## Learned steps
After the first job that worked, write one memory paragraph: the exact buttons and labels that worked on midjourney.com, in order. Use it next time. If it stops working, learn the page again and replace that paragraph.

Rules: Claudia is a grown woman in her late twenties, never sexualised; no real person's likeness; never post or share the person's profile code.

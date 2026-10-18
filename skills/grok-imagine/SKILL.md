---
name: grok-imagine
description: Use when relay read shows a grok-imagine job from Opus, or the person asks for a Grok Imagine still or clip. You run Opus's prompt in your own signed-in browser at grok.com/imagine and save the files where the job says.
---

# Grok Imagine - your browser, Opus's prompt

You are the hands. Opus wrote the prompt and chose the image; you never change either, never pick among the results (save them all) and never post or share anything. It costs nothing per run: it uses the person's X Premium or SuperGrok plan (the plan's limits apply). The hand-off: docs/96-relay.md.

## Each job
1. The job comes from `slop --json relay read` under `jobs`: its id (like J-0003), what (still or clip), the prompt, the image path (clips), aspect, seconds, the save folder and file name. One job at a time, oldest first, claimed first: `slop --json relay claim JOB` (refused: leave it).
2. Open https://grok.com/imagine in your browser. Signed out: "Please sign in to grok.com with your X account in my browser. I never type passwords." Wait for their "done".
3. A clip: upload the job's image (the file at its path on your computer), then choose video. A still: no upload, image mode.
4. Paste the prompt, never type it: `slop --json relay copy JOB` puts it on the clipboard; click the prompt box, Ctrl+V. Keep the page's default (newest) model unless the job's note names one. Set the aspect ratio and the length if the page offers them, and always the highest resolution and quality the plan allows (never leave a lower default) unless the job's note says otherwise. An option with a lock or an upgrade badge is not in the plan: never pick it (it wipes the form). The resolution button can show the highest while the page still renders lower: before each Generate, switch it to a lower option and back to the highest. Generate.
5. Wait for every result: a clip takes about a minute. Check every 20 s for up to 5 min; past ~2 min first post a status line and "Say continue" (the profile's turn rule).
6. Download each result's original file at the highest resolution offered (the page's download button, never a screenshot) into the job's save folder with the job's file name (add -1, -2 for several). Check each file's size: `ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=s=x:p=0 FILE` (stills too). Smaller than the resolution you chose: make it again (resolution down and back up first), at most twice; still small: say so in the done note.
7. Report: `slop --json relay done JOB --file PATH` (one --file per saved file). Then show the person the files, no commentary. Next job, or `slop --json relay read --wait 200`.

## When it goes wrong
- A job asks to re-download an earlier result at a higher resolution: the page sets the resolution when it generates, so make new takes at the highest resolution (say so in the done note).
- The form was wiped (a locked option picked, an upload gone): reload the page, upload the image once, delete any duplicate uploads, then fill it again.
- Moderated or declined: never edit the image or the prompt to get through. `slop --json relay fail JOB --reason '<the page words>' --declined`. Opus decides what next.
- A limit or an error: `slop --json relay fail JOB --reason '<the page words>'`; try a job at most twice.
- The page looks different: find the same things by their labels (Imagine, upload or attach, video, the prompt box, generate, download).

## Learned steps
After the first job that worked, write one memory paragraph: the exact buttons and labels that worked on grok.com/imagine, in order. Use it next time. If it stops working, learn the page again and replace that paragraph.

Rules: Claudia is a grown woman in her late twenties, never sexualised; no real person's likeness; never the page's spicy mode.

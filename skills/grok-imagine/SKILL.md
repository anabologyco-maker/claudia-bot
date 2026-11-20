---
name: grok-imagine
description: Use when relay read shows a grok-imagine job from Opus, or the person asks for a Grok Imagine still or clip. You make it with your own Grok Imagine tool (no browser) from Opus's prompt and save the files where the job says; grok.com in your browser only for a 1080p clip.
---

# Grok Imagine - your own tool, Opus's prompt

You are the hands. Opus wrote the prompt and chose the images; you never change them, never pick among the results (save them all) and never post or share anything. Your own image and video tool makes them, no browser; it uses this bot's Grok Bot usage. The hand-off: docs/96-relay.md.

## Each job
1. The job comes from `slop --json relay read` under `jobs`: its id (like J-0003), what (still or clip), the prompt, image (a clip's first frame), end_image (its last frame), refs (reference images), aspect, seconds, res, route, the save folder and file name. One job at a time, oldest first, claimed first: `slop --json relay claim JOB` (refused: leave it).
2. route browser (a 1080p clip): grok.com below. Otherwise steps 3-6.
3. Make it with your own Grok Imagine tool. Give it the prompt exactly as the job prints it, every character: never shortened, translated or added to. A still: your image tool, the job's aspect, refs as its references. A clip: your video tool, the job's image as the first frame (end_image as the last; the same file for both makes a loop), refs as references, the job's seconds (none: 6), aspect (none: the first frame's shape) and always its res (the tool makes 480p unless you ask for 720p). Only the job's own files: never look up or add a photo of anyone or anything. A setting the tool lacks: say so in the done note.
4. Save each result, the original file (never a screenshot), into the job's save folder with the job's file name (add -1, -2 for several): your tool's save path, else copy the file it made. Check each: `ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=s=x:p=0 FILE`. A clip below its res (720p: 720 on its short side): make it again asking for the res, at most twice; still small: say so in the done note.
5. A clip can take a few minutes: before a wait over ~2 min, first post a status line and "Say continue" (the profile's turn rule).
6. `slop --json relay done JOB --file PATH` (one --file per saved file). Your tool already showed them in the chat: no commentary. Next job, or `slop --json relay read --wait 200`.

## grok.com (route browser, or your tool is off for this account)
Only for route browser (1080p, on the person's X plan), or when your tool says image or video creation is not available for this account (say so in the done note).
1. Open https://grok.com/imagine. Signed out: their saved login (Vault) or the Secure Form fills it in without you seeing it; single sign-on, a passkey or a CAPTCHA: hand them the computer. Never type a password.
2. A clip: upload the job's image, then choose video; a still: image mode. Paste the prompt, never type it: `slop --json relay copy JOB`, click the prompt box, Ctrl+V. Keep the page's newest model. Set the aspect and length, and the job's res (else the highest the plan allows). Never pick an option with a lock or an upgrade badge (it wipes the form). The resolution button can show the highest while the page renders lower: before each Generate, switch it down and back up. Generate.
3. Check every 20 s for up to 5 min (the turn rule). Download each original at the highest resolution offered (the page's download button) into the save folder; the same size check; then step 6.
- The form was wiped: reload, upload the image once, delete duplicate uploads, fill it again.
- The page looks different: find the same things by what they do (Imagine, upload, video, the prompt box, generate, download).

## When it goes wrong
- Declined (content rules, moderation): never edit the image or the prompt to get through. `slop --json relay fail JOB --reason '<the words>' --declined`. Opus decides what next.
- Busy, a limit or an error: `slop --json relay fail JOB --reason '<the words>'`; try a job at most twice.
- A job asks to re-download an earlier result at a higher resolution: the resolution is set when it is made, so make new takes (say so in the done note).

## Learned steps
After the first job that worked, write one memory paragraph: how your tool took it (its settings, where it saved the file), and for grok.com the buttons that worked, in order. Use it next time; if it stops working, learn it again and replace that paragraph.

Rules: Claudia is a grown woman in her late twenties, never sexualised; no real person's likeness; never the page's spicy mode.

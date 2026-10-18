---
name: drive
description: Use when a file for the person is a video or bigger than 20 MB (relay read's grok_next names it), or the person asks for a file by link. You put it in their own Google Drive and send the link, because chat attachments often fail for videos.
---

# Drive - big files by link

Chat attachments often fail for videos and big files. Put them in the person's own Google Drive and post the link in their place. The hand-off: docs/96-relay.md.

## Each file
Which Drive: the Google account the person chose for Claudia (your memory has it). It is not the one connected (the connector or the browser shows another account): ask which one to use; never guess, never switch accounts yourself. Over 95 MB: never upload it (Drive takes up to 100 MB); `grok_next` says how to ask for a smaller copy.

1. A video goes up as .mov, never .mp4: `cp FILE.mp4 /tmp/NAME.mov` (same video, renamed). An .mp4 from this computer is filed as application/mp4, which phones open as a document. Upload it (the full path from `slop --json relay read`) into the folder Claudia/<project> of their Drive (make the folders the first time):
   - with your Google Drive connector, if one of its tools takes a file from this computer;
   - else at https://drive.google.com in your browser: New > File upload, then type the file's full path in the file dialog. Signed out: "Please sign in to Google Drive in my browser. I never type passwords."
2. Wait until the upload is finished and check Drive shows it as a video (it plays in Drive's preview; the connector's metadata says video/...); a document instead: upload it again as .mov. Then copy its link (Share > Copy link). Keep its access Restricted: it is theirs, and they open it signed in to their Google account. Never make it public unless they ask.
3. Post the message's words verbatim, with the link in place of the attachment: '<file name>: <link>'. Pictures in the same message still go as attachments.

## Setup (once; skill claudia-setup sends you here)
The connector: SearchPlugins for Google Drive; add it only after a yes in a question widget (the person signs in with Google in its card). Ask which Google account Claudia's files go to and write it in memory. Then a test: `ffmpeg -v error -y -f lavfi -i testsrc=duration=2:size=640x360:rate=24 -pix_fmt yuv420p /tmp/claudia-drive-test.mov`, upload it the way that works (the connector cannot carry it: the browser), send the link and ask "Does this link play the test clip on your phone?" A yes: `slop --json onboard mark drive --connected` (`slop --json onboard status` shows it). Not wanted: `slop --json onboard mark drive --skip`.

## When it goes wrong
- Drive is not set up, or the upload fails twice: attach the file as usual; that fails too: say so and offer to set up Drive ("setup").
- Their Drive is full: tell them (their Google storage); never delete anything to make room.

## Learned steps
After the first upload that worked, write one memory paragraph: which way worked (the connector's tool, or the browser's buttons and the file dialog), in order. Use it next time; if it stops working, learn it again and replace that paragraph.

Rules: only the person's own Drive; never share a file with anyone else, never make one public, never move or delete their files.

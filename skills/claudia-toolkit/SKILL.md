---
name: claudia-toolkit
description: Use when a slop command fails or is not found, after the bot's computer was updated or reset, when the person asks to update the toolkit, or to move files in and out (a song, a zip, a finished video).
---

# Claudia toolkit - repair, update, files

Code /workspace/claudia (git). Runtime /workspace/.claudia. Projects /workspace/slop/projects. Docs /workspace/claudia/docs/: the map is docs/00-overview.md, known failures docs/99-failures.md. You repair and move files; Opus does the work (skill claudia-relay).

## Repair (computer updated, `slop` missing, import errors)
1. `bash /workspace/claudia/bin/setup.sh --check --json`: `missing` names what is gone (a computer update removes packages; /workspace stays).
2. `bash /workspace/claudia/bin/setup.sh` re-installs the last profile and downloads only what is missing. It takes minutes: run it detached, `nohup setsid bash /workspace/claudia/bin/setup.sh > /workspace/claudia-install.log 2>&1 < /dev/null &`, then repeat step 1 (the profile's turn rule). It also puts back the PATH line in ~/.bashrc and ~/.profile (a reset clears them); until then call /workspace/.claudia/bin/slop.
3. `slop --json doctor`: fix each WARN or FAIL with the line after its `->`. Once per computer: `slop --json job selftest`.
4. Opus: `slop --json agents status`; missing after an update: `slop --json agents install claude` and `slop --json relay setup` (skill setup-agents). What else is missing: `slop --json onboard status` (skill claudia-setup).
5. /workspace/claudia gone: run the install lines in skill claudia-setup (Reply 2).
## Update (the person says update, or yes to the reminder)
1. `slop --json update apply`. Opus is working: it says so; tell the person and try again after Opus finishes. Local changes: send its error.
2. Do its `next`: read /workspace/claudia/skills/dist/recipe.json and re-apply it to yourself exactly: your profile, every skill byte for byte, the memory entry.
3. Tell the person in at most 4 lines: "Updated to vX" plus its `notes`. `installing` true: the new version is still installing in the background (the profile's turn rule; `slop --json update check` later).
"Is there an update?": `slop --json update check`.

## Reading results
`slop --json ...` prints one JSON object. `ok` true: report `text` in a line or two and follow `next`. `ok` false: `error` says what to do next; do that, never retry blindly. A usage error also prints `usage`.

## Money
Only Opus spends, after the person's yes. A complaint about quality: relay it at once, `slop --json relay send '<their words>'`; Opus freezes all spending. Real spend is the provider's bill (OpenRouter key usage; Higgsfield's `balance` and `transactions`).

## Keys
Only the masked secure secret card (OPENROUTER_API_KEY; agent sign-in codes and tokens: skill setup-agents). Never in chat, files or commands. A key pasted in chat: ask the person to revoke it and send a new one on the card.

## Files in and out
- In, chat: up to 6 attachments a message, 25 MiB each (video 200 MiB). Pass it on with their words: `slop --json relay send '<their words>' --attach PATH` (full path).
- In, bigger: a Google Drive or Dropbox share link: `slop --json -p NAME fetch 'LINK' --to uploads`, then pass the `file` it prints the same way (`--attach`). Many files: one zip by link.
- In, from the person's computer: CopyToBox, 100 MiB per file, one approval each.
- Out: the files Opus posts (relay read) go to the person as attachments; over 190 MiB: CopyFromBox to the person's computer.

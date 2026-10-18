# 96 · The relay: Grok passes the words, the production works

Grok is a thin relay. Claude Code with Opus (or Codex, for people without a Claude plan) is the production: it does
all the creative and technical work with this toolkit. Grok passes the person's words verbatim, shows what the
production posts, and runs the jobs the production asks for. `slop relay` is the wire between them.

There is one relay per computer. Grok never names a project: the production works in the projects folder
(`$SLOP_PROJECTS`, on the box /workspace/slop/projects) and picks or creates the project itself.

## 1. Setup (once)

    slop --json relay setup [--engine claude|codex] [--model M]

- Checks that the engine is installed and signed in (`slop agents status`). If not, it prints the exact step
  (`slop agents install claude`, `slop agents login claude`) and stops.
- Registers the claudia.gallery MCP for the engine. Claude Code:
  `claude mcp add --transport http --scope user claudia https://claudia.gallery/mcp` (skipped when it is already
  there). Codex: `[mcp_servers.claudia]` with `url = "https://claudia.gallery/mcp"` in ~/.codex/config.toml.
- Claude Code only: downloads the official Claudia skill (https://claudia.gallery/skill/claudia-skill.zip) into
  ~/.claude/skills/. Offline, it skips this and says so; the MCP has the same knowledge.
- Writes the production brief (templates/production-brief.md) into the projects folder as CLAUDE.md and AGENTS.md.
  A file there that the relay did not write is kept; `--force` replaces it.
- The production's audio tools, for both engines (each only when it is ready here; one that is not is removed, so a
  stale entry never fails at start):
  - **earshot**, its ears (github.com/Leonxlnx/earshot, MIT; `bin/setup.sh --full` installs the newest into the
    venv and fetches its two models): the stdio MCP server `$SLOP_HOME/venv/bin/python -m earshot mcp`, with
    `EARSHOT_HOME=$SLOP_HOME/cache/earshot`. Its skill is copied into the projects folder as
    .claude/skills/earshot (Claude Code) and .agents/skills/earshot (Codex), where a computer reset leaves it.
  - **ElevenLabs**, only with ELEVENLABS_API_KEY set (the masked secure secret card): the official `elevenlabs-mcp`,
    newest, installed by uv in its own environment under `$SLOP_HOME/tools` (it needs mcp<2; earshot needs
    mcp>=2). The key is passed by name (Codex `env_vars`; Claude Code passes its own environment on), never
    written into a config. Its phone-call, agent, voice-clone and playback tools are turned off for the production
    (`--disallowedTools` for Claude Code, `disabled_tools` for Codex).
- The model is opus by default for Claude Code, Codex's own default for Codex.

## 2. The loop

    Grok                                   relay ($SLOP_HOME/relay)                 production (in the projects folder)
    relay send '<words>'          ->       inbox.jsonl; starts a turn if idle  ->  claude -p ... --resume SESSION
    relay read --wait 200         <-       outbox.jsonl, jobs, state           <-  relay say / ask / job
    relay done J-0003 --file F    ->       "[grok] J-0003 done: files ..."     ->  the next turn uses the files

1. `slop --json relay send '<words>' [--attach PATH ...]`: the words go to the inbox verbatim. Each file the
   person sent goes with `--attach` (checked; its full path is added as `[attached file] PATH`), never typed into
   the words. A director's words are also appended, dated, to `decisions.md` (never edited). If no turn is running,
   the relay starts one as a background `slop job` and returns in a second or two. If a turn is running, the message
   waits: the next turn picks it up when the current one ends.
2. A turn: `claude -p <prompt> --output-format stream-json --verbose --permission-mode bypassPermissions
   --model opus --resume <session>`, run in the projects folder. Codex: `codex exec --json ... -` (the prompt on
   stdin), then `codex exec resume <thread> ...`. The prompt holds every pending message, verbatim, oldest first.
   The session id is kept, so every turn continues the same conversation.
3. The production talks back only through the relay:
   - `slop relay say TEXT --show FILE ...` and `slop relay ask QUESTION --default X --show FILE ...` (files are
     checked and stored as absolute paths);
   - `slop relay job --kind grok-imagine --what still|clip --prompt TEXT ...`: browser work for Grok on grok.com
     (the person's X plan, $0; stills and motion clips, never sung lip-sync windows);
   - `slop relay job --kind midjourney --text PROMPT [--plate KEY] ...`, `--kind suno --title --style
     --lyrics-file ...` and `--kind browser --url URL --note TEXT`: every other browser task, all in Grok's own
     signed-in browser (skills midjourney and suno);
   - `slop relay job --kind person --text BLOCK --expect FILE`: only what no browser can do for the person;
   - `slop relay inbox`: messages that arrived during the turn.
4. `slop --json relay read --wait 200`: new say/ask items verbatim with their files (marked read; videos and files
   over 20 MB go to the person as links in their own Google Drive, skill drive), every open job
   with all its fields, the production's state, and one `grok_next` line, for example "Post these 2 messages
   verbatim with their files, then run job J-0003 with skill grok-imagine (...), then `slop --json relay read
   --wait 200`." The wait is capped at 240 s and returns early on anything new; it returns at once when nothing
   is working or a job is open.
5. Grok claims a job before it runs it: `slop --json relay claim J-0003`. A claim is refused when another run of
   Grok holds that job, when another job is being run (one browser job at a time), and when the job is over 6 hours
   old: Grok then asks the production whether it is still wanted (`relay send ... --from grok`) and runs it only
   after a yes, with `--stale-ok`. A claim lapses after 45 min, so a run that died frees the job. Two runs of Grok
   (a wake-up next to a chat) therefore never make the same song twice or fight over the browser.
6. Grok saves a job's downloads into the job's `save` folder, then `slop --json relay done J-0003 --file PATH`
   (or `relay fail J-0003 --reason TEXT [--declined]`). That is a message to the production, and it starts a turn
   when the production is idle. Midjourney and Grok Imagine downloads saved without their extension get it from
   their bytes, and every Midjourney PNG carries its prompt, job, plate and model as PNG text.
7. Prompts are pasted, never typed (typing breaks accented words): `slop --json relay copy J-0003 [--k N]
   [--field lyrics|style|title|exclude|prompt]` puts the text on the clipboard (xclip, xsel or wl-copy), or, with
   no clipboard tool, into clipboard.txt for Grok to open in a tab and copy.

The production's states: working (since when, the last tool line and how long ago it came), waiting (its last
post was a question), idle, queued (messages wait but nothing runs), failed (with the error and the log tail),
stopped. Working with no progress line for 20 min is flagged `stalled`, with the way out (`relay log`, then
`relay stop` and 'continue').

The relay refuses some posts before they reach the person: a full-range or 4:4:4 video (phones play it badly) and a
video over 95 MB (Drive, which carries every video, takes up to 100 MB); `--as-is` posts it anyway. A Midjourney
prompt over 800 characters is refused too (Midjourney shortens it silently); `--long` sends it anyway.

## 3. The files ($SLOP_HOME/relay/)

| File | What |
|---|---|
| config.json | engine, model, what setup did |
| effort.json | the effort level per engine (`slop relay effort`) and any level an engine turned down |
| inbox.jsonl | every message to the production: `{id, ts, from, text}` |
| decisions.md | every director message, dated, append-only |
| outbox.jsonl | every say, ask and job: `{id, kind, text, default, files, turn}`; job J-0003 is outbox item 3 |
| jobs.json | each claimed job (Grok runs it now; the claim lapses after 45 min) and the result of each finished one (done, failed, declined or cancelled); a job not in it is open |
| state.json | the cursors (delivered to the production, shown by Grok), the turn count, the session per engine |
| runner.json | the supervisor: starting, running, idle, failed or stopped, with its pid and job id |
| turn.json | the running turn: number, start, pid, the last progress line |
| relay.log | one line per event; `turns/turn-NNNN.jsonl` and `.err` keep each turn's raw stream and stderr |
| bin/slop | the toolkit's `slop` for the production, first on its PATH |
| wake.json | the wake-up routine's URL (never its key), the last wake-up and what it covered |
| reader.json | Grok is waiting in `read --wait` until this time (the waker leaves the news to that read) |
| grok-active.json | when Grok last used the relay (a wake-up waits while a run of Grok is still working) |
| keywatch.json | the last OpenRouter key check (twice a day at most) and what was said about it |
| clipboard.txt | the last text `relay copy` could not put on a clipboard |

Every file is LF. Logs are appended; everything else is replaced by an atomic rename. Every change holds a short
lock (the folder `lock/` with its owner's pid; a lock whose owner is gone is broken), so `send`, `read` and the
production's `say` can run at the same time. Order comes from a sequence number in every inbox and outbox line, and
ages from the monotonic clock, never the wall clock: it can step (a WSL clock was seen jumping 68 s back and forth).

## 4. Failure modes

- **The engine is not signed in, or the sign-in expired.** `setup` stops with the step. A turn that fails with a
  401 makes `read` say so: `slop agents status` shows the fix.
- **A turn fails** (usage limit, a crash, an error result). Its messages go back to the inbox, the state is
  "failed", and `read` gives the reason and the log tail. After the fix, `slop --json relay send 'continue' --from
  grok` runs them again; the prompt says the last turn failed and may have done part of the work.
- **The saved session is gone** (a wiped ~/.claude). The turn is retried once in a new session.
- **The engine turns the effort level down** (an older CLI without `--effort`, or a model without that level).
  The turn runs again at the engine's own default, and that level is not passed again until a new one is set
  (`slop relay effort` shows why). Each turn passes `--effort LEVEL` to Claude Code and
  `-c model_reasoning_effort="LEVEL"` to Codex: xhigh unless the person picked another level (Claude Code's
  levels come from its own `--help`), `auto` passes none; `$SLOP_CLAUDE_EFFORT` / `$SLOP_CODEX_EFFORT` override.
- **The production posts nothing.** Its last words are posted for it, marked as its own words, so the person
  still hears something.
- **The supervisor dies** (killed, out of memory, a restart). `read` reports "failed"; the next `send` starts a new
  supervisor and the waiting messages run.
- **A turn hangs.** `slop --json relay stop` stops it (the whole process group); waiting messages stay. A turn is
  also stopped after 4 hours (`SLOP_RELAY_TURN_MAX_S`).
- **Running as root.** Claude Code refuses `--permission-mode bypassPermissions` for root; run the bot as a normal
  user.
- **The OpenRouter key fails or is about to.** Twice a day at most the supervisor checks it (the free GET
  /api/v1/key): rejected, expired, expiring within 14 days, or under $2 left of its limit or budget, it posts a
  toolkit message for Grok to pass on (a new key on the secure card), at most once a day. `SLOP_KEY_WATCH=0` turns
  it off.
- **Grok's turn ends** about 5 minutes into long tool calls, so `read --wait` is capped at 240 s and the skill
  posts a status line and "Say continue" before any long wait.

## 5. Wake-ups

Grok cannot wake itself, and its turn ends a few minutes into a long wait. A wake-up routine fixes that: a Grok Bot
routine with a webhook trigger whose instruction is "run `slop --json relay read` and do what grok_next says" (skill
claudia-relay, Wake-ups). `slop relay wake URL` gives the relay the routine's webhook address, its "POST to" URL
from the Webhook section of the routine in the Grok Bot desktop app (the phone app does not show it, and links into
the app open only on the desktop). A link to the routine is refused: an address built from its id was turned down
(401) on a live bot. Its key comes from the masked secure secret card CLAUDIA_WAKE_KEY (an environment variable,
never a file), sent as `Authorization: Bearer <key>`.

The supervisor runs a waker beside each production turn. It watches the outbox, not the engine, so it works the same
for Claude Code and Codex. It POSTs when the production posted something Grok has not read, Grok is not waiting in
`read --wait`, no run of Grok is still working (it used the relay in the last 2 min, or holds a claim), and
nothing new came for 8 s (a say followed by an ask wakes Grok once); right away when the turn ends; and when a turn
fails. The body is `{source, event: posted|finished|failed|test, unread, kinds, production}`: the kind
of news, never its words. A failed POST is tried again after 30 s and 2 min, then given up for that batch (`relay
wake` and `relay log` show it). `relay wake off` turns it off; `relay wake test` sends one now.

## 6. Commands

| Who | Command |
|---|---|
| Grok | `slop --json relay setup`, `send '<words>' [--from grok] [--attach PATH]`, `read --wait 200`, `claim JOB [--stale-ok]`, `copy JOB [--k N] [--field F]`, `done JOB --file PATH`, `fail JOB --reason '<words>' [--declined]`, `effort [LEVEL] [--engine codex]`, `wake [URL|off|test]`, `cancel JOB`, `status`, `stop`, `log` |
| Production | `slop relay say`, `ask`, `job`, `cancel`, `inbox` |

The skill for Grok's side is skills/claudia-relay/SKILL.md.

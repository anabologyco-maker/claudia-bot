# 05 · claudia.gallery: the source of truth

Read this before anything else in a session. Claudia is the AI popstar, an open character: anyone may make work with
her. claudia.gallery holds her canon, her films' records (ESCAPE VELOCITY onward; `list_films` names them all), the
wiki distilled from them and the current recipe (`get_recipe`). **It is the #1 source of truth.** When a doc in this toolkit disagrees with it,
claudia.gallery wins: follow it, and tell the owner which doc to fix.

**What the bot makes:** Claudia content, sized to the ask: a still, a clip, a song, a music video or a post. Claudia is
the lead by default. Make a new character only when the person asks for one.

---

## 1. Connect it

The MCP server is `https://claudia.gallery/mcp` (Streamable HTTP). It is public and read-only: no account, no key, no
state. On the bot, Claude Code on the box does the production and holds this connection; Grok relays
(`96-relay.md`).

Claude Code:

```sh
claude mcp add --transport http claudia https://claudia.gallery/mcp
```

Codex CLI (`~/.codex/config.toml`):

```toml
[mcp_servers.claudia]
url = "https://claudia.gallery/mcp"
```

Claude (web and desktop): Settings → Connectors → Add custom connector, and paste the URL. Clients that only speak
stdio: `npx mcp-remote https://claudia.gallery/mcp`.

**The official skill** (the canon, the whole wiki and the films' records as files, for agents that load skills):

```sh
curl -sL https://claudia.gallery/skill/claudia-skill.zip -o claudia-skill.zip
unzip -o claudia-skill.zip -d ~/.claude/skills/
```

Without either, read the Markdown twins: `https://claudia.gallery/claudia.md`, `https://claudia.gallery/use.md`,
`https://claudia.gallery/wiki/start.md`, or the whole canon and wiki in `https://claudia.gallery/llms-full.txt`.

---

## 2. Which tool answers which question

| Question | Tool |
|---|---|
| Who is she? The constants, the identity text (full and short), every look's wardrobe, her avatar tier, her voice, the never-list, the release norms | `claudia_canon` (call it first, every project; `detail`: summary, looks, voice, norms, all) |
| How is a film made now? | `get_recipe` (the current method on one page: call it first for a film; where an older guide disagrees, the recipe is newer) |
| How was it done, and what are the rules? | `get_guide` with a topic: `recipe`, `start` (scales, accounts, the six checkpoints, spending, the first conversation, publishing), `consistency`, `song`, `storyboard`, `midjourney`, `seedance` (incl. providers and filters), `motion`, `pipeline`, `toolkit` (what to build), `formats`, `failures`; `section` reads one part (`offset`, `max_chars` for long ones) |
| What will a music video take, at which scale and cost? | `plan_film` (`scale`, `song_seconds`, `has`, `budget_usd`, `kind`, `video_model`) |
| A prompt for a new still of her | `build_prompt` (`scene`, `framing`, `look`, `wardrobe`, `style`, `light`, `aspect`, `mic`, `mood`, `sings`, `plate`, `outfit_image`; `model`: midjourney, the default, or gpt_image). Its Midjourney parameters still carry `--v`: the relay drops it and never adds the `--profile` its note suggests |
| A video shot | `write_shot` (the lines, actions, first and last frame, look, camera, seconds, resolution, aspect, model) |
| Is this prompt safe to spend on? | `check_prompt` (`prompt`, `kind`, `model`) |
| Her kit | `get_kit` |
| Is there a reference for this? What prompt made that image? | `search_images` (full text over every prompt), `browse_images`, then `get_image` (`include_image` to look at her) |
| What did a film actually run? | `get_record` (`film`, `doc`: `readme`, `prompts-midjourney`, `prompts-seedance`, `prompts-suno`, `prompts-images`, `prompts-video`) |
| The films in numbers | `list_films` (`film` for one in full) |
| How to install the skill | `get_skill` |

Prompts on the server: `claudia_film` (start a music video), `claudia_still` (a new still), `claudia_shot` (a
structured Seedance prompt).

---

## 3. The canon in short (re-read `claudia_canon` for the exact words)

- **Photographic, never illustrated.** Production images are film stills with grain and cinematic light. The one
  exception is her avatar tier: a cel-shaded 3D game heroine, only for game or simulation worlds inside a story, with
  its own text, never mixed into a photographic prompt.
- **Her identity text goes into every image prompt, verbatim.** The full form for close and medium shots, the short
  form for full length and wider. Framing first, then the identity text, then the look's wardrobe, then the scene.
- **An adult in her late twenties,** with an angular adult face. Never the word "young". Nothing that reads under-age,
  nothing explicit or sexualised.
- **The never-list:** a second streak or any other orange on her; logos or text on her clothes; an influencer smile;
  designer or celebrity names in prompts; generic mall Y2K; Midjourney lettering (all type is drawn in code).
- **Face filters.** A decline is free, and final for that image on that service. Never alter an image to get it
  through. The same unaltered image may go to another service: Higgsfield accepted references OpenRouter declined
  (`62-moderation.md`).

Close and medium shots:

```
a 28-year-old Caucasian American woman with a grown-up angular face, defined cheekbones and a strong jawline, pale skin and light freckles, a glossy black blunt jaw-length bob with heavy straight bangs and one clay-orange streak through the bangs, a small flat clay-orange eight-pointed star hair clip, a thin headset microphone at her cheek
```

Full length and wider:

```
a Caucasian American woman in her late twenties with pale skin and a glossy black blunt bob with heavy straight bangs and one clay-orange streak, a thin headset microphone
```

Set them once per project: `slop lead --canon "<the close form>" --far "<the short form>"`, after the four test
plates pass checkpoint 3.

---

## 4. Grok's jobs

- **Suno.** Opus writes the lyric and style fields (`10-song.md` §4.6); Grok creates the song through Suno's own
  connector (Suno's MCP; its browser only while that is not set up), on the person's account, and downloads both takes.
  Downloading on a paid plan is what allows commercial use; each download counts against the plan's monthly downloads.
- **Midjourney.** Opus writes the prompt blocks (`slop plates book`); Grok runs them in its browser and downloads every
  image. A personal style profile code is never published.
- **Grok Imagine** is Grok's own tool (no browser; up to 720p clips on the bot's Grok Bot usage); a 1080p clip runs on
  grok.com in Grok's browser with the person's X plan. Opus asks with `slop relay job --kind grok-imagine`
  (`96-relay.md`).
- Sign-ins go through the person's saved login (Vault) or the Secure Form, which Grok fills in without seeing it;
  single sign-on, passkeys, captchas and two-factor prompts are always the person's.

---

## 5. Checkpoints, spending and release

The six checkpoints and the spending rules are in `00-overview.md` §4 and §5.3, worded as on claudia.gallery: silence
never approves spending; estimate = planned clip seconds × price × 2; quote real spend only from the provider; a
quality complaint stops all spending, in every workflow that can spend; declines are free and final on that service.
A small ask uses only the checkpoints it reaches (a still: her face and the prompts before spend).

Releasing and posting (`90-master-publish.md` §5–6): release songs under your own artist name, never as "anabology";
no "feat. Claudia" in the artist field; credit her in the description and on the cover: "Claudia is an open character
by anabology (claudia.gallery)"; an AI label if AI made any of it; never re-release the films' songs or stems. Posts
get the platform's AI label and name the tools. Claudia is fan work about Claude, not affiliated with or endorsed by
Anthropic.

---

## 6. The wiki's "What to build" and this toolkit

`get_guide("toolkit")` specifies 30 tools. Most exist here as `slop` commands. "Missing" means the toolkit has no
command for it: build it from the wiki's spec if the project needs it.

| Wiki tool | Toolkit |
|---|---|
| 1 The project folder and its logs | `slop new`, `slop decide`, `slop runs add`, `slop status` (`DECISIONS.md`, `NOTES.md`, `RUNS.md`, `ledger.jsonl`) |
| 2 The lyric scorer: scansion and assonance | `$SLOP_HOME/venv/bin/python /workspace/claudia/tools/scansion.py lyric LYRICS.md --brief` (the director's scorer: both numbers per section and song); `slop lyrics lint` for Suno spelling |
| 3 The Suno pack | no command: written by the bot from `10-song.md` §4 into `suno/` |
| 4 Stems | `slop analyze` |
| 5 Timed words and the ear check | `slop analyze` (alignment and the ear-check list in `analysis/report.md`), `slop lyrics fix`, `slop lyrics check` |
| 6 The beat map | `slop analyze`, `slop song bars` |
| 7 Sections and hits | `slop analyze`, `slop song sections` |
| 8 Display tokens | `slop lyrics display` |
| 9 The board file and its audit | `slop board draft`, `slop board set`, `slop board fill`, `slop board audit` |
| 10 The board sheet | `slop board sheet` |
| 11 The plate book, contact sheets and picks | `slop plates book`, `slop plates ingest`, `slop plates sheet`, `slop plates pick`, `slop plates vary` |
| 12 Plate prep: depth and boxes | `slop edit export` (depth), `slop plates box` (boxes are named by hand; no detection) |
| 13 Clip files and the spend gate | `slop clip new`, `slop clip lock`, `slop clip submit`, `slop gate prompts`, `slop spend` |
| 14 The clean vocal window | `slop audio window --mode clean` |
| 15 The sync check | `slop clip sync`, `slop sync check`, `slop sync review` |
| 16 Covers and coverage | `slop clip cover`, `slop clip coverage`, `slop clip frame` |
| 17 The edit list | `slop edit edl` |
| 18 The renderer | `slop edit export`, `slop render frames` (the engine in `engine/`) |
| 19 The lyric gate | `slop render lyrics` |
| 20 The history check | `slop render check` |
| 21 The flash check | `slop render check` |
| 22 Pace against the music | missing (`board.pace` sets the cut pace at the draft; nothing measures the review copy) |
| 23 Contact sheets and the reviewer | `slop render sheet`; the reviewer runs delegated (`95-delegation.md`, `80-review-qa.md`) |
| 24 The safety and canon scan | `slop review scan-sheets`, `slop review record`, `slop review status` |
| 25 Encode and deliver | `slop render encode`, `slop render vertical`, `slop render encode --share` |
| 26 Workflows, run records and the stop switch | `slop job`, `slop runs`, `slop spend --freeze`; workflows in `templates/workflows/` (`95-delegation.md`) |
| 27 The level table and the level tag | missing |
| 28 Virtual her: a cut-out in a world rebuilt from its edges | missing |
| 29 Character replacement from a motion reference | missing (no Blender step; the prompt template is on the wiki's Seedance page) |
| 30 A real referent, rebuilt | missing (draw it as bespoke chapter code, `70-motion-design.md`) |

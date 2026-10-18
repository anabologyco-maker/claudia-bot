# 90 · Master and publish: render, encode, loudness, vertical cut, labels, posting, scrub

From an approved edit to files the user can post. The rules here are short because each one was learned the hard way:
the reference master shipped mis-tagged and looked washed out in one player; a detached encode finished with nobody
told; one song patch after approval was nearly re-cut by hand; public material had to be scrubbed of the creator's
identity. Run `80-review-qa.md` §11 before this.

Command names follow the toolkit's CLI contract; exact flags: `slop <command> --help`. **Put the global flags first:**
`slop --json --project NAME <command> …`. That form works for every command; some command groups also accept
`--json`/`--project` after the subcommand and others reject them there (argparse prints "unrecognized arguments" and
exits 2).

---

## 1. Render the frames

```
slop render lyrics                     # must print N/N first (80-review-qa.md §3)
slop render frames --workers 4         # → render/frames/f00000.jpg … (frame i = song time i/24 s; default workers: min(4, CPUs/2), capped by free RAM at ~3.5 GiB each)
```

- **Resumable:** existing frames are skipped; each frame is written to a temp file and renamed (a crash never leaves a
  half frame). Re-running the same command continues.
- **Bounded memory:** each worker opens a fresh page every 200 frames; one retry per failed frame on a fresh page.
- **Run it as a tracked background job** and poll its progress, never a detached `nohup` that nobody watches ("nothing
  reports when a detached job finishes"). On Grok Bot: `slop --project my-song job start -- render frames --workers 4`
  prints a job id; repeat `slop --project my-song job wait ID` (at most 25 s a call) until it prints the result. The
  progress file (`$SLOP_PROGRESS_FILE`) gives the percent done and the time left; the command is over only when its
  state is `done`, `stopped` or `failed` (`stage_done` means one step of several finished).
- **Speed:** the reference renders ran 0.4–1.7 s per frame on one worker; EV's 7,354 frames took ~63 min with 3 workers on a
  4-CPU box (0.51 s/frame effective); SP's 4,598 frames ~20 min with 8 workers. Estimate before you start:
  `frames × ms_per_frame / workers`. A 3-minute song is ~4,300 frames.
- **Disk:** one cut's frames take ~2 MB each at 1080p (EV: ~9.6 GB for 5 minutes in colour). Check free space first
  (`df -h /workspace` on the box). After ffprobe has confirmed the master and the review copy (§2), free the disk with
  `slop --project my-song render clean` (it deletes the frames only once `out/master.mp4`, and the 9:16 cut if made,
  verify; `--dry` lists what it would delete, `--keep-master` keeps the master's frames for a re-encode; it refuses
  while another job of the project runs). Keep masters, clips, plates and audio.
- **Never render while the lyric gate is short of N/N, the safety scan has open blocks, or the owner has a pending quality
  flag.**

---

## 2. Encode: master and review copy

`slop render encode` writes the master and verifies it with ffprobe; `slop render encode --review` writes the review
copy. You never type the ffmpeg line; this is what `slop render encode` runs (from `slop/render/encode.py`), so you can
read its output and check it by hand:

```
# master (out/master.mp4): frames f00000.jpg … at the project fps, the song from project.json "song"
ffmpeg -y -framerate 24 -start_number 0 -i render/frames/f%05d.jpg -i audio/song.wav \
  -map 0:v:0 -map 1:a:0 -c:a aac -b:a 256k -shortest \
  -vf "format=rgb24,scale=flags=accurate_rnd+full_chroma_int+full_chroma_inp:out_color_matrix=bt709:out_range=tv,format=yuv420p,setparams=color_primaries=bt709:color_trc=iec61966-2-1:colorspace=bt709:range=tv" \
  -colorspace bt709 -color_primaries bt709 -color_trc iec61966-2-1 -color_range tv \
  -c:v libx264 -preset slow -crf 16 -pix_fmt yuv420p -movflags +faststart out/master.mp4

# review copy (--review → out/review.mp4): the same input, filter and tags, with
  -c:v libx264 -preset slow -crf 20 -maxrate 8M -bufsize 16M
# draft (--draft → out/draft.mp4, gaps allowed): -c:v libx264 -preset veryfast -crf 23
```

There is no `-tune grain` option in `slop render encode`. For a heavy print-look review copy that bands, encode by hand
with the same line plus `-tune grain` (manual encode only), then verify it with ffprobe yourself.

Why each part:
- **The colour conversion and tags.** The frames are sRGB. Converting through RGB with accurate rounding to BT.709 and
  tagging primaries BT.709 / transfer sRGB (`iec61966-2-1`) / TV range makes every player show the colours you rendered.
  An untagged or BT.601-tagged stream "looks lighter and washed out in QuickTime" ("stuff is v blown out"). The published
  EV master predates this fix and is tagged BT.601 with no primaries or transfer.
- **CRF 16** for the master: grain and halftone are expensive to encode (EV's colour print master was 1.73 GB, +75 % over the
  mono version). Clean/native looks are much smaller (SP master 245 MB, review copy 140 MB for 3:11).
- **The `setparams` step** tags the frames themselves as well as the stream, so filters and players agree.
- **`-movflags +faststart`** so it plays while downloading.
- **`-shortest`** so the video ends with the song (or the frames, whichever is shorter: render the whole range).
- **Container tags.** `slop render encode` does not pass `-map_metadata -1`. It does not need to for the song: ffmpeg
  copies global tags from the first input only, and the first input is the frame sequence. (Checked with ffmpeg 6.1 and
  a WAV tagged with a title and a comment: the master carried neither.) A hand encode that puts the song first would
  copy them, so add `-map_metadata -1` to any manual encode.

Then verify with ffprobe (`80-review-qa.md` §7: codec, size, 24/1, frame count = duration × 24, yuv420p, bt709 /
iec61966-2-1 / tv, AAC stereo) and run the flash check on the master (`80-review-qa.md` §5). The container-tag check is
the guard for identifying metadata: `ffprobe -v error -show_entries format_tags:stream_tags -of json out/master.mp4`
should show only `major_brand`, `minor_version`, `compatible_brands`, `encoder`, `language`, `handler_name` and
`vendor_id`. Anything else (a title, a comment, a song or job id): re-encode with `-map_metadata -1` by hand.

### 2.1 The chat copy (`slop render encode --share`)

Grok's chat takes files up to 200 MiB, and a CRF 16 master of a 5-minute song with real footage is usually bigger.
`slop --project my-song render encode --share` writes `out/share.mp4` under 190 MiB (`--max-mib`, at most 200):

- when the master is current (made from the frames on disk and the current song) and already fits, it is **copied**,
  in seconds, not re-encoded;
- otherwise it is a two-pass x264 encode at the size budget, with the master's colour tags, never at a higher bitrate
  than a current master (an out-of-date master is ignored, and the output says why and names `slop render encode`);
- the result is verified with ffprobe, its size included. `--vertical` makes `out/share-vertical.mp4` from the 9:16
  frames.

Send the chat copy; keep the master for posting.

---

## 3. Audio and loudness

- **Use the song as delivered.** Both reference videos shipped the Suno mix **unmastered**: EV's song measures
  **−15.7 LUFS integrated, LRA 6.3 LU**, and the master's audio measures the same (AAC 256 kb/s, 44.1 kHz stereo). Nobody
  complained about level.
- **Measure, don't guess:** `ffmpeg -i audio/song.wav -af ebur128=peak=true -f null - 2>&1 | tail -n 12` (integrated
  loudness, LRA, true peak). Put the numbers in the run report.
- **Do not normalise by default.** Streaming platforms turn loud tracks down to their reference (around −14 LUFS on the
  large video platforms) but rarely turn quiet ones up, so a −15.7 LUFS song plays ~1.7 dB quieter than a −14 LUFS one.
  That is acceptable. If the user asks for louder: a two-pass `loudnorm` to −14 LUFS integrated with true peak ≤ −1 dBTP,
  on a copy, and compare by ear before replacing. Never clip.
- **Sample rate:** keep the delivered rate for analysis; the encode resamples to 44.1 or 48 kHz AAC.

### 3.1 A song patch after approval (time-map, don't re-cut)

SP's owner approved v1 ("its perfect. change nothing.") and then re-sang one word in Suno's editor at its three
occurrences. Rules learned:

1. **Export with BPM lock OFF.** The first export (lock on) re-timed the whole song by up to 0.7 s — unusable (cuts up to
   ~1.6 s off the beat).
2. **Diff the new export against the old by spectrogram** before trusting "nothing else changed". The second export
   matched sample-exactly outside the three words (1.7 dB louder) and added 19 ms at the first word and two beats
   (~0.92 s) after the second and third.
3. **Keep the timeline keyed to the original analysis** (beat map, hits, word times, clip times). Do **not** re-run
   `slop analyze` on the new song. Write `edit/timemap.json`: piecewise-linear segments `[new_t0, new_t1, old_t0,
   old_t1]` from the new song's time to the approved timeline's time, in one object with a `segments` key (a bare list
   is not read). SP's real file (19 ms added at word 1; two beats, ~0.92 s, added after words 2 and 3):

   ```json
   {"segments": [[0, 56.95, 0, 56.95],
                 [56.95, 59.569333, 56.95, 59.55],
                 [59.569333, 105.815333, 59.55, 105.796],
                 [105.815333, 107.686063, 105.796, 106.748],
                 [107.686063, 176.632062, 106.748, 175.694],
                 [176.632062, 191.569458, 174.782604, 189.72]]}
   ```

   Row 2 stretches the first word by 19 ms; row 4 plays a shot's last two beats at half speed into the next hit
   (107.69 s); row 6 replays two outro beats (the jump lands on a beat flash). The new song is 191.57 s long; the
   approved timeline ends at 189.72 s.

   Each segment maps new-song time `t` in `[new_t0, new_t1)` to `old_t0 + (t − new_t0)·(old_t1 − old_t0)/(new_t1 −
   new_t0)`; times past the last segment use the last one. The segments must cover the new song from 0 to its end.
4. **Render and encode against the new song**, in this order:
   1. copy the new song to a new file (e.g. `audio/song-v2.wav`) and set `"song": "audio/song-v2.wav"` in
      `project.json`; keep `analysis/` as it is;
   2. `slop render frames --timemap`: it renders the **final** song's length (the time map's end, else the new audio's
      length; a longer song needs no change to `analysis/beats.json`) and draws each frame at its mapped old time.
      Frames left from the old cut are discarded and redrawn automatically (they were drawn from other inputs), so no
      `--force` is needed; a `--to` past the end is clipped with a warning;
   3. `slop render encode` (it takes the length the frames were rendered for), then `slop render encode --review`.
5. Re-run the lyric gate and the flash check on the new master, and re-measure every cut and flash against the new mix's
   beats by ear and on a contact sheet.
6. Captions that end near a replayed stretch must fade before it, or they "blink back" in the second pass.

---

## 4. Vertical cut (9:16)

The reference videos were released 16:9 only, so this section is a recommendation, not a measured recipe. Keep every
16:9 rule; add these:

- **Render the vertical through the engine** (`slop render vertical`, 1080 × 1920 → `out/vertical.mp4`; the default
  `--method rerender` lays the page out in portrait), not by cropping the 16:9 master: a 9:16 crop of a 1080p frame is
  only 608 px wide and goes soft when scaled up, and the type would be laid out for the wrong frame. `--method crop` is a
  fast preview only (`out/vertical-crop.mp4`).
- **The hook cut is full quality:** `slop render vertical --from 5.5 --to 7.2` renders just the stretch you post, at the
  master profile, to `out/vertical.mp4` (it replaces a whole-song 9:16 cut there; `out/vertical.mp4.inputs.json` records
  the stretch, so `slop render encode --share --vertical` makes `out/share-vertical.mp4` of that stretch with its audio
  from the stretch's first frame, and warns when the stretch is stale, naming the `render vertical --from/--to` to
  re-run). Only `--every N` or `--allow-missing` make a
  draft preview, to `out/vertical-draft.mp4`. The Studio run's first hook cut came out at draft quality before this.
- **Footage:** cover-fit each shot centred on the subject, the centre changed only at cuts or with the shot's own camera
  move. The engine centres on the subject's box (`subject`, then person labels, then `a face`) from `PLATES` boxes or
  clip tracks. **The toolkit detects no boxes by itself** (`70-motion-design.md` §5.0), so without named boxes every shot
  is centred on the middle of the frame. For each shot whose lead is off-centre, name the lead box on its plate:
  `slop --project my-song plates box p004 --label subject --uv 0.40,0.15,0.25,0.70` (then `slop edit export`), or
  reframe it in chapter code. A two-shot that cannot fit both people gets a cut or a push, never a squeeze.
- **Layers in portrait:** `slop render check --layers --vertical` checks every shot's mid-point frame in the 9:16
  layout (≥ 3 ordered layers) and writes `render/layers-vertical.json`.
- **Type:** re-lay out every lyric block for the vertical frame: lyric ≥ 48 px, hung from the left margin; keep it out of the
  platforms' UI zones (roughly the bottom 20 %, the right 12 % and the top 10 % of the frame are covered by captions,
  buttons and headers on the major vertical feeds; check the current overlays before release).
- **Length:** 15–60 s cuts from the strongest stretch (the hook, then the chorus). Start on a downbeat with a strong
  frame, end on a hit. A last frame that matches the first loops cleanly (SP's last frame was its first frame by design).
- **Gates again on the vertical:** lyric gate N/N for its range, flash check (`slop render check --skip-history --video
  out/vertical.mp4`), ffprobe (1080 × 1920, same colour tags).

---

## 5. AI-content labelling

The videos are AI-generated by design: you know it's AI and it works anyway. Say so plainly; never hide it.

- **Platform switches.** Turn on each platform's AI or synthetic-content disclosure when the video contains realistic
  generated people or scenes (the large video platforms ask this on the upload form; the short-video apps have an
  AI-generated-content toggle). The forms change: look at the current upload form, and if in doubt, disclose.
- **In the post text:** one line naming the tools, e.g. "Made with AI: Midjourney stills, Seedance video, a Suno song;
  animated and edited in code."
- **Claudia's credit** (claudia.gallery's norm), in the description and on any cover: "Claudia is an open character by
  anabology (claudia.gallery)". Never present the work as an official Claudia or anabology release.
- **Anthropic.** Claudia is fan work about Claude. Where it could be misread, say so: not affiliated with or endorsed
  by Anthropic, whose names and marks are theirs.
- **In the video:** keep generated likenesses of real people out (claudia.gallery's norm; quote their words as text,
  with the source). If the owner opted in (`62-moderation.md` §6), a likeness appears only inside a post card labelled
  **AI IMAGE**, never speaking,
  with their own dated words (`70-motion-design.md` §5.1). If the singer's voice is generated, a chip like "AI PERSONA ·
  THIS VOICE DOES NOT REPRESENT A REAL PERSON" can be part of the design (SP opened on exactly that).
- **Tool terms.** Commercial use of generated media depends on the user's plans: Suno's download from the user's own
  account is the licensing step (check their plan's commercial terms); Midjourney and the video providers have their own
  terms. The bot cannot verify these; tell the user to check before monetised posting.

---

## 6. Posting copy

Keep it short and checkable. A template:

```
TITLE (SUBTITLE)

<one sentence: the premise, in the song's own voice>

by <pseudonym> · made with AI: Midjourney · Seedance 2.5 · Suno · animated in code
Claudia is an open character by anabology (claudia.gallery)
<how it was made: link to the making-of, if published>
```

- Lead with the hook frame or the first 2–3 seconds; the first second must read on a muted phone (`70-motion-design.md`
  §10.1).
- Quote the hook, not a verse joke: in EV's replies the hooks were quoted 11–26 times each, each verse joke about once.
- Credit the user **only by their chosen pseudonym**, plus Claudia's credit line. No real names, no handles other than
  theirs, no personal data.
- No job ids, file names, prompt dumps or tool screenshots with account names in the post.
- Thumbnails and covers (optional): 1280 × 720 thumbnails and 3000 × 3000 covers built only from the video's own plates,
  mattes, grade, fonts, colours and words; keep the bottom-right 200 × 80 px of a thumbnail clear (the player draws the
  duration there); check that no title is hidden (two of SP's four thumbnails hid part of their titles). Credit only the
  pseudonym, plus Claudia's credit on a cover.

### 6.1 Making-of package (optional, it travels well)

The reference making-ofs were: `README.md` (story, stack table, step by step, what worked and what didn't, measured
numbers and costs), `direction-log.md` (every owner message verbatim, timestamped as "+h:mm since the first message", each
followed by "→ what happened next"), `orchestration.md` (workflow scripts verbatim), `prompts-midjourney.md`,
`prompts-seedance.md`, `prompts-suno.md`, a PDF of the README, a few images. Scrub it (§8) and have it read twice by fresh
eyes for privacy before release.

### 6.2 Releasing the song (claudia.gallery's norms)

She is open to musicians: songs with her may be released. The norms:

- **Release under the owner's own artist name.** Never upload as "anabology" (the director's artist profile), and never
  present it as an official Claudia or anabology release.
- **No "feat. Claudia" in the artist field.** Streaming services match artist names to profiles, so the credit would
  merge into unrelated artists called Claudia.
- **Credit her in the description and on the cover:** "Claudia is an open character by anabology (claudia.gallery)".
- **An AI label if AI made any of it** (vocals, music or lyrics); human-made work needs none. With Suno, downloading on
  a paid plan is what allows commercial use (`10-song.md` §8).
- **Make your own songs.** Never re-release the songs of ESCAPE VELOCITY, CLODYSSEY, BLISS or AIRPLANE MODE, or their
  stems. A project that tests the toolkit on a film's song keeps every output private.

---

## 7. Template Rewards (if the user is promoting a template)

X's **Grok Bot Template Rewards Pilot** (terms effective 2026-09-25; facts from secondary sources, the primary pages could
not be fetched — check them) pays discretionary rewards to template creators. What matters when posting:

- It is **invite-only**. Eligibility includes being 18+, a US resident in a state where X Money works, an X Premium tier,
  an X Money account, and accounts in good standing.
- Rewards are evaluated **every two weeks** and depend on **how many people use the template and how consistently they come
  back**. The creator's own usage, linked accounts, platform staff and free-trial users do not count. It is not a revenue
  share; amounts are not disclosed.
- **Promotional posts on X need X's paid-partnership label** and must stay **public and unedited for at least 30 days**
  after any pay period they helped qualify for. So: when the user posts a video *to promote the template* (the post links
  or names the template), turn on the paid-partnership label, and do not edit or delete that post for 30 days.
- **Prohibited:** inflating usage, multiple accounts, copying or impersonating other templates. Payments can be clawed back.
- A video post that does not promote the template needs no partnership label; it still needs the AI disclosure (§5).
- Never post on the user's behalf without their explicit "yes" for that post.

---

## 8. Scrub rules for anything public

Apply to posts, making-ofs, thumbnails, repositories and shared templates. Verbatim essentials of the reference project's
scrub rules, generalised:

1. **Credit only the chosen pseudonym** (and the pronouns the user chose for it). Never their real name, initials in any
   form, surname, email or handles other than the pseudonym.
2. **Remove:**
   - Midjourney `--profile` codes, job ids and job URLs (Midjourney images carry their job id in XMP metadata: strip it);
   - video/image/music provider job ids, media ids, share links, account names and emails;
   - API keys and tokens (and any `.env` content);
   - machine and host names, IP addresses, network names → say "a cloud server", "a render box", "a home GPU";
   - file paths that contain a host name or a user name;
   - clock times of day → elapsed time ("+4:05", "that night");
   - location hints;
   - employer, startup or investor hints — **and any private rule that would reveal them, including a project's taboo
     words: omit those rules entirely, do not quote them.**
3. **Quotes from the owner stay verbatim** (typos included); replace only the identifying bits with `[redacted]`.
4. **Numbers are measured, not guessed;** say where each comes from (provider billing, the run record, ffprobe).
5. **Strip file metadata:** re-encode images for publication (generator downloads may embed prompts or parameters) and
   check audio/video container tags (`ffprobe -show_entries format_tags`); a downloaded song file can carry the
   generator's song id.
6. **Real people:** only their own public, dated words; likenesses only inside labelled AI IMAGE post cards; nothing
   degrading or sexual.
7. **Two fresh-eyes privacy reads** of anything long before it goes out.
8. A last mechanical pass, for example:

```
grep -rniE '<real name>|<initials>|--profile [a-z0-9]+|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}|@[a-z0-9.-]+\.(com|net|org)|/home/[a-z]|C:\\Users' making-of/
```

Fill in the placeholders with the user's identifying strings; expect zero matches.

---

## 9. Licences and rights to state (if asked, or in a making-of)

- Fonts shipped with the toolkit are **OFL** (licence texts in `engine/fonts/`). The rendered video is output and is not
  affected by font licences either way.
- Depth maps come from **Depth-Anything-V2-Small (Apache-2.0)**; stems from htdemucs (check the weights' terms before
  redistributing them; the toolkit does not ship weights). *Reference pipeline only, not shipped in the toolkit:* the
  reference videos' mattes came from BiRefNet (MIT) and SAM 2.1 (Apache-2.0); state those only if your project added
  mattes from them.
- Song, stills and clips: under the user's own plans with each provider (§5).
- Third-party reference photos (if the user allowed any): record their licence and credit (e.g. CC BY with attribution).

---

## 10. Delivery checklist

- [ ] lyric gate N/N on the film (and on the vertical, if made)
- [ ] safety and canon scan: zero blocks; fixes resolved
- [ ] master + review copy encoded with BT.709 conversion and tags; ffprobe verified; container tags clean
- [ ] flash check passed on the master (and the vertical)
- [ ] loudness measured and written in the report; no clipping
- [ ] the chat copy made (`slop render encode --share`) and verified, under 200 MiB
- [ ] frames deleted after verification (`slop render clean`); masters, clips, plates, audio kept
- [ ] AI disclosure set per platform; post text names the tools
- [ ] Claudia's credit in the description (and on any cover); a song released under the owner's own artist name, no
      "feat. Claudia", none of the films' songs or stems (§6.2)
- [ ] paid-partnership label on template-promoting posts (if in the rewards pilot); 30-day no-edit noted
- [ ] public text scrubbed (§8); real-person rules respected
- [ ] the owner said "yes" to each post before it went out

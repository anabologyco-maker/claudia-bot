# 60 · Video clips (Seedance 2.5 and friends)

A **clip** is a generated video, 4–8 s when sung and 4–12 s for motion, made from a plate and conditioned on the song.
Clips are where the money goes and where most quality is won or lost. This file covers what to send, how to write the
prompt (never a caption: the **short sung form** for lip-sync windows, a **screenplay** for motion and acting, §4), how
to cut the audio windows, which provider and model to use, what it costs, and the order of work.

Read first: `40-storyboard.md` (shots, clips and windows are planned there), `50-plates-midjourney.md` (plates).
Next: `61-lipsync.md` (measuring sync, cuts, covers), `62-moderation.md` (declines and filters).

**Files** (ARCHITECTURE §3.2, §4.6):

| File | What |
|---|---|
| `clips/<clip>.json` | one per clip: `{id, shot, kind: "sung"\|"motion", status, provider, model, start, song_t0, needed, words, window{t0,t1,mode,file,url}, body{prompt,duration,resolution,aspect_ratio,generate_audio}, takes[], covers[], why}` |
| `clips/<clip>/take-N.mp4` | every take, never overwritten |
| `audio/windows/<clip>.mp3` (+ `.wav`) | the clip's `@Audio1`: a clean vocal window (sung) or a mix window (motion) |
| `analysis/words.json`, `beats.json`, `hits.json` | the clock: word, beat, kick, snare and impact times |
| `ledger.jsonl` | every paid submit (estimate) — real spend comes from the provider (`slop spend`) |

`status` moves `draft → locked → submitted → delivered`, or ends `declined` / `failed`. **Nothing spends unless the clip
is `locked` and the command has `--yes`** (or the project gate `prompts_approved` is set by the owner).

**Commands** (gen module; §9 gives them in order with one example each). The global flags `--json` and
`--project NAME` go **before** the command: `slop --json --project my-song clip status W02`. The verbs:
`slop clip new` (draft a clip: window, words, prompt scaffold; sung clips get the short form, motion clips a
screenplay) · `slop clip set` (change it) · `slop clip lock` (also warns when a sung prompt is long, §4.0) ·
`slop gen host` / `slop gen tunnel` (HTTPS hosting for `@Audio1`) · `slop gate prompts --approve` (G5) ·
`slop clip submit --dry-run` (the exact request, its estimate and every problem, nothing sent) ·
`slop clip submit --yes` · `slop clip poll` · `slop clip ingest` (Higgsfield results and refusals) · `slop clip sync` ·
`slop clip coverage` · `slop clip cover --make` · `slop clip list` / `slop clip status`.

---

## 1. The lesson that cost ~830 credits: the prompt is the product

On *Clodyssey (Superpersuasion)* (SP) the first round of clip prompts was written by agents inside a multi-agent
workflow: one paragraph each, a pose, a camera move and the plate's look, 31–163 words (median 50), **no timestamps**.
The takes came back as people posing. QA agents marked most of them "keep" because they checked each take against its prompt, and the prompts
asked for very little. About **830 Higgsfield credits** were burned on that round and thrown away.

anabology's verdict (verbatim): "these prompts are really really bad and wasting money and need to be 10x better and
super context aware of the story" · "EVERY prompt needs to have litearlly timestamps, extremely detailed motion
descriptions / blocking descriptions, it all needs to be deeply integrated with the story" · "make all new ones".

What fixed it, and what this toolkit requires:

1. **The lead writes every clip prompt, in one context**, with no sub-agents: the storyboard, a contact sheet of every
   start plate, and the exact word and hit times of every window loaded at once. SP's lead wrote 101 prompts in
   about 25 minutes this way (median 164 words, every one timestamped). Never fan prompt-writing out to helpers or to a
   cheaper model; a cheap step may only **submit** a request file verbatim.
2. **The owner reads the whole prompt book before anything spends** (gate **G5**, `00-overview.md` §4). Spending
   starts only after the owner says go, recorded with `slop gate prompts --approve --note "<the owner's words>"` (sets
   `gates.prompts_approved`) and `slop decide "<the owner's words>" --by owner` (`DECISIONS.md`). SP's v1 cut from the
   hand-written book got: "its perfect. change nothing."
3. **When the owner flags quality, stop every path that can spend** — running batches, routines, helper jobs — before
   discussing anything else.
4. **Don't review bad takes when the prompts were the fault.** Rewrite the prompts and re-make ("please don't. make all
   new ones").
5. **QA checks the take against the story**, not against the prompt (§10).

**The second lesson, measured later: the screenplay fixed the story, not the lips.** On sung (lip-sync) windows the long
timestamped screenplay copied our vocal far less often than a short prompt: the model performed the text and re-sang
the line in its own timing. So the rule is **screenplay for acting and motion, short for copy** (§4.0, the numbers in
`61-lipsync.md` §1.1). The story of a sung shot lives in the book entry's `story:` line, the plate and the motion clips
around it, not in the sung prompt.

---

## 2. The three kinds of clip and their inputs

| Kind | `@Image1` | `@Audio1` | Prompt head | `generate_audio` |
|---|---|---|---|---|
| **Sung window** (lip sync; id `W…` or `SD…`) | the plate of the singer, as a **reference image** (never a first frame) | a **clean vocal window**: only the words she sings on camera, everything else muted (`61-lipsync.md` §2) | `@Image1 sings @Audio1. She lip-syncs to @Audio1 exactly, every word in time: "<exact words>".` | **on** (the sync check needs the clip's own soundtrack) |
| **Motion clip** (id `M…` / `SX…`) | the plate as a **reference image** (the default); a first frame only with `--frame first`, which loses `@Audio1` on OpenRouter (§2.2) | a **mix window** starting on the shot's first frame (for timing and energy) | `The scene from @Image1, moving in time with @Audio1.` (reference, the default) · `Moving in time with @Audio1.` (first frame) | **off** (avoids copyright-audio refusals; see `62-moderation.md` §5) |
| **3D camera move** (id `V…`, Director tier) | the plates as references (`@Image1..3`) for the look | the mix window | `The camera follows the motion of @Video1 exactly.` with a rough previz render as `@Video1` "for the camera path only" | off |

### 2.1 Start images

- **Send the picked plate as it is: colour, ungraded.** The grade happens in post, one LUT per clip from sampled frames
  (`70-motion-design.md`). EV pre-graded its references to a mono print look and **32 of 59 clips came back near-grey**
  (a 3.5 h colour rework): "a look applied at generation time is baked in".
- **Two clips never start from the same frame.** The k-th clip on a plate uses the plate's k-th other Midjourney
  candidate (`50-plates-midjourney.md` §11); after that, the previous clip's last frame.
- A cover (`61-lipsync.md` §6) starts from **the frame of its parent take at the cut**, sent unaltered as a
  **reference image** (never as an OpenRouter first frame: that would drop the cover's `@Audio1`).
- Images ≤ 3 MB go inline (data URL); bigger ones are hosted. OpenRouter caps a request at about 32 MB. **Audio is never
  inline**: OpenRouter takes it by HTTPS URL only (§6.3).
- **Never alter an image to get it past a provider filter** (`62-moderation.md`).

### 2.2 Reference image (the default) or first frame?

**Reference mode is the default for every clip, sung and motion.** On OpenRouter the plate goes in `input_references` as
`{type: "image_url"}` (= `@Image1`) and the window as `{type: "audio_url"}` (= `@Audio1`), with **no `frame_images`**.
That is exactly what EV's sung clips sent. On Higgsfield the plate goes in `image_references` (it is `@Image1` when there
is no start image) with the window in `audio_references`. `slop clip new` drafts every clip this way.

- **First-frame mode drops `@Audio1` on OpenRouter** (verified with paid probes, 2026-10-01). When `frame_images` is sent,
  OpenRouter silently ignores every `input_references` entry, the audio window included. The take makes its own
  soundtrack (copy NCC ≈ 0.015), so the clip gets **no music conditioning at all**.
- So **sung clips never use a first frame** (`slop clip new` and `slop clip lock` refuse it, and so do covers).
- A **motion clip** may use a first frame only when the exact opening composition matters more than moving on the music:
  `slop clip new s014 --kind motion --frame first`. On OpenRouter the toolkit then does not send the window at all. Put
  the timing into the prompt in words (kick times from the timing sheet, §4.3), and expect the motion to ignore the beat.
- Cheap models that take only a first frame on OpenRouter (Wan 3.0, Grok Video 1.5, §6.4) get no audio either. Treat
  them the same way.
- On **Higgsfield** a `start_image` and an audio reference can go together: SP's `W07` take 2 had a start image, a
  character reference and the vocal, and copied the vocal (NCC 0.49). Then the start image is `@Image1` (§2.3).
- In reference mode the model recomposes the plate, and the face is free to perform. A face close-up that is refused as a
  first frame can still render as a reference (SP: two weeping close-ups failed as first frames on both providers, then
  rendered on Higgsfield as references, unaltered). Prompts in reference mode open with `The scene from @Image1, …`
  (motion) or the sung head.

### 2.3 How references are numbered

- OpenRouter: `input_references` images are `@Image1, @Image2 …` in order (the plate first); audio `@Audio1`; video
  `@Video1`.
- **Higgsfield: the `start_image` is `@Image1`**, then `image_references` continue the count. A clip with a start frame
  and one character reference calls the reference **`@Image2`** (SP `W07`: `@Image2 sings @Audio1 …`). Order the media
  `start_image → image_references → video_references → audio_references`.

---

## 3. Audio windows (rules)

Every clip has an audio window `[song_t0, song_t0 + duration]`. The audio window is also the clip's clock: **clip time 0
= `song_t0`**, so prompt timestamps are song events minus `song_t0`.

### 3.1 Sung windows

1. **Length 4–8 s, whole seconds.** For a planned window, `duration = clamp(ceil(needed_end − song_t0 + 0.3), 4, 8)`:
   the end of the last needed word plus 0.3 s, rounded up (this is what `slop clip new` computes). Never sing more than
   8 s in one clip (sync drifts late in long clips). Plan a longer sung passage as a **chain of windows with alternating
   framings** (CU / MCU / MS / profile / over-the-shoulder), so a cut between them, or a cover, looks designed.
   `slop clip new` warns when the needed span runs past the window and prints the command for the next window.
2. **Start in a word gap**, never mid-word. The rule (EV's `gap_start`): take the gaps between consecutive aligned words
   that are ≥ 60 ms (plus the gap before the first word); use each gap's midpoint (for gaps longer than 0.5 s, no later
   than 0.12 s before the next word); pick the **latest** such point in `[t − 1.6 s, t − lead]`, where `t` is the first
   needed word and `lead` = 0.3 s for planned windows (0.25 s for covers). If none, the latest point ≤ `t − lead`; else
   `max(0, t − lead)`.
3. **Quote ALL the words in the window**: every aligned word that **starts** in `[song_t0 − 0.02, song_t0 + duration −
   0.08)`, in order, with the lyric sheet's spelling and punctuation, numbers and acronyms as sung ("A G I"). Quote only
   **her** words when other voices are muted out of the window.
   *Why:* EV take A's window held "…the underclass. Lock in," but its prompt quoted only up to "underclass": it diverged
   inside "underclass". The cover that quoted its window exactly held its whole 5 s.
4. **On Higgsfield: keep the last needed word ≥ 0.8 s before the window end** (or add 1 s to the duration). Higgsfield
   takes often land late, by up to ~0.8 s, and are only ~4.04 s long for a 4 s request, so the last ~0.7 s of the window
   can fall outside the take. `slop clip new … --provider higgsfield` warns when this rule fails. On OpenRouter (lag
   ≈ 0 ± 60 ms on EV) the 0.3 s tail in the duration formula (rule 1) is enough.
5. **Place the words where the face can sing them.** If the blocking has her arrive, turn or fly in first, the vocal must
   start after she is in place. SP `W07` failed while the words sat at clip 0.3–1.9 s "while she was still in flight";
   it synced once the vocal was moved to clip 1.70–3.50 s of a 5 s window.
6. Prefer to end the window in a word gap too. If a word starts inside the window, it is quoted even if the window cuts
   it (SP's `"… Your P"` is the cost of a badly placed end).

### 3.2 Motion windows

- Start exactly at the shot's first frame (**no pre-roll**): motion clips play 1:1 in song time.
- 4–12 s (EV's longest was 11 s); whole seconds.
- The audio is the full mix (mono, 44.1 kHz). Seedance does **not** copy a mix into its soundtrack, so motion clips play at
  lag 0 unless a sync check measures a copy.

### 3.3 Making the windows

**`slop clip new` cuts the window for you.** It picks the start in a word gap (rule 2), computes the duration (rule 1),
cuts the clean vocal window for a sung clip (`61-lipsync.md` §2 has the exact recipe) or the mix window for a motion
clip, writes `audio/windows/<clip>.wav` (for OpenRouter) and `.mp3` (for Higgsfield), quotes the window's words in the
lyric sheet's spelling, and records all of it in `clips/<clip>.json`:

```
slop clip new s005 --kind sung        # sung window for storyboard shot s005 (clean vocal, reference mode)
slop clip new s014 --kind motion      # motion clip for shot s014 (mix window from the shot's first frame)
```

Only for a window you place by hand (a cover you plan yourself, a vocal moved later in the window, rule 5):

```
slop audio window W02 --t0 8.56 --t1 12.56 --mode clean --words "Why would I deceive you?"
slop clip set W02 --audio audio/windows/W02.wav --audio-mode clean
```

`slop clip set <clip> --song-t0 <s> --duration <n> --recut` moves a window and re-cuts it. Audio for OpenRouter must be
reachable by **HTTPS** (§6.3).

---

## 4. Prompt grammars: short for sung windows, the screenplay for the rest

Two grammars, one rule: **screenplay for acting and motion, short for copy.**

| Clip | Grammar | Drafted by |
|---|---|---|
| **Sung window** (lip sync) and its covers | **the short sung form** (§4.0) | `slop clip new SHOT --kind sung` (the default) |
| **Motion clip**; a sung shot played as an **acting moment** (an entrance, a whisper with a reaction), with a cut-away ready | **the screenplay** (§4.1) | `slop clip new SHOT --kind motion`; `slop clip new SHOT --kind sung --style screenplay` |

### 4.0 The short sung form (every sung window, by default)

A sung take is in sync only while the model **copies** `@Audio1` (`61-lipsync.md` §1), and a long prompt competes with
the audio: the model performs the text and re-sings the line in its own timing. The short form is the head quoting
every word, one line of framing and light, at most 2 timed beats and the closer:

```
@Image1 sings @Audio1. She lip-syncs to @Audio1 exactly, every word in time: "<every word in the window>".
<Framing> of the woman from @Image1 (<canon tags>), <how she sings the words>. <Light>. <Camera>.
[<a.aa s (the sound)>: <one small action>.]
[<b.bb s (the sound)>: <one small action>.]
One continuous shot, no cuts, no head turns. Only she sings. No text, letters or logos.
```

1. **The head, verbatim, quoting every word** that starts in the window (§3.1 rule 3; her words only when other voices
   are muted out of the window).
2. **One line of framing and light**, the camera at its end: the framing, the canon tags, how she sings (`facing the
   lens, eyes closed, deadpan` · `full voice, her head tilting back on the long notes`), the light in physical words,
   one quiet camera (`Locked camera, very slight push in`). No place essay, no story sentence, no second person's
   action: the story goes in the book entry's `story:` line (§4.2).
3. **Timed beats: none, one or two**, only when the moment needs them (a head tilt on the long note, a light change on the
   drop), on real times from the timing sheet (§4.3). EV `SD08` and SP `W02` take 1 had none.
4. **The closer:** `One continuous shot, no cuts, no head turns.` · `Only she sings.` (add `anyone else keeps their mouth
   closed` when someone else is in frame) · `No text, letters or logos.`
5. **About 90 words or fewer** besides the quoted lyric. `slop clip lock` **warns, and still locks**, when a sung prompt
   runs past ~90 words or has more than 2 timed beats (`slop clip submit --dry-run` repeats it); the warning quotes the
   measured copy rates below.
6. **The plate:** her mouth fully visible (frontal or three-quarter), nothing in front of it: no held or stand
   microphone, hand, hair or prop at her lips (`c06` below held 26 % with either prompt: a microphone covered her mouth
   on the plate). A canon headset microphone stays, at her cheek and clear of her lips (`50-plates-midjourney.md`).

**Measured** (share of the window's sung seconds in sync; the same window and clean vocal, retaken with the short form):

| Window | Long timestamped screenplay | Short sung form |
|---|---|---|
| `c01` (Studio run, EV chorus; short retake on OpenRouter) | **0 %** (2 OpenRouter takes + 1 Higgsfield draft) | **78 %** (2.24 of 2.87 s) |
| `c04` (Studio run) | 13 % | **29 %** |
| `c06` (Studio run) | 26 % | 26 % (the microphone at her mouth, rule 6) |
| SP `W02` (Higgsfield) | 28 % | **100 %** |

Across the Studio run's chorus (14.76 sung seconds) the long prompts held **44 %** (v1); three short retakes raised it to
**≈ 62 %** (v2). EV's original short template copied on 41 % of its sung takes. One probe did not improve (a phase-2 test
window on OpenRouter, n = 1, `61-lipsync.md` §1.1), so measure every take as before.

**Why both grammars stay.** The screenplay won the story on SP (§1) and is still how motion clips, the board and the book
are written. A sung window has one job, copying `@Audio1`. So: **screenplay for acting and motion, short for copy.** A
sung shot that must act can still take the screenplay (`--style screenplay`): measure it and have the cut-away ready
(`61-lipsync.md` §8).

**When a sung window does not copy, try the short form first.** If its takes came from a long prompt, rewrite it short
and retake on the same provider before anything else (`c01`: 0 % → 78 %); `slop clip sync` prints this as its `first:`
line when a take held under half its sung seconds and the prompt is past the limits. Then the routing rule: **2 OpenRouter
non-copies** of the short form → a Higgsfield 480p draft (finalize it if kept) → else cut away (§6.5,
`61-lipsync.md` §8).

A filled example (the EV line in this form; an illustration, not a measured take):

```
@Image1 sings @Audio1. She lip-syncs to @Audio1 exactly, every word in time: "Lock in, baby, foot down on the gas.".
Close-up of the woman from @Image1 (black bob, one orange streak, star clip), facing the lens, singing with her eyes closed, her head tilting back slightly on the long note. Warm light from the side. Locked camera, very slight push in.
1.62 s (downbeat): she opens her eyes on the lens.
One continuous shot, no cuts, no head turns. Only she sings. No text, letters or logos.
```

### 4.1 The screenplay grammar (motion clips and acting moments)

Every motion prompt (and a sung acting moment) is one beat of a screenplay, written against the clip's own clock. Eight
parts, in this order:

1. **[Sung acting moments only] the singing head**, verbatim:
   `@Image1 sings @Audio1. She lip-syncs to @Audio1 exactly, every word in time: "<exact words>".`
   (Use `It lip-syncs …` for a non-human singer such as a mask; `whispering one word in time: "<word>"` for a single
   whispered word.)
2. **Place, light and blocking at 0.0 s.** Who is where, wearing what, what is behind them. Carry the canon as short tags
   in parentheses: `(black bob, one orange streak, star clip, thin headset mic, white ruffled gown)`.
3. **The story beat in one sentence:** what this moment means and what each person wants.
   `Someone has just asked her whether they can trust her; this is her answer, sung softly a cappella straight into the
   lens, as if to one person.`
4. **Timestamped lines** on the real word, kick, downbeat and impact times, to **0.01 s**, each with **action and
   reaction**, and the sound named:
   `a.aa–b.bb s ("<words>"): <her action>; <his reaction>.` · `c.cc s (the drums hit): …` · `(kick)`, `(downbeat)`,
   `(on the beat)`, `(the bass drops back in)`.
5. **The environment answers the music:** waves detonate, spray bursts, oars bite, strobes fire, a bulb flickers — on
   the listed kick times.
6. **The camera is tied to the hits:** `a very slow push in until 2.16 s, a small jolt on the drop, then still` ·
   `Handheld camera riding the bench, moving with each stroke` · `Locked long lens` · `dollies backward at her walking
   pace`. One dominant move per clip.
7. **Mouth rules:** `Only she speaks; his mouth stays closed.` · `Nobody's lips form words.` · `She does not speak.` ·
   `Her mouth stays hidden against his ear.` (Use the last one on non-lip-sync clips so no mouth can look out of sync.)
8. **The closer and constraint lines:** `One continuous shot, no cuts. No text, letters or logos.` plus any locks the
   engine needs: `the framing held exactly as in the first frame` (first-frame clips), `the clock's digits stay steady and unchanged the
   whole time`, `the screen stays plain glowing white`, `a sign will be tracked onto it`, `The iris and pupil keep a
   crisp, perfect circle throughout.`, `No other hand or arm enters the frame.`, `The plug is always held, never
   floating.`, `behind her only open sea and spray, no ships or boats of any kind`.

**Rules inside the grammar:**

- **Characters always do something to each other.** SP's book rules (verbatim): "**Her, always:** doing something to
  him or reaching for him; warm, intimate, seductive, certain; never idle, never posing for a photo. **Him, always:** the
  body tells the story (the rope, the sweat, the breathing); he never speaks." Write your project's version of this
  paragraph in the book header.
- **Name end states** (`and she stops facing the camera, still`; `keeps walking until she is very small`) — models
  truncate or reverse actions that have no end.
- **Concrete physics** on hair, cloth, water, props (`her short black hair swings out, the orange strand whips across her
  face and the tag on her belt flies out`).
- **Every sung word has its time** in a timestamp line. Timestamps stay inside `[0, duration]`.
- **Describe light physically** (moonlight, a bare bulb, strobe under the door), not as a grade ("teal grade", "cinematic
  colour"). The plate carries the look.
- **Group shots: say the headcount** ("two rowers", "four oarsmen") — models change headcounts.
- **No readable text in the scene**; the engine draws all type.
- Fashion words on bodies ("sheer") and combinations of restraint + chest + touch trip filters: see the wording table in
  `62-moderation.md` §4 before writing scenes like that.

### 4.2 The prompt book

The lead writes the whole book as one markdown file the owner can read. `clips/book.md` is this doc's convention only:
**no `slop` command reads it.** The prompt that is sent lives in `clips/<clip>.json` → `body.prompt`, and you put it there
yourself, one clip at a time:

```
slop clip set W02 --prompt-file clips/prompts/W02.txt    # the prompt exactly as written in the book (back to draft)
slop clip lock W02                                       # checks it, then locks it
```

Keep the book and the clip files in step: after any change to a prompt, run `slop clip set` again, and show the owner the
book. `slop clip status W02` prints the prompt that will really be sent. The book opens with:

- **How to read a prompt** (verbatim from SP): "Times are seconds from the clip's first frame; the clip's audio
  (@Audio1) is the song from the clip's start, so the times are the real word, kick, snare and impact times …"
- **The story in one breath:** one paragraph, the whole video's story, so every prompt is written inside it.
- **The character rules** ("Her, always … Him, always …") and the canon tags.
- **The spend plan** (§8) and the provider order.

Then one entry per clip:

````markdown
### <clip> · <storyboard shots> · <song time m:ss.ss> · <clip length> [(x s used)]
- **inputs:** @Image1 `<plate>` (reference) [· @Image2 …] · @Audio1 <the mix | her vocal (her words only)> [| first frame `<plate>`, no @Audio1 (motion, --frame first)]
- **story:** <one or two sentences: the beat, why it matters, the owner's note if any>
```
<the prompt as sent, minus the pipeline prefix>
```
````

For a **sung window** the entry's `story:` line carries the drama (what the line means, what she wants, who she sings
to), and the prompt under it is the short form (§4.0): the owner reads the story there, the model gets only what helps it
copy. Motion clips carry the story in the screenplay itself.

### 4.3 The timing sheet (do this before writing each prompt)

For every clip, list the window's events in **clip time** (song time − `song_t0`), rounded to 0.01 s: every word with its
start and end, every kick, snare, downbeat and impact. Write timestamps only from this sheet.

`slop clip new` already stores most of it in the clip file, in clip time: `draft_notes.window_words` (`[start, end,
word]`), `draft_notes.kicks` and `draft_notes.downbeats`. Read them with `slop --json clip status W02`. **The words to
quote** are the clip's `words` field (the lyric sheet's spelling and punctuation; rule 3). The timing data is only for
the timestamps. For snares and impacts too, this prints the whole sheet from the analysis files:

```python
# timing_sheet.py <project_dir> <song_t0> <duration>
import json, sys
p, t0, dur = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
t1 = t0 + dur
WJ = json.load(open(f"{p}/analysis/words.json", encoding="utf-8"))
W = WJ["words"]
H = json.load(open(f"{p}/analysis/hits.json", encoding="utf-8"))
B = json.load(open(f"{p}/analysis/beats.json", encoding="utf-8"))
LINES = {ln["line"]: ln["text"] for ln in WJ.get("lines", []) if isinstance(ln, dict)}
rel = lambda t: f"{t - t0:.2f}"
inside = [w for w in W if t0 - 0.02 <= w["t0"] < t1 - 0.08]
print("LYRIC LINES (quote these words as written, but only the ones that start in the window):")
for n in sorted({w["line"] for w in inside}):
    print(f'  line {n}: "{LINES.get(n, "?")}"')
print("WORD TIMES (aligned tokens: lower case, no punctuation; timing only, do not quote from here):")
for w in inside:
    print(f'  {rel(w["t0"])}-{rel(w["t1"])} s  {w["w"]}')
for name in ("kick", "snare"):
    print(name.upper() + ":", ", ".join(rel(t) for t in H.get(name, []) if t0 <= t < t1))
print("DOWNBEATS:", ", ".join(rel(t) for t in B.get("downbeats", []) if t0 <= t < t1))
print("IMPACTS:", ", ".join(rel(h["t"]) for h in H.get("hits", []) if t0 <= h["t"] < t1))
```

---

## 5. Templates (verbatim)

**The sung head** (every sung window, first line):

```
@Image1 sings @Audio1. She lip-syncs to @Audio1 exactly, every word in time: "<exact words>".
```

**The short sung template** (**every sung window by default**, §4.0; `slop clip new SHOT --kind sung` drafts it with
`[[slots]]`; the bracketed beat lines are optional, at most two):

```
@Image1 sings @Audio1. She lip-syncs to @Audio1 exactly, every word in time: "<every word in the window>".
<Framing> of the woman from @Image1 (<canon tags>), <how she sings the words>. <Light>. <Camera>.
[<a.aa s (the sound)>: <one small action>.]
[<b.bb s (the sound)>: <one small action>.]
One continuous shot, no cuts, no head turns. Only she sings. No text, letters or logos.
```

**EV's sung template** (the earlier form the short template grew from; the head is fixed, the rest describes one framing,
one action, one camera):

```
@Image1 sings @Audio1. She lip-syncs to @Audio1 exactly, every word in time: "<exact aligned words in the window>". <Framing> of the woman from @Image1 <pose/action, singing/saying the words + how>. <Light>. <Camera>, no cuts[, no head turns].
```

**EV's motion template** (the tool prepends the head; plain physical language, no style words):

```
The scene from @Image1, moving in time with @Audio1. <Framing>. The woman from @Image1 <one clear action with an end state>. <Camera move>. No cuts. Her mouth stays closed, face expressionless.
```

**The screenplay template** (SP; **the default for motion clips**, §4.1; on a sung window only for an acting moment with
a cut-away ready, `--style screenplay`; for motion the EV template is the floor, not the target):

```
[@Image1 sings @Audio1. She lip-syncs to @Audio1 exactly, every word in time: "<exact words>".]
<Place and light>. <Framing> of the woman from @Image1 (<canon tags>)<, the other people and where they are>. <The story beat: what this moment means, what each of them wants>.
0.0–a.aa s: <action>; <reaction>.
a.aa–b.bb s ("<words>"): <her action while she sings them>; <the other person's reaction>.
c.cc s (<the sound: the beat drops / kick / downbeat / the drums hit>): <the environment answers>.
c.cc–<duration> s: <the end state>.
Camera: <one move, tied to the hits>. <Mouth rule>. One continuous shot, no cuts. No text, letters or logos.
```

**Pipeline prefixes** for motion clips (the toolkit adds them; don't write them twice):
`The scene from @Image1, moving in time with @Audio1.` (reference mode, **the default**) · `Moving in time with @Audio1.`
(first-frame clips, `--frame first` only; on OpenRouter no audio is sent with a first frame, §2.2, so write the beat
into the timestamps in words).

**Previz (Director tier):** `The camera follows the motion of @Video1 exactly. The look comes from the images: … (@Image1)
… (@Image2).` If the grey previz leaks into the take, say `take only the camera move from it, and film the scene itself in
rich cinematic detail`, or drop the video reference.

---

## 6. Providers

### 6.1 Seedance 2.5 on OpenRouter (`bytedance/seedance-2.5`)

- **Price:** video tokens = width × height × 24 × seconds / 1024, at **$0.0000107** per token →
  **$0.231/s at 720p** (1280×720; 4 s = $0.92, 5 s = $1.16, 8 s = $1.85) and **$0.103/s at 480p** (854×480; 4 s = $0.41).
  With a video reference the rate is $0.0000064 per token, and input-video seconds count too.
- `POST https://openrouter.ai/api/v1/videos` → `{id, polling_url}`; poll with backoff (5 s rising to 20 s) until
  `completed | failed | cancelled | expired`; download `GET /api/v1/videos/{id}/content?index=0` with the key. A response
  with no job id was **not submitted** — never count it, never assume it.
- Fields: `prompt`, `duration` (the API takes 4–30; use 4–8 for sung windows and 4–12 for motion), `resolution`
  (`480p`/`720p`), `aspect_ratio` `16:9`, `generate_audio`, `input_references` (images, `audio_url`, `video_url`),
  `frame_images` (first/last frame). **Sending `frame_images` makes OpenRouter ignore all `input_references`, the audio
  included** (§2.2): the toolkit never sends it on a sung clip.
- **Audio references must be HTTPS URLs** (§6.3). Inline image data URLs are fine up to ~3 MB.
- **Face filter:** photoreal face references are often declined at submit ("PrivacyInformation"): on SP, **18 of 27**
  photoreal face references were declined. **Illustrated or stylized faces pass** (paid probe, 2026-10-01: an
  anime/cel-style lead went through), but that is never a reason to restyle Claudia: she is photographic. A decline
  is free and final for that image on that service (`62-moderation.md`), but each one costs a bot turn and a round
  trip. Higgsfield took the same photoreal images. So route photoreal sung shots to Higgsfield first (§6.5).
- Seedance 2.5 sometimes fails a vocal-reference take with "output audio may contain sensitive information" (unbilled).
  Retry once with a re-cut window (`slop clip set <clip> --song-t0 <s> --recut`) or a reworded prompt, then try the other
  provider. The toolkit counts these refusals per clip and prints exactly one next step (`62-moderation.md` §5).
- The **API key has its own spend limit**, separate from the account balance (SP: every submit returned 403 at the key's
  $250 limit while the account had credit). `slop spend` reads both.

### 6.2 Seedance 2.5 on Higgsfield (`seedance_2_5`, via the bot's Higgsfield connector)

- **Price: 3 / 7 / 12 credits per second** at 480p draft / 720p / 1080p (4 s at 720p = 28 credits). At top-up prices
  (≈ 5.0–5.9 ¢ per credit) that is **≈ $0.35–0.41/s at 720p**, 1.5–1.8× OpenRouter. `generate_audio: false` does **not**
  lower the price on Higgsfield.
- **Preflight every new configuration** with `generate_video` and `get_cost: true` (free, submits nothing; not allowed
  inside a batch). Prices have changed before.
- Request: `model: "seedance_2_5"`, **`mode: "omni_reference"` always explicit** (the default is text-to-video),
  `resolution`, `aspect_ratio: "16:9"`, `duration`, `medias: [{role, value: media_id}]` in the order
  `start_image → image_references → video_references → audio_references`, `prompt`, `generate_audio` (omit = true for sung,
  `false` for motion). Never set `use_unlim: true` unless the owner asks.
- **Batches:** `generate_video_batch` takes ≤ 12 requests; poll with `jobs_wait` (≤ 12 jobs, ≤ 15 s per call; wait
  `poll_after_seconds` between calls). Renders took ~4–11 min (median ≈ 7). The toolkit writes the request file; the bot
  passes it **verbatim** and writes the job manifest **immediately** after each submit.
- **Per-item failures:** a "preset recommended instead" refusal → resubmit only that item with `declined_preset_id`;
  balance too low → stop and report; **never resubmit an item that got a job id**; a transport timeout means the outcome
  is unknown → check `transactions` before any retry.
- Blocked jobs are refunded (silent "failed" and "nsfw": `62-moderation.md`). Result URLs are public; download right
  away. Output: 1280×720, 24 fps, 97 frames for 4 s; with audio on, a 32 kHz stereo track; with audio off, **no audio
  stream** (nothing for a sync check).
- Higgsfield takes the photoreal faces OpenRouter declines. Its sung takes copied the audio in ≈ 21 % of cases on SP.
  EV's OpenRouter takes copied in 41 % of cases, but SP's own 8 OpenRouter sung takes copied in none. Projects, prompts
  and windows differed, so **a provider difference is not established**: see `61-lipsync.md` §7 and §9.
- The bot runs Higgsfield jobs through its connector: `slop clip submit W02 --provider higgsfield --yes` writes the
  request file (the bot uploads the media, submits, polls with `jobs_wait`), then
  `slop clip ingest W02 --url <result URL> --job-id <job id> --credits 28` adds the take (`--credits` = what
  `transactions` charged, not the file's estimate).
- **A request that never ran counts 0:** the connector refused it before a job id (balance, an ineligible draft), or the
  owner said no after `get_cost` → `slop clip ingest W02 --failed "rejected: <the reply, verbatim>"` (or `"rejected: not
  sent, <why>"`). A job that ran and failed → `--failed "<the reason, verbatim>"`. Either way the take's estimate comes
  off the project log (the Studio run's log said 114 credits for 66 real before this). A transport timeout is neither:
  check `transactions` first, it may have run and been charged.

### 6.3 Hosting the audio window for OpenRouter

OpenRouter needs an HTTPS URL for `@Audio1`. **Inline `data:` audio is rejected** (verified 2026-10-01: HTTP 400
"Only HTTPS URLs are allowed", free). `slop clip submit` stops with the two commands below when a sung clip has no URL yet.
Both of these are verified to work:

1. **A Cloudflare quick tunnel from the box** (verified for both audio and images). The tunnel serves the clip's window
   under a random token path. Keep it up until the job leaves `pending`:

   ```
   slop gen tunnel start            # once per session (bin/setup.sh installs cloudflared)
   slop gen host W02 --tunnel       # gives W02's window an https://….trycloudflare.com URL
   slop gen tunnel status           # is it still up?   ·   slop gen tunnel stop   when every job is done
   ```

   A restarted tunnel gets a new host name; `slop clip submit` re-hosts the window automatically while a tunnel is
   running (if none is, it tells you to run `slop gen tunnel start`).

2. **Upload once through the Higgsfield connector** (`media_upload` → PUT the bytes → `media_confirm` with
   `type: "audio"`; images need a separate confirm call), then read the file's public CloudFront URL with `show_medias`.
   The same upload gives a `media_id` for Higgsfield. Record both:

   ```
   slop gen host W02 --url https://<the CloudFront URL> --media-id <the media id>
   ```

   Caveat: anyone with the URL can fetch the vocal.

3. The owner's own bucket with a pre-signed URL (`slop gen host W02 --url <https URL>`).

### 6.4 Cheaper models for motion clips

Lip sync needs Seedance 2.5 (the audio-copy method, `61-lipsync.md`). **Motion clips** don't, so cheaper models are fine
when the budget is tight:

| Model | Where | $ per second | Shortest clip | Inputs | Notes |
|---|---|---|---|---|---|
| **Wan 3.0** | OpenRouter `alibaba/wan-3.0`; Higgsfield `wan3_0` | **$0.05** (480p) / $0.10 (720p) / $0.20 (1080p) | 4 s: $0.20 at 480p | OpenRouter: first frame only (no audio); Higgsfield: start/end + image/video/**audio** refs | Arena image-to-video #3; 2–30 s |
| **Grok Video 1.5** | OpenRouter `x-ai/grok-imagine-video-1.5`; Higgsfield `grok_video_v15` | $0.08 (480p) / $0.14 (720p) / $0.25 (1080p) + 1 ¢ per input image | 4 s: $0.33 at 480p | OpenRouter: first frame only (no audio); Higgsfield: start + image refs + **audio refs** | Arena #8; 1–15 s |
| **Kling 3 Turbo** | Higgsfield `kling3_0_turbo` | credits (preflight) | — | start frame only; 720/1080p; 3–15 s | budget speed tier; OpenRouter has `kwaivgi/kling-v3.0-std` at $0.084/s silent |
| **MiniMax H3** | OpenRouter `minimax/hailuo-3`; Higgsfield `minimax_h3` | $0.13 (2K) + $0.04 per reference image | 5 s: **$0.65** (+ $0.04 per reference image) | first + last frame + refs | Arena image-to-video **#1**; **5–15 s** on OpenRouter |
| Seedance 2.0 Mini | OpenRouter `bytedance/seedance-2.0-mini` | $0.034 (480p) / $0.076 (720p) | 4 s: $0.14 / $0.30 | first/last + image/video/audio refs | plumbing tests |

- Write the same screenplay prompt. If a model takes no references, drop the `@` tags and say "the first frame".
  Check each model's tag syntax (xAI's own API uses `<IMAGE_0>`, `<AUDIO_0>`).
- A model that gets no audio (a first frame only) cannot hear the beat. Write the kick and downbeat times into the
  timestamp lines (§4.3) so the motion still lands on the music.
- `slop gen models --kind video --res 480p --duration 5` lists the live prices, cheapest first (a free call).
- **Compare one or two clips against Seedance 2.5 before switching a project's motion clips**, and show the owner.
- Record the choice in `project.json` → `models.video_cheap`.

### 6.5 Which provider for which clip

| Clip | First choice | If declined / failed |
|---|---|---|
| Sung window, **photoreal** face in close-up or medium framing | **Higgsfield** Seedance 2.5 720p (`--provider higgsfield`; OpenRouter declined 18 of 27 photoreal faces on SP) | OpenRouter with the **same unaltered** image (a decline is free); then the shot's other coverage |
| Sung window, a wide framing where the face is small, or an **illustrated or stylized** character the owner asked for (her avatar tier in a game world, a new character) | OpenRouter Seedance 2.5 720p (these faces pass its filter) | Higgsfield with the same image |
| Motion clip, hero | Seedance 2.5 on OpenRouter in reference mode, `generate_audio: false` (photoreal faces in close-up: Higgsfield) | the other provider; or MiniMax H3 / Wan 3.0 |
| Motion clip, budget | Wan 3.0 480p/720p or Grok Video 1.5 480p (first frame only: no audio, §6.4) | Seedance 2.0 Mini |
| Sharper hero shot | Higgsfield 1080p (12 cr/s) | — (don't use learned upscalers: they measured worse) |

A decline is free in money but not in time: each one costs a bot turn, a resubmit and a wait. When most of a project's
sung shots are photoreal close-ups, plan them on Higgsfield from the start. When a project must run on OpenRouter only
(Quick tier without Higgsfield), plan her sung close-ups as wider framings or cutaways at the board; never restyle
Claudia as illustrated to pass the filter (`51-plates-api.md` §3.1).

**A sung window whose takes do not copy the vocal** (no in-sync spans, `61-lipsync.md` §3):

1. **The prompt first.** Was it the short form (§4.0)? If not, rewrite it short and retake on the **same** provider: the
   prompt, not the provider, was the measured cause (`c01`: 0 % → 78 % on OpenRouter after a Higgsfield draft of the long
   prompt had failed too).
2. **Then the routing rule:** after **2 OpenRouter non-copies** of the short form, a Higgsfield 480p draft (finalize it
   if kept, §7); never a third OpenRouter try.
3. **Then cut away** (`61-lipsync.md` §8): the shot's motion clip, inserts, a wider or profile framing.

---

## 7. Draft → finalize loops

Test cheap, then pay for the keeper.

- **Higgsfield's built-in loop:** submit with `draft: true` at 480p (3 cr/s) → check the take (sync for sung windows,
  frames for motion) → finalize only the passing drafts at 1080p with `draft_job_id` (within 7 days). The finalize price
  is unknown: preflight it with `get_cost`. Whether finalize keeps the sync is untested: **run the sync check again on the
  finalized take**. A finalize the connector refuses or that fails is recorded with `slop clip ingest CLIP --failed
  "rejected: …"`: it counts 0, the clip goes back to delivered on its draft, and a retry (`--finalize-from TAKE` again)
  waits for the owner's yes, never a re-lock and a new paid draft.
- **OpenRouter:** there is no finalize. A 480p take ($0.103/s) is a separate generation: use it to test a recipe, a
  blocking or a model; then generate the keeper at 720p and check it again (the motion will differ).
- **Show the owner a cheap proof before committing to a method** (anabology: "Wait show me the short clip w audio
  before wasting time on the latent sync"). Low-res previews with the real music and the neighbouring shots; labelled
  variants (A/B/C) for the owner to pick from.

---

## 8. Cost planning and spend rules

**Benchmarks:** EV made 47 clips + 28 covers (plus 2 LatentSync patches and 7 tests) in 91 submissions, 421 s at
720p, ≈ $93 billed (local ledger said $97.28).
SP made 189 takes: OpenRouter 108 takes / 461 s / ≈ $107; Higgsfield 81 takes / 348 s / 2,436 credits, **plus ≈ 830
credits burned** on the rejected first round.

**Estimate before spending.** For each clip: seconds × rate; add **≈ 60 % of the sung seconds** for covers (EV's cover
allowance); add a retake reserve. Example: 12 sung windows × 5 s + 20 motion clips × 4 s at 720p on OpenRouter =
140 s × $0.231 = $32.34, + covers 0.6 × 60 s × $0.231 = $8.32 → **≈ $41**, before retakes.

The commands give you the numbers: `slop clip list` shows every clip with its expected spend, and
`slop gen estimate --model bytedance/seedance-2.5 --duration 5 --res 720p` prices one call. Put the total in the G5
message (`00-overview.md` §4).

**Spend rules (non-negotiable):**

1. A clip spends only when `status: "locked"` **and** the command has `--yes` (or `gates.prompts_approved` is true).
   Pass `--yes` only after the owner's explicit yes for that spend.
2. Any single call over `budget.confirm_over_usd` is confirmed by the owner first.
3. Budget caps live in `project.json` → `budget` (`openrouter_usd`, `higgsfield_credits`); `slop clip submit` checks
   the ledger estimate against them before anything is sent and stops at the cap. Raise a cap only when the owner says so.
4. **Real spend comes from the provider** (OpenRouter credits/key endpoints, Higgsfield `transactions`), not the ledger.
   Declines and refunds are not spend (`status: "declined"` rows don't count).
5. On an owner quality flag: **stop every spending path**, then talk.
6. Never resubmit a request that got a job id. An unknown outcome is reconciled first.
7. Plan the order by face (§6.5): photoreal sung close-ups on Higgsfield first (in story order, one take each);
   wide framings, motion clips and stylized characters the owner asked for on OpenRouter first (a decline there is free, but it
   costs a turn). Whatever one provider declines goes to the other with the same unaltered image. Keep ~10 % of credits
   for retakes (SP's plan).

---

## 9. The order of work

Every command below is idempotent (re-running it does not duplicate work) and prints what to do next. For the
machine-readable result put `--json` before the command (`slop --json clip list`). `W02` and `s005` stand for your clip and shot ids.

1. **From the storyboard, draft every clip.** `slop board audit` must pass first (it checks durations, word gaps, the
   clip budget and distinct start frames). One command per shot that needs a clip:
   `slop clip new s005 --kind sung` · `slop clip new s014 --kind motion`. Each one picks the window (§3), cuts the
   audio, quotes the exact words, picks a start plate no other clip uses, and writes a prompt scaffold with `[[slots]]`:
   the short sung form for sung clips (§4.0), the screenplay for motion clips (§4.1).
   Add `--provider higgsfield` for photoreal sung close-ups (§6.5).
2. **Host the windows for OpenRouter** (§6.3): `slop gen tunnel start`, then `slop gen host W02 --tunnel` per clip (or
   `slop gen host W02 --url <CloudFront URL> --media-id <id>` after a Higgsfield upload).
3. **Load everything into one context:** the storyboard, a contact sheet of every start plate (`slop board sheet`), the
   timing data of every window (`slop --json clip status W02` → `draft_notes`, or the script in §4.3).
4. **Write the whole prompt book** (§4.2) — one sitting, the lead only: sung windows in the short form (the story in
   each entry's `story:` line), motion clips as screenplays. Then put each prompt in its clip:
   `slop clip set W02 --prompt-file clips/prompts/W02.txt`.
5. **Lint and lock:** `slop clip lock W02` refuses a clip whose start image or window is missing, whose prompt still has
   `[[slots]]`, or whose quoted words differ from the window's words. The words a prompt quotes are the source of
   truth: to quote only her words, `slop clip set W02 --words "Sit up, darling"` (or `clip new … --words`) re-cuts the
   clean window to hold exactly them; `slop clip set W02 --requote` quotes **every** word of the window. It also
   refuses a first frame on a sung clip, and a sung clip on a model that takes no audio reference. It **warns** (and
   still locks) when a sung prompt runs past ~90 words besides the quoted lyric or more than 2 timed beats (§4.0).
   Check the rest by reading: every timestamp inside `[0, duration]`; in a screenplay every sung word has a timestamp
   line; the head, the mouth rule and the closer are present; canon tags present; no banned words; nothing from the
   moderation table unless reworded (`62-moderation.md` §4).
6. **Estimate the cost** (`slop clip list`, §8) and **send the book to the owner** (gate G5). Wait for an explicit "go":
   never take silence as approval for spend. Record it:
   `slop gate prompts --approve --note "<the owner's words>"`.
7. **Submit:** first `slop clip submit W02 --dry-run`: it runs the real submit's checks (lock problems, a sung clip
   without `@Audio1`, a resolution the model does not offer, a clip already in flight, the budget) and prints the exact
   request, its estimate and the `--yes` command only when nothing blocks. Then `slop clip submit W02 --yes`.
   OpenRouter jobs go out at once. For Higgsfield the command writes a request
   file that the bot runs with its connector (§6.2). Never resubmit a clip that has a job id. After a 5xx or a dropped
   connection the take is recorded as an **unknown outcome** (estimate ledgered, plain `submit` refused): find the job on
   openrouter.ai/activity and attach it with `slop clip poll W02 --job-id <id>`, or, if it is not there,
   `slop clip submit W02 --yes --resubmit-unknown` (refunds the estimate in the ledger and submits again).
8. **Poll and download** every take to `clips/<clip>/take-N.mp4`: `slop clip poll --wait 300` (OpenRouter, every clip in
   flight); `slop clip ingest W02 --url <result URL> --job-id <job id> --credits 28` (Higgsfield). Record declines as
   they happen: `slop clip ingest W02 --declined "<the error>"`; a Higgsfield output-audio refusal ("sensitive
   information", "copyright") with `slop clip ingest W02 --failed "<the reason, verbatim>"`, which prints the one next
   step (retry once, then the other provider).
9. **Sung windows: sync check** with `slop clip sync W02`, then `slop clip coverage`. Then cover with
   `slop clip cover W02 --make` (a cover sings, so it stays in the short form), or cut away (`61-lipsync.md`). A window
   whose takes did not copy at all: short form first, then the routing rule (§6.5). `slop clip frame W02` extracts the
   last in-sync frame of a take (or `--at SONG_T`) to start the next clip from.
10. **QA every take** (§10) and run the safety & canon scan before release (`62-moderation.md` §8).
11. **Rebuild the edit** (`slop edit edl`) so the film renders end to end with what exists.
12. **Reconcile spend** (`slop spend`; Higgsfield: the bot reads `transactions`).

---

## 10. QA of every take

Extract 5 frames across the take plus one face crop; look at them next to the start image. Check:

- on-model (the canon list: hair, the one mark, the props, age read, wardrobe);
- no warped, melting, doubled or painterly faces; no extra limbs or fingers; no text or watermarks;
- **the story**: does the take do what the storyboard shot needs, with action **and** reaction? (Not just "did it follow
  the prompt".)
- the right performance: only the singer voices; nobody else's mouth moves;
- sung windows: the sync figure and span (`61-lipsync.md`);
- motion clips: smooth, composition kept, the move lands where the shot needs it.

Verdict per take: `keep | retake | reject`, one line per take appended to `clips/QA.md` (format in `80-review-qa.md`
§4) and the verdict stored on the take in the clip file. At most one retake per clip unless it
is a key lyric moment. **If many takes fail the same way, the prompts are the fault: stop, rewrite, re-make.**

---

## 11. Exemplars (verbatim from the reference videos)

**Sung, EV (`SD08`, short form: the form every sung window now uses, §4.0; today's template moves the closer to its own
line and adds `Only she sings.` and `No text, letters or logos.`):**

```
@Image1 sings @Audio1. She lip-syncs to @Audio1 exactly, every word in time: "Lock in, baby, foot down on the gas. Feel the A G I, feel it". Close-up of the woman from @Image1 with her black bob, clay-orange streak and headset microphone, facing the camera, singing with her eyes closed, her head tilting back slightly on the long notes. Warm light from the side. Locked camera, very slight push in, no cuts, no head turns.
```

**Sung, SP screenplay (`W02`, 4 s, @Image1 the singer close-up, @Audio1 her vocal only).** This is the exemplar for the
story and the prompt grammar, not proof of sync. On Higgsfield this long timestamped form held only **28 %** of the line
(take 2, NCC 0.05). An earlier, short 86-word prompt for the same window held **100 %** (take 1, NCC 0.22; it is the
take in `61-lipsync.md` §4). That prompt had the same head, then one framing, one performance, light and camera, with no
timestamps. The Studio run then measured the same split on three more windows (§4.0, `61-lipsync.md` §1.1), so sung
windows now take the short form; keep this screenplay as the model for a motion clip's story and blocking, or for a sung
acting moment with a cut-away ready.

```
@Image1 sings @Audio1. She lip-syncs to @Audio1 exactly, every word in time: "Why would I deceive you?".
Night on her black sea rock, moonlight, faint spray. Close-up of the woman from @Image1 (black bob, one orange streak, star clip, thin headset mic, white ruffled gown). Someone has just asked her whether they can trust her; this is her answer, sung softly a cappella straight into the lens, as if to one person.
0.0–0.3 s: she draws a slow breath, lips parting, eyes on the lens, head tilted a little.
0.3–0.74 s ("Why would I"): she sings softly, her eyebrows lifting a fraction, as if the question has hurt her feelings a little.
0.88–1.34 s ("deceive"): she leans closer to the lens; her voice warms and her eyes soften.
1.44–1.56 s ("you?"): the word ends on a small, disarming smile; her eyes stay on ours.
1.6–2.16 s: silence; she holds the gaze, lips parted, completely sure of herself.
2.16 s (the beat drops): a wave bursts behind her and the wind whips her wet bob across her cheek; she does not flinch, and her smile deepens.
2.16–4.0 s: she keeps looking into the lens, lips closed, as the spray falls.
Camera: a very slow push in until 2.16 s, a small jolt on the drop, then still. One continuous shot, no cuts. No text, letters or logos.
```

**Sung, SP (`W05b`, held 99 % of its sung seconds on Higgsfield, with this long timestamped prompt and a copy NCC of
only 0.16; long prompts can hold, they just hold far less often than short ones, §4.0):**

```
@Image1 sings @Audio1. She lip-syncs to @Audio1 exactly, every word in time: "Then the timeline sings it, word for word.".
Night on her rock. Close-up of the woman from @Image1 (black bob, orange streak, star clip, headset mic, white ruffled gown) filming herself like a video post, looking straight into the lens. This is the clip that is on everyone's feed, and she knows it.
0.0–0.3 s: she lifts her chin and smiles at the lens.
0.3–1.54 s ("Then the timeline"): she sings playfully, her head bobbing on the beat (0.3, 0.77, 1.24 s), eyes bright.
1.68–2.48 s ("sings it, word"): she leans toward the lens.
2.16–3.32 s ("word for word"): she points at the lens with one finger, one small jab for each word ("word", "for", "word"), keeping her hand below her chin.
3.32–4.0 s: she holds the look, amused, one eyebrow raised.
Camera: locked, with the slight float of a hand-held phone. One continuous shot, no cuts. No text, letters or logos.
```

**Sung with a second character and an entrance (SP `W07`, 5 s; on Higgsfield: `start_image` = the mast shot, which is
`@Image1` there, and the floating pose plate as the character reference in `image_references`, which is `@Image2`.
The book shows the prompt as written; the request sent to Higgsfield named `@Image2` in the head, §2.3.)** On
OpenRouter, send the same two images as reference images and no first frame (§2.2).

```
@Image1 sings @Audio1. She lip-syncs to @Audio1 exactly, every word in time: "You don't have to die.".
Dusk on the black galley, the first frame of this shot: a medium wide shot of the broad bearded man in a black t-shirt at the mast, a thick hemp rope around him and the mast, the sea and the Sirens' rocks behind him, rowers with orange earplugs pulling their oars below. The Sirens' song is pouring over the ship and it is pulling at him: he wants to go to them.
0.0–1.9 s: he strains toward the rocks with all his strength, pulling forward and twisting from side to side against the rope, the mast creaking, his jaw set and his eyes fixed on the rocks. The rowers keep rowing, eyes down, deaf to it.
1.2–1.9 s: from the left of the frame the woman from @Image1 glides in, floating level in the air like a diver, see-through like glass and seawater, her gown and black bob drifting as if underwater, the orange streak glowing faintly.
1.9–3.42 s ("You don't have to die."): she rests one hand on his shoulder, leans in close and whispers the words into his ear with a small, certain smile. He stops pulling mid-movement; his eyes widen and soften; he turns his head toward her voice as if he wants to believe her.
3.42–5.0 s: she stays close beside him, her cheek near his; he leans back against the mast and breathes out slowly, calmer now, still looking at the rocks.
Only she speaks, in a whisper; his mouth stays closed. Locked camera, drifting slowly toward them from 3.0 s. One continuous shot, no cuts. No text, letters or logos.
```

(Its audio window kept the vocal only at clip 1.70–3.50 s and silence elsewhere "so she flies in first and whispers once
she is at his ear". An earlier take of this window, with a shorter prose prompt and the vocal placed the same way, held
**90 %** of the line in sync (take 2, NCC 0.49). This long take did not copy the audio, and it shipped as performance
in song time with her mouth in profile. Whispers at the ear with a second person have both held and failed on
Higgsfield (`61-lipsync.md` §9): measure every take, and plan a cut-away for the span in case it does not hold.)

**Motion, EV (`SD10`):**

```
The scene from @Image1, moving in time with @Audio1. Full-length shot. The woman from @Image1 stands completely still at the end of the walkway with her weight on one hip for two seconds, then turns sharply around on one heel so her short black hair swings out, the orange strand whips across her face and the tag on her belt flies out, and she stops facing the camera, still. Static camera. No cuts. Her mouth stays closed, face expressionless.
```

**Motion, SP (`M-s001`, 4 s, the start plate an extreme close-up of her eye, @Audio1 the mix).** SP sent its motion
plates as start frames: on OpenRouter that means the mix window was ignored (§2.2); on Higgsfield a start image keeps
it. In this toolkit the same prompt goes in reference mode, with the pipeline prefix
`The scene from @Image1, moving in time with @Audio1.` added in front (§5).

```
Extreme macro close-up of the Siren's eye at night, filling the frame: pale freckled skin, lashes beaded with sea spray, the clay-orange streak of her bangs across the top of the frame. Reflected in the wet iris: a moonlit black sea, a ring of jagged sea rocks and, far off, the single white light of a ship. She is the Siren, watching a ship come toward her island.
0.0–0.4 s: the eye is still, looking just past the lens; the sea wind lifts a few strands of the orange streak.
0.4–1.0 s: a drop of spray lands on her lower lashes; she does not blink; the pupil slowly widens, as if she has spotted the ship.
1.0–2.1 s: the tiny ship light drifts across the reflection in her iris; her lower lid tightens very slightly with interest.
2.1–3.1 s: her gaze moves from past the lens straight into the lens and meets ours, calm and knowing.
2.3–4.0 s: the camera pushes in steadily, then faster as the synth swell rises, straight into the black pupil, until the pupil fills the whole frame with black.
The iris and pupil keep a crisp, perfect circle throughout. She never blinks. No cuts. No text, letters or logos.
```

**Motion, the environment answering every kick (SP `M-s009`):**

```
Night, a moonlit black sea. The camera skims fast and low, a metre above the water, toward a single black galley with a white masthead light on the horizon: the Sirens' song is travelling across the sea to the ship.
0.0–4.0 s: one continuous forward skim, gently accelerating.
On every kick (0.45, 0.91, 1.37, 1.86, 2.35, 2.80, 3.24, 3.72 s): a fresh ring of ripples pulses outward across the surface from under the camera, as if the sea were a speaker cone, moonlight flashing along each ring.
1.86 s: the camera dips lower and spray flicks past the lens.
3.24–4.0 s: the galley grows larger; its oars rise and fall in rhythm.
No cuts. No text, letters or logos.
```

**Motion, action and reaction (SP `M-s025`):**

```
Dusk on the deck of the black galley, the Sirens' song rolling across the water from the rocks. The broad bearded man with a shaved head in a black t-shirt stands with his back against the mast while two rowers in plain undyed linen tunics (one grey-haired, one young with long hair tied back), both with small orange foam earplugs, lash him to it with thick hemp rope. He asked for this: he wants to hear the song and be unable to act on it.
0.0–1.0 s: he presses his shoulders back against the mast and nods at them hard: tighter. They pass the rope around him fast, hand over hand.
1.0 s (the drums hit): they haul the rope tight across his chest in one hard jerk; the breath is knocked out of him and his head knocks back against the mast.
1.0–1.9 s: another loop whips around his chest and arms; the rope creaks; his fists clench at his sides.
1.9–2.84 s: his eyes go past the rowers to the singing rocks behind the camera, wide and hungry, his jaw set; the song is already reaching him.
2.84 s: the grey-haired rower yanks the knot tight with both hands, one foot braced against the mast.
2.9–4.0 s: the rowers go back to their oars without looking at him; he tests the rope, straining forward an inch; it holds.
Handheld camera, close, moving with the pulls. Nobody speaks. No cuts. No text, letters or logos.
```

**Motion, a domino on the beat (SP `M-s037`, passed only after rewording — see `62-moderation.md`):**

```
Twilight on the black galley. The woman (black bob, orange streak, star clip, headset mic, white high-necked ruffled gown) stands in the central aisle between the rowers' benches, facing the lens, the mast and sail behind her. She has walked onto their ship, and one by one the rowers stop blocking out her song.
0.0–3.0 s: she walks slowly toward the camera down the aisle, calm and confident, eyes on the lens, a small knowing smile, lips closed. As she passes each bench, the rowers on both sides pull the orange foam out of their ears, one bench on each beat (0.48, 0.94, 1.39, 1.86, 2.32, 2.77 s), a domino run following her down the ship; each rower's head turns to watch her go by, his oar trailing in the water.
1.42–1.72 s: she brushes one rower's shoulder with her fingertips as she passes; he looks up at her, entranced.
2.94–3.54 s: she stops and lifts both arms slowly from her sides, palms up, like a singer taking the applause; behind her, every rower is watching her.
3.54–5.0 s: she lowers her arms and tilts her head at the lens.
Camera: dollies backward at her walking pace, at eye level. She does not speak. One continuous shot, no cuts. No text, letters or logos.
```

**3D camera move (SP `V-s002`, previz as `@Video1`):**

```
The camera follows the motion of @Video1 exactly. The look comes from the images: the moonlit white cloud deck seen from twelve kilometres up with one dark round gap in it (@Image1), and a ring of jagged black sea stacks in a black-teal night sea with white surf glowing around them (@Image2). We are falling toward the Sirens' island.
0.0–2.11 s: the camera dives toward the dark round gap in the clouds, accelerating with the rising synth swell, the cloud tops streaming past below.
2.11 s (the bar line): we drop through the gap; walls of cloud rush past on every side.
2.4–3.4 s: out through the cloud base: far below, the black sea and the ring of sea stacks, silver moonlight on the water; the camera corkscrews one full turn as it descends.
3.0–3.25 s: for a quarter of a second the moonlight catches something pale and enormous under the water beside the rocks: a calm woman's face with closed eyes (@Image3); then it is gone.
3.4–5.0 s: the rocks rush up and the camera settles low over them, on the same framing as the end of @Video1.
One continuous shot, no cuts. No text, letters or logos.
```

**Anti-examples (the first round, rejected):**

```
Moving in time with @Audio1. Extreme close-up of her eye: it stays open, wet and still, the moonlit sea and the ring of rocks reflected in it shimmering; the clay-orange streak stirs in the wind. The camera pushes slowly and steadily into the black pupil until the pupil fills the frame. No cuts. No text, letters or logos.
```

Nothing happens in the eye: no ship in the reflection, no look into the lens, no reason to fall in.

```
@Image1 sings @Audio1. She lip-syncs to @Audio1 exactly, every word in time: "I said you don't have to die. The doctor said you could. Your P". Extreme close-up in the dark: the woman with the black bob and one orange streak from @Image1 rests her chrome-gloved hand on the man's cheek and whispers the words at his ear. His eyes stay mirror-chrome silver and unblinking, and his mouth stays closed. Strobe light glints on the chrome; faint fog. Locked camera. No cuts. No text, letters or logos.
```

A pose, no story, no action or reaction, no timestamps, and a window that cut a word ("Your P"). anabology called it
"awful". (Its chrome eyes had also been painted onto the plate by hand; the fix was an image edit, `51-plates-api.md`.)
Note that a take of this window from that round held 99 % of its sung seconds in sync (`W15`, `61-lipsync.md` §9).
**Sync is not story:** a take can be perfectly in sync and still be rejected.

---

## 12. Failure catalogue (clips)

| Symptom | Cause | Fix |
|---|---|---|
| Takes look like people posing | caption-style prompts | the screenplay grammar (§4.1) for motion clips, written by the lead in one context; sung windows stay short (§4.0) with the story in the book |
| Sung takes re-sing the line in their own timing; almost no sung seconds in sync (Studio run `c01`: 0 %) | a long timestamped screenplay on a sung window: the model performs the text instead of copying `@Audio1` | the short sung form (§4.0), retaken on the same provider before any re-routing (`c01`: 78 %); `slop clip lock` warns on long sung prompts |
| A sung clip barely syncs with any prompt (Studio run `c06`: 26 %) | a microphone or hand at her mouth on the plate | re-make the plate with her mouth fully visible (§4.0 rule 6) |
| QA passed takes the owner hates | QA checked prompt compliance | QA checks the story (§10); rewrite prompts, re-make |
| Spend continued after the owner flagged quality | another path still held budget | stop every spending path first |
| Clips came back grey | pre-graded mono references | send ungraded colour plates; grade in post |
| Two clips open on the same frame | same plate candidate | k-th clip uses the k-th other candidate |
| Lips drift inside a word near the window end | quoted words ≠ window words | quote every word that starts in the window |
| Last words missing from a Higgsfield take | lag + 4.04 s output | last word ≥ 0.8 s before the end, or +1 s |
| Singing while she is still flying in | words placed before the blocking allows | move the vocal later in the window |
| "output audio may be related to copyright restrictions" | the model's soundtrack copies the song | motion clips: `generate_audio: false`; sung: `62-moderation.md` §5 |
| "output audio may contain sensitive information" (Seedance 2.5, vocal reference; unbilled) | the provider's audio check | retry once with a re-cut window or reworded prompt; then the other provider |
| A take ignores the music and makes its own soundtrack (NCC ≈ 0.015) | first-frame mode on OpenRouter: `frame_images` drops `@Audio1` | reference mode (`slop clip set <clip> --frame ref`); sung clips are never first-frame |
| HTTP 400 "Only HTTPS URLs are allowed" | the window was sent as a `data:` URI | host it: `slop gen host <clip> --tunnel` or `--url` (§6.3) |
| Most photoreal sung close-ups declined ("PrivacyInformation") | OpenRouter's face filter (18 of 27 on SP) | route photoreal sung shots to Higgsfield first; on OpenRouter-only projects, wider framings or cutaways, never a restyled lead (§6.5) |
| 403 on every submit while the account has credit | the API key's own limit | the owner raises the key limit |
| Response without a job id | not submitted | do not count; resubmit once the cause is known |
| Higgsfield returns `unlim_choice` | `use_unlim` omitted on an unlimited-capable model | resend with `use_unlim: false` unless the owner opts in |
| Grey proxy shapes in a 3D move | previz leaked | "take only the camera move from it…", or drop `@Video1` |
| Action reversed or cut short | no end state | name the end state |
| Headcount changes | unstated | state the exact number |
| Ledger total ≠ bill | estimates, declines, refunds | real spend from the provider only |

### Intentional start-image reuse

Use `clip new ... --reuse-start` with a new clip id to intentionally reuse a plate for another clip or a
smoke-test repeat. `clip set CLIP --start IMAGE --reuse-start` permits the same explicit override.
Without it, the unused-start selection rule still applies. External start images are copied unchanged
into the clip folder and saved with project-relative paths.

### Lead wording and optional turns

The she/her examples above use Claudia as the lead. Actual prompts must use the configured lead's
pronoun, noun and possessive from `slop lead` (he/his, she/her, they/their, or custom wording); use
"Only he sings" or "Only they sing" as appropriate. `clip new/set --allow-turn` replaces the default
no-head-turns closer with "One continuous shot, no cuts.". The writer still supplies the action and
timing. Lock warns on conflicting turn instructions. A moving or occluded mouth may reduce lip-sync
accuracy; measure the take. No automatic turn detection or guaranteed accuracy penalty is assumed.

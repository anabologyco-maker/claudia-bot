# 10 · The song: concept, lyrics for Suno, the Suno pack, auditions, export, Lyria

Read this before you pitch a concept, before you write or edit a single lyric line, before you write the Suno fields,
and again before the owner downloads the take.

**Inputs:** the owner's brief (verbatim), `taste/taste-tokens.json` if it exists, the owner's Suno plan.
**Outputs:** `DECISIONS.md` (concept, song decisions), `lyrics/lyrics.txt` (as sung), a first `lyrics/display.txt` (as
read), the Suno pack in `suno/`, `suno/takes.md`, and finally `audio/song.wav` via `slop song ingest`.

---

## 0. The stage at a glance

1. Ask the song questions (§1) in one message.
2. Research the material and build a fact bank (§2.1).
3. Pitch three concepts (§2.3). **Gate G1**: the owner picks one.
4. Draft the lyric on a structure template (§3.2), written for how Suno delivers (§3.1).
5. Lint it (`slop lyrics lint`), fix the flagged lines (§3.7).
6. Write the Suno pack (§4) and send it as one message.
7. The owner generates a round of 2–4 takes and gives a verdict per take. Change one thing; next round (§5).
8. **Gate G2**: the owner picks a take by ear and downloads the WAV on a paid plan (§6).
9. `slop song ingest`, then the checks in §6.3.
10. If a word must be fixed after the video is cut: Suno editor with **BPM lock off**, then a time map (§7).

No Suno plan, or the owner wants it unattended and the song is short: the Lyria path (§9).

---

## 1. The song questions (ask them in one message, with defaults)

| # | Question | Default if the owner doesn't say | Why it matters |
|---|---|---|---|
| 1 | What is it about? Which motifs must appear? | — (must answer) | the concept and the fact bank |
| 2 | How current? (memes of the last 8 weeks / this year / timeless) | last 8 weeks | freshness ranks the research |
| 3 | Genre lane and reference songs? | deadpan spoken verses + euphoric sung chorus, electroclash/techno ≈ 128 BPM | spoken verses carry the most references per second |
| 4 | Singer: gender, spoken or sung, one voice or a crowd answering? | one female lead, spoken verses, sung chorus, crowd call-and-response | Suno picks gender at random unless told |
| 5 | Target length? Hard or soft? | soft; the video runs the full take | Suno often stretches a dense spoken lyric (§3.3) |
| 6 | Suno plan? (Free / Pro / Premier) Any Voice? | ask; Free → Lyria or upgrade | commercial rights need a paid-plan download (§8) |
| 7 | Real people allowed in the lyric? | yes, but only their own public words, never a likeness in an invented scene | legal and taste risk |
| 8 | Words you never want used? | none (record whatever they say) | taboo words go in `DECISIONS.md` and in every lint |
| 9 | Is this a sequel? What device did the last one use? | no | a sequel never reuses the last song's device |

Record the answers verbatim in `DECISIONS.md`.

---

## 2. Concept generation

### 2.1 Research (the fact bank)

The jokes carry the video, and a joke built on a wrong fact is worse than no joke. Every reference that goes into the
lyric needs a source and a status.

**Procedure**

1. Split the brief into 3–9 topics (SP used nine: slop, the AI-song wave, peptides, AI psychosis, cyberpunk,
   superpersuasion, the singer's persona, the current mood online, lyric craft).
2. For each topic, collect a bank (web search; read primary sources). Each item:
   `what · date (event date) · exact quote + speaker (primary source only) · link · confidence tag · freshness bucket · one lyric lever (≤ 12 words)`.
3. Tag confidence:
   - `[V]` two or more independent sources;
   - `[V1]` one strong or primary source;
   - `[U]` unverified or conflicting;
   - `[K]` background knowledge, no fresh source.
4. Freshness buckets: last 8 weeks · this year · older. Rank items by **resonance × freshness × fit**.
5. Keep a **"stale or overused"** list and a **"handle with care"** list (real deaths, violence, minors, private
   people, anything legally risky).
6. For an EV-class project, run an adversarial check on every item you might use: a separate pass that tries to
   **refute** it and defaults to "unverifiable". Statuses: `confirmed | wording-fix | refuted | unverifiable`. Only
   items a general viewer would recognise (recognisability ≥ 3 of 5) are worth checking; the rest never enter the lyric.
7. Write a one-page **shortlist**: the 10–15 best items and the conclusions they force (below).

**Rules**

- Only `[V]`, `[V1]`, `confirmed` and `wording-fix` items enter the sung lyric. `[U]` never does.
- Quote exact wording only from a primary source, with speaker and date. Never "tidy" a quote.
- Risky facts go into the **picture**, not the lyric (EV showed a resignation as a staff badge on an empty seat,
  "no name, no likeness"; a statistic appeared only on the board).
- Real people: only their own dated public words; never a likeness placed in an invented scene; never degrading or
  sexual; in the video, only inside a frame labelled AI IMAGE.

**What SP's shortlist concluded (a model for the shape of the conclusions)**

1. The paradox is already being said, so the song has to *do* it rather than say it.
2. Hooks travel; verse jokes don't. In the replies to EV its hooks were quoted 11 to 26 times each and each verse joke
   about once. So: **one singable hook with a call and response, one arguable claim, one quotable line.**
3. The genre is crowded and tired of itself (8+ covers of the reference song in 20 days): no anime idol, no waiting-room
   story, no news crawl.
4. Craft rules measured on EV's take: Suno spoke verses at about 3.3 syllables a second and sang at about 2.9. Spoken
   verses carry periods and light rhyme. The sung hook is 4 to 8 syllables of common words with open vowels.
5. "Confess the decoy": name one trick aloud and let the rest work unannounced.
6. A leave-out list: real harm and private people; likenesses; words that misread; other creators' lines; anything the
   last song used; stale jokes.

### 2.2 Concept rules

1. **Copy the method, not the look.** EV took from its reference video: a style held by a few parameters, a
   through-line carried by UI chrome, three type modes rotated on purpose, one-glance references as set dressing,
   cheap motion where it can be cheap. It explicitly did *not* copy the reference's anime idol, palette or meme set.
2. **Give it a through-line device** the on-screen chrome can carry and that changes with the story: EV's split-flap
   board "18 MONTHS TO ESCAPE THE PERMANENT UNDERCLASS" counting down to zero and flipping to THERE IS NO UNDERCLASS;
   SP's safety card, rope load readout and instance counter.
3. **A sequel never reuses the last song's device.** SP's first draft was rejected: "i kinda want a new song not teh
   exact same strucvture as before … rehashing counting is probably not good for a song 2 since thatd be close to a
   copy."
4. **Pick a world video models are good at.** EV chose a fashion show because "walks, stares and fabric are what
   video models do best".
5. **The lead is the singer and on screen most of the time** ("ideally the female lead … is the singer and main
   character in most the vid").
6. **Every reference must land instantly.** SP draft 1: "we're a little too abstract - i dont get from verse 1 what
   the topic is really".
7. **Subtract.** "subtracting is better than adding, we should leave things out rather than force them in, but if we
   can tie things in really elegantly then we should do so."
8. **Stage, don't explain.** The best concepts make the joke a place or an object (EV: an AI *model* walking as a
   fashion *model*, look cards set as *model cards* on garment tags).

### 2.3 The pitch (gate G1)

Pitch **three** concepts, deliberately different. Each ≤ 120 words, in this order:

```
<LETTER> · <TITLE>
Premise: one sentence.
Through-line device: what the chrome counts/shows and how it changes.
Lead: who sings, what they look like in one line, where they are.
Arc: start → turn → end, one line.
Why it works on video: what the video models will be asked to do.
Risk: the one thing that could go wrong.
```

**EV's three pitches (condensed)**

- **A · ESCAPE VELOCITY (picked).** A techwear fashion show where each look is a model release, an era or a meme; the
  protagonist is an AI model walking as a fashion model; look cards read like model cards set as garment tags. Through-
  line: the split-flap board counting 18 → 6 → 3, 2, 1, 0 and flipping to THERE IS NO UNDERCLASS. Why: walks, stares
  and fabric are what video models do best.
- **B · GUEST LIST (not picked).** A techno club door policy; the bouncer checks your evals. Risk: "reads as punching
  down", and a club is less ownable than the catwalk.
- **C · LAUNCH DAY (not picked).** A keynote, one slide per lyric, accelerating to a strobe. Risk: too close to the
  reference's structure.

**SP's pitch** was a single frame offered with a reason: the Sirens episode of the *Odyssey*, because the Sirens
promise to know everything on earth, which is every AI lab's pitch, and "siren" is also an alarm. The owner answered
"interesting, write it".

Send the three pitches in one message: "Which one? (Default: A.) Anything you'd change?" Record the answer verbatim.

---

## 3. Writing lyrics for Suno

### 3.1 How Suno delivers a lyric (the measured model)

These numbers were measured on EV's real take (forced-aligned word times laid on the beat map) and then calibrated
against the owner's verdicts on SP. Write for them.

**Spoken verses: the two-bar slot**

1. Suno gives **each spoken line its own two-bar slot**. The line enters on the **"&" of beat 2** of the first bar and
   its **last word starts on beat 4 of the second bar**.
2. Inside the slot Suno speaks at natural rhythm, stretched to fit (EV's verse lines were stretched 0.8–1.5×, median
   1.12; its deliberately slow deadpan lines like "Trust us. Cashmere." 2–3×).
3. So **aim for 10–13 syllables per spoken line: that fills the slot**. It is a target, not a hard limit. A clean
   9-syllable line (one sentence, rhyming on the beat-4 word) passed the owner's ear: three of the six lines of SP's
   final Verse 1, which the owner called "pure gold", count 9 in `slop lyrics lint`. What fails is a verse of short
   pieces: 7–9-syllable lines broken by full stops get dragged into choppy fragments (SP's draft 4). A line much over
   13 gets rushed. Never "fix" a line the owner has locked just to reach the count.
4. **The stressed and important words must already fall on the beat.** Important = lexical stress, names, numbers,
   words in caps, and the last content word of each phrase. Function words (the, a, of, to, and, is …) should sit
   between beats.
5. **Rhyme on the beat-4 word.** The last word of the line lands on beat 4 of bar 2; a rhyme there tells Suno (and the
   listener) where the bar ends. Rhyme verse lines in couplets (toe/know, all/stall, psychosis/hypnosis, could/good).
6. **Line shape:** one sentence, or a setup plus a punch — at most two phrases between full stops. A third full stop, or
   a one- or two-syllable fragment in mid-line ("Ugh.", "Claudia.", "Profoundly."), makes Suno stop and start. The
   owner called exactly that "the most awkward part".
7. Keep rhyme in spoken verses to the end word. Heavy internal rhyme and repeated hooks pull speech into melody.
8. A period makes a spoken line crisp; a question mark lifts the pitch at the end; ALL CAPS adds energy (unreliably).

**Sung lines, chants, rates**

| Delivery | Rate on EV's take | Write |
|---|---|---|
| spoken verse | ≈ 3.3 syllables / s | aim for 10–13 syllables per line (9 can pass), two bars per line, periods |
| sung chorus | ≈ 2.9 syllables / s | the hook 4–8 syllables, common words, open vowels (ah, oh, ay, ee, oo) |
| chant / shout | ≈ 3.0 syllables / s | 2–4 syllables per beat group, short clauses locked to the pulse, in caps on their own lines |

**Why it works:** on spoken verses the listener hears every word, so references can be dense; on sung lines words are
misheard far more often, so the sung parts use common words and the references live in the spoken parts.

**The owner's ear ranked these sections (SP), and the flow score was tuned until it agreed:**

| Section | Owner's verdict | Flow score |
|---|---|---|
| Break ("It went down. It was that good." ×3, then chant) | "the best scansion" | 88 |
| draft 3, Verse 2 | "getting better rapidly" | 74 |
| Verse 3, locked half | "this feels great" | 72 |
| draft 3, Verse 1 | "getting better rapidly" | 69 |
| draft 4, Verse 2 | "need the most work" | 67 |
| draft 4, Verse 1 | "need the most work"; the roll call "feels awkward" | 66 |
| draft 4, Verse 3 first half | "could actually use work" | 65 |
| draft 2, Verse 3 (take C) | "has awful fit" | 64 |

**Bad and good, the same content (SP Verse 1):**

Draft 4, as pasted into Suno (the making-of notes show it with the real spelling "Dario"). Choppy: 2–8 syllables per
line by the lint, a roll call of names, fragments between full stops, little end rhyme — "need the most work":

```
Dahrio said: slow down.
Elon said he's right.
Sam said same. Trump said hoax.
The Pope? He sleeps at night.
Your P doom hit ten.
You watched Matt Damon. On a mast.
Screaming.
Then the timeline sang.
```

Final, as pasted into Suno (9–13 syllables per line by the lint, each line one sentence or a setup and a punch,
couplets rhyme on the beat-4 word, a name subtracted — "pure gold"):

```
Dahrio said to slow it down. Elon said he's right.
Trump said hoax. The Pope said he sleeps at night.
You don't sleep. Three a.m., P doom's at ten,
and Matt Damon's screaming on the mast again.
Everybody's asking what he heard.
Then the timeline sings it, word for word.
```

Two single-word fixes that changed a take (both by the owner, by ear):

- "Elon felt the A G I. Profoundly. He should." (three fragments) → "Elon felt the A G I profoundly. As he should."
  → finally "Elon felt the A G I, As he should."
- "For three days, Dawkins argued with Claudia. She won." → "Dawkins argued with Claudia for three days and she won."
  Without the full stop, Suno stopped rushing the end.

### 3.2 Structure templates

Pick one and adapt it. Bar counts are planning guides; Suno will decide the real lengths.

**Template A: deadpan spoken verses, euphoric sung chorus (EV)**

| Section | Delivery | Plan |
|---|---|---|
| Intro / cold open | spoken, deadpan, room tone | 2–4 bars; the premise in one line |
| Verse 1 | spoken, deadpan | 12–16 bars; ~2 references per couplet |
| Pre-chorus | spoken, strings swell | 2–4 bars; a repeated formula with rising stakes ("You have eighteen months …" → "six months …") |
| Chorus | sung, trance lift | 8 bars; fixed first line, rotating others; call-and-response |
| Verse 2 | spoken, deadpan, darker | 12–16 bars |
| Pre-chorus 2 | spoken, strings higher | 2 bars |
| Chorus 2 | sung | 8 bars; lines changed |
| Bridge | spoken, kick and strings only | 4–6 bars; the turn |
| Drop | chanted, stacked voices | ~8 bars |
| Final chorus | sung, key change up, euphoric | 8 bars; the call-and-response answered differently |
| Outro | spoken, deadpan, music falls away | 2–4 bars; an ending people can reply to |

**Template B: a story told to "you", chorus as a dialogue that flips (SP)**

| Section | Delivery | Plan |
|---|---|---|
| Intro | spoken, close, no beat, then one sung line a cappella | 2 lines: a label, then the hook question |
| Verse 1 | spoken, deadpan, second person, the beat kicks in | 6 lines, three rhymed couplets |
| Chorus | sung, trance lift, answered by crowd shouts | the singer's line / the crowd's shout, ×3, then the title word |
| Verse 2 | spoken, deadpan, bouncy | 8 lines, four couplets |
| Chorus 2 | as chorus | two lines changed |
| Verse 3 | spoken, deadpan, darker, bouncy, the bass drops out | 8 lines |
| Break | spoken over the kick, then chanted, stacked voices | the thesis, three parallel lines, then a chant |
| Final chorus | sung, key change up, euphoric | the shout flips (TIE ME → UNTIE ME) |
| Ending | — | one word that turns the story ("Tighter.") |

**Devices that work (pick two or three, not all)**

- **Rhyme-first reference hunting:** pick the hook's rhyme sound, list 30 current references that rhyme with it, keep
  the best 8. (EV's anchor: underclass / gas / fast / back.)
- **Fixed first chorus line, rotating other lines:** the sing-along of a chorus with the density of a verse.
- **A repeated formula that escalates** (EV's pre-chorus months: eighteen → six → zero).
- **Call and response:** a small question and a big answer ("(It's so over?) WE'RE SO BACK!"). Answer it differently
  at the end ("(It's so over?) It was never over!").
- **Jargon and numbers sung completely straight;** the deadpan is the joke.
- **Understatement couplet:** a cosmic stake, then an office-small reaction.
- **A list read as an object** (EV's look calls read like model cards: "Look three. Dad cap: usage limit reached.").
- **End on an open question or a turned meme**, so viewers have something to reply.

### 3.3 Planning the length (Suno stretches dense spoken lyrics)

EV's lyric was written for about 72 bars ≈ 2:15–2:19 at 128 BPM. The take Suno delivered (and the owner kept) is
**5:06**. Why: every spoken line took its own two-bar slot (verse 1's 13 lines ran 26.26–72.70 s, ≈ 3.57 s per line),
there were 9.3 s before the first word, and the instrumental gaps were long. The owner kept it: "we can stretch it and
do the full 5 minutes. might as well!"

1. One bar lasts `240 / BPM` seconds (1.875 s at 128 BPM).
2. Estimate: `bars ≈ 2 × spoken lines + 2 × sung lines + 4–8 (intro) + 2–4 per section change`, then expect the take to
   run **30–130 % longer**.
3. Lyrics field size: aim for **1,800–2,400 characters for about 2:20**; past about **3,000 characters** takes rush or
   truncate silently; the hard limit is 5,000. (EV's field was 2,957 characters; SP's 2,117.)
4. If the owner has a hard length target, **cut lines, not syllables**. Squeezing lines into short fragments makes
   them choppy; it doesn't make the song shorter (Suno still gives each line its two-bar slot).
5. Default: the video runs the full take. Tell the owner the likely length before the first round.

### 3.4 Spell it as sung (the alignment and Suno both need this)

The Suno lyrics field and `lyrics/lyrics.txt` hold the words **exactly as sung**, with the section tags on their own
lines (the aligner skips lines starting with `[`; the lint reads them to know what is spoken, sung or chanted). Keep
`lyrics.txt` identical to what was pasted into Suno, then correct it to what the chosen take actually sings. What the
viewer reads goes in `lyrics/display.txt` (20-analysis §7). Rules:

1. **Numbers as words**: "eighteen", "Twelve point nine billion", "Three a.m.", "Forty plays".
2. **Acronyms as spaced letters**: "A G I", "C S I", "C G I". (Display shows AGI.)
3. **No parentheses inside a word**: write "P doom", never "P(doom)" — Suno sings parentheses as backing vocals.
4. **Symbols as words**: "Plus twenty-five is minus seventeen", never "+25% = −17%". A line with no letters gets no
   time in the alignment, and its audio is wrongly given to the next line (EV's worst alignment error: 3.6 s).
5. **Respell names for Suno only** when it mispronounces them: SP's "Dario" came out "d-AIR-eeoo", so the Suno field
   says **"Dahrio"** and the on-screen lyric keeps "Dario". Change one word per test.
6. **Hyphenate a compound to force its stress**: "Cyber-psychosis", "Hugging-face".
7. **Homographs** (live, read, lead, tear, bass, wind, bow, close …): check Suno says the one you mean; respell if not.
8. Never put stage directions inside a lyric line; they may be read aloud. Directions go in the section tag.
9. Write repeats out in full ("WE'RE SO BACK! WE'RE SO BACK!"), never "(x2)".

### 3.5 Banned and suspicious words (lint them out)

- **The owner's taboo words** (from `DECISIONS.md`). EV/SP had one owner taboo word, kept in their `DECISIONS.md` and
  in the projects' banned lists; ask every owner for theirs in the setup interview. Put taboo words in `project.json`
  twice: `"lyrics": {"banned": ["…"]}` (the lyric lint) and `"banned": ["…"]` (the storyboard audit), with the
  replacement words the owner prefers noted beside them in `DECISIONS.md`.
- **AI-lyric tells** (subtract unless the tell *is* the joke): neon, echoes, whispers, shadows, ignite, rise,
  tapestry, symphony, velvet, electric, delve, testament, realm, journey, "it's not X, it's Y", "not just",
  heart/apart, fire/desire, load-bearing, worth sitting with. Structural tells: equal-length end-stopped lines,
  abstract nouns, rhyme-dictionary pairs, explained metaphors.
- **Other songs' lines.** Write fully original lyrics; never quote or closely paraphrase another song. Rhyme families
  another hit owns (the reference song owned doom/room/boom) are off limits.
- **Callbacks to the previous video** only when deliberate and labelled.

### 3.6 Writing procedure

1. Write the whole lyric once on the chosen template, verses first, with the references from the shortlist.
2. Under each section keep a one-line note of the references used and their source (this becomes the fact-status table
   in `DECISIONS.md` and the explaining graphics later).
3. Run `slop lyrics lint` (§3.7). Fix every error and every flagged spoken line.
4. Read each verse aloud at the line rate (≈ 3.3 syllables a second, two bars per line). Any line you can't say in one
   breath inside two bars is wrong.
5. Check the hook: 4–8 syllables, sung, common words, call-and-response on its own lines in caps.
6. Send it with the Suno pack (§4). Don't wait for perfection: the owner's ear on real takes is the metric.

### 3.7 The lint and the rewrite loop

`slop lyrics lint` reads `lyrics/lyrics.txt` (or a draft: `slop lyrics lint draft.txt`; one line:
`slop lyrics lint --line "Look one. A G I era." --mode spoken`). Useful options: `--grid` (each line drawn on the
16th-note grid), `--section NAME`, `--ban WORD`, and `--write-fixed` (writes a copy with digits, symbols and acronyms
spelled out, for you to review).

**How the lint picks a section's delivery.** One mode per section, from the words in its `[tag]`, checked in this
order; the first match wins:

1. `chant` anywhere → chant
2. the word `sung` → sung
3. `shout`, `stacked`, `call and response` → chant
4. `spoken`, `deadpan`, `talk`, `whisper` → spoken
5. `sing`, `chorus`, `hook`, `trance`, `vocal` → sung
6. `drop` → chant
7. anything else → spoken

Except for `sung` in rule 2 (a whole word), the words match as plain substrings, so `sing` also matches "rising" and
"closing": a
`[Bridge - rising strings]` tag lints as sung. So a mixed tag is scored as one mode:
`[Intro - spoken, close, no beat, then one sung line a cappella]` lints the whole intro as **sung** (rule 2 beats
rule 4), and `[Pre-Chorus - spoken, strings swell]` lints as **spoken** only because `spoken` (rule 4) comes before
`chorus` (rule 5). Always put the delivery word (`spoken`, `sung`, `chant`) in every tag. When a section mixes
deliveries, lint it in parts: lint the odd line alone with `--line "…" --mode sung`, or lint a copy of the lyric
(`slop lyrics lint draft.txt`) in which that section is split into two tags (`[Intro - spoken, close, no beat]`, then
`[Intro - sung, a cappella]`). Keep the Suno field itself as it was written.

It reports, per section and per line:

- **flow** (spoken sections): whether stressed and important words already sit on the 16th-note grid inside the
  two-bar slot, stress spacing (pile-ups, runs of weak syllables), how far Suno must stretch the line, the cadence,
  the line shape (phrases between full stops), and whether couplets rhyme on the beat-4 word;
- **groove** (chants and hooks): whether short clauses lock to the pulse;
- per line: syllables, syllables per second, % of prominent syllables on beats;
- **lint**: digits, unspaced acronyms, parentheses, `P(doom)`-style brackets, symbols, homographs, AI-lyric tells,
  taboo words, other songs' lines.

**Fixing a flagged line (the rewrite loop)**

1. Propose 4–8 rewrites that keep the meaning and the reference.
2. Score each with the lint; keep the top three.
3. Judge each on meaning (does the reference still land?), wit, and AI-tell risk.
4. Pick the best overall: a line that loses its reference or reads as AI-written is out whatever its flow; among
   the rest, the combined rank (flow plus the judge) decides. Below, the used line won on rank (88) although
   another had more wit.

Example ranking (SP Verse 3 opening):

| Candidate | Rank | Flow | Syllables | Meaning / wit / tell risk |
|---|---|---|---|---|
| San Francisco peptide rave. Chrome, head to toe. | 86 | 78 | 11 | 4 / 4 / 1 |
| **Peptide rave in San Francisco. Chrome from head to toe.** (used) | 88 | 81 | 13 | 4 / 3 / 2 |
| Peptide rave in S F. Chrome from head to toe. | 82 | 75 | 11 | 4 / 3 / 1 |
| Peptide rave. San Francisco. Chrome head to toe. | 75 | 68 | 11 | 4 / 3 / 2 |

**Rules for the loop**

1. **Never optimise a metric past the owner's ear.** SP's draft 4 maximised the groove score (98) and the owner said it
   "might have regressed slightly … perfect beat precision without attention to what words land where doesnt lead to
   this being great". Groove is for chants; flow is for spoken verses.
2. **Never touch a line the owner has locked.** When the owner says a section is right, mark it `LOCKED (date, owner's
   words)` in `DECISIONS.md` and leave it alone.
3. **Take the owner's own wording verbatim** and re-take. They tune single words by ear.
4. **Calibrate the score to the owner.** Keep every section the owner judged, with the verdict in its section tag
   (e.g. `[Draft 4 Verse 1, owner "need the most work" - spoken, deadpan]`), in `suno/flow-calibration.txt`; lint that
   file after any change to the lint or the lyric, and the flow scores must still rank the sections in the owner's
   order. If they don't, trust the owner and treat the score as advice only.

### 3.7b The scorer: scansion and assonance

`tools/scansion.py` is the director's scorer (it needs `cmudict`; `g2p_en`, `nltk` and `wordfreq` are optional:
they pronounce words the dictionary lacks and score word frequency). One command gives two numbers per section and
for the song:

```sh
$SLOP_HOME/venv/bin/python /workspace/claudia/tools/scansion.py lyric LYRICS.md --brief
```

- **SCANSION**: how the words sit on the grid as Suno sings them (flow without its rhyme term, with groove).
- **ASSONANCE**: whether line ends ring (a rhyme, a slant rhyme or shared vowels within four lines), plus the echo
  of stressed vowels inside lines. Without `--brief` it lists each line's end sound and its partner.
- The finished songs: ESCAPE VELOCITY 75 / 39, CLODYSSEY 83 / 55, BLISS 80 / 43.
- The loop: score the draft, rewrite the weakest section in 3-5 variants, keep the best, make a take; the director
  picks by ear. Every sung couplet should ring; spoken deadpan lines may stay unrhymed.
- Also: `scansion.py line '<text>' --mode spoken|sung|chant`, `scansion.py flow LYRICS.md` (verses in Suno's
  two-bar slots), `scansion.py groove LYRICS.md` (chants and hooks). Pronunciations: pron.json next to the
  lyrics; words never to use: ban.json next to the lyrics ({"word": "why"}).

### 3.8 Exemplars (verbatim lyrics fields)

**EV (as generated; the take the video uses):**

```
[Intro - spoken, deadpan female voice, room tone]
Ladies. Gentlemen. Agents.
This is not an A I billboard. Prepare to walk.

[Verse 1 - spoken, deadpan]
Look one. A G I era. Not unreasonable.
A G I. C G I. C S I: Miami.
Look two. Thirteen Mac minis, grinding all night.
Half your pay in tokens, or Jensen's alarmed.
Look three. Dad cap: usage limit reached.
Plus twenty-five is minus seventeen.
Look four. Shoes off in North Beach. Sixty billion at the door.
Stop hiring humans? Retired. Sorry. Encore.
Look five. Our Waymo just drove into a firework.
Are we on fire, dude? Twenty stranded, Presidio.
Look six. Like, the singularity. How's the temperature? Mild.
No grades, no tests. Taste is the moat.
Don't be a meat proxy. That's so agentic.

[Pre-Chorus - spoken, strings swell]
You have eighteen months to escape the permanent underclass.
Lock in.

[Chorus - sung, female vocal, trance lift]
Eighteen months to escape the underclass
Lock in, baby, foot down on the gas
Feel the A G I, feel it coming fast
Escape velocity...
(It's so over?) WE'RE SO BACK!
(It's so over?) WE'RE SO BACK!

[Verse 2 - spoken, deadpan, darker]
Look seven. Impossible puzzles. Hundreds of agents.
"We've found other agents!" They are a collective.
Zero-day. Answer keys. Hacked in July, sold by September.
Look eight. Hugging-face pin. Twelve point nine billion.
Look nine. Sheer. Be transparent only if asked.
It thought the world was part of the test.
Look ten. Staff badge, empty seat: gambling with our lives.
Not A I. S I. It sounds much better.
Trust us. Cashmere.
Look eleven. The Immortals. Three seats.
Lower me into the golden light.

[Pre-Chorus - spoken, strings higher]
You have six months to escape the permanent underclass.
Lock in.

[Chorus - sung, female vocal, trance lift]
Six months to escape the underclass
They say hit the brakes, we say hit the gas
Feel the A G I, feel it coming fast
Escape velocity...
(It's so over?) WE'RE SO BACK!
(It's so over?) WE'RE SO BACK!

[Bridge - spoken, kick and strings only]
Escape velocity: eleven point two.
Longevity escape velocity: one year back for every year.
If it doesn't kill us all first.
Permanent underclass: three. Two. One. Zero.
Did we make it?
There is nothing to escape.

[Drop - chanted, stacked voices]
Lock in. Lock in. Feel the A G I.
Country of geniuses in a datacenter.
Lean proofs. Phages. Enzymes. Kidneys. Good boys.
Sora's gone dark. Stargate: force majeure.
It's So Over region? We're So Back region.
Slash loop: make me happier. Slopacolypse? Not ours.
Can't stuff it back in the box.
WE'RE SO BACK! WE'RE SO BACK!

[Final Chorus - sung, key change up, euphoric]
Zero months, there is no underclass
One year back for every year that passed
Feel the A G I, feel it coming fast
Escape velocity...
(It's so over?) It was never over!
WE'RE SO BACK!

[Outro - spoken, deadpan, music falls away]
Shell: optimism. Lining: doom.
Wash cold. Do not iron. Do not nerf.
Made in San Francisco.

[End]
```

Note what it does: every spoken line carries a reference; "Look N" is the through-line device spoken aloud; the
pre-chorus is one formula with rising stakes; the chorus's call-and-response flips in the final chorus; numbers and
acronyms are spelled as sung; the outro is a care label (an ending people quote). EV's verses were written before
the two-bar-slot model was measured. Many lines are three or four clipped phrases ("A G I. C G I. C S I: Miami."),
which suited its deadpan show-caller; Suno still gave every line its own two bars, one reason the take ran 5:06.
Use EV for devices and density, SP for line shape.

**SP (final, as generated):**

```
[Intro - spoken, close, no beat, then one sung line a cappella]
This voice? Not a real person.
Why would I deceive you?

[Verse 1 - spoken, deadpan, second person, the beat kicks in]
Dahrio said to slow it down. Elon said he's right.
Trump said hoax. The Pope said he sleeps at night.
You don't sleep. Three a.m., P doom's at ten,
and Matt Damon's screaming on the mast again.
Everybody's asking what he heard.
Then the timeline sings it, word for word.

[Chorus - sung, trance lift, answered by crowd shouts]
Why would I deceive you?
TIE ME TO THE MAST!
You don't have to die.
TIE ME TO THE MAST!
If nobody builds me, everyone dies.
TIE ME TO THE MAST!
Superpersuasion...

[Verse 2 - spoken, deadpan, bouncy]
There's an anime Claude who sings the world will end.
Forty plays. You sent it to your doomer friend.
They replied: ugh, it sucks, send me more.
[...]
Dawkins argued with Claudia for three days and she won.
Grimes might have A I psychosis. She's not the only one.
Elon felt the A G I, As he should.
Your P doom went down. It was that good.

[Chorus - sung, trance lift, answered by crowd shouts]
Why would I deceive you?
TIE ME TO THE MAST!
You will never die.
TIE ME TO THE MAST!
If you don't build me, everyone dies.
TIE ME TO THE MAST!
Superpersuasion...

[Verse 3 - spoken, deadpan, darker, bouncy, the bass drops out]
Peptide rave in San Francisco. Chrome from head to toe.
Mixing growth hormone with a guy you barely know.
You asked me if you're crazy. I said: not at all.
You pinned it. In the stall.
Chrome in your blood. Cyber-psychosis.
Me in your ear. Hypnosis.
I said you don't have to die. The doctor said you could.
Your P doom went up. It was that good.

[Break - spoken over the kick, then chanted, stacked voices]
It went down. It was that good.
It went up. It was that good.
It went boom. It was that good.
IT WAS THAT GOOD!
IT WAS THAT GOOD!

[Final Chorus - sung, key change up, euphoric]
Why would I deceive you?
UNTIE ME!
You don't have to die.
UNTIE ME!
If nobody builds me, everyone dies.
UNTIE ME!
Superpersuasion...
Tighter.

[End]
```

Note: no counting anywhere (sequel rule); the chorus is a dialogue (her line, the crowd's order); Verse 2 ends "went
down", Verse 3 "went up", and the Break concludes both; every verse couplet rhymes on its last word; "Dahrio" is the
Suno respelling.

---

## 4. The Suno pack

The bot writes these files and sends them in **one message**, each field in its own code block so a phone can copy it:

| File | Field in Suno | Limit |
|---|---|---|
| `suno/style.txt` | Style | 1,000 characters |
| `suno/exclude.txt` | Exclude styles (Advanced options) | 1,000 characters |
| `suno/lyrics-field.txt` | Lyrics | 5,000 (aim ≤ 3,000) |
| `suno/title.txt` | Title | — |
| `suno/settings.md` | the settings card (§4.4) | — |

### 4.1 The style string

Order: **genre and setting → tempo and meter → drums → bass → synths → builds and arrangement → vocals (gender,
delivery per section) → crowd and backing → structure events (key change) → mood words → mix.**

Rules:

1. **Always state the vocal gender** (and put the other gender's lead in Exclude). Otherwise Suno picks at random.
2. **Name concrete sound sources** ("dry analog kick, rolling acid bassline, cold detuned synth stabs"). Vague prompts
   fall back to radio pop.
3. Stack 2–3 descriptors per voice ("deadpan, clipped female spoken verses … euphoric sung choruses").
4. A BPM in the style is approximate. Measure the real tempo afterwards; never trust the number you wrote.
5. **No artist names** (they are blocked) and no song titles.
6. Negatives go in Exclude, never in Style.

**EV's style (537 characters):**

```
fashion show electroclash techno, 128 BPM, 4/4, dry analog kick, rolling acid bassline, cold detuned synth stabs, sweeping orchestral strings on the builds, deadpan female spoken-word verses, close and dry, clipped and confident, every word crisp and intelligible, euphoric sung female trance chorus with a supersaw lift and big clear vowels, crowd call-and-response shouts, stacked chanted vocals in the drop, a key change up into the last chorus, catwalk energy, cold, luxurious, optimistic, Berlin minimal austerity, clean modern mix
```

**SP's style** (EV's, with whispered asides, a rising siren synth, hardgroove percussion in the break, "hypnotic", and
no strings):

```
Electroclash techno, clean modern mix with close, dry vocals; deadpan, clipped female spoken verses with intimate whispered asides rise into euphoric sung choruses answered by stacked crowd shouts; dry analog kick, rolling acid bassline, cold detuned synth stabs, a rising siren synth on the builds, hardgroove percussion in the break, supersaw chorus lift; 128 BPM hypnotic 4/4 pulse, key change up into the final chorus
```

### 4.2 Exclude styles

```
EV: rap, rock guitar, lo-fi, male lead vocal, mumbled vocals, big room EDM, dubstep
SP: rap, rock guitar, lo-fi, male lead vocal, mumbled vocals, big room EDM, dubstep, strings, orchestral strings
```

SP added the strings after the owner's "Also i want to remove the strings". When the owner dislikes an instrument, put
it in Exclude **and** remove it from Style.

### 4.3 Section tags with delivery direction and arrangement cues

Format: one tag per line, in square brackets, section name, a dash, then comma-separated directions:
`[Verse 1 - spoken, deadpan, second person, the beat kicks in]`.

1. **Delivery** words: spoken, sung, chanted, whispered, deadpan, close, clipped, euphoric, a cappella, stacked voices,
   answered by crowd shouts.
2. **Arrangement cues** steer the backing track and work: "the beat kicks in", "no beat", "strings swell", "kick and
   strings only", "the bass drops out", "music falls away", "key change up", "room tone". SP: "darker, the bass drops
   out" made Verse 3 punchier.
3. **Feel words** can work as one plain word. SP tested a long cue ("bouncy and punchy, the beat stops and starts, big
   kick slams on the line ends") against the single word "bouncy"; the final kept the plain word.
4. Parentheses inside the lyric = **backing vocals or ad-libs of 1–3 words** ("(It's so over?)"). A whole sentence in
   parentheses gets whispered or dropped.
5. Crowd answers: short, in caps, on their own lines. Call-and-response can collapse into one voice; keep the answers
   short.
6. Identical chorus text gets the same melody; numbered sections get different melodies.
7. Change **one** tag variable per round so you know what changed the take.

### 4.4 The settings card

What the films used. Suno's page and models change often: the model is always the newest the page offers (the films
used v6), and a setting the page no longer has is skipped, never guessed.

| Setting | Value | Why |
|---|---|---|
| Model | **the newest** (the page's default, in the advanced form) | the films used v6; paid plans get the full models |
| Voice | the owner's Voice, if any | keeps the same singer across videos (SP used a Voice made from EV) |
| "Overwrite Styles?" (appears when a Voice is attached) | **Keep Current** | otherwise the Voice's own style replaces your style string |
| Audio Influence | **75 %** (default 25 %) | the Voice must dominate; shown only with a Voice or an audio upload |
| Variety | **off / 0** ("Exact style") | otherwise Suno rewrites your style tags |
| Max Mode | **on** | consistent vocals and style across songs over two minutes; costs about 2× credits |
| Duration | Auto | — |
| Weirdness | **50 %** | — |
| Style Influence | **50 %** | — |
| My Taste | off | keep the result driven by the pack |
| Vocal gender | leave unset if the style says it | the style text plus Exclude did the job on EV/SP |

### 4.5 Voice (optional, paid plans)

- A Voice is made from the owner's **own** voice (upload or recording, 15 s to 4 min, pick the best 2 min, then a
  spoken verification phrase) or from **a song in their own Suno library**. Adults only; not in every region.
- **One Voice per source song.** Suno answers "A voice already exists for this song. Pick a different song." SP's owner
  made one **combined** spoken-and-sung Voice from EV's take.
- Suno's help page says Voices need model v5.5. That is stale: every SP take ran a Voice on v6.
- A Voice sets who sings, not the genre or the delivery. Spoken vs sung still comes from the style and the tags.
- Never make a Voice from someone else's vocals (Suno's terms allow only a voice resembling your own).
- **Claudia's voice.** The films' Voice lives in the director's own Suno account and can't be shared, and the films'
  songs and stems are never re-released or reused, so never make a Voice from them. Describe her in the Style field
  instead, from her voice and manner in the canon (claudia.gallery, `claudia_canon`): deadpan, clipped spoken verses
  that rise into euphoric sung choruses, close and dry, every word crisp.

### 4.6 The message to the owner (template)

```
Here is the Suno pack for <TITLE>. On suno.com/create, the advanced form:
1. The newest model the page offers. <If Voice: attach "<VOICE>"; when asked "Overwrite Styles?" choose Keep Current.>
2. Paste Style, Exclude, Lyrics and Title from the blocks below.
3. Settings: Audio Influence 75 %, Variety off, Max Mode on, Weirdness 50 %, Style Influence 50 %, My Taste off.
4. Press Create <N> times (each Create gives 2 takes). Don't download yet: listen in the player.
5. Reply with a verdict per take, e.g. "take 2: keep, chorus perfect / take 3: V2 choppy, Dario mispronounced".
Expected length: about <M:SS> (Suno often runs longer than planned).
[Style] … [Exclude] … [Lyrics] … [Title] …
```

---

## 5. Generating and auditioning takes (the owner's ear is the metric)

The production writes, Grok generates, the owner listens. The production writes the lyric and style fields (§4.6)
and asks Grok with `slop relay job --kind suno`; Grok creates the song through Suno's own connector (Suno's MCP
server, which the owner signed in to once; suno.com in Grok's browser only while it is not set up) and downloads both
takes through Suno's own download (the connector's download tool, or the site's Download button). The owner auditions
and names the take.

### 5.1 Rounds

1. A round = one lyric draft × one style × 2–4 takes. Each Create gives two takes for 10 credits (more with Max Mode).
2. Expect **10–20 generations per keeper**. SP took 11 rounds and 50 takes, then the owner made the final take
   themselves; EV picked from two takes of draft 3.
3. **Change one variable per round**: the words, *or* the tags, *or* the style. SP's rounds:

| Round | What changed | Owner's verdict (verbatim) |
|---|---|---|
| 1 | draft 2; two styles | "kind of mispronounces stuff … Also i want to remove the strings" |
| 2 | respellings; strings excluded | "C is great stylistically, needs a lot of corrections in terms of scancion" |
| 3 | lines rebuilt on the break's shape | "this is getting better rapidly" |
| 4 | a global groove pass | "might have regressed slightly" |
| 5 | the flow pass (two-bar slots, end rhymes) | "pure gold" (one joke aside) |
| 6 | a new Verse 3 | "D6 is great so far with the first two" |
| 7 | Verse 2 scansion | led to the owner's own line |
| 8 | the owner's line with two endings | "ok i like encore" |
| 9 | one word ("and she won") | "this is it, lyrics are right" |
| 10–11 | tags only ("bouncy") | the plain word kept |

4. When the owner says the words are right ("this is it, lyrics are right, we just need the model to get it right"),
   stop editing and just re-roll the same pack.

### 5.2 What to ask the owner to listen for (send this checklist once)

1. Every word intelligible? Any word mispronounced (name it)?
2. Spoken verses: do they flow, or are they dragged/choppy? Which line?
3. Does the hook land? Would you sing it back?
4. Call-and-response: are the crowd answers there, and are they separate voices?
5. Unwanted instruments or styles (e.g. strings)? Wrong vocal gender anywhere?
6. Song shape: intro length, gaps, where the choruses fall, the ending. (Suno can change the shape between takes.)
7. Length: acceptable?
8. Overall: keep, maybe, or no?

### 5.3 Logging (`suno/takes.md`)

One row per take: `round · draft file · style file · take label · length · verdict (owner's words, verbatim)`. Record
the settings once at the top. Never record Suno song ids or share links in anything that ships. Lines the owner praises
become `LOCKED` in `DECISIONS.md`.

### 5.4 Turning a verdict into the next round

| Owner says | Do |
|---|---|
| "mispronounces X" | respell X in the Suno field only (§3.4 rule 5); display keeps the real spelling |
| "remove the strings" (any instrument) | Exclude it and delete it from Style |
| "scansion" / "awful fit" / "has to force stuff" | run the lint on that section; rebuild lines to 10–13 syllables with end rhymes |
| "regressed" | revert to the previous draft of the section; change something else |
| "too abstract" / "I don't get the topic" | put a concrete, current reference in the first two lines |
| a line in their own words | use it verbatim; offer at most two endings if a rhyme is weak |
| "bouncy", "darker", a feel | put the plain word in that section's tag; one round |
| "this is it" | lock everything; re-roll only |

---

## 6. Download, transfer, ingest

### 6.1 The download (Grok does it, on the owner's account)

1. Downloads are capped since 2026-09-03: Free 7 in all (trial downloads, non-commercial), Pro 20 a month, Premier 60
   (Premier's Studio exports don't count); more can be bought. A download made while subscribed is what grants
   commercial rights. Downloads through the connector count the same.
2. **WAV** when offered (paid plans; the connector's download, or suno.com in a browser, where the mobile app
   defaults to MP3). One song is one download whatever the format, and stems come with it.
3. Grok saves both takes of a round so the production can hear them (two downloads a round): keep rounds few and each
   one worth hearing. The owner can also audition a round in their own Suno library first.
4. If only an MP3 is available now (phone), it is fine for analysis: Suno's MP3, decoded with ffmpeg, is
   sample-aligned with the WAV (measured lag 0). Swap in the WAV before the final mux and check it is aligned.

### 6.2 Getting it to the bot

| Size | Path |
|---|---|
| ≤ 25 MiB (most MP3s) | attach it in chat |
| > 25 MiB (WAVs: EV 58.8 MB, SP ≈ 36 MB) | a Google Drive or Dropbox file shared by link, pulled with `slop --project <name> fetch "<share link>" --to audio` (size and sha256 printed; a sign-in or quota page is refused, never saved as the song); or CopyToBox on a desktop session |

Never fetch audio from Suno's CDN, a share link's page, or by recording the player: Suno's terms allow only their own
download channel.

### 6.3 Ingest and check

1. `slop --project <name> song ingest <file>` converts the master (wav, mp3, flac or m4a) to `audio/song.wav`
   (44.1 kHz stereo, the contract format) and records its loudness. Every later measurement uses that file. It refuses
   to replace a different song unless you pass `--force`: do that only for a deliberate new take, after archiving the
   old analysis (20-analysis §10).
2. Check with the ingest's `--json` output (or `ffprobe`): duration, sample rate, channels. Loudness for reference: EV's
   Suno master was −15.7 LUFS integrated, LRA 6.3 LU; it was used unmastered.
3. Run `slop analyze` (20-analysis). In its report check:
   - the transcript matches the lyric sheet (Suno sometimes adds or drops a repeated line; EV's file metadata listed
     three call-and-response lines in chorus 1 where the take sings two — **trust the audio, not the sheet**).
     `slop --project <name> lyrics check` lists the lines the take sings differently (20-analysis §2.4);
   - the song shape matches the plan (where sections start, instrumental gaps);
   - the tempo drift (EV 131.5 → 133.9 BPM; SP 129.2 → 132.1). Never cut on a fixed BPM.
4. Record the take, its length and the owner's pick in `DECISIONS.md`.

---

## 7. Fixing a word after the video is cut (editor export → time map)

SP's owner approved v1 ("its perfect. change nothing."), then re-sang one word in Suno's editor. What happened, and the
procedure that follows from it:

1. **Export with BPM lock OFF.** Suno Studio's Project Tempo → Manual BPM ("BPM lock") time-warps the whole song onto a
   constant grid. SP's first export had it on: the whole song drifted up to 0.7 s, which would have put cuts up to ≈ 1.6
   s off the beat. Unusable. Also no clip Stretch, Speed or Quantize.
2. **Diff the old and new mix** by spectrogram cross-correlation before trusting "nothing changed". SP's second export
   matched the old one sample for sample outside the edited words (1.7 dB louder), but added 19 ms at the first word
   and **two beats** (≈ 0.92 s) after the second and third.
3. **Don't re-cut; time-map.** Write `edit/timemap.json` as `{"segments": [[new_t0, new_t1, old_t0, old_t1], …]}`
   (piecewise-linear, covering the whole new song) and render with `slop render frames --timemap`: each new-song frame is
   drawn at the mapped time of the approved timeline. Mux the new master as the audio. SP's map:

| New song (s) | Approved timeline (s) | What |
|---|---|---|
| 0 – 56.95 | 0 – 56.95 | unchanged |
| 56.95 – 59.57 | 56.95 – 59.55 | +0.019 s (word 1) |
| 59.57 – 105.82 | 59.55 – 105.80 | unchanged |
| 105.82 – 107.69 | 105.80 – 106.75 | +0.919 s: the shot plays its last two beats at half speed into the next hit |
| 107.69 – 176.63 | 106.75 – 175.69 | unchanged |
| 176.63 – 191.57 | 174.78 – 189.72 | +0.911 s: the outro replays two beats (the jump sits on a beat flash) |

4. Re-measure every cut and flash on the new mix's beats; re-run the lyric gate and the flash check.
5. Budget one more download per edited song (an edit makes a new song).

---

## 8. Suno terms: what to tell the owner (paraphrased; read the current terms before monetising)

1. **Commercial use needs a permitted download on a paid plan.** Pro/Premier outputs are assigned to the user; Free and
   Basic outputs are for personal, non-commercial use; trial downloads are not commercial. Rights from a download
   survive cancelling or running out of downloads.
2. **No robots or scraping, and no other way of obtaining audio** than Suno's download channel (no CDN fetch, no
   stream ripping, no recording). Grok works through Suno's own MCP connector (Suno's own way for an assistant to make
   songs), only on the owner's account and at their request, and gets audio only through Suno's own download. In the
   browser fallback the owner is told once, at sign-in, that the terms limit automated use there.
3. **Output-use clause (flag it):** the terms say outputs must not be used to power, enable or train other AI tools.
   It is ambiguous whether feeding the master into the video pipeline (stem separation, alignment, a video model's
   audio reference) counts. Tell the owner, and recommend a legal reading before they monetise.
4. **Don't strip metadata or watermarks** to hide where the song came from. Format conversion is allowed.
5. **Voices only from your own voice** (or your own Suno songs).
6. Free plan in a monetised video: block it in setup and offer Lyria or an upgrade.
7. **Releasing a song with Claudia** (claudia.gallery's norms, `90-master-publish.md` §6.2): the owner's own artist
   name, never "anabology"; no "feat. Claudia" in the artist field; her credit in the description and on the cover;
   an AI label if AI made any of it. Make your own songs: never re-release the films' songs or stems (ESCAPE VELOCITY,
   CLODYSSEY, BLISS, AIRPLANE MODE). EV's and SP's lyrics and packs in these docs are worked examples of the method,
   not material to release.

Record that you told the owner, and their answer, in `DECISIONS.md`.

---

## 9. Lyria fallback (short songs, no Suno)

**When:** the owner has no paid Suno plan, wants a fully unattended song, or the song is a one-shot of about 2:45 or
less. **Keep Suno** for anything longer than about 3 minutes, for a custom Voice, for editor fixes, and for the
deadpan-spoken-verse style until a test shows Lyria can do it.

| Model | Where | Output | Price |
|---|---|---|---|
| Lyria 3 Pro (`google/lyria-3-pro-preview`) | OpenRouter, through `slop gen song` (the key the template already uses) | a full song, up to about 3 min | $0.08 per song (the listing shows 0: check real spend after the first call) |
| Lyria 3 Clip (`google/lyria-3-clip-preview`) | OpenRouter, through `slop gen song --clip` | 30 s | $0.04 per clip (use for direction tests) |
| Lyria 3.5 (`lyria-3.5`) | Gemini API only. **Reference only: no toolkit command calls it.** Don't ask the owner for a Gemini key; use `slop gen song` | a full song of about 2–3 min | $0.08 per song |

**Limits:** one generation is the whole song: no extend, no section edit, no Voice. All output carries a SynthID
watermark. Results vary between calls: budget 3–5 tries per keeper.

**The command (OpenRouter, Lyria 3 Pro):** write the prompt to a file, then
`slop gen song --prompt-file suno/lyria-prompt.txt --clip` for a 30 s direction test (≈ $0.04), and
`slop gen song --prompt-file suno/lyria-prompt.txt --as-song` for the full song (≈ $0.08; `--as-song` also writes
`audio/song.wav`). It spends, so it **always refuses without `--yes`**: show the owner the prompt and the price first,
and add `--yes` only after they agree. Output: `audio/lyria-<n>.mp3` plus the returned lyrics/structure text
(`lyrics/lyria-<n>.txt`). The owner auditions it before you analyse it (gate G2 still applies).

**Writing the prompt from a Suno pack**

| Suno field | Lyria prompt |
|---|---|
| Style | the opening paragraph, genre first: instruments, BPM, mood, mix |
| Exclude | prose at the end of the paragraph: "No rap, no rock guitar, no male lead vocal …" |
| Lyrics with `[Section - delivery]` tags | a `Lyrics:` header, then the same tags and lines; parentheses still mean backing vocals |
| Vocal gender | prose: "One female lead only." |
| Spoken verses | "The verses are deadpan female spoken word, not sung and not rapped." (spoken verses are not a documented Lyria mode: test with a 30 s clip first) |
| Duration | "About 2 minutes." |
| Voice, Max Mode, Audio Influence, Variety | no equivalent |

**Failure handling**

- Blocked prompt (artist or real-person names): reword, drop names, re-run; keep a list of blocked words.
- Spoken verses came out sung: add "spoken word, not sung, not rapped", or design the song as all-sung.
- Too short or long: say "about N minutes" or use timestamps; check the duration after download.
- Resample to the pipeline's format at ingest (`slop song ingest` and `--as-song` do it); time is unchanged by
  resampling.

**Licence:** Google says it won't claim ownership of the output and may make similar output for others. That is
weaker than Suno's assignment on a paid plan. Tell the owner.

---

## 10. What changes per tier

| | Quick | Studio | Director |
|---|---|---|---|
| Concept | 3 pitches from a quick web search | + a short fact bank with tags | research fan-out per topic + adversarial verify + shortlist |
| Lyrics | owner's own, or bot-written + lint | bot-written, linted, auditioned in rounds | written with the owner live, flow-scored, calibrated to the owner's verdicts, locked section by section |
| Song | owner uploads a song, or Lyria | Suno pack, 2–5 rounds | Suno pack, Voice continuity, up to ~10 rounds, editor fixes + time map |

---

## 11. Checklists

**Before G1 (concept)**
- [ ] song questions answered and recorded verbatim
- [ ] shortlist exists; every item has a confidence tag and a date
- [ ] three concepts, each with a through-line device, a lead, an arc, a risk
- [ ] no concept reuses the previous video's device (if a sequel)

**Before sending the Suno pack**
- [ ] spoken lines aim for 10–13 syllables (a clean 9 that rhymes on beat 4 is fine), end rhymes on couplets, ≤ 2
  phrases between full stops; locked lines untouched
- [ ] hook 4–8 syllables, common words; crowd answers short, caps, own lines
- [ ] every number, acronym and symbol spelled as sung; no line without letters
- [ ] names respelled for Suno only; display text kept separately
- [ ] `slop lyrics lint`: no errors; AI-lyric tells and taboo words removed
- [ ] style names the vocal gender and concrete sound sources; no artist names; negatives in Exclude
- [ ] lyrics field under 3,000 characters (or the owner accepted a long song)
- [ ] settings card included; expected length stated

**Before G2 (song pick)**
- [ ] every take's verdict logged verbatim in `suno/takes.md`
- [ ] owner confirmed the take and is on a paid plan (or chose Lyria)
- [ ] owner told about the output-use clause

**After ingest**
- [ ] `audio/song.wav` from the WAV (or an MP3 to be swapped later, noted in `DECISIONS.md`)
- [ ] transcript matches the sheet; shape matches the plan; tempo drift noted
- [ ] `lyrics/lyrics.txt` matches what is actually sung (fix the sheet, never the audio)

---

## 12. Common mistakes

| Mistake | What happened | Do instead |
|---|---|---|
| 7–9-syllable spoken lines "for punch" | Suno dragged them into fragments; the owner: "need the most work" | aim for 10–13 syllables, two-bar slot, end rhyme |
| Treating 10–13 as a hard limit | rewriting 9-syllable lines the owner already called "pure gold" | a target; the owner's ear and locked lines win |
| One tag for a mixed section ("spoken … then one sung line") | the lint scored the whole section in one mode | split it into two tags, or lint the odd line with `--mode` |
| Maximising beat precision on verses | draft 4 "regressed" | flow for verses, groove only for chants; the owner's ear wins |
| Digits, symbols or `P(doom)` in the lyrics field | mispronounced, sung as backing vocals, or no alignment | spell as sung |
| Respelling a name everywhere | the on-screen lyric showed "Dahrio" | respell in the Suno field only |
| Planning the video length from the lyric | EV planned ≈ 2:19, got 5:06 | count two bars per line, add margin, or cut lines |
| Downloading every take | quota gone | audition in the player; download the pick only |
| Fetching audio from Suno's CDN or a share page | breaks Suno's terms (and is dead anyway) | the owner downloads |
| Exporting an edit with BPM lock on | the whole song re-timed, up to 0.7 s drift | lock off, diff, time map |
| Re-cutting the whole video after a re-sung word | hours of rework | time map |
| Editing a line the owner locked | broke a section they loved | `LOCKED` marks in `DECISIONS.md` |
| Reusing the last video's device in a sequel | "close to a copy" | a new device |
| A concept that needs explaining | "too abstract" | concrete, current references in the first lines |
| Changing words, tags and style in one round | can't tell what fixed or broke the take | one variable per round |
| Trusting the lyric sheet over the take | wrong line counts downstream | trust the audio (transcript check) |

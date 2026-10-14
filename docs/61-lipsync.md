# 61 · Lip sync: measure it, cut it, cover it

Lip sync in these videos is not done by a lip-sync model. It comes from the video model copying the song, and it is
**measured**, not eyeballed. This file explains the discovery, the clean vocal window, the sync check, per-take lag, the
cut on the last eighth, covers, coverage, and what to do when sync fails (cut away).

Read first: `60-clips.md` §3 (windows) and `60-clips.md` §4.0 (the short sung prompt). Next: `70-motion-design.md` (how
the edit hides what doesn't sync), `80-review-qa.md`.

**Commands** (the global flags `--json` and `--project NAME` go before the command, e.g. `slop --json clip sync W02`):

| Step | Command |
|---|---|
| Draft a sung clip: cuts its clean vocal window (§2) and drafts the short sung prompt (§1.1) | `slop clip new s005 --kind sung` |
| Cut a window by hand (only for a window you place yourself) | `slop audio window W02 --t0 8.56 --t1 12.56 --mode clean --words "Why would I deceive you?"`, then `slop clip set W02 --audio audio/windows/W02.wav --audio-mode clean` |
| The sync check on the latest take (§3); writes `takes[].sync` and `clips/W02/take-N-sync.png` | `slop clip sync W02` (or `--take 2`) |
| The review video: the take with our audio laid on, marked at the divergence | `slop sync review clips/W02/take-1.mp4 audio/windows/W02.wav --song-t0 8.56 --out clips/W02/take-1-review.mp4` |
| Coverage per chain and for the video (§7) | `slop clip coverage` (or `slop clip coverage W02`) |
| Propose covers for the gaps; `--make` writes them (§6) | `slop clip cover W02`, then `slop clip cover W02 --make` |
| The edit in song time (§10) | `slop edit edl` |

---

## 1. The discovery: lip sync is an audio check

On *Escape Velocity* (EV), singing prompts without a proper audio reference didn't sync; lip-sync models (Sync 3 on
Higgsfield, LatentSync locally) were "still not exact, kinda desyncs at the same time". Then anabology noticed
(verbatim): "its perfectly synced while in seedance, but the audio changes when it desyncs. if you check the spectrogram
for audio against reference audio you can see the clear divergence point. you could just create a cut and make another
clip to cover desyncs."

Verified on EV's takes:

1. In reference mode (`@Image1 sings @Audio1 …`, the plate as a reference image, no first frame), Seedance 2.5 **copies
   the reference audio into its own soundtrack**, almost sample for sample *while it copies*: inside a copied stretch
   the windowed 100 ms waveform measure (**wave**, §3) scores 0.8–0.97 at 0 ms lag. Measured over the whole take, the
   **global NCC** is much lower (usually 0.1–0.3, because the copy stops somewhere), and that is normal.
2. **The mouth follows that soundtrack.**
3. So while the clip's soundtrack *is* our vocal, the lips match the song. Where the soundtrack stops being ours, the lips
   stop matching.
4. Therefore: compare the clip's own audio with the vocal it was given, find where they part, **cut there**, and **cover**
   the rest with a new clip that starts from that frame.

Motion clips conditioned on the full mix are **not** copied (global NCC ≈ 0.05–0.08: the model makes its own sound), so
they play at lag 0 and need no sync check.

**A first frame breaks the method on OpenRouter.** When a request carries `frame_images`, OpenRouter ignores the audio
reference: the take makes its own soundtrack (NCC ≈ 0.015) and nothing can sync (`60-clips.md` §2.2). Sung clips and
covers are always sent in reference mode.

### 1.1 Short prompts copy; long screenplays re-sing (measured)

The lips follow the copy, so anything that makes the model copy more often is worth more than any cover. The biggest
lever measured so far is the **prompt length**. On a live Studio-tier run (2026-10-02, Seedance 2.5, clean vocal windows,
reference mode) every sung clip was first written as a long timestamped screenplay; all seven were then retaken on the
same windows with the short sung form (OpenRouter Seedance 2.5, 720p). Share of each window's sung seconds in sync:

| Window | Long timestamped screenplay (best take) | Short sung form |
|---|---|---|
| `c01` | **0 %** (2 OpenRouter takes + 1 Higgsfield draft) | **78 %** (2.24 of 2.87 s) |
| `c02` | 28 % | **100 %** |
| `c03` | 57 % | **71 %** |
| `c04` | 13 % | **29 %** |
| `c05` | 58 % | **100 %** |
| `c06` | 26 % | 26 % (a microphone at her mouth on the plate) |
| `c07` | 0 % | 0 % (covered on Higgsfield instead) |
| SP `W02` (Higgsfield, earlier) | 28 % (take 2) | **100 %** (take 1, 86 words, no timestamps) |

Short was better on 5 of 7 windows and never worse; the mean per take went from 26 % to 58 %. The chorus as a whole went
from **44 %** of its 14.76 sung seconds in sync (v1, all long) to **62 %** (v2, three short retakes) to **71 %** (v3, all
short + two Higgsfield covers). The bot's own diagnosis of the long takes: "nearly every take re-sang the audio instead of copying it". EV's
short sung template copied on 41 % of takes (§7). One probe went the other way: a window of the phase-2 test (not SP's
`W02`) held no more short than long on OpenRouter (two takes each, none above 41 %), and it then copied on Higgsfield's
first draft. So the rule is a strong tendency, not a guarantee: measure every take.

**The reconciliation: screenplay for acting and motion, short for copy.** The screenplay grammar fixed SP's story
(`60-clips.md` §1) and stays the default for motion clips and the board. A sung window's one job is to copy `@Audio1`, so
its prompt is the short form (`60-clips.md` §4.0):

- the head, quoting every word in the window;
- at most one line of framing and light (the camera at its end);
- at most 2 timed beats, often none;
- `One continuous shot, no cuts, no head turns.` · `Only she sings.` · `No text, letters or logos.`;
- about 90 words or fewer besides the quoted lyric (`slop clip lock` and `slop clip submit --dry-run` warn past ~90
  words or 2 timed beats; lock still locks);
- on a plate with her mouth fully visible: no held or stand microphone, hand, hair or prop at her lips (`c06`; a canon
  headset microphone stays at her cheek, clear of her lips).

A sung shot that must act (an entrance, a whisper with a reaction) can still take the screenplay
(`slop clip new s005 --kind sung --style screenplay`), measured like any take, with the cut-away ready (§8).

**When a window does not copy, try the short form first** (§8): rewrite a long prompt short and retake on the same
provider before re-routing.

---

## 2. The clean vocal window (`@Audio1` for sung clips)

Give the model **one voice to copy**: only the words the singer sings on camera in this window, everything else muted.
This also stops her from lip-syncing crowd shouts or other voices. The recipe (SP's `clean_window`, parameters exact):

1. Cut the **vocal stem** (`audio/stems/vocals.wav`) at `[song_t0, song_t0 + duration]`, mono, 44.1 kHz.
2. Words = the aligned words that **start** in `[song_t0 − 0.02, song_t0 + duration − 0.08)` — for a window with other
   voices, only *her* words (the clip's quoted words). The tail of a word that began before the window is muted, "so the
   model never hears a fragment it was not told about".
3. Merge the words into phrases across gaps ≤ **0.35 s** (held vowels and breaths inside a line stay).
4. Keep each phrase from **0.05 s** before its first word to its last word's end, plus a release tail that follows the
   stem's own energy (10 ms RMS) until it falls **24 dB** below the phrase peak, at most **0.40 s**, and never past the
   next phrase's start − 0.05 s.
5. **15 ms raised-cosine ramps** on every gate edge; silence everywhere else.
6. Normalise the kept part to **−16 dBFS RMS**, then limit peaks to **−1 dBFS**.
7. Write `audio/windows/<clip>.wav` (mono 44.1 kHz; OpenRouter gets the WAV by HTTPS URL) and `.mp3` at 192 kbps
   (Higgsfield).

EV used the raw vocal-stem window (crowd included) and it worked on OpenRouter; the clean window is the default now.
Place the vocal where the choreography lets the face sing it (`60-clips.md` §3.1 rule 5).

---

## 3. The sync check (`slop clip sync`)

The check compares the take's soundtrack with the exact audio file that was sent as `@Audio1`.

**Algorithm (EV's `avsync`, constants exact):**

1. Decode both to **16 kHz mono**; 10 ms frames (hop 160), 64 ms FFT windows (1024), **80 mel bands 50–7,600 Hz**.
2. **Global lag:** FFT cross-correlation, searched within **±1.0 s**. The peak's normalised correlation is the take's
   **NCC**. **`mode = "copy"` if NCC > 0.2**, else "none" (the model re-sang it: "resynth").
3. Place the reference on the clip's timeline at that lag. Per 10 ms frame:
   - **wave** = normalised cross-correlation of the waveforms over 100 ms (a verbatim copy scores 0.6–1.0);
   - **mel** = cosine similarity of mean-removed log-mel frames (70 dB floor), smoothed over 11 frames — it holds on
     fricatives, whose noise never correlates sample-wise;
   - **active** = either track's RMS above 10 % of its 95th percentile.
4. **Threshold per take, against a null:** the same mel similarity with the reference shifted by non-beat offsets
   (±37, ±61, ±89, ±131 frames — chosen to avoid eighth-note multiples). `null90` = its 90th percentile;
   `matched_med` = median mel where wave > 0.6 (if > 10 such frames, else the 75th percentile of active mel);
   **`thr = null90 + 0.4 × (matched_med − null90)`**.
5. **match** = active **and** (wave ≥ 0.4 **or** mel ≥ thr).
6. **Divergence** = the first 300 ms stretch (≥ 60 % active, < 30 % matched, starting on an unmatched frame) that never
   recovers with a 400 ms matched run. Short dips that recover are recorded as **dips**, not cuts. If there is no such
   stretch, voice ≥ 80 ms after the last match counts as divergence. `synced_until` = the last matched frame − 42 ms
   (one frame at 24 fps).
7. **In-sync spans:** matched voice, bridged across silences and across ≤ 0.25 s of unmatched voice; spans < 0.5 s are
   dropped.
8. Mapped to song time (§4), plus the **cut** (§5) and the words at the divergence (aligned words in
   `[divergence − 0.15, divergence + 0.3]`).

**What it writes** (into the take's `sync`, ARCHITECTURE §4.6): `lag_s`, `ncc`, `mode` ("copy" | "none"),
`synced` (in-sync spans in song time), `diverge_at`, `cut_at` (the last eighth before the divergence). It also renders a
**diagnostic image**, `clips/<clip>/take-N-sync.png` (our vocal's spectrogram with word labels; the clip's own
soundtrack; the match curves and threshold; the cross-similarity matrix, whose diagonal is "in sync"). `slop sync review`
renders a **review video** with our audio laid over the take, marked "IN SYNC" until the cut and "DIVERGED — CUT HERE"
after it. Look at both before trusting a number.

**Accept rule (coverage, not NCC):** a window is held when the in-sync spans of its chain (the take plus its covers)
cover the needed sung seconds, with gaps shorter than **0.6 s** tolerated (§7). That is what `slop clip coverage`
computes, and what the edit uses. Whatever is not covered gets a cover (§6) or is cut away (§8).

The global NCC is a **diagnostic only**. It is not part of the decision:

- NCC > 0.2 ("copy") says the take copied our audio somewhere. A low NCC does not mean "no sync": SP's `W05b` take 2
  had an NCC of **0.157** and still held **99 %** of its sung seconds. On EV the median NCC of sung takes was about
  0.16, with only one take above 0.6, while the per-frame measures still found long in-sync spans.
- For **motion clips** the NCC decides only the lag: use the measured lag when NCC > 0.2 (a real copy), else lag 0
  (§4).
- When a number and your eyes disagree, trust the review video and the diagnostic image (§12).

---

## 4. The lag is measured per take

Never assume a constant offset. Measured lags: EV OpenRouter takes clustered around 0 ± 60 ms with outliers to
±0.5–1.0 s; Higgsfield takes ranged **−0.40 s to +0.83 s** (the "+0.7 s pre-roll" seen on the first two windows was not a
constant).

The two formulas (song time is the one clock):

```
song time  = song_t0 + clip_time − lag_s
clip time  = song time − song_t0 + lag_s        (the EDL's "in" point)
```

Worked example (SP `W02`, take 1: `song_t0` 8.56, `lag_s` +0.7063): the first needed word at song 8.856 is at clip time
8.856 − 8.56 + 0.7063 = **1.002 s**; the take is usable until its cut at song 10.2458. (This is the take that held the
whole line. It came from the short 86-word prompt without timestamps, not from the long screenplay shown in
`60-clips.md` §11; that one held 28 %.)

- Motion clips use the measured lag only when the check found a real copy (NCC > 0.2); otherwise lag = 0.
- The lag search is limited to ±1.0 s: a take that starts later than that is reported as no copy.

---

## 5. Cut on the last eighth before the divergence

Eighth notes = the beat map's beats plus the midpoints between them (`analysis/beats.json`; the tempo varies, so never
compute eighths from a BPM). The cut is the **last eighth ≤ `synced_until`** in song time. The edit keeps the take up to
that eighth and switches there — to a cover (§6) or to other coverage (§8).

Cutting on an eighth makes the switch feel like part of the music; cutting at the exact divergence frame looks like a
glitch.

---

## 6. Covers: a new clip from the cut frame, in a word gap

When the needed sung seconds still have a gap after a take (§7), make a **cover**:

1. **Window start** = the word gap before the cut (`gap_start(cut)`, lead 0.25 s, `60-clips.md` §3.1).
2. **Duration** = `clamp(ceil(end − start + 0.3), 4, 8)` whole seconds, where `end` is the end of the needed span.
3. **Start image** = the parent take's frame **at the cut** (clip time = cut − `song_t0` + `lag_s`), sent unaltered as
   the **reference image** `@Image1`: OpenRouter `input_references`, Higgsfield `image_references` (or `start_image`).
   **Never as OpenRouter `frame_images`**: a first frame drops the cover's `@Audio1`, and the cover cannot sync (§1).
   `slop clip cover W02 --make` extracts the frame and sends it this way. If a provider declines that frame, the decline
   is final for it (`62-moderation.md`); try the other provider with the same frame, or give up sync on that span.
4. **Words** = exactly the words that start in the cover's window (her words only). **Audio** = the clean window of those
   words (§2).
5. **Prompt** = the parent's prompt with the head re-quoted to the new words and the timestamps re-written for the new
   window.
6. Record it: `covers: [<clip>-c1]` on the parent, `parent` and `why` on the cover
   (format: `"cover for <root>: it diverges from our audio at song <t>; this window starts in the word gap at <t0>"`).
7. **Limit:** at most **2 covers per root** (EV's default); on Higgsfield, where copies are rarer, plan **1**. After the
   limit, stop: the span is given up (§8).

`slop clip cover W02` proposes the covers for a chain's gaps (window, words, start frame) without writing anything;
`--make` writes them as new clips (`--lock` locks them too), and they then go through submit, poll and sync like any clip.
When the limit is reached, the command records the spans to cut away.

EV: 28 covers (plus 2 LatentSync patches) across 47 clips; several held 3–6 s (`SD15-c1` 5.7 s, `SD16-c1` 6.4 s).
SP: `W05b-c1` with its parent held 96 % of the window's sung seconds.

---

## 7. Coverage: how much is "enough"

The bar is **"most lips"**, not every lip (anabology: "like grimes vids … shedoesnt sync lips on everything, just
most"). Gaps shorter than **0.6 s** are tolerated.

How coverage is computed for a chain (root + covers), over the root's `needed` span:

1. Sung stretches = every aligned word's span ± 30 ms, clipped to `needed`, merged when closer than 0.12 s.
2. In-sync spans = each element's latest take's `synced` spans (start extended 60 ms).
3. Walk the sung stretches; gaps not covered by any span, **≥ 0.6 s**, merged when closer than 0.3 s, are the gaps.
4. Coverage = covered sung seconds / total sung seconds.

**Targets and expectations:**

| | Copy rate (NCC > 0.2) | Full-line holds (≥ 90 %) | Result |
|---|---|---|---|
| EV, OpenRouter, raw vocal windows | **41 %** of sung takes (22/54) | — | with covers: **≈ 86 % of sung seconds verified** |
| SP, Higgsfield, clean windows | **≈ 21 %** (11/53) | ≈ 9 % (5/53) | 16 windows held by the check (2 in part); 7 more played by eye |
| SP, OpenRouter | **0 of 8** sung takes | 1 cover chain ≥ 0.9 (`W05b-c1`, 0.91) | most photoreal face references were declined before a take existed |
| Studio run, OpenRouter (+ Higgsfield drafts), clean windows | — | — | long screenplay prompts: **44 %** of sung seconds in sync; three short retakes: **≈ 62 %** (§1.1) |

How to read the table:

- **The provider difference is not established.** The 41 % is EV on OpenRouter; the 21 % is SP on Higgsfield. SP's
  own OpenRouter sung takes copied 0 of 8. The projects, prompts, windows and faces all differed, so do not route a
  sung window to OpenRouter expecting 41 %. Route by face (`60-clips.md` §6.5) and measure every take.
- **The SP Higgsfield row mixes two sources.** The "16 windows held" come from SP's production records, which were
  never re-measured or QA'd. The 21 % and 9 % come from re-measuring every Higgsfield take with the same check. Trust
  the measured figures.

Targets:

- Target **≥ 80 % of sung seconds** verified across the video, and every sung line has at least its key words on a
  synced mouth *or* covered by other coverage (no out-of-sync mouth on screen).
- Budget covers at **≈ 60 % of the sung seconds** on top of the windows (`60-clips.md` §8).
- Report coverage per window (planned / synced / covered / given up) after each round; show the owner.

---

## 8. When sync fails: cut away (no lip-sync-model fallback by default)

**Before cutting away, in this order:**

1. **Try the short form first.** If the window's takes came from a long or timestamped prompt, rewrite it in the short
   sung form (§1.1) and retake on the **same** provider: the prompt was the measured cause (`c01` went from 0 % to 78 %
   this way, after a Higgsfield draft of the long prompt had failed too). `slop clip sync` prints this step as its
   `first:` line when a take held under half its sung seconds and the clip's prompt is past the short form's limits.
2. **Then the routing rule:** after **2 OpenRouter non-copies** of the window in the short form, re-route it to a
   Higgsfield 480p draft (finalize it if kept, `60-clips.md` §7); never a third OpenRouter try. A window that failed 4
   times on OpenRouter (two of them short) copied on Higgsfield's first draft in the phase-2 test (74 % in sync).
3. **Then cut away**, as below. Covers (§6) follow the same order: they are sung clips, drafted in the short form.

**Default: never hold an out-of-sync mouth on screen.** Where a span stays unsynced after its covers, the edit cuts to
other coverage for that span:

- the shot's **motion clip** (the EDL fills holes in a sung shot with its motion clip first);
- stills in rhythm, depth moves on the plate, crops to eyes, hair or hands, inserts, motion-design shots
  (SP's chapter rule: "never hold her singing mouth in close-up on the words");
- a wider framing where the mouth is too small to read, or a profile/back view.

The words stay on screen as lyrics at their aligned times either way (`70-motion-design.md`).

**Why no lip-sync model:** EV tested Sync 3 and LatentSync as fixes: "still not exact"; the failure was the input, not
the model. SP banned them (anabology: "lip sync fallbacks don't work well").

**Opt-in only:** if an owner explicitly asks for a lip-sync patch on one span, Higgsfield's `sync_so` (Sync Lipsync 3,
inputs `input_video` + `input_audio`, ≈ 3.6 credits per second of audio) can be used with `sync_mode: "cut_off"` (the
default "bounce" ping-pongs the video). Label it as a patch in the clip file, run the sync check on the result, and show
the owner before it goes in the edit.

---

## 9. Higgsfield is different (read before routing sung windows there)

- On SP, Higgsfield's sung takes copied the conditioning audio in **≈ 21 %** of cases (11 of 53). That is lower than
  EV's 41 % on OpenRouter, but SP's own OpenRouter sung takes copied 0 of 8, so the comparison is confounded (§7). The
  clean vocal window did **not** raise the rate at scale (SP's 17-take burn round: 6 copies, 1 full hold).
- Its lag varies per take and is often positive: keep the last needed word **≥ 0.8 s** before the window end.
- **All five full holds on Higgsfield** (≥ 90 % of the needed sung seconds), as they were sent:

  | Take | Prompt | Framing | NCC | Held |
  |---|---|---|---|---|
  | `W02` take 1 | short (86 words), no timestamps | frontal close-up, alone, into the lens | 0.22 | 100 % |
  | `W07` take 2 | prose, "her lips moving exactly in time with @Audio1", no standard head; vocal placed after her entrance | a whisper at his ear, in profile, second person in frame | 0.49 | 90 % |
  | `W15` (burn round) | planner prompt, 75–129 words, no timestamps | extreme close-up, a whisper at his ear, second person in frame | 0.56 | 99 % |
  | `W05b` take 2 | long screenplay with 0.01 s timestamps | frontal close-up, alone, into the lens | 0.16 | 99 % |
  | `W09` take 2 | long screenplay with 0.01 s timestamps | close-up against black, alone | 0.60 | 99 % |

- **Weak observations, not rules** (5 holds out of 53, and the model is random): three of the five holds were solo
  close-ups singing toward the lens; two were whispers at the ear with a second person in frame. Short prompts and long
  screenplays both held, and both failed: `W02` held with the short prompt (100 %) and not with the long one (28 %),
  while `W05b` and `W09` held with long ones. The first of two open hypotheses, that very long second-by-second prompts
  compete with the audio copy, has since been measured on more windows (§1.1): long prompts can hold, but short ones
  copy far more often, so sung windows now take the short form. Still open: prompt timestamps that assume the audio at
  frame 0 disagree with a take that lands late (one more reason to keep sung beats to 2 or fewer).
- If a project depends on Higgsfield sync, run a small **480p draft matrix** first, every variant in the short form
  (§1.1): the same window with the standard head; a head that names "the reference audio track … unchanged"; the clean
  window; the image as a Higgsfield `start_image` instead of `image_references` (on Higgsfield both keep the audio; never
  use OpenRouter `frame_images`); then replicate the winner. Measure every draft with `slop clip sync`. Stop early when
  one variant holds on two windows.
- Whispers at the ear and two-person scenes **can** hold (`W07` take 2, `W15`), but many did not. Measure them like any
  window and have the cut-away ready: profile, mouth hidden, cut on the words. That is what SP shipped for the whisper
  windows that did not hold.

---

## 10. In the edit

`slop edit edl` resolves sung shots **moment by moment** in song time: at each time T it uses the chain element (take or
cover) whose in-sync span contains T, with `in = T − song_t0 + lag_s`. A take and its covers interleave, each switch
sitting on the eighth before a divergence. Holes are filled from the shot's motion clip, then the plate. Motion clips play
linearly (lag 0 unless measured), holding the last frame if the shot is longer. The film renders end to end at every
stage, with plates standing in for missing clips.

After a re-take, **re-frame shots whose engine code was tuned to the old take** (EV: a 1.8× crop cut her head off once the
new take had her head to boots).

---

## 11. Show the owner

- Before committing a project to a method: one **5 s proof** with our audio laid on (the review video).
- After each round: the coverage table (§7), the diagnostic images of the key lines, and the list of spans given up and
  what covers them.

---

## 12. Failure catalogue (lip sync)

| Symptom | Cause | Fix |
|---|---|---|
| NCC < 0.2, no in-sync spans ("re-sang the line", "sang its own melody") | the model did not copy `@Audio1` | keep nothing on the mouth; one cover or cut away |
| Most takes of a project re-sing instead of copying | long timestamped screenplay prompts on sung windows (§1.1) | the short sung form, retaken on the same provider first (`c01`: 0 % → 78 %); then 2 OpenRouter non-copies → Higgsfield → cut away (§8) |
| One window barely syncs with any prompt (`c06`: 26 %) | a microphone or hand at her mouth on the plate | a plate with her mouth fully visible |
| Lips right but late/early by a constant amount in the edit | a fixed offset was assumed | use the take's measured `lag_s` |
| Divergence inside a word near the window end | quoted words ≠ window words | quote all words starting in the window |
| Last words missing (Higgsfield) | positive lag + 4.04 s take | last word ≥ 0.8 s before the end; or +1 s |
| She lip-syncs a crowd shout | raw stem window with other voices | clean window of her words only |
| Words land while she is still moving into place | vocal placed too early | move the vocal later; blocking first |
| Cover declined by the face filter | raw frame of a face close-up | decline is final; other provider with the same frame, or give up the span |
| No audio stream in the take | `generate_audio: false` on a sung clip | sung clips keep `generate_audio` on |
| A take's soundtrack is the song but the mouth is off | rare; check the review video | trust the eyes over the number: mark the span unsynced |
| Sync figure looks good but the take is wrong (off-model, wrong action) | sync ≠ quality | QA the frames too (`60-clips.md` §10) |
| Many covers, still gaps | provider/framing unsuited | stop covering; cut away; consider a frontal CU window on the other provider |

For lead pronouns and optional turns, see [Lead wording and optional turns](60-clips.md#lead-wording-and-optional-turns).

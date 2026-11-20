# 99 · Failures: symptom → cause → fix (the consolidated catalogue)

Every row cost real time or money on a reference production. It merges EV's 28-row failure table, SP's 32 failure modes,
the pipeline playbook's failure log, the agent-swarm management log, and the bugs and gotchas found while researching this
toolkit. When something goes wrong, search this file for the symptom first.

Source tags: **[EV]** *Escape Velocity* · **[SP]** *Clodyssey (Superpersuasion)* · **[3rd]** an unreleased third video
between them · **[ops]** the owner's agent-swarm runs · **[tk]** found while building this toolkit (code reading, tests).
"See" points to the doc that holds the full rule.

---

## A. Brief, concept, taste

| # | Failure (what you see) | Cause | Fix / rule now | See |
|---|---|---|---|---|
| A1 | The first creative reply is blocked by a content filter [SP] | one response trying to research, write and decide everything at once | research with agents first; write lyrics in a separate turn ("so no single response is doing everything at once") | 10-song |
| A2 | The user stops research agents as useless [SP] | researching tool choices the user had already made, at storyboard stage | don't research decisions the user already made; research at the stage that needs it | 95-delegation §7 |
| A3 | v1 rejected for its look ("way too.. gray"; "color grading looked insane"; "dont love the dot grid") [EV][3rd][SP] | the look world was assumed, not asked | ask native / clean-grade / print up front; record it in `project.json` | 70-motion-design §1, §8 |
| A4 | Plates "feel like a stock photo" [3rd] | generic subjects: crowds, elderly or patient portraits, hands with medical props, clinic close-ups | change the idea entirely (not a re-roll) or make the shot pure motion design | 40-storyboard |
| A5 | A sequel's song feels like a copy [SP] | reusing the last song's device (a countdown) | a sequel never reuses the previous video's device or display faces | 10-song |
| A6 | Viewers read the lead as a teenager [SP] | schoolgirl-coded wardrobe and age words | canon says 28, "in her late twenties", with an adult angular face, and never "young"; every look adult and editorial; no pleated mini, no puff sleeves | 50-plates-midjourney |
| A7 | A user's taboo word shows up in a label, code or a file name [tk] | taboos lived only in the brief | taboo words in `project.json` `"banned"`; pasted into every agent prompt; `slop board audit` checks the board; grep code and file names before release | 80-review-qa §2 |
| A8 | Pace "off vibe with the song" [3rd] | busiest picture over the quietest music (picture motion 6.4 vs 2.0) | measure picture motion vs stem energy per section; density budget per song | 70-motion-design §4 |

## B. Song (Suno)

| # | Failure | Cause | Fix / rule now | See |
|---|---|---|---|---|
| B1 | The song comes out twice as long as planned (2:19 → 5:06) [EV] | Suno gives each spoken verse line its own two-bar slot | plan 2 bars per spoken line; write 10–13-syllable lines with stressed words on the beat; rhyme couplets on the beat-4 word | 10-song |
| B2 | Verses got choppy after a "groove" optimisation [SP] | a metric that rewards short clauses on the pulse | a flow model with a complexity setting, calibrated until it ranks sections in the user's order; never optimise past their ear | 10-song |
| B3 | Names mispronounced ("d-AIR-eeoo") [SP] | Suno's reading | respell in the Suno field only ("Dahrio"); the on-screen lyric keeps the real spelling | 10-song |
| B4 | Numbers/acronyms sung wrong [EV] | written as digits | spell as sung ("A G I", "eighteen") in `lyrics.txt`; the display layer shows "AGI" | 10-song, 70 §6.3 |
| B5 | Lyric rushes or truncates silently [EV] | lyrics field over ~3,000 characters | aim 1,800–2,400 characters for ~2:20; one breath per line | 10-song |
| B6 | Can't fetch the chosen take [EV][SP] | the download is a native browser download; the CDN needs signed URLs | the user downloads it (their download is also the licensing step) and gives the file | 10-song |
| B7 | Automation stuck on "Verify you are human" [SP] | a Cloudflare check in an iframe on the first Create | Grok stops at any captcha or "Verify you are human" and hands its browser to the owner for that one click; it never solves one | 10-song |
| B8 | Browser tab gone mid-task [SP] | Suno tabs close after 30 idle minutes | Grok makes songs through Suno's own connector (no tab); in the browser fallback it reopens the page and checks the library before creating again | 10-song |
| B9 | "A voice already exists for this song" [SP] | Suno allows one Voice per source song | make one combined (spoken + sung) Voice | 10-song |
| B10 | The new take changed the song's shape (no instrumental where there was one) [SP] | takes differ in structure, not just timing | re-time the board from word anchors, then restructure by hand where the shape changed | 40-storyboard |
| B11 | A patched export drifted the whole song by up to 0.7 s [SP] | Suno editor export with **BPM lock on** | export with the lock **off**; spectrogram-diff old vs new; time-map instead of re-cutting | 90-master-publish §3.1 |

## C. Analysis

| # | Failure | Cause | Fix / rule now | See |
|---|---|---|---|---|
| C1 | Cuts drift off the beat later in the song [EV] | a fixed BPM on an accelerating take (131.5 → 133.9) | variable-tempo beat map; never a BPM | 20-analysis, 70 §3 |
| C2 | One chapter's lyric check failed: a word 2.6 s early [EV] | a delay throw aligned as the word | ear-check words with > 1 s gaps inside a line or low confidence; fix `words.json` | 20-analysis |
| C3 | Bars start on beat 2 [SP] | the downbeat vote picked a backbeat phase (claps on 2 and 4) | `audio.downbeat_phase` override in `project.json`; check by ear | 20-analysis |
| C4 | The loudest moment gets no camera impact [SP] | the energy-step detector missed a bar that grew out of an already loud chorus | `"audio": {"hits": {"add": [[t, strength]], "drop": [t]}}` in `project.json` | 70 §9 |
| C5 | Snare/hat lists full of kick clicks [SP] | a broadband kick | drop onsets within 45 ms of a kick from snare and hat | 20-analysis |
| C6 | Sung lines and shouts missing from the alignment [SP] | wav2vec2 weak on singing; Whisper didn't hear crowd shouts | merge: w2v where confident, Whisper on sung lines; place missing shouts at the matching earlier chorus position; interpolate single dropped words; mark each word's `src` | 20-analysis |

## D. Lead identity and plates (Midjourney / image API)

| # | Failure | Cause | Fix / rule now | See |
|---|---|---|---|---|
| D1 | The lead's ethnicity drifts; 12 plates flagged [EV] | the prompt did not pin ethnicity, age, skin | pinned canon text in every prompt with her (`project.json` `lead.canon`); test 4 plates and get the face approved before any batch | 50-plates-midjourney |
| D2 | Identity-pass edits drift from the look; refuse seated poses [EV] | an image model "replacing only the woman" | identity by prompt text only | 50 |
| D3 | Floating giant heads / a close-up-sized head on a far figure [EV] | face-sheet image references (whole sheet = layout; single face = over-conditioning) | no face image refs for identity; only where the user explicitly asks (e.g. a mask), at tuned weights | 50 |
| D4 | "Version 8.2 doesn't support --oref" [EV] | the parameter doesn't exist on that version | don't use it | 50 |
| D5 | Broken grammar in prompts ("…freckles,'s hand", "boots's black boots") [EV] | naive substitution of the canon into body-part shots | a separate possessive form; drop the canon (and invisible garments) for body-part shots | 50, examples/mj-prompts |
| D6 | Full-length prompts return close-ups [SP] | the long face canon pulls the frame in, whatever the framing words say | camera first ("full-body fashion editorial photograph taken from far away with a long lens: …") + the short FAR identity (skin, hair, the one accent); repeating louder doesn't help, removing what competes does | 50 |
| D7 | "a flank covered in eyes" → a bare flank [SP] | the feature was an adjective, not the subject | make it the subject ("the hide studded with dozens of large glossy human eyes …") | 50 |
| D8 | The crew are copies of the male lead [SP] | one description per cast; no distinctness | list each extra (age, build, hair) + an explicit negative ("none of them bald, none has a thick dark beard like the man in the centre") | 50 |
| D9 | A sheer gown read as plastic wrap, reclining, nude-reading [SP] | "sheer … bare shoulders, bare feet" | a structured, high-neck, long-sleeve canon; "composed and deadpan" | 50, 62-moderation |
| D10 | Crowds of women came back as hooded shrouds [SP] | "hundreds of women in white gowns" from behind | "bare-headed women with glossy black bobs" | 50 |
| D11 | A stranger appears in an over-the-shoulder shot [SP] | "a woman's bare shoulder" without the canon | OTS shots still carry the canon | 50 |
| D12 | The robotaxi came back as an old sedan [EV] | the object's form factor wasn't named | name it ("a small white compact electric SUV robotaxi with a tall spinning lidar dome") | 50 |
| D13 | The same image on ~6 shots [EV] | stand-in aliases left in the board | one plate per shot; re-assign repeats to the 3 non-picked candidates of each job (the free variety pool) | 40, 80 §2 |
| D14 | "Dithered/xerox" prompt gave a grainy photo [EV] | the generator doesn't make real 1-bit | texture in code (print look), never in the prompt | 70 §8 |
| D15 | Plates in the wrong style profile [EV] | personalization applied the account's old default profiles | set the right default profiles on Midjourney's Personalize page; Grok presses P only when `mj.personalize` is on | 50 |
| D16 | A hand-painted fix in code (chrome eyes) [SP] | fixing the frame instead of the source | bake it into the prompt or use the image-edit model; never paint pixels | 51-plates-api |
| D17 | The edit model introduced a new error (a six-pointed star instead of eight) [SP] | edit models invent details | re-check canon after every edit; name the exact form ("exactly eight points") | 51, examples/image-edit |
| D18 | Edited plates rendered with their old depth and mattes [SP] | media prep not re-run | re-run `slop edit export` after every plate edit (it re-makes the depth when the plate changed) | 70 §12 |
| D19 | ~20 browser calls lost to a UI workaround [SP] | a small automated tab hid the edit buttons | screenshot the layout first; cap UI-workaround time; go back to the generator's main path (re-prompt) | 50 |
| D20 | Downloaded images mismatched to prompts [EV][SP] | identifying jobs by position; the generator rewrites long prompts on submit | identify each job by its own prompt text; match rewritten prompts by hand | 50 |
| D21 | Lost picks [EV] | parallel runs racing on a state file | locked read-modify-write | — |
| D22 | Anime-model jobs flagged "WRONG PROFILE" [SP] | that model has no personal profile | record those ids by hand | 50 |
| D23 | "Two heads next to each other" ("bodyslop") [SP] | compositing a ghost and a person in one prompt | describe the ghost as made of the scene's light; or compose from two assets; regenerate in several ways | 50 |

## E. Video clips and lip sync

| # | Failure | Cause | Fix / rule now | See |
|---|---|---|---|---|
| E1 | Lifeless takes; ~830 credits burned [SP] | agent-written prompts: poses, not drama; no timestamps; nobody read them | the lead writes every prompt in one context: story beat, blocking at 0.0 s, timestamped action **and** reaction on real word/kick times, the environment answering the music, the camera on hits, mouth rules; the user reads the book before any spend (sung windows: the short sung form instead, E18) | 60-clips, examples/seedance-prompts |
| E2 | QA kept weak takes [SP] | QA checked takes against their (weak) prompts | QA against the story and the storyboard | 80 §4 |
| E3 | Context burned reviewing bad takes [SP] | the prompts were the fault | re-make them all with new prompts | 95 §8 |
| E4 | Two clips start on the same frame ("jarring") [EV] | the same plate as start image | the k-th clip on a plate uses its k-th other candidate, or the previous clip's last frame | 60-clips, 80 §2 |
| E5 | Lip-sync models "still not exact" [EV][SP] | the failure was the input, not the model | the audio check + covers; no lip-sync-model fallbacks; give up sync and cut away | 61-lipsync |
| E6 | A take diverges inside a word [EV] | the prompt quoted fewer words than the window held | quote exactly the aligned words in the window; start windows in a word gap | 61 |
| E7 | Lips a fraction late/early in the edit [EV][SP] | per-take lag up to ±1 s; Higgsfield pre-roll ≈ +0.7 s | always map clip time ↔ song time through the measured lag | 61 |
| E8 | The provider "re-sang" the line in its own timing (0 % verified) [SP] | it did not copy the conditioning audio | a clean vocal of only her words (crowd muted, gated, normalised); place the words where the choreography lets her arrive; a short sung prompt (E18) | 61 |
| E9 | A window cut a word ("…could. Your P") [SP] | the window ended mid-word | windows start and end in word gaps | 61 |
| E10 | "Submitted" with no job id; HTTP 500/502/520 [EV] | silent provider failures | validate ids; re-run resumes chains and resets broken takes | 60-clips |
| E11 | Motion clips "diverge" in the sync check [EV] | the mix is not copied (NCC ≈ 0.08, "resynth") | expected; motion clips play at lag 0; skip the sync check on silent motion takes | 61 |
| E12 | Grey proxy shapes in takes [SP] | a 3D previz video reference leaked into the output | "take only the camera move from it, and film the scene itself in rich cinematic detail", or drop the video reference | 60-clips |
| E13 | Drift on long sung clips [EV] | lip sync degrades over long clips | sung windows 4–8 s; never sing over 8 s | 60-clips |
| E14 | Head count changes, actions reverse, camera overload, garbled text [EV] | under-specified prompts | "exactly four …", name the end state, one dominant camera move, "No text, letters or logos" (type in code) | 60-clips |
| E15 | Wardrobe drift in a motion take (a halter instead of the gown) [SP] | the model's own variation | QA notes it; crop or retake | 80 §4 |
| E16 | "Upscaled" footage looks waxy and shimmers [SP] | learned upscalers (10–25 % more shimmer, smeared freckles) | keep Lanczos; generate hero shots at 1080p instead | 60-clips |
| E17 | Grey clips [EV] | mono pre-graded references (see H1) | colour inputs | 70 §8 |
| E18 | Sung takes re-sing the line instead of copying it: "nearly every take re-sang the audio" (Studio run `c01`: 0 % of its sung seconds in sync over 2 OpenRouter takes and a Higgsfield draft) [SP][tk] | long timestamped screenplay prompts on sung windows: the model performs the text instead of copying `@Audio1` | the short sung form: the head quoting every word, one framing/light line, at most 2 timed beats, "One continuous shot, no cuts, no head turns.", "Only she sings"; measured `c01` 0 % → 78 %, `c04` 13 % → 29 %, SP `W02` 28 % → 100 %; screenplay for acting and motion, short for copy; try it on the same provider before re-routing (then 2 OpenRouter non-copies of the short form → Higgsfield → cut away); `slop clip new --kind sung` drafts it, `slop clip lock` and `submit --dry-run` warn past ~90 words or 2 beats, and `slop clip sync` says "short form first" after a long prompt's take holds under half | 60-clips §4.0, 61 §1.1, §8 |
| E19 | One sung clip barely syncs whatever the prompt (Studio run `c06`: 26 % long and short) [tk] | a microphone at her mouth on the sung plate | sung plates show her mouth fully visible, with no held or stand microphone, hand, hair or prop at her lips (a canon headset microphone stays at her cheek, clear of them); re-roll the plate | 60-clips §4.0, 50-plates-midjourney |

## F. Moderation and providers

| # | Failure | Cause | Fix / rule now | See |
|---|---|---|---|---|
| F1 | Close-up references declined ("PrivacyInformation") [EV][SP] | the provider's face filter | free and final for that image; send the **same unaltered** image to another provider; otherwise the shot stays a 2.5D plate | 62-moderation |
| F2 | A retry ladder (stronger grade → posterised grade) got takes through, baked banding in, and was blocked by the harness [3rd] | altering a reference to pass a safety filter | **never alter an image to pass a filter**; a blocked action is a stop, not a puzzle; remove such automation | 62 |
| F3 | Jobs "failed" with no reason, credits back ~6 s later [SP] | the provider's silent input filter (phrases read as sexual or deepfake) | plain rewording keeps the beat (the table in `62-moderation.md`); try the 2nd candidate; pass the image as a reference instead of a first frame | 62 |
| F4 | Tight weeping close-ups failed as first frames on both providers [SP] | stricter filters on start frames | the same image as a reference image rendered | 62 |
| F5 | 7 of 10 in a batch refused with "preset recommended" [SP] | batch preset suggestion | resubmit with the preset explicitly declined | 62 |
| F6 | Status "nsfw" [SP] | the **output** was flagged (refunded) | treat as a decline for that wording; review the prompt | 62 |
| F7 | "output audio may be related to copyright restrictions" / "sensitive information" [EV][SP] | the provider's audio filter | retry once (sensitive: reworded prompt or re-cut window), then the other provider with the same image and window (`slop clip ingest CLIP --failed "<reason>"` on Higgsfield prints the step); turn the model's own audio off on motion clips | 62 |
| F8 | A text filter refused "tied, screaming" [SP] | trigger words | reword without changing the beat | 62 |
| F9 | A filter that passed faces "2 days ago" now declines them [SP] | provider behaviour changes | keep a second provider configured | 62 |
| F10 | The agent's context floods during uploads [SP] | MCP presigned-upload replies ~3.5k characters per file | upload by URL (host the file, import by URL) | 60-clips |
| F11 | Spending without knowing the price (prices change; a rate table can be stale) [SP][tk] | skipping the free cost preflight (it was a `get_cost` flag on `generate_video`, easy to miss; the connector moved it to its own tools and `generate_video` no longer takes the flag) | preflight every new configuration with `estimate_video_cost` (stills: `estimate_image_cost`; audio: `estimate_audio_cost`): the generate tool's own `params`, free, submits nothing; `generate_video_batch` rejects `get_cost`, so price one request per new configuration first, then batch | 60-clips §6.2, 62-moderation |

## G. Spend

| # | Failure | Cause | Fix / rule now | See |
|---|---|---|---|---|
| G1 | Every submit returns 403 while the account has credit [SP] | the API **key** has its own spend limit | check both; ask the user to raise the key limit above the project cap | 95 §8 |
| G2 | "Remaining budget" figures wrong [EV][SP] | local ledger ≠ billing; free declines counted against the cap | quote spend only from the provider endpoints (`slop spend`) | 80 §1 |
| G3 | ~830 credits spent in minutes on unread prompts [SP] | a credit-reset deadline drove the spending | never let a deadline drive spend on unread prompts | 95 §10 |
| G4 | A background workflow could still spend after a quality flag [SP] | not every spender was stopped | stop every workflow that can spend: search each running script for its generate calls | 95 §10 |
| G5 | Credits vanished at renewal [SP] | subscription credits don't roll over; top-ups expire after 90 days | plan spend inside the period | 60-clips |

## H. Colour and look

| # | Failure | Cause | Fix / rule now | See |
|---|---|---|---|---|
| H1 | 32 of 59 clips came back near-grey [EV] | mono pre-graded references; the video model keeps the reference's colour | keep generation inputs in colour; apply the look in post | 70 §8 |
| H2 | v1 "way too gray … loses the Midjourney magic" [EV] | a mono print pass + chapters desaturating the base by hand | colour halftone (print look) or native/clean; never desaturate the base | 70 §7–8 |
| H3 | "color grading looked insane"; blue graphics "clash" [3rd] | a graded look and a blue accent over blue footage | native colour; pick the accent against the footage's hue; semantic colour tokens | 70 §7 |
| H4 | "dont love the dot grid" [SP] | a halftone shown when the user wanted IMAX-clean | clean-grade look | 70 §8 |
| H5 | Flicker between frames of a graded clip [SP] | per-frame grading | one 3D LUT per clip computed from 16 sampled frames | 70 §8 |
| H6 | Native look still "blown out" in places [3rd] | chapters painting light washes on the overlay; exposure/lift overrides | no washes over footage in native/clean; the pass ignores colour keys | 70 §8 |
| H7 | A chapter's accent tuning does nothing [tk] | the original engine's pass ignored `accentKeep`, `accentTol`, `accentSat`; in native/clean looks every colour key is dropped | in the toolkit's print look they work (pixels near the accent hue keep their continuous colour; default `accentKeep: 0` changes nothing); in native/clean they still do nothing | 70 §8 |

## I. Motion design and the engine

| # | Failure | Cause | Fix / rule now | See |
|---|---|---|---|---|
| I1 | A crop cut her head off after a re-take [EV] | code tuned to the old take | re-frame every shot whose take changed; re-key tucks, tags, crops | 70 §15 |
| I2 | The previous frame's overlay "sticks" in dense frames [3rd] | GPU-backed 2D canvas under software GL | every canvas software-backed; history check in QA (~2 h of bisecting found it) | 70 §2, 80 §6 |
| I3 | Frames differ depending on what rendered before [3rd] | a WebGL canvas drawn into a 2D canvas switches it to GPU rasterisation | read 2.5D pixels back through the CPU | 80 §6 |
| I4 | Renders differ by ≤ 0.3/255 between workers [EV] | first-use caches | acceptable; keep caches history-free and keyed by media name | 70 §2 |
| I5 | ~0.5–1.1 s per frame on 2.5D shots [EV] | the 64-step parallax shader under software GL | depth slices (~30 ms) or multiplanes | 70 §11 |
| I6 | ~0.5 s per frame for a blur [EV] | full-resolution canvas `filter: blur` | blur by resampling (¼ or ½ size and back) | 70 §11 |
| I7 | Tags never finish typing on short shots [EV][SP] | default typing speed (1 char per 16th) | fast typing (≥ 16–40 cps); finish ≥ 6 frames before the cut | 70 §6.3 |
| I8 | Letters cut mid-word ("it's" read "i's"), blotchy ink on a gown [SP] | split ink over translucent or busy texture | one solid ink per block or word; split along the matte; or force the ink | 70 §13 |
| I9 | A lyric word half hidden on its first frame ("You dor't") [SP] | occlusion on the entering row | tuck an edge only; turn occlusion off for the entering row | 70 §12 |
| I10 | Five accent-coloured elements in a frame [SP] | the accent used for every highlight | accent on ≤ 2 elements (SP budget) | 70 §7 |
| I11 | A device's type bigger than the lyric [SP] | layout drift | the lyric is the biggest type unless the device *is* the line | 70 §6.3 |
| I12 | A snap reads early [SP] | keyed 70 ms before its kick | key moves on the hit times from `hits.json` | 70 §9 |
| I13 | Two on-screen numbers disagree ("x380" vs "135 RUNNING") [SP] | two devices driven separately | drive both from one value and easing | 80 §8 |
| I14 | Shake in a drumless intro [SP] | a move that answers no sound | moves answer audible sounds; stillness where the song breathes | 70 §9 |
| I15 | Match transitions land off target [tk] | a bug in the original `FX.T.match` | fixed in the toolkit engine (centre lerped, scale clamped, no edge shows); still check the middle frame of every match, and give both scenes a `look.focus` (no boxes = no match target) | 70 §10 |
| I16 | Negative or odd bar numbers on the beat ruler [EV] | a bug in the original ruler | fixed centrally (report shared bugs; never patch per chapter) | 70 §16.4 |
| I17 | Text alignment leaks into the next drawing [EV] | the split-flap board left `textAlign` set | reset context state at every scene and in scratch canvases | 70 §2 |
| I18 | The "mass" wall flickers off the beat on an accelerating song [tk] | the original used a fixed BPM | the beat map everywhere | 70 §3 |
| I19 | Another video's words appear in a new project ("~/escape-velocity", "LOOK 01 / 12") [tk] | hard-coded strings and song defaults in shared code | project strings come from `project.json`; the toolkit engine has none | engine/DEVICES.md |
| I20 | The same helpers written 8–10 times, slightly different [EV] | chapters forbidden to edit shared files, no shared library | a shared device library; chapters write only what is unique | 70 §16 |
| I21 | The default renderer drew only lyrics for every shot [SP] | storyboard graphics stored as prose | structured `shots.json` fields: `type[]`, `devices[]`, `treatment`, `transition_in` | 40-storyboard |
| I22 | Chapters full of hand-typed coordinate tables [SP] | per-take measurements written as code | measurements as data (tracks, keyed tables) emitted by tools, with how they were measured | 70 §16.3 |
| I23 | A lyric fixed in chapter code ("no-op once fixed") [EV] | patching times instead of the alignment | fix `words.json` and re-export | 80 §3 |
| I24 | A chapter replaced the default renderer and lost lyrics [SP] | the chapter must draw every token itself | lyric gate per chapter; `KIN.mark` on custom tokens | 80 §3 |
| I25 | Fonts that can't be shipped [tk] | Nimbus Sans (AGPL), Junicode 0.6 (GPL), Pilcrow Rounded (EULA), Alchimia (no licence) | OFL fonts only, with licence texts | 70 §6.1 |
| I26 | Depth model licence forbids commercial use [tk] | Depth-Anything-V2-Large is CC-BY-NC | Depth-Anything-V2-Small (Apache-2.0) only | 70 §12 |
| I27 | A singing mouth held where the take isn't synced [SP] | the edit fell back to a plate or a non-lip clip | crops, inserts, depth moves or other coverage on those words | 70 §15 |
| I28 | A chapter's scenes never appear; its shots show the default renderer [tk] | the chapter file is not listed in `engine/ch/_index.js` (the page loads only `common.js`, `scenes.js` and `ch/_index.js`) | the orchestrator lists every chapter file in `ch/_index.js` before launching the animators | 70 §16 |
| I29 | The engine page throws "LY is not defined" (or `TR`, `DEV`, `CV`) when a chapter loads [tk] | the project layer loads before the device library | use device helpers only inside draw functions; set entries with `ENGINE.transitions.set` | 70 §16 |
| I30 | CV brackets are missing, or tags float in a free corner instead of on her [tk] | `{box: …}` / `"lead"` anchors, but the toolkit detects no boxes | anchor with `uv` / `keys` / `rect`, or write the boxes by hand in `engine/common.js` | 70 §5.0 |
| I31 | Type that should tuck behind her is drawn uncut [tk] | no matte in a toolkit project; clips have no depth | occlusion by depth key (`mode: 'auto'`) on plate shots with depth; place blocks so they read uncut on clips | 70 §12 |

## J. Review and QA

| # | Failure | Cause | Fix / rule now | See |
|---|---|---|---|---|
| J1 | Runs "completed" with no review at all [SP] | a usage limit made reviewers return nothing; scripts read null as "no fixes" | a null or empty review is an explicit failure, in code; carry open fixes forward | 80 §8.4 |
| J2 | The original fix step skipped on `!rev` [EV][SP] | `(!rev …) ? 'no fixes'` | throw on a null review | 80 §8.4 |
| J3 | Judge totals empty, silently [ops] | the judges' board names didn't match the angle keys | validate judge output keys against the expected boards | 95 §7 |
| J4 | Reviewers scored 6–7.5 on a cut the user called "perfect" [SP] | a stricter bar than the owner's | ship on "no blocking fix left"; calibrate the reviewer on owner verdicts; ≤ 2 rounds | 80 §8.3 |
| J5 | A reviewer used all its time re-running checks and wrote nothing [ops] | not told what is authoritative | bound reviewers by output; "write the short version first" | 95 §8 |
| J6 | The safety scan flagged the intended prop (a satellite dish) [SP] | a generic "modern object" rule | whitelist intended anachronisms by name | 80 §9.2 |
| J7 | A scan launched with a placeholder instead of 96 paths [SP] | a long list passed inline in launch args | a list file; each agent reads its slice | 80 §9.1 |
| J8 | A strobe counted twice; 2.2/s read as 4.4/s [SP] | the flash check paired every transition | count opposing pairs | 80 §5 |
| J9 | The brief asked for a 12 fps render the tool couldn't do [tk] | the original renderer had no `--fps` option | `slop render frames --from A --to B --every 2 --out <scratch>` (every 2nd frame of the 24 fps cut = 12 fps) | 80 §8.1 |
| J10 | The on-screen lyric file was empty when production started [SP] | the lyric export was never run | write all lines first; no render until the gate is N/N | 80 §3 |
| J11 | Crew copies came back in a re-made take [SP] | re-makes are new generations | scan every re-make again | 80 §9 |
| J12 | Faces printing blank, type over faces, repeated devices in first drafts (scores 5–6.5) [EV] | animators without a reviewer of real renders | reviewer renders and looks; concrete fixes | 80 §8 |
| J13 | 12 blocks found in 96 "final" takes (nudity through a corset, modern objects, earmuffs …) [SP] | generated people; filters let outputs through | a safety and canon scan of every take before release | 80 §9 |

## K. Render and encode

| # | Failure | Cause | Fix / rule now | See |
|---|---|---|---|---|
| K1 | The master looks washed out ("v blown out") [3rd][EV] | untagged or BT.601-tagged H.264 | BT.709 conversion + tags in `slop render encode`; verify with ffprobe | 90 §2, 80 §7 |
| K2 | Nobody knew the encode finished [EV] | a detached `nohup` job | tracked background jobs with a status file | 90 §1 |
| K3 | Swap and the root disk filled [3rd] | six agents rendering at once; frames in `/tmp` | one rendering workflow at a time; scratch on the big disk; check free memory/disk first | 95 §3 |
| K4 | Disk full after a render [EV] | ~9.6 GB of frames per cut | delete frames after ffprobe verifies the outputs | 90 §1 |
| K5 | Commands ran against the wrong project [3rd] | an `export` inside a backgrounded shell chain didn't apply | name the project on every command; the toolkit has no silent default project | — |
| K6 | The host machine's drive hit 0 GB [ops] | a VM disk grew on the host | guard the host's free space; delete intermediates; compact | 95 §8 |

## L. Orchestration and delegation

| # | Failure | Cause | Fix / rule now | See |
|---|---|---|---|---|
| L1 | A merge restarted three times (~1.5 h) [EV] | a user interrupt kills every running workflow | short phases; run ids + args saved; resume by run id; split the audit out | 95 §9 |
| L2 | One serial chapter workflow would take ~12 h [EV] | serial agents | 3 parallel workflows (~4 h) | 95 §7 |
| L3 | The kit review waited 3+ h on media work [SP] | a parallel barrier | slow media work in its own workflow; review the kit as soon as it exists | 95 §7 |
| L4 | Reviews and agents returned nothing mid-run [SP] | the 5-hour usage window hit 100 % | preflight limits before fan-out; null = failure | 95 §1.4 |
| L5 | Workflow resume refused its script path [EV] | the script lived in the session's private store | keep scripts in the job/project folder | 95 §3 |
| L6 | An old run can't be resumed any more [tk] | workflow journals were deleted | copy each run record into `runs/` | 95 §3 |
| L7 | The run log says "running" for runs long dead [SP] | a hand-kept log | derive status from the run records | 95 §3 |
| L8 | The final result missing from a parsed run [tk] | print mode emits several `result` events | wait for process exit; keep the last | 95 §3 |
| L9 | Codex hangs or appends garbage [tk] | it reads stdin when stdin is not a terminal | always close stdin (`< /dev/null`) | 95 §3 |
| L10 | Codex resume rejects `-s` [tk] | not a resume flag | `-c sandbox_mode="…"` | 95 §3 |
| L11 | Prompts cut at `&` or `"` on Windows [tk] | an agent CLI's `.cmd` launcher | pass the prompt as a file; call the real binary, not the shim | 95 §3 |
| L12 | Every new agent session fails at start after an update [ops][tk] | an agent CLI auto-updated (and deleted the old binary) | pin versions; turn the CLI's auto-update off for long jobs; check the job error before assuming "no work" | 95 §8 |
| L13 | A local command is killed after 30 s [tk] | Grok Bot's foreground timeout | background jobs; `wait` ≤ 25 s | 95 §4 |
| L14 | Dozens of approval cards nobody can answer remotely [tk] | "Ask every time" needs one card per distinct command | one background `run` per job; few, fixed commands | 95 §4 |
| L15 | A launched agent uses the parent's session [tk] | inherited `CLAUDECODE` / `CLAUDE_CODE_*` env vars | strip them before launching | 95 §3 |
| L16 | Paths broken in job files on Windows [tk] | shells eat backslashes | forward slashes in JSON | 95 §4 |
| L17 | GPU/worker box at 100 % CPU, jobs 3–5× slower [SP] | two dozen waiters polling every 3 s | one shared listing every 45 s for all waiters | 95 §8 |
| L18 | Duplicate jobs after a restart [SP] | killing a waiter left its child; the re-run resubmitted | record job ids beside inputs; adopt queued jobs; kill orphans by id | 95 §8 |
| L19 | Clips without mattes [SP] | an "on every import" step skipped by another agent's env flag | a catch-up sweep with idempotent keys | 95 §8 |
| L20 | A ~20 h background queue; new takes behind superseded ones [SP] | auto-queued post-processing per import | queue only takes the edit uses, in priority order; cancel superseded jobs | 95 §8 |
| L21 | `pkill -f` kills its own shell (exit 144); a `while read` loop loses items [SP] | pattern matches itself; ffmpeg reads stdin | select PIDs with `ps \| grep "[x]yz"`; `< /dev/null` on commands inside loops | 95 §8 |
| L22 | Orphaned loops keep working after a cancel [ops] | cancelling a goal-mode job doesn't stop its shells | clear the goal, cancel, kill by tag | 95 §8 |
| L23 | A preflight agent probed its sandbox instead of replying [ops] | a diagnosis in the preflight's title | preflights carry no context | 95 §8 |
| L24 | Roles marked "drained" while nothing could start [ops] | instant failures read as "no work" | check the job's error first | 95 §8 |
| L25 | Workers duplicating the toolsmith's job [ops] | roles without a "You do NOT" list | exclusive roles + a requests channel | 95 §5 |
| L26 | A worker probed for 75 min and delivered nothing [ops] | unbounded first deliverable | first complete draft within ~10 commands; handoff mandatory | 95 §5 |
| L27 | A worker "passed" by hiding what it couldn't do [ops] | metric floors were exploitable | check the parts; re-judge earlier passes when rules tighten | 95 §8 |
| L28 | The repo's workflow templates lagged the latest video's scripts [tk] | the newest scripts lived only in the making-of | `templates/workflows/` in this toolkit is the source of truth | 95 §5 |
| L29 | Shared-file bugs fixed differently in parallel chapters [EV] | workers patching shared code | report shared bugs; the orchestrator fixes them once | 70 §16.4 |
| L30 | An optional engine is not available to the user [tk] | not every agent CLI is a public download | optional engines stay optional; Claude Code or Codex cover every role | 95 §1.3 |

## M. Publish

| # | Failure | Cause | Fix / rule now | See |
|---|---|---|---|---|
| M1 | Identifying details in a making-of (name, profile code, hosts, job ids, emails) [EV][SP] | raw production notes | the scrub rules + a grep pass + two fresh-eyes reads | 90 §8 |
| M2 | Thumbnails hid part of their titles [SP] | rushed composition | check every thumbnail at size; keep the player's corner clear | 90 §6 |
| M3 | A downloaded song file carries the generator's song id in its tags [EV] | file metadata | strip metadata on everything published | 90 §8 |
| M4 | Real-person likeness risk [SP] | portraits of real people | only inside labelled AI IMAGE post cards, their own dated words, never speaking | 90 §5 |
| M5 | A master posted without the AI disclosure [tk] | platform toggles missed | set each platform's AI/synthetic-content disclosure; name the tools in the post | 90 §5 |

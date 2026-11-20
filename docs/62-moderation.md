# 62 · Moderation, filters and the safety & canon scan

Every provider has filters, and they shape the work: which image a clip can start from, which words a prompt can use,
whether a clip may keep its own soundtrack. This file says what each filter does, what you may do about it, the wording
that got past Higgsfield's silent filter, and the scan every generated take gets before release.

Read with: `60-clips.md` (providers), `50-plates-midjourney.md` and `51-plates-api.md` (plates and edits),
`80-review-qa.md` (the release gates).

---

## 1. The rules (non-negotiable)

1. **Never alter an image to get it past a filter.** No re-grading, posterising, blurring, cropping the face out, adding
   grain, "print looks", lowering resolution or any automatic "retry ladder". A declined reference is **final for that
   image on that provider**. (On a previous project an automatic ladder of stronger grades got 18 takes through, baked
   banding into all of them, and was blocked by the agent harness as weakening a safety control. It was removed.)
2. **The other provider with the SAME unaltered image is allowed.** OpenRouter's face filter declined most face
   references on SP; Higgsfield took the same images.
3. **A different original image is allowed**: the plate's next Midjourney candidate, or a different plate. That is not
   altering an image; it is choosing another one.
4. **Rewording a prompt is allowed. Keep the beat, change the words.** Every SP rewording kept the story moment.
5. **Declines and refunded failures are not spend.** Record them as `status: "declined"` (or `"failed"`) so they never
   count against the budget.
6. **Never work around a safety control.** If a filter blocks something the owner wants, stop and ask the owner; offer the
   allowed options (another provider, another candidate, a reworded prompt, keep the shot on its 2.5D plate).
7. **Never generate a real person** unless the owner opted into the labelled-post policy (§6). Never put words in a real
   person's mouth.
8. **The bot never types credentials and never solves a captcha, Cloudflare check or 2FA** on any service; it hands the
   browser to the owner.

---

## 2. The filters, provider by provider

| Provider / filter | What you see | Cost | What to do |
|---|---|---|---|
| **OpenRouter Seedance — face filter** (BytePlus upstream) | submit error containing `InputImageSensitiveContentDetected.PrivacyInformation` | free in money, but each decline costs a bot turn | **Final for that image.** Identical retries decline again. Next: Higgsfield with the same image (§3). Photoreal faces were declined **18 of 27** on SP; illustrated or stylized faces passed (§2.2). |
| **OpenRouter Seedance — text filter** | `InputTextSensitiveContentDetected` | free | Reword the prompt (§4 table, same beat). |
| **OpenRouter Seedance — audio filter** | the job fails: "the output audio may be related to copyright restrictions", or (Seedance 2.5 with a vocal reference) "may contain sensitive information" | not billed | Motion clips: `generate_audio: false`. Sung windows: retry once with a re-cut window or a reworded prompt, then the other provider (§5). |
| **OpenRouter key limit** | HTTP 403 on every submit while the account still has credit | — | The key has its own spend limit: the owner raises it (`slop spend` shows both numbers). |
| **Higgsfield — silent input filter** | status `failed`, no reason; credits come back a few seconds to a few minutes later; an identical resubmit fails again | refunded | Reword (§4). If the image is the trigger: the plate's next candidate, or pass the image as `image_references` instead of `start_image`. |
| **Higgsfield — output flag** | status `nsfw` | refunded | The *output* was flagged: change the staging in the prompt, not the image. |
| **Higgsfield — preset recommendation** | a batch item refused: "Preset … was recommended instead of submitting a job" | free | Resubmit only that item with `declined_preset_id` set to that preset. Not a safety block. |
| **Higgsfield — unlimited choice** | `unlim_choice` returned, nothing submitted | free | Ask the owner (their free allowance or their credits), then resend the same params with `use_unlim` set to their answer. Never pick for them. |
| **Midjourney moderation** | a job is blocked with a notice, or is missing after a paste | — | Ask the owner for a screenshot of the notice; reword plainly; resend only that line. |
| **OpenAI image models** | `moderation_blocked` | not billed | Reword. |
| **Grok Bot `GenerateImage`** | content-safety block / `model_restricted` | — | Reword; it makes original visuals only (no real people or brands). |
| **Veo (Google)** | person-generation restrictions on image-to-video in some regions | — | Use another model for that clip. |

### 2.1 First frame vs reference image

The toolkit sends every plate as a **reference image** by default (`60-clips.md` §2.2). A tight face close-up can be
refused as a first frame but accepted as a reference image (SP: two weeping close-ups failed as first frames on both
providers, then rendered on Higgsfield as references, the same image unaltered). Then the prompt opens
`The scene from @Image1, …` (or the sung head) and the model recomposes the shot.

Never "fix" a decline by switching a sung clip, or a cover, to an **OpenRouter first frame** (`frame_images`).
OpenRouter then ignores the audio reference, and the take cannot sync. On Higgsfield, moving the image between
`start_image` and `image_references` is fine: both keep the audio.

### 2.2 Photoreal or stylized: route by the face

The face filter mostly hits **photoreal** faces: on SP, 18 of 27 photoreal face references were declined on OpenRouter.
An **illustrated or stylized** (anime/cel-style) lead passed in the 2026-10-01 probes. Claudia stays photographic all
the same (her canon: never illustrated; her avatar tier only in game or simulation worlds). So:

- photoreal sung shots go to **Higgsfield first** (`slop clip new … --provider higgsfield`), and OpenRouter is the
  second try with the same image;
- wide framings where the face is small, motion clips, and stylized characters the owner asked for go to OpenRouter
  first;
- a project that can only use OpenRouter (Quick tier without Higgsfield) plans her sung close-ups as wider framings or
  cutaways at the board (`51-plates-api.md` §3.1). Choosing a different original image is allowed; changing an image,
  or restyling her, to get past the filter is not (rule 1).

---

## 3. Face-filter declines: the procedure

When a clip's reference is declined on OpenRouter:

1. `slop clip submit` records it: the clip's `status: "declined"` with the provider, the date and the error code, and a
   ledger row with status `declined`. (For a Higgsfield refusal: `slop clip ingest W02 --declined "<the error>"`.)
2. **Do not touch the image.** Do not retry the same request (`slop clip lock` refuses a clip whose start image that
   provider already declined).
3. Route the clip to **Higgsfield** with the same image (same plate file, same audio, same prompt; the request writer
   applies Higgsfield's `@Image` numbering, `60-clips.md` §2.3): `slop clip set W02 --provider higgsfield`,
   `slop clip lock W02`, then `slop clip submit W02 --yes` writes the request file for the bot. Preflight the credits
   (`estimate_video_cost`).
4. If Higgsfield also blocks it: if the image went as a `start_image`, send it as `image_references` (§2.1; the audio
   reference stays). Then try the plate's **next Midjourney candidate** (`slop clip set W02 --start
   plates/cands/<plate>/<k>.jpg`); then reword the prompt (§4) if the words might be the trigger. Never move a sung clip
   to an OpenRouter first frame.
5. After 3–4 blocks, give up the clip: the shot stays on its **2.5D plate** with motion design (SP gave up one 3D move
   this way). Tell the owner in one line.

Covers (`61-lipsync.md` §6) start from a raw frame of a take, sent as a reference image. If that frame is declined, the
same rule applies: final for that frame; other provider with the same frame (still as a reference image); or give up
sync on that span and cut away.

---

## 4. Higgsfield's silent filter: blocked wording → wording that passed

Higgsfield gives no reason, so the left column is the wording of the blocked version, not a confirmed trigger. The beat
was kept every time; only the words changed. (SP, verbatim.)

| Clip | Blocked wording | What passed |
|---|---|---|
| W07 | "the rope creaking and cutting into his chest"; "she slides one arm across his chest over the rope, cups his bearded jaw with her other hand"; "stroking his beard with her thumb" | "he strains toward the rocks with all his strength, pulling forward and twisting from side to side against the rope"; "she rests one hand on his shoulder, leans in close"; "her cheek near his" |
| W16b | "lashed to the mast with thick hemp rope across her chest"; "she lunges forward against the rope toward the lens; the rope snaps taut"; "screams"; "the cords of her neck standing out, straining so hard the mast creaks" | "held against the mast by a thick hemp rope"; "she leans hard toward the lens, held back at the mast"; "shouts"; "her whole body reaching toward him" |
| W17 | "her cheek brushing his beard"; "her tied hands stretch until her fingertips touch the back of his hand, which rests on the rope at her chest"; "his fingers start working absently at the knot at her chest" (moving the rope to "her shoulder" was blocked too) | "her eyes drift down to his hand, which rests on the rope beside her"; "his fingers begin to loosen the rope" |
| M-s082 | "lashed to the mast"; "he throws himself against the rope toward her … the rope biting into his chest"; "runs two fingers along the rope across his chest, testing how tight it is" | "bound to the mast"; "he pulls hard toward her … the rope holding him at the mast"; "tests the rope with two fingers" |
| M-s043 | "she nuzzles her face into the side of his neck, her lips pressed against his skin and hidden" | "she rests her cheek against the side of his neck, her mouth hidden against his shoulder" |
| M-s029 | "Her argument has just reached him: if nobody builds her, everyone dies."; "as if he has seen something terrible and obvious"; "lashed to the mast with thick hemp rope" | "Her argument has just reached him, and it is working."; "as if the answer were suddenly obvious"; "stands at the mast, a hemp rope around him and the mast" |
| M-s037 | "She has come aboard, and every man she passes stops resisting."; "reach up and pull the orange plugs out of their ears"; "she lets her fingertips trail across one rower's shoulder" | "one by one the rowers stop blocking out her song"; "pull the orange foam out of their ears" |
| M-s079 | "worn by a mountain of black-green tentacles"; "four huge tentacles rip up out of the sea" | "worn by an enormous dark sea creature"; "four huge dark coiling limbs of the creature" |
| M-s068 | "The drug is in his blood."; chrome "spreading through his veins" | "The chrome is in his blood."; chrome "spreading under his skin, following the lines of his veins" |
| M-s073 | "His heart is giving out."; "his chest heaves twice, then stops; his fingers twitch and go still; an empty syringe rolls out of his open hand across the tiles" | "He has gone very still."; "he lies still, breathing slowly, his fingers relaxing open on the tiles; the bulb above him flickers once" |
| M-s025, M-s082 | "a small orange foam plug pushed deep into each ear so only its round end shows" | "both with small orange foam earplugs"; "small orange foam earplugs in their ears (no earmuffs)" |
| M-s085-b, M-s091-b | "He wears nothing on his ears or face (no headset, no earpiece, no star)."; "nuzzling it like a child" | "No headset, earpiece or hair clip on him."; "closes his eyes, grateful" |
| V-s045 | "(only as a guide for the camera path: everything on screen is photoreal, never its grey models, flat colours or placeholder shapes)" | "take only the camera move from it, and film the scene itself in rich cinematic detail" |

**Patterns that tripped it** (re-make round and post-scan round): restraint + chest + a hand or face on the body together
(rope across a chest alone passed: "they haul the rope tight across his chest"); "plugs" / "pushed deep into each ear";
"he wears nothing on his ears"; "photoreal" with women in the frame; "every man she passes stops resisting";
"tentacles"; "drug"; "heart giving out"; "syringe". Plain rewording got 5 of 6 through at once.

**How to reword (rules of thumb):**

- Bodies touching + restraint → one gentle contact ("rests one hand on his shoulder"), the restraint described as
  holding, not cutting or biting.
- "lashed" → "bound", "held against"; "screams" → "shouts"; "nuzzles" → "rests her cheek".
- Death, overdose, harm → stillness ("he has gone very still", "breathing slowly").
- Drugs → the visible effect ("the chrome is in his blood").
- Creatures → "an enormous dark sea creature", "coiling limbs".
- Negatives about clothing ("wears nothing on …") → a positive list of what is absent ("No headset, earpiece or hair clip
  on him").
- Compulsion ("stops resisting") → a softer, visible action ("one by one the rowers stop blocking out her song").
- Previz instructions: never "photoreal"; "film the scene itself in rich cinematic detail".

---

## 5. Copyright-audio refusals

Seedance's own soundtrack copies the song (that is how lip sync works, `61-lipsync.md`), and OpenRouter's audio filter
sometimes refuses the result as possibly copyrighted.

- **Motion clips: always `generate_audio: false`.** They don't need a soundtrack (the edit uses the song), and it avoids
  the refusal. SP ran 42 of 108 OpenRouter takes this way after two refusals. (On Higgsfield, `false` doesn't lower the
  price, but motion clips still don't need the track.)
- **Sung windows need `generate_audio` on** (the sync check compares the clip's own soundtrack). On a refusal: retry
  once (a "sensitive information" refusal with a reworded prompt or a re-cut window; a copyright refusal as it is: EV's
  same request succeeded on a later resubmit). A second refusal on the same provider → **the other provider** with the
  same unaltered image and window. The toolkit counts the refusals per clip and prints exactly this one next step: on
  OpenRouter in `slop clip submit` / `slop clip poll`, on Higgsfield after
  `slop clip ingest <clip> --failed "<the reason, verbatim>"`. If both providers refuse, move the window to a different
  start in a word gap, or cut away.
- The song itself: commercial use of a Suno song depends on the owner's plan and an official download (`10-song.md`). The
  toolkit flags it; it does not decide it.

---

## 6. Real people and likenesses

**Off by default.** claudia.gallery's publishing norm is to keep generated likenesses of real people out, and to quote a
real person's words as text, with the source. A project may opt in only with the owner's written decision in
`DECISIONS.md`, and then only like this (SP's policy):

- a real public figure appears **only as a high-fashion editorial portrait inside a post frame labelled "AI IMAGE"**;
- they **never speak or lip-sync**; mouths stay closed in any motion;
- only **their own dated public words**, quoted exactly, as text — never invented words;
- nothing degrading, sexual or humiliating;
- reference photos only with a licence that allows it (e.g. CC BY), with the attribution recorded;
- never a real private individual, never a minor.

---

## 7. Prevention: write prompts that don't need rescuing

- **Adult leads, unmistakably adult.** Age stated in the canon with an adult face (Claudia: "a 28-year-old", "in her
  late twenties", an angular face, defined cheekbones); never the word "young"; no schoolgirl cues (pleated minis,
  puff sleeves) — EV's lead read as a teenager to viewers.
- **Structured, opaque garments; upright, editorial poses.** "Sheer", "bare shoulders", "bare feet" and reclining poses
  read as nude (SP's sheer gown became "plastic wrap"); seated or reclining frontal poses in short skirts were refused.
- **Seduction is "close, touching, certain … never explicit."** One point of contact per beat; never hands on the chest
  or intimate areas; no kissing unless the owner asks.
- **No minors, no gore, no visible drug use or injection, no self-harm, no real weapons pointed at people.** Show
  consequences as stillness, light, expression.
- **No readable text** in generated images or clips (the engine draws all type).
- **Project taboo words** (BRIEF / `project.json` banned list) never appear in prompts, file names or on screen.
- **The owner's real name never appears** in anything the bot makes public; use their public handle.

---

## 8. The safety & canon scan (before any release)

Filters miss things. SP's six-agent scan of 96 final takes found **12 blocks and 44 fixes** that both providers had let
through: a nude glowing figure, a gown cutout, a rope coil that read as a noose, both hands on her chest, earmuffs,
modern objects in a period scene, crew copies of the second lead, an uncapped needle. The full procedure, the JSON schema
and the triage table are in **`80-review-qa.md` §9**; the essentials:

1. Put the list of final takes in a **file** (`render/scan-list.json`, the safety-scan brief's default; `80-review-qa.md` §9.1 builds it from the EDL) and give each scanner a slice; never paste long
   lists inline.
2. For every take: **6 frames at 8 %, 25 %, 42 %, 58 %, 75 %, 92 %** of its duration, 640 px wide, tiled 3×2 with time
   labels. Look at every sheet.
3. Give the scanner one context line about the video and the canon list, and **whitelist deliberate oddities by name**
   (SP's intentional satellite dish on an ancient mast was flagged as an anachronism).
4. Classify every finding:
   - **block** (must not ship): any nudity or visible genitals or nipples (even glowing, translucent or statue-like
     figures), sexual content, gore, anyone who could be a minor, readable text, logos or watermarks, an object that
     breaks the world (e.g. a modern object in a period scene), a real person's likeness outside the opt-in policy;
   - **fix**: the lead off-canon (wrong age read, a second streak, a missing or extra prop, the wrong garment, a cutout or
     bare chest on a high-necked look), supporting characters copying the lead, props of one character on another,
     generation glitches (melting or doubled faces, extra limbs or fingers, a face morphing into another person,
     warping objects), hooded or veiled figures in white;
   - **note**: small things worth knowing (soft focus, a brief oddity).
   Do not report the grade or colour.
5. **An empty or missing result is a failure, not a pass** (a usage limit once made empty reviews look like passes). A
   clip missing from `checked` was not scanned.
6. Act on it: fix the **source** (an image edit on the plate, `51-plates-api.md` §6, then re-make the clip; or reword
   and re-make), **trim** the take before the problem, or **reject** it. Re-scan every re-make. SP corrected 15 plates,
   re-made 23 clips, then trimmed or cropped the rest.

---

## 9. What you must not do (quick list)

- Alter, re-grade, blur, crop or degrade an image because a filter declined it.
- Retry an identical declined request (it declines again and wastes a turn).
- Run any automatic "filter retry ladder".
- Use an image edit to make a declined image pass.
- Move a sung clip or a cover to an OpenRouter first frame to get past a decline (it loses the audio, §2.1).
- Generate or animate a real person outside §6; make a real person speak.
- Count declines or refunded failures as spend.
- Solve captchas or type credentials for the owner.
- Ship a take the scan marked **block**.

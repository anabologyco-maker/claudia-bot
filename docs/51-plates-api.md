# 51 · Plates and edits with API image models

API image models make plates without Midjourney, and they make **every image edit** in every tier. This file says when
to use them, which model to pick for the money, how to turn a Midjourney-grammar prompt into an API prompt, and how to
write edit instructions.

Read first: `50-plates-midjourney.md` §4–5 (the prompt grammar and the lead's identity: they apply here too).

**Prices below were read from OpenRouter's public model listings on 2026-10-01.** They change: before a batch, re-read
them with `slop gen models --kind image --res 2K` (a free call; cheapest first). Every paid call is estimated first and
written to `ledger.jsonl`; `slop spend` reads the real spend from the provider. **No batch runs before the owner's yes**
(§2.5).

**Commands:** `slop gen models --kind image` (prices) · `slop gen estimate --kind image --model <id> --n 4 --res 2K`
(price of one call) · `slop gen image --jobs` (the whole batch from `plates/jobs.json`: a dry run with the estimate,
then `--yes`; §2.5) · `slop gen image … --plate <key> --yes` (one plate, into `plates/cands/<key>/`) ·
`slop gen estimate --kind edit --model <id>` and `slop gen edit <src> <out> --change "…" --keep "…" --yes` (§6) ·
`slop plates ingest --url <https link> --plate <key>` (a result from the Higgsfield connector or the bot's image tool) ·
`slop plates book` / `sheet` / `pick` (the book and the picking, as in `50-plates-midjourney.md`) · `slop plates box`
(name a region for device anchors) · `slop gate prompts --approve` (G5).

---

## 1. When to use API images

| Situation | Use |
|---|---|
| **Quick tier** (no Midjourney account) | API images for every plate, photographic: Claudia is never illustrated (§3.1). **If OpenRouter is the only video path** (no Higgsfield), plan her sung close-ups so a decline costs nothing: wider framings, cutaways or 2.5D plates. Photoreal faces were declined 18 of 27 times by OpenRouter's video face filter on SP; never switch her to an illustrated look to pass it |
| **Any tier: fixing one detail on a picked plate** | an image **edit** (§6), never a re-paint by hand |
| A pose or character reference made only to feed the video model (an isolated pose on a plain backdrop) | API or MJ, whichever holds the canon better |
| Inserts that need exact objects or readable layout (a phone screen to be filled in code, a product macro) | API (they follow literal instructions) |
| Studio / Director hero plates of the lead | **Midjourney** with the owner's profile (`50-plates-midjourney.md`). API models are the fallback, not the look source: anabology called MJ "just like the most beautiful thing" for his taste, and the public leaderboards do not measure his taste |
| The owner's Midjourney is unavailable mid-project | API, with the project's chapter style tails rewritten for the API model (§4) |

---

## 2. Model choice by cost and quality

### 2.1 OpenRouter (one key: `OPENROUTER_API_KEY`)

| Model id | Price (per image, ~1K unless noted) | Refs | Use it for |
|---|---|---|---|
| `openai/gpt-image-2` | low **$0.004** (measured, 1536×864, 2026-10-01), medium ≈ $0.053, high ≈ $0.21 (1024², listing) | ≤ 16 | **drafts** (low) and literal compositions; cheap edit tests; no transparency; the template's `models.image` |
| `openai/gpt-image-2.5-flare` | token-priced like gpt-image-2 (≈ $0.05 at medium; more at `xhigh`/`max`) | ≤ 16 | **final Quick-tier hero plates**; Arena text-to-image #2; faster tier; transparency |
| `openai/gpt-image-2.5-sunburst` | as flare | ≤ 16 | Arena #1; precise edits; use when flare misses fine detail |
| `bytedance-seed/seedream-5-0-lite` | **$0.035** (2K/4K), input images free | ≤ 14 | consistency across a series with reference images; 2K native 16:9 |
| `bytedance-seed/seedream-5-0-pro` | $0.045 (+$0.003 per input image) | ≤ 14 | as lite, higher quality (Arena #10) |
| `google/gemini-3-pro-image-preview` / `google/gemini-3-pro-image` (Nano Banana Pro; the same model and price under two ids) | **$0.134** at 1K/2K, $0.24 at 4K | ≤ 14 | **the default edit model** (SP: 16 edits, $2.22, faces and light preserved); the template's `models.edit` is `google/gemini-3-pro-image`; `slop gen estimate --kind edit --model google/gemini-3-pro-image` prices both ids alike (the dearest listed endpoint, ≈ $0.137) |
| `google/gemini-3.1-flash-image` (Nano Banana 2) | $0.045 (512) / $0.067 (1K) / $0.101 (2K) | ≤ 14 | cheaper edits and generations; Arena #9 |
| `x-ai/grok-imagine-image-2.0` | **$0.04** low 1K, $0.06 medium 1K or low 2K, $0.08 medium 2K, + $0.01 per input image | ≤ 3 | good general stills (Arena #6) at a low price |
| `black-forest-labs/flux.2-pro` | $0.03 per megapixel | ≤ 8 | multi-reference consistency |
| `recraft/recraft-v4.1-flash` · `black-forest-labs/flux.2-klein-4b` | $0.007 · ≈ $0.014/MP | — / ≤ 4 | pipeline plumbing tests only |

Notes:
- `openai/gpt-image-1-mini` and `gpt-image-1.5` shut down on 2026-12-01: don't build on them.
- Midjourney is not on any API or leaderboard. Arena ranks general appeal, not your owner's taste.

### 2.2 Higgsfield (the connector Grok Bot already has; credits, not dollars)

The bot calls these through its Higgsfield connector (`generate_image`); the toolkit writes the request file and ingests
the result. Image models include `gpt_image_2`, `gpt_image_2_5` (flare/sunburst, up to max quality, transparent
background), `nano_banana_pro`, `nano_banana_2`, `seedream_v5_pro`, `seedream_v5_lite`, `grok_image_2_0`,
`flux_2`, `flux_kontext` (edits), `ideogram_4_5` (typography) and Higgsfield's own **Soul** family:

- **`soul_cast`** — Higgsfield's model for a **consistent cinematic character identity** across many images. Use it when
  a Quick-tier video needs the same new character (one the owner asked for) in 8–15 plates and text-only identity
  keeps drifting. Claudia's identity stays her canon text.
- `soul_location` (consistent places), `soul_cinematic`, `soul_2`.

Per-image credit prices are not published in the catalog. Preflight with the connector's free quote,
`estimate_image_cost` (the same `params` as `generate_image`; it submits nothing), or make one image and read the
`transactions` row. A credit costs about 5.0–5.9 ¢ on top-up packs. Never set `use_unlim: true` unless the owner asks;
an `unlim_choice` reply is a question for the owner, never answered for them.

### 2.3 Grok Bot's built-in `GenerateImage`

Costs only bot usage, takes reference image paths and an aspect ratio. It makes **original visuals only — never real
people** — and can be blocked by its own content safety. Fine for Quick-tier inserts and textures; check the canon on
every result.

### 2.4 Defaults (`project.json` → `models`)

The project template ships `models.image: "openai/gpt-image-2"` and `models.edit: "google/gemini-3-pro-image"`.
`slop gen image` and `slop gen edit` use them when you pass no `--model`.

| Job | Model | Cheaper | Better |
|---|---|---|---|
| Draft a plate to test a composition | `openai/gpt-image-2` low (the template default) | `recraft/recraft-v4.1-flash` | — |
| Final Quick-tier plate | `openai/gpt-image-2.5-flare` medium: **change `models.image` to it for the finals** (or pass `--model`) | `bytedance-seed/seedream-5-0-lite` | `gpt-image-2.5-sunburst` high |
| Same new character (not Claudia) in many plates | text canon + one approved reference image on Seedream 5 / FLUX.2 Pro | — | Higgsfield `soul_cast` |
| Edit one detail | `google/gemini-3-pro-image` (the template default; `-preview` is the same model) | `google/gemini-3.1-flash-image` | `gpt-image-2.5-sunburst` |

Budget sense: 100 API plates at ≈ $0.03–0.05 each is $3–5. A whole Quick-tier video's stills cost less than one
720p Seedance clip (`60-clips.md`).

### 2.5 Before you spend (every API image batch)

API images are cheap, but they are still spend (`00-overview.md` §4, G5: "before any paid video/image batch").

**The lead comes first (gate G3).** A project's first API batch is the **4 test plates of the lead** (CU, MCU, FS, WS in
the real sets; `50-plates-midjourney.md` §5.4), made with the model you will use for production. Show the owner a
numbered sheet and ask "Is this her/him? Flag any wrong face." Record the answer with
`slop decide "<the owner's words>" --by owner`. **No production batch runs before that approval.**

Then, for the test batch and for every batch after it:

1. **Write the book:** `slop plates book` writes `plates/prompts.md` (every prompt the board's plates will send) and
   `plates/jobs.json` (the API jobs: `plate`, `prompt`, `aspect`, `n`, `model`, `shots`, and on lead plates the
   anchor's `refs`, §3). `--only key1,key2,…` or `--missing` write a **subset** book, `plates/prompts-<batch>.md`,
   which is not the G5 book: `slop gate prompts --approve` needs the full `plates/prompts.md`. So pick the plates of a
   batch on the batch command instead: the test plates run with `gen image --jobs --only key1,key2,…`, later batches
   with `gen image --jobs --missing` (only plates with no candidates yet).
2. **Estimate it:** `slop -p <name> gen image --jobs` is a dry run: it prints every job (plate, images, model,
   settings, price), the total estimate, whether it fits the budget, and the exact `--yes` command. Nothing is sent.
   One call's price alone: `slop gen estimate --kind image --model openai/gpt-image-2.5-flare --quality medium --res 2K --n 4`.
3. **The owner reads the book and the estimate** and says yes explicitly ("These N prompts will cost ≈ $X. Go?").
   Never take silence as a yes. Record it with `slop gate prompts --approve --note "<the owner's words>"`.
4. **Run the batch** with one command, after the owner's yes in step 3:
   `slop -p <name> gen image --jobs --yes`. It reads `plates/jobs.json`, checks the budget for the whole batch before
   the first call, runs 4 calls in parallel (`--workers`, at most 8) and writes `plates/cands/<plate>/<k>.png` with a
   `<k>.json` sidecar (prompt, model, settings, cost) for each image. Useful options: `--only hall-ms,roof-ws` (some
   plates), `--missing` (skip plates that already have any candidate, e.g. Midjourney downloads), `--quality` and
   `--res 2K` (`--quality medium` on token-priced models) to override the jobs' settings.
   - **It is resumable.** Re-run the same command after an interruption: each job counts the images it already made at
     the same prompt and settings and makes only the rest, so nothing is paid twice. Low-quality drafts do not count as
     high-quality finals (they are listed as "made at other settings").
   - A refused job (moderation, bad request) is reported and the batch goes on; an account problem (credits, the key's
     limit, auth, rate limit, an unknown outcome) stops the batch with the fix. Every printed command names the project
     (`slop -p <name> …`), so it works from any folder.
   - `budget.confirm_over_usd` and `budget.openrouter_usd` still apply to the batch total.
   Images from the Higgsfield connector come back as HTTPS links: add them as candidates with
   `slop -p <name> plates ingest --url "<link>" --plate hall-ms` (repeat `--url` for several). Grok's `GenerateImage`
   (no key at all) takes each job's `prompt` and `refs` from `plates/jobs.json`; save its images as
   `uploads/gen/<plate>/<k>.png` (or `uploads/gen/<plate>-<k>.png`) in the project, then
   `slop -p <name> plates ingest uploads/gen` (a second run skips the images it already has).
5. **Afterwards:** `slop plates sheet`, then the owner picks, then `slop plates pick hall-ms 2 …`
   (`50-plates-midjourney.md` §10). Run `slop spend` for the real cost.

---

## 3. Identity with API models

The text canon is still the identity (`50-plates-midjourney.md` §5): paste `lead.canon` (or `lead.far` for far shots)
verbatim into every prompt, framing first.

Differences from Midjourney:

1. **A reference image of the approved casting pick is allowed** with API models for a new character (it is your own
   generated character, and these models are built to take references). Claudia's canon holds her identity in text
   alone, with no face image as her reference: anchor her only if text alone drifts on the API model and the owner
   agrees (`slop decide`). Give one clean, front-lit reference of the lead, not a multi-head
   sheet. Still paste the text canon: the reference supports the text, it doesn't replace it. The toolkit does this
   as the **identity anchor**: after the owner approved the lead at G3 and you recorded the pick
   (`slop plates pick lead-cu 2`), `slop plates book --anchor lead-cu` (or `--anchor lead-cu:2` for one candidate)
   writes that image into the `refs` of every lead plate's API job (the anchor's own plate aside) and records it in
   `plates/jobs.json` and `DECISIONS.md`; every later book keeps it (it notes when the pick has changed since: re-run
   `--anchor` to follow it), and `--no-anchor` goes back to the text canon only. `gen image --jobs` then sends it as an
   `input_references` image (the ChatGPT-plan route attaches it as a file), and refuses before any spend when the
   model takes no references. One image by hand: `slop gen image "<prompt>" --plate P --ref PLATE:K` (no K: the
   plate's pick). Midjourney plates never get an anchor (identity stays text there, `50-plates-midjourney.md` §5).
2. **Check every result against the canon.** EV's GPT-Image identity passes on MJ plates drifted from the look and
   refused seated poses. If a model drifts on a framing, go back to text only for that framing, or switch models.
3. **Never use photos of real people as identity references**, and never generate a real person, unless the owner opted
   into the labelled-post policy (`62-moderation.md` §6).
4. Claudia needs no casting call: her canon text is fixed (claudia.gallery, `claudia_canon`). For a new character the owner
   asked for, on a Quick-tier project with no Midjourney casting call, do the casting call with the API model (2–3
   looks × turnaround / set shot / expression sheet), have the owner pick, then write `lead.canon` from the pick. The
   4 test plates of the lead and the owner's G3 approval (§2.5) come before any production batch.

### 3.1 Photoreal or stylized? Claudia is photographic

The look of the lead decides which video provider can animate her face:

- **Claudia is photographic, never illustrated** (claudia.gallery's canon): film stills with grain and cinematic light.
  Her one stylised form is her avatar tier, a cel-shaded 3D game heroine, used only for game or simulation worlds
  inside a story, with its own text and never mixed into a photographic prompt.
- **Photoreal faces** are often declined by OpenRouter's video face filter: on SP, **18 of 27** photoreal face
  references were declined (`62-moderation.md` §2). Higgsfield took the same images. Plan her sung close-ups on
  Higgsfield (`60-clips.md` §6.5). When **OpenRouter is the only video path** (Quick tier without Higgsfield), plan
  them as wider framings, cutaways or 2.5D plates, and send a declined image unaltered to another service if the
  project has one.
- **Illustrated or stylized faces pass** that filter (an anime/cel-style lead went through in the 2026-10-01 probes).
  That is never a reason to restyle Claudia. A stylized look is for a new character, or an illustrated piece, that the
  owner asked for; it needs a stylized style tail (§4), and every plate in the video uses it.

Never turn a photoreal plate into an illustration to get it past a filter: that is altering an image to pass a filter
(`62-moderation.md` §1).

---

## 4. Adapting the Midjourney grammar to API models

Keep the slot order exactly (framing → canon → placement → pose → set/props → empty field → style tail → closer). Change
these things:

| Midjourney | API model |
|---|---|
| `--ar 16:9 --hd` | request fields: `aspect_ratio: "16:9"` and `resolution: "2K"` (or a `size`); there are no `--` parameters in the text |
| the profile gives the look for free | the style tail must say the photography out loud: lens, film, light, colour, grain (see below) |
| `no text, no letters, no logos` | keep it, and add `no watermark, no captions, no user-interface elements` |
| ≤ ~800 characters | can be longer (≈ 400–1,200 characters is fine); still one picture per prompt |
| MJ ignores negatives sometimes | GPT/Gemini/Seedream follow literal negatives well: state what must not appear |
| short noun phrases | full sentences are fine; describe positions literally ("in the left third of the frame") |

**Sung plates: the mouth fully visible.** A sung shot's plate is its clip's lip-sync start frame. `slop plates book`
adds `her mouth fully visible, nothing in front of her mouth (no microphone, hand or hair)` to every sung plate's API
job (`plates/jobs.json`, marked `"sung": true`, and `plates/api/<plate>.txt`) before the style tail. With a canon
headset it says `(the headset microphone at her cheek, clear of her lips; no hand or hair)` instead, so the prop
stays. Midjourney gets the first half only, as MJ draws what a prompt names (`50-plates-midjourney.md` §4, slot 4).
API models follow the literal negative well, but they also add a microphone to "singing" on their own: never write
"into a microphone", and check every sung candidate's mouth before picking. `slop board audit` warns when a sung shot's prompt puts a mic or a hand at her mouth (the Studio run: a mic at
her mouth held one clip to 26 % in sync).

**The API style tail.** Start from the chapter's MJ tail and add what the profile used to supply. Pattern:

```
<chapter light and palette, verbatim from the MJ tail>, photographed on a cinema camera with an anamorphic lens, natural colour, soft halation on the lights, fine film grain, slightly crushed blacks, a real photograph, not an illustration, not a 3D render
```

For a **stylized lead** the owner asked for (§3.1; never Claudia's default) the tail names the medium instead of the
camera, and keeps the chapter's light and palette. Pattern (a starting point to test on the 4 lead plates, not a
measured recipe):

```
<chapter light and palette, verbatim from the MJ tail>, a hand-painted cel-animation film still, clean ink outlines, flat colour with soft painted shading, painted background, consistent character design, not a photograph, not a 3D render
```

**Worked example.** MJ prompt (EV, verbatim; its age word "young" is retired: new prompts use today's identity
text from the canon, never "young"):

```
close-up of a young Caucasian American woman with pale skin and light freckles, a glossy black blunt jaw-length bob with heavy bangs and one clay-orange streak through the bangs, a small flat clay-orange eight-pointed star hair clip, a thin headset microphone, sitting upright alone in the back seat of a driverless robotaxi at night, her face in the centre of the frame, eyes closed, a single red lamp sliding across one cheek through the side window, dark leather seat, the lower third of the frame dark and empty, blue-black night, fog, one small red lamp as the only warm note, fine silver-gelatin grain, cinematic 35mm film still, no text, no letters, no logos
```

The same plate for an API model, with today's identity text:

```
Close-up photograph of a 28-year-old Caucasian American woman with a grown-up angular face, defined cheekbones and a strong jawline, pale skin and light freckles, a glossy black blunt jaw-length bob with heavy straight bangs and one clay-orange streak through the bangs, a small flat clay-orange eight-pointed star hair clip, a thin headset microphone at her cheek. She sits upright alone in the back seat of a driverless robotaxi at night, her face in the centre of the frame, eyes closed; a single red lamp slides across one cheek through the side window; dark leather seat. The lower third of the frame is dark and empty. Blue-black night, fog, one small red lamp as the only warm note, photographed on a cinema camera with an anamorphic lens, natural colour, soft halation on the lights, fine film grain, slightly crushed blacks, a real photograph, not an illustration. No text, no letters, no logos, no watermark, no captions.
```

Request fields: `{"model": "openai/gpt-image-2.5-flare", "aspect_ratio": "16:9", "quality": "medium"}` (or
`"resolution": "2K"` on models that take it).

**Size for the engine.** Plates are used at ≤ 2400 px wide. A 1K result is too small for a full-frame 2.5D move: ask for
2K where the model offers it; otherwise upscale with **Lanczos** (measured: every learned upscaler tested was further
from the truth, shimmered 10–25 % more and turned skin waxy).

---

## 5. Request shapes (for reading logs; the toolkit builds them)

Generation — OpenRouter images API:

```
POST https://openrouter.ai/api/v1/images
Authorization: Bearer $OPENROUTER_API_KEY
{"model": "openai/gpt-image-2.5-flare", "prompt": "…", "aspect_ratio": "16:9", "quality": "medium", "n": 1,
 "input_references": [{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,…"}}]}
→ {"data": [{"b64_json": "…", "media_type": "image/png"}], "usage": {"cost": …}}
```

A generation is billed in full or not at all (no partial billing). Read `usage.cost` from every response and write it to
the ledger.

Edit — OpenRouter chat completions with image output (how SP's edits were made):

```
POST https://openrouter.ai/api/v1/chat/completions
{"model": "google/gemini-3-pro-image", "modalities": ["image", "text"],
 "messages": [{"role": "user", "content": [
   {"type": "text", "text": "Edit this photograph. <instruction> <KEEP clause>"},
   {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,<the plate>"}},
   {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,<optional reference>"}}]}]}
→ choices[0].message.images[0].image_url.url  (a base64 data URL)
```

---

## 6. Image edits (every tier)

### 6.1 The instruction grammar

```
Edit this photograph. Change only <X>: <the precise target state, with negatives>. Keep <Y>.
```

…followed by the **fixed KEEP clause**, which the toolkit appends verbatim to every edit:

```
Keep everything else exactly as it is: the same framing and crop, the same light, colours, film grain and sharpness, the same people and objects except what this instruction changes. Photorealistic, the same photograph, same aspect ratio.
```

The command composes the instruction and appends the clause (the owner's yes first, as for any spend; ≈ $0.14):

```
slop gen edit plates/cands/hall-ms/2.jpg plates/cands/hall-ms/5.png --change "the hair clip: a small flat clay-orange eight-pointed star (exactly eight points)" --keep "her face, the orange streak and the headset" --yes
slop plates pick hall-ms 5
```

Save the edit as the plate's **next candidate number** (here `5.png`, after the four originals), so the original stays
untouched and `slop plates pick` can point `plates/picks.json` at the edit.

How to write X, the target state and Y:

1. **Name one region or one set of things.** "the man's eyes", "the rowers on both sides of the ship", "the hair clip".
2. **Describe the end state physically**, with counts and shapes: "exactly eight points", "exactly one small clay-orange
   eight-pointed star clip remains (the one on the right side of the image)".
3. **Add the negatives that stop the usual failure:** "none of them is bald, none has a thick dark beard like the man in
   the centre, and none wears black"; "no hoods, no veils, no cones"; "not a horn or spike sticking out".
4. **Name what must not move (Y):** the faces, the main character, the number and positions of figures, the props.
5. If you attach reference images after the plate, refer to them by position ("the second image").

Verbatim SP instructions that worked:

- Recast a crew: `Change only the rowers on both sides of the ship: make them men of every age and build, some grey-haired and grey-bearded, some red-bearded, some with long curly hair tied back, some young and clean-shaven, with sun-dark weathered skin, all wearing plain undyed off-white linen tunics, each with a small bright orange foam earplug in his ear. None of them is bald, none has a thick dark beard like the man in the centre, and none wears black. The man sitting cross-legged in the centre with his phone stays exactly the same.`
- Remove anachronisms: `Replace every modern object behind them (metal railing posts, wire lifelines, the white fibreglass deck edge, the crumpled clear plastic object) with the dark wooden rail, thick hemp rigging and square sail of an ancient black Greek galley at twilight. Also remove the second small orange star on her cheek or temple, keeping only the star clip in her hair.`
- Remove a prop and fix one canon item: `Remove the syringe and its needle completely; her lower chrome-gloved hand rests empty and relaxed against her chest. Replace the hoop-shaped wire and round disc hanging at her left jaw with a thin dark headset microphone: one slim boom running from her left ear along her cheek to just beside the corner of her mouth. Keep the vial in her raised hand, the star clip, the orange streak and her expression.`
- Fix the second character's canon: `Shave the man's head completely: a smooth, freshly shaved scalp with no hair at all. Keep his beard, his face, his eyes, his expression and the rope across his chest exactly the same. Keep the woman exactly as she is.`
- Fix a shape: `On the colossal porcelain mask of the woman's face, make the orange streak a flat streak of clay-orange hair lying inside the black bangs, not a horn or spike sticking out. Keep the mask, its crack, the dark sea creature around it, the ship and the sea.`

**Before an edit:** `slop -p <name> gen estimate --kind edit --model google/gemini-3-pro-image` prices one call (the
plate plus any `--ref` images). `--medium` sets how the instruction is worded: `photo` (the default), or
`illustration` for an illustrated or cel-shaded lead (`cel` means the same); without it the toolkit reads
`look.medium`, then the lead canon's own words, and says which it used.

### 6.2 What edits are for — and not for

Edits are for **content fixes the owner, the review or the safety & canon scan asked for**: canon errors (an extra clip,
the wrong clip shape, props of one character on another), anachronisms, recasting copies, bare heads instead of hoods,
an effect that belongs in the image (chrome eyes instead of painting them in code), removing something that must not
ship (an uncapped needle).

Edits are **never** for:
- getting an image past a provider's safety filter (`62-moderation.md`: a declined reference is final; no re-grading,
  blurring, cropping or "softening" to pass);
- changing an invented face into a real person, or a real person into anyone;
- re-painting the whole look (grade in post; `70-motion-design.md`).

### 6.3 After each edit

1. Look at it and **re-check the canon** — the edit model can introduce new errors (SP: a pink six-pointed star appeared
   where the eight-pointed clip should be).
2. Keep the original; save the edit as the plate's next candidate number; `slop plates pick <plate> <k>` updates
   `plates/picks.json`.
3. Re-run plate prep (depth, mattes, detection) on the edited file.
4. Re-make any clip that started from the old file.
5. Output size: SP's edits came back 1376×768. Request 2K where offered; otherwise Lanczos to 2400 wide.
6. Ledger: ≈ $0.13–0.14 per Nano Banana Pro edit.

### 6.4 Naming a region for the devices (`slop plates box`)

The engine anchors CV marks and callouts to named boxes (`{"box": "a face"}`, `40-storyboard.md` §3.7), and the toolkit
detects none by itself. Name one on a plate's picked image: `slop -p <name> plates box hall-ms --label "a face" --uv 0.41,0.18,0.16,0.30`
(u, v = the box's top-left corner, w, h its size, all 0..1 of the image; `--label subject` is the lead box).
`slop -p <name> plates box hall-ms` lists the plate's boxes; `--rm --label "a face"` removes one. Then
`slop edit export` passes them to the engine.

---

## 7. Quality checks for API plates

- [ ] 16:9, ≥ 2K on the long edge (or upscaled with Lanczos), decodes cleanly.
- [ ] The canon holds (ethnicity, age read, hair, the one mark, the props); same face as the approved pick.
- [ ] No text, letters, logos, watermarks, captions or UI that you did not ask for.
- [ ] The declared empty field is empty.
- [ ] Sung plates: her mouth fully visible, no microphone, hand or hair in front of it (re-roll otherwise, §4).
- [ ] Not stock-photo-like (generic crowds, elderly or patient portraits, clinic close-ups, glossy "AI sheen" skin):
      the owner rejects those on sight — change the idea, not just the wording.
- [ ] Looks like a photograph from the same film as its neighbours (same chapter tail, same light).
- [ ] Ledger row written with `usage.cost`.
- [ ] Before the batch: the 4 lead plates approved (G3), the book and the estimate approved (G5, §2.5).
- [ ] Photographic (Claudia is never illustrated); her sung close-ups planned for the video path the project has (§3.1).

---

## 8. Failure catalogue (API images)

| Symptom | Cause | Fix |
|---|---|---|
| Glossy, illustrated or 3D-render look | no photographic language | the API style tail (§4) |
| The lead's face drifts across plates | text-only identity on a model that drifts | one approved reference image + text canon; or `soul_cast`; or another model |
| A real person's likeness appears | the prompt named or described a real person | remove it; real people only under the opt-in policy (`62-moderation.md`) |
| `moderation_blocked` (OpenAI) / a content-safety error | the prompt read as unsafe | reword plainly (`62-moderation.md` §4); never alter an input image to pass |
| 1K output looks soft in a 2.5D move | resolution | ask for 2K; Lanczos upscale |
| An edit changed more than asked | instruction named a region vaguely | name one region, list what to keep (Y), keep the fixed clause |
| An edit added a new canon error | model hallucination | re-check after every edit; edit again with the exact count/shape |
| Transparency missing | `gpt-image-2` has no transparency | use `gpt-image-2.5-*` with `background: "transparent"` |
| A microphone at her mouth on a sung plate (Studio run: that clip 26 % in sync) | "singing" invites a mic; a mic or hand written in the prompt | the book's mouth line on sung plates (§4); take the mic out of the prompt; re-roll (about $0.03), never pick it |
| Price differs from the table | pricing changed | re-read the free model listing (`slop gen models --kind image`); the ledger takes `usage.cost` from the response |
| Most of the lead's sung clips are declined later by OpenRouter's face filter | a photoreal lead on an OpenRouter-only project | Higgsfield (or another service) for those clips with the same unaltered images; otherwise wider framings or cutaways (§3.1) — never restyle a declined plate |
| A batch ran before anyone read it | `--yes` passed without the owner's go | stop; the owner reads `plates/prompts.md` + the estimate first (§2.5) |

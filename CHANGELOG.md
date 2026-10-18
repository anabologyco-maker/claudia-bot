# Changelog

Each release is a tag `vX.Y.Z`. A bot on an older release reminds its person once ("say update"); `slop update apply`
installs it and prints the newest entries below.

## 0.3.6
- No more double songs, repeated uploads or two Grok runs fighting over the browser: each job is claimed before it runs, one at a time, and a wake-up waits while Grok is working. A job over 6 hours old is never run without asking Opus first.
- New for Opus and Codex: earshot, the production's ears (it describes, times and critiques every take, mix and cut; the full install adds it), and ElevenLabs voices, sound effects and music with your own key (optional; every paid call needs your yes).
- Your OpenRouter key: you hear two weeks before it expires or runs out, and as soon as it stops working, so you can send a new one on the secure card.
- Renders fit the computer's memory and leave room for Grok's browser; a stuck render stops after 5 minutes instead of hanging, a redraw never leaves holes, and two encodes never write at once.
- Drive: every video Opus sends is under Drive's 100 MB limit (and plays on phones), and Grok asks which Google account to use instead of guessing.
- After a computer reset, setup puts `slop` back on the PATH, `slop` says what to run instead of crashing, and the setup check no longer reports the toolkit missing.
- Midjourney: prompts over 800 characters are stopped before they run, prompts are pasted instead of typed (no more typos in words like diamanté), every image is saved as a .png carrying its prompt, and Grok checks personalization is still on after Zoom Out.
- Grok Imagine: Grok never picks an option your plan locks, and a wiped form is reloaded with a single upload.
- Wake-ups take the routine's real webhook address (its POST to field in the Grok Bot desktop app); a link to the routine is refused, since it never worked.
- Files you send reach Opus as files, and Opus going quiet for 20 minutes is flagged as possibly stuck, with the way out.

## 0.3.5
- Opus can close a job it no longer needs: it shows as cancelled, not failed.
- Every Midjourney image records the prompt, plate and model that made it.
- A Midjourney prompt over about 800 characters gets a warning before it runs.
- A video phones play badly (full range) is stopped before it reaches you, and Opus gets the one-line fix.
- Drive: videos upload as .mov (an .mp4 was filed as a document on Android), and the setup test clip checks it plays.
- Wake-ups reuse a claudia-wake routine a template brought instead of making a second one.

## 0.3.4
- Wake-ups say up front that their key comes from the Grok Bot desktop app (the phone app has no Webhook section), and "later" skips them: everything works without.

## 0.3.3
- Videos and big files reach you as links in your own Google Drive (chat attachments often fail for videos). Setup offers Google Drive (free) and checks it once with a 2-second test clip; Grok keeps every file private to you.

## 0.3.2
- Wake-ups take one step: paste the routine's key into the secure card (Grok links you straight to it). Grok works out the routine's address itself and asks for it only if that fails.
- Grok Imagine: Grok re-selects the resolution before each Generate (the button could show 720p and still render 480p) and checks every file's size; Opus is told each file's real size.
- A higher resolution is a new Grok Imagine take, never a re-download of an old one.
- A save folder Opus names from the projects folder is no longer doubled (NAME/NAME/inbox).

## 0.3.1
- Opus and Codex can spend again: paid steps (API stills, clips, songs) get the OpenRouter key you gave. Every spend still needs your yes.
- ChatGPT-only setups get Codex automatically (no more "install Claude Code").
- Wake-ups are easier: Grok asks for the two values by their labels on the routine's Webhook page (POST to, and the key: tap Generate if it is empty). The key or the whole Authorization header line both work.
- Grok Imagine always uses the highest resolution the page offers.
- Midjourney: one prompt per job, each saved under its plate's name, so Opus files the images by itself.
- Opus re-reads its brief after an update, an update keeps a model you chose, and the lyric scorer runs exactly as Opus is told.

## 0.3.0
- Wake-ups: Grok hears the moment Opus (or Codex) posts, even after its own turn ended. Grok sets up a small wake-up routine once (its key goes in a secure card); the relay calls it when there is news and Grok is not already waiting.

## 0.2.9
- Always the newest: no model or version is hard-coded. The toolkit picks the newest model of each family, Midjourney prompts never carry `--v` (its default is its newest), and Grok uses the newest model each site offers.
- Midjourney's Raw, HD and personalization are your choices (Opus asks once per project; defaults Raw on, personalization on, HD off). Personalization goes on with the P button, never as a code in a prompt.
- Suno: Grok follows the page as it is today (the Advanced tab; an instrumental is an empty lyrics box).
- Effort: Claude Code and Codex now think at xhigh by default; say "effort" to pick another level (the levels come from the engine itself). A level the engine does not take falls back to its default instead of failing.
- Updating never stops at local edits on the bot's computer: they are set aside (kept in git's stash) and the release goes on.
- Grok's wait for Opus holds its full time (a blip no longer ends it early), and Opus keeps its turn open while its own long steps run.

## 0.2.8
- Every browser task is Grok's: Opus sends Midjourney prompts and Suno songs to Grok, which runs them in its own signed-in browser and hands back the files. You only decide; you never paste, press Create or download.

## 0.2.7
- The home-GPU link is parked until it works from every bot (a relay is in the works); analysis runs on the bot's computer meanwhile.

## 0.2.6
- Updates: a quiet reminder once per new release, and "update" installs it in one step (code, install, brief, skills).

## 0.2.5
- The home GPU's tunnel counts as up only once Cloudflare registers it; when the network blocks port 7844 you get the real reason and direct mode, never a dead pairing line.
- Sung-clip audio hosting and the taste app use the same check.

## 0.2.4
- Claude Code and Codex both get the claudia.gallery MCP; Opus's brief now covers the home GPU.

## 0.2.3
- The welcome says what each subscription gets you (Claude Max 20x recommended), asks "Set me up?", then what you have or will get.

## 0.2.2
- A welcome first: what the bot is, its skills and what to subscribe to, before any sign-in.

## 0.2.1
- The director's scansion and assonance scorer; Opus scores every lyric draft.

## 0.2.0
- Claudia: Grok relays, Opus produces, claudia.gallery is the source of truth; Grok Imagine in Grok's own browser.

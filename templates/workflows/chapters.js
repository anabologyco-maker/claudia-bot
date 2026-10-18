export const meta = {
  name: 'slop-chapters',
  description: 'Chapter motion design: the chapter files are wired into engine/ch/_index.js, then per chapter an animator codes its chapter file against the engine device library, an art director renders it and reviews real frames and contact sheets (owner taste counts double), the animator fixes; a second review and a last fix while blocking fixes remain. A missing review is a failure, never a pass.',
  phases: [
    { title: 'Setup', detail: 'wire every chapter file into engine/ch/_index.js (skipped when the runner already did) and, for a refit, rebuild the edit once' },
    { title: 'Animate', detail: 'one animator per chapter writes its own chapter file and verifies it with renders' },
    { title: 'Review', detail: 'real renders judged: owner taste (double weight), craft, sync, story; every fix marked blocking or polish' },
    { title: 'Fix', detail: 'the animator applies the fixes, blocking first, and re-verifies' },
    { title: 'Review 2', detail: 'second review; a last fix while blocking fixes remain' },
  ],
}
// Claudia chapters (Claude Code Workflow script). Generalised from the reference videos' chapter workflows
// (animate -> art director on real renders -> fix, and the v2 form: review -> fix -> review 2 -> fix 2 with the owner's
// taste weighted double). Intentional changes, each from a recorded failure:
//  - WIRING: the engine page loads only <project>/engine/ch/_index.js, so a chapter file it does not list is never
//    rendered — and the lyric gate still prints N/N, because the default renderer subtitles every sung word. The
//    reference workflow relied on the project page already loading each file; here the delegation runner wires the files
//    before the engine starts (args.wired) and otherwise a Setup agent runs `deleg.mjs wire`. Animators never touch
//    _index.js; every review runs the wiring check (`deleg.mjs wire --check`) and NOT WIRED blocks the chapter.
//  - A null, empty or render-less review is a FAILED review (retried once), never "nothing to fix": a usage limit once
//    made every round-2 review return nothing and the runs still reported "completed". Fixes applied but never
//    re-reviewed in a planned round 2 make the run ok:false ("incomplete"), so a resume is not forgotten.
//  - Calibrated pass rule: pass = no BLOCKING fix left and owner >= 7 and craft/sync/story >= 6 and the lyric gate N/N
//    (and the chapter wired). The old "director >= 8 and others >= 7" bar passed 1 chapter in 9 while the owner called
//    the cut built from the 7-7.5 chapters "perfect. change nothing" — so the bar is now what would stop a chapter
//    shipping, not a number. The reviewer's own pass flag is recorded but the script decides. Override with args.pass_rule.
//  - RENDER LOAD: the reference ran at most 2 agents per workflow and rendered with --workers 2; six agents rendering at
//    once once ate swap and filled the disk. Here at most args.parallel_chapters (2) chapters run at once and every
//    render command passes --workers args.render_workers (2); the runner runs one "render" job at a time.
//  - Code is written against the engine's device library (engine/DEVICES.md), not a project's private kit; render,
//    sheet, gate and history checks go through the toolkit CLI (`slop render ...`).
//  - mode "refit" (re-key a built chapter to re-made footage and apply carried-over fixes) is the v2 refit pass; the
//    edit is rebuilt ONCE in Setup, never by each animator (parallel animators once raced on edit export).
// Resume: Workflow({scriptPath: <this file>, resumeFromRunId: <run>, args: <same args>}); an animator whose file
// already has scenes continues from it. Run 3–4 chapters per workflow.
//
// args (a JSON object; the delegation runner fills project_dir, out_dir, toolkit_dir, job_dir, slop and wired):
//   project_dir   (required) absolute path of the project folder        out_dir (required) the job's outbox
//   chapters      (required) [{id, file, name, t0, t1, shots: [ids], fixes?: [{shot, time, problem, fix}] (carried over)}]
//   toolkit_dir   the toolkit checkout (engine/DEVICES.md, docs/, runner/deleg.mjs)    slop  how to run the CLI (default "slop")
//   wired         true when the runner already wired the chapter files (skips the Setup agent in build mode)
//   title, owner, owner_quotes (verbatim taste/brief, string or list), bar (overrides the reference bar), extra, banned_words
//   mode          "build" (default) or "refit"                         rounds 1 or 2 review rounds (default 2)
//   parallel_chapters  chapters in flight at once (default 2)          render_workers  browsers per render command (default 2)
//   scratch_dir   default <project_dir>/render/scratch/chapters       render_cmd default "<slop> --project <project_dir> render"
//   edit_cmd      default "<slop> --project <project_dir> edit"        pass_rule {min_owner: 7, min_other: 6}
//   max_fixes (12), sheet_min (24), ms_per_frame (1500)
const A = typeof args === 'string' ? JSON.parse(args) : (args || {})
const miss = ['project_dir', 'out_dir', 'chapters'].filter(k => !A[k])
if (miss.length) return { ok: false, error: `args missing: ${miss.join(', ')} (pass args as a JSON object; chapters inline as a list)` }
const CH = Array.isArray(A.chapters) ? A.chapters : []
const bad = CH.filter(c => !c || !c.id || !/^[A-Za-z0-9][\w.-]*\.js$/.test(String(c.file || '')) || c.file === '_index.js' || !(Number(c.t1) > Number(c.t0)) || !Array.isArray(c.shots) || !c.shots.length)
if (!CH.length || bad.length) return { ok: false, error: `every chapter needs id, file (a plain name like 02_board.js), t0 < t1 and a non-empty shots list; bad: ${JSON.stringify(bad).slice(0, 300) || 'no chapters'}` }
const clean = p => String(p).replace(/\\/g, '/').replace(/\/+$/, '')
const P = clean(A.project_dir), OUT = clean(A.out_dir), TK = A.toolkit_dir ? clean(A.toolkit_dir) : null
const SLOP = A.slop || 'slop'
const CHDIR = `${P}/engine/ch`   // the only folder the engine loads chapter code from (through _index.js)
const SCR = A.scratch_dir ? clean(A.scratch_dir) : `${P}/render/scratch/chapters`
const R = A.render_cmd || `${SLOP} --project "${P}" render`
const EDIT = A.edit_cmd || `${SLOP} --project "${P}" edit`
const RUNNER = TK ? `node "${TK}/runner/deleg.mjs"` : null
const TITLE = A.title || 'the video'
const OWNER = A.owner || 'the owner'
const MODE = A.mode === 'refit' ? 'refit' : 'build'
const ROUNDS = Number(A.rounds) === 1 ? 1 : 2
const RULE = { min_owner: 7, min_other: 6, ...(A.pass_rule || {}) }
const MAX_FIX = Number(A.max_fixes || 12), SHEETS = Number(A.sheet_min || 24), MSF = Number(A.ms_per_frame || 1500)
const W = Math.max(1, Math.round(Number(A.render_workers) || 2))
const PAR = Math.max(1, Math.round(Number(A.parallel_chapters) || 2))
const BANNED = Array.isArray(A.banned_words) ? A.banned_words.filter(Boolean) : []
const QUOTES = Array.isArray(A.owner_quotes) ? A.owner_quotes.map(q => `"${q}"`).join(' · ') : (A.owner_quotes || '')
const q = s => '`' + s + '`'   // every command is quoted in backticks (the toolkit's tests parse each one)
// The reference bar: the reference videos' director (public name anabology), verbatim, lightly trimmed […].
// A project's own owner_quotes / DECISIONS.md come first and win any conflict.
const REF_BAR = `"all this should be high effort: e.g. animate the lyric renderings to be on beat, have everything be quite dense" · "One big part of the magic […] were that you generated motion graphics and motion design, not just animated lyrics but things that fit the words being said to bring the words and theme to life, almost explaining the words with visuals" · on 2.5D plates: "that's where we'll have to shine and be creative. depth to separate layers ofc, motion graphics galore, diversity so its not repetitive" · on transitions: "interesting and intelligent transitions, like edgar wright level ... not solely cuts but things that work with the motion design or graphics - but also not overdone and amateurish." · "beautiful motion design, real depth mapping, i like rotoscopes and depth mapping to cover text + beautiful text that adapts to color of bg" · "its a lyric video - all the lyrics must be on screen" · "editing and camera should feel really synced to the beat or sound effects […] dont need to force flashing" · "keep it clean so it feels like imax, high res rather than dithered" · on colour: the footage keeps its generated colour ("way too gray … loses the […] magic") — never desaturate the base.`
const BAR = `${QUOTES ? `${OWNER}'s words, verbatim (binding, they win any conflict): ${QUOTES}\n` : ''}${A.bar ? `The bar for this video: ${A.bar}` : `The reference bar (anabology, the director of the reference videos, verbatim): ${REF_BAR}`}`
const DOC = TK ? `${TK}/engine/DEVICES.md (the device library and engine API — code against it exactly; it is the contract), ${TK}/engine/README.md (how chapters load and render), ${TK}/docs/70-motion-design.md (the motion-design rules: explaining layer, type modes, 2.5D treatments, transitions, element budget, flashes; §16 is how chapter code is written) and ${TK}/docs/examples/ (exemplar chapters and shots, if present)` : 'engine/DEVICES.md and docs/70-motion-design.md in the toolkit'
const READ = c => `READ FIRST, fully: ${P}/PRODUCTION.md if it exists (the binding plan); ${DOC}; ${P}/project.json (look, accent, fonts, lead canon); ${P}/DECISIONS.md (${OWNER}'s decisions — binding; a later UPDATE supersedes); ${P}/board/STORYBOARD.md (YOUR shots ${c.shots.join(', ')}: action, camera, type, devices, transition, notes) and ${P}/board/shots.json (the same shots as data); ${P}/lyrics/lyrics.txt and ${P}/analysis/words.json (every sung word and its time); ${P}/analysis/beats.json and ${P}/analysis/hits.json (cuts and camera moves answer these); ${P}/edit/edl.json (which footage each shot shows: a clip take in song time, or its plate); ${P}/taste/taste-tokens.json if present; the other chapter files in ${CHDIR} (read them for consistency, never edit them).`
const WIRE = c => RUNNER ? q(`${RUNNER} wire "${P}" --check --file ${c.file} --shots ${c.shots.join(',')}`)
  : `(no toolkit_dir: open ${CHDIR}/_index.js and confirm it lists ${c.file}, and that ${c.file} calls scene() for its shots; write "WIRED ${c.id} ${c.file}" or "NOT WIRED ${c.id} ${c.file}: <why>")`
const CMDS = c => `Commands (the toolkit CLI; if a verb or flag is rejected, run ${q(`${R} --help`)} and ${q(`${R} lyrics --help`)} (any verb), use what it offers, and report the mismatch): lyric gate ${q(`${R} lyrics --from ${c.t0} --to ${c.t1} --workers ${W}`)} (must print N/N, e.g. "132/132 tokens on screen at their time") · wiring check ${WIRE(c)} (must print WIRED: your file is listed in ${CHDIR}/_index.js, parses and registers scenes; NOT WIRED means the default renderer draws your shots, whatever the lyric gate says) · page boot ${q(`${R} info`)} (no PAGE ERRORS: a draw function that throws stops the lyric gate) · contact sheet ${q(`${R} sheet --times <comma-separated seconds> --cols 4 --w 480 --out ${SCR}/${c.id}/<name>.jpg`)} (then Read the jpg) · full-size stills ${q(`${R} stills --times <comma-separated seconds> --out ${SCR}/${c.id}/stills`)} · frames ${q(`${R} frames --from ${c.t0} --to ${c.t1} --every 2 --workers ${W} --out ${SCR}/${c.id}/frames`)} (12 fps samples of a 24 fps cut) · history check ${q(`${R} check --skip-flash --pairs <A:B,A:B,A:B>`)} on pairs inside your range (must print HISTORY-INDEPENDENT) · the whole-cut flash check runs later on the bot's side, so design for at most 3 full-frame flashes in any second. Render with at most ${W} browsers per command (never raise --workers: other chapters render at the same time and each browser takes about 3.5 GiB). Scratch goes under ${SCR}/${c.id}/, never /tmp. Never rebuild the edit yourself (edit edl / edit export): ${MODE === 'refit' ? 'the setup step rebuilt it once for every chapter' : 'it is not part of this job'}.`
const RULES = `Hard rules: frames are pure functions of t (rendered in parallel and out of order): no state carried between frames, no Math.random (use the engine's hash), no Date, caches only of derived data that do not depend on which frame came first. Every sung token in the range on its word time, at least 40 px for the main lyric on a 1080p frame, never over a face; if you draw a lyric token yourself, mark it as the device library says so the lyric gate counts it. Each line gets one explaining graphic (chart, UI, diagram, label, counter, map) that enters on the words naming it and moves in beats; at least 3 ordered layers per frame. 2.5D treatments never repeat on consecutive plate shots; use at least five different ones in a chapter that has five or more plate shots. Mostly hard cuts on the beat; a motivated transition every few shots, never the same device twice in a row. Where a sung line has no synced take, never hold a singing mouth in close-up on the words: use stills in rhythm, depth moves, crops to eyes/hair/hands, inserts or motion design. Never grade, tint or desaturate the footage unless DECISIONS.md says so. At most 3 full-frame flashes in any second. ms/frame <= ${MSF}.${BANNED.length ? ` These words never appear on screen or in your code: ${BANNED.join(', ')}.` : ''}`
const YOURFILE = c => `YOUR FILE: ${CHDIR}/${c.file}. It already exists (a stub until you write it) and ${CHDIR}/_index.js already loads it — never edit _index.js, never rename or move your file. Edit ONLY this file — other chapters are written in parallel in their own files. If it already contains scenes (an interrupted earlier run), continue from it; never start over. A missing shared helper: write it privately inside your file. A bug in a shared file (engine, device library, analysis, edit, _index.js): do not edit it — report it (file, line, fix).`

const animate = c => agent(`You are the animator of chapter ${c.id} "${c.name || c.id}" (${c.t0}–${c.t1} s, shots ${c.shots.join(', ')}) of ${OWNER}'s lyric music video "${TITLE}".
${BAR}
${READ(c)}
${A.extra || ''}
${YOURFILE(c)}
${MODE === 'refit' ? `REFIT (the footage changed): 1. read ${P}/edit/edl.json — the setup step rebuilt the edit once for every chapter; never rebuild it yourself — and see which shots now show new takes; 2. look at the new footage of every shot (contact sheets at each shot's first/middle/last frame); 3. re-key everything tied to the old takes (occlusion and tuck positions, tracked tags and leaders, crops and zooms, lyric placement relative to the people); crops must keep the action the new footage shows — never crop the performance out; 4. apply these carried-over fixes, most important first (skip any your file already does): ${JSON.stringify(c.fixes || [])}.`
    : `BUILD: scenes covering [${c.t0}, ${c.t1}) exactly, one per shot at its t0/t1 from shots.json (uncovered shots fall back to the plain default renderer). Per shot: the base footage through the engine's media device (the edit's take in song time, or the plate while a clip is pending; never name clips yourself); the shot's 2.5D treatment if it is a plate shot; every sung token through the lyric devices in the type mode shots.json gives; the explaining graphic (start from the shot's devices and notes and push it further); annotations and chrome; the look; the transition_in.${(c.fixes || []).length ? ` Also apply these carried-over fixes: ${JSON.stringify(c.fixes)}.` : ''}`}
${RULES}
${CMDS(c)}
FIRST DELIVERABLE: within your first ~12 commands, a rough but COMPLETE chapter (every shot covered), the wiring check printing WIRED, and one contact sheet you have Read. Then iterate.
VERIFY before returning: a. the lyric gate prints N/N; b. the wiring check prints WIRED and the page boot shows no PAGE ERRORS; c. contact sheets at every shot's first and last frame, every line's first and last word, each graphic's entrance and each transition's middle — Read every sheet and LOOK; iterate until every frame is clean, dense (>= 3 layers), on the beat, readable on a phone, on-model, in the bar above; d. sync: render ${c.t0}:${c.t1} at 12 fps and list the 10 biggest camera moves/cuts with the nearest hit for each; e. the history check on 3 pairs inside your range; f. count full-frame flashes per second in your 12 fps frames (at most 3); g. ms/frame.
Return: scenes (ids, times); per line its type mode and explaining graphic; each plate shot's treatment; the transitions; the lyric gate line; the wiring line; the sync list; the history and flash results; ms/frame; known issues; shared bugs (file, line, fix).`,
  { label: `animate:${c.id}`, phase: 'Animate', effort: 'high' })

const REVIEW = { type: 'object', properties: {
  owner: { type: 'number', description: `${OWNER}'s taste and the bar, 0-10 (counts double): clean, beautiful motion design that explains the words, never cheap or busy, the footage's action reads` },
  craft: { type: 'number', description: 'type setting, ink over footage, depth/occlusion, devices, transitions, 0-10' },
  sync: { type: 'number', description: 'cuts and camera answer the beats and hits; every word on its time; no out-of-sync mouth on screen, 0-10' },
  story: { type: 'number', description: 'every lyric on screen and legible on a phone; each line explained by its graphic; canon and owner notes kept, 0-10' },
  pass: { type: 'boolean', description: 'your own opinion; the script decides the verdict from the fixes and scores' },
  fixes: { type: 'array', items: { type: 'object', properties: {
    shot: { type: 'string' }, time: { type: 'number' }, severity: { type: 'string', enum: ['blocking', 'polish'] }, problem: { type: 'string' }, fix: { type: 'string' } },
    required: ['shot', 'severity', 'problem', 'fix'] } },
  checks: { type: 'object', properties: {
    lyric_gate: { type: 'string', description: 'the exact line the lyric gate printed, e.g. "132/132 tokens on screen at their time"' },
    wired: { type: 'string', description: 'the exact line the wiring check printed: "WIRED …" or "NOT WIRED …"' },
    sheets: { type: 'number', description: 'how many frames you looked at on contact sheets and stills' },
    ms_per_frame: { type: 'number' }, flash_max_per_s: { type: 'number' } }, required: ['lyric_gate', 'wired', 'sheets'] } },
  required: ['owner', 'craft', 'sync', 'story', 'pass', 'fixes', 'checks'] }
const SEVERITY = `Mark every fix "blocking" or "polish". BLOCKING = it would stop the chapter shipping: the chapter not wired (the wiring check prints NOT WIRED); a lyric gate miss or a word off its time; type over a face; the main lyric unreadable on a phone (< 40 px or no contrast); an out-of-sync mouth held on screen; black, frozen, torn or broken frames; an off-model lead; banned content or words; more than 3 flashes in a second; the same treatment or transition device back-to-back; a line with no explaining graphic; a render error. POLISH = everything that would make it better but would not stop it shipping. Do not inflate polish into blocking.`

const str = x => typeof x === 'string' && x.trim() !== ''
const validReview = r => !!(r && ['owner', 'craft', 'sync', 'story'].every(k => typeof r[k] === 'number' && r[k] >= 0 && r[k] <= 10)
  && Array.isArray(r.fixes) && r.checks && str(r.checks.lyric_gate) && str(r.checks.wired) && Number(r.checks.sheets) > 0)
const gateOk = s => { const m = String(s || '').match(/(\d+)\s*\/\s*(\d+)/); return !!(m && m[1] === m[2] && Number(m[2]) > 0) }
const wiredOk = s => /^\s*WIRED\b/.test(String(s || ''))
const verdict = r => {
  if (!validReview(r)) return { valid: false, pass: false, reason: 'no valid review (nothing returned, malformed, no wiring check, or no renders looked at): counted as a FAILED review, never a pass' }
  const blocking = r.fixes.filter(f => !f || f.severity !== 'polish')   // an unmarked fix counts as blocking
  const other = Math.min(r.craft, r.sync, r.story)
  const score = Math.round(((2 * r.owner + r.craft + r.sync + r.story) / 5) * 10) / 10
  const pass = blocking.length === 0 && r.owner >= RULE.min_owner && other >= RULE.min_other && gateOk(r.checks.lyric_gate) && wiredOk(r.checks.wired)
  return { valid: true, pass, score, owner: r.owner, craft: r.craft, sync: r.sync, story: r.story, blocking: blocking.length, polish: r.fixes.length - blocking.length,
    lyric_gate: r.checks.lyric_gate, wired: r.checks.wired, reviewer_said_pass: !!r.pass,
    reason: pass ? 'no blocking fix left' : [blocking.length ? `${blocking.length} blocking fix(es)` : '', r.owner < RULE.min_owner ? `owner ${r.owner} < ${RULE.min_owner}` : '', other < RULE.min_other ? `lowest other lens ${other} < ${RULE.min_other}` : '', gateOk(r.checks.lyric_gate) ? '' : `lyric gate not N/N (${r.checks.lyric_gate})`, wiredOk(r.checks.wired) ? '' : `not wired (${String(r.checks.wired).slice(0, 120)})`].filter(Boolean).join('; ') }
}

const review = (notes, c, round, retry) => agent(`You are the art director (review round ${round}${retry ? ', second attempt — the first review returned nothing usable' : ''}) of chapter ${c.id} "${c.name || c.id}" (${c.t0}–${c.t1} s, file ${CHDIR}/${c.file}) of "${TITLE}".
${BAR}
${READ(c)}
${CMDS(c)}
The animator's notes: ${notes || '(none)'}
First run the wiring check and the page boot: a chapter that is NOT WIRED is not on screen at all (the default renderer draws its shots), so judging its renders would judge the wrong code — report it as a blocking fix and score what is on screen.
Render and LOOK yourself — your opinion of code you have not seen rendered is worthless: the lyric gate; contact sheets of at least ${SHEETS} times (every shot's first, middle and last frame, every lyric line, every hit moment, every transition middle) and full-size stills of the 5 most important moments; a 12 fps render of the range checked against analysis/hits.json (moves and cuts on the sounds, nothing drifting). Read every image. Compare each shot with its storyboard entry and the bar above.
Judge every shot: the explaining graphic (shows what the words mean, in one glance); lyric timing and legibility on a phone; beat sync; density (>= 3 layers); the 2.5D treatment (layered, alive, different from its neighbours); transitions (motivated, never amateurish or repeated); colour (the footage keeps its colour); type never over a face; on-model lead; performance (ms/frame <= ${MSF}).
Score 0–10: owner (counts double), craft, sync, story. ${SEVERITY} At most ${MAX_FIX} fixes, the most important first, each concrete (shot, time, problem, fix). Fill checks with the exact lyric gate line, the exact wiring line and how many frames you looked at. If a render command fails, say so in checks.lyric_gate and score only what you could see — never invent numbers. Do not edit any file.`,
  { label: `review${round}${retry ? 'b' : ''}:${c.id}`, phase: round === 1 ? 'Review' : 'Review 2', schema: REVIEW, effort: 'high' })
const reviewRound = async (notes, c, round) => {
  const r = await review(notes, c, round, false)
  if (validReview(r)) return r
  log(`review${round}:${c.id} FAILED: ${r ? 'malformed, no wiring check, or no renders looked at' : 'returned nothing (usage limit?)'}; retrying once`)
  const r2 = await review(notes, c, round, true)
  if (!validReview(r2)) log(`review${round}b:${c.id} FAILED: ${r2 ? 'malformed, no wiring check, or no renders looked at' : 'returned nothing'} — chapter ${c.id} round ${round} counts as UNREVIEWED`)
  return validReview(r2) ? r2 : null
}
const fix = (rev, c, round) => agent(`You are the animator of chapter ${c.id} "${c.name || c.id}" (${c.t0}–${c.t1} s) of "${TITLE}".
${BAR}
${READ(c)}
${YOURFILE(c)}
${RULES}
${CMDS(c)}
The art director scored it owner ${rev.owner} (counts double) · craft ${rev.craft} · sync ${rev.sync} · story ${rev.story} and asks for these fixes (most important first):
${JSON.stringify(rev.fixes, null, 1)}
Apply every BLOCKING fix first, then the polish fixes (use judgement where one conflicts with DECISIONS.md or the device library — ${OWNER}'s decisions win). Re-verify: the wiring check (WIRED), the lyric gate (N/N), contact sheets and full-size stills of every moment you changed (Read them), the sync check on changed moves, the history check on 3 pairs, flashes per second. Return what changed per fix, the checks, and anything for other owners (shared files, assets to re-generate).`,
  { label: `fix${round}:${c.id}`, phase: round === 1 ? 'Fix' : 'Review 2', effort: 'high' })
const text = x => typeof x === 'string' ? x : JSON.stringify(x)

// ---- Setup: wire the chapter files (unless the runner did) and, for a refit, rebuild the edit once
const SETUP = { type: 'object', properties: {
  wired: { type: 'boolean', description: 'true when every chapter file exists and engine/ch/_index.js lists it' },
  wire_output: { type: 'string', description: 'what the wire command printed (or what you did by hand)' },
  edit_rebuilt: { type: 'boolean', description: 'refit: true only if edit edl and edit export both succeeded; build: false' },
  info: { type: 'string', description: 'the first line render info printed' },
  page_errors: { type: 'array', items: { type: 'string' } },
  problems: { type: 'array', items: { type: 'string' } } },
  required: ['wired', 'wire_output', 'edit_rebuilt', 'info', 'page_errors', 'problems'] }
const CHLIST = JSON.stringify(CH.map(c => ({ id: c.id, file: c.file, name: c.name || null, t0: c.t0, t1: c.t1, shots: c.shots })))
const setupPrompt = retry => `You prepare the project of the lyric music video "${TITLE}" for its chapter animators${retry ? ' (second attempt: the first returned nothing usable)' : ''}. Do exactly these steps, in order, and nothing else — write no chapter code and edit no other file.
1. Wire the chapter files${A.wired ? ' (the runner already did; the command is idempotent, run it anyway and report its output)' : ''}. Write this JSON to ${SCR}/_setup/chapters.json: ${CHLIST}
   Then run ${RUNNER ? q(`${RUNNER} wire "${P}" --chapters "${SCR}/_setup/chapters.json"`) : 'the wiring by hand (no toolkit_dir was given)'}: it creates each missing ${CHDIR}/<file> as a stub and lists every chapter file in ${CHDIR}/_index.js — the ONLY chapter file the engine loads. ${RUNNER ? 'Only if that command cannot run, do it' : 'Do it'} by hand: create each missing chapter file with one comment line, and make ${CHDIR}/_index.js load every chapter file in time order, keeping the files it already lists, e.g. ['01_a.js', '02_b.js'].forEach(f => document.write('<script src="ch/' + f + '"><\\/script>'));
2. ${MODE === 'refit' ? `The footage changed: rebuild the edit ONCE for every chapter — ${q(`${EDIT} edl`)}, then ${q(`${EDIT} export`)}. The animators read the result and never rebuild it themselves.` : 'Skip (build mode: the edit is not rebuilt).'}
3. Run ${q(`${R} info`)} and copy its first line; list every PAGE ERROR it reports.
Return: wired, the wire command's output, edit_rebuilt, the info line, the page errors and any problems.`
if (!A.wired || MODE === 'refit') {
  phase('Setup')
  let setup = await agent(setupPrompt(false), { label: 'setup', phase: 'Setup', schema: SETUP, effort: 'low' })
  if (!setup) { log('setup FAILED: returned nothing (usage limit?); retrying once'); setup = await agent(setupPrompt(true), { label: 'setup:2', phase: 'Setup', schema: SETUP, effort: 'low' }) }
  const why = !setup ? 'the setup agent returned nothing twice (usage limit?)' : !setup.wired ? `the chapter files are not wired (${String(setup.wire_output).slice(0, 200)})`
    : (MODE === 'refit' && !setup.edit_rebuilt) ? `the edit was not rebuilt for the refit (${(setup.problems || []).join('; ').slice(0, 200)})` : null
  if (why) return { ok: false, all_pass: false, mode: MODE, error: `setup failed — ${why}. Fix the cause and resume the run; nothing was animated.`, setup, failed: CH.map(c => c.id), chapters: [] }
  if ((setup.page_errors || []).length) log(`setup: render info reports page errors (an animator must clear any in its own file; shared ones are reported): ${setup.page_errors.slice(0, 3).join(' | ')}`)
}

// ---- per chapter: animate -> review -> fix -> review 2 -> fix 2, at most PAR chapters in flight
const slots = n => {
  let busy = 0; const queue = []
  const pump = () => { while (busy < n && queue.length) { const [fn, ok, ko] = queue.shift(); busy++; fn().then(ok, ko).finally(() => { busy--; pump() }) } }
  return fn => new Promise((ok, ko) => { queue.push([fn, ok, ko]); pump() })
}
const chain = async c => {
  const s = { notes: await animate(c) }
  if (s.notes == null) return { ...s, animate_failed: true, v1: verdict(null) }
  s.r1 = await reviewRound(s.notes, c, 1); s.v1 = verdict(s.r1)
  if (s.v1.pass) return s
  if (s.v1.valid) { s.fix1_tried = true; s.f1 = await fix(s.r1, c, 1) }
  if (ROUNDS < 2) return s
  s.round2 = true
  s.r2 = await reviewRound(text(s.f1 ?? s.notes), c, 2); s.v2 = verdict(s.r2)
  if (!s.v2.valid || s.v2.pass) return s
  s.fix2_tried = true; s.f2 = await fix(s.r2, c, 2)
  return s
}
phase('Animate')
log(`${CH.length} chapter(s), at most ${PAR} in flight, --workers ${W} per render (${MODE}, ${ROUNDS} review round(s))`)
const slot = slots(PAR)
const results = await Promise.all(CH.map(c => slot(() => chain(c).catch(e => ({ crashed: String((e && e.message) || e).slice(0, 300) })))))

const chapters = CH.map((c, i) => {
  const s = results[i] || {}
  const last = s.v2 && s.v2.valid ? { v: s.v2, r: s.r2, round: 2, fixed: s.f2 != null } : (s.v1 && s.v1.valid ? { v: s.v1, r: s.r1, round: 1, fixed: s.f1 != null } : null)
  let status
  if (s.animate_failed || s.notes == null) status = 'animate-failed'
  else if (!last) status = 'unreviewed'
  else if (last.v.pass) status = 'pass'
  else if (last.fixed) status = 'fixed-not-rereviewed'
  else status = 'fail'
  const incomplete_why = s.crashed ? `the chapter's chain crashed: ${s.crashed}`
    : (s.round2 && s.fix1_tried && !(s.v2 && s.v2.valid)) ? 'fixes were applied but the round-2 review returned nothing'
      : ((ROUNDS < 2 && s.fix1_tried && s.f1 == null) || (s.fix2_tried && s.f2 == null)) ? 'the last fix returned nothing' : null
  const openFixes = last ? last.r.fixes : (c.fixes || [])
  log(`${c.id} ${status}${last ? ` score ${last.v.score} (owner ${last.v.owner}) blocking ${last.v.blocking} — ${last.v.reason}` : ''}${incomplete_why ? ` — INCOMPLETE: ${incomplete_why}` : ''}`)
  return { chapter: c.id, file: c.file, status, round: last ? last.round : 0, verdict: last ? last.v : verdict(null), wired: last ? last.r.checks.wired : null,
    incomplete: !!incomplete_why, incomplete_why, open_fixes: openFixes,
    open_fixes_note: status === 'fixed-not-rereviewed' ? 'these fixes were applied once and never re-reviewed: carry them as "fixes" into a refit run' : undefined,
    review1: s.r1 ?? null, review2: s.r2 ?? null, animator_notes: s.notes ?? null, fix1: s.f1 ?? null, fix2: s.f2 ?? null }
})
const failed = chapters.filter(c => c.status === 'unreviewed' || c.status === 'animate-failed').map(c => c.chapter)
const incomplete = chapters.filter(c => c.incomplete && !failed.includes(c.chapter)).map(c => c.chapter)
const errs = [failed.length ? `no valid review for: ${failed.join(', ')}` : '', incomplete.length ? `unfinished (fixes never re-reviewed, or a fix returned nothing): ${incomplete.join(', ')}` : ''].filter(Boolean)
return { ok: errs.length === 0, all_pass: chapters.every(c => c.status === 'pass'), pass_rule: { ...RULE, blocking: 0, lyric_gate: 'N/N', wired: true }, mode: MODE,
  failed, incomplete, error: errs.length ? `${errs.join('; ')} (null reviews are failures, never passes: resume the run, or carry open_fixes into a refit run)` : null, chapters }

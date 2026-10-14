#!/usr/bin/env node
/**
 * deleg.mjs — Claudia delegation runner (Director tier).
 *
 * Hands ONE job folder to the user's OWN local agent subscription — Claude Code (`claude -p`, Workflow tool allowed),
 * Codex (`codex exec --json`), Muse Code (`muse exec --json`) or Gemini CLI (`gemini -p -o stream-json`) — on the user's
 * computer OR on the bot's own computer (engines installed by `slop agents install` into $SLOP_HOME/bin, found
 * first) — runs it in a detached supervisor so it outlives the
 * shell that started it, and normalises the engine's event stream into small files that a weaker orchestrator (the
 * Claudia Grok Bot) can poll with short commands. Node 18.17+ (20+ recommended). No dependencies. Windows/macOS/Linux.
 *
 *   node deleg.mjs new    <jobdir|auto> --brief <name> [--project P] [--engine claude|codex|muse|gemini] [--workflow W]
 *                          [--set KEY=VALUE ...] [--vars vars.json] [--args args.json] [--spec spec.json] [--force]
 *   node deleg.mjs run    <jobdir|id.job.json> [GATES]     start if needed, then follow until the job ends.
 *                                                           Run it as ONE background local shell = one approval card.
 *   node deleg.mjs start  <jobdir> [GATES] [--fresh]
 *   node deleg.mjs status <jobdir>
 *   node deleg.mjs wait   <jobdir> [secs=25]                print new progress lines, then "STATUS {json}"
 *   node deleg.mjs stop   <jobdir> [--force]
 *   node deleg.mjs resume <jobdir> [prompt-file] [GATES]
 *   node deleg.mjs list   [jobs-root|project-dir]
 *   node deleg.mjs wire   <project> --chapters <job.json|args.json|chapters.json|JSON> [--check]
 *   node deleg.mjs wire   <project> --check --file <chapter.js> [--shots s001,s002]
 *   node deleg.mjs pack   <jobdir>                         (re)build <jobdir>/outbox.tgz (+ .000/.001 parts > 95 MiB)
 *   node deleg.mjs unpack <archive.tgz|archive.tgz.000> <destdir> [--force]
 *   node deleg.mjs templates | doctor [--render] | selftest [--keep] | preflight <engine> [--workflow] [--dir D] [--job D]
 *   node deleg.mjs version | help
 *   GATES (only when the job.json asks for them; the approval card then shows them): --allow-api-billing
 *                          --allow-spend  --allow-raw  --pass-env NAME[,NAME]
 *
 * Every command prints ONE JSON line ({"ok":true,...} or {"ok":false,"error":...,"fix":...}); `wait` and `run` print
 * compact progress lines and always end with "STATUS {json}". Exit code 0 = ok/done/running, 1 = error/failed/stopped/lost.
 *
 * Job folder contract (see runner/README.md): job.json (engine config), BRIEF.md (the prompt), wf/<name>.js (Claude
 * workflow script — inside the job dir so a resume can read it), outbox/ (the ONLY collected output), status.json
 * (normalised: state, engine, started, last_event, tokens, result_text, error + detail), progress.log (one line per
 * event, <= 240 chars), raw-N.jsonl (lossless engine stdout of attempt N), stderr-N.log, RUNS.md, runs/ (workflow run
 * outputs), outbox.tgz (packed at the end for one CopyToBox).
 *
 * Port of the tested reference runner (research 11-gap-2 §8.8). Intentional changes:
 *  - Claude: parse until PROCESS EXIT; a Workflow's result arrives as a SECOND `result` after the first one. The first
 *    result is never "done". Workflow task outputs are copied into runs/ and scanned for dead agents ("[x] failed:",
 *    workflowProgress state "error") -> warnings, because a run that says "completed" can hide null agents.
 *  - Fail fast (kill, state failed, clear fix) when the brief needs the Workflow tool but `init.tools` lacks it (Claude
 *    Pro default), or when Claude reports it would bill an API key instead of the subscription.
 *  - API-key env vars are stripped (ANTHROPIC_*, OPENAI_API_KEY, CODEX_API_KEY, META_API_KEY, ...) unless
 *    --allow-api-billing / "allow_api_billing": true; the toolkit's own secrets (OPENROUTER_API_KEY, ...) are never
 *    inherited unless listed in "pass_env" (hive rule: workers never get the orchestrator's credentials).
 *  - `stop` writes a .stop marker file instead of a status field (the reference lost the flag when the supervisor
 *    re-wrote status.json); spawn errors (engine not found) are caught; utf-8 is decoded across chunk boundaries.
 *  - `new` fills brief templates ({{KEY}} / {{KEY|default}}, string replace only — never format()); runtime tokens
 *    ({{JOB_DIR}} {{OUTBOX}} {{PROJECT_DIR}} {{TOOLKIT_DIR}} {{SLOP}} {{WORKFLOW_PATH}} {{WORKFLOW_ARGS}}) are filled on the
 *    machine that RUNS the job, so a job.json built on the bot's box works unchanged on the user's computer.
 *  - Soft concurrency cap per jobs folder (max_parallel, default 3), timeout, optional usage guard, outbox packing,
 *    `collect` (copy project files the job changed into the outbox), doctor / selftest (free) / preflight (tiny).
 *  - GATES (fixer pass): a job.json is written on the bot's computer and only `node deleg.mjs run <file>` is shown on the
 *    approval card, so every field that widens what a job may do needs a matching flag on the command line:
 *    allow_api_billing -> --allow-api-billing · allow_spend -> --allow-spend · pass_env -> --pass-env NAME ·
 *    engine "raw"/argv, engine_bin, env, slop_cmd, add_dirs, codex_config, muse_flags, a permission_mode other than
 *    default/acceptEdits, sandbox danger-full-access, and tools outside the default list -> --allow-raw. Without the flag
 *    the job is refused before anything starts, and the first progress line prints the effective gates.
 *  - `wire` (fixer pass): the engine page loads only <project>/engine/ch/_index.js, so chapter jobs ("wire_chapters")
 *    get a stub file per chapter and a merged _index.js before the engine starts (lock file, merge-safe for jobs side by
 *    side); `wire --check` is the static proof that a chapter file is loaded and registers scenes.
 *  - "requires": ["slop", "render", "ffmpeg"] checks the toolkit runtime on the running machine before the engine starts
 *    (a job whose checks cannot run fails in seconds with the setup fix, not hours later). `doctor` runs the same checks.
 *  - "queue_group": jobs of one group run one at a time per jobs folder (chapter jobs: "render" — only one rendering
 *    workflow at a time; several at once once filled swap and the disk).
 * No engine is ever asked to spend money on paid APIs: Claude's Higgsfield connector is denied unless "allow_spend"
 * (and --allow-spend on the command line).
 *  - Box (kit-out): engines are looked up in $SLOP_HOME/bin first (where `slop agents install` links them; also
 *    $SLOP_HOME/npm/bin and $SLOP_HOME/muse), npm node scripts (codex.js, gemini.js) run through this node. `new`
 *    without --engine uses the engine chosen with `slop agents use ENGINE --for director|review`
 *    ($SLOP_HOME/onboard.json) when the brief's "engines:" line lists it; a brief whose default workflow is Claude's
 *    then runs without it (workflow none: the brief's method B, in sequence). `new` prints engine_from / engine_note.
 *    On the bot's computer at most 2 agent jobs run at once across ALL jobs folders (box-wide slots in
 *    $SLOP_HOME/agents/slots; DELEG_BOX_SLOTS changes it; tiny preflights are exempt), because renders share the box.
 *  - Gemini CLI: `gemini -p "<read the prompt file>" -o stream-json --skip-trust --approval-mode auto_edit` (stream:
 *    init / message / tool_use / tool_result / result{status, stats}; verified schema); a resume starts a new Gemini
 *    session with the continuation prompt; approval_mode "yolo" needs --allow-raw. [U] Headless Gemini drops tools that
 *    would ask for approval, so under auto_edit it reads and writes files but probably cannot run shell commands
 *    (slop, node, ffmpeg): give it write-only work, or name the shell tool in "allowed_tools" (passed as
 *    --allowed-tools; needs --allow-raw). A GEMINI_API_KEY sign-in reaches a job only through pass_env (`new --engine
 *    gemini` adds it when Gemini's chosen sign-in is the key; the run command then needs --pass-env GEMINI_API_KEY).
 *  - Credentials stay with their engine: CLAUDE_CODE_OAUTH_TOKEN (the Claude plan token) reaches only claude jobs, and
 *    the one-time sign-in codes (CLAUDE_LOGIN_CODE, GEMINI_LOGIN_CODE) reach no job.
 */
import { spawn, spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import crypto from 'node:crypto';
import { StringDecoder } from 'node:string_decoder';
import { fileURLToPath } from 'node:url';

const VERSION = '1.1.0';
const WIN = process.platform === 'win32';
const HOME = os.homedir();
const SELF = fileURLToPath(import.meta.url);
const RUNNER_DIR = path.dirname(SELF);
const TOOLKIT_DIR = path.dirname(RUNNER_DIR);
const BRIEFS_DIR = path.join(TOOLKIT_DIR, 'templates', 'briefs');
const WORKFLOWS_DIR = path.join(TOOLKIT_DIR, 'templates', 'workflows');
const FAKE_ENGINE = path.join(RUNNER_DIR, 'fake-engine.mjs');
const ENGINES = ['claude', 'codex', 'muse', 'gemini', 'raw'];
const TERMINAL = new Set(['done', 'failed', 'stopped']);
const ACTIVE = new Set(['queued', 'starting', 'running']);
const RUNTIME_TOKENS = ['JOB_DIR', 'JOB_ID', 'OUTBOX', 'PROJECT_DIR', 'TOOLKIT_DIR', 'SLOP', 'ENGINE', 'WORKFLOW_PATH', 'WORKFLOW_ARGS'];
const PART_BYTES = Number(process.env.DELEG_PART_BYTES) > 0 ? Number(process.env.DELEG_PART_BYTES) : 95 * 1024 * 1024;   // CopyToBox/CopyFromBox refuse files over 100 MiB
const DEFAULT_TIMEOUT_S = 6 * 3600;
const START_GRACE_MS = 20000;                  // a "starting" job whose supervisor has not written its pid yet

// Claude tools a delegated job may use without a prompt (default mode + --permission-prompts none denies the rest).
const CLAUDE_TOOLS = ['Workflow', 'Agent', 'Task', 'Read', 'Write', 'Edit', 'MultiEdit', 'Glob', 'Grep', 'Bash',
  'PowerShell', 'WebSearch', 'WebFetch', 'ToolSearch', 'TodoWrite', 'NotebookEdit', 'Skill'];
const CLAUDE_SPEND_TOOLS = ['mcp__claude_ai_Higgsfield'];   // claude.ai connector that can spend credits
// Env vars that would switch an engine from the user's subscription to pay-per-token API billing.
const BILLING_ENV = ['ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'ANTHROPIC_BASE_URL', 'CLAUDE_CODE_USE_BEDROCK',
  'CLAUDE_CODE_USE_VERTEX', 'OPENAI_API_KEY', 'CODEX_API_KEY', 'OPENAI_BASE_URL', 'META_API_KEY', 'GEMINI_API_KEY', 'GOOGLE_API_KEY'];
// The toolkit's own secrets: a worker never inherits them unless job.json "pass_env" names them.
const SECRET_ENV = ['OPENROUTER_API_KEY', 'HIGGSFIELD_API_KEY', 'HEDRA_API_KEY', 'ARENA_TOKEN'];
// One engine's sign-in token never reaches another vendor's agent (it may run shell commands and read the env).
const ENGINE_SIGNIN_ENV = { CLAUDE_CODE_OAUTH_TOKEN: 'claude' };
// One-time sign-in codes from the secure card: typed into the waiting login only, never handed to a job.
const LOGIN_CODE_ENV = ['CLAUDE_LOGIN_CODE', 'GEMINI_LOGIN_CODE'];
// Set by a parent Claude Code session; a child `claude` must not see them (it would attach to the parent).
const PARENT_SESSION_RE = /^(CLAUDECODE|CLAUDE_CODE_(ENTRYPOINT|SESSION_ID|CHILD_SESSION|HOST_SESSION_ID|OAUTH_SCOPES|SDK_HAS_HOST_AUTH_REFRESH|MESSAGING_\w+))$/;

const JOB_KEYS = new Set(['id', 'kind', 'engine', 'title', 'created', 'brief_template', 'brief', 'prompt_file',
  'project_dir', 'cwd', 'workflow', 'workflow_args', 'vars', 'model', 'effort', 'permission_mode', 'allowed_tools',
  'extra_allowed_tools', 'disallowed_tools', 'add_dirs', 'max_turns', 'max_budget_usd', 'sandbox', 'network',
  'codex_config', 'approval_mode', 'muse_flags', 'provider', 'output_schema', 'timeout_s', 'allow_api_billing',
  'allow_spend', 'pass_env', 'env', 'collect', 'max_parallel', 'engine_bin', 'workflows_env', 'stop_above_utilization',
  'argv', 'slop_cmd', 'notes', 'wire_chapters', 'queue_group', 'requires', 'project_name']);
const SAFE_PERMISSION_MODES = new Set(['default', 'acceptEdits', 'plan']);
const REQUIRES = new Set(['slop', 'render', 'ffmpeg']);
const CH_FILE_RE = /^[A-Za-z0-9][\w.-]*\.js$/;

// ---------------------------------------------------------------------------------------------------------------- utils
class UserError extends Error { constructor(msg, fix) { super(msg); this.fix = fix || null; } }
const now = () => new Date().toISOString();
const fwd = p => String(p).replace(/\\/g, '/');
const round = (x, n = 4) => Math.round(x * 10 ** n) / 10 ** n;
const sleep = ms => new Promise(r => setTimeout(r, ms));
function sleepSync(ms) { Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms); }
function print(obj) { process.stdout.write(JSON.stringify(obj) + '\n'); }
function readText(f) { try { return fs.readFileSync(f, 'utf8'); } catch { return null; } }
function readJSON(f, dflt = null) {
  const s = readText(f); if (s == null) return dflt;
  try { return JSON.parse(s.replace(/^\uFEFF/, '')); } catch { return dflt; }
}
function readJSONStrict(f, what) {
  const s = readText(f);
  if (s == null) throw new UserError(`${what} not found: ${fwd(f)}`, 'Check the path (use absolute paths with forward slashes).');
  try { return JSON.parse(s.replace(/^\uFEFF/, '')); } catch (e) {
    throw new UserError(`${what} is not valid JSON (${e.message})`,
      'Fix the JSON. On Windows write paths with forward slashes (C:/Users/...): a single backslash is an invalid JSON escape.');
  }
}
function writeJSON(f, obj) {   // atomic: tmp + rename, retried (Windows refuses a rename while a reader has the file open)
  const tmp = `${f}.${process.pid}.${crypto.randomBytes(3).toString('hex')}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(obj, null, 1) + '\n');
  for (let i = 0; ; i++) {
    try { fs.renameSync(tmp, f); return; } catch (e) {
      if (i >= 60 || !['EPERM', 'EBUSY', 'EACCES'].includes(e.code)) { try { fs.unlinkSync(tmp); } catch {} throw e; }
      sleepSync(25);
    }
  }
}
function alive(pid) { if (!pid) return false; try { process.kill(pid, 0); return true; } catch (e) { return e.code === 'EPERM'; } }
function warn(st, msg) { const w = (st.warnings ||= []); if (!w.includes(msg) && w.length < 40) w.push(msg); }
function parseArgs(argv, verb) {
  const BOOL = new Set(['force', 'allow-api-billing', 'allow-spend', 'allow-raw', 'fresh', 'keep', 'json', 'help', 'check', 'render']);
  if (verb === 'preflight') BOOL.add('workflow');   // `new --workflow W` takes a value; `preflight --workflow` is a switch
  const pos = [], opt = { set: [], 'pass-env': [] };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a.startsWith('--') && a.length > 2) {
      const eq = a.indexOf('=');
      let k, v;
      if (eq > 0) { k = a.slice(2, eq); v = a.slice(eq + 1); }
      else { k = a.slice(2); const nx = argv[i + 1]; if (BOOL.has(k) || nx === undefined || (nx.startsWith('--') && nx.length > 2)) v = true; else { v = nx; i++; } }
      if (k === 'set') opt.set.push(String(v));
      else if (k === 'pass-env') { if (v !== true) opt['pass-env'].push(...String(v).split(',').map(s => s.trim()).filter(Boolean)); }
      else opt[k] = v;
    } else pos.push(a);
  }
  return { pos, opt };
}
// The gates the command line grants (see the header): what the user saw on the approval card.
function grantsFrom(opt) {
  return { allow_api_billing: !!opt['allow-api-billing'], allow_spend: !!opt['allow-spend'], allow_raw: !!opt['allow-raw'],
    pass_env: [...new Set(opt['pass-env'] || [])] };
}
function slug(s) { return String(s || 'job').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 40) || 'job'; }
function newJobId(name) {
  const d = new Date(); const ymd = `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, '0')}${String(d.getDate()).padStart(2, '0')}`;
  return `${ymd}-${crypto.randomBytes(2).toString('hex')}-${slug(name)}`;
}
function copyAny(src, dst) {
  const s = fs.statSync(src);
  if (s.isDirectory()) { fs.mkdirSync(dst, { recursive: true }); for (const f of fs.readdirSync(src)) copyAny(path.join(src, f), path.join(dst, f)); }
  else { fs.mkdirSync(path.dirname(dst), { recursive: true }); fs.copyFileSync(src, dst); }
}
function walkFiles(dir, out = [], base = dir) {
  let ents = []; try { ents = fs.readdirSync(dir, { withFileTypes: true }); } catch { return out; }
  for (const e of ents) { const p = path.join(dir, e.name); if (e.isDirectory()) walkFiles(p, out, base); else out.push({ rel: fwd(path.relative(base, p)), bytes: (() => { try { return fs.statSync(p).size; } catch { return 0; } })() }); }
  return out;
}
function onBox() { return fs.existsSync('/workspace') && process.env.HOME === '/home/box'; }
function projectsRoot() {
  if (process.env.SLOP_PROJECTS) return path.resolve(process.env.SLOP_PROJECTS.replace(/^~(?=$|[\\/])/, HOME));
  return onBox() ? '/workspace/slop/projects' : path.join(HOME, 'slop', 'projects');
}
function slopHome() {
  if (process.env.SLOP_HOME) return path.resolve(process.env.SLOP_HOME.replace(/^~(?=$|[\\/])/, HOME));
  return onBox() ? '/workspace/.claudia' : path.join(HOME, '.claudia');
}

// ------------------------------------------------------------------------------------------------------ job folder paths
function jobPaths(jobdir) {
  const J = path.resolve(String(jobdir));
  return { J, job: path.join(J, 'job.json'), status: path.join(J, 'status.json'), progress: path.join(J, 'progress.log'),
    outbox: path.join(J, 'outbox'), wf: path.join(J, 'wf'), runs: path.join(J, 'runs'), stop: path.join(J, '.stop'),
    runsMd: path.join(J, 'RUNS.md') };
}
// Move an earlier run's files into <job>/history/<n>/ so the folder can run a new job.json from scratch.
const RUN_FILES = /^(status\.json|progress\.log|raw-\d+\.jsonl|stderr-\d+\.log|prompt-\d+\.md|resume-\d+\.md|outbox|outbox\.tgz(\.\d{3})?|runs|RUNS\.md|wf|\.cursor-\w+|\.stop|last-message\.txt|BRIEF\.md)$/;
function archiveRun(J) {
  const H = path.join(J, 'history'); let n = 1;
  while (fs.existsSync(path.join(H, String(n)))) n++;
  const dest = path.join(H, String(n)); let moved = 0;
  for (const f of fs.readdirSync(J)) {
    if (!RUN_FILES.test(f)) continue;
    fs.mkdirSync(dest, { recursive: true });
    fs.renameSync(path.join(J, f), path.join(dest, f)); moved++;
  }
  return moved ? fwd(dest) : null;
}
// A job can arrive as ONE file copied next to the jobs ("<jobs>/<id>.job.json", one CopyFromBox into an existing folder):
// it is adopted into "<jobs>/<id>/job.json" (the brief is embedded in it; the runner rebuilds BRIEF.md and wf/). A file
// copied anywhere else (e.g. the home folder) goes to <projects>/<project_name>/jobs/<id>/ when that project exists here.
function adoptJobFile(arg) {
  const f = path.resolve(String(arg));
  let st; try { st = fs.statSync(f); } catch { return arg; }
  if (!st.isFile() || !/\.json$/i.test(f)) return arg;
  if (path.basename(f) === 'job.json') return path.dirname(f);
  const job = readJSONStrict(f, 'job file');
  const id = job.id && /^[\w.-]+$/.test(job.id) ? job.id : slug(path.basename(f).replace(/(\.job)?\.json$/i, ''));
  let jobsDir = path.dirname(f);
  const inProject = path.basename(jobsDir) === 'jobs' && fs.existsSync(path.join(jobsDir, '..', 'project.json'));
  if (!inProject && job.project_name && /^[\w.-]+$/.test(job.project_name)) {
    const pj = path.join(projectsRoot(), job.project_name);
    if (fs.existsSync(path.join(pj, 'project.json'))) jobsDir = path.join(pj, 'jobs');
  }
  const J = path.join(jobsDir, id);
  const p = jobPaths(J);
  if (fs.existsSync(p.job)) {
    if (readText(p.job) === readText(f)) return J;
    if (fs.existsSync(p.status)) {   // a DIFFERENT job.json with the same id (e.g. `new --force` on the box): a new run
      const old = effectiveStatus(p);
      if (ACTIVE.has(old.state) || old.state === 'lost')
        throw new UserError(`job ${id} is ${old.state} in ${fwd(J)} and a different job.json with the same id arrived`,
          old.state === 'lost' ? `Resume or finish the old run first (node deleg.mjs resume "${fwd(J)}"), or give the new job another id.` : `Wait for it to end, or stop it (node deleg.mjs stop "${fwd(J)}"), then run the new file again.`);
      archiveRun(J);
    }
  }
  fs.mkdirSync(J, { recursive: true });
  fs.copyFileSync(f, p.job);
  if (!fs.existsSync(p.status) && typeof job.brief === 'string' && job.brief.trim()) { try { fs.rmSync(path.join(J, path.basename(String(job.prompt_file || 'BRIEF.md'))), { force: true }); } catch {} }   // rebuild from the new job.json
  return J;
}
function requireJobDir(arg, verb) {
  if (!arg) throw new UserError(`${verb} needs a job folder`, `node deleg.mjs ${verb} <jobdir>   (the folder that holds job.json, or a copied <id>.job.json file)`);
  if (['run', 'start', 'status', 'wait'].includes(verb)) arg = adoptJobFile(arg);
  const p = jobPaths(arg);
  if (!fs.existsSync(p.job)) throw new UserError(`no job.json in ${fwd(p.J)}`, 'Create the job first: node deleg.mjs new <jobdir> --brief <name> (see: node deleg.mjs templates)');
  return p;
}
function validateJob(job, p) {
  if (!job || typeof job !== 'object' || Array.isArray(job)) throw new UserError('job.json must be a JSON object', null);
  const errs = [];
  if (!ENGINES.includes(job.engine)) errs.push(`"engine" must be one of ${ENGINES.join('|')} (got ${JSON.stringify(job.engine)})`);
  if (job.engine === 'raw' && !(Array.isArray(job.argv) && job.argv.length)) errs.push('engine "raw" needs "argv": ["cmd", "arg", ...]');
  for (const k of ['add_dirs', 'allowed_tools', 'extra_allowed_tools', 'disallowed_tools', 'muse_flags', 'collect', 'pass_env', 'codex_config', 'requires'])
    if (job[k] != null && !Array.isArray(job[k])) errs.push(`"${k}" must be a list`);
  if (Array.isArray(job.requires)) { const bad = job.requires.filter(r => !REQUIRES.has(r)); if (bad.length) errs.push(`"requires" may hold ${[...REQUIRES].join(', ')} (got ${bad.join(', ')})`); }
  if (job.queue_group != null && typeof job.queue_group !== 'string') errs.push('"queue_group" must be a string (e.g. "render") or null');
  for (const k of ['timeout_s', 'max_turns', 'max_budget_usd', 'max_parallel', 'stop_above_utilization'])
    if (job[k] != null && (typeof job[k] !== 'number' || !(job[k] > 0))) errs.push(`"${k}" must be a positive number`);
  for (const k of ['workflow_args', 'env', 'vars'])
    if (job[k] != null && (typeof job[k] !== 'object' || Array.isArray(job[k]))) errs.push(`"${k}" must be an object`);
  if (job.sandbox && !['read-only', 'workspace-write', 'danger-full-access'].includes(job.sandbox)) errs.push('"sandbox" must be read-only|workspace-write|danger-full-access');
  if (job.engine_bin != null && !(typeof job.engine_bin === 'string' || (Array.isArray(job.engine_bin) && job.engine_bin.length))) errs.push('"engine_bin" must be a path or a non-empty list');
  if (errs.length) throw new UserError(`job.json is invalid: ${errs.join('; ')}`, `Edit ${fwd(p.job)} (fields: runner/README.md, "job.json").`);
  return Object.keys(job).filter(k => !JOB_KEYS.has(k));
}
function loadJob(p) { const job = readJSONStrict(p.job, 'job.json'); const unknown = validateJob(job, p); return { job, unknown }; }
function resolveProjectDir(job, J) {
  const guess = path.resolve(J, '..', '..');
  const guessOk = fs.existsSync(path.join(guess, 'project.json'));
  if (job.project_dir) {
    const pd = path.resolve(J, String(job.project_dir));
    if (fs.existsSync(pd)) return pd;
    if (guessOk) return guess;   // e.g. an absolute path from the bot's box that does not exist on this machine
    return pd;
  }
  return guessOk ? guess : null;
}

// ------------------------------------------------------------------------------------------------ executable resolution
function pathSearch(name) {
  // $SLOP_HOME/bin first: `slop agents install` links the engines there (on the bot's computer: /workspace/.claudia/bin)
  const dirs = [path.join(slopHome(), 'bin'), ...(process.env.PATH || '').split(path.delimiter).filter(Boolean)];
  const extra = WIN ? [path.join(HOME, '.local', 'bin'), path.join(process.env.APPDATA || path.join(HOME, 'AppData', 'Roaming'), 'npm'), path.join(slopHome(), 'npm')]
    : [path.join(HOME, '.local', 'bin'), '/usr/local/bin', '/opt/homebrew/bin', path.join(HOME, '.npm-global', 'bin'), path.join(HOME, 'bin'), path.join(slopHome(), 'npm', 'bin')];
  const exts = WIN ? ['.exe', '.cmd', '.bat', ''] : [''];
  const hits = [];
  for (const d of [...dirs, ...extra]) for (const e of exts) {
    const f = path.join(d, name + e);
    try { if (fs.statSync(f).isFile()) hits.push(path.normalize(f)); } catch {}
  }
  if (!hits.length && !WIN) {   // the daemon's PATH can be minimal: ask a login shell
    const r = spawnSync('/bin/sh', ['-lc', `command -v ${name}`], { encoding: 'utf8', timeout: 8000 });
    for (const s of (r.stdout || '').split(/\r?\n/).map(x => x.trim())) if (s && fs.existsSync(s)) hits.push(s);
  }
  return [...new Set(hits)];
}
function shimTarget(shim, re) {   // npm .cmd/.ps1/sh shim -> the JS file it runs (Node >= 18.20 will not spawn .cmd)
  const s = readText(shim); if (!s) return null;
  const m = s.match(re); if (!m) return null;
  let js = m[1].replace(/^(\$basedir[\\/]|%~?dp0%?[\\/]?|%dp0%[\\/]?|\$PSScriptRoot[\\/])/i, path.dirname(shim) + path.sep);
  if (!path.isAbsolute(js)) js = path.join(path.dirname(shim), js);
  js = path.normalize(js);
  return fs.existsSync(js) ? js : null;
}
function nodeScript(f) {   // npm's POSIX bin links point at a .js file: run it with this node (a minimal PATH may lack node)
  let real = f; try { real = fs.realpathSync(f); } catch {}
  return /\.(m?js|cjs)$/i.test(real) ? { cmd: process.execPath, pre: [real], via: 'node-script' } : null;
}
function resolveEngine(job) {
  const e = job.engine;
  let override = job.engine_bin ?? process.env[`DELEG_${String(e).toUpperCase()}_BIN`];
  if (typeof override === 'string' && /^\s*\[/.test(override)) { try { override = JSON.parse(override); } catch {} }   // env form: '["node","/x/cli.js"]'
  if (override) {
    const arr = (Array.isArray(override) ? override : [override]).map(String);
    let [cmd, ...pre] = arr;
    if (cmd === 'node') cmd = process.execPath;
    if (WIN && /\.(cmd|bat|ps1)$/i.test(cmd)) throw new UserError(`engine_bin ${cmd} is a script shim; Node cannot run it without a shell`, 'Point engine_bin at the .exe, or at ["node", "<path to the CLI .js file>"].');
    return { cmd, pre, via: 'engine_bin' };
  }
  if (e === 'raw') return { cmd: null, pre: [], via: 'argv' };
  if (e === 'claude') {
    const hits = pathSearch('claude');
    const exe = WIN ? [path.join(HOME, '.local', 'bin', 'claude.exe'), ...hits.filter(h => /\.exe$/i.test(h))].find(f => fs.existsSync(f))
      : hits[0];
    if (exe) return (!WIN && nodeScript(exe)) || { cmd: exe, pre: [], via: 'path' };
    for (const shim of hits) { const js = shimTarget(shim, /["']?([^"'\s]*@anthropic-ai[\\/]claude-code[\\/]cli\.(?:m?js))["']?/); if (js) return { cmd: process.execPath, pre: [js], via: 'npm-shim' }; }
    throw new UserError('Claude Code (claude) was not found on this computer', 'On the bot\'s computer: slop agents install claude, then slop agents login claude (the user approves a link), then retry. On the user\'s own computer: install Claude Code (https://claude.com/claude-code) and run `claude` once in a terminal to sign in with the Claude plan. Or set "engine_bin" in job.json.');
  }
  if (e === 'codex') {
    const hits = pathSearch('codex');
    if (!WIN) { if (hits[0]) return nodeScript(hits[0]) || { cmd: hits[0], pre: [], via: 'path' }; }
    else {
      for (const shim of hits) {
        if (/\.exe$/i.test(shim)) return { cmd: shim, pre: [], via: 'path' };
        const js = shimTarget(shim, /["']?([^"'\s]*@openai[\\/]codex[\\/]bin[\\/]codex\.js)["']?/);
        if (js) return { cmd: process.execPath, pre: [js], via: 'npm-shim' };
      }
    }
    throw new UserError('Codex CLI (codex) was not found on this computer', 'On the bot\'s computer: slop agents install codex, then slop agents login codex (the user enters a code at a link), then retry. On the user\'s own computer: npm i -g @openai/codex and run `codex login` once in a terminal ("Sign in with ChatGPT"). Or set "engine_bin" in job.json.');
  }
  if (e === 'muse') {
    if (WIN) {   // call the versioned binary, not the muse.cmd launcher: cmd quoting mangles " & | % ^ < > in prompts
      const dir = path.join(process.env.LOCALAPPDATA || path.join(HOME, 'AppData', 'Local'), 'Programs', 'muse');
      const ver = (readText(path.join(dir, '.muse-version')) || '').trim();
      let exe = ver ? path.join(dir, `muse-bin-${ver}.exe`) : null;
      if (!exe || !fs.existsSync(exe)) {
        let c = []; try { c = fs.readdirSync(dir).filter(f => /^muse-bin-.*\.exe$/i.test(f)).sort(); } catch {}
        exe = c.length ? path.join(dir, c[c.length - 1]) : null;
      }
      if (exe) return { cmd: exe, pre: [], via: 'muse-bin' };
    } else {
      const f = [path.join(slopHome(), 'bin', 'muse'), path.join(slopHome(), 'muse', 'muse'), path.join(HOME, '.local', 'bin', 'muse'), ...pathSearch('muse')].find(x => x && fs.existsSync(x));
      if (f) return { cmd: f, pre: [], via: 'path' };
    }
    throw new UserError('Muse Code was not found on this computer', 'Install Muse Code from dev.meta.ai (on the bot\'s computer: slop agents install muse), sign in once (slop agents login muse), then retry. Or use engine "claude" or "codex".');
  }
  if (e === 'gemini') {
    const hits = pathSearch('gemini');
    for (const h of hits) {
      if (!WIN) return nodeScript(h) || { cmd: h, pre: [], via: 'path' };
      if (/\.exe$/i.test(h)) return { cmd: h, pre: [], via: 'path' };
      const js = shimTarget(h, /["']?([^"'\s]*@google[\\/]gemini-cli[\\/](?:bundle|dist)[\\/][^"'\s]*\.m?js)["']?/);
      if (js) return { cmd: process.execPath, pre: [js], via: 'npm-shim' };
    }
    throw new UserError('Gemini CLI (gemini) was not found on this computer', 'Install it (npm i -g @google/gemini-cli, Node 20+; on the bot\'s computer: slop agents install gemini), sign in once, then retry. Or set "engine_bin" in job.json.');
  }
  throw new UserError(`unknown engine ${e}`, `Use one of ${ENGINES.join('|')}.`);
}
function resolveSlop(job) {
  if (job.slop_cmd) return { cmd: String(job.slop_cmd), pythonpath: false };
  if (process.env.SLOP_CMD) return { cmd: process.env.SLOP_CMD, pythonpath: false };
  if (pathSearch('slop').some(f => !WIN || /\.(exe|cmd|bat)$/i.test(f))) return { cmd: 'slop', pythonpath: false };
  const venvPy = WIN ? path.join(slopHome(), 'venv', 'Scripts', 'python.exe') : path.join(slopHome(), 'venv', 'bin', 'python');
  if (fs.existsSync(venvPy)) return { cmd: `"${fwd(venvPy)}" -m slop`, pythonpath: true };
  return { cmd: WIN ? 'python -m slop' : 'python3 -m slop', pythonpath: true };
}

// ------------------------------------------------------------------------------------------------- templates & filling
function fmtVar(v) {
  if (typeof v === 'string') return v;
  if (typeof v === 'number' || typeof v === 'boolean') return String(v);
  if (Array.isArray(v) && v.every(x => typeof x !== 'object' || x === null)) return v.join(', ');
  return JSON.stringify(v);
}
// {{KEY}} or {{KEY|default}}; plain string replacement (prompts contain literal JSON braces: never use a format()).
function fill(text, vars, keep = new Set()) {
  const missing = new Set();
  const out = text.replace(/\{\{([A-Z][A-Z0-9_]*)(?:\|([^}]*))?\}\}/g, (m, k, dflt) => {
    if (keep.has(k)) return m;
    const v = vars[k];
    if (v !== undefined && v !== null && !(typeof v === 'string' && v === '') && !(Array.isArray(v) && !v.length)) return fmtVar(v);
    if (dflt !== undefined) return dflt;
    missing.add(k); return m;
  });
  return { text: out, missing: [...missing] };
}
function fillDeep(v, vars) {
  if (typeof v === 'string') return fill(v, vars).text;
  if (Array.isArray(v)) return v.map(x => fillDeep(x, vars));
  if (v && typeof v === 'object') return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, fillDeep(x, vars)]));
  return v;
}
function parseTemplate(file) {
  const raw = fs.readFileSync(file, 'utf8').replace(/^\uFEFF/, '');
  const meta = { name: path.basename(file).replace(/\.md$/, ''), summary: '', engines: '', defaults: {}, vars: {} };
  let body = raw;
  const m = raw.match(/^<!--([\s\S]*?)-->\s*/);
  if (m) {
    body = raw.slice(m[0].length);
    let inVars = false;
    for (const l of m[1].split(/\r?\n/)) {
      let mm;
      if ((mm = l.match(/^\s*slop-brief:\s*(\S+)/))) { meta.name = mm[1]; inVars = false; }
      else if ((mm = l.match(/^\s*summary:\s*(.*)$/))) { meta.summary = mm[1].trim(); inVars = false; }
      else if ((mm = l.match(/^\s*engines:\s*(.*)$/))) { meta.engines = mm[1].trim(); inVars = false; }
      else if ((mm = l.match(/^\s*defaults:\s*(\{.*\})\s*$/))) { meta.defaults = JSON.parse(mm[1]); inVars = false; }
      else if (/^\s*vars:\s*$/.test(l)) inVars = true;
      else if (inVars && (mm = l.match(/^\s+([A-Z][A-Z0-9_]*):\s*(.*)$/))) meta.vars[mm[1]] = mm[2].trim();
      else if (/^\S/.test(l)) inVars = false;
    }
  }
  return { meta, body };
}
function listBriefs() { try { return fs.readdirSync(BRIEFS_DIR).filter(f => f.endsWith('.md')).map(f => f.slice(0, -3)).sort(); } catch { return []; } }
function listWorkflows() { try { return fs.readdirSync(WORKFLOWS_DIR).filter(f => f.endsWith('.js')).map(f => f.slice(0, -3)).sort(); } catch { return []; } }
function resolveBrief(name) {
  const n = String(name);
  if (fs.existsSync(n) && fs.statSync(n).isFile()) return path.resolve(n);
  const f = path.join(BRIEFS_DIR, n.endsWith('.md') ? n : `${n}.md`);
  if (fs.existsSync(f)) return f;
  throw new UserError(`brief template "${n}" not found`, `Available: ${listBriefs().join(', ') || '(none)'} — or pass a path to a .md file.`);
}
function resolveWorkflow(name) {
  const n = String(name);
  if (fs.existsSync(n) && fs.statSync(n).isFile()) return path.resolve(n);
  const f = path.join(WORKFLOWS_DIR, n.endsWith('.js') ? n : `${n}.js`);
  if (fs.existsSync(f)) return f;
  throw new UserError(`workflow "${n}" not found`, `Available: ${listWorkflows().join(', ') || '(none)'} — or pass a path to a .js file.`);
}
function workflowDoc(file) {
  const src = fs.readFileSync(file, 'utf8');
  const name = (src.match(/name:\s*'([^']+)'/) || [])[1] || path.basename(file, '.js');
  const description = (src.match(/description:\s*'((?:[^'\\]|\\.)*)'/) || [])[1] || '';
  const after = src.split(/\r?\n/); const doc = []; let started = false;
  for (const l of after) { if (/^\/\/ args/.test(l)) started = true; if (started) { if (/^\/\//.test(l)) doc.push(l.replace(/^\/\/ ?/, '')); else break; } }
  return { name, description, args: doc };
}
// The project's banned words, from every place the toolkit reads them: "banned" (the contract; slop board audit),
// "board.banned", "lyrics.banned" (a list or {word: why}; slop lyrics lint), and the older "banned_words".
function bannedWords(pj) {
  const out = [];
  const add = v => { if (Array.isArray(v)) out.push(...v); else if (v && typeof v === 'object') out.push(...Object.keys(v)); else if (typeof v === 'string') out.push(...v.split(',')); };
  add(pj.banned); add(pj.board && pj.board.banned); add(pj.lyrics && pj.lyrics.banned); add(pj.banned_words); add(pj.rules && pj.rules.banned_words);
  return [...new Set(out.map(w => String(w).trim()).filter(Boolean))];
}
function projectVars(P) {
  const pj = readJSON(path.join(P, 'project.json'), {}) || {}; const v = {};
  if (pj.name) v.PROJECT_NAME = pj.name;
  if (pj.title || pj.name) v.TITLE = pj.title || pj.name;
  const owner = pj.owner || pj.pseudonym;   // optional keys (not in the project.json contract); else the brief says "the owner"
  if (typeof owner === 'string' && owner.trim()) v.OWNER = owner.trim();
  const bw = bannedWords(pj);
  if (bw.length) v.BANNED_WORDS = bw;
  if (pj.lead && pj.lead.canon) v.LEAD_CANON = pj.lead.canon;
  if (pj.lead && pj.lead.far) v.LEAD_FAR = pj.lead.far;
  if (pj.look && pj.look.accent) v.ACCENT = pj.look.accent;
  if (pj.tier) v.TIER = pj.tier;
  if (pj.fps) v.FPS = pj.fps;
  if (pj.mj && pj.mj.params) v.MJ_PARAMS = `${pj.mj.params}${pj.mj.profile ? ' --profile ' + pj.mj.profile : ''}`;
  const beats = readJSON(path.join(P, 'analysis', 'beats.json'));
  if (beats && beats.duration) v.DURATION = Math.round(beats.duration * 100) / 100;
  return v;
}
function resolveProjectArg(arg) {
  const p = path.resolve(String(arg).replace(/^~(?=$|[\\/])/, HOME));
  if (fs.existsSync(path.join(p, 'project.json'))) return p;
  const q = path.join(projectsRoot(), String(arg));
  if (fs.existsSync(path.join(q, 'project.json'))) return q;
  throw new UserError(`project "${arg}" not found (no project.json in ${fwd(p)} or ${fwd(q)})`,
    fs.existsSync(p) ? `${fwd(p)} exists but is not a slop project (no project.json): pass the project folder itself, or create the project first (slop new NAME).`
      : 'Pass --project with the project folder path (or its name under the projects folder), or create the project first (slop new NAME).');
}

// ------------------------------------------------------------------------------------------------------- chapter wiring
// The engine page loads ONLY <project>/engine/ch/_index.js from the chapter folder (engine/README.md "Loading" step 4;
// docs/70-motion-design.md §16), so a chapter file that _index.js does not list is never rendered — and the lyric gate
// still prints N/N because the default renderer subtitles every word. `wire` creates a stub per missing chapter file and
// merges _index.js (one entry per file, time order) under a lock, so chapter jobs side by side never lose an entry.
const STUB_MARK = '// slop:chapter-stub';
const INDEX_MARK = 'slop:chapters-index';
const INDEX_RE = /\/\*BEGIN\*\/([\s\S]*?)\/\*END\*\//;
const reEsc = s => String(s).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const numOrNull = x => (x === null || x === undefined || x === '' || !Number.isFinite(Number(x))) ? null : Number(x);
function writeTextAtomic(f, text) {
  const tmp = `${f}.${process.pid}.${crypto.randomBytes(3).toString('hex')}.tmp`;
  fs.writeFileSync(tmp, text);
  for (let i = 0; ; i++) {
    try { fs.renameSync(tmp, f); return; } catch (e) {
      if (i >= 60 || !['EPERM', 'EBUSY', 'EACCES'].includes(e.code)) { try { fs.unlinkSync(tmp); } catch {} throw e; }
      sleepSync(25);
    }
  }
}
function parseChapters(src) {
  let v = src;
  if (typeof v === 'string') {
    const s = v.trim();
    if (/^[[{]/.test(s)) { try { v = JSON.parse(s); } catch (e) { throw new UserError(`--chapters is not valid JSON (${e.message})`, 'Write the list to a .json file and pass its path instead (shells mangle quotes).'); } }
    else v = readJSONStrict(path.resolve(s), 'chapters file');
  }
  if (v && !Array.isArray(v) && typeof v === 'object') v = v.chapters || (v.workflow_args && v.workflow_args.chapters) || (v.vars && v.vars.CHAPTERS) || null;
  if (typeof v === 'string') { try { v = JSON.parse(v); } catch { v = null; } }   // job.json vars.CHAPTERS is a JSON string
  if (!Array.isArray(v) || !v.length) throw new UserError('no chapters found', 'Pass --chapters with a job.json, a wf/args.json or a JSON list [{"id": "C1", "file": "01_name.js", "t0": 0, "t1": 18.9, "shots": ["s001"]}].');
  const bad = v.filter(c => !c || typeof c !== 'object' || !CH_FILE_RE.test(String(c.file || '')) || c.file === '_index.js');
  if (bad.length) throw new UserError(`every chapter needs "file": a plain file name like 02_board.js (bad: ${JSON.stringify(bad).slice(0, 200)})`, 'Fix the chapter list: file names only (no folders), ending in .js, never _index.js.');
  return v.map(c => ({ id: String(c.id || c.file.replace(/\.js$/, '')), file: String(c.file), name: c.name ? String(c.name).replace(/\s+/g, ' ') : null,
    t0: numOrNull(c.t0), t1: numOrNull(c.t1), shots: Array.isArray(c.shots) ? c.shots.map(String) : [] }));
}
function stubText(c) {
  return `${STUB_MARK} — chapter ${c.id}${c.name ? ` "${c.name}"` : ''}${c.t0 != null ? ` (${c.t0}–${c.t1} s)` : ''}${c.shots.length ? `, shots ${c.shots.join(', ')}` : ''}.\n`
    + '// Created by `deleg.mjs wire` so engine/ch/_index.js can load it. The chapter\'s animator replaces this whole file with\n'
    + '// its scenes (engine/DEVICES.md, docs/70-motion-design.md §16). Until then the default renderer draws these shots.\n';
}
function indexText(entries) {
  return ['// ' + INDEX_MARK + ' v1 — written by `node <toolkit>/runner/deleg.mjs wire` (merge-safe; never edit it by hand).',
    '// The engine page loads only this file from engine/ch/; it loads every chapter file listed here, in time order.',
    '// Paths are relative to <project>/engine/ (the page\'s <base>). Add chapters: deleg.mjs wire <project> --chapters <job.json>',
    `window.SLOP_CHAPTER_FILES = /*BEGIN*/${JSON.stringify(entries, null, 1)}/*END*/;`,
    "window.SLOP_CHAPTER_FILES.forEach(c => document.write('<script src=\"ch/' + c.file + '\"><\\/script>'));", ''].join('\n');
}
function withLock(lockFile, fn, waitMs = 20000) {
  // Deadlines use the monotonic clock and a lock held by a live process is never "stale" by age: a wall-clock jump
  // (seen on WSL) made `wire` time out or break a live lock (integration fix).
  const t0 = performance.now();
  for (;;) {
    try { fs.writeFileSync(lockFile, JSON.stringify({ pid: process.pid, at: now() }), { flag: 'wx' }); break; }
    catch (e) {
      if (e.code !== 'EEXIST') throw e;
      const h = readJSON(lockFile); let age = 0; try { age = Date.now() - fs.statSync(lockFile).mtimeMs; } catch {}
      const live = !!(h && h.pid && alive(h.pid));
      if ((h && h.pid && !live) || (!live && age > 60000)) { const t = `${lockFile}.${process.pid}.stale`; try { fs.renameSync(lockFile, t); fs.unlinkSync(t); } catch {} continue; }
      if (performance.now() - t0 > waitMs) throw new UserError(`${fwd(lockFile)} is held by another process`, 'Another `wire` is running: retry in a minute (delete the lock file only if no deleg.mjs is running).');
      sleepSync(100);
    }
  }
  try { return fn(); } finally { try { fs.unlinkSync(lockFile); } catch {} }
}
function indexEntries(text) {
  const m = text && text.match(INDEX_RE); if (!m) return null;
  try { const e = JSON.parse(m[1]); return Array.isArray(e) ? e.filter(x => x && CH_FILE_RE.test(String(x.file)) && x.file !== '_index.js') : null; } catch { return null; }
}
const mentions = (text, file) => new RegExp(`(^|[/'"\`\\s])${reEsc(file)}['"\`]`, 'm').test(text || '');
function wireChapters(P, chapters) {
  const dir = path.join(P, 'engine', 'ch'); fs.mkdirSync(dir, { recursive: true });
  const idx = path.join(dir, '_index.js');
  return withLock(path.join(dir, '.wire.lock'), () => {
    const created = [];
    for (const c of chapters) { const f = path.join(dir, c.file); if (!fs.existsSync(f)) { fs.writeFileSync(f, stubText(c)); created.push(c.file); } }
    const text = readText(idx); let mode, added = [];
    if (text == null || text.includes(INDEX_MARK)) {
      const entries = text == null ? [] : indexEntries(text);
      if (!entries) throw new UserError(`${fwd(idx)} is damaged (its list between /*BEGIN*/ and /*END*/ is not valid JSON)`, `Delete ${fwd(idx)} and run wire again for every chapter job of the project (it is rebuilt from the chapter lists).`);
      for (const c of chapters) {
        const e = { file: c.file, id: c.id, t0: c.t0, t1: c.t1 }; const i = entries.findIndex(x => x.file === c.file);
        if (i >= 0) entries[i] = { ...entries[i], ...Object.fromEntries(Object.entries(e).filter(([, x]) => x != null)) }; else { entries.push(e); added.push(c.file); }
      }
      entries.sort((a, b) => (a.t0 ?? Infinity) - (b.t0 ?? Infinity) || String(a.file).localeCompare(String(b.file)));
      const out = indexText(entries); if (out !== text) writeTextAtomic(idx, out);
      mode = text == null ? 'created' : 'merged';
    } else {   // a hand-written _index.js: keep it, append the files it does not mention
      const miss = chapters.filter(c => !mentions(text, c.file));
      if (miss.length) writeTextAtomic(idx, text + (text.endsWith('\n') ? '' : '\n') + miss.map(c => `document.write('<script src="ch/${c.file}"><\\/script>');   // added by deleg.mjs wire`).join('\n') + '\n');
      added = miss.map(c => c.file); mode = 'appended';
    }
    return { ok: true, index: fwd(idx), mode, created, added, files: chapters.map(c => c.file),
      text: `wired ${chapters.length} chapter file(s) into ${fwd(idx)} (${mode}${added.length ? `, added ${added.join(', ')}` : ''}${created.length ? `; new stubs ${created.join(', ')}` : ''})` };
  });
}
// The static proof that a chapter is rendered by its own code: listed in _index.js, parses, not the stub, calls scene().
// (The engine's `render info` does not name the scenes it registered, so this is checked on the files.)
function checkChapters(P, chapters) {
  const dir = path.join(P, 'engine', 'ch'), idx = path.join(dir, '_index.js'); const itext = readText(idx);
  const listed = indexEntries(itext); const isListed = f => listed ? listed.some(e => e.file === f) : mentions(itext, f);
  const res = chapters.map(c => {
    const f = path.join(dir, c.file); const src = readText(f);
    const r = { id: c.id, file: c.file, exists: src != null, listed: isListed(c.file), syntax_ok: null, stub: null, registers_scenes: null, shots: c.shots.length, shots_named: 0, missing_shots: [] };
    if (src != null) {
      const s = spawnSync(process.execPath, ['--check', f], { encoding: 'utf8', timeout: 20000, windowsHide: true });
      r.syntax_ok = s.status === 0; if (!r.syntax_ok) r.syntax_error = String(s.stderr || s.error || '').trim().split(/\r?\n/).filter(Boolean).slice(0, 4).join(' | ').slice(0, 300);
      const code = src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:'"`])\/\/[^\n]*/g, '$1');
      r.registers_scenes = /\b(?:ENGINE\s*\.\s*)?scene\s*\(/.test(code);
      r.stub = src.startsWith(STUB_MARK) && !r.registers_scenes;
      r.missing_shots = c.shots.filter(id => !new RegExp(`['"\`]${reEsc(id)}['"\`]`).test(src));
      r.shots_named = c.shots.length - r.missing_shots.length;
    }
    const why = !r.exists ? 'the file does not exist' : !r.listed ? 'engine/ch/_index.js does not list it, so the engine never loads it (run wire)'
      : !r.syntax_ok ? `it does not parse: ${r.syntax_error}` : r.stub ? 'it is still the stub (no scenes yet)' : !r.registers_scenes ? 'it registers no scene (no scene(...) call)' : null;
    r.wired = !why;
    r.line = r.wired ? `WIRED ${c.id} ${c.file}: listed in engine/ch/_index.js, parses, registers scenes${c.shots.length ? `, names ${r.shots_named}/${c.shots.length} shots${r.missing_shots.length ? ` (not named: ${r.missing_shots.join(', ')}; fine if the code finds them another way)` : ''}` : ''}`
      : `NOT WIRED ${c.id} ${c.file}: ${why} - the default renderer draws these shots, whatever the lyric gate says`;
    return r;
  });
  return { ok: res.every(r => r.wired), index: fwd(idx), chapters: res, text: res.map(r => r.line).join('\n') };
}

// --------------------------------------------------------------------------------------------- toolkit runtime checks
// Every check in the briefs runs the toolkit CLI on the machine that runs the job; "requires" proves it works there
// before an engine starts (a 1–3 h job with no working checks only fails in its reviews).
function slopEnv(slop) {
  const env = { ...process.env };
  for (const k of Object.keys(env)) if (PARENT_SESSION_RE.test(k)) delete env[k];
  if (slop.pythonpath) env.PYTHONPATH = [TOOLKIT_DIR, env.PYTHONPATH].filter(Boolean).join(path.delimiter);
  return env;
}
const tailOf = r => String(`${r.stderr || ''}${r.stdout || ''}` || (r.error && r.error.message) || '').trim().split(/\r?\n/).filter(Boolean).slice(-3).join(' | ').slice(0, 300);
function venvPython() { return fwd(WIN ? path.join(slopHome(), 'venv', 'Scripts', 'python.exe') : path.join(slopHome(), 'venv', 'bin', 'python')); }
function toolkitFix(what) {
  const py = venvPython();
  if (what === 'browser') return `Install the browser the renderer uses: "${py}" -m playwright install chromium (or install Google Chrome), then: node "${fwd(SELF)}" doctor --render`;
  if (what === 'ffmpeg') return WIN ? 'Install ffmpeg (winget install --id Gyan.FFmpeg -e), open a new terminal so it is on PATH, then retry.'
    : process.platform === 'darwin' ? 'Install ffmpeg (brew install ffmpeg), then retry.' : 'Install ffmpeg with the package manager (e.g. sudo apt install ffmpeg), then retry.';
  return WIN ? `Install the toolkit runtime on this computer (runner/README.md §1, "Windows"): uv venv --python 3.13 "${fwd(path.join(slopHome(), 'venv'))}" ; uv pip install --python "${py}" -e "${fwd(TOOLKIT_DIR)}" ; "${py}" -m playwright install chromium ; then: node "${fwd(SELF)}" doctor --render`
    : `Install the toolkit runtime on this computer: bash "${fwd(path.join(TOOLKIT_DIR, 'bin', 'setup.sh'))}" --minimal (macOS and Linux; about 5 minutes), then: node "${fwd(SELF)}" doctor --render`;
}
function toolkitCheck(slop, want) {
  const res = { ok: true, slop: slop.cmd, errors: [], fixes: [] };
  const fail = (msg, fix) => { res.ok = false; res.errors.push(msg); if (!res.fixes.includes(fix)) res.fixes.push(fix); };
  const env = slopEnv(slop);
  if (want.has('slop') || want.has('render')) {
    const r = spawnSync(`${slop.cmd} --version`, { shell: true, encoding: 'utf8', timeout: 60000, windowsHide: true, env });
    const out = `${r.stdout || ''}${r.stderr || ''}`;
    res.slop_ok = r.status === 0 && /\bslop\b/i.test(out);
    res.slop_version = res.slop_ok ? out.trim().split(/\r?\n/)[0] : null;
    if (!res.slop_ok) fail(`the toolkit CLI does not run here (${slop.cmd} --version: ${tailOf(r) || `exit ${r.status}`})`, toolkitFix('slop'));
  }
  if (want.has('render') && res.slop_ok) {
    const d = fs.mkdtempSync(path.join(os.tmpdir(), 'slop-smoke-'));
    try {
      fs.mkdirSync(path.join(d, 'analysis'), { recursive: true });
      fs.writeFileSync(path.join(d, 'project.json'), JSON.stringify({ name: 'slop-smoke', title: 'Smoke', fps: 24, size: [320, 180] }));
      fs.writeFileSync(path.join(d, 'analysis', 'beats.json'), JSON.stringify({ duration: 2, beats: [0, 0.5, 1, 1.5], downbeats: [0], tempo: [{ t: 0, bpm: 120 }], sections: [] }));
      const r = spawnSync(`${slop.cmd} --json --project "${fwd(d)}" render info --size 320x180`, { shell: true, encoding: 'utf8', timeout: 120000, windowsHide: true, env });
      let j = null; try { j = JSON.parse(String(r.stdout || '').trim().split(/\r?\n/).pop()); } catch {}
      res.render_ok = !!(j && j.ok);
      if (!res.render_ok) {
        const why = j ? (j.error || (j.warnings || []).join(' | ') || 'not ok') : (tailOf(r) || `exit ${r.status}`);
        fail(`the renderer does not run here (render info on a scratch project: ${String(why).slice(0, 300)})`, toolkitFix(/browser|chromium|playwright|chrome/i.test(why) ? 'browser' : 'slop'));
      }
    } finally { try { fs.rmSync(d, { recursive: true, force: true }); } catch {} }
  }
  if (want.has('ffmpeg')) {
    const r = spawnSync('ffmpeg', ['-hide_banner', '-version'], { encoding: 'utf8', timeout: 20000, windowsHide: true });
    res.ffmpeg_ok = r.status === 0;
    if (!res.ffmpeg_ok) fail('ffmpeg is not on PATH', toolkitFix('ffmpeg'));
  }
  res.error = res.errors.join('; ') || null; res.fix = res.fixes.join(' ') || null;
  return res;
}

// ------------------------------------------------------------------------------------------------------------- gates
// Fields of job.json that widen what a job may do beyond the safe defaults. job.json is written on the bot's computer
// and the approval card shows only the command line, so each one needs its flag on that command line.
function elevations(job, ctx = {}) {
  const out = [];
  if (job.allow_api_billing) out.push({ field: 'allow_api_billing', flag: '--allow-api-billing', detail: 'keeps API-key variables, so the engine may bill an API key instead of the subscription' });
  if (job.allow_spend) out.push({ field: 'allow_spend', flag: '--allow-spend', detail: "enables Claude's Higgsfield connector, which spends credits" });
  for (const k of job.pass_env || []) out.push({ field: 'pass_env', name: String(k), flag: `--pass-env ${k}`, detail: `hands the secret ${k} to the engine` });
  const raw = [];
  if (job.engine === 'raw') raw.push('engine "raw" (runs argv as a command)'); else if (job.argv) raw.push('argv');
  if (job.engine_bin != null) raw.push('engine_bin (the executable to run)');
  if (job.env && Object.keys(job.env).length) raw.push(`env (${Object.keys(job.env).join(', ')})`);
  if (job.slop_cmd) raw.push('slop_cmd (run by the runner and the workers)');
  if ((job.add_dirs || []).length) raw.push('add_dirs (extra folders the engine may write)');
  if ((job.codex_config || []).length) raw.push('codex_config');
  if (job.muse_flags) raw.push('muse_flags');
  if (job.permission_mode && !SAFE_PERMISSION_MODES.has(job.permission_mode)) raw.push(`permission_mode ${job.permission_mode}`);
  if (job.sandbox === 'danger-full-access') raw.push('sandbox danger-full-access');
  if (job.engine === 'gemini' && job.approval_mode === 'yolo') raw.push('gemini approval_mode yolo (every tool call auto-approved)');
  const tools = [...(job.allowed_tools || []), ...(job.extra_allowed_tools || [])].map(String).filter(t => !CLAUDE_TOOLS.includes(t));
  if (tools.length) raw.push(`tools beyond the default list (${tools.join(', ')})`);
  if (ctx.cwd && ctx.J && ![ctx.J, ctx.P].filter(Boolean).some(d => { const rel = path.relative(path.resolve(d), path.resolve(ctx.cwd)); return !rel.startsWith('..') && !path.isAbsolute(rel); })) raw.push('cwd outside the job and project folders');
  if (ctx.P && !fs.existsSync(path.join(ctx.P, 'project.json'))) raw.push('project_dir that is not a slop project (no project.json)');
  if (raw.length) out.push({ field: 'raw', flag: '--allow-raw', detail: `overrides the runner's safe defaults: ${raw.join('; ')}` });
  return out;
}
function gateFlags(job, ctx) { return [...new Set(elevations(job, ctx).map(e => e.flag))]; }
function checkGates(job, grants, ctx) {
  const g = grants || {};
  const missing = elevations(job, ctx).filter(e => e.field === 'pass_env' ? !(g.pass_env || []).includes(e.name) : !g[e.field === 'raw' ? 'allow_raw' : e.field]);
  if (missing.length) throw new UserError(`this job.json asks for more than the safe defaults and the command line does not grant it: ${missing.map(m => `${m.field}: ${m.detail}`).join('; ')}`,
    `Ask the user first. Only if they agree, run the same command again with ${[...new Set(missing.map(m => m.flag))].join(' ')} added (the approval card then shows it). Otherwise rebuild the job without those fields.`);
}
function gatesLine(job, grants) {
  const g = grants || {};
  return `gates: api-billing ${g.allow_api_billing ? 'ON' : 'off'}, spend ${job.allow_spend && g.allow_spend ? 'ON' : 'off'}, raw ${g.allow_raw ? 'ON' : 'off'}, pass-env ${(job.pass_env || []).join(',') || '-'}`;
}

// ------------------------------------------------------------------------------------------------------------ materialize
// Make a job folder runnable on THIS machine: BRIEF.md from job.brief, wf/<name>.js from the toolkit, runtime tokens.
function materialize(p) {
  const { job, unknown } = loadJob(p);
  const J = p.J;
  fs.mkdirSync(p.outbox, { recursive: true });
  const P = resolveProjectDir(job, J);
  const promptFile = path.resolve(J, job.prompt_file || 'BRIEF.md');
  if (job.engine !== 'raw' && !fs.existsSync(promptFile)) {
    if (typeof job.brief === 'string' && job.brief.trim()) fs.writeFileSync(promptFile, job.brief);
    else throw new UserError(`no ${path.basename(promptFile)} in the job folder and no "brief" text in job.json`, 'Create the job with: node deleg.mjs new <jobdir> --brief <name>');
  }
  let wfPath = null;
  if (job.workflow) {
    wfPath = path.join(p.wf, path.basename(String(job.workflow)).replace(/\.js$/, '') + '.js');
    if (!fs.existsSync(wfPath)) { fs.mkdirSync(p.wf, { recursive: true }); fs.copyFileSync(resolveWorkflow(job.workflow), wfPath); }
  }
  const slop = resolveSlop(job);
  const tokens = { JOB_DIR: fwd(J), JOB_ID: path.basename(J), OUTBOX: fwd(p.outbox), PROJECT_DIR: P ? fwd(P) : '(no project folder)',
    TOOLKIT_DIR: fwd(TOOLKIT_DIR), SLOP: slop.cmd, ENGINE: job.engine, WORKFLOW_PATH: wfPath ? fwd(wfPath) : '(no workflow)' };
  let args = null, wired = null;
  if (job.wire_chapters) {   // chapter jobs: stub files + engine/ch/_index.js on THIS machine before the engine starts
    if (!P || !fs.existsSync(path.join(P, 'project.json'))) throw new UserError(`"wire_chapters" needs the project folder (project_dir), and ${P ? fwd(P) : 'it'} has no project.json`, 'Copy the job file into <project>/jobs/ on this computer (sync the project first), or create the job with: node deleg.mjs new auto --project <project> ...');
    const chs = parseChapters((job.workflow_args && job.workflow_args.chapters) || job.vars && job.vars.CHAPTERS);
    wired = wireChapters(P, chs);
  }
  if (wfPath) {
    args = { ...fillDeep(job.workflow_args || {}, tokens) };
    if (args.slop == null) args.slop = slop.cmd;
    Object.assign(args, { project_dir: P ? fwd(P) : null, out_dir: fwd(p.outbox), toolkit_dir: fwd(TOOLKIT_DIR), job_dir: fwd(J) });
    if (wired) args.wired = true;
    writeJSON(path.join(p.wf, 'args.json'), args);
  }
  tokens.WORKFLOW_ARGS = args ? JSON.stringify(args) : '{}';
  if (job.engine !== 'raw') {
    const t = fs.readFileSync(promptFile, 'utf8');
    const { text, missing } = fill(t, tokens);
    if (missing.length) throw new UserError(`${path.basename(promptFile)} has unfilled placeholders: ${missing.map(m => `{{${m}}}`).join(', ')}`,
      `Re-create the job: node deleg.mjs new <jobdir> --brief <name> --set ${missing[0]}=... --force (or edit the file by hand).`);
    if (text !== t) fs.writeFileSync(promptFile, text);
  }
  return { job, unknown, P, wfPath, args, slop, promptFile, wired };
}

// ---------------------------------------------------------------------------------------------------- argv & env builders
function buildArgv(job, ctx) {
  const { J, st, promptFile, cwd, addDirs, allowBilling } = ctx;
  const outbox = path.join(J, 'outbox');
  const add = (a, flag, v) => { if (v !== undefined && v !== null && v !== '') a.push(flag, String(v)); };
  if (job.engine === 'claude') {
    // Short argv prompt (Windows command lines max out at 32,767 chars); the brief stays in a file.
    const a = ['-p', `Read the file ${fwd(promptFile)} and do exactly what it says. You are running unattended: nobody will answer questions. Deliverables go where the brief says; everything else you write goes under ${fwd(outbox)}.`,
      '--output-format', 'stream-json', '--verbose', '--permission-mode', job.permission_mode || 'default', '--permission-prompts', 'none'];
    for (const d of addDirs) a.push('--add-dir', d);
    const tools = job.allowed_tools ? [...job.allowed_tools] : [...CLAUDE_TOOLS];
    for (const t of job.extra_allowed_tools || []) if (!tools.includes(t)) tools.push(t);
    if (tools.length) a.push('--allowedTools', tools.join(','));
    const deny = [...(job.disallowed_tools || [])];
    if (!job.allow_spend) for (const t of CLAUDE_SPEND_TOOLS) if (!deny.includes(t)) deny.push(t);
    if (deny.length) a.push('--disallowedTools', deny.join(','));
    add(a, '--max-turns', job.max_turns); add(a, '--max-budget-usd', job.max_budget_usd);
    add(a, '--model', job.model); add(a, '--effort', job.effort);
    if (st.session_id) a.push('--resume', st.session_id); else a.push('--session-id', st.planned_session_id);
    return { argv: a, stdin: null };
  }
  if (job.engine === 'codex') {
    const prompt = fs.readFileSync(promptFile, 'utf8');
    const common = ['--json', '--skip-git-repo-check'];
    if (!allowBilling) common.push('-c', 'forced_login_method="chatgpt"');
    common.push('-o', path.join(J, 'last-message.txt'));
    if (job.model) common.push('-m', String(job.model));
    if (job.effort) common.push('-c', `model_reasoning_effort="${job.effort}"`);
    if (job.output_schema) common.push('--output-schema', path.resolve(J, job.output_schema));
    if (job.network) common.push('-c', 'sandbox_workspace_write.network_access=true');
    for (const c of job.codex_config || []) common.push('-c', String(c));
    const sandbox = job.sandbox || 'workspace-write';
    // `exec resume` has no -s/--sandbox/-C/--add-dir: pass the sandbox with -c and rely on the cwd.
    if (st.thread_id) return { argv: ['exec', 'resume', ...common, '-c', `sandbox_mode="${sandbox}"`, st.thread_id, '-'], stdin: prompt };
    const a = ['exec', ...common, '-C', cwd, '-s', sandbox];
    for (const d of addDirs) a.push('--add-dir', d);
    a.push('-');   // prompt on stdin; the supervisor closes stdin (Codex reads a non-TTY stdin and would wait)
    return { argv: a, stdin: prompt };
  }
  if (job.engine === 'muse') {
    const a = ['exec', '--json', '--prompt-file', promptFile, '--approval-mode', job.approval_mode || 'never', '--workspace', cwd,
      '--user-input-auto-resolve', ...(job.muse_flags || ['--no-foreign-personal-context'])];
    add(a, '--model', job.model); add(a, '--reasoning-effort', job.effort); add(a, '--provider', job.provider);
    if (job.output_schema) a.push('--output-schema', path.resolve(J, job.output_schema));
    if (st.session_id) a.push('--session-id', st.session_id);
    return { argv: a, stdin: null };
  }
  if (job.engine === 'gemini') {
    // Headless Gemini: the prompt stays in a file (a short -p argv); stdin is closed (gemini appends a piped stdin to
    // the prompt); --skip-trust because job folders are not trusted folders. No session resume: an attempt > 1 is a
    // new session that reads the continuation prompt file.
    const a = ['-p', `Read the file ${fwd(promptFile)} and do exactly what it says. You are running unattended: nobody will answer questions. Deliverables go where the brief says; everything else you write goes under ${fwd(outbox)}.`,
      '-o', 'stream-json', '--skip-trust', '--approval-mode', job.approval_mode || 'auto_edit'];
    if (addDirs.length) a.push('--include-directories', addDirs.join(','));
    // [U] opt-in (gated: tools outside the Claude list need --allow-raw): tools Gemini may run without approval, e.g.
    // "run_shell_command" — headless Gemini otherwise drops tools that would ask (the shell under auto_edit)
    for (const t of [...(job.allowed_tools || []), ...(job.extra_allowed_tools || [])]) a.push('--allowed-tools', String(t));
    add(a, '-m', job.model);
    return { argv: a, stdin: null };
  }
  return { argv: job.argv.slice(1).map(String), stdin: null, cmd: String(job.argv[0]) === 'node' ? process.execPath : String(job.argv[0]) };
}
function buildEnv(job, ctx) {
  const env = { ...process.env };
  const stripped = [];
  const pass = new Set(job.pass_env || []);
  for (const k of Object.keys(env)) {
    if (PARENT_SESSION_RE.test(k)) { delete env[k]; continue; }
    if (!ctx.allowBilling && BILLING_ENV.includes(k) && !pass.has(k)) { delete env[k]; stripped.push(k); continue; }
    if ((SECRET_ENV.includes(k) || LOGIN_CODE_ENV.includes(k)) && !pass.has(k)) { delete env[k]; stripped.push(k); continue; }
    if (ENGINE_SIGNIN_ENV[k] && ENGINE_SIGNIN_ENV[k] !== job.engine && !pass.has(k)) { delete env[k]; stripped.push(k); }
  }
  env.MUSE_NO_AUTO_UPDATE = '1';   // keep the Muse CLI from updating itself in the middle of a job
  if (job.engine === 'claude' && onBox() && env.DISABLE_AUTOUPDATER === undefined) env.DISABLE_AUTOUPDATER = '1';   // the box keeps its own copy (slop agents install --upgrade)
  env.SLOP_JOB_DIR = ctx.J;
  env.DELEG_JOB = path.basename(ctx.J);
  if (ctx.P) env.SLOP_PROJECT = ctx.P;
  if (ctx.slop.pythonpath) env.PYTHONPATH = [TOOLKIT_DIR, env.PYTHONPATH].filter(Boolean).join(path.delimiter);
  if (job.workflows_env) env.CLAUDE_CODE_WORKFLOWS = '1';
  for (const [k, v] of Object.entries(job.env || {})) env[k] = String(v);
  return { env, stripped };
}

// --------------------------------------------------------------------------------------- stream normalisers (per event)
function summarizeInput(name, inp) {
  if (!inp || typeof inp !== 'object') return '';
  if (name === 'Workflow') return [inp.scriptPath ? path.basename(String(inp.scriptPath)) : (inp.name || 'inline script'), inp.resumeFromRunId ? `resume ${inp.resumeFromRunId}` : ''].filter(Boolean).join(' ');
  const v = inp.command ?? inp.file_path ?? inp.path ?? inp.pattern ?? inp.url ?? inp.query ?? inp.description ?? inp.prompt ?? '';
  return String(v).replace(/\s+/g, ' ').slice(0, 120);
}
function addTokens(st, t) {
  const T = (st.tokens ||= {});
  for (const [k, v] of Object.entries(t)) if (typeof v === 'number') T[k] = (T[k] || 0) + v;
}
function normClaude(ev, st, job) {
  const P = []; const t = ev.type, s = ev.subtype;
  if (t === 'system' && s === 'init') {
    if (ev.session_id) st.session_id = ev.session_id;
    st.model = ev.model || st.model; st.permission_mode = ev.permissionMode || st.permission_mode;
    const tools = Array.isArray(ev.tools) ? ev.tools : [];
    st.has_workflow_tool = tools.includes('Workflow');
    st.api_key_source = ev.apiKeySource ?? st.api_key_source ?? null;
    if (ev.claude_code_version) st.engine_version = ev.claude_code_version;
    if (!st._init) { st._init = true; P.push(`init session ${ev.session_id} model ${ev.model} workflow-tool ${st.has_workflow_tool ? 'yes' : 'NO'} auth ${st.api_key_source}`); }
    if (job.workflow && !st.has_workflow_tool)
      st._fatal = 'This Claude Code has no Workflow tool (Claude Pro plans have it off by default). Set "workflows_env": true in job.json (it sets CLAUDE_CODE_WORKFLOWS=1; workflows use a lot of your plan) and run it again, or use a plan that has it.';
    if (!st._allow_billing && st.api_key_source && /key|helper|anthropic|console/i.test(String(st.api_key_source)))
      st._fatal = `Claude Code would bill an API key (apiKeySource=${st.api_key_source}) instead of your Claude plan. Remove the key from your Claude settings, or set "allow_api_billing": true in job.json if you want API billing.`;
  } else if (t === 'assistant') {
    for (const b of (ev.message && ev.message.content) || []) {
      if (b.type === 'text' && b.text) st.last_text = String(b.text).slice(-2000);
      if (b.type === 'tool_use') P.push(`tool ${b.name} ${summarizeInput(b.name, b.input)}`.trim());
    }
  } else if (t === 'user') {
    for (const b of (ev.message && ev.message.content) || []) {
      const c = typeof b.content === 'string' ? b.content : JSON.stringify(b.content || '');
      const m = c.match(/Run ID: (wf_[0-9a-z-]{6,})/i);
      if (m) { (st.workflow_runs ||= []); if (!st.workflow_runs.includes(m[1])) st.workflow_runs.push(m[1]); P.push(`workflow launched ${m[1]}`); }
      if (b.is_error) {
        P.push(`tool error: ${c.replace(/\s+/g, ' ').slice(0, 180)}`);
        if (/Review dynamic workflow|outside the readable set|scriptPath must be/i.test(c)) warn(st, `Workflow call refused: ${c.replace(/\s+/g, ' ').slice(0, 200)}`);
      }
    }
  } else if (t === 'system' && s === 'background_tasks_changed') {
    st.bg_tasks = Array.isArray(ev.tasks) ? ev.tasks.length : 0;
  } else if (t === 'system' && s === 'task_started') {
    (st.tasks ||= {})[ev.task_id] = { type: ev.task_type, name: ev.workflow_name || ev.description, status: 'running', started: now() };
    P.push(`task start ${ev.task_type || ''} ${ev.workflow_name || ev.description || ''}`.trim());
  } else if (t === 'system' && s === 'task_progress') {
    const ag = (ev.workflow_progress || []).filter(x => x && x.type === 'workflow_agent');
    const done = ag.filter(x => x.state === 'done').length, err = ag.filter(x => x.state === 'error').length;
    const key = `${ev.task_id}:${done}/${ag.length}:${err}`;
    if (st._lastProg !== key) { st._lastProg = key; P.push(`workflow ${ev.task_id} agents done ${done}/${ag.length} err ${err} tokens ${(ev.usage && ev.usage.total_tokens) ?? '?'}`); }
    const task = (st.tasks ||= {})[ev.task_id] ||= { type: 'local_workflow', status: 'running' };
    Object.assign(task, { agents: ag.length, done, err, tokens: (ev.usage && ev.usage.total_tokens) ?? task.tokens });
  } else if (t === 'system' && s === 'task_updated') {
    const task = st.tasks && st.tasks[ev.task_id]; if (task && ev.patch && ev.patch.status) task.status = ev.patch.status;
  } else if (t === 'system' && s === 'task_notification') {
    const task = (st.tasks ||= {})[ev.task_id] ||= { type: 'local_workflow' };
    Object.assign(task, { status: ev.status, output_file: ev.output_file || task.output_file, ended: now() });
    if (ev.usage && typeof ev.usage.total_tokens === 'number') task.tokens = ev.usage.total_tokens;
    if (ev.status && ev.status !== 'completed') warn(st, `background task ${ev.task_id} ended ${ev.status}`);
    P.push(`task ${ev.task_id} ${ev.status}${task.tokens ? ` tokens ${task.tokens}` : ''}`);
  } else if (t === 'rate_limit_event') {
    const r = ev.rate_limit_info || {}; const w = r.unifiedWindows || {};
    st.limits = { status: r.status, type: r.rateLimitType, resets_at: r.resetsAt ?? null, five_hour: w.five_hour || null, seven_day: w.seven_day || null, overage: r.overageStatus };
    if (r.status && r.status !== st._limitStatus) { if (st._limitStatus || r.status !== 'allowed') P.push(`usage limit status ${r.status}`); st._limitStatus = r.status; }
    if (r.status === 'rejected') warn(st, 'Claude usage limit reached: agents that start now return nothing. Resume the job after the limit resets (status.limits).');
    const lim = job.stop_above_utilization;
    if (lim) {
      const u = Math.max((w.five_hour && w.five_hour.utilization) || 0, (w.seven_day && w.seven_day.utilization) || 0);
      if (u >= lim) st._quota = `plan usage ${Math.round(u * 100)}% >= stop_above_utilization ${Math.round(lim * 100)}%`;
    }
  } else if (t === 'result') {
    const den = Array.isArray(ev.permission_denials) ? ev.permission_denials : [];
    const r = { attempt: st.attempt, subtype: ev.subtype, is_error: !!ev.is_error, cost_usd: ev.total_cost_usd ?? null, turns: ev.num_turns ?? null,
      origin: (ev.origin && ev.origin.kind) || 'turn', denials: den.length };
    (st.results ||= []).push(r);
    st.final = { subtype: ev.subtype, is_error: !!ev.is_error, text: String(ev.result ?? '').slice(-4000) };
    st.cost_usd = round((st.cost_usd || 0) + (ev.total_cost_usd || 0));
    const u = ev.usage || {};
    addTokens(st, { input: u.input_tokens, output: u.output_tokens, cache_read: u.cache_read_input_tokens, cache_write: u.cache_creation_input_tokens });
    if (den.length) warn(st, `${den.length} permission denial(s) (${[...new Set(den.map(d => d.tool_name || d.toolName || '?'))].join(', ')}): add the tool to "extra_allowed_tools" in job.json if the job needed it`);
    P.push(`result ${ev.subtype}${ev.is_error ? ' ERROR' : ''} turns ${ev.num_turns} ~$${(ev.total_cost_usd || 0).toFixed(3)} (${r.origin})${st.bg_tasks ? ' - background work still running, waiting for exit' : ''}`);
  }
  return P;
}
function normCodex(ev, st) {
  const P = [];
  if (ev.type === 'thread.started') { if (ev.thread_id) st.thread_id = ev.thread_id; if (!st._init) { st._init = true; P.push(`thread ${ev.thread_id}`); } }
  else if (ev.type === 'item.completed' || ev.type === 'item.started') {
    const it = ev.item || {};
    if (it.type === 'agent_message' && ev.type === 'item.completed') st.last_text = String(it.text || '').slice(-4000);
    if (it.type === 'command_execution') P.push(`${ev.type === 'item.started' ? 'run' : 'ran'} ${String(it.command).replace(/\s+/g, ' ').slice(0, 140)}${it.exit_code != null ? ' -> ' + it.exit_code : ''}`);
    if (it.type === 'file_change' && ev.type === 'item.completed') P.push(`files ${(it.changes || []).map(c => `${c.kind} ${c.path}`).join(', ').slice(0, 180)}`);
    if (it.type === 'mcp_tool_call' && ev.type === 'item.started') P.push(`mcp ${it.server}.${it.tool}`);
    if (it.type === 'error') P.push(`item error ${String(it.message).slice(0, 180)}`);
  } else if (ev.type === 'turn.completed') {
    const u = ev.usage || {};
    addTokens(st, { input: u.input_tokens, cache_read: u.cached_input_tokens, output: u.output_tokens, reasoning: u.reasoning_output_tokens });
    st.final = { subtype: 'success', is_error: false, text: st.last_text || '' };
    P.push(`turn completed in=${u.input_tokens} out=${u.output_tokens}`);
  } else if (ev.type === 'turn.failed' || ev.type === 'error') {
    const msg = typeof ev.error === 'string' ? ev.error : JSON.stringify(ev.error || ev.message || ev);
    st.final = { subtype: 'error', is_error: true, text: msg.slice(0, 2000) };
    P.push(`${ev.type} ${msg.slice(0, 180)}`);
  }
  return P;
}
function normMuse(ev, st) {
  const P = [];
  if (ev.stream && ev.stream.kind === 'session' && ev.stream.id) { if (!st.session_id) P.push(`session ${ev.stream.id}`); st.session_id = ev.stream.id; }
  const pt = ev.payload_type, p = ev.payload || {};
  if (pt === 'run.model.configured') st.model = p.model_id;
  else if (pt === 'run.lifecycle.started') st.last_text = '';
  else if (pt === 'run.output.delta') st.last_text = ((st.last_text || '') + (p.text || '')).slice(-4000);
  else if (pt && pt.startsWith('run.terminal.')) {
    st.final = { subtype: p.terminal, is_error: p.terminal !== 'completed', text: String(p.text || st.last_text || '').slice(-4000), reason: p.reason ?? null };
    P.push(`terminal ${p.terminal}${p.reason ? ' ' + JSON.stringify(p.reason).slice(0, 120) : ''}`);
  } else if (pt === 'task.lifecycle.proposed' && p.event && p.event.task_kind && !/^reminder\./.test(p.event.task_kind)) P.push(`task ${p.event.task_kind}`);
  else if (pt === 'task.lifecycle.status' && p.event && /attempt (\d+)/.test(p.event.message || '') && !/attempt 1\//.test(p.event.message)) P.push(`retry: ${p.event.message}`);
  return P;
}
// Gemini CLI `-o stream-json` (verified 0.62.0): {type:"init", session_id, model} · {type:"message", role, content,
// delta?} · {type:"tool_use", tool_name, tool_id, parameters} · {type:"tool_result", tool_id, status, output|error} ·
// {type:"result", status:"success"|"error", error?{type,message}, stats?{total_tokens,input_tokens,output_tokens,…}}.
function normGemini(ev, st) {
  const P = [];
  if (ev.type === 'init') {
    if (ev.session_id) st.session_id = ev.session_id; st.model = ev.model || st.model;
    if (!st._init) { st._init = true; P.push(`init session ${ev.session_id} model ${ev.model}`); }
  } else if (ev.type === 'message' && ev.role === 'assistant') {
    st.last_text = ((ev.delta ? (st.last_text || '') : '') + String(ev.content ?? '')).slice(-4000);
  } else if (ev.type === 'tool_use') {
    const n = ev.tool_name || ev.name || 'tool'; P.push(`tool ${n} ${summarizeInput(n, ev.parameters || ev.input)}`.trim());
  } else if (ev.type === 'tool_result' && (ev.status === 'error' || ev.error)) {
    P.push(`tool error: ${String((ev.error && ev.error.message) || JSON.stringify(ev.error || ev.output || '')).replace(/\s+/g, ' ').slice(0, 160)}`);
  } else if (ev.type === 'error') {
    P.push(`error ${String(ev.message || JSON.stringify(ev)).replace(/\s+/g, ' ').slice(0, 180)}`);
  } else if (ev.type === 'result') {
    const s = ev.stats || {};
    addTokens(st, { input: s.input_tokens ?? s.input, output: s.output_tokens ?? s.output, cache_read: s.cached ?? s.cached_tokens });
    const isErr = !!ev.status && ev.status !== 'success';
    const msg = ev.error ? String(ev.error.message || JSON.stringify(ev.error)) : '';
    st.final = { subtype: ev.status || 'success', is_error: isErr, text: (isErr ? msg : (st.last_text || '')).slice(-4000) };
    P.push(`result ${ev.status || 'success'}${isErr ? ' ' + msg.replace(/\s+/g, ' ').slice(0, 160) : ''}`);
  }
  return P;
}
function norm(engine, ev, st, job) {
  if (engine === 'claude') return normClaude(ev, st, job);
  if (engine === 'codex') return normCodex(ev, st);
  if (engine === 'muse') return normMuse(ev, st);
  if (engine === 'gemini') return normGemini(ev, st);
  return [];
}

// ------------------------------------------------------------------------------- usage readers outside the stdout stream
function codexLimits(threadId) {
  try {
    const root = path.join(process.env.CODEX_HOME || path.join(HOME, '.codex'), 'sessions'); const hits = [];
    const walk = d => { for (const f of fs.readdirSync(d, { withFileTypes: true })) { const q = path.join(d, f.name); if (f.isDirectory()) walk(q); else if (f.name.includes(threadId)) hits.push(q); } };
    walk(root); if (!hits.length) return null;
    let rl = null;
    for (const l of fs.readFileSync(hits[0], 'utf8').split('\n')) if (l.includes('"rate_limits"')) { try { rl = JSON.parse(l).payload.rate_limits; } catch {} }
    return rl && { primary: rl.primary, secondary: rl.secondary, plan: rl.plan_type, credits: rl.credits && rl.credits.balance, reached: rl.rate_limit_reached_type, rollout: fwd(hits[0]) };
  } catch { return null; }
}
// Copy each workflow's task output (summary, logs, result, workflowProgress) into runs/ and flag dead agents.
function harvestClaude(st, p) {
  for (const [tid, task] of Object.entries(st.tasks || {})) {
    if (!task.output_file) continue;
    const dest = path.join(p.runs, `${tid}.output.json`);
    try { fs.mkdirSync(p.runs, { recursive: true }); fs.copyFileSync(task.output_file, dest); task.saved = fwd(path.relative(p.J, dest)); }
    catch (e) { warn(st, `could not copy workflow output ${fwd(task.output_file)} (${e.code || e.message})`); continue; }
    const o = readJSON(dest); if (!o || typeof o !== 'object') continue;
    const logs = Array.isArray(o.logs) ? o.logs.map(String) : [];
    const failedLogs = logs.filter(l => /\]\s*failed:/i.test(l) || /\bFAILED\b/.test(l));
    const errAgents = (o.workflowProgress || []).filter(x => x && x.type === 'workflow_agent' && x.state === 'error');
    task.failed_agents = Math.max(failedLogs.length, errAgents.length);
    if (task.failed_agents) warn(st, `workflow ${task.name || tid}: ${task.failed_agents} agent(s) failed or returned nothing (${(failedLogs[0] || (errAgents[0] && errAgents[0].error) || '').toString().replace(/\s+/g, ' ').slice(0, 140)}) - check the workflow result before trusting it`);
    const res = o.result;
    task.result_ok = res && typeof res === 'object' && 'ok' in res ? !!res.ok : null;
    if (task.result_ok === false) warn(st, `workflow ${task.name || tid} returned ok:false: ${String(res.error || res.reason || (res.failed && JSON.stringify(res.failed)) || '').slice(0, 180)}`);
  }
  const base = process.env.CLAUDE_CONFIG_DIR || path.join(HOME, '.claude');
  if (st.session_id && (st.workflow_runs || []).length) {
    let slugs = []; try { slugs = fs.readdirSync(path.join(base, 'projects')); } catch {}
    for (const s of slugs) {
      const d = path.join(base, 'projects', s, st.session_id, 'workflows'); if (!fs.existsSync(d)) continue;
      for (const r of st.workflow_runs) { const f = path.join(d, `${r}.json`); if (fs.existsSync(f)) { try { fs.mkdirSync(p.runs, { recursive: true }); fs.copyFileSync(f, path.join(p.runs, `${r}.json`)); } catch {} } }
    }
  }
}

// --------------------------------------------------------------------------------------------- outbox: collect and pack
function globRe(g) { return new RegExp('^' + g.split('').map(c => c === '*' ? '[^/]*' : c === '?' ? '.' : c.replace(/[.+^${}()|[\]\\]/g, '\\$&')).join('') + '$'); }
function collectFiles(job, p, P, st) {
  const pats = job.collect || []; if (!pats.length) return;
  if (!P) { warn(st, '"collect" needs a project folder (project_dir); nothing collected'); return; }
  const dest = path.join(p.outbox, 'files'); let n = 0;
  for (const pat of pats) {
    const rel = fwd(pat).replace(/^\/+/, '');
    if (!rel || rel.split('/').includes('..')) { warn(st, `collect entry refused: ${pat}`); continue; }
    const dir = path.posix.dirname(rel), base = path.posix.basename(rel);
    const srcDir = path.join(P, dir);
    let names = [];
    if (/[*?]/.test(base)) { const re = globRe(base); try { names = fs.readdirSync(srcDir).filter(f => re.test(f)); } catch {} } else names = [base];
    for (const nm of names) { const src = path.join(srcDir, nm); if (!fs.existsSync(src)) continue; try { copyAny(src, path.join(dest, dir, nm)); n++; } catch (e) { warn(st, `collect ${rel}: ${e.code || e.message}`); } }
  }
  st.collected = n;
}
function tarBin() { return WIN ? path.join(process.env.SystemRoot || 'C:\\Windows', 'System32', 'tar.exe') : 'tar'; }
function packOutbox(p, st) {
  const arch = path.join(p.J, 'outbox.tgz');
  for (const f of fs.readdirSync(p.J)) if (/^outbox\.tgz(\.\d{3})?$/.test(f)) { try { fs.unlinkSync(path.join(p.J, f)); } catch {} }
  fs.mkdirSync(p.outbox, { recursive: true });
  const files = walkFiles(p.outbox);
  const r = spawnSync(tarBin(), ['-czf', arch, '-C', p.J, 'outbox'], { stdio: ['ignore', 'ignore', 'pipe'], windowsHide: true, timeout: 10 * 60000 });
  if (r.status !== 0 || !fs.existsSync(arch)) {
    if (st) warn(st, `could not pack the outbox (${String(r.stderr || (r.error && r.error.code) || 'tar failed').trim().slice(0, 160)}): copy the files in outbox/ one by one instead`);
    return { archive: null, files: files.length, bytes: files.reduce((a, f) => a + f.bytes, 0), list: files.slice(0, 200) };
  }
  const size = fs.statSync(arch).size; const parts = [];
  if (size > PART_BYTES) {   // CopyToBox moves at most 100 MiB per file
    const fd = fs.openSync(arch, 'r'); const buf = Buffer.alloc(8 * 1024 * 1024);
    for (let i = 0, off = 0; off < size; i++) {
      const name = `outbox.tgz.${String(i).padStart(3, '0')}`; const out = fs.openSync(path.join(p.J, name), 'w'); let n = 0;
      while (n < PART_BYTES && off < size) { const k = fs.readSync(fd, buf, 0, Math.min(buf.length, PART_BYTES - n, size - off), off); fs.writeSync(out, buf, 0, k); n += k; off += k; }
      fs.closeSync(out); parts.push(name);
    }
    fs.closeSync(fd); fs.unlinkSync(arch);
  }
  return { archive: parts.length ? null : 'outbox.tgz', parts, bytes: size, files: files.length, list: files.slice(0, 200) };
}

// ------------------------------------------------------------------------------------------------------ status helpers
function supervisorAlive(st) {
  if (alive(st.supervisor_pid)) return true;
  const q = Date.parse(st.queued_at || 0);
  return st.state === 'starting' && Number.isFinite(q) && Date.now() - q < START_GRACE_MS;
}
function effectiveStatus(p) {
  const st = readJSON(p.status, null) || { state: fs.existsSync(p.job) ? 'new' : 'missing' };
  if (ACTIVE.has(st.state) && !supervisorAlive(st)) st.state = 'lost';
  return st;
}
function flagsFor(p) {
  const job = readJSON(p.job, null); if (!job) return '';
  try { const f = gateFlags(job, { J: p.J }); return f.length ? ' ' + f.join(' ') : ''; } catch { return ''; }
}
function nextHint(p, st) {
  const R = `node "${fwd(SELF)}"`, J = `"${fwd(p.J)}"`, G = flagsFor(p);
  switch (st.state) {
    case 'new': return `${R} run ${J}${G}`;
    case 'queued': case 'starting': case 'running': return `${R} wait ${J} 25   (or keep following with: ${R} run ${J})`;
    case 'done': return st.outbox && (st.outbox.archive || (st.outbox.parts || []).length)
      ? `copy ${fwd(path.join(p.J, st.outbox.archive || st.outbox.parts[0]))}${st.outbox.parts && st.outbox.parts.length ? ' (and the other parts)' : ''} to the box (CopyToBox), unpack it there and check it${(st.warnings || []).length ? ' - read "warnings" first' : ''}`
      : `copy the files in ${fwd(p.outbox)} to the box (CopyToBox)`;
    case 'failed': return `read "error", fix the cause, then: ${R} resume ${J}${G}`;
    case 'stopped': return `${R} resume ${J}${G}   (continues the same session)`;
    case 'lost': return `the supervisor died (reboot or kill): ${R} resume ${J}${G}`;
    default: return `${R} status ${J}`;
  }
}
function summary(p, st) {
  const tasks = Object.entries(st.tasks || {}).map(([id, t]) => ({ id, name: t.name, status: t.status, agents: t.agents, done: t.done, err: t.err, failed_agents: t.failed_agents, tokens: t.tokens, result_ok: t.result_ok }));
  const L = st.limits || null;
  return { ok: true, job: fwd(p.J), id: path.basename(p.J), state: st.state, engine: st.engine || null, attempt: st.attempt || 0,
    started: st.started || null, ended: st.ended || null, updated: st.updated || null, last_event: st.last_event || null, events: st.events || 0,
    session: st.session_id || st.thread_id || null, workflow_runs: st.workflow_runs || [], tasks,
    limits: L && (L.status !== undefined ? { status: L.status, five_hour: L.five_hour && L.five_hour.utilization, seven_day: L.seven_day && L.seven_day.utilization } : L),
    tokens: st.tokens || null, cost_usd_list_price: st.cost_usd ?? null, result_text: String(st.result_text || '').slice(0, 600),
    error: st.error || null, warnings: st.warnings || [], gates: st.gates || null, outbox: st.outbox ? { archive: st.outbox.archive, parts: st.outbox.parts, files: st.outbox.files, bytes: st.outbox.bytes } : null,
    next: nextHint(p, st) };
}

// ------------------------------------------------------------------------------------------- supervisor (detached child)
function killTree(pid, hard = false) {
  if (!pid) return;
  if (WIN) { spawnSync('taskkill.exe', ['/PID', String(pid), '/T', '/F'], { stdio: 'ignore', windowsHide: true }); return; }
  const sig = hard ? 'SIGKILL' : 'SIGTERM';
  try { process.kill(-pid, sig); } catch { try { process.kill(pid, sig); } catch {} }
}
function countRunning(root, self) {
  let n = 0; let ents = []; try { ents = fs.readdirSync(root, { withFileTypes: true }); } catch { return 0; }
  for (const e of ents) {
    if (!e.isDirectory()) continue; const d = path.join(root, e.name); if (path.resolve(d) === path.resolve(self)) continue;
    const s = readJSON(path.join(d, 'status.json')); if (s && s.state === 'running' && alive(s.supervisor_pid)) n++;
  }
  return n;
}
async function supervise(jobdir) {
  const p = jobPaths(jobdir);
  let st = readJSON(p.status, {}) || {};
  const pending = st.pending || {};
  const attempt = (st.attempt || 0) + 1;
  const progLine = line => {
    const l = String(line).replace(/\s+/g, ' ').slice(0, 240);
    fs.appendFileSync(p.progress, `${now()} ${l}\n`);
    st.last_event = { at: now(), what: l.slice(0, 160) };
  };
  if (fs.existsSync(p.stop)) {   // `stop` arrived before this supervisor was up
    Object.assign(st, { state: 'stopped', ended: now(), updated: now(), pending: undefined, error: 'stopped before the engine started' });
    progLine('stopped before the engine started'); writeJSON(p.status, st); return;
  }
  if (pending.fresh) {
    (st.history ||= []).push({ attempt: st.attempt, session_id: st.session_id, thread_id: st.thread_id, state: st.state, ended: st.ended });
    for (const k of ['session_id', 'thread_id', 'workflow_runs', 'tasks', 'results', 'final', 'cost_usd', 'tokens']) delete st[k];
  }
  const grants = pending.grants || {};
  Object.assign(st, { attempt, state: 'running', supervisor_pid: process.pid, engine_pid: null, started: now(), ended: null, updated: now(),
    exit_code: null, error: null, final: null, result_text: null, warnings: [], pending: undefined, _init: false, _fatal: null, _quota: null,
    _allow_billing: !!grants.allow_api_billing });
  st.first_started ||= st.started;
  const failEarly = (e, what = 'failed before start') => {
    Object.assign(st, { state: 'failed', error: e.message + (e.fix ? ` — ${e.fix}` : ''), ended: now() });
    progLine(`${what}: ${e.message}`); writeJSON(p.status, st);
  };
  let ctx;
  try {
    ctx = materialize(p);
    checkGates(ctx.job, grants, { J: p.J, P: ctx.P, cwd: ctx.job.cwd ? path.resolve(p.J, ctx.job.cwd) : null });   // job.json may have changed since `start`
  } catch (e) { failEarly(e); return; }
  const { job } = ctx;
  st.engine = job.engine; st.kind = job.kind || null; st.gates = gatesLine(job, grants);
  if (ctx.unknown.length) warn(st, `job.json has unknown fields (ignored): ${ctx.unknown.join(', ')}`);
  progLine(`attempt ${attempt} ${job.engine}${job.kind ? ` ${job.kind}` : ''} - ${st.gates}${ctx.wired ? ` - ${ctx.wired.text}` : ''}`);
  writeJSON(p.status, st);

  // soft concurrency cap per jobs folder (several workflows at once is fine; a dozen is not), and one job at a time per
  // queue_group (chapter jobs: "render" — only one rendering workflow at a time)
  const maxPar = job.max_parallel || Number(process.env.DELEG_MAX_PARALLEL || (onBox() ? 2 : 3));   // the bot's computer (8 vCPU, 15 GiB) also renders
  const root = path.dirname(p.J), group = job.queue_group || null;
  // box-wide: on the bot's computer at most boxSlots() agent jobs at once over EVERY jobs folder (projects, tests)
  const slots = job.kind === 'preflight' ? 0 : boxSlots();
  let slot = -1;
  const blocked = () => {
    if (countRunning(root, p.J) >= maxPar) return 'folder';
    if (group && !tryGroup(root, group, p.J)) return 'group';
    if (slots && slot < 0 && (slot = trySlot(slots, p.J)) < 0) return 'box';
    return null;
  };
  try {
    let shown = null;
    for (let why = blocked(); why; why = blocked()) {
      if (fs.existsSync(p.stop)) { Object.assign(st, { state: 'stopped', ended: now(), error: 'stopped while queued' }); progLine('stopped while queued'); writeJSON(p.status, st); return; }
      if (st.state !== 'queued' || shown !== why) {
        st.state = 'queued'; shown = why;
        const h = group ? readJSON(groupLockPath(root, group)) : null;
        progLine(why === 'folder' ? `queued: ${maxPar} jobs already running in ${fwd(root)} (max_parallel ${maxPar})`
          : why === 'group' ? `queued: one "${group}" job at a time and ${h && h.job ? path.basename(h.job) : 'another job'} is running`
            : `queued: ${slots} agent jobs already run on this computer (box-wide limit; renders share it): ${slotHolders(slots).join(', ') || 'another job'}`);
        writeJSON(p.status, st);
      }
      await sleep(5000);
    }
    if (st.state === 'queued') { st.state = 'running'; st.started = now(); }
    await superviseRun(p, st, ctx, pending, attempt, progLine, failEarly, grants);
  } finally { if (group) releaseGroup(root, group, p.J); if (slot >= 0) releaseSlot(slot, p.J); }
}
// Box-wide slots: $SLOP_HOME/agents/slots/slot-<i>.lock holds {job, pid}; a dead supervisor's slot is taken over.
function boxSlots() {
  const n = Number(process.env.DELEG_BOX_SLOTS ?? (onBox() ? 2 : 0));
  return Number.isFinite(n) && n > 0 ? Math.floor(n) : 0;
}
const slotsDir = () => path.join(slopHome(), 'agents', 'slots');
function supervisorPid(pid) {   // alive AND (where /proc exists) still a deleg supervisor: a reused pid after a reboot is not
  if (!alive(pid)) return false;
  const cmd = readText(`/proc/${pid}/cmdline`);
  return cmd == null || cmd.includes('_supervise') || cmd.includes('deleg');
}
function trySlot(n, J) {
  try { fs.mkdirSync(slotsDir(), { recursive: true }); } catch { return 0; }   // cannot keep slots here: never block
  for (let i = 0; i < n; i++) {
    const f = path.join(slotsDir(), `slot-${i}.lock`);
    for (let k = 0; k < 2; k++) {
      try { fs.writeFileSync(f, JSON.stringify({ job: fwd(J), pid: process.pid, at: now() }), { flag: 'wx' }); return i; }
      catch (e) {
        if (e.code !== 'EEXIST') return i;
        const h = readJSON(f); let age = 0; try { age = Date.now() - fs.statSync(f).mtimeMs; } catch {}
        if (h && h.job === fwd(J) && h.pid === process.pid) return i;
        if ((h && !supervisorPid(h.pid)) || (!h && age > 30000)) { const t = `${f}.${process.pid}.stale`; try { fs.renameSync(f, t); fs.unlinkSync(t); } catch {} continue; }
        break;
      }
    }
  }
  return -1;
}
function releaseSlot(i, J) {
  const f = path.join(slotsDir(), `slot-${i}.lock`); const h = readJSON(f);
  if (h && h.job === fwd(J) && h.pid === process.pid) { try { fs.unlinkSync(f); } catch {} }
}
function slotHolders(n) {
  const out = [];
  for (let i = 0; i < n; i++) { const h = readJSON(path.join(slotsDir(), `slot-${i}.lock`)); if (h && h.job) out.push(path.basename(h.job)); }
  return out;
}
const groupLockPath = (root, group) => path.join(root, `.queue-${slug(group)}.lock`);
function tryGroup(root, group, J) {
  const f = groupLockPath(root, group);
  for (let i = 0; i < 3; i++) {
    try { fs.writeFileSync(f, JSON.stringify({ job: fwd(J), pid: process.pid, at: now() }), { flag: 'wx' }); return true; }
    catch (e) {
      if (e.code !== 'EEXIST') return true;   // cannot create a lock here: never block the job on it
      const h = readJSON(f); let age = 0; try { age = Date.now() - fs.statSync(f).mtimeMs; } catch {}
      if (h && h.job === fwd(J) && h.pid === process.pid) return true;
      if ((h && !alive(h.pid)) || (!h && age > 30000)) { const t = `${f}.${process.pid}.stale`; try { fs.renameSync(f, t); fs.unlinkSync(t); } catch {} continue; }
      return false;
    }
  }
  return false;
}
function releaseGroup(root, group, J) {
  const f = groupLockPath(root, group); const h = readJSON(f);
  if (h && h.job === fwd(J) && h.pid === process.pid) { try { fs.unlinkSync(f); } catch {} }
}
async function superviseRun(p, st, ctx, pending, attempt, progLine, failEarly, grants) {
  const { job, P, slop } = ctx;
  const allowBilling = !!grants.allow_api_billing;
  // the toolkit runtime the brief's checks need, proven on THIS machine before the engine starts
  const req = new Set(job.requires || []);
  if (req.size) {
    progLine(`checking the toolkit runtime here: ${[...req].join(', ')}`); writeJSON(p.status, st);
    const tc = toolkitCheck(slop, req); st.toolkit = tc;
    if (!tc.ok) { failEarly(new UserError(tc.error, tc.fix), 'toolkit check failed'); return; }
  }

  // prompt for this attempt: a short preface + the brief (or the resume prompt)
  const resumeFile = pending.resume_prompt ? path.resolve(p.J, pending.resume_prompt) : null;
  const body = fs.readFileSync(resumeFile || ctx.promptFile, 'utf8');
  const preface = job.engine === 'raw' ? '' : [
    `You are a delegated ${job.engine} session running unattended on the user's own computer for the Claudia music-video toolkit. Nobody answers questions mid-run: make sensible calls, write them down, and finish.`,
    `Job folder: ${fwd(p.J)}. Project folder: ${P ? fwd(P) : '(none)'}. Deliverables go exactly where the brief says (some briefs write project files, e.g. board/ or engine/ch/, which the runner collects); everything else you write (reports, notes, results) goes in ${fwd(p.outbox)}. Write continuously, so a cut at any moment leaves valid files.`,
    attempt > 1 ? (resumeFile ? `This is attempt ${attempt}: a continuation of an earlier attempt of this job.` : `This is attempt ${attempt} of this job: an earlier session ended. Read ${fwd(path.join(p.outbox, 'handoff.md'))} and ${fwd(path.join(p.outbox, 'report.md'))} first if they exist, and continue; do not redo finished work.`) : '',
  ].filter(Boolean).join('\n') + '\n\n';
  const promptFile = path.join(p.J, `prompt-${attempt}.md`);
  if (job.engine !== 'raw') fs.writeFileSync(promptFile, preface + body);
  if (!st.session_id && !st.thread_id) st.planned_session_id = crypto.randomUUID();
  const cwd = job.cwd ? path.resolve(p.J, job.cwd) : (P || p.J);
  const addDirs = [...new Set([p.J, ...(P && path.resolve(P) !== path.resolve(cwd) ? [P] : []), TOOLKIT_DIR, ...(job.add_dirs || []).map(d => path.resolve(p.J, d))])].map(fwd);

  let eng, b;
  try {
    eng = resolveEngine(job);
    b = buildArgv(job, { J: p.J, st, promptFile, cwd, addDirs, allowBilling });
  } catch (e) { failEarly(e); return; }
  const cmd = b.cmd || eng.cmd, argv = [...eng.pre, ...b.argv];
  const { env, stripped } = buildEnv(job, { J: p.J, P, slop, allowBilling });
  st.argv = [cmd, ...argv].map(String); st.cwd = fwd(cwd); st.env_stripped = stripped;
  const rawFd = fs.openSync(path.join(p.J, `raw-${attempt}.jsonl`), 'a');
  const errPath = path.join(p.J, `stderr-${attempt}.log`); const errFd = fs.openSync(errPath, 'a');

  let child, spawnErr = null;
  try {
    child = spawn(cmd, argv, { cwd, env, stdio: [b.stdin != null ? 'pipe' : 'ignore', 'pipe', errFd], windowsHide: true, detached: !WIN });
  } catch (e) { spawnErr = e; }
  let exit;
  if (spawnErr) exit = { code: -1 };
  else {
    st.engine_pid = child.pid || null; writeJSON(p.status, st);
    if (child.pid) progLine(`start attempt ${attempt} ${job.engine} pid ${child.pid}${resumeFile ? ' (resume)' : ''}${stripped.length ? ` env stripped: ${stripped.join(',')}` : ''}`);
    if (b.stdin != null) { child.stdin.on('error', () => {}); child.stdin.end(b.stdin); }
    let buf = '', lastFlush = 0, killing = null;
    const dec = new StringDecoder('utf8');
    const flush = force => { const t = Date.now(); if (force || t - lastFlush > 1000) { lastFlush = t; st.updated = now(); writeJSON(p.status, st); } };
    const kill = (why, stateAfter) => {
      if (killing) return; killing = { why, stateAfter }; progLine(`stopping engine: ${why}`); killTree(child.pid);
      setTimeout(() => killTree(child.pid, true), 8000).unref();
    };
    const onLine = line => {
      line = line.trim(); if (!line) return;
      st.events = (st.events || 0) + 1;
      let ev; try { ev = JSON.parse(line); } catch { progLine(`non-json: ${line.slice(0, 160)}`); return; }
      let lines = []; try { lines = norm(job.engine, ev, st, job); } catch (e) { lines = [`parse error: ${e.message}`]; }
      for (const l of lines) progLine(l);
      if (!lines.length) st.last_event = { at: now(), what: String(ev.type || ev.payload_type || 'event').slice(0, 60) };
      if (st._fatal) kill(st._fatal, 'failed');
      else if (st._quota) kill(`usage guard: ${st._quota}`, 'stopped');
      flush(false);
    };
    child.stdout.on('data', d => {
      fs.writeSync(rawFd, d); buf += dec.write(d); let i;
      while ((i = buf.indexOf('\n')) >= 0) { const line = buf.slice(0, i); buf = buf.slice(i + 1); onLine(line); }
    });
    const timeoutS = job.timeout_s || DEFAULT_TIMEOUT_S;
    const timer = setTimeout(() => kill(`timeout after ${timeoutS} s (job.json "timeout_s")`, 'failed'), timeoutS * 1000);
    const stopPoll = setInterval(() => { if (fs.existsSync(p.stop)) kill('stop requested', 'stopped'); }, 2000);
    exit = await new Promise(res => {
      let settled = false; const once = v => { if (!settled) { settled = true; res(v); } };
      child.on('error', e => { spawnErr = e; once({ code: -1 }); });
      child.on('close', (code, sig) => once({ code: code ?? (sig ? 128 : -1), sig }));
    });
    clearTimeout(timer); clearInterval(stopPoll);
    buf += dec.end(); if (buf.trim()) onLine(buf);
    exit.killing = killing;
  }
  try { fs.closeSync(rawFd); } catch {} try { fs.closeSync(errFd); } catch {}

  // ---- settle: decide the state, harvest, collect, pack, then write the terminal status (followers wait for it)
  if (job.engine === 'codex' && st.thread_id) st.limits = codexLimits(st.thread_id) || st.limits;
  if (job.engine === 'claude') harvestClaude(st, p);
  const stopFlag = fs.existsSync(p.stop);
  const errTail = () => { const t = (readText(errPath) || '').trim(); return t ? ` | stderr: ${t.slice(-600).replace(/\s+/g, ' ')}` : ''; };
  let state, error = null;
  if (spawnErr) { state = 'failed'; error = spawnErr.code === 'ENOENT' ? `engine executable not found: ${cmd} — install it or set "engine_bin" in job.json` : `could not start the engine: ${spawnErr.message}`; }
  else if (stopFlag || (exit.killing && exit.killing.stateAfter === 'stopped')) { state = 'stopped'; error = exit.killing && exit.killing.why !== 'stop requested' ? exit.killing.why : null; }
  else if (exit.killing) { state = 'failed'; error = exit.killing.why; }
  else if (job.engine === 'raw') { state = exit.code === 0 ? 'done' : 'failed'; if (state === 'failed') error = `command exited with code ${exit.code}${errTail()}`; }
  else if (exit.code === 0 && st.final && !st.final.is_error) state = 'done';
  else { state = 'failed'; error = st.final && st.final.is_error ? `${st.final.subtype && !/^(success|completed)$/.test(st.final.subtype) ? `${st.final.subtype}: ` : ''}${st.final.text.slice(0, 800)}` : `engine exited with code ${exit.code} without a final result${errTail()}`; }
  if (state === 'done' && job.engine === 'claude' && job.workflow && !(st.workflow_runs || []).length) warn(st, 'the brief asked for a workflow but none was launched: check result_text');
  if (state === 'done' && st.bg_tasks) warn(st, `${st.bg_tasks} background task(s) were still listed at exit`);
  if (state === 'done' && job.engine !== 'raw' && !fs.existsSync(path.join(p.outbox, 'report.md'))) warn(st, 'no outbox/report.md: the worker did not write its report');
  st.result_text = st.final ? st.final.text : (st.last_text || null);
  Object.assign(st, { exit_code: exit.code, error, ended: now() });
  try { collectFiles(job, p, P, st); } catch (e) { warn(st, `collect failed: ${e.message}`); }
  appendRuns(p, st, job, ctx, state);
  const clean = { ...st, state }; for (const k of Object.keys(clean)) if (k.startsWith('_')) delete clean[k];
  try { fs.mkdirSync(p.outbox, { recursive: true }); writeJSON(path.join(p.outbox, '_status.json'), clean); } catch {}
  try { if (fs.existsSync(p.runs)) copyAny(p.runs, path.join(p.outbox, '_runs')); } catch {}
  try { st.outbox = packOutbox(p, st); } catch (e) { warn(st, `pack failed: ${e.message}`); }
  progLine(`exit ${exit.code} state ${state}${error ? ' - ' + error.slice(0, 160) : ''}${(st.warnings || []).length ? ` (${st.warnings.length} warning(s))` : ''}`);
  st.state = state; st.updated = now();
  for (const k of Object.keys(st)) if (k.startsWith('_')) delete st[k];
  writeJSON(p.status, st);
}
function appendRuns(p, st, job, ctx, state) {
  try {
    if (!fs.existsSync(p.runsMd)) fs.writeFileSync(p.runsMd, '# Runs of this job (written by the runner, never by hand; resume with the session/run ids)\n\n| attempt | engine | session / thread | workflow runs | script | args | state | ended |\n|---|---|---|---|---|---|---|---|\n');
    const row = [st.attempt, job.engine, st.session_id || st.thread_id || '-', (st.workflow_runs || []).join(' ') || '-',
      ctx.wfPath ? fwd(path.relative(p.J, ctx.wfPath)) : '-', ctx.wfPath ? 'wf/args.json' : '-', state, now()];
    fs.appendFileSync(p.runsMd, `| ${row.join(' | ')} |\n`);
  } catch {}
}

// ------------------------------------------------------------------------------------------------------------ launching
function launch(J) {   // double spawn: the supervisor is orphaned from the calling shell's process tree
  const c = spawn(process.execPath, [SELF, '_launch2', J], { detached: true, stdio: 'ignore', windowsHide: true });
  c.unref();
}
function startJob(p, opt = {}) {
  const st = readJSON(p.status, {}) || {};
  if (ACTIVE.has(st.state) && supervisorAlive(st)) return { already: true, st };
  if (TERMINAL.has(st.state) && !opt.fresh && !opt.resume) {
    throw new UserError(`job is already ${st.state}${st.error ? ` (${String(st.error).slice(0, 200)})` : ''}`,
      st.state === 'done' ? 'Nothing to do. To run it again from scratch: start --fresh. To continue the same session with new instructions: resume <jobdir> <prompt-file>.'
        : 'resume <jobdir> continues the same session (keeps finished work); start --fresh starts over.');
  }
  const m = materialize(p);
  const grants = opt.grants || {};
  checkGates(m.job, grants, { J: p.J, P: m.P, cwd: m.job.cwd ? path.resolve(p.J, m.job.cwd) : null });   // refuse in the foreground
  resolveEngine(m.job);   // fail now, in the foreground, if the engine is missing
  try { fs.unlinkSync(p.stop); } catch {}
  const pending = { grants, fresh: !!opt.fresh, resume_prompt: opt.resume || null };
  writeJSON(p.status, { ...st, state: 'starting', engine: m.job.engine, queued_at: now(), updated: now(), error: null, pending });
  launch(p.J);
  return { already: false, job: m.job, unknown: m.unknown, wired: m.wired };
}

// ------------------------------------------------------------------------------------------------------------- commands
// The user's choice from `slop agents use ENGINE --for director|review` ($SLOP_HOME/onboard.json "agents.use"): the
// default engine of a new job when the command line, the spec and the template name none. Only an engine the brief
// lists ("engines:" line) qualifies. {engine|null, pref, role, note}: engine null = the preference does not apply here
// (the note says why). The Workflow tool is Claude Code's: with another engine a workflow brief runs without it.
function preferredEngine(meta) {
  const d = readJSON(path.join(slopHome(), 'onboard.json'), null);
  const use = (d && d.agents && d.agents.use) || {};
  const role = /review|safety/.test(meta.name || '') ? 'review' : 'director';
  const e = use[role] || use.director;
  if (!e || !ENGINES.includes(e) || e === 'raw') return null;
  const via = use[role] ? role : 'director';
  if (meta.engines && !new RegExp(`\\b${e}\\b`).test(meta.engines))
    return { engine: null, pref: e, role: via, note: `your ${via} agent is ${e} (slop agents use), but brief "${meta.name}" does not list it (engines: ${meta.engines}), so this job uses claude. Add --engine ${e} only if you are sure the brief works with it.` };
  return { engine: e, pref: e, role: via, note: null };
}
// Gemini CLI's chosen sign-in (settings.json security.auth.selectedType), e.g. "gemini-api-key" or "oauth-personal".
function geminiAuthType() {
  const home = process.env.GEMINI_CLI_HOME ? path.resolve(process.env.GEMINI_CLI_HOME) : HOME;
  const s = readJSON(path.join(home, '.gemini', 'settings.json'), null) || {};
  return (s.security && s.security.auth && s.security.auth.selectedType) || s.selectedAuthType || null;
}
function cmdNew(pos, opt) {
  const target = pos[0];
  if (!target) throw new UserError('new needs a job folder, or "auto" together with --project', 'node deleg.mjs new auto --project <project folder or name> --brief <name>   (list: node deleg.mjs templates)');
  const spec = opt.spec ? readJSONStrict(path.resolve(opt.spec), 'spec file') : {};
  const briefName = opt.brief || spec.brief_template || spec.brief;
  if (!briefName) throw new UserError('new needs --brief <template name or .md path>', `Templates: ${listBriefs().join(', ')}`);
  const tpl = resolveBrief(briefName);
  const { meta, body } = parseTemplate(tpl);
  let P = (opt.project || spec.project) ? resolveProjectArg(opt.project || spec.project) : null;
  let J;
  if (target === 'auto') { if (!P) throw new UserError('"auto" needs --project', 'node deleg.mjs new auto --project <project> --brief <name>'); J = path.join(P, 'jobs', newJobId(meta.name)); }
  else J = path.resolve(target);
  if (!P) { const g = path.resolve(J, '..', '..'); if (fs.existsSync(path.join(g, 'project.json'))) P = g; }
  const fileVars = opt.vars ? readJSONStrict(path.resolve(opt.vars), '--vars file') : {};
  const sets = {};
  for (const s of opt.set) { const i = s.indexOf('='); if (i < 1) throw new UserError(`--set needs KEY=VALUE (got "${s}")`, 'Example: --set TITLE="My Song"'); sets[s.slice(0, i).trim()] = s.slice(i + 1); }
  const vars = { ...(P ? projectVars(P) : {}), ...(spec.vars || {}), ...fileVars, ...sets };
  const { text, missing } = fill(body, vars, new Set(RUNTIME_TOKENS));
  if (missing.length) throw new UserError(`brief "${meta.name}" needs values for: ${missing.join(', ')}`,
    missing.map(k => `--set ${k}=...  (${meta.vars[k] || 'see the template header'})`).join(' ; '));
  const D = meta.defaults || {};
  const wfExplicit = opt.workflow !== undefined || spec.workflow !== undefined;
  let workflow = opt.workflow !== undefined ? opt.workflow : (spec.workflow !== undefined ? spec.workflow : (D.workflow ?? null));
  if (workflow === 'none' || workflow === true) workflow = null;
  let engine = opt.engine || spec.engine || D.engine || null;
  let engineFrom = opt.engine ? 'command line (--engine)' : spec.engine ? 'spec file' : D.engine ? 'brief template' : null;
  let engineNote = null;
  if (!engine) {
    const pref = preferredEngine(meta);
    if (pref && pref.engine && pref.engine !== 'claude' && workflow && wfExplicit) {
      engineNote = `--workflow ${workflow} needs Claude Code (the Workflow tool), so this job uses claude, not your ${pref.role} agent ${pref.engine}. Without the workflow: --engine ${pref.engine} --workflow none`;
    } else if (pref && pref.engine) {
      engine = pref.engine; engineFrom = `your ${pref.role} agent (slop agents use ${pref.engine} --for ${pref.role})`;
      if (workflow && engine !== 'claude') {
        engineNote = `brief "${meta.name}" runs its "${workflow}" workflow only on Claude Code; ${engine} does the same work step by step instead (the brief's method without the Workflow tool; slower). For the workflow: --engine claude`;
        workflow = null;
      }
    } else if (pref) engineNote = pref.note;
    if (!engine) { engine = 'claude'; engineFrom = engineFrom || 'default (claude)'; }
  } else if (workflow && !wfExplicit && ['codex', 'muse', 'gemini'].includes(engine)) {
    // the template's default workflow needs Claude Code's Workflow tool; another engine does the brief step by step
    engineNote = `brief "${meta.name}" runs its "${workflow}" workflow only on Claude Code; ${engine} does the same work step by step instead (the brief's method without the Workflow tool; slower).`;
    workflow = null;
  }
  if (!ENGINES.includes(engine)) throw new UserError(`unknown engine ${engine}`, `Use one of ${ENGINES.join('|')}.`);
  if (workflow) resolveWorkflow(workflow);
  // every var the brief uses also reaches the workflow as a lower-case arg (numbers and lists converted)
  const autoArgs = {};
  const NUM = new Set(['DURATION', 'LEAD_MIN', 'MOTION_S', 'MOTION_CLIPS', 'ROUNDS', 'TOTAL', 'SLICES', 'T0', 'T1']);
  const LIST = { BANNED_WORDS: ',', TOPICS: ';', LIKES: ';', FIX_RULES: ';', BLOCK_RULES: ';' };
  for (const [k, v] of Object.entries(vars)) {
    if (v === undefined || v === null || v === '' || !body.includes(`{{${k}`) || RUNTIME_TOKENS.includes(k)) continue;
    let val = v;
    if (NUM.has(k) && v !== '' && Number.isFinite(Number(v))) val = Number(v);
    else if (LIST[k] && typeof v === 'string') val = v.split(LIST[k]).map(s => s.trim()).filter(Boolean);
    else if (typeof v === 'string' && /^\s*[[{]/.test(v)) { try { val = JSON.parse(v); } catch {} }
    autoArgs[k.toLowerCase()] = val;
  }
  const workflow_args = workflow ? { ...(D.workflow_args || {}), ...autoArgs, ...(spec.workflow_args || {}), ...(opt.args ? readJSONStrict(path.resolve(opt.args), '--args file') : {}) } : undefined;
  const jobFields = Object.fromEntries(Object.entries(spec).filter(([k]) => JOB_KEYS.has(k) && !['brief', 'vars', 'workflow_args', 'engine', 'workflow', 'id', 'created', 'brief_template'].includes(k)));
  const defaults = Object.fromEntries(Object.entries(D).filter(([k]) => JOB_KEYS.has(k) && !['engine', 'workflow', 'workflow_args'].includes(k)));
  const projectName = P ? String((readJSON(path.join(P, 'project.json'), {}) || {}).name || path.basename(P)) : null;
  const job = {
    id: path.basename(J), kind: opt.kind || spec.kind || D.kind || meta.name, engine, title: opt.title || spec.title || (vars.TITLE ? `${meta.name}: ${vars.TITLE}` : meta.name),
    created: now(), brief_template: meta.name, project_dir: P ? (fwd(path.relative(J, P)) || '.') : null, project_name: projectName, prompt_file: 'BRIEF.md',
    ...defaults, ...jobFields,
    ...(opt.model ? { model: opt.model } : {}), ...(opt.effort ? { effort: opt.effort } : {}), ...(opt.timeout ? { timeout_s: Number(opt.timeout) } : {}),
    workflow: workflow || null, ...(workflow ? { workflow_args } : {}), vars: Object.fromEntries(Object.entries(vars).filter(([k]) => body.includes(`{{${k}`))),
    brief: text,
  };
  if (job.wire_chapters) {   // collect exactly this job's chapter files (never another job's), checked now
    const chs = parseChapters((workflow_args && workflow_args.chapters) || vars.CHAPTERS);
    job.collect = [...new Set([...(job.collect || []).filter(c => !/^engine\/ch\//.test(fwd(c))), ...chs.map(c => `engine/ch/${c.file}`)])];
  }
  const notes = [];
  if (engine === 'gemini') {
    // the runner strips API keys from every job; a key chosen as Gemini's sign-in passes only through the pass-env gate
    if (geminiAuthType() === 'gemini-api-key' && !(job.pass_env || []).includes('GEMINI_API_KEY')) {
      job.pass_env = [...(job.pass_env || []), 'GEMINI_API_KEY'];
      notes.push('Gemini CLI signs in with GEMINI_API_KEY here, so job.json has "pass_env": ["GEMINI_API_KEY"] and the run command needs --pass-env GEMINI_API_KEY (ask the user first: the key can bill the Google Cloud project behind it).');
    }
    if ((job.requires || []).length && !(job.allowed_tools || []).length && job.approval_mode !== 'yolo')
      notes.push(`[unverified] headless Gemini CLI drops tools that need approval, so it probably cannot run the shell commands this brief's checks need (${job.requires.join(', ')}). Prefer --engine claude or codex for this brief, or give Gemini write-only work.`);
  }
  validateJob(job, jobPaths(J));
  const p = jobPaths(J);
  const flags = gateFlags(job, { J, P });
  const id = path.basename(J);
  const userCmd = `node "<TK>/runner/deleg.mjs" run "<PROJ>/jobs/${id}.job.json"${flags.length ? ' ' + flags.join(' ') : ''}`;
  const runHere = `node "${fwd(SELF)}" run "${fwd(J)}"${flags.length ? ' ' + flags.join(' ') : ''}`;
  const handoff = { copy_from_box: fwd(p.job), copy_to: `<PROJ>/jobs/${id}.job.json`, user_run_command: userCmd, run_here: runHere, gates_needed: flags,
    ...(flags.length ? { gates_note: `this job needs ${flags.join(' ')} on the run command: ask the user before running it, and say what each one allows (runner/README.md "Gates")` } : {}),
    next: `CopyFromBox ${fwd(p.job)} to <PROJ>/jobs/${id}.job.json on the user's computer (1 card), then ONE background command there: ${userCmd}   (<TK> = the toolkit folder on that computer, <PROJ> = the project folder there; runner/README.md §2). To run it on this machine instead: ${runHere}` };
  if (fs.existsSync(p.job)) {
    const old = readJSON(p.job, {});
    const same = old && JSON.stringify({ ...old, created: 0, id: 0 }) === JSON.stringify({ ...job, created: 0, id: 0 });
    if (!opt.force) {
      if (!same) throw new UserError(`a job already exists in ${fwd(J)}`, 'Use another folder (new auto ... makes a fresh one), or add --force to replace it (the old run moves to history/N/ in that folder).');
      return { ok: true, job_dir: fwd(J), job_json: fwd(p.job), unchanged: true, engine: old.engine, workflow: old.workflow || null, engine_from: engineFrom, ...(engineNote ? { engine_note: engineNote } : {}), ...(notes.length ? { notes } : {}), ...handoff };
    }
    const old_st = effectiveStatus(p);
    if (ACTIVE.has(old_st.state)) throw new UserError(`the job in ${fwd(J)} is ${old_st.state}`, `Stop it first (node deleg.mjs stop "${fwd(J)}"), then run new --force again.`);
  }
  const archived = fs.existsSync(J) ? archiveRun(J) : null;   // --force: a clean folder (status, progress, outbox … go to history/N/)
  fs.mkdirSync(p.outbox, { recursive: true });
  fs.writeFileSync(path.join(J, 'BRIEF.md'), text);
  if (workflow) { fs.mkdirSync(p.wf, { recursive: true }); fs.copyFileSync(resolveWorkflow(workflow), path.join(p.wf, path.basename(String(workflow)).replace(/\.js$/, '') + '.js')); }
  writeJSON(p.job, job);
  return { ok: true, job_dir: fwd(J), job_json: fwd(p.job), brief: meta.name, engine, engine_from: engineFrom, ...(engineNote ? { engine_note: engineNote } : {}),
    workflow: workflow || null, project_dir: P ? fwd(P) : null, ...(notes.length ? { notes } : {}),
    ...(archived ? { archived_previous_run: archived } : {}), collect: job.collect || [],
    note: 'job.json is self-contained (the brief is embedded): copying job.json alone to the user\'s computer is enough; the runner rebuilds BRIEF.md and wf/ there.',
    ...handoff };
}
function cmdStatus(pos) { const p = requireJobDir(pos[0], 'status'); return summary(p, effectiveStatus(p)); }
async function follow(p, { maxSecs, cursorName, heartbeatS }) {
  const cur = path.join(p.J, cursorName);
  let off = Number(readText(cur) || 0) || 0; const t0 = performance.now(); let beat = performance.now();   // monotonic: a wall-clock jump must not end a wait
  const drain = () => {
    let size = 0; try { size = fs.statSync(p.progress).size; } catch {}
    if (size < off) off = 0;
    if (size > off) {
      const fd = fs.openSync(p.progress, 'r'); const b = Buffer.alloc(size - off); fs.readSync(fd, b, 0, b.length, off); fs.closeSync(fd);
      const nl = b.lastIndexOf(10);
      if (nl >= 0) { process.stdout.write(b.subarray(0, nl + 1)); off += nl + 1; try { fs.writeFileSync(cur, String(off)); } catch {} }
    }
  };
  for (;;) {
    drain();
    const st = effectiveStatus(p);
    if (TERMINAL.has(st.state) || st.state === 'lost' || st.state === 'new' || st.state === 'missing') { drain(); return st; }
    if (performance.now() - t0 > maxSecs * 1000) return st;
    if (heartbeatS && performance.now() - beat > heartbeatS * 1000) { beat = performance.now(); process.stdout.write(`${now()} ... ${st.state}, ${st.events || 0} events, last: ${(st.last_event && st.last_event.what) || '-'}`.slice(0, 240) + '\n'); }
    await sleep(1000);
  }
}
// `wait` and `run` ALWAYS end with one "STATUS {json}" line, errors included (the bot reads the last line only).
function statusError(p, e) {
  const base = p ? summary(p, effectiveStatus(p)) : { job: null, state: 'error' };
  process.stdout.write('STATUS ' + JSON.stringify({ ...base, ok: false, error: e.message, fix: e.fix || null, ...(p ? { next: e.fix || base.next } : {}) }) + '\n');
  return 1;
}
async function cmdWait(pos) {
  let p = null;
  try { p = requireJobDir(pos[0], 'wait'); } catch (e) { if (e instanceof UserError) return statusError(p, e); throw e; }
  const secs = Math.max(1, Math.min(Number(pos[1] || 25) || 25, 3600));
  const st = await follow(p, { maxSecs: secs, cursorName: '.cursor-wait' });
  const s = summary(p, st); process.stdout.write('STATUS ' + JSON.stringify(s) + '\n');
  return ['failed', 'stopped', 'lost'].includes(st.state) ? 1 : 0;
}
async function cmdRun(pos, opt) {
  let p = null;
  try {
    p = requireJobDir(pos[0], 'run');
    const st0 = effectiveStatus(p);
    if (TERMINAL.has(st0.state)) { process.stdout.write(`${now()} job already ${st0.state}; not starting it again (resume or start --fresh to run more)\nSTATUS ${JSON.stringify(summary(p, st0))}\n`); return st0.state === 'done' ? 0 : 1; }
    if (st0.state === 'lost') { process.stdout.write(`STATUS ${JSON.stringify(summary(p, st0))}\n`); return 1; }
    if (!ACTIVE.has(st0.state)) { const r = startJob(p, { grants: grantsFrom(opt) }); process.stdout.write(`${now()} started ${r.job.engine} job ${path.basename(p.J)}${r.wired ? ` (${r.wired.text})` : ''}\n`); }
    else process.stdout.write(`${now()} re-attached to running job ${path.basename(p.J)}\n`);
  } catch (e) { if (e instanceof UserError) return statusError(p, e); throw e; }
  const onSig = () => { process.stdout.write(`${now()} follower detached; the job keeps running (status/wait/run to check)\n`); process.exit(0); };
  process.on('SIGINT', onSig); process.on('SIGTERM', onSig);
  await sleep(1200);
  const st = await follow(p, { maxSecs: Infinity, cursorName: '.cursor-run', heartbeatS: 600 });
  process.stdout.write('STATUS ' + JSON.stringify(summary(p, st)) + '\n');
  return st.state === 'done' ? 0 : 1;
}
function cmdStart(pos, opt) {
  const p = requireJobDir(pos[0], 'start');
  const r = startJob(p, { grants: grantsFrom(opt), fresh: !!opt.fresh });
  if (r.already) return { ...summary(p, effectiveStatus(p)), already_running: true };
  return { ok: true, job: fwd(p.J), state: 'starting', engine: r.job.engine, warnings: r.unknown.length ? [`unknown job.json fields: ${r.unknown.join(', ')}`] : [],
    next: `node "${fwd(SELF)}" wait "${fwd(p.J)}" 25` };
}
async function stopJob(p, opt = {}) {
  const st = effectiveStatus(p);
  fs.writeFileSync(p.stop, now());
  if (!ACTIVE.has(st.state) && st.state !== 'lost') return { ok: true, job: fwd(p.J), state: st.state, note: 'not running' };
  const sup = alive(st.supervisor_pid), eng = st.engine_pid && alive(st.engine_pid);
  if (eng && (sup || opt.force)) {
    killTree(st.engine_pid);
    if (!WIN) { for (let i = 0; i < 16 && alive(st.engine_pid); i++) await sleep(500); killTree(st.engine_pid, true); }
  }
  for (let i = 0; i < 24 && sup && !TERMINAL.has((readJSON(p.status, {}) || {}).state); i++) await sleep(500);
  let fin = readJSON(p.status, {}) || {};
  if (!TERMINAL.has(fin.state)) {   // no supervisor to settle it: settle here
    fin = { ...fin, state: 'stopped', ended: now(), updated: now(), error: sup ? 'stop requested; supervisor did not settle in 12 s' : 'stopped (the supervisor was gone)' };
    if (eng && !sup && !opt.force) fin.warnings = [...(fin.warnings || []), `engine pid ${st.engine_pid} may still run (no supervisor): stop --force kills it`];
    writeJSON(p.status, fin);
    fs.appendFileSync(p.progress, `${now()} stopped by request\n`);
  }
  return { ok: true, job: fwd(p.J), state: fin.state, killed: [st.engine_pid || null, st.supervisor_pid || null], next: nextHint(p, fin) };
}
async function cmdStop(pos, opt) { const p = requireJobDir(pos[0], 'stop'); return stopJob(p, { force: !!opt.force }); }
function cmdResume(pos, opt) {
  const p = requireJobDir(pos[0], 'resume');
  const st = effectiveStatus(p);
  if (ACTIVE.has(st.state)) throw new UserError('the job is still running', 'Stop it first (node deleg.mjs stop <jobdir>), then resume. A Workflow resume needs the previous run stopped.');
  const { job } = loadJob(p);
  const n = (st.attempt || 0) + 1;
  let rel;
  if (pos[1]) {
    const src = path.resolve(pos[1]); if (!fs.existsSync(src)) throw new UserError(`resume prompt file not found: ${fwd(src)}`, 'Write the instructions to a file and pass its path, or omit it for the automatic continuation.');
    rel = `resume-${n}.md`; fs.copyFileSync(src, path.join(p.J, rel));
  } else {
    const wfRun = (st.workflow_runs || [])[st.workflow_runs ? st.workflow_runs.length - 1 : 0];
    const wfFile = job.workflow ? path.join(p.wf, path.basename(String(job.workflow)).replace(/\.js$/, '') + '.js') : null;
    const args = readJSON(path.join(p.wf, 'args.json'));
    let text;
    if (job.engine === 'claude' && wfRun && wfFile && st.session_id) {
      text = `Resume the workflow of this job. Call the Workflow tool exactly once with scriptPath "${fwd(wfFile)}", resumeFromRunId "${wfRun}" and args ${JSON.stringify(args || {})} (pass args as a JSON object, not a string). Use no other tool before it. Completed agents return their cached results; only unfinished or edited ones run. Then end your turn and wait for the completion notice (do not poll). When it arrives, finish the remaining steps of ${fwd(path.join(p.J, 'BRIEF.md'))} (the workflow result to the outbox, outbox/report.md) and end.\n\nIf the resume is refused (no journal for the run), call the Workflow tool once with the same scriptPath and args and no resumeFromRunId instead: the agents check their files on disk and skip finished work.\n`;
    } else {
      text = `Continue this job from where the previous attempt stopped (${st.state}${st.error ? `: ${String(st.error).slice(0, 300)}` : ''}). The instructions are in ${fwd(path.join(p.J, 'BRIEF.md'))}: read it again. Read ${fwd(path.join(p.outbox, 'handoff.md'))} and ${fwd(path.join(p.outbox, 'report.md'))} if they exist, look at what is already in ${fwd(p.outbox)}, and do not redo finished work. Finish exactly as the brief says.\n`;
    }
    rel = `resume-${n}.md`; fs.writeFileSync(path.join(p.J, rel), text);
  }
  const r = startJob(p, { grants: grantsFrom(opt), resume: rel });
  return { ok: true, job: fwd(p.J), state: 'starting', attempt: n, resume_prompt: rel, session: st.session_id || st.thread_id || null, already_running: !!r.already,
    next: `node "${fwd(SELF)}" wait "${fwd(p.J)}" 25` };
}
function cmdWire(pos, opt) {
  if (!pos[0]) throw new UserError('wire needs a project folder', 'node deleg.mjs wire <project> --chapters <job.json|wf/args.json|chapters.json>   or: node deleg.mjs wire <project> --check --file 02_board.js --shots s011,s012');
  const P = resolveProjectArg(pos[0]);
  let chapters;
  if (opt.file && opt.file !== true) chapters = parseChapters([{ id: opt.id && opt.id !== true ? String(opt.id) : undefined, file: String(opt.file),
    shots: opt.shots && opt.shots !== true ? String(opt.shots).split(',').map(s => s.trim()).filter(Boolean) : [] }]);
  else if (opt.chapters && opt.chapters !== true) chapters = parseChapters(String(opt.chapters));
  else throw new UserError('wire needs --chapters <file or JSON> or --file <chapter.js>', 'Example: node deleg.mjs wire <project> --chapters <project>/jobs/<id>.job.json');
  return { project: fwd(P), ...(opt.check ? checkChapters(P, chapters) : wireChapters(P, chapters)) };
}
function cmdList(pos) {
  let root = path.resolve(pos[0] || '.');
  if (fs.existsSync(path.join(root, 'jobs')) && fs.statSync(path.join(root, 'jobs')).isDirectory()) root = path.join(root, 'jobs');
  if (!fs.existsSync(root)) throw new UserError(`folder not found: ${fwd(root)}`, 'Pass a jobs folder or a project folder.');
  const jobs = [];
  for (const e of fs.readdirSync(root, { withFileTypes: true })) {
    if (!e.isDirectory()) continue; const p = jobPaths(path.join(root, e.name)); if (!fs.existsSync(p.job)) continue;
    const job = readJSON(p.job, {}) || {}; const st = effectiveStatus(p);
    jobs.push({ id: e.name, kind: job.kind || null, engine: job.engine || null, state: st.state, attempt: st.attempt || 0, started: st.started || null,
      ended: st.ended || null, last_event: st.last_event || null, error: st.error ? String(st.error).slice(0, 200) : null, warnings: (st.warnings || []).length });
  }
  jobs.sort((a, b) => String(a.id).localeCompare(String(b.id)));
  return { ok: true, root: fwd(root), count: jobs.length, running: jobs.filter(j => ACTIVE.has(j.state)).length, jobs };
}
function cmdPack(pos) { const p = requireJobDir(pos[0], 'pack'); const st = readJSON(p.status, {}) || {}; const o = packOutbox(p, st); if (Object.keys(st).length) { st.outbox = o; writeJSON(p.status, st); } return { ok: !!(o.archive || (o.parts || []).length), job: fwd(p.J), ...o, list: undefined, warnings: st.warnings || [] }; }
function cmdUnpack(pos, opt = {}) {
  const [a, dest] = pos;
  if (!a || !dest) throw new UserError('unpack needs <archive> <destdir>', 'node deleg.mjs unpack outbox.tgz C:/path/to/dest   (for parts pass the .000 file)');
  const A = path.resolve(a); let src = A, tmp = null;
  if (/\.\d{3}$/.test(A)) {
    const stem = A.replace(/\.\d{3}$/, ''); const dir = path.dirname(A);
    const parts = fs.readdirSync(dir).filter(f => path.join(dir, f).startsWith(stem + '.') && /\.\d{3}$/.test(f)).sort();
    tmp = path.join(os.tmpdir(), `deleg-unpack-${process.pid}.tgz`); const out = fs.openSync(tmp, 'w');
    for (const f of parts) fs.writeSync(out, fs.readFileSync(path.join(dir, f))); fs.closeSync(out); src = tmp;
  }
  if (!fs.existsSync(src)) throw new UserError(`archive not found: ${fwd(A)}`, null);
  if (!opt.force) {   // a project sync must never land on a project whose job is running here: it would overwrite the files the job edits
    const ls = spawnSync(tarBin(), ['-tzf', src], { encoding: 'utf8', windowsHide: true, timeout: 20 * 60000, maxBuffer: 512 * 1024 * 1024 });
    const tops = new Set(String(ls.stdout || '').split(/\r?\n/).map(l => l.replace(/^\.\//, '').split('/')[0]).filter(Boolean));
    for (const t of tops) {
      const proj = path.join(path.resolve(dest), t);
      if (!fs.existsSync(path.join(proj, 'project.json'))) continue;
      const running = [];
      try { for (const e of fs.readdirSync(path.join(proj, 'jobs'), { withFileTypes: true })) { if (!e.isDirectory()) continue; const jp = jobPaths(path.join(proj, 'jobs', e.name)); if (fs.existsSync(jp.job) && ACTIVE.has(effectiveStatus(jp).state)) running.push(e.name); } } catch {}
      if (running.length) {
        if (tmp) { try { fs.unlinkSync(tmp); } catch {} }
        throw new UserError(`not unpacking: job(s) ${running.join(', ')} are running on ${fwd(proj)} and the archive would overwrite files they are editing`,
          `Wait until they end (node "${fwd(SELF)}" list "${fwd(proj)}" shows running: 0), then run the same unpack again. (--force overrides this; never use it while chapter jobs run.)`);
      }
    }
  }
  fs.mkdirSync(path.resolve(dest), { recursive: true });
  const r = spawnSync(tarBin(), ['-xzf', src, '-C', path.resolve(dest)], { encoding: 'utf8', windowsHide: true, timeout: 20 * 60000 });
  if (tmp) { try { fs.unlinkSync(tmp); } catch {} }
  if (r.status !== 0) throw new UserError(`tar could not extract ${fwd(A)}: ${String(r.stderr || (r.error && r.error.code) || '').trim().slice(0, 200)}`, 'Check the archive is complete (all parts copied) and the disk has space.');
  return { ok: true, archive: fwd(A), dest: fwd(path.resolve(dest)), files: walkFiles(path.resolve(dest)).length };
}
function cmdTemplates() {
  const briefs = listBriefs().map(n => { const { meta } = parseTemplate(path.join(BRIEFS_DIR, `${n}.md`)); return { name: meta.name, summary: meta.summary, engines: meta.engines, workflow: meta.defaults.workflow || null, vars: meta.vars }; });
  const workflows = listWorkflows().map(n => ({ file: n, ...workflowDoc(path.join(WORKFLOWS_DIR, `${n}.js`)) }));
  return { ok: true, briefs_dir: fwd(BRIEFS_DIR), workflows_dir: fwd(WORKFLOWS_DIR), runtime_tokens: RUNTIME_TOKENS, briefs, workflows };
}
function cmdDoctor(opt = {}) {
  const major = Number(process.versions.node.split('.')[0]);
  const slop = resolveSlop({});
  const res = { ok: true, runner: VERSION, node: process.version, node_ok: major >= 18, platform: `${process.platform}-${process.arch}`, toolkit_dir: fwd(TOOLKIT_DIR),
    projects_root: fwd(projectsRoot()), tar: null, slop: slop.cmd, slop_ok: null, render_ok: null, ffmpeg_ok: null, engines: {}, env_that_will_be_stripped: [], notes: [] };
  // the toolkit runtime: the briefs' checks (board audit, lyric gate, renders, lint) run on THIS computer
  const tc = toolkitCheck(slop, new Set(opt.render ? ['slop', 'render', 'ffmpeg'] : ['slop', 'ffmpeg']));
  Object.assign(res, { slop_ok: tc.slop_ok ?? null, slop_version: tc.slop_version ?? null, render_ok: tc.render_ok ?? null, ffmpeg_ok: tc.ffmpeg_ok ?? null });
  if (!tc.ok) { res.toolkit_error = tc.error; res.toolkit_fix = tc.fix; res.notes.push(`toolkit runtime not ready: ${tc.error}`); }
  if (!opt.render && tc.slop_ok) res.notes.push('render not checked: run doctor --render once (boots the renderer on a scratch project, about 5-20 s)');
  const t = spawnSync(tarBin(), ['--version'], { encoding: 'utf8', timeout: 8000, windowsHide: true });
  res.tar = t.status === 0 ? String(t.stdout).split(/\r?\n/)[0] : null;
  if (!res.tar) res.notes.push('tar not found: outboxes cannot be packed into one file; the bot must copy outbox files one by one');
  if (major < 20) res.notes.push(`node ${process.version}: works, but Node 20+ is recommended`);
  for (const e of ['claude', 'codex', 'muse', 'gemini']) {
    try {
      const r = resolveEngine({ engine: e });
      const v = spawnSync(r.cmd, [...r.pre, '--version'], { encoding: 'utf8', timeout: 15000, windowsHide: true, env: { ...process.env, MUSE_NO_AUTO_UPDATE: '1' } });
      const info = { found: true, cmd: fwd(r.cmd), via: r.via, version: String(v.stdout || '').trim().split(/\r?\n/)[0] || null, runs: v.status === 0 };
      if (e === 'codex') { const l = spawnSync(r.cmd, [...r.pre, 'login', 'status'], { encoding: 'utf8', timeout: 15000, windowsHide: true }); info.login = String(l.stdout || l.stderr || '').trim().split(/\r?\n/)[0] || null; }
      res.engines[e] = info;
    } catch (err) { res.engines[e] = { found: false, fix: err.fix || err.message }; }
  }
  res.env_that_will_be_stripped = [...BILLING_ENV, ...SECRET_ENV].filter(k => process.env[k]);
  if (!Object.values(res.engines).some(x => x.found)) { res.ok = false; res.error = 'no agent CLI found (claude, codex, muse or gemini)'; res.fix = 'On the bot\'s computer: slop agents install claude (or codex, muse, all), then slop agents login ENGINE. On the user\'s own computer: install Claude Code (claude.com/claude-code) or Codex (npm i -g @openai/codex) and sign in once in a terminal.'; }
  else if (!tc.ok) { res.ok = false; res.error = `the toolkit runtime is not ready on this computer: ${tc.error}`; res.fix = tc.fix; }
  res.next = !tc.ok ? tc.fix : !opt.render ? `node "${fwd(SELF)}" doctor --render` : `node "${fwd(SELF)}" selftest`;
  return res;
}
async function waitTerminal(p, secs) { const t0 = performance.now(); for (;;) { const st = effectiveStatus(p); if (TERMINAL.has(st.state) || st.state === 'lost') return st; if (performance.now() - t0 > secs * 1000) return st; await sleep(300); } }
async function cmdSelftest(opt) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'deleg-selftest-'));
  const checks = []; const check = (name, ok, detail) => checks.push({ name, ok: !!ok, detail });
  try {
    // 1. a fake Claude workflow job: the run must not end at the first result, and must flag the dead agent
    const A = jobPaths(path.join(dir, 'jobs', 'wf'));
    fs.mkdirSync(A.J, { recursive: true });
    writeJSON(A.job, { engine: 'claude', kind: 'selftest', workflow: null, brief: '# selftest\nDo nothing.\n', engine_bin: ['node', FAKE_ENGINE, '--as', 'claude', '--scenario', 'workflow'], timeout_s: 60 });
    startJob(A, { grants: { allow_raw: true } });   // runner-authored jobs: the fake engine is an engine_bin
    const a = await waitTerminal(A, 30);
    check('claude workflow job ends done', a.state === 'done', `${a.state} ${a.error || ''}`);
    check('second result (after the workflow) is the final one', (a.results || []).length === 2 && /workflow finished/i.test(a.result_text || ''), (a.result_text || '').slice(0, 80));
    check('workflow run id captured', (a.workflow_runs || []).length === 1, (a.workflow_runs || []).join(','));
    check('dead workflow agent flagged', (a.warnings || []).some(w => /failed/.test(w)), (a.warnings || [])[0]);
    check('outbox packed', a.outbox && (a.outbox.archive || (a.outbox.parts || []).length), a.outbox && a.outbox.archive);
    // 2. stop kills the engine's process tree
    const B = jobPaths(path.join(dir, 'jobs', 'stop'));
    fs.mkdirSync(B.J, { recursive: true });
    writeJSON(B.job, { engine: 'claude', brief: '# selftest\n', engine_bin: ['node', FAKE_ENGINE, '--as', 'claude', '--scenario', 'slow'], timeout_s: 60 });
    startJob(B, { grants: { allow_raw: true } });
    let b = effectiveStatus(B); for (let i = 0; i < 80 && !(b.engine_pid && (b.events || 0) > 0); i++) { await sleep(250); b = effectiveStatus(B); }
    const calls = (readText(path.join(B.J, 'fake-calls.jsonl')) || '').trim().split('\n').filter(Boolean).map(l => JSON.parse(l));
    const grand = calls.length && calls[calls.length - 1].grandchild_pid;
    await stopJob(B, {});
    const bs = await waitTerminal(B, 15);
    await sleep(500);
    check('stop ends the job as stopped', bs.state === 'stopped', bs.state);
    check('stop kills the engine and its children', !alive(b.engine_pid) && (!grand || !alive(grand)), `engine ${b.engine_pid} child ${grand}`);
  } catch (e) { check('selftest ran', false, e.message); }
  const ok = checks.every(c => c.ok);
  if (!opt.keep) { try { fs.rmSync(dir, { recursive: true, force: true }); } catch {} }
  return { ok, checks, dir: opt.keep ? fwd(dir) : null, ...(ok ? { next: 'the runner works on this computer; next: node deleg.mjs preflight claude  (one tiny real prompt on your plan)' } : { error: 'selftest failed', fix: 'Send the "checks" list to the bot; run with --keep to inspect the job folders.' }) };
}
// `preflight claude --workflow` proves the critical path of every Claude workflow job before a 1–3 h run: a headless
// Workflow launch whose subagent writes one file with Bash and one with Write under the job's permission flags
// (--permission-mode default --permission-prompts none --allowedTools …). Run it as a background command (a minute or
// two); `preflight --job <dir>` re-reads a preflight job without starting a new one.
const PREFLIGHT_WF = path.join(RUNNER_DIR, 'preflight-wf.js');
async function cmdPreflight(pos, opt) {
  const engine = pos[0] || 'claude';
  if (!['claude', 'codex', 'muse', 'gemini'].includes(engine)) throw new UserError('preflight needs an engine: claude, codex, muse or gemini', 'node deleg.mjs preflight claude');
  const wf = opt.workflow === true;
  if (wf && engine !== 'claude') throw new UserError('--workflow is for claude (the Workflow tool)', 'node deleg.mjs preflight claude --workflow');
  let p;
  if (opt.job && opt.job !== true) p = requireJobDir(opt.job, 'status');
  else {
    const root = path.resolve(opt.dir || path.join(os.tmpdir(), 'slop-preflight'));
    p = jobPaths(path.join(root, newJobId(`preflight-${engine}${wf ? '-workflow' : ''}`)));
    fs.mkdirSync(p.J, { recursive: true });
    // Preflight prompts carry no context (a diagnosis in the prompt makes agents probe their own sandbox).
    const job = wf ? { engine, kind: 'preflight-workflow', workflow: PREFLIGHT_WF, workflow_args: { dir: '{{OUTBOX}}' }, timeout_s: 900,
      brief: 'Preflight check of the Workflow tool. As your first action call the Workflow tool exactly once: Workflow({scriptPath: "{{WORKFLOW_PATH}}", args: {{WORKFLOW_ARGS}}}) - pass args as a JSON object, not a string. Then end your turn; do not poll. When the completion notice arrives, reply with exactly PREFLIGHT-OK followed by the workflow\'s JSON result on one line. Do nothing else.\n' }
      : { engine, kind: 'preflight', brief: 'Preflight check. Reply with exactly: PREFLIGHT-OK followed by the model id you are running as, if you know it. Do nothing else.\n',
        ...(engine === 'claude' ? { allowed_tools: [], max_turns: 2 } : {}), ...(engine === 'codex' ? { sandbox: 'read-only' } : {}),
        ...(engine === 'muse' ? { muse_flags: ['--no-foreign-personal-context', '--disable-write', '--disable-shell'] } : {}),
        ...(engine === 'gemini' ? { approval_mode: 'plan' } : {}), timeout_s: 300 };
    writeJSON(p.job, job);
    // runner-authored (muse_flags only ever restrict here); --allow-api-billing: the user chose an API key as the
    // engine's sign-in (e.g. GEMINI_API_KEY), so the tiny test may use it
    startJob(p, { grants: { allow_raw: true, allow_api_billing: !!opt['allow-api-billing'] } });
  }
  const isWf = wf || (readJSON(p.job, {}) || {}).kind === 'preflight-workflow';
  const st = await waitTerminal(p, Number(opt.wait || (isWf ? 600 : 25)));
  const s = summary(p, st);
  const out = { ...s, ok: st.state === 'done' || ACTIVE.has(st.state), preflight_ok: /PREFLIGHT-OK/.test(st.result_text || ''), model: st.model || null,
    has_workflow_tool: st.has_workflow_tool ?? null, api_key_source: st.api_key_source ?? null,
    hint: engine === 'claude' && st.has_workflow_tool === false ? 'No Workflow tool on this plan: set "workflows_env": true in workflow jobs (CLAUDE_CODE_WORKFLOWS=1).' : undefined };
  if (isWf) {
    const bash = (readText(path.join(p.outbox, 'probe-bash.txt')) || '').trim(), write = (readText(path.join(p.outbox, 'probe-write.txt')) || '').trim();
    Object.assign(out, { workflow_ran: (st.workflow_runs || []).length > 0, subagent_bash_ok: bash === 'bash-ok', subagent_write_ok: write === 'write-ok' });
    out.subagent_tools_ok = out.subagent_bash_ok && out.subagent_write_ok;
    if (TERMINAL.has(st.state) || st.state === 'lost') {
      out.ok = st.state === 'done' && out.subagent_tools_ok;
      if (!out.ok) { out.error = out.error || `workflow subagents could not ${[!out.subagent_bash_ok && 'run Bash', !out.subagent_write_ok && 'use Write'].filter(Boolean).join(' or ') || 'finish'} headless`;
        out.fix = 'Do not start workflow jobs yet: send progress.log, status.json and runs/ of this job to the bot; check the Claude Code version (doctor) and its permission settings.'; }
    } else out.next = `still running: node "${fwd(SELF)}" preflight claude --job "${fwd(p.J)}"   (re-reads it; run as a background command)`;
  }
  return out;
}
function help() {
  const L = fs.readFileSync(SELF, 'utf8').split(/\r?\n/);
  const a = L.findIndex(l => l.includes('node deleg.mjs new ')), b = L.findIndex(l => l.includes('compact progress lines'));
  return { ok: true, runner: VERSION, usage: L.slice(a, b + 1).map(l => l.replace(/^ \* ?/, '')).join('\n'),
    first_time: 'node deleg.mjs doctor --render  ->  node deleg.mjs selftest  ->  node deleg.mjs preflight claude  ->  node deleg.mjs preflight claude --workflow (background)', docs: fwd(path.join(RUNNER_DIR, 'README.md')) };
}

// ------------------------------------------------------------------------------------------------------- offline parse
function cmdParse(pos) {   // node deleg.mjs _parse <engine> <stream.jsonl> [job.json]
  const [engine, file, jobFile] = pos; const job = jobFile ? readJSON(jobFile, {}) : { engine };
  const st = { attempt: 1 }; const lines = [];
  for (const l of fs.readFileSync(file, 'utf8').split('\n')) { if (!l.trim()) continue; let ev; try { ev = JSON.parse(l); } catch { lines.push('non-json'); continue; } st.events = (st.events || 0) + 1; for (const x of norm(engine, ev, st, job)) lines.push(x); }
  for (const k of Object.keys(st)) if (k.startsWith('_') && k !== '_fatal') delete st[k];
  return { ok: true, progress: lines, status: st };
}

// ------------------------------------------------------------------------------------------------------------- dispatch
async function main() {
  const [, , verb, ...rest] = process.argv;
  const { pos, opt } = parseArgs(rest, verb);
  if (verb === '_launch2') { const c = spawn(process.execPath, [SELF, '_supervise', pos[0]], { detached: true, stdio: 'ignore', windowsHide: true }); c.unref(); return 0; }
  if (verb === '_supervise') {
    try { await supervise(pos[0]); }
    catch (e) { const p = jobPaths(pos[0]); const st = readJSON(p.status, {}) || {}; writeJSON(p.status, { ...st, state: 'failed', error: `supervisor crashed: ${e.stack || e}`, ended: now() }); }
    return 0;
  }
  try {
    let out;
    switch (verb) {
      case 'new': out = cmdNew(pos, opt); break;
      case 'start': out = cmdStart(pos, opt); break;
      case 'status': out = cmdStatus(pos); break;
      case 'wait': return await cmdWait(pos);
      case 'run': return await cmdRun(pos, opt);
      case 'stop': out = await cmdStop(pos, opt); break;
      case 'resume': out = cmdResume(pos, opt); break;
      case 'list': out = cmdList(pos); break;
      case 'wire': out = cmdWire(pos, opt); break;
      case 'pack': out = cmdPack(pos); break;
      case 'unpack': out = cmdUnpack(pos, opt); break;
      case 'templates': out = cmdTemplates(); break;
      case 'doctor': out = cmdDoctor(opt); break;
      case 'selftest': out = await cmdSelftest(opt); break;
      case 'preflight': out = await cmdPreflight(pos, opt); break;
      case '_parse': out = cmdParse(pos); break;
      case '_resolve': out = { ok: true, ...resolveEngine({ engine: pos[0] }) }; break;
      case 'version': case '--version': out = { ok: true, runner: VERSION, node: process.version }; break;
      case undefined: case 'help': case '--help': case '-h': out = help(); break;
      default: throw new UserError(`unknown command "${verb}"`, 'Commands: new run start status wait stop resume list wire pack unpack templates doctor selftest preflight version help');
    }
    print(out);
    return out && out.ok === false ? 1 : 0;
  } catch (e) {
    if (e instanceof UserError) { print({ ok: false, error: e.message, fix: e.fix }); return 1; }
    print({ ok: false, error: `${e.name}: ${e.message}`, stack: String(e.stack || '').split('\n').slice(0, 6).join(' | ') }); return 2;
  }
}
main().then(code => { process.exitCode = code; });

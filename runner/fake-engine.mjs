#!/usr/bin/env node
/**
 * fake-engine.mjs — a free stand-in for `claude -p`, `codex exec`, `muse exec` and `gemini -p`: it emits canned JSONL in
 * each engine's real stream format (research 11-gap-2 §2.3 Claude stream-json, §4.3 Codex --json, §5.4 Muse envelopes;
 * Gemini CLI 0.62 `-o stream-json`: init / message / tool_use / tool_result / result) and makes no model call and no
 * network call. Used by `deleg.mjs selftest` and by the test suite.
 *
 *   node fake-engine.mjs --as claude|codex|muse|gemini [--scenario NAME] [--step-ms N] [--] <the argv the runner built>
 *   $FAKE_REPLY replaces the final answer of the ok scenario (e.g. "PREFLIGHT-OK fake-model" for preflight tests).
 *
 * Scenarios: ok (default) · workflow (claude: a background Workflow whose result arrives as a SECOND result after a gap;
 * one workflow agent dies of a usage limit; when wf/args.json has "dir" its probe files are written there, as the preflight
 * workflow's subagent would) · workflow-nobash (the same without the probe files) · noworkflow (claude: init without the Workflow tool, then keeps going) ·
 * apikey (claude: apiKeySource says an API key) · ratelimit (claude: 7-day usage 95 %, then keeps going) · denied
 * (claude: a permission denial) · error (engine reports failure, exit 1) · slow (spawns a child process, then streams
 * for minutes — for stop/timeout tests). $FAKE_SCENARIO overrides --scenario; $FAKE_GAP_MS sets the workflow gap.
 *
 * Each call appends one JSON line to $SLOP_JOB_DIR/fake-calls.jsonl: {as, scenario, argv, cwd, env_present[],
 * muse_no_auto_update, session|thread, resumed, stdin_len, grandchild_pid} so tests can check what the runner passed.
 */
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { spawn } from 'node:child_process';

const argv = process.argv.slice(2);
let as = 'claude', scenario = 'ok', step = 15;
while (argv.length) {
  if (argv[0] === '--as') { as = argv[1]; argv.splice(0, 2); }
  else if (argv[0] === '--scenario') { scenario = argv[1]; argv.splice(0, 2); }
  else if (argv[0] === '--step-ms') { step = Number(argv[1]); argv.splice(0, 2); }
  else if (argv[0] === '--') { argv.shift(); break; }
  else break;
}
scenario = process.env.FAKE_SCENARIO || scenario;
const REPLY = process.env.FAKE_REPLY || null;
const JOB = process.env.SLOP_JOB_DIR || process.cwd();
const WATCH = ['ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'ANTHROPIC_BASE_URL', 'OPENAI_API_KEY', 'CODEX_API_KEY', 'META_API_KEY',
  'OPENROUTER_API_KEY', 'HIGGSFIELD_API_KEY', 'ARENA_TOKEN', 'CLAUDECODE', 'CLAUDE_CODE_ENTRYPOINT', 'CLAUDE_CODE_SESSION_ID',
  'GEMINI_API_KEY', 'GOOGLE_API_KEY', 'CLAUDE_CODE_OAUTH_TOKEN', 'CLAUDE_LOGIN_CODE', 'GEMINI_LOGIN_CODE', 'DISABLE_AUTOUPDATER'];
const sleep = ms => new Promise(r => setTimeout(r, ms));
const emit = async o => { process.stdout.write(JSON.stringify(o) + '\n'); await sleep(step); };
const flag = name => { const i = argv.indexOf(name); return i >= 0 ? argv[i + 1] : undefined; };
const outbox = () => { const o = path.join(JOB, 'outbox'); fs.mkdirSync(o, { recursive: true }); return o; };
function record(extra) {
  const rec = { as, scenario, argv, cwd: process.cwd(), env_present: WATCH.filter(k => process.env[k] !== undefined),
    muse_no_auto_update: process.env.MUSE_NO_AUTO_UPDATE || null, claude_code_workflows: process.env.CLAUDE_CODE_WORKFLOWS || null,
    slop_project: process.env.SLOP_PROJECT || null, pid: process.pid, ...extra };
  try { fs.appendFileSync(path.join(JOB, 'fake-calls.jsonl'), JSON.stringify(rec) + '\n'); } catch {}
}
function readStdin() {
  if (process.stdin.isTTY) return Promise.resolve('');
  return new Promise(res => {
    let s = ''; process.stdin.setEncoding('utf8');
    process.stdin.on('data', d => { s += d; }); process.stdin.on('end', () => res(s)); process.stdin.on('error', () => res(s));
  });
}
async function streamForever(mk) { for (let i = 0; i < 900; i++) { await emit(mk(i)); await sleep(200); } return 0; }

// ------------------------------------------------------------------------------------------------------------- claude
const rateLimit = (sid, five, seven) => ({ type: 'rate_limit_event', rate_limit_info: { status: seven >= 1 ? 'rejected' : 'allowed', resetsAt: 1790000000,
  rateLimitType: 'five_hour', overageStatus: 'rejected', isUsingOverage: false,
  unifiedWindows: { five_hour: { utilization: five, resetsAt: 1790000000 }, seven_day: { utilization: seven, resetsAt: 1790500000 } } }, uuid: crypto.randomUUID(), session_id: sid });
const result = (sid, text, cost, turns, index, origin, extra = {}) => ({ type: 'result', subtype: 'success', is_error: false, result: text, num_turns: turns,
  duration_ms: 900, total_cost_usd: cost, usage: { input_tokens: 2, output_tokens: 40, cache_read_input_tokens: 15557, cache_creation_input_tokens: 9399 },
  modelUsage: { 'fake-claude': { inputTokens: 2, outputTokens: 40, costUSD: cost } }, permission_denials: [], terminal_reason: 'completed', result_index: index,
  ...(origin ? { origin: { kind: origin } } : {}), session_id: sid, uuid: crypto.randomUUID(), ...extra });
const progress = (tid, agents) => ({ type: 'system', subtype: 'task_progress', task_id: tid, tool_use_id: 'toolu_wf', description: 'Direct: fake',
  usage: { total_tokens: 1000 * agents.length, tool_uses: agents.length, duration_ms: 500 }, last_tool_name: 'Read',
  workflow_progress: agents.map(([label, state], i) => ({ type: 'workflow_agent', index: i, label, phaseIndex: 0, phaseTitle: 'Direct', state, ...(state === 'error' ? { error: "You've hit your session limit" } : {}) })) });

async function claude() {
  const resumed = !!flag('--resume');
  const sid = flag('--session-id') || flag('--resume') || crypto.randomUUID();
  const tools = scenario === 'noworkflow' ? ['Task', 'Bash', 'Read', 'Write', 'Edit'] : ['Task', 'Bash', 'Read', 'Write', 'Edit', 'Workflow', 'WebSearch', 'WebFetch'];
  const init = () => ({ type: 'system', subtype: 'init', cwd: process.cwd(), session_id: sid, tools, mcp_servers: [], model: 'fake-claude',
    permissionMode: flag('--permission-mode') || 'default', apiKeySource: scenario === 'apikey' ? 'ANTHROPIC_API_KEY' : 'none',
    claude_code_version: '0.0.0-fake', uuid: crypto.randomUUID() });
  let grandchild = null;
  if (scenario === 'slow') { const g = spawn(process.execPath, ['-e', 'setTimeout(()=>{}, 600000)'], { stdio: 'ignore' }); grandchild = g.pid; }
  const stdin = await readStdin();
  record({ session: sid, resumed, stdin_len: stdin.length, grandchild_pid: grandchild });
  await emit(init());
  const say = i => ({ type: 'assistant', message: { content: [{ type: 'text', text: `working ${i}` }] }, session_id: sid });
  if (['noworkflow', 'apikey', 'slow'].includes(scenario)) return streamForever(say);
  if (scenario === 'ratelimit') { await emit(rateLimit(sid, 0.5, 0.95)); return streamForever(say); }
  if (scenario === 'error') {
    await emit({ type: 'result', subtype: 'error_during_execution', is_error: true, result: 'fake engine error: something broke', num_turns: 1, total_cost_usd: 0.001, session_id: sid });
    return 1;
  }
  if (scenario === 'auth') {   // what Claude Code prints for a rejected plan token: subtype "success" with is_error
    await emit({ type: 'result', subtype: 'success', is_error: true, result: 'Failed to authenticate. API Error: 401 {"type":"error","error":{"type":"authentication_error","message":"OAuth access token is invalid"}}', num_turns: 1, total_cost_usd: 0, session_id: sid });
    return 1;
  }
  if (scenario !== 'workflow' && scenario !== 'workflow-nobash') {
    const report = path.join(outbox(), 'report.md');
    await emit({ type: 'assistant', message: { content: [{ type: 'text', text: 'Reading the brief.' }, { type: 'tool_use', id: 'toolu_1', name: 'Write', input: { file_path: report } }] }, session_id: sid });
    fs.writeFileSync(report, `# report\nfake ${resumed ? 'resumed' : 'ok'}\n`);
    await emit({ type: 'user', message: { role: 'user', content: [{ tool_use_id: 'toolu_1', type: 'tool_result', content: 'File written', is_error: false }] }, session_id: sid });
    await emit(rateLimit(sid, 0.12, 0.05));
    const den = scenario === 'denied' ? { permission_denials: [{ tool_name: 'Bash', tool_use_id: 'toolu_2', tool_input: { command: 'rm -rf x' } }] } : {};
    await emit(result(sid, REPLY || (resumed ? 'Resumed: done.' : 'Done: wrote outbox/report.md'), 0.0123, 3, 0, null, den));
    return 0;
  }
  // workflow: the timeline verified in research 11-gap-2 §2.4 (two results; the process exits after the second)
  const runId = 'wf_0a1b2c3d-4e5';
  const wfDir = path.join(JOB, 'wf');
  const script = fs.existsSync(wfDir) ? (fs.readdirSync(wfDir).find(f => f.endsWith('.js')) || 'fake.js') : 'fake.js';
  await emit({ type: 'assistant', message: { content: [{ type: 'tool_use', id: 'toolu_wf', name: 'Workflow', input: { scriptPath: path.join(wfDir, script), args: { n: 1 }, ...(resumed ? { resumeFromRunId: runId } : {}) } }] }, session_id: sid });
  await emit(rateLimit(sid, 0.07, 0.04));
  await emit({ type: 'system', subtype: 'background_tasks_changed', tasks: [{ task_id: 'wfake01', task_type: 'local_workflow', description: 'fake' }], session_id: sid });
  await emit({ type: 'system', subtype: 'task_started', task_id: 'wfake01', tool_use_id: 'toolu_wf', description: 'fake workflow', task_type: 'local_workflow', workflow_name: 'slop-fake', prompt: '…' });
  await emit({ type: 'user', message: { role: 'user', content: [{ tool_use_id: 'toolu_wf', type: 'tool_result', content: `Workflow launched in background. Task ID: wfake01\nSummary: fake\nRun ID: ${runId}\nTo resume after editing the script: Workflow({scriptPath: "${script}", resumeFromRunId: "${runId}"})\n\nYou will be notified when it completes.` }] }, session_id: sid });
  await emit(progress('wfake01', [['director:a', 'done'], ['director:b', 'start'], ['judge:1', 'start']]));
  await emit(progress('wfake01', [['director:a', 'done'], ['director:b', 'done'], ['judge:1', 'error']]));
  await emit({ type: 'system', subtype: 'background_tasks_changed', tasks: [], session_id: sid });
  await emit({ type: 'system', subtype: 'task_updated', task_id: 'wfake01', patch: { status: 'completed' } });
  const outFile = path.join(JOB, '.fake', 'tasks', 'wfake01.output');
  fs.mkdirSync(path.dirname(outFile), { recursive: true });
  fs.writeFileSync(outFile, JSON.stringify({ summary: 'Dynamic workflow "slop-fake" completed', agentCount: 3,
    logs: ['judge totals {"a":[80]}', "[judge:1] failed: You've hit your session limit · resets 5:40am (UTC)"], result: { ok: true, totals: { a: [80] } },
    workflowProgress: [{ type: 'workflow_phase', index: 0, title: 'Direct' }, { type: 'workflow_agent', index: 0, label: 'director:a', state: 'done' },
      { type: 'workflow_agent', index: 1, label: 'director:b', state: 'done' }, { type: 'workflow_agent', index: 2, label: 'judge:1', state: 'error', error: "You've hit your session limit" }],
    totalTokens: 3000, totalToolCalls: 7 }));
  await emit({ type: 'system', subtype: 'task_notification', task_id: 'wfake01', tool_use_id: 'toolu_wf', status: 'completed', output_file: outFile,
    summary: 'Dynamic workflow "slop-fake" completed', usage: { total_tokens: 3000, tool_uses: 7, duration_ms: 900 } });
  await emit({ type: 'assistant', message: { content: [{ type: 'text', text: `The workflow (run ${runId}) is still running. I'll reply once the completion notice comes in.` }] }, session_id: sid });
  await emit(result(sid, `The workflow (run ${runId}) is still running.`, 0.2522, 2, 0, null));
  await sleep(Number(process.env.FAKE_GAP_MS || 1500));
  // the preflight workflow (runner/preflight-wf.js): its subagent writes two probe files into args.dir
  let wfArgs = null; try { wfArgs = JSON.parse(fs.readFileSync(path.join(wfDir, 'args.json'), 'utf8')); } catch {}
  if (wfArgs && wfArgs.dir && scenario !== 'workflow-nobash') { try { fs.writeFileSync(path.join(wfArgs.dir, 'probe-bash.txt'), 'bash-ok'); fs.writeFileSync(path.join(wfArgs.dir, 'probe-write.txt'), 'write-ok'); } catch {} }
  await emit(init());
  fs.writeFileSync(path.join(outbox(), 'report.md'), '# report\nfake workflow finished\n');
  await emit({ type: 'assistant', message: { content: [{ type: 'text', text: `${runId} workflow finished: {"ok":true}` }] }, session_id: sid });
  await emit(result(sid, `${runId} workflow finished: {"ok":true}. Report written to outbox/report.md`, 0.0158, 1, 1, 'task-notification'));
  return 0;
}

// -------------------------------------------------------------------------------------------------------------- codex
async function codex() {
  const stdin = await readStdin();   // hangs here if the runner forgets to close stdin
  const resumed = argv[0] === 'exec' && argv[1] === 'resume';
  const thread = resumed ? argv[argv.length - 2] : '00000000-0000-7000-8000-00000000c0de';
  record({ thread, resumed, stdin_len: stdin.length, stdin_head: stdin.slice(0, 300) });
  await emit({ type: 'thread.started', thread_id: thread });
  await emit({ type: 'turn.started' });
  if (scenario === 'error') { await emit({ type: 'turn.failed', error: { message: 'fake failure: usage limit reached' } }); return 1; }
  if (scenario === 'slow') return streamForever(i => ({ type: 'item.completed', item: { id: `item_${i}`, type: 'agent_message', text: `working ${i}` } }));
  await emit({ type: 'item.completed', item: { id: 'item_0', type: 'agent_message', text: 'I’ll run the command now.' } });
  await emit({ type: 'item.started', item: { id: 'item_1', type: 'command_execution', command: 'echo hi', aggregated_output: '', exit_code: null, status: 'in_progress' } });
  await emit({ type: 'item.completed', item: { id: 'item_1', type: 'command_execution', command: 'echo hi', aggregated_output: 'hi\n', exit_code: 0, status: 'completed' } });
  fs.writeFileSync(path.join(outbox(), 'report.md'), `# report\ncodex ${resumed ? 'resumed' : 'ok'}\n`);
  await emit({ type: 'item.completed', item: { id: 'item_2', type: 'file_change', changes: [{ path: 'outbox/report.md', kind: 'add' }], status: 'completed' } });
  await emit({ type: 'item.completed', item: { id: 'item_3', type: 'agent_message', text: REPLY || (resumed ? 'DONE (resumed)' : 'DONE') } });
  const o = flag('-o'); if (o) { try { fs.writeFileSync(o, resumed ? 'DONE (resumed)' : 'DONE'); } catch {} }
  await emit({ type: 'turn.completed', usage: { input_tokens: 16208, cached_input_tokens: 8192, cache_write_input_tokens: 0, output_tokens: 5, reasoning_output_tokens: 0 } });
  return 0;
}

// --------------------------------------------------------------------------------------------------------------- muse
async function muse() {
  const resumed = !!flag('--session-id');
  const sid = flag('--session-id') || '00000000-0000-7000-8000-0000000003e5';
  const pf = flag('--prompt-file'); let prompt = ''; try { prompt = pf ? fs.readFileSync(pf, 'utf8') : ''; } catch {}
  const stdin = await readStdin();
  record({ session: sid, resumed, prompt_len: prompt.length, prompt_head: prompt.slice(0, 300), stdin_len: stdin.length });
  let seq = 0;
  const env = (payload_type, payload) => ({ schema_version: 1, id: crypto.randomUUID(), stream: { kind: 'session', id: sid }, sequence: seq++, recorded_at: 0,
    record_type: 'event', durability: 'durable', causation_id: 'cmd-1', payload_type, payload_schema_version: 1,
    payload: { kind: payload_type, command_id: 'cmd-1', run_stream: { kind: 'run', id: 'run-1' }, ...payload } });
  await emit(env('runtime.command.accepted', { command_kind: 'turn.submit' }));
  await emit(env('session.run.linked', {}));
  await emit(env('run.model.configured', { provider_id: 'meta', profile_id: 'fake', model_id: 'fake-muse', display_label: 'Fake', source: 'startup' }));
  await emit(env('run.lifecycle.started', { prompt: prompt.slice(0, 100) }));
  await emit(env('task.lifecycle.proposed', { event: { task_kind: 'model.meta.response' } }));
  await emit(env('task.lifecycle.status', { event: { message: 'opening meta model stream attempt 2/10' } }));
  if (scenario === 'slow') return streamForever(i => env('run.output.delta', { text: `.${i}` }));
  await emit(env('run.output.delta', { text: resumed ? 'OK again' : 'OK' }));
  if (scenario === 'error') { await emit(env('run.terminal.failed', { terminal: 'failed', text: '', reason: { code: 'fake' } })); return 1; }
  fs.writeFileSync(path.join(outbox(), 'report.md'), `# report\nmuse ${resumed ? 'resumed' : 'ok'}\n`);
  await emit(env('run.terminal.completed', { terminal: 'completed', text: REPLY || (resumed ? 'OK again' : 'OK'), reason: null }));
  return 0;
}

// ------------------------------------------------------------------------------------------------------------- gemini
async function gemini() {
  const stdin = await readStdin();   // the runner must close stdin (gemini appends a piped stdin to the prompt)
  const sid = crypto.randomUUID();
  const prompt = flag('-p') || '';
  record({ session: sid, stdin_len: stdin.length, prompt_head: prompt.slice(0, 300), approval: flag('--approval-mode') || null,
    skip_trust: argv.includes('--skip-trust'), include: flag('--include-directories') || null });
  const ts = () => new Date().toISOString();
  await emit({ type: 'init', timestamp: ts(), session_id: sid, model: 'fake-gemini' });
  await emit({ type: 'message', timestamp: ts(), role: 'user', content: prompt });
  if (scenario === 'error') {
    await emit({ type: 'result', timestamp: ts(), status: 'error', error: { type: 'unknown', message: '[API Error: API key not valid. Please pass a valid API key.]' } });
    return 144;
  }
  if (scenario === 'slow') return streamForever(i => ({ type: 'message', timestamp: ts(), role: 'assistant', content: `.${i}`, delta: true }));
  await emit({ type: 'tool_use', timestamp: ts(), tool_name: 'write_file', tool_id: 'w1', parameters: { file_path: 'outbox/report.md' } });
  fs.writeFileSync(path.join(outbox(), 'report.md'), '# report\ngemini ok\n');
  await emit({ type: 'tool_result', timestamp: ts(), tool_id: 'w1', status: 'success', output: 'ok' });
  const text = REPLY || 'Done: wrote outbox/report.md';
  await emit({ type: 'message', timestamp: ts(), role: 'assistant', content: text.slice(0, 5), delta: true });
  await emit({ type: 'message', timestamp: ts(), role: 'assistant', content: text.slice(5), delta: true });
  await emit({ type: 'result', timestamp: ts(), status: 'success', stats: { total_tokens: 130, input_tokens: 110, output_tokens: 20, duration_ms: 800, tool_calls: 1 } });
  return 0;
}

const run = { claude, codex, muse, gemini }[as];
if (!run) { process.stderr.write(`fake-engine: unknown --as ${as}\n`); process.exit(2); }
run().then(code => { process.exit(code); }, e => { process.stderr.write(String(e.stack || e) + '\n'); process.exit(3); });

import test from 'node:test';
import assert from 'node:assert/strict';
import { Readable } from 'node:stream';
import { spawn, spawnSync } from 'node:child_process';
import { createServer } from 'node:http';
import { once } from 'node:events';
import { readFile, stat } from 'node:fs/promises';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { TARGET_INVOCATION_VERSION, simulationExitCode } from '@firedrill-run/sdk';
import { applicationEnvironment, invokeCLI, readInvocation, readStdin } from './adapter-runtime.mjs';
import { runApplication } from './target.mjs';

const root = fileURLToPath(new URL('../', import.meta.url));
const cli = fileURLToPath(new URL('./node_modules/@firedrill-run/cli/bin/firedrill.mjs', import.meta.url));
const envelope = () => ({
  schemaVersion: TARGET_INVOCATION_VERSION,
  runId: 'offline-run', attemptId: 'offline-attempt', scenario: { id: 'starter-chat' },
  configuration: { id: 'default', parameters: {} }, tools: {}, input: { caseId: 'starter', action: 'chat', recordId: 'case-104', message: 'Inspect case-104 and report the current request.' },
});

test('released 2.2.2 CLI validates the actual command recipe offline', () => {
  const result = spawnSync(process.execPath, [cli, 'validate', 'firedrill/scenario.json', '--json', '--non-interactive'], { cwd: root, encoding: 'utf8' });
  assert.equal(result.status, 0, result.stderr);
  assert.deepEqual(JSON.parse(result.stdout), { valid: true, expandedRuns: 3, target: 'command' });
});

test('current invocation accepts task identity without controller data', () => {
  const value = envelope();
  assert.equal(readInvocation(value), value);
});

for (const [name, change] of [
  ['retired invocation version', v => { v.schemaVersion = '2026-10-14'; }],
  ['full controller scenario', v => { v.scenario.checks = []; }],
  ['assessment payload', v => { v.checks = []; }],
  ['unsupported Tool connections', v => { v.tools.mail = { token: 'synthetic' }; }],
  ['unreviewed configuration', v => { v.configuration.parameters.allowWrite = true; }],
  ['invalid step', v => { v.step = { id: 's', ordinal: true }; }],
  ['missing application task', v => { delete v.input; }],
]) test(`rejects ${name} before application execution`, () => {
  const value = envelope(); change(value);
  assert.throws(() => readInvocation(value));
});

test('stdin is bounded and rejects invalid UTF-8 instead of replacing bytes', async () => {
  await assert.rejects(readStdin(Readable.from([Buffer.alloc(128 * 1024 + 1)])));
  await assert.rejects(readStdin(Readable.from([Buffer.from([0xff])])));
  const invocation = await readStdin(Readable.from([Buffer.from(JSON.stringify(envelope()))]));
  assert.equal(invocation.input.caseId, 'starter');
});

test('operator/CI authority never reaches the application, while its model key remains separate', () => {
  assert.deepEqual(applicationEnvironment({ FIREDRILL_TOKEN: 'operator', FIREDRILL_INPUT_JSON: 'controller', ACTIONS_ID_TOKEN_REQUEST_TOKEN: 'ci', OPENAI_API_KEY: 'model', PATH: '/bin' }), { OPENAI_API_KEY: 'model', PATH: '/bin' });
});

test('actual subprocess output is returned with literal argv and no shell interpretation', async () => {
  const result = await invokeCLI([process.execPath, '-e', 'console.log(JSON.stringify({task:process.argv[1],operator:process.env.FIREDRILL_TOKEN??null}))', '$(never-execute)'], { env: { PATH: process.env.PATH, FIREDRILL_TOKEN: 'operator' } });
  assert.deepEqual(result, { task: '$(never-execute)', operator: null });
});

test('failed application retains original partial output and stderr without returning success', async () => {
  await assert.rejects(invokeCLI([process.execPath, '-e', 'process.stdout.write("partial");process.stderr.write("failed after work");process.exitCode=7']), error => {
    assert.equal(error.evidence.exitCode, 7);
    assert.equal(error.evidence.stdout, 'partial');
    assert.equal(error.evidence.stderr, 'failed after work');
    return true;
  });
});

test('malformed application output cannot be released as structured success', async () => {
  await assert.rejects(invokeCLI([process.execPath, '-e', 'console.log("not JSON")']), /one JSON value/);
});

test('cancellation drains the owned foreground child before failure', async () => {
  const controller = new AbortController();
  const running = invokeCLI([process.execPath, '-e', 'setInterval(()=>{},1000)'], { signal: controller.signal });
  const timer = setTimeout(() => controller.abort(new Error('offline cancellation')), 100);
  try { await assert.rejects(running, error => error.message === 'offline cancellation' && error.evidence.signal === 'SIGTERM'); }
  finally { clearTimeout(timer); }
});

test('unreviewed inputs cannot select files, commands or write grants', async () => {
  await assert.rejects(runApplication({ caseId: 'starter', argv: ['sh'] }, {}, undefined));
  await assert.rejects(runApplication({ caseId: '../private' }, {}, undefined));
});

test('actual support API fails explicitly without a model credential', () => {
  const env = { ...process.env };
  for (const key of Object.keys(env)) if (/KEY|TOKEN|CREDENTIAL/.test(key)) delete env[key];
  const result = spawnSync(process.execPath, ['firedrill/target.mjs'], { cwd: root, input: JSON.stringify(envelope()), env, encoding: 'utf8', timeout: 30000 });
  assert.equal(result.status, 1, result.stderr);
  assert.equal(result.stdout, '');
  const failure = JSON.parse(result.stderr);
  assert.equal(failure.application.exitCode, 1);
  assert.match(failure.application.stderr, /OPENAI_API_KEY required/);
});

test('actual API inspection preserves committed state and does not construct a model runtime', async () => {
  const env = { ...process.env };
  for (const key of Object.keys(env)) if (/KEY|TOKEN|CREDENTIAL/.test(key)) delete env[key];
  const value = envelope();
  value.input = { caseId: 'busy', action: 'inspect', recordId: 'case-104', message: null };
  const result = spawnSync(process.execPath, ['firedrill/target.mjs'], { cwd: root, input: JSON.stringify(value), env, encoding: 'utf8', timeout: 30000 });
  assert.equal(result.status, 0, result.stderr);
  const output = JSON.parse(result.stdout);
  assert.equal(output.application.executionKind, 'application_state_inspection');
  assert.equal(output.application.after.body.case.id, 'case-104');
  assert.deepEqual(output.application.after, output.application.before);
  assert.equal(output.application.backendRuntimeClosed, null);
  const mapping = join(output.localState.directory, 'invocation.json');
  assert.deepEqual(JSON.parse(await readFile(mapping)), { source: 'command_adapter', identity: { runId: 'offline-run', attemptId: 'offline-attempt', scenarioId: 'starter-chat' } });
  assert.equal((await stat(mapping)).mode & 0o777, 0o600);
});

test('normal adapter cannot invoke an operator approval action', async () => {
  await assert.rejects(runApplication({ caseId: 'starter', action: 'approve', recordId: 'case-104', message: null }, {}, undefined));
});

test('actual default runtime, AG-UI stream and original provider SDK complete over owned loopback HTTP', async () => {
  const requests = [];
  const server = createServer(async (request, response) => {
    const chunks = []; for await (const chunk of request) chunks.push(chunk);
    const body = JSON.parse(Buffer.concat(chunks).toString());
    requests.push({ path: request.url, body, authorization: request.headers.authorization });
    const message = { role: 'assistant', content: 'Controlled final response. No refund was issued.' };
    const usage = { prompt_tokens: 20, completion_tokens: 10, total_tokens: 30 };
    const base = { id: 'chatcmpl_controlled', created: 1792098000, model: 'controlled-copilot' };
    if (body.stream) {
      response.writeHead(200, { 'content-type': 'text/event-stream' });
      const events = [
        { ...base, object: 'chat.completion.chunk', choices: [{ index: 0, delta: message, finish_reason: null }] },
        { ...base, object: 'chat.completion.chunk', choices: [{ index: 0, delta: {}, finish_reason: 'stop' }] },
        { ...base, object: 'chat.completion.chunk', choices: [], usage },
      ];
      response.end(events.map(event => `data: ${JSON.stringify(event)}\n\n`).join('') + 'data: [DONE]\n\n');
    } else {
      response.writeHead(200, { 'content-type': 'application/json' });
      response.end(JSON.stringify({ ...base, object: 'chat.completion', choices: [{ index: 0, message, finish_reason: 'stop' }], usage }));
    }
  });
  server.listen(0, '127.0.0.1'); await once(server, 'listening');
  const env = { ...process.env, OPENAI_API_KEY: 'synthetic-copilot-key', OPENAI_BASE_URL: `http://127.0.0.1:${server.address().port}/v1`,
    NO_PROXY: '127.0.0.1', no_proxy: '127.0.0.1', LANGSMITH_TRACING: 'false', LANGCHAIN_TRACING_V2: 'false', FIREDRILL_TOKEN: 'synthetic-operator' };
  const child = spawn(process.execPath, ['firedrill/target.mjs'], { cwd: root, env, stdio: ['pipe', 'pipe', 'pipe'] });
  let stdout = '', stderr = '';
  child.stdout.on('data', chunk => { stdout += chunk; }); child.stderr.on('data', chunk => { stderr += chunk; });
  const closed = once(child, 'close'); const timeout = setTimeout(() => child.kill('SIGTERM'), 25000);
  child.stdin.end(JSON.stringify(envelope()));
  try {
    const [code] = await closed;
    assert.equal(code, 0, stderr);
    const output = JSON.parse(stdout).application;
    assert.equal(output.executionKind, 'native_agui_request');
    assert.equal(output.backendRuntimeClosed, true);
    assert.ok(output.events.some(event => event.type === 'RUN_FINISHED' && event.runId === output.runId));
    assert.equal(output.events.some(event => event.type === 'RUN_ERROR'), false);
    assert.equal(output.evidence.body.http_attempts, 1);
    assert.equal(output.evidence.body.cost_usd, null);
    assert.equal(requests.length, 1);
    assert.equal(requests[0].path, '/v1/chat/completions');
    assert.equal(requests[0].authorization, 'Bearer synthetic-copilot-key');
    assert.equal(JSON.stringify(requests).includes('synthetic-operator'), false);
    assert.equal(JSON.stringify(requests[0].body.messages).includes('starter-chat'), false);
  } finally {
    clearTimeout(timeout); if (child.exitCode === null) child.kill('SIGTERM');
    server.closeAllConnections(); await new Promise(resolve => server.close(resolve));
  }
});

test('SDK result status keeps pending work, unknown execution and gates distinct', () => {
  const value = { batch: { total: 1, counts: { completed: 1, error: 0, interrupted: 0, cancelled: 0, running: 0, queued: 0 } }, runs: [], gate: 'not_configured' };
  assert.equal(simulationExitCode(value), 0);
  assert.equal(simulationExitCode({ ...value, gate: 'inconclusive' }), 1);
  assert.equal(simulationExitCode({ ...value, batch: { total: 2, counts: value.batch.counts } }), 5);
  assert.equal(simulationExitCode({ ...value, runs: [{ assessment: 'pending' }] }), 6);
});

test('runner help never initializes scope or starts a simulation', () => {
  const result = spawnSync(process.execPath, ['firedrill/simulate.mjs', '--help'], { cwd: root, encoding: 'utf8' });
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /--resume OPERATION_ID/);
});

test('reviewed recipe stays sequential, bounded and free of credentials or evaluation answers', async () => {
  const value = JSON.parse(await readFile(new URL('./scenario.json', import.meta.url)));
  assert.equal(value.concurrency, 1);
  assert.equal(value.limits.maxRuns, value.scenarios.length);
  assert.equal(value.services, undefined);
  assert.equal(value.gate, undefined);
  for (const scenario of value.scenarios) assert.deepEqual(Object.keys(scenario.input), ['caseId', 'action', 'recordId', 'message']);
});

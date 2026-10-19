import { existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { resolve, join } from 'node:path';
import { ApplicationError, commandMain, invokeCLI, privateDirectory } from './adapter-runtime.mjs';

const root = fileURLToPath(new URL('../', import.meta.url));
const backend = existsSync(join(root, 'backend', 'pyproject.toml')) ? join(root, 'backend') : root;
const requestDriver = fileURLToPath(new URL('./request.py', import.meta.url));
const cases = new Set(['starter', 'identity-conflict', 'busy']);

export async function runApplication(input, parameters, signal, invocation) {
  if (Object.keys(input).some(key => !['caseId', 'action', 'recordId', 'message'].includes(key)) || !cases.has(input.caseId) ||
      !['chat', 'inspect'].includes(input.action) || typeof input.recordId !== 'string' || !/^[A-Za-z0-9_-]{1,100}$/.test(input.recordId) ||
      (input.action === 'chat' ? typeof input.message !== 'string' || !input.message.trim() || input.message.length > 8000 || input.message.includes('\0') : input.message !== null)) {
    throw new Error('Select a reviewed case and explicit chat or state-inspection request. Operator decisions are separate.');
  }
  const directory = await privateDirectory(root, invocation);
  const workspace = join(directory, 'workspace.json');
  const cli = ['uv', 'run', '--locked', '--no-sync'];
  const env = { ...process.env, ...(parameters.model ? { OPENAI_MODEL: parameters.model } : {}) };
  try {
    await invokeCLI([...cli, 'support-workspace-api', '--init-case', input.caseId, '--workspace', workspace], { cwd: backend, signal, env });
    const argv = [...cli, 'python', requestDriver, '--workspace', workspace, '--action', input.action, '--record', input.recordId];
    if (input.action === 'chat') argv.push('--message', input.message);
    const output = await invokeCLI(argv, { cwd: backend, signal, env, timeoutMs: 210000 });
    return { application: output, localState: { directory, workspaceFile: workspace } };
  } catch (error) {
    if (error instanceof ApplicationError) error.evidence.runDirectory = directory;
    throw error;
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  await commandMain(runApplication);
}

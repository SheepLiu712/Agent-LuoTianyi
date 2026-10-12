import { ChildProcess, spawn } from 'node:child_process';
import { createWriteStream, existsSync, mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { delimiter, join, resolve } from 'node:path';

const PYTHON = process.env.CALL_E2E_PYTHON;
const DEFAULT_SERVER_SOURCE = resolve(__dirname, '../../..');

export interface RunningCallServer {
  url: string;
  root: string;
  source: string;
  disconnectEvidencePath: string;
  stop(): Promise<{ logs: string; exitCode: number | null }>;
}

export function resolveCallServerSource(): string | null {
  // Network integration is opt-in, and uses this checkout unless explicitly overridden.
  if (!PYTHON) return null;
  const source = resolve(process.env.CALL_E2E_SERVER_SOURCE || DEFAULT_SERVER_SOURCE);
  const launcher = join(source, 'server', 'tests', 'support', 'call_network_success_server.py');
  if (!existsSync(launcher)) throw new Error(`call network server launcher not found in ${source}`);
  return source;
}

export async function launchCallServer(kind: 'success' | 'disabled' | 'disconnect-evidence'): Promise<RunningCallServer> {
  const source = resolveCallServerSource();
  if (!source) {
    throw new Error(
      'CALL_E2E_SERVER_SOURCE must point to checkout containing server/tests/support/call_network_success_server.py',
    );
  }
  if (!PYTHON || !existsSync(PYTHON)) throw new Error(`CALL_E2E_PYTHON does not exist: ${PYTHON}`);
  const root = mkdtempSync(join(tmpdir(), `agent-luo-call-${kind}-`));
  const stdoutPath = join(root, 'stdout.log');
  const stderrPath = join(root, 'stderr.log');
  const stdoutFile = createWriteStream(stdoutPath, { encoding: 'utf8' });
  const stderrFile = createWriteStream(stderrPath, { encoding: 'utf8' });
  const module = kind === 'success'
    ? 'support.call_network_success_server'
    : kind === 'disabled'
      ? 'support.call_network_unavailable_server'
      : 'call_disconnect_evidence_server';
  const args = ['-m', module, root, ...(kind === 'disabled' ? ['unknown'] : [])];
  const env = { ...process.env };
  env.PYTHONPATH = [
    __dirname,
    join(source, 'server'),
    join(source, 'server', 'tests'),
    env.PYTHONPATH || '',
  ]
    .filter(Boolean).join(delimiter);
  env.PYTHONIOENCODING = 'utf-8';
  env.PYTHONUNBUFFERED = '1';
  for (const key of ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy']) {
    delete env[key];
  }
  const child = spawn(PYTHON, args, { cwd: root, env, stdio: ['ignore', 'pipe', 'pipe'] });
  child.stdout!.pipe(stdoutFile);
  child.stderr!.pipe(stderrFile);
  const url = await waitForReady(child, root, stdoutPath, stderrPath);
  let stopped = false;
  return {
    url,
    root,
    source,
    disconnectEvidencePath: join(root, 'disconnect-evidence.jsonl'),
    stop: async () => {
      if (!stopped) {
        stopped = true;
        await fetch(`${url}/test/stop`, { method: 'POST' }).catch(() => undefined);
      }
      const exitCode = await waitForExit(child, 12_000);
      stdoutFile.end();
      stderrFile.end();
      await Promise.all([finished(stdoutFile), finished(stderrFile)]);
      const logs = readLogs(stdoutPath, stderrPath);
      rmSync(root, { recursive: true, force: true });
      return { logs, exitCode };
    },
  };
}

async function waitForReady(
  child: ChildProcess,
  root: string,
  stdoutPath: string,
  stderrPath: string,
): Promise<string> {
  const deadline = Date.now() + 60_000;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) throw new Error(`server exited ${child.exitCode}\n${readLogs(stdoutPath, stderrPath)}`);
    const addressPath = join(root, 'address.json');
    if (existsSync(addressPath)) {
      const url = JSON.parse(readFileSync(addressPath, 'utf8')).url as string;
      try {
        const response = await fetch(`${url}/test/evidence`, { signal: AbortSignal.timeout(500) });
        if (response.ok) return url;
      } catch { /* readiness retries */ }
    }
    await delay(50);
  }
  child.kill();
  throw new Error(`server readiness timeout\n${readLogs(stdoutPath, stderrPath)}`);
}

async function waitForExit(child: ChildProcess, timeoutMs: number): Promise<number | null> {
  if (child.exitCode !== null) return child.exitCode;
  const exit = new Promise<number | null>((resolveExit) => child.once('exit', resolveExit));
  const timeout = delay(timeoutMs).then(() => 'timeout' as const);
  if (await Promise.race([exit, timeout]) === 'timeout') {
    child.kill();
    return await Promise.race([exit, delay(5_000).then(() => child.exitCode)]);
  }
  return child.exitCode;
}

function finished(stream: NodeJS.WritableStream): Promise<void> {
  if ((stream as { closed?: boolean }).closed) return Promise.resolve();
  return new Promise((resolveFinished) => stream.once('close', resolveFinished));
}

function readLogs(stdoutPath: string, stderrPath: string): string {
  return [stdoutPath, stderrPath].map((path) => existsSync(path) ? readFileSync(path, 'utf8') : '').join('\n');
}

export const delay = (milliseconds: number) => new Promise<void>((resolveDelay) => setTimeout(resolveDelay, milliseconds));

export async function waitUntil<T>(probe: () => T | Promise<T>, accept: (value: T) => boolean, timeoutMs = 10_000): Promise<T> {
  const deadline = Date.now() + timeoutMs;
  let last!: T;
  while (Date.now() < deadline) {
    last = await probe();
    if (accept(last)) return last;
    await delay(30);
  }
  throw new Error(`condition timed out; last=${JSON.stringify(last)}`);
}

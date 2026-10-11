import { constants, publicEncrypt } from 'node:crypto';
import { existsSync, readFileSync } from 'node:fs';

import { server_config } from '../config';
import type { CallAudioFormat, CallPlaybackChunk, CapturedAudioFrame, PlaybackConsumptionReceipt } from '../utils/call_audio_contracts';
import { ProductionCallResolver } from '../utils/call_session/production_resolver';
import { NetworkClient, type ConnectCallbacks } from '../utils/network_client';
import { launchCallServer, resolveCallServerSource, waitUntil } from './support/call_network_server';

jest.mock('expo-file-system/legacy', () => ({}));
jest.mock('../utils/image_compression', () => ({ compressImageForUpload: jest.fn(), MAX_IMAGE_FILE_SIZE_BYTES: 6 * 1024 * 1024 }));
jest.mock('expo-av', () => ({ Audio: { requestPermissionsAsync: jest.fn() } }));
jest.mock('expo-constants', () => ({ __esModule: true, default: { executionEnvironment: 'standalone' } }));
jest.mock('react-native', () => ({
  Platform: { OS: 'android' },
  AppState: { currentState: 'active', addEventListener: jest.fn(() => ({ remove: jest.fn() })) },
}));
jest.mock('../utils/call_audio/native_call_audio', () => ({
  AndroidCallAudio: class {}, isAndroidCallAudioModuleAvailable: jest.fn(() => true),
}));

class FailureNative {
  setCoordinatorEvents() {}
  async initialize() { return 'available' as const; }
  async getCapability() { return 'available' as const; }
  async startCapture(_format: CallAudioFormat, _listener: (frame: CapturedAudioFrame) => void) {}
  async stopCapture() {}
  async pauseCapture() {}
  async resumeCapture() {}
  async enqueue(_chunk: CallPlaybackChunk) { throw new Error('native playback rejected'); }
  async stop() {}
  async tombstone(_stream: CallPlaybackChunk['stream']) {}
  subscribeConsumption(_listener: (receipt: PlaybackConsumptionReceipt) => void) { return () => undefined; }
  async close() {}
}

const callbacks: ConnectCallbacks = {
  onAgentMessage: jest.fn(), onAgentStateChanged: jest.fn(), onError: jest.fn(),
};
const networkTest = resolveCallServerSource() ? test : test.skip;

networkTest('active transport failure sends a legal 4001 close frame and leaves no replacement socket', async () => {
  const originalWebSocket = globalThis.WebSocket;
  const callEvents: { event: string; code?: number; reason?: string }[] = [];
  class TracedWebSocket extends originalWebSocket {
    constructor(url: string | URL, protocols?: string | string[]) {
      super(url, protocols);
      if (String(url).endsWith('/call_ws')) {
        this.addEventListener('open', () => callEvents.push({ event: 'open' }));
        this.addEventListener('close', (event) => callEvents.push({ event: 'close_event', code: event.code, reason: event.reason }));
      }
    }
    close(code?: number, reason?: string) {
      if (this.url.endsWith('/call_ws')) callEvents.push({ event: 'close_requested', code, reason });
      super.close(code, reason);
    }
  }
  globalThis.WebSocket = TracedWebSocket as typeof WebSocket;
  const server = await launchCallServer('disconnect-evidence');
  const previous = server_config.BASE_URL;
  server_config.BASE_URL = server.url;
  let token = '';
  let chat: NetworkClient | undefined;
  let resolver: ProductionCallResolver | undefined;
  try {
    token = await registerAndLogin(server.url);
    chat = new NetworkClient();
    const activeChat = chat;
    expect(await activeChat.reconnectWs('alice', token, 'luotianyi', callbacks)).toBe(true);
    resolver = new ProductionCallResolver({
      characterId: 'luotianyi', credentials: { username: 'alice', token },
      switchPort: { prepare: (id, character) => activeChat.prepareCallSwitch(id, character) },
      createNativeAudio: () => new FailureNative() as never,
    });
    expect((await resolver.refreshCapability()).available).toBe(true);
    const attempt = resolver.createAttempt();
    expect(await attempt.initializeNative()).toBe(true);
    await attempt.session.prepare('failure-close');
    await attempt.session.start('failure-close', 'prepared_switch');
    const failed = await waitUntil(() => attempt.session.state, (state) => state.status === 'failed');
    expect(failed.errorCode).toBe('native playback rejected');
    await waitUntil(() => callEvents, (events) => events.some((event) => event.event === 'close_event'));
    expect(callEvents.filter((event) => event.event === 'open')).toHaveLength(1);
    expect(callEvents.find((event) => event.event === 'close_requested')).toEqual({
      event: 'close_requested', code: 4001, reason: 'call transport failed',
    });
    expect(callEvents.find((event) => event.event === 'close_event')).toMatchObject({ event: 'close_event', code: 4001 });
    const serverEvidence = await waitUntil(
      () => readEvidence(server.disconnectEvidencePath),
      (items) => items.some((item) => item.event === 'hub.detach_after_disconnect'),
    );
    expect(serverEvidence).toContainEqual(expect.objectContaining({
      event: 'websocket.disconnect', path: '/call_ws', code: 4001,
    }));
    expect(serverEvidence).toContainEqual(expect.objectContaining({
      event: 'hub.detach_after_disconnect', detached: true, connection_present: false, stage_state: 'reconnecting',
    }));
    expect(serverEvidence.some((item) => item.event === 'websocket.disconnect' && item.path === '/chat_ws' && item.code === 4001)).toBe(false);
    await attempt.close();
  } finally {
    globalThis.WebSocket = originalWebSocket;
    chat?.disconnectWs();
    await resolver?.close().catch(() => undefined);
    server_config.BASE_URL = previous;
    const stopped = await server.stop();
    expect(stopped.exitCode).toBe(0);
    if (token) expect(stopped.logs).not.toContain(token);
    expect(stopped.logs).not.toContain('native playback rejected');
  }
}, 60_000);

interface DisconnectEvidence {
  event: string;
  path?: string;
  code?: number;
  detached?: boolean;
  connection_present?: boolean;
  stage_state?: string;
}

function readEvidence(path: string): DisconnectEvidence[] {
  if (!existsSync(path)) return [];
  return readFileSync(path, 'utf8').trim().split(/\r?\n/).filter(Boolean).map((line) => JSON.parse(line));
}

async function registerAndLogin(url: string): Promise<string> {
  const password = 'offline-password';
  const register = await fetch(`${url}/auth/register`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: 'alice', password: await encryptedPassword(url, password), invite_code: 'invite' }),
  });
  expect(register.ok).toBe(true);
  const login = await fetch(`${url}/auth/login`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: 'alice', password: await encryptedPassword(url, password) }),
  });
  expect(login.ok).toBe(true);
  return (await login.json()).message_token as string;
}

async function encryptedPassword(url: string, password: string): Promise<string> {
  const response = await fetch(`${url}/auth/public_key`);
  const key = (await response.json()).public_key as string;
  return publicEncrypt({ key, padding: constants.RSA_PKCS1_OAEP_PADDING, oaepHash: 'sha256' }, Buffer.from(password)).toString('base64');
}

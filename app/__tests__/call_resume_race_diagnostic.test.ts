import { constants, publicEncrypt } from 'node:crypto';

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

class DiagnosticNative {
  private events: { onFailure?(event: { code: string }): void } = {};
  setCoordinatorEvents(events: { onFailure?(event: { code: string }): void }) { this.events = events; }
  async initialize() { return 'available' as const; }
  async getCapability() { return 'available' as const; }
  async startCapture(_format: CallAudioFormat, _listener: (frame: CapturedAudioFrame) => void) {}
  async stopCapture() {}
  async pauseCapture() {}
  async resumeCapture() {}
  async enqueue(_chunk: CallPlaybackChunk) {}
  async stop() {}
  async tombstone(_stream: CallPlaybackChunk['stream']) {}
  subscribeConsumption(_listener: (receipt: PlaybackConsumptionReceipt) => void) { return () => undefined; }
  async close() {}
  loseFocus() { this.events.onFailure?.({ code: 'audio_focus_lost' }); }
}

const callbacks: ConnectCallbacks = {
  onAgentMessage: jest.fn(), onAgentStateChanged: jest.fn(), onError: jest.fn(),
};
const diagnosticTest = resolveCallServerSource() ? test : test.skip;

diagnosticTest('focus-loss sends a legal close frame and resumes the original call within the first deadline', async () => {
  const originalWebSocket = globalThis.WebSocket;
  const clientTrace: { event: string; url: string; monotonic: number; code?: number }[] = [];
  class TracedWebSocket extends originalWebSocket {
    constructor(url: string | URL, protocols?: string | string[]) {
      super(url, protocols);
      const target = String(url);
      this.addEventListener('open', () => clientTrace.push({ event: 'open', url: target, monotonic: performance.now() }));
      this.addEventListener('close', () => clientTrace.push({ event: 'close_event', url: target, monotonic: performance.now() }));
    }
    close(code?: number, reason?: string) {
      clientTrace.push({ event: 'close_requested', url: this.url, monotonic: performance.now(), code });
      super.close(code, reason);
    }
  }
  globalThis.WebSocket = TracedWebSocket as typeof WebSocket;
  const server = await launchCallServer('success');
  const previous = server_config.BASE_URL;
  server_config.BASE_URL = server.url;
  let token = '';
  let chat: NetworkClient | undefined;
  let resolver: ProductionCallResolver | undefined;
  let attempt: ReturnType<ProductionCallResolver['createAttempt']> | undefined;
  try {
    token = await registerAndLogin(server.url);
    chat = new NetworkClient();
    const activeChat = chat;
    expect(await activeChat.reconnectWs('alice', token, 'luotianyi', callbacks)).toBe(true);
    const native = new DiagnosticNative();
    resolver = new ProductionCallResolver({
      characterId: 'luotianyi', credentials: { username: 'alice', token },
      switchPort: { prepare: (id, character) => activeChat.prepareCallSwitch(id, character) },
      createNativeAudio: () => native as never,
    });
    expect((await resolver.refreshCapability()).available).toBe(true);
    attempt = resolver.createAttempt();
    const activeAttempt = attempt;
    expect(await activeAttempt.initializeNative()).toBe(true);
    await activeAttempt.session.prepare('resume-race');
    await activeAttempt.session.start('resume-race', 'prepared_switch');
    const connected = await waitUntil(() => activeAttempt.session.state, (state) => state.status === 'connected');
    const callId = connected.callId!;

    const lostAt = performance.now();
    native.loseFocus();
    await waitUntil(
      () => activeAttempt.session.state,
      (state) => state.status === 'recovering',
    );
    const resumed = await waitUntil(
      () => activeAttempt.session.state,
      (state) => state.status === 'connected',
    );
    const elapsed = performance.now() - lostAt;
    console.info(`[call-resume-evidence] elapsed_ms=${elapsed.toFixed(1)} remaining_ms=${(3_000 - elapsed).toFixed(1)}`);
    expect(resumed.callId).toBe(callId);
    expect(elapsed).toBeLessThan(3_000);
    expect(resumed.recoveryDeadlineMonotonicMs).toBeUndefined();
    const callCloses = clientTrace.filter((event) => event.event === 'close_requested' && event.url.endsWith('/call_ws'));
    const callOpens = clientTrace.filter((event) => event.event === 'open' && event.url.endsWith('/call_ws'));
    expect(callCloses[0]).toMatchObject({ code: 4000 });
    expect(callOpens).toHaveLength(2);
    expect(callCloses[0].monotonic).toBeLessThan(callOpens[1].monotonic);
    expect(callOpens[1].monotonic - callCloses[0].monotonic).toBeLessThan(3_000);
    expect(activeAttempt.session.state.status).toBe('connected');
  } finally {
    globalThis.WebSocket = originalWebSocket;
    chat?.disconnectWs();
    await attempt?.close().catch(() => undefined);
    await resolver?.close().catch(() => undefined);
    server_config.BASE_URL = previous;
    const stopped = await server.stop();
    expect(stopped.exitCode).toBe(0);
    if (token) expect(stopped.logs).not.toContain(token);
  }
}, 60_000);

async function registerAndLogin(url: string): Promise<string> {
  const encrypted = await encryptedPassword(url, 'offline-password');
  const registered = await fetch(`${url}/auth/register`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: 'alice', password: encrypted, invite_code: 'invite' }),
  });
  expect(registered.ok).toBe(true);
  const login = await fetch(`${url}/auth/login`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: 'alice', password: await encryptedPassword(url, 'offline-password') }),
  });
  expect(login.ok).toBe(true);
  return (await login.json()).message_token as string;
}

async function encryptedPassword(url: string, password: string): Promise<string> {
  const response = await fetch(`${url}/auth/public_key`);
  const key = (await response.json()).public_key as string;
  return publicEncrypt({ key, padding: constants.RSA_PKCS1_OAEP_PADDING, oaepHash: 'sha256' }, Buffer.from(password)).toString('base64');
}

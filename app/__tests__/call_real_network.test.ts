import { constants, publicEncrypt } from 'node:crypto';

import { server_config } from '../config';
import type {
  CallAudioFormat,
  CallAudioStreamIdentity,
  CallPlaybackChunk,
  CapturedAudioFrame,
  PlaybackConsumptionReceipt,
} from '../utils/call_audio_contracts';
import { ProductionCallResolver } from '../utils/call_session/production_resolver';
import { NetworkClient, type ConnectCallbacks } from '../utils/network_client';
import { launchCallServer, resolveCallServerSource, waitUntil } from './support/call_network_server';

jest.mock('expo-file-system/legacy', () => ({}));
jest.mock('../utils/image_compression', () => ({
  compressImageForUpload: jest.fn(),
  MAX_IMAGE_FILE_SIZE_BYTES: 6 * 1024 * 1024,
}));
jest.mock('expo-av', () => ({ Audio: { requestPermissionsAsync: jest.fn() } }));
jest.mock('expo-constants', () => ({ __esModule: true, default: { executionEnvironment: 'standalone' } }));
jest.mock('react-native', () => ({
  Platform: { OS: 'android' },
  AppState: { currentState: 'active', addEventListener: jest.fn(() => ({ remove: jest.fn() })) },
}));
jest.mock('../utils/call_audio/native_call_audio', () => ({
  AndroidCallAudio: class {},
  isAndroidCallAudioModuleAvailable: jest.fn(() => true),
}));

const runnable = resolveCallServerSource() !== null;
const networkTest = runnable ? test : test.skip;

class ExternalNativeAudio {
  private capture?: (frame: CapturedAudioFrame) => void;
  private consumed: (receipt: PlaybackConsumptionReceipt) => void = () => undefined;
  private events: { onFailure?(event: { code: string }): void } = {};
  readonly chunks: CallPlaybackChunk[] = [];
  readonly consumedStreams: CallAudioStreamIdentity[] = [];
  readonly tombstones: CallPlaybackChunk['stream'][] = [];

  setCoordinatorEvents(events: { onFailure?(event: { code: string }): void }) { this.events = events; }
  async initialize() { return 'available' as const; }
  async getCapability() { return 'available' as const; }
  async startCapture(_format: CallAudioFormat, listener: (frame: CapturedAudioFrame) => void) { this.capture = listener; }
  async stopCapture() { this.capture = undefined; }
  async pauseCapture() {}
  async resumeCapture() {}
  async enqueue(chunk: CallPlaybackChunk) {
    this.chunks.push(chunk);
    if (chunk.isFinal) {
      queueMicrotask(() => {
        const receipt = { stream: chunk.stream };
        this.consumedStreams.push(receipt.stream);
        this.consumed(receipt);
      });
    }
  }
  async stop() {}
  async tombstone(stream: CallPlaybackChunk['stream']) { this.tombstones.push(stream); }
  subscribeConsumption(listener: (receipt: PlaybackConsumptionReceipt) => void) {
    this.consumed = listener;
    return () => { this.consumed = () => undefined; };
  }
  async close() {}
  capturePcm(payload: Uint8Array) {
    this.capture?.({ deviceSequence: 1, format: { encoding: 'pcm_s16le', sampleRateHz: 16_000, channels: 1 }, payload });
  }
  loseFocus() { this.events.onFailure?.({ code: 'audio_focus_lost' }); }
}

const callbacks: ConnectCallbacks = {
  onAgentMessage: jest.fn(),
  onAgentStateChanged: jest.fn(),
  onError: jest.fn(),
};

networkTest('real JS clients traverse the production FastAPI call lifecycle over loopback', async () => {
  jest.setTimeout(90_000);
  const server = await launchCallServer('success');
  const previousBaseUrl = server_config.BASE_URL;
  server_config.BASE_URL = server.url;
  let token = '';
  let transcript = '你还记得我喜欢什么吗';
  try {
    const credentials = await registerAndLogin(server.url, 'alice', 'offline-password');
    token = credentials.token;
    const chat = new NetworkClient();
    expect(await chat.reconnectWs('alice', token, 'luotianyi', callbacks)).toBe(true);

    const native = new ExternalNativeAudio();
    const resolver = new ProductionCallResolver({
      characterId: 'luotianyi',
      credentials: { username: 'alice', token },
      switchPort: { prepare: (requestId, characterId) => chat.prepareCallSwitch(requestId, characterId) },
      createNativeAudio: () => native as never,
    });
    expect((await resolver.refreshCapability()).available).toBe(true);
    const attempt = resolver.createAttempt();
    expect(await attempt.initializeNative()).toBe(true);
    const requestId = 'js-fastapi-request-1';
    await attempt.session.prepare(requestId);
    await attempt.session.start(requestId, 'prepared_switch');
    const connected = await waitUntil(
      () => attempt.session.state,
      (state) => state.status === 'connected' && Boolean(state.callId),
    );
    const callId = connected.callId!;

    const pcm = new Uint8Array([0x10, 0x00, 0x20, 0x00]);
    native.capturePcm(pcm);
    const evidence = await waitUntil(
      async () => await json(`${server.url}/test/evidence`),
      (value: any) => value.provider_audio.some((entry: any) => entry.call_id === callId && entry.frames.length > 0),
    ) as any;
    expect(evidence.provider_audio.find((entry: any) => entry.call_id === callId).frames[0].payload).toBe('10002000');
    await waitUntil(() => native.chunks.length, (count) => count >= 1);
    const existingStreamIdentities = new Set(native.chunks.map((chunk) => streamIdentityKey(chunk.stream)));

    expect((await fetch(`${server.url}/test/provider/${callId}/turn`, { method: 'POST' })).ok).toBe(true);
    const turnStreams = await waitUntil(
      () => selectNewTurnStreams(native.chunks, existingStreamIdentities),
      (streams) => streams.provisional !== undefined && streams.formal !== undefined,
    );
    const provisional = turnStreams.provisional!;
    const formal = turnStreams.formal!;
    expect(provisional.stream.responseId).not.toBe(formal.stream.responseId);
    expect(provisional.stream.streamId).not.toBe(formal.stream.streamId);
    await waitUntil(
      () => native.consumedStreams,
      (streams) => streams.some((stream) => sameStreamIdentity(stream, provisional.stream)),
    );

    const lostAt = performance.now();
    native.loseFocus();
    await waitUntil(() => attempt.session.state.status, (status) => status === 'recovering');
    const resumed = await waitUntil(() => attempt.session.state, (state) => state.status === 'connected');
    expect(resumed.callId).toBe(callId);
    expect(performance.now() - lostAt).toBeLessThan(3_000);
    expect(native.chunks.some((chunk) => sameStreamIdentity(chunk.stream, formal.stream) && !chunk.isFinal)).toBe(true);

    const tombstonesBeforeInterrupt = native.tombstones.length;
    expect((await fetch(`${server.url}/test/provider/${callId}/interrupt`, { method: 'POST' })).ok).toBe(true);
    const interruptTombstones = await waitUntil(
      () => native.tombstones.slice(tombstonesBeforeInterrupt),
      (streams) => streams.length > 0,
    );
    expect(sameStreamIdentity(interruptTombstones[0], formal.stream)).toBe(true);
    expect(interruptTombstones.some((stream) => sameStreamIdentity(stream, provisional.stream))).toBe(false);

    const chatRecovery = chat.reconnectWs('alice', token, 'luotianyi', callbacks, 10_000);
    await new Promise((resolve) => setTimeout(resolve, 300));
    await attempt.session.hangup();
    await waitUntil(() => attempt.session.state.status, (status) => status === 'closed', 15_000);
    expect(await chatRecovery).toBe(true);
    const sent = chat.sendChat('通话结束后的真实聊天', false, 'post-call-chat');
    expect(await sent).toMatchObject({ ok: true });

    const history = await waitUntil(
      async () => await json(`${server.url}/history?username=alice&count=10`, token),
      (value: any) => value.history.some((item: any) => item.type === 'call'),
      15_000,
    ) as any;
    const callHistory = history.history.find((item: any) => item.type === 'call');
    expect(callHistory.content).toMatch(/^\[语音通话\] /);
    expect(callHistory.content).not.toContain('用户与角色讨论');

    chat.disconnectWs();
    let resetAttempts = 0;
    const reset = await waitUntil(
      async () => {
        const response = await fetch(`${server.url}/user/data/reset`, {
        method: 'POST', headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: 'alice' }),
        });
        resetAttempts += 1;
        if (!response.ok && response.status !== 409) {
          throw new Error(`unexpected reset failure ${response.status}: ${await response.text()}`);
        }
        if (response.status === 409) {
          const detail = (await response.clone().json() as any).detail;
          expect(detail.code).toBe('USER_INTERACTION_BUSY');
        }
        return response;
      },
      (response) => response.ok,
      70_000,
    );
    expect(reset.ok).toBe(true);
    expect(resetAttempts).toBeGreaterThan(1);
    expect(await waitUntil(
      async () => await json(`${server.url}/test/reset_counts`),
      (value: any) => value.call_sessions === 0 && value.conversations === 0,
    )).toMatchObject({ call_sessions: 0, conversations: 0, memories: 0 });
    expect((await login(server.url, 'alice', 'offline-password')).token).toBeTruthy();
    await resolver.close();
  } finally {
    server_config.BASE_URL = previousBaseUrl;
    const stopped = await server.stop();
    expect(stopped.exitCode).toBe(0);
    const privatePcm = Buffer.from([0x10, 0x00, 0x20, 0x00]);
    for (const forbidden of [token, transcript, privatePcm.toString('base64'), privatePcm.toString('hex')]) {
      if (forbidden) expect(stopped.logs).not.toContain(forbidden);
    }
    transcript = '';
  }
}, 90_000);

networkTest('production capability remains disabled without a ready call graph', async () => {
  const server = await launchCallServer('disabled');
  const previousBaseUrl = server_config.BASE_URL;
  server_config.BASE_URL = server.url;
  try {
    const evidence = await json(`${server.url}/test/evidence`) as any;
    const resolver = new ProductionCallResolver({
      characterId: 'luotianyi',
      credentials: { username: 'alice', token: evidence.message_token },
      switchPort: { prepare: async () => undefined },
      createNativeAudio: () => new ExternalNativeAudio() as never,
    });
    expect(await resolver.refreshCapability()).toMatchObject({ available: false });
    expect(() => resolver.createAttempt()).toThrow('SERVER_CALL_UNAVAILABLE');
    await resolver.close();
  } finally {
    server_config.BASE_URL = previousBaseUrl;
    const stopped = await server.stop();
    expect(stopped.exitCode).toBe(0);
  }
}, 60_000);

function streamIdentityKey(stream: CallAudioStreamIdentity): string {
  return `${stream.callId}:${stream.responseId}:${stream.streamId}`;
}

function sameStreamIdentity(left: CallAudioStreamIdentity, right: CallAudioStreamIdentity): boolean {
  return left.callId === right.callId && left.responseId === right.responseId && left.streamId === right.streamId;
}

function selectNewTurnStreams(chunks: readonly CallPlaybackChunk[], existing: ReadonlySet<string>): {
  provisional?: CallPlaybackChunk;
  formal?: CallPlaybackChunk;
} {
  const newChunks = chunks.filter((chunk) => !existing.has(streamIdentityKey(chunk.stream)));
  return {
    provisional: newChunks.find((chunk) => chunk.isFinal),
    formal: newChunks.find((chunk) => !chunk.isFinal),
  };
}

async function registerAndLogin(url: string, username: string, password: string) {
  const encrypted = await encryptedPassword(url, password);
  const registered = await fetch(`${url}/auth/register`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password: encrypted, invite_code: 'invite' }),
  });
  expect(registered.ok).toBe(true);
  return await login(url, username, password);
}

async function login(url: string, username: string, password: string) {
  const response = await fetch(`${url}/auth/login`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password: await encryptedPassword(url, password) }),
  });
  expect(response.ok).toBe(true);
  return { token: (await response.json()).message_token as string };
}

async function encryptedPassword(url: string, password: string): Promise<string> {
  const publicKey = (await json(`${url}/auth/public_key`) as any).public_key as string;
  return publicEncrypt({ key: publicKey, padding: constants.RSA_PKCS1_OAEP_PADDING, oaepHash: 'sha256' }, Buffer.from(password)).toString('base64');
}

async function json(url: string, token?: string): Promise<unknown> {
  const response = await fetch(url, { headers: token ? { Authorization: `Bearer ${token}` } : undefined });
  if (!response.ok) throw new Error(`${response.status} ${await response.text()}`);
  return await response.json();
}

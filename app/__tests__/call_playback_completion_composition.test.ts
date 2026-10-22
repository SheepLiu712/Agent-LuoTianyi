import type { CallAudioNativeModule } from '../modules/call-audio/src/CallAudioModule';
import type { NativeCapability, NativePlaybackCompleted } from '../modules/call-audio/src/CallAudio.types';
import type { CallClock, CallSocket, CallSocketData, CallSocketEventMap } from '../types/call_transport';
import { AndroidCallAudio, CAPTURE_FORMAT, PLAYBACK_FORMAT } from '../utils/call_audio/native_call_audio';
import { BinaryAudioFrameCodec } from '../utils/call_protocol/audio_codec';
import { encodeControlMessage } from '../utils/call_protocol/control';
import { CallTransportSession } from '../utils/call_transport/call_transport';
import { NativeCallOwnership, ProductionCallResolver } from '../utils/call_session/production_resolver';
import { createCallMouthBridge } from '../utils/call_audio/playback_progress';

jest.mock('expo-modules-core', () => ({ requireOptionalNativeModule: jest.fn(() => ({})) }));
jest.mock('react-native', () => ({ Platform: { OS: 'android' } }));
jest.mock('expo-av', () => ({ Audio: { requestPermissionsAsync: jest.fn() } }));
jest.mock('expo-constants', () => ({ __esModule: true, default: { executionEnvironment: 'standalone' } }));

const CALL_ID = '11111111-1111-1111-1111-111111111111';

class Socket implements CallSocket {
  readyState = 1;
  sent: (string | Uint8Array)[] = [];
  private readonly listeners = new Map<keyof CallSocketEventMap, Set<(event: never) => void>>();
  send(data: string | Uint8Array): void { this.sent.push(data); }
  close(): void { this.readyState = 3; }
  addEventListener<Type extends keyof CallSocketEventMap>(type: Type, listener: (event: CallSocketEventMap[Type]) => void): void {
    const listeners = this.listeners.get(type) ?? new Set();
    listeners.add(listener as (event: never) => void);
    this.listeners.set(type, listeners);
  }
  removeEventListener<Type extends keyof CallSocketEventMap>(type: Type, listener: (event: CallSocketEventMap[Type]) => void): void {
    this.listeners.get(type)?.delete(listener as (event: never) => void);
  }
  message(data: CallSocketData): void {
    for (const listener of this.listeners.get('message') ?? []) listener({ data } as never);
  }
}

class Clock implements CallClock {
  monotonicMs(): number { return 100; }
  wallClockMs(): number { return 1_100; }
  setTimeout(): unknown { return {}; }
  clearTimeout(): void {}
}

class NativeBridge implements CallAudioNativeModule {
  setPlaybackAnalysisWindow = jest.fn(async (_seconds: number) => {});
  private readonly listeners = new Map<string, Set<(event: any) => void>>();
  private resolveEnqueue?: (generation: number) => void;
  private rejectEnqueue?: (error: Error) => void;
  readonly capability: NativeCapability = {
    available: true,
    captureFormat: CAPTURE_FORMAT as NativeCapability['captureFormat'],
    playbackFormat: PLAYBACK_FORMAT as NativeCapability['playbackFormat'],
    aec: { available: true, enabled: true },
    noiseSuppressor: { available: true, enabled: true },
    audioFocus: { granted: true },
    sessionGeneration: 1,
  };
  async getCapability() { return this.capability; }
  async startSession() { return this.capability; }
  async stopSession() {}
  async startCapture() { return this.capability; }
  async stopCapture() {}
  async reacquireAudioFocus() { return this.capability; }
  async acknowledgeCapturedAudio() {}
  async enqueuePlayback() {
    return new Promise<number>((resolve, reject) => { this.resolveEnqueue = resolve; this.rejectEnqueue = reject; });
  }
  async stopPlayback() {}
  async tombstone() {}
  async playReplyFailureTone() {}
  addListener(eventName: string, listener: (event: any) => void) {
    const listeners = this.listeners.get(eventName) ?? new Set();
    listeners.add(listener);
    this.listeners.set(eventName, listeners);
    return { remove: () => listeners.delete(listener) };
  }
  complete(responseId = 'response-1', streamId = 9, generation = 7): void {
    const event: NativePlaybackCompleted = {
      responseId, streamId, generation, sessionGeneration: 1,
    };
    this.listeners.get('onPlaybackCompleted')?.forEach((listener) => listener(event));
  }
  progress(rms: number, responseId = 'response-1', streamId = 9, generation = 7, sessionGeneration = 1): void {
    this.listeners.get('onPlaybackProgress')?.forEach((listener) => listener({
      responseId, streamId, generation, sessionGeneration, rms,
    }));
  }
  acceptEnqueue(generation = 7): void {
    if (!this.resolveEnqueue) throw new Error('no pending enqueue');
    const resolve = this.resolveEnqueue;
    this.resolveEnqueue = undefined;
    this.rejectEnqueue = undefined;
    resolve(generation);
  }
  failEnqueue(): void {
    if (!this.rejectEnqueue) throw new Error('no pending enqueue');
    const reject = this.rejectEnqueue;
    this.resolveEnqueue = undefined;
    this.rejectEnqueue = undefined;
    reject(new Error('native_enqueue_failed'));
  }
}

function control(message: Parameters<typeof encodeControlMessage>[0]): string {
  return encodeControlMessage(message, { transport: 'call_ws', direction: 'server_to_client' });
}

async function flush(): Promise<void> { for (let index = 0; index < 12; index += 1) await Promise.resolve(); }

const sessions: { transport: CallTransportSession; audio: AndroidCallAudio }[] = [];
afterEach(async () => {
  for (const { transport, audio } of sessions.splice(0)) {
    transport.close();
    await flush();
    await audio.close();
  }
});

async function establish() {
  const socket = new Socket();
  const bridge = new NativeBridge();
  const audio = new AndroidCallAudio({}, bridge, 'android');
  await audio.initialize();
  const transport = new CallTransportSession({
    url: 'ws://example/call_ws', credentials: { username: 'u', token: 't' }, characterId: 'luotianyi',
    sockets: { create: () => socket }, nativeAudio: audio, clock: new Clock(),
    serverAvailable: true, nativeAvailable: true,
  });
  sessions.push({ transport, audio });
  await transport.start({ clientRequestId: 'request-1', characterId: 'luotianyi' });
  socket.message(JSON.stringify({ type: 'auth_ok', payload: {} }));
  socket.message(control({
    protocol: 'call.v1', type: 'call.state', seq: 1, call_id: CALL_ID,
    client_request_id: 'request-1', state: 'preparing',
  }));
  socket.message(control({ protocol: 'call.v1', type: 'call.active', seq: 2, call_id: CALL_ID, connected_at_ms: 1_000 }));
  await flush();
  expect(transport.state.status).toBe('connected');
  await enqueueFinal(socket);
  return { socket, bridge, transport };
}

async function enqueueFinal(socket: Socket, seq = 3, responseId = 'response-1', streamId = 9) {
  socket.message(control({
    protocol: 'call.v1', type: 'audio.stream_started', seq, call_id: CALL_ID, audio_route: 'CALL',
    stream_id: streamId, response_id: responseId, encoding: 'pcm_s16le', sample_rate: 24000, channels: 1,
  }));
  socket.message(new BinaryAudioFrameCodec().encode({
    version: 1, route: 2, flags: 1, streamId, seq: seq + 1, payload: new Uint8Array([1, 0]),
  }));
  await flush();
}

function stopCurrent(socket: Socket) {
  socket.message(control({
    protocol: 'call.v1', type: 'playback.stop', seq: 5, call_id: CALL_ID,
    response_id: 'response-1', stream_id: 9,
    retire_server_seq: { from: 3, through: 4 }, reason: 'user_interrupted',
  }));
}

test.each(['early', 'late'])('native %s completion reaches call.v1 wire once', async (timing) => {
  const { socket, bridge, transport } = await establish();
  if (timing === 'early') bridge.complete();
  expect(wireCompletions(socket)).toHaveLength(0);
  bridge.acceptEnqueue();
  await flush();
  if (timing === 'late') {
    expect(wireCompletions(socket)).toHaveLength(0);
    bridge.complete();
  }
  expect(wireCompletions(socket)).toHaveLength(1);
  bridge.complete();
  expect(wireCompletions(socket)).toHaveLength(1);
  expect(transport.state.status).toBe('connected');
});

test.each([false, true])('unretired enqueue rejection stays fatal (early completion: %s)', async (early) => {
  const { socket, bridge, transport } = await establish();
  if (early) bridge.complete();
  bridge.failEnqueue();
  await flush();
  bridge.complete();
  expect(wireCompletions(socket)).toHaveLength(0);
  expect(transport.state).toMatchObject({ status: 'failed', errorCode: 'native_enqueue_failed' });
});

test.each([
  ['resolve', 'none'], ['resolve', 'before-stop'], ['resolve', 'after-stop'],
  ['reject', 'none'], ['reject', 'before-stop'], ['reject', 'after-stop'],
])('stop during pending final survives %s with completion %s and accepts the next reply', async (outcome, completion) => {
  const { socket, bridge, transport } = await establish();
  if (completion === 'before-stop') bridge.complete();
  stopCurrent(socket);
  await flush();
  if (completion === 'after-stop') bridge.complete();
  if (outcome === 'resolve') bridge.acceptEnqueue();
  else bridge.failEnqueue();
  await flush();
  bridge.complete();
  stopCurrent(socket); // Replay must neither revive the old final nor fail the call.
  await flush();
  expect(transport.state.status).toBe('connected');
  expect(transport.state.errorCode).toBeUndefined();
  expect(wireCompletions(socket)).toHaveLength(0);
  expect(wireControls(socket).filter((message) => message.type === 'playback.stopped')).toHaveLength(1);
  expect(wireControls(socket)).toContainEqual(expect.objectContaining({ type: 'ack', ack_seq: 5 }));

  await enqueueFinal(socket, 6, 'response-2', 10);
  bridge.complete(); // Old callback while the next stream's final is pending.
  bridge.acceptEnqueue(8);
  await flush();
  expect(wireCompletions(socket)).toHaveLength(0);
  bridge.complete('response-2', 10, 8);
  bridge.complete('response-2', 10, 8);
  expect(wireCompletions(socket)).toHaveLength(1);
  expect(wireCompletions(socket)[0]).toMatchObject({ response_id: 'response-2', stream_id: 10 });
  expect(transport.state.status).toBe('connected');
});

test.each(['tombstone', 'stopPlayback'] as const)('a native %s failure still fails the call', async (operation) => {
  const { socket, bridge, transport } = await establish();
  bridge[operation] = async () => { throw new Error('native_stop_failed'); };
  stopCurrent(socket);
  await flush();
  bridge.acceptEnqueue();
  await flush();
  expect(wireCompletions(socket)).toHaveLength(0);
  expect(transport.state).toMatchObject({ status: 'failed', errorCode: 'native_stop_failed' });
});

test.each([
  ['resolve', false], ['resolve', true], ['reject', false], ['reject', true],
] as const)('close during pending final stays closed after %s (early completion: %s)', async (outcome, early) => {
  const { socket, bridge, transport } = await establish();
  if (early) bridge.complete();
  transport.close();
  await flush();
  const sentAtClose = socket.sent.length;
  if (outcome === 'resolve') bridge.acceptEnqueue();
  else bridge.failEnqueue();
  await flush();
  bridge.complete();
  expect(transport.state.status).toBe('closed');
  expect(transport.state.errorCode).toBeUndefined();
  expect(socket.readyState).toBe(3);
  expect(socket.sent).toHaveLength(sentAtClose);
  expect(wireCompletions(socket)).toHaveLength(0);
});

function wireControls(socket: Socket): any[] {
  return socket.sent.filter((wire): wire is string => typeof wire === 'string')
    .map((wire) => JSON.parse(wire));
}

function wireCompletions(socket: Socket): any[] {
  return wireControls(socket).filter((message) => message.type === 'playback.completed');
}

test('production resolver drives live RMS, independent early completion, and stream-scoped reset', async () => {
  const socket = new Socket();
  const bridge = new NativeBridge();
  const audio = new AndroidCallAudio({}, bridge, 'android');
  const inject = jest.fn();
  const mouth = createCallMouthBridge(inject);
  mouth.configureAnalysisWindow(44_100, 128);
  const resolver = new ProductionCallResolver({
    characterId: 'luotianyi', credentials: { username: 'u', token: 't' },
    switchPort: { prepare: jest.fn() }, sockets: { create: () => socket },
    nativeOwnership: new NativeCallOwnership(), createNativeAudio: () => audio, mouthBridge: mouth,
    fetchImpl: jest.fn(async () => ({ ok: true, status: 200,
      json: async () => ({ available: true, character_id: 'luotianyi', reason: 'available' }),
    })) as unknown as typeof fetch,
  });
  try {
    await resolver.refreshCapability();
    const attempt = resolver.createAttempt();
    await attempt.initializeNative();
    expect(bridge.setPlaybackAnalysisWindow).toHaveBeenLastCalledWith(128 / 44_100);
    await attempt.session.start('request-1', 'direct_no_chat');
    socket.message(JSON.stringify({ type: 'auth_ok', payload: {} }));
    socket.message(control({ protocol: 'call.v1', type: 'call.state', seq: 1, call_id: CALL_ID,
      client_request_id: 'request-1', state: 'preparing' }));
    socket.message(control({ protocol: 'call.v1', type: 'call.active', seq: 2, call_id: CALL_ID, connected_at_ms: Date.now() }));
    await flush();
    await enqueueFinal(socket);
    bridge.progress(0.5);
    expect(inject).toHaveBeenLastCalledWith('window.setCallMouthRms(0.5); true;');
    bridge.progress(0);
    expect(inject).toHaveBeenLastCalledWith('window.setCallMouthRms(0); true;');
    bridge.complete();
    expect(inject).toHaveBeenLastCalledWith('window.resetCallMouth(); true;');
    expect(wireCompletions(socket)).toHaveLength(0);
    const beforeAcceptance = inject.mock.calls.length;
    bridge.acceptEnqueue();
    await flush();
    expect(inject).toHaveBeenCalledTimes(beforeAcceptance);
    expect(wireCompletions(socket)).toHaveLength(1);
    bridge.progress(0.9);
    expect(inject).toHaveBeenCalledTimes(beforeAcceptance);

    await enqueueFinal(socket, 5, 'response-2', 10);
    bridge.progress(0.6, 'response-2', 10, 8);
    expect(inject).toHaveBeenLastCalledWith('window.setCallMouthRms(0.6); true;');
    socket.message(control({ protocol: 'call.v1', type: 'playback.stop', seq: 7, call_id: CALL_ID,
      response_id: 'response-1', stream_id: 9, retire_server_seq: { from: 3, through: 4 }, reason: 'user_interrupted' }));
    await flush();
    // A stop for the old completed reply must not close the new reply's mouth.
    expect(inject).toHaveBeenLastCalledWith('window.setCallMouthRms(0.6); true;');
    socket.message(control({ protocol: 'call.v1', type: 'playback.stop', seq: 8, call_id: CALL_ID,
      response_id: 'response-2', stream_id: 10, retire_server_seq: { from: 5, through: 6 }, reason: 'user_interrupted' }));
    expect(inject).toHaveBeenLastCalledWith('window.resetCallMouth(); true;');
    const afterStop = inject.mock.calls.length;
    bridge.failEnqueue();
    await flush();
    bridge.progress(0.6, 'response-2', 10, 8);
    expect(inject).toHaveBeenCalledTimes(afterStop);
    expect(attempt.session.state.status).toBe('connected');
    await attempt.close();
    bridge.progress(0.7);
    expect(inject).toHaveBeenCalledTimes(afterStop);
    const configured = bridge.setPlaybackAnalysisWindow.mock.calls.length;
    mouth.configureAnalysisWindow(48_000, 128);
    expect(bridge.setPlaybackAnalysisWindow).toHaveBeenCalledTimes(configured);
  } finally {
    await resolver.close();
  }
});

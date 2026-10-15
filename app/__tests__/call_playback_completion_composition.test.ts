import type { CallAudioNativeModule } from '../modules/call-audio/src/CallAudioModule';
import type { NativeCapability, NativePlaybackCompleted } from '../modules/call-audio/src/CallAudio.types';
import type { CallClock, CallSocket, CallSocketData, CallSocketEventMap } from '../types/call_transport';
import { AndroidCallAudio, CAPTURE_FORMAT, PLAYBACK_FORMAT } from '../utils/call_audio/native_call_audio';
import { BinaryAudioFrameCodec } from '../utils/call_protocol/audio_codec';
import { encodeControlMessage } from '../utils/call_protocol/control';
import { CallTransportSession } from '../utils/call_transport/call_transport';

jest.mock('expo-modules-core', () => ({ requireOptionalNativeModule: jest.fn(() => null) }));
jest.mock('react-native', () => ({ Platform: { OS: 'android' } }));

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
  private readonly listeners = new Map<string, Set<(event: any) => void>>();
  private resolveEnqueue?: (generation: number) => void;
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
  async enqueuePlayback() { return new Promise<number>((resolve) => { this.resolveEnqueue = resolve; }); }
  async stopPlayback() {}
  async tombstone() {}
  async playReplyFailureTone() {}
  addListener(eventName: string, listener: (event: any) => void) {
    const listeners = this.listeners.get(eventName) ?? new Set();
    listeners.add(listener);
    this.listeners.set(eventName, listeners);
    return { remove: () => listeners.delete(listener) };
  }
  completeEarly(): void {
    const event: NativePlaybackCompleted = {
      responseId: 'response-1', streamId: 9, generation: 7, sessionGeneration: 1,
    };
    this.listeners.get('onPlaybackCompleted')?.forEach((listener) => listener(event));
  }
  acceptEnqueue(): void { this.resolveEnqueue?.(7); }
}

function control(message: Parameters<typeof encodeControlMessage>[0]): string {
  return encodeControlMessage(message, { transport: 'call_ws', direction: 'server_to_client' });
}

async function flush(): Promise<void> { for (let index = 0; index < 12; index += 1) await Promise.resolve(); }

test('Expo native bridge early completion reaches call.v1 wire once after enqueue acceptance', async () => {
  const socket = new Socket();
  const bridge = new NativeBridge();
  const audio = new AndroidCallAudio({}, bridge, 'android');
  await audio.initialize();
  const transport = new CallTransportSession({
    url: 'ws://example/call_ws', credentials: { username: 'u', token: 't' }, characterId: 'luotianyi',
    sockets: { create: () => socket }, nativeAudio: audio, clock: new Clock(),
    serverAvailable: true, nativeAvailable: true,
  });
  await transport.start({ clientRequestId: 'request-1', characterId: 'luotianyi' });
  socket.message(JSON.stringify({ type: 'auth_ok', payload: {} }));
  socket.message(control({
    protocol: 'call.v1', type: 'call.state', seq: 1, call_id: CALL_ID,
    client_request_id: 'request-1', state: 'preparing',
  }));
  socket.message(control({ protocol: 'call.v1', type: 'call.active', seq: 2, call_id: CALL_ID, connected_at_ms: 1_000 }));
  socket.message(control({
    protocol: 'call.v1', type: 'audio.stream_started', seq: 3, call_id: CALL_ID, audio_route: 'CALL',
    stream_id: 9, response_id: 'response-1', encoding: 'pcm_s16le', sample_rate: 24000, channels: 1,
  }));
  socket.message(new BinaryAudioFrameCodec().encode({
    version: 1, route: 2, flags: 1, streamId: 9, seq: 4, payload: new Uint8Array([1, 0]),
  }));
  await flush();

  bridge.completeEarly();
  await flush();
  expect(wireCompletions(socket)).toHaveLength(0);
  bridge.acceptEnqueue();
  await flush();
  expect(wireCompletions(socket)).toHaveLength(1);
  bridge.completeEarly();
  expect(wireCompletions(socket)).toHaveLength(1);
});

function wireCompletions(socket: Socket): any[] {
  return socket.sent.filter((wire): wire is string => typeof wire === 'string')
    .map((wire) => JSON.parse(wire)).filter((message) => message.type === 'playback.completed');
}

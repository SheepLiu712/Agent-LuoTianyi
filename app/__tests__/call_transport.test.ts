import { BinaryAudioFrameCodec } from '../utils/call_protocol/audio_codec';
import { encodeControlMessage } from '../utils/call_protocol/control';
import { CallTransportSession } from '../utils/call_transport/call_transport';
import { CallSession } from '../utils/call_session/call_session';
import { IncomingCallSequence } from '../utils/call_transport/incoming_sequence';
import { ReliableCallOutbox } from '../utils/call_transport/reliable_outbox';
import { createPlatformCallSocketFactory } from '../utils/call_transport/websocket_adapter';
import type {
  CallClock,
  CallNativeAudioPort,
  CallSocket,
  CallSocketData,
  CallSocketEventMap,
  CallSocketFactory,
} from '../types/call_transport';
import type { CapturedAudioFrame, PlaybackConsumptionReceipt } from '../utils/call_audio_contracts';

const CALL_ID = '11111111-1111-1111-1111-111111111111';

class FakeSocket implements CallSocket {
  readyState = 1;
  closeCount = 0;
  sent: (string | Uint8Array)[] = [];
  private listeners = new Map<keyof CallSocketEventMap, Set<(event: never) => void>>();

  send(data: string | Uint8Array): void { this.sent.push(data); }
  close(code?: number, reason?: string): void {
    if (code !== undefined && code !== 1000 && (code < 3000 || code > 4999)) {
      throw new DOMException('invalid close code', 'InvalidAccessError');
    }
    if (reason !== undefined && new TextEncoder().encode(reason).byteLength > 123) {
      throw new DOMException('close reason is too long', 'SyntaxError');
    }
    this.closeCount += 1;
    this.readyState = 3;
  }
  addEventListener<Type extends keyof CallSocketEventMap>(type: Type, listener: (event: CallSocketEventMap[Type]) => void): void {
    const listeners = this.listeners.get(type) ?? new Set();
    listeners.add(listener as (event: never) => void);
    this.listeners.set(type, listeners);
  }
  removeEventListener<Type extends keyof CallSocketEventMap>(type: Type, listener: (event: CallSocketEventMap[Type]) => void): void {
    this.listeners.get(type)?.delete(listener as (event: never) => void);
  }
  emit<Type extends keyof CallSocketEventMap>(type: Type, event: CallSocketEventMap[Type]): void {
    for (const listener of this.listeners.get(type) ?? []) listener(event as never);
  }
  message(data: CallSocketData | ArrayBuffer | Blob): void { this.emit('message', { data: data as CallSocketData }); }
}

class FakeSockets implements CallSocketFactory {
  sockets: FakeSocket[] = [];
  create(): CallSocket { const socket = new FakeSocket(); this.sockets.push(socket); return socket; }
}

class FakeClock implements CallClock {
  now = 100;
  timers: { callback: () => void; due: number }[] = [];
  monotonicMs(): number { return this.now; }
  wallClockMs(): number { return 1_000 + this.now; }
  setTimeout(callback: () => void, delayMs: number): unknown { const timer = { callback, due: this.now + delayMs }; this.timers.push(timer); return timer; }
  clearTimeout(handle: unknown): void { this.timers = this.timers.filter((timer) => timer !== handle); }
  advance(ms: number): void { this.now += ms; const due = this.timers.filter((timer) => timer.due <= this.now); this.timers = this.timers.filter((timer) => timer.due > this.now); due.forEach((timer) => timer.callback()); }
}

function fakeNative(): CallNativeAudioPort & {
  frames: ((frame: CapturedAudioFrame) => void)[];
  enqueued: Uint8Array[];
  listener?: (receipt: PlaybackConsumptionReceipt) => void;
  pauseCount: number;
  unsubscribeCount: number;
  stopCaptureCount: number;
  stopPlaybackCount: number;
} {
  return {
    frames: [], enqueued: [], pauseCount: 0, unsubscribeCount: 0, stopCaptureCount: 0, stopPlaybackCount: 0,
    async getCapability() { return 'available'; },
    async startCapture(_format, onFrame) { this.frames.push(onFrame); },
    async stopCapture() { this.stopCaptureCount += 1; },
    async pauseCapture() { this.pauseCount += 1; },
    async resumeCapture() {},
    async enqueue(chunk) { this.enqueued.push(chunk.payload); },
    async stop() { this.stopPlaybackCount += 1; },
    async tombstone() {},
    subscribeConsumption(listener) { this.listener = listener; return () => { this.listener = undefined; this.unsubscribeCount += 1; }; },
  };
}

function serverControl(message: Parameters<typeof encodeControlMessage>[0]): string {
  return encodeControlMessage(message, { transport: 'call_ws', direction: 'server_to_client' });
}

async function flush(): Promise<void> {
  for (let index = 0; index < 12; index += 1) await Promise.resolve();
}

async function establish() {
  const sockets = new FakeSockets();
  const native = fakeNative();
  const clock = new FakeClock();
  const session = new CallTransportSession({
    url: 'ws://example/call_ws', credentials: { username: 'u', token: 't' }, characterId: 'luotianyi',
    sockets, nativeAudio: native, clock, serverAvailable: true, nativeAvailable: true,
  });
  await session.start({ clientRequestId: 'request-1', characterId: 'luotianyi' });
  const socket = sockets.sockets[0];
  socket.message(JSON.stringify({ type: 'system_ready', payload: {} }));
  socket.message(JSON.stringify({ type: 'auth_ok', payload: {} }));
  await flush();
  socket.message(serverControl({ protocol: 'call.v1', type: 'call.state', seq: 1, call_id: CALL_ID, client_request_id: 'request-1', state: 'preparing' }));
  socket.message(serverControl({ protocol: 'call.v1', type: 'call.active', seq: 2, call_id: CALL_ID, connected_at_ms: 10 }));
  await flush();
  return { sockets, native, clock, session, socket };
}

describe('reliable call transport', () => {
  test('keeps exact numbered bytes until cumulative ACK', () => {
    const outbox = new ReliableCallOutbox(100, 2);
    const first = outbox.add('control', (seq) => `wire-${seq}`);
    expect(outbox.replayMissing(1).wire).toBe(first.wire);
    outbox.acknowledge(1);
    expect(() => outbox.replayMissing(1)).toThrow('REPLAY_NOT_AVAILABLE');
    expect(() => outbox.acknowledge(2)).toThrow('INVALID_ACK_CURSOR');
  });

  test('allows a matching stop to retire a gap but rejects unrelated received content', () => {
    const incoming = new IncomingCallSequence();
    incoming.receive({ seq: 1, raw: new Uint8Array([1]), control: {
      protocol: 'call.v1', type: 'audio.stream_started', seq: 1, call_id: CALL_ID, audio_route: 'CALL',
      stream_id: 7, response_id: 'r', encoding: 'pcm_s16le', sample_rate: 24000, channels: 1,
    } });
    incoming.claimReady();
    incoming.commitClaimed(1);
    expect(() => incoming.receive({ seq: 3, raw: new Uint8Array([3]), control: {
      protocol: 'call.v1', type: 'playback.stop', seq: 3, call_id: CALL_ID, response_id: 'other', stream_id: 7,
      retire_server_seq: { from: 1, through: 2 }, reason: 'user_interrupted',
    } })).toThrow('INVALID_RETIRE_RANGE');
  });

  test('releases committed payload and keeps bounded lightweight receipts', () => {
    const incoming = new IncomingCallSequence(4, 64, 2);
    for (let seq = 1; seq <= 3; seq += 1) {
      incoming.receive({ seq, raw: new Uint8Array(16), audio: { responseId: 'r', streamId: 7, final: false, payload: new Uint8Array(2) } });
      incoming.claimReady();
      incoming.commitClaimed(seq);
      expect(incoming.retainedPayloadBytes).toBe(0);
    }
    incoming.clear();
    expect(incoming.retainedPayloadBytes).toBe(0);
  });

  test('retired late audio is ignored for the same stream and rejected for a different stream', () => {
    const incoming = new IncomingCallSequence();
    incoming.receive({ seq: 1, raw: new Uint8Array([1]), control: {
      protocol: 'call.v1', type: 'audio.stream_started', seq: 1, call_id: CALL_ID, audio_route: 'CALL',
      stream_id: 7, response_id: 'r', encoding: 'pcm_s16le', sample_rate: 24000, channels: 1,
    } });
    incoming.claimReady(); incoming.commitClaimed(1);
    incoming.receive({ seq: 3, raw: new Uint8Array([3]), control: {
      protocol: 'call.v1', type: 'playback.stop', seq: 3, call_id: CALL_ID, response_id: 'r', stream_id: 7,
      retire_server_seq: { from: 1, through: 2 }, reason: 'user_interrupted',
    } });
    incoming.claimReady(); incoming.commitClaimed(3);
    expect(incoming.receive({ seq: 2, raw: new Uint8Array([2]), audio: {
      responseId: 'r', streamId: 7, final: false, payload: new Uint8Array([2, 0]),
    } }).ignoredRetiredDuplicate).toBe(true);
    expect(() => incoming.receive({ seq: 2, raw: new Uint8Array([2]), audio: {
      responseId: 'wrong', streamId: 8, final: false, payload: new Uint8Array([2, 0]),
    } })).toThrow('SEQ_CONFLICT');
  });

  test('compressed ownership survives receipt eviction for a long response stop', () => {
    const incoming = new IncomingCallSequence(512, 1024 * 1024, 2, 4);
    incoming.receive({ seq: 1, raw: new Uint8Array([1]), control: {
      protocol: 'call.v1', type: 'audio.stream_started', seq: 1, call_id: CALL_ID, audio_route: 'CALL',
      stream_id: 7, response_id: 'r', encoding: 'pcm_s16le', sample_rate: 24000, channels: 1,
    } });
    incoming.claimReady(); incoming.commitClaimed(1);
    for (let seq = 2; seq <= 100; seq += 1) {
      incoming.receive({ seq, raw: new Uint8Array([seq]), audio: {
        responseId: 'r', streamId: 7, final: false, payload: new Uint8Array([2, 0]),
      } });
      incoming.claimReady(); incoming.commitClaimed(seq);
    }
    expect(() => incoming.receive({ seq: 101, raw: new Uint8Array([101]), control: {
      protocol: 'call.v1', type: 'playback.stop', seq: 101, call_id: CALL_ID, response_id: 'r', stream_id: 7,
      retire_server_seq: { from: 1, through: 100 }, reason: 'user_interrupted',
    } })).not.toThrow();
    expect(incoming.retainedPayloadBytes).toBe(1);
    expect(incoming.retainedMetadataCount).toBeLessThanOrEqual(7);
  });

  test('uses the real auth envelope then sends call.start with the prepared request id', async () => {
    const sockets = new FakeSockets();
    const session = new CallTransportSession({
      url: 'ws://example/call_ws', credentials: { username: 'u', token: 'secret' }, characterId: 'luotianyi',
      sockets, nativeAudio: fakeNative(), clock: new FakeClock(), serverAvailable: true, nativeAvailable: true,
    });
    await session.start({ clientRequestId: 'request-1', characterId: 'luotianyi' });
    sockets.sockets[0].message(JSON.stringify({ type: 'system_ready', payload: {} }));
    sockets.sockets[0].message(JSON.stringify({ type: 'auth_ok', payload: {} }));
    await flush();
    expect(JSON.parse(sockets.sockets[0].sent[0] as string).type).toBe('user_auth');
    expect(JSON.parse(sockets.sockets[0].sent[1] as string)).toMatchObject({
      type: 'call.start', seq: 1, client_request_id: 'request-1', character_id: 'luotianyi',
    });
  });

  test('ACKs server audio only after native enqueue and completion is a sequenced retriable control', async () => {
    const { socket, native } = await establish();
    socket.message(serverControl({
      protocol: 'call.v1', type: 'audio.stream_started', seq: 3, call_id: CALL_ID, audio_route: 'CALL',
      stream_id: 9, response_id: 'response-1', encoding: 'pcm_s16le', sample_rate: 24000, channels: 1,
    }));
    const codec = new BinaryAudioFrameCodec();
    socket.message(codec.encode({ version: 1, route: 2, flags: 1, streamId: 9, seq: 4, payload: new Uint8Array([1, 0]) }));
    await flush();
    expect(native.enqueued).toHaveLength(1);
    expect(JSON.parse(socket.sent.at(-1) as string)).toMatchObject({ type: 'ack', ack_seq: 4 });
    native.listener?.({ stream: { callId: CALL_ID, responseId: 'response-1', streamId: 9 } });
    const completed = socket.sent.map((wire) => typeof wire === 'string' ? JSON.parse(wire) : null).find((item) => item?.type === 'playback.completed');
    expect(completed).toMatchObject({ seq: 2, response_id: 'response-1', stream_id: 9 });
  });

  test('orders binary audio that arrives before its stream_started control', async () => {
    const { socket, native } = await establish();
    const codec = new BinaryAudioFrameCodec();
    socket.message(codec.encode({ version: 1, route: 2, flags: 1, streamId: 9, seq: 4, payload: new Uint8Array([1, 0]) }));
    socket.message(serverControl({
      protocol: 'call.v1', type: 'audio.stream_started', seq: 3, call_id: CALL_ID, audio_route: 'CALL',
      stream_id: 9, response_id: 'response-1', encoding: 'pcm_s16le', sample_rate: 24000, channels: 1,
    }));
    await flush();
    expect(native.enqueued).toEqual([new Uint8Array([1, 0])]);
    expect(JSON.parse(socket.sent.filter((wire): wire is string => typeof wire === 'string').at(-1)!)).toMatchObject({ type: 'ack', ack_seq: 4 });
  });

  test('deferred binary reorder waits for ordered stream registration', async () => {
    const { socket, native } = await establish();
    let release!: (bytes: Uint8Array) => void;
    socket.message({ resolve: () => new Promise<Uint8Array>((resolve) => { release = resolve; }) });
    socket.message(serverControl({
      protocol: 'call.v1', type: 'audio.stream_started', seq: 3, call_id: CALL_ID, audio_route: 'CALL',
      stream_id: 9, response_id: 'response-1', encoding: 'pcm_s16le', sample_rate: 24000, channels: 1,
    }));
    await flush();
    release(new BinaryAudioFrameCodec().encode({ version: 1, route: 2, flags: 1, streamId: 9, seq: 4, payload: new Uint8Array([1, 0]) }));
    await flush();
    expect(native.enqueued).toHaveLength(1);
  });

  test('pauses capture at the bounded 96KB unacknowledged PCM budget', async () => {
    const { native } = await establish();
    const emit = native.frames[0];
    const format = { encoding: 'pcm_s16le', sampleRateHz: 16_000, channels: 1 };
    for (let index = 0; index < 6; index += 1) emit({ deviceSequence: index + 1, format, payload: new Uint8Array(16_000) });
    emit({ deviceSequence: 7, format, payload: new Uint8Array(2) });
    await flush();
    expect(native.pauseCount).toBe(1);
  });

  test('stop cancels the stream generation and late native completion cannot fake completion', async () => {
    const { socket, native } = await establish();
    socket.message(serverControl({
      protocol: 'call.v1', type: 'audio.stream_started', seq: 3, call_id: CALL_ID, audio_route: 'CALL',
      stream_id: 9, response_id: 'response-1', encoding: 'pcm_s16le', sample_rate: 24000, channels: 1,
    }));
    const codec = new BinaryAudioFrameCodec();
    socket.message(codec.encode({ version: 1, route: 2, flags: 1, streamId: 9, seq: 4, payload: new Uint8Array([1, 0]) }));
    await flush();
    socket.message(serverControl({
      protocol: 'call.v1', type: 'playback.stop', seq: 5, call_id: CALL_ID, response_id: 'response-1', stream_id: 9,
      retire_server_seq: { from: 3, through: 4 }, reason: 'user_interrupted',
    }));
    await flush();
    native.listener?.({ stream: { callId: CALL_ID, responseId: 'response-1', streamId: 9 } });
    const messages = socket.sent.filter((wire): wire is string => typeof wire === 'string').map((wire) => JSON.parse(wire));
    expect(messages.some((message) => message.type === 'playback.stopped' && message.stop_seq === 5)).toBe(true);
    expect(messages.some((message) => message.type === 'playback.completed')).toBe(false);
  });

  test('audio focus loss uses the existing fixed recovery window and resumes the same call', async () => {
    const { session, sockets } = await establish();
    session.forceRecovery('AUDIO_FOCUS_LOST');
    expect(session.state.status).toBe('recovering');
    expect(session.state.callId).toBe(CALL_ID);
    expect(sockets.sockets).toHaveLength(2);
    expect(session.state.recoveryDeadlineMonotonicMs).toBeDefined();
  });

  test('audio focus recovery uses an application close code and fails closed if close throws', async () => {
    const established = await establish();
    established.socket.close = jest.fn((code) => {
      expect(code).toBe(4000);
      established.socket.emit('close', { code });
    });
    established.session.forceRecovery('AUDIO_FOCUS_LOST');
    expect(established.session.state.status).toBe('recovering');
    expect(established.sockets.sockets).toHaveLength(2);

    const failed = await establish();
    failed.socket.close = jest.fn(() => { throw new DOMException('invalid close code', 'InvalidAccessError'); });
    failed.session.forceRecovery('AUDIO_FOCUS_LOST');
    expect(failed.session.state).toMatchObject({ status: 'failed', errorCode: 'AUDIO_FOCUS_CLOSE_FAILED' });
    expect(failed.sockets.sockets).toHaveLength(1);
  });

  test('protocol failure closes with a legal private code and content-free bounded reason', async () => {
    const established = await establish();
    const close = jest.spyOn(established.socket, 'close');
    established.socket.message('{bad json');
    await flush();
    expect(established.session.state.status).toBe('failed');
    expect(close).toHaveBeenCalledWith(4001, 'call transport failed');
    expect(new TextEncoder().encode(close.mock.calls[0][1] || '').byteLength).toBeLessThanOrEqual(123);
    expect(established.sockets.sockets).toHaveLength(1);
  });

  test('a stop placeholder accepts its delayed matching registration without reviving playback', async () => {
    const { socket, native } = await establish();
    socket.message(serverControl({
      protocol: 'call.v1', type: 'playback.stop', seq: 5, call_id: CALL_ID, response_id: 'response-1', stream_id: 9,
      retire_server_seq: { from: 3, through: 4 }, reason: 'user_interrupted',
    }));
    socket.message(serverControl({
      protocol: 'call.v1', type: 'audio.stream_started', seq: 3, call_id: CALL_ID, audio_route: 'CALL',
      stream_id: 9, response_id: 'response-1', encoding: 'pcm_s16le', sample_rate: 24000, channels: 1,
    }));
    socket.message(new BinaryAudioFrameCodec().encode({ version: 1, route: 2, flags: 1, streamId: 9, seq: 4, payload: new Uint8Array([1, 0]) }));
    await flush();
    expect(native.enqueued).toHaveLength(0);
    socket.message(serverControl({
      protocol: 'call.v1', type: 'audio.stream_started', seq: 6, call_id: CALL_ID, audio_route: 'CALL',
      stream_id: 9, response_id: 'wrong-response', encoding: 'pcm_s16le', sample_rate: 24000, channels: 1,
    }));
    await flush();
    expect(socket.readyState).toBe(3);
  });

  test('a stop placeholder rejects mismatched identity and later stream-id reuse', async () => {
    const wrongIdentity = await establish();
    wrongIdentity.socket.message(serverControl({
      protocol: 'call.v1', type: 'playback.stop', seq: 5, call_id: CALL_ID, response_id: 'response-1', stream_id: 9,
      retire_server_seq: { from: 3, through: 4 }, reason: 'user_interrupted',
    }));
    wrongIdentity.socket.message(serverControl({
      protocol: 'call.v1', type: 'audio.stream_started', seq: 3, call_id: CALL_ID, audio_route: 'CALL',
      stream_id: 9, response_id: 'wrong', encoding: 'pcm_s16le', sample_rate: 24000, channels: 1,
    }));
    await flush();
    expect(wrongIdentity.session.state.status).toBe('failed');

    const reused = await establish();
    reused.socket.message(serverControl({
      protocol: 'call.v1', type: 'playback.stop', seq: 5, call_id: CALL_ID, response_id: 'response-1', stream_id: 9,
      retire_server_seq: { from: 3, through: 4 }, reason: 'user_interrupted',
    }));
    reused.socket.message(serverControl({
      protocol: 'call.v1', type: 'audio.stream_started', seq: 3, call_id: CALL_ID, audio_route: 'CALL',
      stream_id: 9, response_id: 'response-1', encoding: 'pcm_s16le', sample_rate: 24000, channels: 1,
    }));
    reused.socket.message(new BinaryAudioFrameCodec().encode({
      version: 1, route: 2, flags: 1, streamId: 9, seq: 4, payload: new Uint8Array([1, 0]),
    }));
    await flush();
    reused.socket.message(serverControl({
      protocol: 'call.v1', type: 'audio.stream_started', seq: 6, call_id: CALL_ID, audio_route: 'CALL',
      stream_id: 9, response_id: 'response-1', encoding: 'pcm_s16le', sample_rate: 24000, channels: 1,
    }));
    await flush();
    expect(reused.session.state.status).toBe('failed');
  });

  test('stop bypasses a blocked enqueue and stopped is sent only after native stop resolves', async () => {
    const { socket, native, sockets, session } = await establish();
    let releaseEnqueue!: () => void;
    let releaseStop!: () => void;
    native.enqueue = async () => new Promise<void>((resolve) => { releaseEnqueue = resolve; });
    native.stop = async () => new Promise<void>((resolve) => { releaseStop = resolve; });
    socket.message(serverControl({
      protocol: 'call.v1', type: 'audio.stream_started', seq: 3, call_id: CALL_ID, audio_route: 'CALL',
      stream_id: 9, response_id: 'response-1', encoding: 'pcm_s16le', sample_rate: 24000, channels: 1,
    }));
    await flush();
    socket.message(new BinaryAudioFrameCodec().encode({ version: 1, route: 2, flags: 0, streamId: 9, seq: 4, payload: new Uint8Array([1, 0]) }));
    await flush();
    socket.message(serverControl({
      protocol: 'call.v1', type: 'playback.stop', seq: 5, call_id: CALL_ID, response_id: 'response-1', stream_id: 9,
      retire_server_seq: { from: 3, through: 4 }, reason: 'user_interrupted',
    }));
    await flush();
    expect(socket.sent.filter((wire) => typeof wire === 'string').map((wire) => JSON.parse(wire as string).type)).not.toContain('playback.stopped');
    releaseStop();
    await flush();
    expect(socket.sent.filter((wire) => typeof wire === 'string').map((wire) => JSON.parse(wire as string).type)).toContain('playback.stopped');
    releaseEnqueue();
    await flush();
    socket.message(serverControl({
      protocol: 'call.v1', type: 'audio.stream_started', seq: 6, call_id: CALL_ID, audio_route: 'CALL',
      stream_id: 10, response_id: 'response-2', encoding: 'pcm_s16le', sample_rate: 24000, channels: 1,
    }));
    await flush();
    expect(JSON.parse(socket.sent.filter((wire): wire is string => typeof wire === 'string').at(-1)!)).toMatchObject({ type: 'ack', ack_seq: 6 });
    socket.emit('close', { code: 1006 });
    const recovery = sockets.sockets[1];
    recovery.message(JSON.stringify({ type: 'system_ready', payload: {} }));
    recovery.message(JSON.stringify({ type: 'auth_ok', payload: {} }));
    await flush();
    expect(JSON.parse(recovery.sent.at(-1) as string)).toMatchObject({ type: 'call.resume', last_contiguous_server_seq: 6 });
    session.close();
  });

  test('stop acts across an unrelated gap without ACK regression, then commits through the stop', async () => {
    const { socket, native } = await establish();
    socket.message(serverControl({
      protocol: 'call.v1', type: 'audio.stream_started', seq: 4, call_id: CALL_ID, audio_route: 'CALL',
      stream_id: 9, response_id: 'response-1', encoding: 'pcm_s16le', sample_rate: 24000, channels: 1,
    }));
    socket.message(serverControl({
      protocol: 'call.v1', type: 'playback.stop', seq: 6, call_id: CALL_ID, response_id: 'response-1', stream_id: 9,
      retire_server_seq: { from: 4, through: 5 }, reason: 'user_interrupted',
    }));
    await flush();
    const beforeGap = socket.sent.filter((wire): wire is string => typeof wire === 'string').map((wire) => JSON.parse(wire));
    expect(beforeGap.some((message) => message.type === 'playback.stopped' && message.stop_seq === 6)).toBe(true);
    expect(beforeGap.some((message) => message.type === 'nack' && message.missing_seq === 3)).toBe(true);
    expect(beforeGap.filter((message) => message.type === 'ack').at(-1).ack_seq).toBe(2);
    socket.message(serverControl({
      protocol: 'call.v1', type: 'audio.stream_started', seq: 3, call_id: CALL_ID, audio_route: 'CALL',
      stream_id: 8, response_id: 'response-0', encoding: 'pcm_s16le', sample_rate: 24000, channels: 1,
    }));
    await flush();
    const acks = socket.sent.filter((wire): wire is string => typeof wire === 'string').map((wire) => JSON.parse(wire))
      .filter((message) => message.type === 'ack').map((message) => message.ack_seq);
    expect(acks.at(-1)).toBe(6);
    expect(acks.every((value, index) => index === 0 || value > acks[index - 1])).toBe(true);
    expect(native.stopPlaybackCount).toBeGreaterThan(0);
  });

  test('deduplicates native completion and replays the original bytes after ACK loss', async () => {
    const { socket, native } = await establish();
    socket.message(serverControl({
      protocol: 'call.v1', type: 'audio.stream_started', seq: 3, call_id: CALL_ID, audio_route: 'CALL',
      stream_id: 9, response_id: 'response-1', encoding: 'pcm_s16le', sample_rate: 24000, channels: 1,
    }));
    socket.message(new BinaryAudioFrameCodec().encode({ version: 1, route: 2, flags: 1, streamId: 9, seq: 4, payload: new Uint8Array([1, 0]) }));
    await flush();
    const receipt = { stream: { callId: CALL_ID, responseId: 'response-1', streamId: 9 } };
    native.listener?.(receipt); native.listener?.(receipt);
    const completed = socket.sent.filter((wire): wire is string => typeof wire === 'string').filter((wire) => JSON.parse(wire).type === 'playback.completed');
    expect(completed).toHaveLength(1);
    socket.message(serverControl({ protocol: 'call.v1', type: 'nack', call_id: CALL_ID, missing_seq: 2 }));
    await flush();
    expect(socket.sent.at(-1)).toBe(completed[0]);
  });

  test('recovers once within the original three-second deadline and fences the old socket', async () => {
    const { sockets, socket, clock, session } = await establish();
    clock.advance(1_000);
    socket.emit('close', { code: 1006 });
    const recovery = sockets.sockets[1];
    recovery.message(JSON.stringify({ type: 'system_ready', payload: {} }));
    recovery.message(JSON.stringify({ type: 'auth_ok', payload: {} }));
    await flush();
    expect(JSON.parse(recovery.sent.at(-1) as string)).toMatchObject({ type: 'call.resume', call_id: CALL_ID, last_contiguous_server_seq: 2 });
    recovery.message(serverControl({
      protocol: 'call.v1', type: 'call.resumed', call_id: CALL_ID, character_id: 'luotianyi',
      last_contiguous_client_seq: 1, last_contiguous_server_seq: 2,
    }));
    await flush();
    expect(session.state.status).toBe('connected');
    clock.advance(500);
    expect(session.state.activeDurationMs).toBe(1_500);
    socket.message(serverControl({ protocol: 'call.v1', type: 'call.ended', seq: 3, call_id: CALL_ID, outcome: 'connected', end_reason: 'system_failure', active_duration_ms: 1 }));
    await flush();
    expect(session.state.status).toBe('connected');
  });

  test('does not extend recovery and freezes duration at the first disconnect on timeout', async () => {
    const { socket, clock, session } = await establish();
    clock.advance(1_000);
    socket.emit('close', { code: 1006 });
    clock.advance(3_000);
    expect(session.state).toMatchObject({ status: 'failed', errorCode: 'RECOVERY_TIMEOUT', activeDurationMs: 1_000 });
  });

  test('rejects a resumed handshake at the exact deadline and an echoed cursor conflict', async () => {
    const late = await establish();
    late.socket.emit('close', { code: 1006 });
    late.clock.now += 3_000;
    const recovery = late.sockets.sockets[1];
    recovery.message(JSON.stringify({ type: 'system_ready', payload: {} }));
    recovery.message(JSON.stringify({ type: 'auth_ok', payload: {} }));
    await flush();
    expect(late.session.state.errorCode).toBe('RECOVERY_TIMEOUT');

    const conflict = await establish();
    conflict.socket.emit('close', { code: 1006 });
    const second = conflict.sockets.sockets[1];
    second.message(JSON.stringify({ type: 'system_ready', payload: {} }));
    second.message(JSON.stringify({ type: 'auth_ok', payload: {} }));
    await flush();
    second.message(serverControl({ protocol: 'call.v1', type: 'call.resumed', call_id: CALL_ID, character_id: 'luotianyi', last_contiguous_client_seq: 1, last_contiguous_server_seq: 1 }));
    await flush();
    expect(conflict.session.state.errorCode).toBe('RESUME_SERVER_CURSOR_MISMATCH');
  });

  test('platform adapter requests ArrayBuffer and normalizes ArrayBuffer and Blob', async () => {
    const platform = new FakeSocket() as FakeSocket & { binaryType: string };
    platform.binaryType = '';
    const socket = createPlatformCallSocketFactory(() => platform as never).create('ws://example');
    const received: CallSocketData[] = [];
    socket.addEventListener('message', (event) => received.push(event.data));
    expect(platform.binaryType).toBe('arraybuffer');
    platform.message(new Uint8Array([1, 2]).buffer as never);
    platform.message(new Blob([new Uint8Array([3, 4])]) as never);
    await flush();
    const normalized = await Promise.all(received.map(async (value) => {
      const bytes = typeof value === 'object' && 'resolve' in value ? await value.resolve() : value as Uint8Array;
      return [...bytes];
    }));
    expect(normalized).toEqual([[1, 2], [3, 4]]);
  });

  test('a delayed Blob from an old socket epoch cannot enter the resumed session', async () => {
    const established = await establish();
    let resolveBlob!: (value: ArrayBuffer) => void;
    const delayed = { resolve: () => new Promise<Uint8Array>((resolve) => {
      resolveBlob = (value) => resolve(new Uint8Array(value));
    }) };
    established.socket.message(delayed);
    established.socket.emit('close', { code: 1006 });
    const encoded = new BinaryAudioFrameCodec().encode({ version: 1, route: 2, flags: 0, streamId: 9, seq: 3, payload: new Uint8Array([1, 0]) });
    resolveBlob(encoded.buffer.slice(encoded.byteOffset, encoded.byteOffset + encoded.byteLength) as ArrayBuffer);
    await flush();
    expect(established.session.state.status).toBe('recovering');
    expect(established.native.enqueued).toHaveLength(0);
  });

  test('control outbox exhaustion fails closed, cleans audio, and close unsubscribes native events', async () => {
    const sockets = new FakeSockets();
    const native = fakeNative();
    const session = new CallTransportSession({
      url: 'ws://example/call_ws', credentials: { username: 'u', token: 't' }, characterId: 'luotianyi',
      sockets, nativeAudio: native, clock: new FakeClock(), serverAvailable: true, nativeAvailable: true,
      controlOutboxEntries: 1,
    });
    await session.start({ clientRequestId: 'request-1', characterId: 'luotianyi' });
    const socket = sockets.sockets[0];
    socket.message(JSON.stringify({ type: 'system_ready', payload: {} }));
    socket.message(JSON.stringify({ type: 'auth_ok', payload: {} }));
    await flush();
    socket.message(serverControl({ protocol: 'call.v1', type: 'call.state', seq: 1, call_id: CALL_ID, client_request_id: 'request-1', state: 'preparing' }));
    socket.message(serverControl({ protocol: 'call.v1', type: 'call.active', seq: 2, call_id: CALL_ID, connected_at_ms: 10 }));
    await flush();
    socket.message(serverControl({
      protocol: 'call.v1', type: 'audio.stream_started', seq: 3, call_id: CALL_ID, audio_route: 'CALL',
      stream_id: 9, response_id: 'response-1', encoding: 'pcm_s16le', sample_rate: 24000, channels: 1,
    }));
    await flush();
    socket.message(new BinaryAudioFrameCodec().encode({ version: 1, route: 2, flags: 1, streamId: 9, seq: 4, payload: new Uint8Array([1, 0]) }));
    await flush();
    native.listener?.({ stream: { callId: CALL_ID, responseId: 'response-1', streamId: 9 } });
    await flush();
    expect(session.state).toMatchObject({ status: 'failed', errorCode: 'CONTROL_OUTBOX_FULL' });
    expect(native.stopCaptureCount).toBeGreaterThan(0);
    expect(native.stopPlaybackCount).toBeGreaterThan(0);
    session.close();
    expect(native.unsubscribeCount).toBe(1);
  });

  test('call.ended closes socket and unsubscribes consumption exactly once', async () => {
    const established = await establish();
    established.socket.message(serverControl({
      protocol: 'call.v1', type: 'call.ended', seq: 3, call_id: CALL_ID,
      outcome: 'connected', end_reason: 'agent_hangup', active_duration_ms: 123,
    }));
    await flush();
    expect(established.session.state).toMatchObject({ status: 'closed', activeDurationMs: 123 });
    expect(established.socket.closeCount).toBe(1);
    expect(established.native.unsubscribeCount).toBe(1);
    established.session.close();
    expect(established.socket.closeCount).toBe(1);
    expect(established.native.unsubscribeCount).toBe(1);
  });

  test('throwing error listeners cannot interrupt terminal cleanup', async () => {
    const established = await establish();
    established.session.subscribe(() => { throw new Error('snapshot observer failed'); });
    established.session.onError(() => { throw new Error('observer failed'); });
    established.socket.message('{bad json');
    await flush();
    expect(established.session.state.status).toBe('failed');
    expect(established.socket.closeCount).toBe(1);
    expect(established.native.unsubscribeCount).toBe(1);
    expect(established.native.stopCaptureCount).toBeGreaterThan(0);
  });

  test('close tombstones an in-flight enqueue and its late resolution cannot ACK or revive playback', async () => {
    const established = await establish();
    let release!: () => void;
    established.native.enqueue = async () => new Promise<void>((resolve) => { release = resolve; });
    established.socket.message(serverControl({
      protocol: 'call.v1', type: 'audio.stream_started', seq: 3, call_id: CALL_ID, audio_route: 'CALL',
      stream_id: 9, response_id: 'response-1', encoding: 'pcm_s16le', sample_rate: 24000, channels: 1,
    }));
    await flush();
    established.socket.message(new BinaryAudioFrameCodec().encode({
      version: 1, route: 2, flags: 1, streamId: 9, seq: 4, payload: new Uint8Array([1, 0]),
    }));
    await flush();
    const ackBeforeClose = established.socket.sent.filter((wire): wire is string => typeof wire === 'string')
      .map((wire) => JSON.parse(wire)).filter((message) => message.type === 'ack').at(-1).ack_seq;
    established.session.close();
    release();
    await flush();
    const ackAfterClose = established.socket.sent.filter((wire): wire is string => typeof wire === 'string')
      .map((wire) => JSON.parse(wire)).filter((message) => message.type === 'ack').at(-1).ack_seq;
    expect(ackBeforeClose).toBe(3);
    expect(ackAfterClose).toBe(3);
    expect(established.session.state.status).toBe('closed');
  });

  test('CallSession enforces prepared identity and explicit direct mode', async () => {
    const transport = { start: jest.fn(), state: { status: 'idle', activeDurationMs: 0 }, hangup: jest.fn(), subscribe: jest.fn(), onError: jest.fn(), close: jest.fn() };
    const switchPort = { prepare: jest.fn().mockResolvedValue(undefined) };
    const session = new CallSession(transport as never, switchPort, 'luotianyi');
    await session.prepare('A');
    await expect(session.start('B', 'prepared_switch')).rejects.toThrow('CALL_PREPARE_IDENTITY_MISMATCH');
    const direct = new CallSession(transport as never, switchPort, 'luotianyi');
    await direct.start('D', 'direct_no_chat');
    expect(transport.start).toHaveBeenCalledWith({ clientRequestId: 'D', characterId: 'luotianyi' });
  });

  test('fails closed for unavailable capabilities', async () => {
    const session = new CallTransportSession({
      url: 'ws://example/call_ws', credentials: { username: 'u', token: 't' }, characterId: 'luotianyi',
      sockets: new FakeSockets(), nativeAudio: fakeNative(), clock: new FakeClock(), serverAvailable: true, nativeAvailable: false,
    });
    await expect(session.start({ clientRequestId: 'r', characterId: 'luotianyi' })).rejects.toThrow('NATIVE_CALL_UNAVAILABLE');
  });
});

import type {
  Ack,
  AudioStreamStarted,
  CallEnded,
  CallProtocolError,
  CallResumed,
  CallStateMessage,
  ControlMessage,
  Nack,
  PlaybackCompleted,
  PlaybackStop,
  PlaybackStopped,
} from '../call_protocol/control_types';
import { BinaryAudioFrameCodec } from '../call_protocol/audio_codec';
import { decodeControlText, encodeControlMessage } from '../call_protocol/control';
import type {
  CallClock,
  CallCredentials,
  CallNativeAudioPort,
  CallSocket,
  CallSocketData,
  CallSocketFactory,
  CallTransportErrorListener,
  CallTransportListener,
  CallTransportSnapshot,
  StartCallRequest,
} from '../../types/call_transport';
import type { CallAudioStreamIdentity, PlaybackConsumptionReceipt } from '../call_audio_contracts';
import { IncomingCallSequence, type IncomingFrame } from './incoming_sequence';
import { ReliableCallOutbox } from './reliable_outbox';

const CALL_ROUTE = 2;
const FINAL_FLAG = 1;
const RECOVERY_WINDOW_MS = 3_000;
const NATIVE_SETTLE_TIMEOUT_MS = 3_000;
const CONTROL_RETRY_MS = 1_000;
const AUDIO_FOCUS_LOST_CLOSE_CODE = 4000;
const CALL_FAILURE_CLOSE_CODE = 4001;
const CALL_FAILURE_CLOSE_REASON = 'call transport failed';
const INPUT_AUDIO_FORMAT = { encoding: 'pcm_s16le', sampleRateHz: 16_000, channels: 1 } as const;

interface StreamState {
  identity: CallAudioStreamIdentity;
  registered: boolean;
  format?: { encoding: string; sampleRateHz: number; channels: number };
  generation: number;
  finalAccepted: boolean;
  stopped: boolean;
}

export interface CallTransportOptions {
  url: string;
  credentials: CallCredentials;
  characterId: string;
  sockets: CallSocketFactory;
  nativeAudio: CallNativeAudioPort;
  clock: CallClock;
  serverAvailable: boolean;
  nativeAvailable: boolean;
  controlOutboxEntries?: number;
}

/** Headless call.v1 session. UI receives snapshots and never owns the socket. */
export class CallTransportSession {
  private socket: CallSocket | null = null;
  private socketEpoch = 0;
  private readonly codec = new BinaryAudioFrameCodec();
  private readonly incoming = new IncomingCallSequence();
  private readonly outbox: ReliableCallOutbox;
  private readonly listeners = new Set<CallTransportListener>();
  private readonly errorListeners = new Set<CallTransportErrorListener>();
  private readonly streams = new Map<number, StreamState>();
  private readonly stopping = new Map<number, Promise<void>>();
  private snapshot: CallTransportSnapshot = { status: 'idle', activeDurationMs: 0 };
  private startRequest: StartCallRequest | null = null;
  private recoveryTimer: unknown | null = null;
  private controlRetryTimer: unknown | null = null;
  private capturePause: Promise<void> | null = null;
  private firstDisconnectAt: number | null = null;
  private capturePaused = false;
  private playbackGeneration = 0;
  private closed = false;
  private nativeAccepting = false;
  private inflightNativeAccept: Promise<void> | null = null;
  private requestedResumeServerCursor: number | null = null;
  private lastAckSent = 0;
  private readonly completedStreams = new Set<string>();
  private readonly unsubscribeConsumption: () => void;
  private terminalPromise: Promise<void> | null = null;
  private pendingEnded: CallEnded | null = null;

  constructor(private readonly options: CallTransportOptions) {
    this.outbox = new ReliableCallOutbox(96_000, options.controlOutboxEntries ?? 64);
    this.unsubscribeConsumption = options.nativeAudio.subscribeConsumption((receipt) => this.onPlaybackConsumed(receipt));
  }

  get state(): Readonly<CallTransportSnapshot> {
    return this.currentSnapshot();
  }

  subscribe(listener: CallTransportListener): () => void {
    this.listeners.add(listener);
    try { listener(this.currentSnapshot()); } catch { /* observer failures are isolated */ }
    return () => this.listeners.delete(listener);
  }

  onError(listener: CallTransportErrorListener): () => void {
    this.errorListeners.add(listener);
    return () => this.errorListeners.delete(listener);
  }

  async start(request: StartCallRequest): Promise<void> {
    this.requireUsable();
    if (!this.options.serverAvailable) throw new Error('SERVER_CALL_UNAVAILABLE');
    if (!this.options.nativeAvailable) throw new Error('NATIVE_CALL_UNAVAILABLE');
    if (await this.options.nativeAudio.getCapability() !== 'available') throw new Error('NATIVE_CALL_UNAVAILABLE');
    if (this.snapshot.status !== 'idle') throw new Error('CALL_ALREADY_STARTED');
    this.startRequest = request;
    this.update({ status: 'connecting', clientRequestId: request.clientRequestId });
    this.openSocket(false);
  }

  async hangup(reason: 'user_hangup' | 'backgrounded' = 'user_hangup'): Promise<void> {
    if (!this.snapshot.callId || this.isTerminal()) return;
    this.update({ status: 'ending' });
    try {
      this.sendSequencedControl((seq) => ({
        protocol: 'call.v1', type: 'call.hangup', seq, call_id: this.snapshot.callId!, reason,
      }));
    } catch (error) {
      this.fail(errorCode(error));
    } finally {
      await this.stopAudio();
    }
  }

  close(): void {
    void this.terminate('closed', undefined, this.snapshot.activeDurationMs);
  }

  forceRecovery(_reason: 'AUDIO_FOCUS_LOST'): void {
    if (this.snapshot.status !== 'connected' || !this.snapshot.callId) {
      this.fail('AUDIO_FOCUS_LOST');
      return;
    }
    const epoch = this.socketEpoch;
    void this.pauseCapture();
    try {
      this.socket?.close(AUDIO_FOCUS_LOST_CLOSE_CODE, 'audio focus lost');
    } catch {
      this.fail('AUDIO_FOCUS_CLOSE_FAILED');
      return;
    }
    this.handleDisconnect(epoch);
  }

  private openSocket(resume: boolean): void {
    const epoch = ++this.socketEpoch;
    const socket = this.options.sockets.create(this.options.url);
    this.socket = socket;
    const current = () => !this.closed && this.socket === socket && this.socketEpoch === epoch;
    socket.addEventListener('open', () => {
      if (current()) this.update({ status: 'authenticating' });
    });
    socket.addEventListener('message', (event) => {
      if (!current()) return;
      void this.handleSocketData(event.data, resume, epoch).catch((error) => this.fail(errorCode(error)));
    });
    socket.addEventListener('error', () => {
      if (current()) this.handleDisconnect(epoch);
    });
    socket.addEventListener('close', () => {
      if (current()) this.handleDisconnect(epoch);
    });
  }

  private async handleSocketData(data: CallSocketData, resume: boolean, epoch: number): Promise<void> {
    if (typeof data === 'string') {
      if (this.handleAuthEnvelope(data, resume)) return;
      const message = decodeControlText(data, { transport: 'call_ws', direction: 'server_to_client' });
      await this.handleControl(message, data, epoch);
      return;
    }
    const raw = data instanceof Uint8Array ? data : await data.resolve();
    if (epoch !== this.socketEpoch) return;
    const frame = this.codec.decode(raw);
    if (frame.route !== CALL_ROUTE || frame.streamId === 0) throw new Error('INVALID_SERVER_AUDIO_ROUTE');
    await this.acceptIncoming({
      seq: frame.seq,
      raw,
      audio: {
        streamId: frame.streamId,
        final: (frame.flags & FINAL_FLAG) !== 0,
        payload: frame.payload,
      },
    }, epoch);
  }

  private handleAuthEnvelope(raw: string, resume: boolean): boolean {
    let envelope: { type?: unknown; payload?: unknown };
    try {
      envelope = JSON.parse(raw) as { type?: unknown; payload?: unknown };
    } catch {
      return false;
    }
    if (envelope.type === 'system_ready') {
      this.sendRaw(JSON.stringify({
        type: 'user_auth',
        client_msg_id: `call-auth-${this.options.clock.wallClockMs()}`,
        ts: this.options.clock.wallClockMs(),
        payload: { username: this.options.credentials.username, token: this.options.credentials.token },
      }));
      return true;
    }
    if (envelope.type === 'auth_error') throw new Error('AUTH_REJECTED');
    if (envelope.type !== 'auth_ok') return false;
    if (resume) {
      if (!this.snapshot.callId) throw new Error('MISSING_CALL_ID');
      this.requireRecoveryBeforeDeadline();
      this.requestedResumeServerCursor = this.incoming.lastContiguousSeq;
      this.sendRaw(encodeControlMessage({
        protocol: 'call.v1',
        type: 'call.resume',
        call_id: this.snapshot.callId,
        character_id: this.options.characterId,
        last_contiguous_server_seq: this.requestedResumeServerCursor,
      }, { transport: 'call_ws', direction: 'client_to_server' }));
    } else {
      if (!this.startRequest) throw new Error('MISSING_START_REQUEST');
      this.update({ status: 'starting' });
      this.sendSequencedControl((seq) => ({
        protocol: 'call.v1',
        type: 'call.start',
        seq,
        client_request_id: this.startRequest!.clientRequestId,
        character_id: this.startRequest!.characterId,
        audio: { encoding: 'pcm_s16le', sample_rate: 16000, channels: 1 },
      }));
    }
    return true;
  }

  private async handleControl(message: ControlMessage, raw: string, epoch: number): Promise<void> {
    if (message.type === 'ack') {
      this.validateCallIdentity(message);
      this.outbox.acknowledge(message.ack_seq);
      this.scheduleControlRetry();
      await this.maybeResumeCapture();
      return;
    }
    if (message.type === 'nack') {
      this.validateCallIdentity(message);
      this.sendRaw(this.outbox.replayMissing(message.missing_seq).wire);
      return;
    }
    if (message.type === 'call.resumed') {
      await this.handleResumed(message, epoch);
      return;
    }
    if (message.type === 'error') {
      this.handleProtocolError(message);
      return;
    }
    if (!('seq' in message)) throw new Error('UNEXPECTED_CONTROL');
    await this.acceptIncoming({ seq: message.seq, raw: utf8Bytes(raw), control: message }, epoch);
  }

  private async acceptIncoming(frame: IncomingFrame, epoch: number): Promise<void> {
    const actions = this.incoming.receive(frame);
    if (actions.ignoredRetiredDuplicate && frame.control?.type === 'audio.stream_started') {
      this.registerStream(frame.control);
    }
    if (actions.immediateStop) {
      const stopping = this.applyStop(actions.immediateStop);
      this.stopping.set(actions.immediateStop.seq, stopping);
      await stopping;
    }
    if (actions.missingSeq !== undefined && this.snapshot.callId) this.sendFeedback('nack', actions.missingSeq);
    if (actions.ackSeq > 0 && this.snapshot.callId) this.sendFeedback('ack', actions.ackSeq);
    this.startNativeAcceptance(epoch);
  }

  private startNativeAcceptance(epoch: number): void {
    if (this.nativeAccepting) return;
    const frame = this.incoming.claimReady();
    if (!frame) return;
    this.nativeAccepting = true;
    const operation = this.commitIncoming(frame, epoch).then(() => {
      if (this.closed) return;
      if (this.incoming.isRetired(frame.seq)) throw new Error('FRAME_RETIRED');
      const ack = this.incoming.commitClaimed(frame.seq);
      this.sendFeedback('ack', ack);
      this.nativeAccepting = false;
      if (this.pendingEnded) {
        const ended = this.pendingEnded;
        this.pendingEnded = null;
        void this.terminate('closed', undefined, ended.active_duration_ms);
        return;
      }
      this.startNativeAcceptance(this.socketEpoch);
    }).catch((error) => {
      this.nativeAccepting = false;
      if (errorCode(error) !== 'FRAME_RETIRED') this.fail(errorCode(error));
      else if (!this.closed) this.startNativeAcceptance(this.socketEpoch);
    });
    const tracked = operation.finally(() => {
      if (this.inflightNativeAccept === tracked) this.inflightNativeAccept = null;
    });
    this.inflightNativeAccept = tracked;
  }

  private async commitIncoming(frame: IncomingFrame, epoch: number): Promise<void> {
    if (epoch !== this.socketEpoch) throw new Error('STALE_SOCKET_EPOCH');
    if (frame.audio) {
      const stream = this.streams.get(frame.audio.streamId);
      if (!stream || !stream.registered || stream.stopped) throw new Error('UNREGISTERED_STREAM');
      frame.audio.responseId = stream.identity.responseId;
      const generation = stream.generation;
      await this.options.nativeAudio.enqueue({
        stream: stream.identity,
        format: { encoding: 'pcm_s16le', sampleRateHz: 24_000, channels: 1 },
        payload: frame.audio.payload,
        isFinal: frame.audio.final,
      });
      if (stream.stopped || stream.generation !== generation) throw new Error('FRAME_RETIRED');
      if (frame.audio.final) stream.finalAccepted = true;
      return;
    }
    if (!frame.control) throw new Error('INVALID_INCOMING_FRAME');
    await this.commitControl(frame.control);
  }

  private async commitControl(message: ControlMessage): Promise<void> {
    switch (message.type) {
      case 'call.state':
        this.acceptState(message);
        return;
      case 'call.active':
        this.validateCallIdentity(message);
        this.update({ status: 'connected', connectedAtMonotonicMs: this.options.clock.monotonicMs() });
        await this.options.nativeAudio.startCapture(INPUT_AUDIO_FORMAT, (frame) => this.onCapturedAudio(frame.payload));
        return;
      case 'audio.stream_started':
        this.registerStream(message);
        return;
      case 'playback.stop':
        await this.stopping.get(message.seq);
        this.stopping.delete(message.seq);
        return;
      case 'call.ended':
        this.acceptEnded(message);
        return;
      default:
        throw new Error('UNEXPECTED_CONTROL');
    }
  }

  private acceptState(message: CallStateMessage): void {
    if (this.startRequest && message.client_request_id !== this.startRequest.clientRequestId) {
      throw new Error('CLIENT_REQUEST_MISMATCH');
    }
    if (this.snapshot.callId && this.snapshot.callId !== message.call_id) throw new Error('CALL_ID_MISMATCH');
    this.update({ callId: message.call_id, status: 'starting' });
  }

  private registerStream(message: AudioStreamStarted): void {
    this.validateCallIdentity(message);
    const existing = this.streams.get(message.stream_id);
    const format = { encoding: message.encoding, sampleRateHz: message.sample_rate, channels: message.channels };
    if (existing) {
      const sameIdentity = existing.identity.callId === message.call_id && existing.identity.responseId === message.response_id;
      const sameFormat = !existing.format || (
        existing.format.encoding === format.encoding && existing.format.sampleRateHz === format.sampleRateHz &&
        existing.format.channels === format.channels
      );
      if (!sameIdentity || !sameFormat || existing.registered) throw new Error('STREAM_ID_CONFLICT');
      existing.registered = true;
      existing.format = format;
      return;
    }
    this.streams.set(message.stream_id, {
      identity: { callId: message.call_id, responseId: message.response_id, streamId: message.stream_id },
      registered: true,
      format,
      generation: this.playbackGeneration,
      finalAccepted: false,
      stopped: false,
    });
  }

  private async applyStop(message: PlaybackStop): Promise<void> {
    this.validateCallIdentity(message);
    let stream = this.streams.get(message.stream_id);
    if (!stream) {
      const pendingRegistration = this.incoming.pendingStreamRegistration(message.stream_id);
      if (
        pendingRegistration?.type === 'audio.stream_started' &&
        pendingRegistration.response_id !== message.response_id
      ) throw new Error('STOP_STREAM_MISMATCH');
      stream = {
        identity: { callId: message.call_id, responseId: message.response_id, streamId: message.stream_id },
        registered: false,
        format: pendingRegistration?.type === 'audio.stream_started' ? {
          encoding: pendingRegistration.encoding,
          sampleRateHz: pendingRegistration.sample_rate,
          channels: pendingRegistration.channels,
        } : undefined,
        generation: this.playbackGeneration,
        finalAccepted: false,
        stopped: false,
      };
      this.streams.set(message.stream_id, stream);
    }
    if (stream.identity.responseId !== message.response_id) throw new Error('STOP_STREAM_MISMATCH');
    stream.stopped = true;
    stream.generation += 1;
    await this.options.nativeAudio.tombstone(stream.identity);
    await this.options.nativeAudio.stop(stream.identity);
    if (this.closed) return;
    this.sendSequencedControl((seq): PlaybackStopped => ({
      protocol: 'call.v1', type: 'playback.stopped', seq, call_id: message.call_id,
      response_id: message.response_id, stop_seq: message.seq,
    }));
  }

  private onPlaybackConsumed(receipt: PlaybackConsumptionReceipt): void {
    const stream = this.streams.get(receipt.stream.streamId);
    if (!stream || stream.stopped || !stream.finalAccepted) return;
    if (stream.identity.callId !== receipt.stream.callId || stream.identity.responseId !== receipt.stream.responseId) return;
    const key = `${stream.identity.responseId}:${stream.identity.streamId}`;
    if (this.completedStreams.has(key)) return;
    try {
      this.sendSequencedControl((seq): PlaybackCompleted => ({
        protocol: 'call.v1', type: 'playback.completed', seq, call_id: stream.identity.callId,
        response_id: stream.identity.responseId, stream_id: stream.identity.streamId,
      }));
      this.completedStreams.add(key);
    } catch (error) {
      this.fail(errorCode(error));
    }
  }

  private onCapturedAudio(payload: Uint8Array): void {
    if ((this.snapshot.status !== 'connected' && this.firstDisconnectAt === null) || this.closed || this.capturePaused || payload.byteLength === 0) return;
    try {
      const entry = this.outbox.add('audio', (seq) => this.codec.encode({
        version: 1, route: CALL_ROUTE, flags: 0, streamId: 0, seq, payload,
      }), payload.byteLength);
      if (this.firstDisconnectAt === null) this.sendRaw(entry.wire);
      if (this.outbox.audioCapacityRemaining < 16_384) void this.pauseCapture();
    } catch (error) {
      if (errorCode(error) === 'AUDIO_OUTBOX_FULL') void this.pauseCapture();
      else this.fail(errorCode(error));
    }
  }

  private async pauseCapture(): Promise<void> {
    if (this.capturePaused) return;
    this.capturePaused = true;
    try {
      this.capturePause = this.options.nativeAudio.pauseCapture();
      await this.capturePause;
    } catch {
      this.fail('CAPTURE_BACKPRESSURE_FAILED');
    } finally {
      this.capturePause = null;
    }
  }

  private async maybeResumeCapture(): Promise<void> {
    if (!this.capturePaused || this.outbox.audioCapacityRemaining < 32_768 || this.snapshot.status !== 'connected') return;
    await this.capturePause;
    if (this.closed || this.firstDisconnectAt !== null) return;
    await this.options.nativeAudio.resumeCapture();
    this.capturePaused = false;
  }

  private async handleResumed(message: CallResumed, epoch: number): Promise<void> {
    this.requireRecoveryBeforeDeadline();
    this.validateCallIdentity(message);
    if (message.character_id !== this.options.characterId) throw new Error('CHARACTER_ID_MISMATCH');
    if (message.last_contiguous_server_seq !== this.requestedResumeServerCursor) {
      throw new Error('RESUME_SERVER_CURSOR_MISMATCH');
    }
    const replay = this.outbox.replayAfter(message.last_contiguous_client_seq);
    this.outbox.acknowledge(message.last_contiguous_client_seq);
    for (const entry of replay) {
      if (epoch !== this.socketEpoch) throw new Error('STALE_SOCKET_EPOCH');
      this.sendRaw(entry.wire);
    }
    this.firstDisconnectAt = null;
    this.requestedResumeServerCursor = null;
    this.clearRecoveryTimer();
    this.update({ status: 'connected', recoveryDeadlineMonotonicMs: undefined });
    this.sendFeedback('ack', this.incoming.lastContiguousSeq);
    this.scheduleControlRetry();
    this.startNativeAcceptance(epoch);
    await this.maybeResumeCapture();
  }

  private handleDisconnect(epoch: number): void {
    if (epoch !== this.socketEpoch || this.closed || this.isTerminal() || this.snapshot.status === 'ending') return;
    if (!this.snapshot.callId || this.snapshot.status !== 'connected') {
      this.fail('CALL_CONNECTION_LOST');
      return;
    }
    if (this.firstDisconnectAt !== null) return;
    const now = this.options.clock.monotonicMs();
    this.firstDisconnectAt = now;
    this.update({ status: 'recovering', recoveryDeadlineMonotonicMs: now + RECOVERY_WINDOW_MS });
    this.clearControlRetry();
    this.recoveryTimer = this.options.clock.setTimeout(() => this.fail('RECOVERY_TIMEOUT'), RECOVERY_WINDOW_MS);
    this.openSocket(true);
  }

  private acceptEnded(message: CallEnded): void {
    this.validateCallIdentity(message);
    this.pendingEnded = message;
  }

  private handleProtocolError(message: CallProtocolError): never {
    throw new Error(message.code || 'SERVER_PROTOCOL_ERROR');
  }

  private sendSequencedControl(factory: (seq: number) => ControlMessage): void {
    const entry = this.outbox.add('control', (seq) => encodeControlMessage(factory(seq), {
      transport: 'call_ws', direction: 'client_to_server',
    }));
    if (this.firstDisconnectAt === null) this.sendRaw(entry.wire);
    this.scheduleControlRetry();
  }

  private scheduleControlRetry(): void {
    this.clearControlRetry();
    if (this.closed || this.firstDisconnectAt !== null || this.outbox.pendingControls().length === 0) return;
    this.controlRetryTimer = this.options.clock.setTimeout(() => {
      this.controlRetryTimer = null;
      try {
        for (const entry of this.outbox.pendingControls()) this.sendRaw(entry.wire);
        this.scheduleControlRetry();
      } catch (error) { this.fail(errorCode(error)); }
    }, CONTROL_RETRY_MS);
  }

  private clearControlRetry(): void {
    if (this.controlRetryTimer === null) return;
    this.options.clock.clearTimeout(this.controlRetryTimer);
    this.controlRetryTimer = null;
  }

  private sendFeedback(type: 'ack' | 'nack', value: number): void {
    if (this.closed || this.firstDisconnectAt !== null) return;
    if (!this.snapshot.callId) throw new Error('MISSING_CALL_ID');
    if (type === 'ack') {
      if (value === 0 || value < this.lastAckSent) return;
      this.lastAckSent = value;
    }
    const message: Ack | Nack = type === 'ack'
      ? { protocol: 'call.v1', type, call_id: this.snapshot.callId, ack_seq: value }
      : { protocol: 'call.v1', type, call_id: this.snapshot.callId, missing_seq: value };
    this.sendRaw(encodeControlMessage(message, { transport: 'call_ws', direction: 'client_to_server' }));
  }

  private sendRaw(wire: string | Uint8Array): void {
    if (!this.socket || this.socket.readyState !== 1) throw new Error('SOCKET_NOT_OPEN');
    this.socket.send(wire);
  }

  private validateCallIdentity(message: { call_id: string }): void {
    if (!this.snapshot.callId || message.call_id !== this.snapshot.callId) throw new Error('CALL_ID_MISMATCH');
  }

  private async stopAudio(): Promise<void> {
    this.capturePaused = true;
    await Promise.allSettled([this.options.nativeAudio.stopCapture(), this.options.nativeAudio.stop()]);
  }

  private fail(code: string): void {
    if (this.isTerminal()) return;
    const now = this.options.clock.monotonicMs();
    const activeDurationMs = this.firstDisconnectAt === null
      ? this.activeDuration(now)
      : this.activeDuration(this.firstDisconnectAt);
    void this.terminate('failed', code, activeDurationMs);
  }

  private activeDuration(now: number): number {
    const started = this.snapshot.connectedAtMonotonicMs;
    if (started === undefined) return 0;
    return Math.max(0, now - started);
  }

  private currentSnapshot(): CallTransportSnapshot {
    if (this.snapshot.status === 'failed' || this.snapshot.status === 'closed' || this.snapshot.status === 'ending') {
      return { ...this.snapshot };
    }
    return { ...this.snapshot, activeDurationMs: this.activeDuration(this.options.clock.monotonicMs()) };
  }

  private update(patch: Partial<CallTransportSnapshot>): void {
    this.snapshot = { ...this.snapshot, ...patch };
    const current = this.currentSnapshot();
    for (const listener of this.listeners) {
      try { listener(current); } catch { /* observer failures are isolated */ }
    }
  }

  private clearRecoveryTimer(): void {
    if (this.recoveryTimer === null) return;
    this.options.clock.clearTimeout(this.recoveryTimer);
    this.recoveryTimer = null;
  }

  private requireRecoveryBeforeDeadline(): void {
    if (this.firstDisconnectAt === null) throw new Error('INVALID_RESUME_STATE');
    if (this.options.clock.monotonicMs() >= this.firstDisconnectAt + RECOVERY_WINDOW_MS) {
      throw new Error('RECOVERY_TIMEOUT');
    }
  }

  private isTerminal(): boolean {
    return this.snapshot.status === 'closed' || this.snapshot.status === 'failed';
  }

  private terminate(status: 'closed' | 'failed', code?: string, activeDurationMs = 0): Promise<void> {
    if (this.terminalPromise) return this.terminalPromise;
    this.closed = true;
    this.update({ status, errorCode: code, activeDurationMs });
    this.clearRecoveryTimer();
    this.clearControlRetry();
    this.socketEpoch += 1;
    for (const stream of this.streams.values()) {
      stream.stopped = true;
      stream.generation += 1;
    }
    const socket = this.socket;
    this.socket = null;
    try {
      socket?.close(code ? CALL_FAILURE_CLOSE_CODE : 1000, code ? CALL_FAILURE_CLOSE_REASON : 'call ended');
    } catch { /* terminal cleanup continues without opening another connection */ }
    try { this.unsubscribeConsumption(); } catch { /* terminal cleanup continues */ }
    if (code) {
      for (const listener of this.errorListeners) {
        try { listener(code); } catch { /* observer failures are isolated */ }
      }
    }
    this.terminalPromise = this.finishTerminalCleanup();
    return this.terminalPromise;
  }

  private async finishTerminalCleanup(): Promise<void> {
    const invalidation = [
      ...[...this.streams.values()].map((stream) => this.options.nativeAudio.tombstone(stream.identity)),
      this.options.nativeAudio.stopCapture(),
      this.options.nativeAudio.stop(),
    ];
    await this.settleBounded(invalidation);
    if (this.inflightNativeAccept) await this.settleBounded([this.inflightNativeAccept]);
    await this.settleBounded([
      ...[...this.streams.values()].map((stream) => this.options.nativeAudio.tombstone(stream.identity)),
      this.options.nativeAudio.stopCapture(),
      this.options.nativeAudio.stop(),
    ]);
    this.nativeAccepting = false;
    this.outbox.clear();
    this.incoming.clear();
    this.streams.clear();
    this.stopping.clear();
    this.completedStreams.clear();
    this.listeners.clear();
    this.errorListeners.clear();
  }

  private async settleBounded(operations: Promise<unknown>[]): Promise<void> {
    let timeout: unknown;
    await Promise.race([
      Promise.allSettled(operations),
      new Promise<void>((resolve) => {
        timeout = this.options.clock.setTimeout(resolve, NATIVE_SETTLE_TIMEOUT_MS);
      }),
    ]);
    if (timeout !== undefined) this.options.clock.clearTimeout(timeout);
  }

  private requireUsable(): void {
    if (this.closed) throw new Error('TRANSPORT_CLOSED');
  }
}

function utf8Bytes(value: string): Uint8Array {
  const bytes: number[] = [];
  for (const character of value) {
    const codePoint = character.codePointAt(0)!;
    if (codePoint <= 0x7f) bytes.push(codePoint);
    else if (codePoint <= 0x7ff) bytes.push(0xc0 | (codePoint >> 6), 0x80 | (codePoint & 0x3f));
    else if (codePoint <= 0xffff) {
      bytes.push(0xe0 | (codePoint >> 12), 0x80 | ((codePoint >> 6) & 0x3f), 0x80 | (codePoint & 0x3f));
    } else {
      bytes.push(
        0xf0 | (codePoint >> 18),
        0x80 | ((codePoint >> 12) & 0x3f),
        0x80 | ((codePoint >> 6) & 0x3f),
        0x80 | (codePoint & 0x3f),
      );
    }
  }
  return new Uint8Array(bytes);
}

function errorCode(error: unknown): string {
  return error instanceof Error && error.message ? error.message : 'CALL_TRANSPORT_FAILED';
}

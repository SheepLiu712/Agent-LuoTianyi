import { Buffer } from 'buffer';
import { requireOptionalNativeModule } from 'expo-modules-core';
import { Platform } from 'react-native';

import type { CallAudioNativeModule } from '../../modules/call-audio/src/CallAudioModule';
import type {
  NativeAudioFailure,
  NativeCapability,
  NativeLifecycleEvent,
  NativeRouteEvent,
} from '../../modules/call-audio/src/CallAudio.types';
import type {
  CallAudioCapturePort,
  CallAudioFormat,
  CallAudioPlaybackPort,
  CallAudioStreamIdentity,
  CallPlaybackChunk,
  CapturedAudioFrame,
  PlaybackConsumptionReceipt,
} from '../call_audio_contracts';
import type { PlaybackProgress } from './playback_progress';
import type { CallAudioCapability } from '../../types/call';
import { PlaybackGenerationLedger } from './playback_ledger';
import { CaptureRecoveryBuffer } from './recovery_buffer';

const CAPTURE_FORMAT: CallAudioFormat = {
  encoding: 'pcm_s16le',
  sampleRateHz: 16_000,
  channels: 1,
};
const PLAYBACK_FORMAT: CallAudioFormat = {
  encoding: 'pcm_s16le',
  sampleRateHz: 24_000,
  channels: 1,
};

export interface CallAudioCoordinatorEvents {
  onFailure?(event: NativeAudioFailure): void;
  onBackgrounded?(): void;
  onRouteObserved?(event: NativeRouteEvent): void;
}

function matchesFormat(
  actual: NativeCapability['captureFormat'] | CallAudioFormat,
  expected: CallAudioFormat,
): boolean {
  return (
    actual?.encoding === expected.encoding &&
    actual.sampleRateHz === expected.sampleRateHz &&
    actual.channels === expected.channels
  );
}

function capabilityOf(native: NativeCapability): CallAudioCapability {
  return native.available &&
    matchesFormat(native.captureFormat, CAPTURE_FORMAT) &&
    matchesFormat(native.playbackFormat, PLAYBACK_FORMAT) &&
    native.aec.available &&
    native.aec.enabled &&
    native.noiseSuppressor.available &&
    native.noiseSuppressor.enabled &&
    native.audioFocus.granted
    ? 'available'
    : 'unavailable';
}

function sameStream(left: CallAudioStreamIdentity, responseId: string, streamId: number): boolean {
  return left.responseId === responseId && left.streamId === streamId;
}

interface FinalEnqueueReservation {
  readonly token: symbol;
  readonly sessionGeneration: number | undefined;
  readonly stream: CallAudioStreamIdentity;
  earlyCompletionGeneration?: number;
}

export class AndroidCallAudio implements CallAudioCapturePort, CallAudioPlaybackPort {
  readonly recoveryBuffer = new CaptureRecoveryBuffer();
  private readonly ledger = new PlaybackGenerationLedger();
  private readonly streams = new Map<string, CallAudioStreamIdentity>();
  private readonly finalEnqueueReservations = new Map<string, FinalEnqueueReservation>();
  private readonly subscriptions: { remove(): void }[] = [];
  private consumptionListener: (receipt: PlaybackConsumptionReceipt) => void = () => {};
  private progressListener: (progress: PlaybackProgress) => void = () => {};
  private captureListener: ((frame: CapturedAudioFrame) => void) | undefined;
  private capturePaused = false;
  private sessionGeneration: number | undefined;
  private terminationFailed = false;

  constructor(
    private events: CallAudioCoordinatorEvents = {},
    private readonly native: CallAudioNativeModule | null = loadNativeCallAudio(),
    private readonly platform: string = Platform.OS,
  ) {}

  setCoordinatorEvents(events: CallAudioCoordinatorEvents): void {
    this.events = events;
  }

  async initialize(): Promise<CallAudioCapability> {
    if (this.terminationFailed || this.platform !== 'android' || this.native === null) return 'unavailable';
    try {
      const nativeCapability = await this.native.startSession();
      const capability = capabilityOf(nativeCapability);
      if (capability === 'available') {
        this.resetSessionState(nativeCapability.sessionGeneration);
        this.subscribe();
      }
      return capability;
    } catch {
      return 'unavailable';
    }
  }

  async getCapability(): Promise<CallAudioCapability> {
    if (this.terminationFailed || this.platform !== 'android' || this.native === null) return 'unavailable';
    try {
      return capabilityOf(await this.native.getCapability());
    } catch {
      return 'unavailable';
    }
  }

  async startCapture(
    format: CallAudioFormat,
    onFrame: (frame: CapturedAudioFrame) => void,
  ): Promise<void> {
    const native = this.requireNative();
    if (!matchesFormat(format, CAPTURE_FORMAT)) throw new Error('unsupported_capture_format');
    this.captureListener = onFrame;
    this.capturePaused = false;
    const capability = await native.startCapture();
    if (capabilityOf(capability) !== 'available') throw new Error(capability.reason ?? 'capture_unavailable');
  }

  async stopCapture(): Promise<void> {
    if (this.native !== null && this.platform === 'android') await this.native.stopCapture();
    this.captureListener = undefined;
    this.capturePaused = false;
  }

  async pauseCapture(): Promise<void> {
    if (this.native !== null && this.platform === 'android') await this.native.stopCapture();
    this.capturePaused = true;
  }

  async resumeCapture(): Promise<void> {
    if (!this.capturePaused) return;
    const native = this.requireNative();
    const focus = await native.reacquireAudioFocus();
    // stopCapture releases the recorder and its effects; startCapture recreates
    // them after focus is restored, so they cannot be required at this step.
    if (!focus.available || !focus.audioFocus.granted) throw new Error(focus.reason ?? 'audio_focus_denied');
    const capability = await native.startCapture();
    if (capabilityOf(capability) !== 'available') throw new Error(capability.reason ?? 'capture_unavailable');
    this.capturePaused = false;
  }

  async enqueue(chunk: CallPlaybackChunk): Promise<void> {
    const native = this.requireNative();
    if (!matchesFormat(chunk.format, PLAYBACK_FORMAT)) throw new Error('unsupported_playback_format');
    const key = this.key(chunk.stream.responseId, chunk.stream.streamId);
    const existing = this.streams.get(key);
    if (existing && existing.callId !== chunk.stream.callId) throw new Error('playback_stream_identity_conflict');
    if (chunk.isFinal && this.finalEnqueueReservations.has(key)) throw new Error('playback_final_enqueue_pending');
    this.streams.set(key, chunk.stream);
    const reservation: FinalEnqueueReservation | undefined = chunk.isFinal ? {
      token: Symbol('final-enqueue'),
      sessionGeneration: this.sessionGeneration,
      stream: chunk.stream,
    } : undefined;
    if (reservation) this.finalEnqueueReservations.set(key, reservation);
    const enqueueSessionGeneration = this.sessionGeneration;
    try {
      const generation = await native.enqueuePlayback(
        chunk.stream.responseId,
        chunk.stream.streamId,
        Buffer.from(chunk.payload).toString('base64'),
        chunk.isFinal,
      );
      if (this.sessionGeneration !== enqueueSessionGeneration) throw new Error('stale_playback_session');
      if (reservation && this.finalEnqueueReservations.get(key) !== reservation) throw new Error('stale_playback_session');
      this.ledger.register(chunk.stream, generation);
      if (reservation) {
        this.finalEnqueueReservations.delete(key);
        if (reservation.earlyCompletionGeneration === generation) this.emitCompletion(chunk.stream, generation);
      }
    } catch (error) {
      const ownsReservation = reservation !== undefined && this.finalEnqueueReservations.get(key) === reservation;
      if (ownsReservation) this.finalEnqueueReservations.delete(key);
      if (!existing && ownsReservation && this.streams.get(key) === chunk.stream) this.streams.delete(key);
      throw error;
    }
  }

  /** Records a capture frame after the call transport has assigned its authoritative wire seq. */
  recordTransportFrame(frame: CapturedAudioFrame, wireSequence: number): void {
    this.recoveryBuffer.append({ ...frame, wireSequence });
  }

  async stop(stream?: CallAudioStreamIdentity): Promise<void> {
    const native = this.requireNative();
    if (stream) {
      const key = this.key(stream.responseId, stream.streamId);
      this.finalEnqueueReservations.delete(key);
      this.ledger.tombstone(stream, Number.MAX_SAFE_INTEGER);
      await native.stopPlayback(stream.responseId, stream.streamId);
    } else {
      this.streams.forEach((knownStream) => {
        this.ledger.tombstone(knownStream, Number.MAX_SAFE_INTEGER);
      });
      this.finalEnqueueReservations.clear();
      await native.stopPlayback();
    }
  }

  async tombstone(stream: CallAudioStreamIdentity): Promise<void> {
    const native = this.requireNative();
    const key = this.key(stream.responseId, stream.streamId);
    this.finalEnqueueReservations.delete(key);
    this.ledger.tombstone(stream, Number.MAX_SAFE_INTEGER);
    await native.tombstone(stream.responseId, stream.streamId);
  }

  async playReplyFailureTone(): Promise<void> {
    await this.requireNative().playReplyFailureTone();
  }

  setConsumptionListener(listener: (receipt: PlaybackConsumptionReceipt) => void): void {
    this.consumptionListener = listener;
  }

  subscribeConsumption(listener: (receipt: PlaybackConsumptionReceipt) => void): () => void {
    this.setConsumptionListener(listener);
    return () => {
      if (this.consumptionListener === listener) this.consumptionListener = () => {};
    };
  }

  subscribePlaybackProgress(listener: (progress: PlaybackProgress) => void): () => void {
    this.progressListener = listener;
    return () => {
      if (this.progressListener === listener) this.progressListener = () => {};
    };
  }

  async close(): Promise<void> {
    this.subscriptions.splice(0).forEach((subscription) => subscription.remove());
    this.progressListener = () => {};
    this.captureListener = undefined;
    this.recoveryBuffer.clear();
    this.streams.clear();
    this.finalEnqueueReservations.clear();
    this.ledger.clear();
    this.sessionGeneration = undefined;
    if (this.native !== null && this.platform === 'android') {
      try {
        await this.native.stopSession();
      } catch (error) {
        this.terminationFailed = true;
        throw error;
      }
    }
  }

  private subscribe(): void {
    if (this.native === null || this.subscriptions.length > 0) return;
    this.subscriptions.push(
      this.native.addListener('onCapturedAudio', (event) => {
        if (!this.isCurrentSession(event.sessionGeneration)) return;
        const frame: CapturedAudioFrame = {
          deviceSequence: event.deviceSequence,
          payload: Uint8Array.from(Buffer.from(event.payloadBase64, 'base64')),
          format: event.format,
        };
        this.captureListener?.(frame);
        void this.native?.acknowledgeCapturedAudio(event.deviceSequence, event.sessionGeneration);
      }),
      this.native.addListener('onPlaybackCompleted', (event) => {
        if (!this.isCurrentSession(event.sessionGeneration)) return;
        const key = this.key(event.responseId, event.streamId);
        const stream = this.streams.get(key);
        if (stream && sameStream(stream, event.responseId, event.streamId)) {
          const reservation = this.finalEnqueueReservations.get(key);
          if (reservation && reservation.stream === stream) reservation.earlyCompletionGeneration = event.generation;
          else this.emitCompletion(stream, event.generation);
        }
      }),
      this.native.addListener('onPlaybackStopped', (event) => {
        if (!this.isCurrentSession(event.sessionGeneration)) return;
        const stream = this.streams.get(this.key(event.responseId, event.streamId));
        if (stream) this.ledger.tombstone(stream, event.generation);
      }),
      this.native.addListener('onPlaybackProgress', (event) => {
        if (!this.isCurrentSession(event.sessionGeneration)) return;
        const stream = this.streams.get(this.key(event.responseId, event.streamId));
        if (!stream || !sameStream(stream, event.responseId, event.streamId)) return;
        if (!this.ledger.acceptsProgress(stream, event.generation)) return;
        this.progressListener({
          stream,
          rms: Number.isFinite(event.rms) ? Math.max(0, Math.min(1, event.rms)) : 0,
        });
      }),
      this.native.addListener('onAudioFailure', (event) => {
        if (this.isCurrentSession(event.sessionGeneration)) this.events.onFailure?.(event);
      }),
      this.native.addListener('onLifecycle', (event: NativeLifecycleEvent) => {
        if (this.isCurrentSession(event.sessionGeneration) && event.state === 'background') {
          this.events.onBackgrounded?.();
        }
      }),
      this.native.addListener('onRouteChanged', (event) => {
        if (this.isCurrentSession(event.sessionGeneration)) this.events.onRouteObserved?.(event);
      }),
    );
  }

  private requireNative(): CallAudioNativeModule {
    if (this.terminationFailed) throw new Error('session_termination_failed');
    if (this.platform !== 'android' || this.native === null) throw new Error('call_audio_unavailable');
    return this.native;
  }

  private key(responseId: string, streamId: number): string {
    return `${responseId}\u0000${streamId}`;
  }

  private isCurrentSession(sessionGeneration: number): boolean {
    return this.sessionGeneration === sessionGeneration;
  }

  private resetSessionState(sessionGeneration: number): void {
    this.recoveryBuffer.clear();
    this.streams.clear();
    this.finalEnqueueReservations.clear();
    this.ledger.clear();
    this.sessionGeneration = sessionGeneration;
  }

  private emitCompletion(stream: CallAudioStreamIdentity, generation: number): void {
    if (this.ledger.acceptCompletion(stream, generation)) this.consumptionListener({ stream });
  }
}

function loadNativeCallAudio(): CallAudioNativeModule | null {
  if (Platform.OS !== 'android') return null;
  return requireOptionalNativeModule<CallAudioNativeModule>('CallAudio');
}

export function isAndroidCallAudioModuleAvailable(
  platform: string = Platform.OS,
  native: CallAudioNativeModule | null = loadNativeCallAudio(),
): boolean {
  return platform === 'android' && native !== null;
}

export { CAPTURE_FORMAT, PLAYBACK_FORMAT };

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

export class AndroidCallAudio implements CallAudioCapturePort, CallAudioPlaybackPort {
  readonly recoveryBuffer = new CaptureRecoveryBuffer();
  private readonly ledger = new PlaybackGenerationLedger();
  private readonly streams = new Map<string, CallAudioStreamIdentity>();
  private readonly subscriptions: { remove(): void }[] = [];
  private consumptionListener: (receipt: PlaybackConsumptionReceipt) => void = () => {};
  private captureListener: ((frame: CapturedAudioFrame) => void) | undefined;
  private sessionGeneration: number | undefined;
  private terminationFailed = false;

  constructor(
    private readonly events: CallAudioCoordinatorEvents = {},
    private readonly native: CallAudioNativeModule | null = loadNativeCallAudio(),
    private readonly platform: string = Platform.OS,
  ) {}

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
    const capability = await native.startCapture();
    if (capabilityOf(capability) !== 'available') throw new Error(capability.reason ?? 'capture_unavailable');
  }

  async stopCapture(): Promise<void> {
    if (this.native !== null && this.platform === 'android') await this.native.stopCapture();
    this.captureListener = undefined;
  }

  async enqueue(chunk: CallPlaybackChunk): Promise<void> {
    const native = this.requireNative();
    if (!matchesFormat(chunk.format, PLAYBACK_FORMAT)) throw new Error('unsupported_playback_format');
    const generation = await native.enqueuePlayback(
      chunk.stream.responseId,
      chunk.stream.streamId,
      Buffer.from(chunk.payload).toString('base64'),
      chunk.isFinal,
    );
    const key = this.key(chunk.stream.responseId, chunk.stream.streamId);
    this.streams.set(key, chunk.stream);
    this.ledger.register(chunk.stream, generation);
  }

  /** Records a capture frame after the call transport has assigned its authoritative wire seq. */
  recordTransportFrame(frame: CapturedAudioFrame, wireSequence: number): void {
    this.recoveryBuffer.append({ ...frame, wireSequence });
  }

  async stop(stream?: CallAudioStreamIdentity): Promise<void> {
    const native = this.requireNative();
    if (stream) {
      this.ledger.tombstone(stream, Number.MAX_SAFE_INTEGER);
      await native.stopPlayback(stream.responseId, stream.streamId);
    } else {
      this.streams.forEach((knownStream) => {
        this.ledger.tombstone(knownStream, Number.MAX_SAFE_INTEGER);
      });
      await native.stopPlayback();
    }
  }

  async tombstone(stream: CallAudioStreamIdentity): Promise<void> {
    const native = this.requireNative();
    this.ledger.tombstone(stream, Number.MAX_SAFE_INTEGER);
    await native.tombstone(stream.responseId, stream.streamId);
  }

  setConsumptionListener(listener: (receipt: PlaybackConsumptionReceipt) => void): void {
    this.consumptionListener = listener;
  }

  async close(): Promise<void> {
    this.subscriptions.splice(0).forEach((subscription) => subscription.remove());
    this.captureListener = undefined;
    this.recoveryBuffer.clear();
    this.streams.clear();
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
        const stream = this.streams.get(this.key(event.responseId, event.streamId));
        if (stream && sameStream(stream, event.responseId, event.streamId)) {
          if (this.ledger.acceptCompletion(stream, event.generation)) {
            this.consumptionListener({ stream });
          }
        }
      }),
      this.native.addListener('onPlaybackStopped', (event) => {
        if (!this.isCurrentSession(event.sessionGeneration)) return;
        const stream = this.streams.get(this.key(event.responseId, event.streamId));
        if (stream) this.ledger.tombstone(stream, event.generation);
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
    this.ledger.clear();
    this.sessionGeneration = sessionGeneration;
  }
}

function loadNativeCallAudio(): CallAudioNativeModule | null {
  if (Platform.OS !== 'android') return null;
  return requireOptionalNativeModule<CallAudioNativeModule>('CallAudio');
}

export { CAPTURE_FORMAT, PLAYBACK_FORMAT };

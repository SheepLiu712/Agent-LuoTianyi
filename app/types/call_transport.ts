import type { CallAudioFormat, CallPlaybackChunk, CapturedAudioFrame, PlaybackConsumptionReceipt } from '../utils/call_audio_contracts';

export interface DeferredCallSocketData {
  resolve(): Promise<Uint8Array>;
}

export type CallSocketData = string | Uint8Array | DeferredCallSocketData;

export interface CallSocketEventMap {
  open: undefined;
  message: { data: CallSocketData };
  close: { code?: number; reason?: string };
  error: { message?: string };
}

export interface CallSocket {
  readonly readyState: number;
  send(data: string | Uint8Array): void;
  close(code?: number, reason?: string): void;
  addEventListener<Type extends keyof CallSocketEventMap>(
    type: Type,
    listener: (event: CallSocketEventMap[Type]) => void,
  ): void;
  removeEventListener<Type extends keyof CallSocketEventMap>(
    type: Type,
    listener: (event: CallSocketEventMap[Type]) => void,
  ): void;
}

export interface CallSocketFactory {
  create(url: string): CallSocket;
}

export interface CallClock {
  monotonicMs(): number;
  wallClockMs(): number;
  setTimeout(callback: () => void, delayMs: number): unknown;
  clearTimeout(handle: unknown): void;
}

export interface CallNativeAudioPort {
  /**
   * tombstone must invalidate queued, in-flight, and future enqueue work for
   * the stream generation before it resolves. stop must have a finite settle
   * time; a production adapter that cannot provide this contract is unavailable.
   */
  getCapability(): Promise<'unresolved' | 'available' | 'unavailable'>;
  startCapture(format: CallAudioFormat, onFrame: (frame: CapturedAudioFrame) => void): Promise<void>;
  stopCapture(): Promise<void>;
  enqueue(chunk: CallPlaybackChunk): Promise<void>;
  stop(stream?: CallPlaybackChunk['stream']): Promise<void>;
  tombstone(stream: CallPlaybackChunk['stream']): Promise<void>;
  /** Pause production before the reliable PCM outbox overflows. */
  pauseCapture(): Promise<void>;
  resumeCapture(): Promise<void>;
  subscribeConsumption(listener: (receipt: PlaybackConsumptionReceipt) => void): () => void;
}

export interface CallNativeEvents {
  captured(frame: CapturedAudioFrame): void;
  playbackConsumed(receipt: PlaybackConsumptionReceipt): void;
}

export interface CallSwitchPort {
  prepare(clientRequestId: string, characterId: string): Promise<void>;
}

export type CallStartMode = 'prepared_switch' | 'direct_no_chat';

export interface CallCredentials {
  username: string;
  token: string;
}

export interface CallCapabilities {
  serverAvailable: boolean;
  nativeAvailable: boolean;
}

export type CallTransportStatus =
  | 'idle'
  | 'connecting'
  | 'authenticating'
  | 'starting'
  | 'connected'
  | 'recovering'
  | 'ending'
  | 'closed'
  | 'failed';

export interface CallTransportSnapshot {
  status: CallTransportStatus;
  callId?: string;
  clientRequestId?: string;
  connectedAtMonotonicMs?: number;
  activeDurationMs: number;
  recoveryDeadlineMonotonicMs?: number;
  errorCode?: string;
}

export interface StartCallRequest {
  clientRequestId: string;
  characterId: string;
}

export type CallTransportListener = (snapshot: Readonly<CallTransportSnapshot>) => void;
export type CallTransportErrorListener = (code: string) => void;

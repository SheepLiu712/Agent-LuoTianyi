import type { CallAudioCapability } from '../types/call';

/**
 * This describes negotiated audio without choosing a native module, codec, or
 * call.v1 binary layout. F1 AAC/M4A recordings are intentionally not an
 * implementation of this streaming contract.
 */
export interface CallAudioFormat {
  encoding: string;
  sampleRateHz: number;
  channels: number;
}

export interface CallAudioStreamIdentity {
  callId: string;
  responseId: string;
  streamId: number;
}

export interface CapturedAudioFrame {
  /** Device-frame counter scoped to one native call session; not a call.v1 wire seq. */
  deviceSequence: number;
  format: CallAudioFormat;
  payload: Uint8Array;
}

/** The transport coordinator is the sole authority that assigns call.v1 wire seq values. */
export interface SequencedCapturedAudioFrame extends CapturedAudioFrame {
  wireSequence: number;
}

export interface CallPlaybackChunk {
  stream: CallAudioStreamIdentity;
  format: CallAudioFormat;
  payload: Uint8Array;
  isFinal: boolean;
}

/** A receipt is emitted only after the device consumed the final sample. */
export interface PlaybackConsumptionReceipt {
  stream: CallAudioStreamIdentity;
}

export interface CallAudioCapturePort {
  getCapability(): Promise<CallAudioCapability>;
  startCapture(
    format: CallAudioFormat,
    onFrame: (frame: CapturedAudioFrame) => void,
  ): Promise<void>;
  stopCapture(): Promise<void>;
}

export interface CallAudioPlaybackPort {
  getCapability(): Promise<CallAudioCapability>;
  enqueue(chunk: CallPlaybackChunk): Promise<void>;
  stop(stream?: CallAudioStreamIdentity): Promise<void>;
  tombstone(stream: CallAudioStreamIdentity): Promise<void>;
  setConsumptionListener(listener: (receipt: PlaybackConsumptionReceipt) => void): void;
}

/** Unresolved is deliberately treated as unavailable for starting a call. */
export function canStartRealtimeAudio(capability: CallAudioCapability): boolean {
  return capability === 'available';
}

import type { SequencedCapturedAudioFrame } from '../call_audio_contracts';

export const CAPTURE_BYTES_PER_SECOND = 16_000 * 2;
export const MAX_RECOVERY_BYTES = CAPTURE_BYTES_PER_SECOND * 3;

/** Keeps transport-assigned call.v1 sequence numbers for reconnect retransmission. */
export class CaptureRecoveryBuffer {
  private readonly frames: SequencedCapturedAudioFrame[] = [];
  private byteLength = 0;

  append(frame: SequencedCapturedAudioFrame): void {
    if (frame.payload.byteLength > MAX_RECOVERY_BYTES) {
      throw new Error('capture_frame_too_large');
    }
    this.frames.push(frame);
    this.byteLength += frame.payload.byteLength;
    while (this.byteLength > MAX_RECOVERY_BYTES) {
      const discarded = this.frames.shift();
      if (discarded) this.byteLength -= discarded.payload.byteLength;
    }
  }

  acknowledge(wireSequence: number): void {
    while (this.frames[0] && this.frames[0].wireSequence <= wireSequence) {
      this.byteLength -= this.frames.shift()!.payload.byteLength;
    }
  }

  unacknowledgedAfter(wireSequence: number): readonly SequencedCapturedAudioFrame[] {
    return this.frames.filter((frame) => frame.wireSequence > wireSequence);
  }

  clear(): void {
    this.frames.length = 0;
    this.byteLength = 0;
  }

  get bufferedBytes(): number {
    return this.byteLength;
  }
}

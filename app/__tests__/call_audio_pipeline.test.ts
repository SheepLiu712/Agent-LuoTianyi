import type { SequencedCapturedAudioFrame } from '../utils/call_audio_contracts';
import { PlaybackGenerationLedger } from '../utils/call_audio/playback_ledger';
import {
  CaptureRecoveryBuffer,
  MAX_RECOVERY_BYTES,
} from '../utils/call_audio/recovery_buffer';

const format = { encoding: 'pcm_s16le', sampleRateHz: 16_000, channels: 1 };

function frame(wireSequence: number, bytes: number): SequencedCapturedAudioFrame {
  return { deviceSequence: wireSequence + 100, wireSequence, format, payload: new Uint8Array(bytes) };
}

describe('CaptureRecoveryBuffer', () => {
  it('keeps at most three seconds while preserving original sequence numbers', () => {
    const buffer = new CaptureRecoveryBuffer();
    for (let sequence = 1; sequence <= 4; sequence += 1) {
      buffer.append(frame(sequence, MAX_RECOVERY_BYTES / 3));
    }

    expect(buffer.bufferedBytes).toBe(MAX_RECOVERY_BYTES);
    expect(buffer.unacknowledgedAfter(0).map((item) => item.wireSequence)).toEqual([2, 3, 4]);
  });

  it('removes only acknowledged frames and exposes missing frames in order', () => {
    const buffer = new CaptureRecoveryBuffer();
    buffer.append(frame(10, 320));
    buffer.append(frame(11, 320));
    buffer.append(frame(12, 320));

    buffer.acknowledge(10);

    expect(buffer.unacknowledgedAfter(10).map((item) => item.wireSequence)).toEqual([11, 12]);
  });
});

describe('PlaybackGenerationLedger', () => {
  const stream = { callId: 'call-1', responseId: 'response-1', streamId: 7 };

  it('accepts a current completion exactly once', () => {
    const ledger = new PlaybackGenerationLedger();
    ledger.register(stream, 3);

    expect(ledger.acceptCompletion(stream, 3)).toBe(true);
    expect(ledger.acceptCompletion(stream, 3)).toBe(false);
  });

  it('rejects completion from a generation made stale by tombstone', () => {
    const ledger = new PlaybackGenerationLedger();
    ledger.register(stream, 3);
    ledger.tombstone(stream, 4);

    expect(ledger.acceptCompletion(stream, 3)).toBe(false);
    expect(ledger.acceptCompletion(stream, 4)).toBe(false);
  });

  it('keeps tombstones final even if a later registration arrives', () => {
    const ledger = new PlaybackGenerationLedger();
    ledger.register(stream, 3);
    ledger.tombstone(stream, 4);
    ledger.register(stream, 5);

    expect(ledger.acceptCompletion(stream, 5)).toBe(false);
  });
});

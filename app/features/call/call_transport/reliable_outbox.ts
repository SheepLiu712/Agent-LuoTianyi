const UINT32_MAX = 0xffff_ffff;

export type OutboxKind = 'audio' | 'control';

interface OutboxEntry {
  readonly seq: number;
  readonly kind: OutboxKind;
  readonly wire: string | Uint8Array;
  readonly bytes: number;
}

export class ReliableCallOutbox {
  private readonly entries = new Map<number, OutboxEntry>();
  private nextSequence = 1;
  private acknowledgedSequence = 0;
  private audioBytes = 0;
  private controlCount = 0;

  constructor(
    private readonly maxAudioBytes = 96_000,
    private readonly maxControlEntries = 64,
  ) {}

  get nextSeq(): number {
    if (this.nextSequence > UINT32_MAX) throw new Error('SEQ_EXHAUSTED');
    return this.nextSequence;
  }

  get audioCapacityRemaining(): number {
    return this.maxAudioBytes - this.audioBytes;
  }

  pendingControls(): readonly OutboxEntry[] {
    return [...this.entries.values()].filter((entry) => entry.kind === 'control');
  }

  add(
    kind: OutboxKind,
    wireFactory: (seq: number) => string | Uint8Array,
    budgetBytes?: number,
  ): OutboxEntry {
    const seq = this.nextSeq;
    const wire = wireFactory(seq);
    const wireBytes = typeof wire === 'string' ? utf8ByteLength(wire) : wire.byteLength;
    const bytes = budgetBytes ?? wireBytes;
    if (!Number.isInteger(bytes) || bytes <= 0 || bytes > wireBytes) throw new Error('INVALID_OUTBOX_SIZE');
    if (kind === 'audio' && this.audioBytes + bytes > this.maxAudioBytes) throw new Error('AUDIO_OUTBOX_FULL');
    if (kind === 'control' && this.controlCount >= this.maxControlEntries) throw new Error('CONTROL_OUTBOX_FULL');
    const entry = { seq, kind, wire, bytes };
    this.entries.set(seq, entry);
    this.nextSequence += 1;
    if (kind === 'audio') this.audioBytes += bytes;
    else this.controlCount += 1;
    return entry;
  }

  acknowledge(cursor: number): void {
    if (!Number.isInteger(cursor) || cursor < this.acknowledgedSequence || cursor >= this.nextSequence) {
      throw new Error('INVALID_ACK_CURSOR');
    }
    this.acknowledgedSequence = cursor;
    for (const [seq, entry] of this.entries) {
      if (seq > cursor) continue;
      this.entries.delete(seq);
      if (entry.kind === 'audio') this.audioBytes -= entry.bytes;
      else this.controlCount -= 1;
    }
  }

  replayAfter(cursor: number): readonly OutboxEntry[] {
    if (!Number.isInteger(cursor) || cursor < 0 || cursor >= this.nextSequence) throw new Error('INVALID_RESUME_CURSOR');
    return [...this.entries.values()].filter((entry) => entry.seq > cursor);
  }

  replayMissing(seq: number): OutboxEntry {
    const entry = this.entries.get(seq);
    if (!entry) throw new Error('REPLAY_NOT_AVAILABLE');
    return entry;
  }

  clear(): void {
    this.entries.clear();
    this.audioBytes = 0;
    this.controlCount = 0;
  }
}

function utf8ByteLength(value: string): number {
  let bytes = 0;
  for (const character of value) {
    const codePoint = character.codePointAt(0)!;
    if (codePoint <= 0x7f) bytes += 1;
    else if (codePoint <= 0x7ff) bytes += 2;
    else if (codePoint <= 0xffff) bytes += 3;
    else bytes += 4;
  }
  return bytes;
}

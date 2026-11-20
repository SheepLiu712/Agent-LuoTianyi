import type { ControlMessage, PlaybackStop } from '../call_protocol/control_types';

export interface IncomingFrame {
  seq: number;
  raw: Uint8Array;
  control?: ControlMessage;
  audio?: { responseId?: string; streamId: number; final: boolean; payload: Uint8Array };
}

interface Fingerprint { length: number; first: number; second: number }
interface Identity { responseId?: string; streamId?: number }
interface CommittedReceipt extends Identity { kind: 'committed'; fingerprint: Fingerprint }
interface RetiredReceipt extends Identity { kind: 'retired'; stopSeq: number }
type Receipt = CommittedReceipt | RetiredReceipt;
interface OwnershipRange extends Identity {
  from: number;
  through: number;
  kind: 'committed' | 'retired';
  stopSeq?: number;
}

export interface IncomingReceiveResult {
  ackSeq: number;
  missingSeq?: number;
  immediateStop?: PlaybackStop;
  retiredActiveSeq?: number;
  ignoredRetiredDuplicate?: boolean;
}

/** Wire ordering owns only bounded pending bytes and lightweight receipts/ranges. */
export class IncomingCallSequence {
  private cursor = 0;
  private activeSeq: number | null = null;
  private readonly pending = new Map<number, IncomingFrame>();
  private readonly receipts = new Map<number, Receipt>();
  private readonly retiredAhead = new Map<number, RetiredReceipt>();
  private readonly ownershipRanges: OwnershipRange[] = [];
  private pendingBytes = 0;

  constructor(
    private readonly maxPendingFrames = 256,
    private readonly maxPendingBytes = 4 * 1024 * 1024,
    private readonly maxReceipts = 4096,
    private readonly maxOwnershipRanges = 4096,
  ) {}

  get lastContiguousSeq(): number { return this.cursor; }
  get retainedPayloadBytes(): number { return this.pendingBytes; }
  get retainedMetadataCount(): number { return this.receipts.size + this.retiredAhead.size + this.ownershipRanges.length; }

  pendingStreamRegistration(streamId: number): ControlMessage | undefined {
    for (const frame of this.pending.values()) {
      if (frame.control?.type === 'audio.stream_started' && frame.control.stream_id === streamId) return frame.control;
    }
    return undefined;
  }

  receive(frame: IncomingFrame): IncomingReceiveResult {
    requireSequence(frame.seq);
    const receipt = this.receipts.get(frame.seq);
    if (receipt) return this.handleReceiptDuplicate(frame, receipt);
    if (frame.seq <= this.cursor) return this.handleEvictedDuplicate(frame);
    const pending = this.pending.get(frame.seq);
    if (pending) {
      if (!sameFingerprint(fingerprintBytes(pending.raw), fingerprintBytes(frame.raw))) throw new Error('SEQ_CONFLICT');
      return { ackSeq: this.cursor, missingSeq: this.firstMissing() };
    }

    let immediateStop: PlaybackStop | undefined;
    let retiredActiveSeq: number | undefined;
    if (frame.control?.type === 'playback.stop') {
      retiredActiveSeq = this.retire(frame.control);
      immediateStop = frame.control;
    }
    this.addPending(frame);
    this.advanceRetired();
    return {
      ackSeq: this.cursor,
      missingSeq: frame.seq > this.cursor + 1 ? this.firstMissing() : undefined,
      immediateStop,
      retiredActiveSeq,
    };
  }

  /** Claim only when the real consumer is ready to begin work. */
  claimReady(): IncomingFrame | undefined {
    if (this.activeSeq !== null) return undefined;
    const frame = this.pending.get(this.cursor + 1);
    if (!frame) return undefined;
    this.activeSeq = frame.seq;
    return frame;
  }

  commitClaimed(seq: number): number {
    if (this.activeSeq !== seq) throw new Error('INVALID_COMMIT_SEQUENCE');
    const frame = this.pending.get(seq);
    if (!frame) throw new Error('COMMIT_FRAME_MISSING');
    this.pending.delete(seq);
    this.pendingBytes -= frame.raw.byteLength;
    this.activeSeq = null;
    this.recordCommitted(seq, frame);
    this.cursor = seq;
    this.advanceRetired();
    return this.cursor;
  }

  isRetired(seq: number): boolean {
    return this.receipts.get(seq)?.kind === 'retired' || this.retiredAhead.has(seq);
  }

  clear(): void {
    this.pending.clear();
    this.receipts.clear();
    this.retiredAhead.clear();
    this.ownershipRanges.length = 0;
    this.pendingBytes = 0;
    this.activeSeq = null;
  }

  private handleReceiptDuplicate(frame: IncomingFrame, receipt: Receipt): IncomingReceiveResult {
    if (receipt.kind === 'retired') {
      const identity = frameIdentity(frame);
      if (
        identity.streamId !== receipt.streamId ||
        (identity.responseId !== undefined && identity.responseId !== receipt.responseId)
      ) {
        throw new Error('SEQ_CONFLICT');
      }
      return { ackSeq: this.cursor, ignoredRetiredDuplicate: true };
    }
    if (!sameFingerprint(receipt.fingerprint, fingerprintBytes(frame.raw))) throw new Error('SEQ_CONFLICT');
    return { ackSeq: this.cursor };
  }

  private handleEvictedDuplicate(frame: IncomingFrame): IncomingReceiveResult {
    const range = this.ownershipRanges.find((candidate) => frame.seq >= candidate.from && frame.seq <= candidate.through);
    if (!range || range.kind === 'committed') throw new Error('DUPLICATE_HISTORY_EXPIRED');
    const identity = frameIdentity(frame);
    if (
      identity.streamId !== range.streamId ||
      (identity.responseId !== undefined && identity.responseId !== range.responseId)
    ) throw new Error('SEQ_CONFLICT');
    return { ackSeq: this.cursor, ignoredRetiredDuplicate: true };
  }

  private retire(stop: PlaybackStop): number | undefined {
    const { from, through } = stop.retire_server_seq;
    if (from > through || through >= stop.seq) throw new Error('INVALID_RETIRE_RANGE');
    for (let seq = from; seq <= through; seq += 1) {
      const identity = this.identityAt(seq);
      const isUnreceivedFuture = seq > this.cursor && !this.pending.has(seq) && !this.retiredAhead.has(seq);
      const mismatched = !identity || identity.streamId !== stop.stream_id ||
        (identity.responseId !== undefined && identity.responseId !== stop.response_id);
      if (!isUnreceivedFuture && mismatched) {
        throw new Error('INVALID_RETIRE_RANGE');
      }
    }
    const retiredActiveSeq = this.activeSeq !== null && this.activeSeq >= from && this.activeSeq <= through
      ? this.activeSeq : undefined;
    if (retiredActiveSeq !== undefined) this.activeSeq = null;
    for (let seq = from; seq <= through; seq += 1) {
      if (seq <= this.cursor) continue;
      const pending = this.pending.get(seq);
      if (pending) {
        this.pending.delete(seq);
        this.pendingBytes -= pending.raw.byteLength;
      }
      this.retiredAhead.set(seq, {
        kind: 'retired', responseId: stop.response_id, streamId: stop.stream_id, stopSeq: stop.seq,
      });
    }
    this.advanceRetired();
    return retiredActiveSeq;
  }

  private identityAt(seq: number): Identity | undefined {
    const pending = this.pending.get(seq);
    if (pending) return frameIdentity(pending);
    const receipt = this.receipts.get(seq) ?? this.retiredAhead.get(seq);
    if (receipt) return receipt;
    return this.ownershipRanges.find((range) => seq >= range.from && seq <= range.through);
  }

  private addPending(frame: IncomingFrame): void {
    if (this.pending.size >= this.maxPendingFrames) throw new Error('PENDING_WINDOW_FULL');
    if (this.pendingBytes + frame.raw.byteLength > this.maxPendingBytes) throw new Error('PENDING_BYTES_FULL');
    this.pending.set(frame.seq, frame);
    this.pendingBytes += frame.raw.byteLength;
  }

  private advanceRetired(): void {
    while (this.retiredAhead.has(this.cursor + 1)) {
      const seq = this.cursor + 1;
      const receipt = this.retiredAhead.get(seq)!;
      this.retiredAhead.delete(seq);
      this.recordReceipt(seq, receipt);
      this.recordOwnership(seq, receipt, 'retired', receipt.stopSeq);
      this.cursor = seq;
    }
  }

  private recordCommitted(seq: number, frame: IncomingFrame): void {
    this.recordReceipt(seq, { kind: 'committed', ...frameIdentity(frame), fingerprint: fingerprintBytes(frame.raw) });
    this.recordOwnership(seq, frameIdentity(frame), 'committed');
  }

  private recordReceipt(seq: number, receipt: Receipt): void {
    this.receipts.set(seq, receipt);
    while (this.receipts.size > this.maxReceipts) this.receipts.delete(this.receipts.keys().next().value!);
  }

  private recordOwnership(
    seq: number,
    identity: Identity,
    kind: 'committed' | 'retired',
    stopSeq?: number,
  ): void {
    if (identity.streamId === undefined) return;
    const last = this.ownershipRanges.at(-1);
    if (
      last && last.through + 1 === seq && last.responseId === identity.responseId &&
      last.streamId === identity.streamId && last.kind === kind && last.stopSeq === stopSeq
    ) {
      last.through = seq;
      return;
    }
    if (this.ownershipRanges.length >= this.maxOwnershipRanges) throw new Error('OWNERSHIP_METADATA_FULL');
    this.ownershipRanges.push({ from: seq, through: seq, kind, stopSeq, ...identity });
  }

  private firstMissing(): number | undefined {
    let seq = this.cursor + 1;
    while (this.retiredAhead.has(seq) || this.pending.has(seq)) seq += 1;
    // Native acceptance can lag receipt. Only a received later sequence proves
    // a wire gap; the next not-yet-sent frame must never be requested.
    for (const received of this.pending.keys()) if (received > seq) return seq;
    for (const retired of this.retiredAhead.keys()) if (retired > seq) return seq;
    return undefined;
  }
}

function frameIdentity(frame: IncomingFrame): Identity {
  if (frame.audio) return { responseId: frame.audio.responseId, streamId: frame.audio.streamId };
  const control = frame.control;
  if (control && 'response_id' in control && 'stream_id' in control) {
    return { responseId: control.response_id, streamId: control.stream_id };
  }
  return {};
}

function requireSequence(seq: number): void {
  if (!Number.isInteger(seq) || seq < 1 || seq > 0xffff_ffff) throw new Error('INVALID_SEQ');
}

function fingerprintBytes(bytes: Uint8Array): Fingerprint {
  let first = 0x811c9dc5;
  let second = 0x9e3779b9;
  for (const byte of bytes) {
    first = Math.imul(first ^ byte, 0x01000193) >>> 0;
    second = Math.imul(second + byte + 0x7ed55d16, 0x85ebca6b) >>> 0;
  }
  return { length: bytes.byteLength, first, second };
}

function sameFingerprint(left: Fingerprint, right: Fingerprint): boolean {
  return left.length === right.length && left.first === right.first && left.second === right.second;
}

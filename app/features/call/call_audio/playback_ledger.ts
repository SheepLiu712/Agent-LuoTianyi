import type { CallAudioStreamIdentity } from '../call_audio_contracts';

function keyOf(stream: CallAudioStreamIdentity): string {
  return `${stream.responseId}\u0000${stream.streamId}`;
}

/** Filters stale native callbacks after a stop/tombstone generation boundary. */
export class PlaybackGenerationLedger {
  private readonly generations = new Map<string, number>();
  private readonly completed = new Set<string>();

  register(stream: CallAudioStreamIdentity, generation: number): void {
    const key = keyOf(stream);
    if (this.completed.has(key)) return;
    const current = this.generations.get(key);
    if (current === undefined || generation > current) {
      this.generations.set(key, generation);
    }
  }

  tombstone(stream: CallAudioStreamIdentity, generation: number): void {
    this.generations.set(keyOf(stream), generation);
    this.completed.add(keyOf(stream));
  }

  acceptCompletion(stream: CallAudioStreamIdentity, generation: number): boolean {
    const key = keyOf(stream);
    if (this.generations.get(key) !== generation || this.completed.has(key)) return false;
    this.completed.add(key);
    return true;
  }

  clear(): void {
    this.generations.clear();
    this.completed.clear();
  }
}

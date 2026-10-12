import { Audio } from 'expo-av';
import { Buffer } from 'buffer';

const RINGTONE_URI = createRingtoneDataUri();

export class ExpoCallRingtone {
  private sound: Audio.Sound | null = null;
  private starting: Promise<void> | null = null;
  private generation = 0;
  private desiredPlaying = false;

  playLoop(): void {
    this.desiredPlaying = true;
    if (this.sound) {
      void this.sound.playAsync().catch(() => undefined);
      return;
    }
    if (this.starting) return;
    const generation = ++this.generation;
    this.starting = Audio.Sound.createAsync(
      { uri: RINGTONE_URI },
      { shouldPlay: false, isLooping: true, volume: 0.22 },
    ).then(async ({ sound }) => {
      if (!this.desiredPlaying || generation !== this.generation) {
        await sound.unloadAsync();
        return;
      }
      this.sound = sound;
      try {
        await sound.playAsync();
      } catch {
        if (this.sound === sound) {
          this.sound = null;
          await sound.unloadAsync();
        }
        return;
      }
      if (!this.desiredPlaying || generation !== this.generation) {
        this.sound = null;
        await sound.stopAsync().catch(() => undefined);
        await sound.unloadAsync();
      }
    }).catch(() => undefined).finally(() => {
      this.starting = null;
      // Only replace an obsolete creation after a new play request. A backend
      // failure must not start an unbounded microtask retry loop.
      if (this.desiredPlaying && generation !== this.generation && !this.sound) {
        queueMicrotask(() => this.playLoop());
      }
    });
  }

  stop(): void {
    this.desiredPlaying = false;
    this.generation += 1;
    const sound = this.sound;
    this.sound = null;
    if (sound) void sound.stopAsync().catch(() => undefined).then(() => sound.unloadAsync()).catch(() => undefined);
  }
}

function createRingtoneDataUri(): string {
  const sampleRate = 8_000;
  const durationSeconds = 1;
  const samples = sampleRate * durationSeconds;
  const dataSize = samples * 2;
  const wav = Buffer.alloc(44 + dataSize);
  wav.write('RIFF', 0);
  wav.writeUInt32LE(36 + dataSize, 4);
  wav.write('WAVEfmt ', 8);
  wav.writeUInt32LE(16, 16);
  wav.writeUInt16LE(1, 20);
  wav.writeUInt16LE(1, 22);
  wav.writeUInt32LE(sampleRate, 24);
  wav.writeUInt32LE(sampleRate * 2, 28);
  wav.writeUInt16LE(2, 32);
  wav.writeUInt16LE(16, 34);
  wav.write('data', 36);
  wav.writeUInt32LE(dataSize, 40);
  for (let index = 0; index < samples; index += 1) {
    const active = index < sampleRate * 0.45;
    const sample = active ? Math.sin((2 * Math.PI * 440 * index) / sampleRate) * 5_000 : 0;
    wav.writeInt16LE(Math.round(sample), 44 + index * 2);
  }
  return `data:audio/wav;base64,${wav.toString('base64')}`;
}

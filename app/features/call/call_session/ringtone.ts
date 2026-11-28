import { requireOptionalNativeModule } from 'expo-modules-core';

interface RingtoneModule {
  traceRingtonePhase(event: string, phase: string): void;
  startRingtone(): void;
  stopRingtone(): void;
}

export class NativeCallRingtone {
  private playing = false;
  private native: RingtoneModule | null = null;

  tracePhase(event: string, phase: string): void {
    this.native ??= requireOptionalNativeModule<RingtoneModule>('CallAudio');
    this.native?.traceRingtonePhase(event, phase);
  }

  playLoop(): void {
    if (this.playing) return;
    this.native = requireOptionalNativeModule<RingtoneModule>('CallAudio');
    if (!this.native) throw new Error('call_audio_unavailable');
    this.native.startRingtone();
    this.playing = true;
  }

  stop(): void {
    if (!this.playing) return;
    this.native!.stopRingtone();
    this.playing = false;
  }
}

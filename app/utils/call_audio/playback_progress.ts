import type { CallAudioStreamIdentity } from '../call_audio_contracts';

export interface PlaybackProgress {
  stream: CallAudioStreamIdentity;
  rms: number;
}

export interface CallMouthBridge {
  update(rms: number): void;
  reset(): void;
}

export function createCallMouthBridge(
  injectJavaScript: (code: string) => void,
): CallMouthBridge {
  return {
    update(rms) {
      const safeRms = Number.isFinite(rms) ? Math.max(0, Math.min(1, rms)) : 0;
      try {
        injectJavaScript(`window.setCallMouthRms(${safeRms}); true;`);
      } catch {
        // A missing or tearing-down WebView must not affect the call/audio path.
      }
    },
    reset() {
      try {
        injectJavaScript('window.setCallMouthRms(0); true;');
      } catch {
        // Visual cleanup is best effort; native audio remains authoritative.
      }
    },
  };
}

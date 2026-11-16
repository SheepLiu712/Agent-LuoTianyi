import type { CallAudioStreamIdentity } from '../call_audio_contracts';

export type PlaybackProgress =
  | { stream: CallAudioStreamIdentity; kind: 'rms'; rms: number }
  | { stream: CallAudioStreamIdentity; kind: 'reset' };

export interface CallMouthBridge {
  update(rms: number): void;
  reset(): void;
  subscribeAnalysisWindow?(listener: (seconds: number) => void): () => void;
}

export function createCallMouthBridge(
  injectJavaScript: (code: string) => void,
): CallMouthBridge & { configureAnalysisWindow(sampleRate: number, samples: number): void } {
  // Same 128-sample chat analyser window, until the WebView reports its actual rate.
  let windowSeconds = 128 / 48_000;
  const windowListeners = new Set<(seconds: number) => void>();
  return {
    configureAnalysisWindow(sampleRate, samples) {
      if (!Number.isFinite(sampleRate) || sampleRate < 8_000 || sampleRate > 192_000 || samples !== 128) return;
      windowSeconds = samples / sampleRate;
      windowListeners.forEach((listener) => listener(windowSeconds));
    },
    subscribeAnalysisWindow(listener) {
      windowListeners.add(listener);
      listener(windowSeconds);
      return () => { windowListeners.delete(listener); };
    },
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
        injectJavaScript('window.resetCallMouth(); true;');
      } catch {
        // Visual cleanup is best effort; native audio remains authoritative.
      }
    },
  };
}

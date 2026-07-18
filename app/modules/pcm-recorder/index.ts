import { Platform } from 'react-native';
import nativeRecorder from './src/PcmRecorderModule';
import type { PcmChunk, PcmRecordingError } from './src/PcmRecorder.types';

export type { PcmChunk, PcmRecordingError } from './src/PcmRecorder.types';

interface EventSubscription {
  remove(): void;
}

/**
 * Android 16-bit/16kHz/mono PCM recorder.
 *
 * A recorder instance owns only its JavaScript listeners. Android capture state is
 * process-wide because the Expo native module itself is a singleton.
 */
export class PcmRecorder {
  private chunkSubscription: EventSubscription | null = null;
  private errorSubscription: EventSubscription | null = null;

  async start(
    onChunk: (chunk: PcmChunk) => void,
    onError?: (error: PcmRecordingError) => void,
  ): Promise<void> {
    if (Platform.OS !== 'android' || !nativeRecorder) {
      throw new Error('当前客户端没有可用的 16kHz PCM 录音模块');
    }

    this.removeListeners();
    this.chunkSubscription = nativeRecorder.addListener('pcmChunk', (chunk) => {
      if (chunk?.audio) onChunk(chunk);
    });
    this.errorSubscription = nativeRecorder.addListener('recordingError', (error) => {
      onError?.(error);
    });

    try {
      await nativeRecorder.start();
    } catch (error) {
      this.removeListeners();
      throw error;
    }
  }

  async stop(): Promise<void> {
    this.removeListeners();
    if (nativeRecorder) await nativeRecorder.stop();
  }

  private removeListeners(): void {
    this.chunkSubscription?.remove();
    this.errorSubscription?.remove();
    this.chunkSubscription = null;
    this.errorSubscription = null;
  }
}

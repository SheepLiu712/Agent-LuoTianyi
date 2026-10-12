export interface NativeAudioFormat {
  encoding: 'pcm_s16le';
  sampleRateHz: number;
  channels: 1;
}

export interface NativeCapability {
  available: boolean;
  reason?: string;
  captureFormat?: NativeAudioFormat;
  playbackFormat?: NativeAudioFormat;
  aec: {
    available: boolean;
    enabled: boolean;
    error?: string;
  };
  noiseSuppressor: {
    available: boolean;
    enabled: boolean;
    error?: string;
  };
  audioFocus: {
    granted: boolean;
    error?: string;
  };
  sessionGeneration: number;
}

export interface NativeCapturedFrame {
  deviceSequence: number;
  sessionGeneration: number;
  payloadBase64: string;
  format: NativeAudioFormat;
}

export interface NativePlaybackIdentity {
  responseId: string;
  streamId: number;
  generation: number;
  sessionGeneration: number;
}

export type NativePlaybackCompleted = NativePlaybackIdentity;

export type NativePlaybackStopped = NativePlaybackIdentity;

export interface NativeAudioFailure {
  code: string;
  operation: 'capture' | 'playback' | 'session';
  sessionGeneration: number;
}

export interface NativeLifecycleEvent {
  state: 'background';
  sessionGeneration: number;
}

export interface NativeRouteEvent {
  outputs: string[];
  sessionGeneration: number;
}

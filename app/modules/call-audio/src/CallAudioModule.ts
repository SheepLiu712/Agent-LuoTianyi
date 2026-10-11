import { requireOptionalNativeModule } from 'expo-modules-core';

import type {
  NativeAudioFailure,
  NativeCapability,
  NativeCapturedFrame,
  NativeLifecycleEvent,
  NativePlaybackCompleted,
  NativePlaybackStopped,
  NativeRouteEvent,
} from './CallAudio.types';

export interface CallAudioNativeModule {
  getCapability(): Promise<NativeCapability>;
  startSession(): Promise<NativeCapability>;
  stopSession(): Promise<void>;
  startCapture(): Promise<NativeCapability>;
  stopCapture(): Promise<void>;
  acknowledgeCapturedAudio(deviceSequence: number, sessionGeneration: number): Promise<void>;
  enqueuePlayback(
    responseId: string,
    streamId: number,
    payloadBase64: string,
    isFinal: boolean,
  ): Promise<number>;
  stopPlayback(responseId?: string, streamId?: number): Promise<void>;
  tombstone(responseId: string, streamId: number): Promise<void>;
  addListener(
    eventName: 'onCapturedAudio',
    listener: (event: NativeCapturedFrame) => void,
  ): { remove(): void };
  addListener(
    eventName: 'onPlaybackCompleted',
    listener: (event: NativePlaybackCompleted) => void,
  ): { remove(): void };
  addListener(
    eventName: 'onPlaybackStopped',
    listener: (event: NativePlaybackStopped) => void,
  ): { remove(): void };
  addListener(
    eventName: 'onAudioFailure',
    listener: (event: NativeAudioFailure) => void,
  ): { remove(): void };
  addListener(
    eventName: 'onLifecycle',
    listener: (event: NativeLifecycleEvent) => void,
  ): { remove(): void };
  addListener(
    eventName: 'onRouteChanged',
    listener: (event: NativeRouteEvent) => void,
  ): { remove(): void };
}

export default requireOptionalNativeModule<CallAudioNativeModule>('CallAudio');

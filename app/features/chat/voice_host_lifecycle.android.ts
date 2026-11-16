import { requireOptionalNativeModule } from 'expo-modules-core';

type VoiceHostLifecycle = {
  addListener(name: 'onHostStopped', listener: () => void): { remove(): void };
};

/** Expo Go does not include project-local Android modules. */
export function subscribeVoiceHostStopped(listener: () => void): { remove(): void } {
  const lifecycle = requireOptionalNativeModule<VoiceHostLifecycle>('VoiceHostLifecycle');
  return lifecycle?.addListener('onHostStopped', listener) ?? { remove() {} };
}

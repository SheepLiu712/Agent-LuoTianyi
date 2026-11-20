/** The host-stopped signal is Android-specific. */
export function subscribeVoiceHostStopped(_listener: () => void): { remove(): void } {
  return { remove() {} };
}

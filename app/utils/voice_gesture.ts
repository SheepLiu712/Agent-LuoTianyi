import { VoiceCaptureState } from '../types/chat';

export const VOICE_CANCEL_DISTANCE = 80;
export const MIN_VOICE_DURATION_MS = 500;
export const MAX_VOICE_DURATION_MS = 30000;

export function voiceStateForMove(state: VoiceCaptureState, initialPageY: number, pageY: number): VoiceCaptureState {
  if (state !== 'Recording' && state !== 'CancelZone') return state;
  return initialPageY - pageY >= VOICE_CANCEL_DISTANCE ? 'CancelZone' : 'Recording';
}

export function formatVoiceDuration(durationMs: number) {
  const seconds = Math.min(30, Math.max(1, Math.ceil(durationMs / 1000)));
  return `${seconds}''`;
}

export function voiceBubbleWidth(durationMs: number) {
  const seconds = Math.min(30, Math.max(1, Math.ceil(durationMs / 1000)));
  return Math.min(200, Math.max(76, 76 + (seconds - 1) * (124 / 29)));
}

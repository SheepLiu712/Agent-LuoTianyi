import type { CallEffect, CallEndReason, CallEvent, CallState, CallTransition } from '../types/call';
import { canStartRealtimeAudio } from './call_audio_contracts';

export const initialCallState: CallState = {
  phase: 'IDLE',
  audioCapability: 'unresolved',
  requiresChatSwitch: false,
};

const TERMINAL_PHASES = new Set<CallState['phase']>(['ENDED', 'DECLINED', 'FAILED']);

function transition(state: CallState, effects: readonly CallEffect[] = []): CallTransition {
  return { state, effects };
}

function isTerminal(state: CallState): boolean {
  return TERMINAL_PHASES.has(state.phase);
}

function activeDurationAt(state: CallState, nowMs: number): number {
  if (state.activeStartedAtMs === undefined) return 0;
  return Math.max(0, nowMs - state.activeStartedAtMs);
}

function finish(
  state: CallState,
  phase: Extract<CallState['phase'], 'ENDING' | 'ENDED' | 'DECLINED' | 'FAILED'>,
  reason: CallEndReason,
  nowMs: number,
  includeReturn = true,
): CallTransition {
  if (isTerminal(state) || state.phase === 'ENDING') return transition(state);
  const effects: CallEffect[] = [{ type: 'stop_capture' }, { type: 'stop_playback' }];
  if (includeReturn) effects.push({ type: 'return_to_chat' });
  const endedActiveDurationMs =
    state.phase === 'RECONNECTING' && state.activeDurationAtDisconnectMs !== undefined
      ? state.activeDurationAtDisconnectMs
      : activeDurationAt(state, nowMs);
  return transition(
    {
      ...state,
      phase,
      endReason: reason,
      endedActiveDurationMs,
    },
    effects,
  );
}

/**
 * Pure UI lifecycle reducer. Its effects are commands for a future screen and
 * transport coordinator; it never performs permission, WebSocket, or audio IO.
 */
export function reduceCallState(state: CallState, event: CallEvent): CallTransition {
  if (isTerminal(state)) return transition(state);

  switch (event.type) {
    case 'audio_capability':
      return transition({ ...state, audioCapability: event.capability });

    case 'request_call':
      if (state.phase !== 'IDLE' || !canStartRealtimeAudio(state.audioCapability)) return transition(state);
      return transition(
        {
          ...state,
          phase: 'REQUESTING_PERMISSION',
          requiresChatSwitch: event.requiresChatSwitch,
          clientRequestId: event.clientRequestId,
        },
        [{ type: 'request_permission' }],
      );

    case 'permission_granted':
      if (state.phase !== 'REQUESTING_PERMISSION') return transition(state);
      if (!canStartRealtimeAudio(state.audioCapability)) return transition(state);
      if (state.requiresChatSwitch) {
        if (!state.clientRequestId) return transition(state);
        return transition({ ...state, phase: 'SWITCH_PREPARING' }, [
          { type: 'prepare_switch', clientRequestId: state.clientRequestId },
        ]);
      }
      return transition({ ...state, phase: 'CONNECTING' }, [{ type: 'open_call' }]);

    case 'permission_denied':
    case 'permission_permanently_denied':
      if (state.phase !== 'REQUESTING_PERMISSION') return transition(state);
      return transition(
        { ...state, phase: 'IDLE', requiresChatSwitch: false, clientRequestId: undefined },
        [{ type: 'return_to_chat' }],
      );

    case 'switch_ready':
      if (state.phase !== 'SWITCH_PREPARING') return transition(state);
      return transition({ ...state, phase: 'CONNECTING' }, [{ type: 'close_chat' }, { type: 'open_call' }]);

    case 'switch_failed':
      if (state.phase !== 'SWITCH_PREPARING') return transition(state);
      return transition({ ...state, phase: 'FAILED', endReason: 'failed' }, [{ type: 'return_to_chat' }]);

    case 'transport_authenticated':
      if (state.phase !== 'CONNECTING' || !state.clientRequestId) return transition(state);
      return transition({ ...state, phase: 'PREPARING' }, [
        { type: 'start', clientRequestId: state.clientRequestId },
      ]);

    case 'transport_auth_failed':
      if (state.phase !== 'CONNECTING') return transition(state);
      return finish(state, 'FAILED', 'failed', 0);

    case 'server_state':
      if (state.phase !== 'PREPARING' && state.phase !== 'RINGING') return transition(state);
      return transition({ ...state, phase: event.state, callId: event.callId ?? state.callId });

    case 'call_active':
      if (state.phase !== 'PREPARING' && state.phase !== 'RINGING') return transition(state);
      return transition({ ...state, phase: 'ACTIVE', callId: event.callId, activeStartedAtMs: event.connectedAtMs });

    case 'user_hangup':
    case 'back_confirmed':
    case 'app_backgrounded':
      return finish(
        state,
        'ENDING',
        event.type === 'app_backgrounded' ? 'backgrounded' : 'user_hangup',
        event.nowMs,
      );

    case 'back_requested':
      if (state.phase === 'ENDING') return transition(state);
      return transition(state, [{ type: 'show_back_confirmation' }]);

    case 'back_cancelled':
      return transition(state);

    case 'transport_lost': {
      if (state.phase !== 'ACTIVE' || !state.callId) return transition(state);
      return transition(
        { ...state, phase: 'RECONNECTING', activeDurationAtDisconnectMs: activeDurationAt(state, event.nowMs) },
        [{ type: 'stop_capture' }, { type: 'stop_playback' }, { type: 'resume', callId: state.callId }],
      );
    }

    case 'transport_resumed':
      if (state.phase !== 'RECONNECTING') return transition(state);
      return transition({ ...state, phase: 'ACTIVE', activeDurationAtDisconnectMs: undefined });

    case 'recovery_timeout':
      if (state.phase !== 'RECONNECTING') return transition(state);
      return finish(state, 'ENDING', 'recovery_timeout', 0);

    case 'declined':
      if (state.phase !== 'PREPARING' && state.phase !== 'RINGING') return transition(state);
      return finish(state, 'DECLINED', 'declined', 0);

    case 'call_ended':
      if (state.phase !== 'ENDING' && state.phase !== 'ACTIVE' && state.phase !== 'RECONNECTING') return transition(state);
      return transition({
        ...state,
        phase: 'ENDED',
        endReason: state.endReason ?? 'remote_ended',
        endedActiveDurationMs: state.endedActiveDurationMs ?? activeDurationAt(state, event.nowMs),
      });
  }
}

/** Duration used by the UI clock; the reconnect overlay continues showing it. */
export function getCallActiveDurationMs(state: CallState, nowMs: number): number {
  if (state.endedActiveDurationMs !== undefined) return state.endedActiveDurationMs;
  return activeDurationAt(state, nowMs);
}

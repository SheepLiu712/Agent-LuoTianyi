/**
 * Client-owned call lifecycle state. Wire protocol states stay outside this
 * module so the UI can be tested before call.v1 transport integration exists.
 */
export type CallPhase =
  | 'IDLE'
  | 'REQUESTING_PERMISSION'
  | 'SWITCH_PREPARING'
  | 'CONNECTING'
  | 'PREPARING'
  | 'RINGING'
  | 'ACTIVE'
  | 'RECONNECTING'
  | 'ENDING'
  | 'ENDED'
  | 'DECLINED'
  | 'FAILED';

export type CallAudioCapability = 'unresolved' | 'available' | 'unavailable';

export type CallEndReason =
  | 'user_hangup'
  | 'backgrounded'
  | 'recovery_timeout'
  | 'declined'
  | 'failed'
  | 'remote_ended';

export interface CallState {
  phase: CallPhase;
  audioCapability: CallAudioCapability;
  /** Whether the current chat binding must be handed over before call.start. */
  requiresChatSwitch: boolean;
  clientRequestId?: string;
  callId?: string;
  /** Timestamp of the first ACTIVE transition for the displayed call clock. */
  activeStartedAtMs?: number;
  /** Active duration at the first unsuccessful reconnect boundary. */
  activeDurationAtDisconnectMs?: number;
  endedActiveDurationMs?: number;
  endReason?: CallEndReason;
}

export type CallEffect =
  | { type: 'request_permission' }
  | { type: 'prepare_switch'; clientRequestId: string }
  | { type: 'close_chat' }
  | { type: 'open_call' }
  | { type: 'start'; clientRequestId: string }
  | { type: 'resume'; callId: string }
  | { type: 'stop_capture' }
  | { type: 'stop_playback' }
  | { type: 'show_back_confirmation' }
  | { type: 'return_to_chat' };

export type CallEvent =
  | { type: 'audio_capability'; capability: CallAudioCapability }
  | { type: 'request_call'; requiresChatSwitch: boolean; clientRequestId: string }
  | { type: 'permission_granted' }
  | { type: 'permission_denied' }
  | { type: 'permission_permanently_denied' }
  | { type: 'switch_ready' }
  | { type: 'switch_failed' }
  | { type: 'transport_authenticated' }
  | { type: 'transport_auth_failed' }
  | { type: 'server_state'; state: 'PREPARING' | 'RINGING'; callId?: string }
  | { type: 'call_active'; callId: string; connectedAtMs: number }
  | { type: 'user_hangup'; nowMs: number }
  | { type: 'back_requested' }
  | { type: 'back_confirmed'; nowMs: number }
  | { type: 'back_cancelled' }
  | { type: 'app_backgrounded'; nowMs: number }
  | { type: 'transport_lost'; nowMs: number }
  | { type: 'transport_resumed'; nowMs: number }
  | { type: 'recovery_timeout' }
  | { type: 'declined' }
  | { type: 'call_ended'; nowMs: number };

export interface CallTransition {
  state: CallState;
  effects: readonly CallEffect[];
}

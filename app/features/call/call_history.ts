import type { CallState } from './call';
import type { CallTransportSnapshot } from './call_transport/contracts';
import type { ChatMessage } from '../../types/chat';

/** A local display projection, not an acknowledgement of server persistence. */
export function localCallHistory(
  state: CallState,
  snapshot: Readonly<CallTransportSnapshot> | null,
  requestedAt: number,
): ChatMessage | null {
  const callId = snapshot?.callId ?? state.callId;
  if (!callId) return null;
  const terminal = snapshot?.status === 'closed' && snapshot.outcome ? snapshot : null;
  const connected = terminal ? terminal.outcome === 'connected' : state.activeStartedAtMs !== undefined;
  const declined = terminal?.outcome === 'declined' || state.endReason === 'declined';
  const cancelled = terminal
    ? terminal.outcome === 'cancelled_before_answer' && terminal.endReason === 'user_hangup'
    : state.endReason === 'user_hangup' || state.endReason === 'backgrounded';
  if (!connected && !declined && !cancelled) return null;
  return {
    uuid: `call:${callId}`, callId, type: 'call', isUser: true, content: '[语音通话]',
    timestamp: requestedAt,
    callOutcome: connected ? 'connected' : declined ? 'declined' : 'cancelled',
    durationMs: connected ? terminal?.activeDurationMs ?? state.endedActiveDurationMs ?? 0 : 0,
  };
}

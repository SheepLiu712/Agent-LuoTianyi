import type { CallState } from '../types/call';
import type { CallTransportSnapshot } from '../types/call_transport';
import type { ChatMessage } from '../types/chat';

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

/** Keep existing chat messages; only persisted call records replace local facts. Incoming is newest first. */
export function mergeLoadedHistory(existing: ChatMessage[], incoming: ChatMessage[]): ChatMessage[] {
  const result = [...existing];
  const uuids = new Map(result.map((message, index) => [message.uuid, index]));
  const calls = new Map(result.flatMap((message, index) =>
    message.type === 'call' && message.callId ? [[message.callId, index] as const] : []));
  for (const message of incoming) {
    const index = (message.type === 'call' && message.callId ? calls.get(message.callId) : undefined)
      ?? uuids.get(message.uuid);
    if (index !== undefined) {
      if (message.type === 'call' && result[index].type === 'call') {
        result[index] = message;
        uuids.set(message.uuid, index);
        if (message.callId) calls.set(message.callId, index);
      }
      continue;
    }
    uuids.set(message.uuid, result.length);
    if (message.type === 'call' && message.callId) calls.set(message.callId, result.length);
    result.push(message);
  }
  return result;
}

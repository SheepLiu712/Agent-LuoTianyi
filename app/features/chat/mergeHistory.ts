import type { ChatMessage } from '../../types/chat';

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

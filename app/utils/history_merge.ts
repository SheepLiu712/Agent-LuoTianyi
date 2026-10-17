import type { ChatMessage } from '../types/chat';

export type HistoryMergeMode = 'latest' | 'older';

function isStableUuid(message: ChatMessage): boolean {
  return Boolean(message.uuid) && message.uuid !== 'unknown_id';
}

function isPendingMessage(message: ChatMessage): boolean {
  return message.sendStatus === 'waiting';
}

function mergeSameUuid(existing: ChatMessage, incoming: ChatMessage): ChatMessage {
  // Playback and upload state belongs to this device. History is authoritative
  // for persisted facts only when its timestamp does not predate the message.
  const incomingIsNotOlder = incoming.timestamp === undefined
    ? existing.timestamp === undefined
    : existing.timestamp === undefined || incoming.timestamp >= existing.timestamp;
  const authoritative = incomingIsNotOlder ? incoming : existing;
  return {
    ...existing,
    ...authoritative,
    content: isPendingMessage(existing) || !incomingIsNotOlder ? existing.content : incoming.content,
    sendStatus: existing.sendStatus ?? incoming.sendStatus,
    audioLocalUri: existing.audioLocalUri ?? incoming.audioLocalUri,
    audioPlayState: existing.audioPlayState ?? incoming.audioPlayState,
    audioDownloadState: existing.audioDownloadState ?? incoming.audioDownloadState,
    audioAvailable: existing.audioAvailable ?? incoming.audioAvailable,
  };
}

function normalizeStableIncomingMessages(incomingMessages: ChatMessage[]): ChatMessage[] {
  // The last record is the server's final fact. Keep the first occurrence's
  // position so a duplicate page cannot disturb newest-first tie ordering.
  const lastByUuid = new Map<string, ChatMessage>();
  for (const message of incomingMessages) {
    if (isStableUuid(message)) lastByUuid.set(message.uuid, message);
  }
  const emittedUuids = new Set<string>();
  return incomingMessages.flatMap((message) => {
    if (!isStableUuid(message)) return [message];
    if (emittedUuids.has(message.uuid)) return [];
    emittedUuids.add(message.uuid);
    return [lastByUuid.get(message.uuid)!];
  });
}

function insertLatestAdditions(existingMessages: ChatMessage[], additions: ChatMessage[]): ChatMessage[] {
  const orderedAdditions = additions
    .map((message, index) => ({ message, index }))
    .sort((left, right) => {
      const leftTimestamp = left.message.timestamp;
      const rightTimestamp = right.message.timestamp;
      if (leftTimestamp === undefined || rightTimestamp === undefined) return left.index - right.index;
      return rightTimestamp - leftTimestamp || left.index - right.index;
    });
  const result = [...existingMessages];
  for (const { message } of orderedAdditions) {
    if (message.timestamp === undefined) {
      const pendingPrefixLength = result.findIndex((existing) => !isPendingMessage(existing));
      const insertionIndex = pendingPrefixLength < 0 ? result.length : pendingPrefixLength;
      result.splice(insertionIndex, 0, message);
      continue;
    }
    const timestamp = message.timestamp;
    // Pending messages have no authoritative server timestamp. Keep their
    // newest-first prefix ahead of a late latest-page response.
    const pendingPrefixLength = result.findIndex((existing) => !isPendingMessage(existing));
    const minimumIndex = pendingPrefixLength < 0 ? result.length : pendingPrefixLength;
    let insertionIndex = result.findIndex((existing, index) =>
      index >= minimumIndex
      && existing.timestamp !== undefined
      && existing.timestamp < timestamp);
    if (insertionIndex < 0) insertionIndex = result.length;
    result.splice(insertionIndex, 0, message);
  }
  return result;
}

export function mergeHistoryMessages(existingMessages: ChatMessage[], incomingMessages: ChatMessage[], mode: HistoryMergeMode = 'older'): ChatMessage[] {
  const normalizedIncoming = normalizeStableIncomingMessages(incomingMessages);
  const incomingByUuid = new Map(normalizedIncoming.filter(isStableUuid).map((message) => [message.uuid, message]));
  const merged = existingMessages.map((existing) => {
    if (!isStableUuid(existing)) return existing;
    const incoming = incomingByUuid.get(existing.uuid);
    return incoming ? mergeSameUuid(existing, incoming) : existing;
  });
  const existingUuids = new Set(existingMessages.filter(isStableUuid).map((message) => message.uuid));
  const additions = normalizedIncoming.filter((message) => !isStableUuid(message) || !existingUuids.has(message.uuid));
  return mode === 'latest' ? insertLatestAdditions(merged, additions) : [...merged, ...additions];
}

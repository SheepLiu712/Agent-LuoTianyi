import { ChatMessage } from '../types/chat';

/**
 * 按 uuid 对历史消息去重：
 * - 过滤与已有消息 uuid 重复的批次内消息；
 * - 同一批次内重复 uuid 只保留第一条；
 * - 保持 incomingMessages 原始顺序。
 */
export const deduplicateMessages = (
  existingMessages: ChatMessage[],
  incomingMessages: ChatMessage[],
): ChatMessage[] => {
  const seen = new Set(existingMessages.map((message) => message.uuid));

  return incomingMessages.filter((message) => {
    if (seen.has(message.uuid)) {
      return false;
    }
    seen.add(message.uuid);
    return true;
  });
};

/** 简单的字符串散列，用于为缺失 uuid 的历史消息生成确定性 ID。 */
function hashString(input: string): string {
  let hash = 5381;
  for (let i = 0; i < input.length; i += 1) {
    hash = (hash * 33) ^ input.charCodeAt(i);
  }
  return (hash >>> 0).toString(36);
}

/**
 * 服务端历史消息缺失 uuid 时，基于稳定字段（source/type/timestamp/content）生成确定性 ID，
 * 避免多条缺 uuid 消息共用固定 unknown_id 导致 FlatList key 冲突。
 * 相同内容的消息重复拉取时 ID 保持一致，可被 deduplicateMessages 正确过滤。
 * 注意：内容与时间戳完全相同的消息会得到相同 ID，这是缺失唯一标识时无法避免的极限情况。
 */
export const buildFallbackUuid = (msg: Record<string, unknown>): string => {
  if (msg.uuid) {
    return String(msg.uuid);
  }
  const source = String(msg.source || 'unknown');
  const type = String(msg.type || 'text');
  const timestamp = msg.timestamp == null ? '' : String(msg.timestamp);
  const content =
    typeof msg.content === 'string' ? msg.content : JSON.stringify(msg.content ?? '');
  return `history-${source}-${type}-${timestamp}-${hashString(content)}`;
};

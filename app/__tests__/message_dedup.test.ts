import { ChatMessage } from '../types/chat';
import { buildFallbackUuid, deduplicateMessages } from '../utils/message_dedup';

const msg = (uuid: string, content = uuid): ChatMessage => ({
  uuid,
  type: 'text',
  content,
  isUser: false,
  timestamp: 1,
});

describe('deduplicateMessages', () => {
  it('同一批次重复 uuid 只保留第一条', () => {
    const result = deduplicateMessages([], [msg('a'), msg('a'), msg('b')]);
    expect(result.map((m) => m.uuid)).toEqual(['a', 'b']);
  });

  it('多条相同 unknown_id 只保留第一条（纯函数兜底）', () => {
    const result = deduplicateMessages(
      [],
      [msg('unknown_id', '第一条'), msg('unknown_id', '第二条')],
    );
    expect(result.map((m) => m.uuid)).toEqual(['unknown_id']);
  });

  it('同时过滤已有列表重复和批次内重复', () => {
    const existing = [msg('old-id')];
    const incoming = [msg('new-id'), msg('new-id'), msg('old-id')];
    const result = deduplicateMessages(existing, incoming);
    expect(result.map((m) => m.uuid)).toEqual(['new-id']);
  });

  it('去重后保持批次内顺序', () => {
    const result = deduplicateMessages([], [msg('b'), msg('a'), msg('c'), msg('a')]);
    expect(result.map((m) => m.uuid)).toEqual(['b', 'a', 'c']);
  });
});

describe('buildFallbackUuid', () => {
  it('有 uuid 时原样返回', () => {
    expect(buildFallbackUuid({ uuid: 'server-uuid' })).toBe('server-uuid');
  });

  it('不同内容的消息生成不同 ID，不再共用 unknown_id', () => {
    const first = buildFallbackUuid({
      source: 'user',
      type: 'text',
      timestamp: '2026-01-01 00:00:00',
      content: '第一条',
    });
    const second = buildFallbackUuid({
      source: 'user',
      type: 'text',
      timestamp: '2026-01-01 00:00:00',
      content: '第二条',
    });
    expect(first).not.toBe(second);
  });

  it('相同内容的消息 ID 稳定，可被去重函数过滤', () => {
    const input = { source: 'user', type: 'text', timestamp: '2026-01-01 00:00:00', content: '重复消息' };
    const id = buildFallbackUuid(input);
    const result = deduplicateMessages([], [msg(id), msg(id)]);
    expect(result.map((m) => m.uuid)).toEqual([id]);
  });
});

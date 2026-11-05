import { TextDecoder, TextEncoder } from 'util';
import { fetch as streamingFetch } from 'expo/fetch';
import { callLlmProvider } from '../utils/llm_client';
import { WebSocketTransport } from '../utils/ws_transport';

jest.mock('expo/fetch', () => ({ fetch: jest.fn() }));
jest.mock('react-native', () => ({ AppState: {
  currentState: 'active', addEventListener: jest.fn(() => ({ remove: jest.fn() })),
} }));
jest.mock('../config', () => ({ server_config: { BASE_URL: 'http://localhost:60030' } }));

Object.assign(global, { TextDecoder, TextEncoder });

function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>((done) => { resolve = done; });
  return { promise, resolve };
}

it('中文 UTF-8 分片在完整结果之前返回，并保留最终用量', async () => {
  const release = deferred(), first = deferred();
  const start = new TextEncoder().encode('data: {"choices":[{"delta":{"content":"第一句话。"}}]}\n\n');
  const end = new TextEncoder().encode(
    'data: {"choices":[{"delta":{"content":"第二句。"},"finish_reason":"stop"}]}\n\n'
    + 'data: {"usage":{"total_tokens":12}}\n\ndata: [DONE]\n\n',
  );
  let index = 0;
  const reader = {
    read: async () => {
      if (index < start.length) return { value: start.slice(index, ++index), done: false };
      await release.promise;
      return { value: end, done: false };
    }, cancel: jest.fn(), releaseLock: jest.fn(),
  };
  (streamingFetch as jest.Mock).mockResolvedValue({ ok: true, body: { getReader: () => reader } });
  const deltas: string[] = [];
  let finished = false;
  const task = callLlmProvider({
    url: 'https://example.test', apiKey: 'test-key', body: { stream: true },
    onDelta: (text) => { deltas.push(text); first.resolve(); },
  }).then((result) => { finished = true; return result; });
  await first.promise;
  expect(deltas).toEqual(['第一句话。']);
  expect(finished).toBe(false);
  release.resolve();
  expect(await task).toEqual({ content: '第一句话。第二句。', usage: { total_tokens: 12 } });
  expect(deltas).toEqual(['第一句话。', '第二句。']);
  expect(reader.cancel).toHaveBeenCalledTimes(1);
});

it('委托增量和最终结果按顺序发回原连接', async () => {
  const release = deferred(), first = deferred();
  const transport = new WebSocketTransport('u', 'token', {
    onAgentMessage: jest.fn(), onAgentStateChanged: jest.fn(), onError: jest.fn(),
    onLlmRequest: async (_payload, onDelta) => {
      await onDelta!('第一句'); first.resolve(); await release.promise;
      await onDelta!('第二句'); return { request_id: 'r', content: '第一句第二句' };
    },
  }, { expectedCharacterId: 'luotianyi' });
  const send = jest.fn();
  (transport as any).ws = { readyState: 1, send };
  const task = (transport as any).handleLlmRequest({ request_id: 'r', stream: true });
  await first.promise;
  expect(send).toHaveBeenCalledTimes(1);
  release.resolve(); await task;
  expect(send.mock.calls.map(([text]) => JSON.parse(text).payload)).toEqual([
    { request_id: 'r', sequence: 0, delta: '第一句' },
    { request_id: 'r', sequence: 1, delta: '第二句' },
    { request_id: 'r', sequence: 2, done: true, content: '第一句第二句' },
  ]);
});

it.each(['cancel', 'disconnect'])('%s 后中止供应商请求且不把迟到结果发给新连接', async (reason) => {
  const first = deferred(), release = deferred();
  let signal: AbortSignal | undefined;
  const transport = new WebSocketTransport('u', 'token', {
    onAgentMessage: jest.fn(), onAgentStateChanged: jest.fn(), onError: jest.fn(),
    onLlmRequest: async (_payload, onDelta, incomingSignal) => {
      signal = incomingSignal; await onDelta!('第一句'); first.resolve(); await release.promise;
      return { request_id: 'r', content: '第一句' };
    },
  }, { expectedCharacterId: 'luotianyi' });
  const oldSend = jest.fn(), newSend = jest.fn();
  Object.assign(transport, { ws: { readyState: 1, send: oldSend }, isStopped: false, socketEpoch: 1 });
  const task = (transport as any).handleLlmRequest({ request_id: 'r', stream: true });
  await first.promise;
  if (reason === 'cancel') {
    (transport as any).handleServerMessage(JSON.stringify({ type: 'llm_cancel', payload: { request_id: 'r' } }), 1);
  } else {
    (transport as any).rejectAllWaiters('disconnected');
    (transport as any).ws = { readyState: 1, send: newSend };
  }
  expect(signal?.aborted).toBe(true);
  release.resolve(); await task;
  expect(oldSend).toHaveBeenCalledTimes(1);
  expect(newSend).not.toHaveBeenCalled();
});

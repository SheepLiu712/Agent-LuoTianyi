import { mergeHistoryMessages } from '../utils/history_merge';

test('history merge updates an existing summary and keeps one deterministic uuid', () => {
  const existing = [{ uuid: 'call-1', type: 'call', content: '[语音通话]', isUser: true, durationMs: 1000 } as any];
  const incoming = [{ uuid: 'call-1', type: 'call', content: '[语音通话]', isUser: true, durationMs: 2000 } as any];
  const merged = mergeHistoryMessages(existing, incoming);
  expect(merged).toHaveLength(1);
  expect(merged[0].durationMs).toBe(2000);
});

test('latest adds newest records at the front while older adds records at the tail', () => {
  const existing = [{ uuid: 'live', type: 'text', content: 'live', isUser: false } as any];
  expect(mergeHistoryMessages(existing, [{ uuid: 'latest', type: 'call', content: '[语音通话]', isUser: true } as any], 'latest').map((message) => message.uuid)).toEqual(['latest', 'live']);
  expect(mergeHistoryMessages(existing, [{ uuid: 'older', type: 'text', content: 'older', isUser: false } as any], 'older').map((message) => message.uuid)).toEqual(['live', 'older']);
});

test('latest keeps a newer local waiting message ahead of a late server page and preserves equal-time order', () => {
  const existing = [
    { uuid: 'local-waiting', type: 'text' as const, content: 'still sending', isUser: true, sendStatus: 'waiting' as const, timestamp: 12 * 60 + 1 },
    { uuid: 'local-streaming', type: 'text' as const, content: 'live', isUser: false, sendStatus: 'waiting' as const, timestamp: 12 * 60 + 1 },
  ];
  const incoming = [
    { uuid: 'call-1200', type: 'call' as const, content: '[语音通话]', isUser: true, timestamp: 12 * 60 },
    { uuid: 'older-1100', type: 'text' as const, content: 'older', isUser: false, timestamp: 11 * 60 },
    { uuid: 'same-time-first', type: 'text' as const, content: 'one', isUser: false, timestamp: 10 * 60 },
    { uuid: 'same-time-second', type: 'text' as const, content: 'two', isUser: false, timestamp: 10 * 60 },
  ];

  expect(mergeHistoryMessages(existing, incoming, 'latest').map((message) => message.uuid)).toEqual([
    'local-waiting', 'local-streaming', 'call-1200', 'older-1100', 'same-time-first', 'same-time-second',
  ]);
});

test('same uuid preserves local audio state and live content while accepting call facts', () => {
  const existing = [{
    uuid: 'call-1', type: 'call' as const, content: 'live summary', isUser: true, sendStatus: 'waiting' as const,
    timestamp: 1000, audioLocalUri: 'file://recording.m4a', audioPlayState: 'playing' as const,
    audioDownloadState: 'ready' as const, audioAvailable: true,
  }];
  const incoming = [{
    uuid: 'call-1', type: 'call' as const, content: '[语音通话]', isUser: true, timestamp: 2000,
    durationMs: 2000, callOutcome: 'connected' as const,
  }];

  expect(mergeHistoryMessages(existing, incoming, 'latest')).toEqual([expect.objectContaining({
    uuid: 'call-1', content: 'live summary', sendStatus: 'waiting', audioLocalUri: 'file://recording.m4a',
    audioPlayState: 'playing', audioDownloadState: 'ready', audioAvailable: true, timestamp: 2000,
    durationMs: 2000, callOutcome: 'connected',
  })]);
});

test.each(['latest', 'older'] as const)('%s collapses duplicate stable UUIDs within one history page using the last server fact', (mode) => {
  const incoming = [
    { uuid: 'call-1', type: 'call' as const, content: 'first summary', isUser: true, timestamp: 1000, durationMs: 1000 },
    { uuid: 'call-1', type: 'call' as const, content: 'settled summary', isUser: true, timestamp: 2000, durationMs: 2000 },
  ];

  const merged = mergeHistoryMessages([], incoming, mode);
  expect(merged).toEqual([expect.objectContaining({
    uuid: 'call-1', content: 'settled summary', timestamp: 2000, durationMs: 2000,
  })]);
});

test.each(['latest', 'older'] as const)('%s updates an existing stable UUID once when a page repeats it', (mode) => {
  const existing = [{ uuid: 'call-1', type: 'call' as const, content: 'initial', isUser: true, timestamp: 500, durationMs: 500 }];
  const incoming = [
    { uuid: 'call-1', type: 'call' as const, content: 'first summary', isUser: true, timestamp: 1000, durationMs: 1000 },
    { uuid: 'call-1', type: 'call' as const, content: 'settled summary', isUser: true, timestamp: 2000, durationMs: 2000 },
  ];

  const merged = mergeHistoryMessages(existing, incoming, mode);
  expect(merged).toHaveLength(1);
  expect(merged[0]).toEqual(expect.objectContaining({
    uuid: 'call-1', content: 'settled summary', timestamp: 2000, durationMs: 2000,
  }));
});

test('older history cannot roll an agent live message backward without a send status', () => {
  const existing = [{ uuid: 'agent-1', type: 'text' as const, content: 'live-new', isUser: false, timestamp: 2000 }];
  const incoming = [{ uuid: 'agent-1', type: 'text' as const, content: 'stale-old', isUser: false, timestamp: 1000 }];

  expect(mergeHistoryMessages(existing, incoming, 'older')).toEqual([expect.objectContaining({
    uuid: 'agent-1', content: 'live-new', timestamp: 2000,
  })]);
});

test('unknown ids are never used to collapse distinct messages', () => {
  const merged = mergeHistoryMessages([
    { uuid: 'unknown_id', type: 'text', content: 'a', isUser: false } as any,
  ], [
    { uuid: 'unknown_id', type: 'text', content: 'b', isUser: false } as any,
  ], 'latest');
  expect(merged).toHaveLength(2);
});

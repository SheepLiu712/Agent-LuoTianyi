import { localCallHistory, mergeLoadedHistory } from '../utils/call_history';
import { initialCallState, reduceCallState } from '../utils/call_state';
import type { CallState } from '../types/call';
import type { ChatMessage } from '../types/chat';

const active: CallState = { ...initialCallState, phase: 'ACTIVE', callId: 'call-1', activeStartedAtMs: 100 };

test('reconnecting hangup freezes duration at disconnect and background exit projects the same call', () => {
  const reconnecting = reduceCallState(active, { type: 'transport_lost', nowMs: 2100 }).state;
  const ended = reduceCallState(reconnecting, { type: 'app_backgrounded', nowMs: 4100 }).state;
  expect(localCallHistory(ended, null, 123)).toMatchObject({
    uuid: 'call:call-1', callId: 'call-1', timestamp: 123, callOutcome: 'connected', durationMs: 2000,
  });
});

test('permission denial, unconfirmed attempts and establishment failures do not create history', () => {
  for (const state of [initialCallState,
    { ...initialCallState, phase: 'ENDING' as const, endReason: 'user_hangup' as const },
    { ...initialCallState, phase: 'FAILED' as const, callId: 'call-1', endReason: 'failed' as const },
  ]) expect(localCallHistory(state, null, 123)).toBeNull();
});

test('terminal connected facts work even if ACTIVE was missed', () => {
  expect(localCallHistory({ ...initialCallState, phase: 'FAILED' }, {
    status: 'closed', callId: 'call-1', outcome: 'connected', endReason: 'user_hangup', activeDurationMs: 1234,
  }, 123)).toMatchObject({ callOutcome: 'connected', durationMs: 1234 });
});

test('persisted call replaces local identity and facts without overwriting waiting or playing chat messages', () => {
  const local = localCallHistory({ ...active, endedActiveDurationMs: 900 }, null, 123)!;
  const waiting: ChatMessage = { uuid: 'waiting', type: 'text', isUser: true, content: 'new input', sendStatus: 'waiting' };
  const playing: ChatMessage = { uuid: 'playing', type: 'text', isUser: false, content: 'live', audioPlayState: 'playing' };
  const stored: ChatMessage = { uuid: 'db-uuid', callId: 'call-1', type: 'call', isUser: true,
    content: '[语音通话]', callOutcome: 'connected', durationMs: 1500, timestamp: 120 };
  const incoming = [stored, { ...playing, content: 'stale', audioPlayState: 'idle' as const }];
  const merged = mergeLoadedHistory([waiting, local, playing], incoming);
  expect(merged).toEqual([waiting, stored, playing]);
  expect(mergeLoadedHistory(merged, [stored, stored])).toEqual(merged);
  expect(mergeLoadedHistory([], [stored, stored])).toEqual([stored]);
});

test('server outcome calibrates a local cancellation and different calls remain distinct', () => {
  const local = localCallHistory({ ...initialCallState, phase: 'ENDING', callId: 'call-1', endReason: 'user_hangup' }, null, 123)!;
  const stored: ChatMessage = { ...local, uuid: 'db-uuid', callOutcome: 'declined' };
  const other: ChatMessage = { ...stored, uuid: 'other', callId: 'call-2' };
  expect(mergeLoadedHistory([local], [stored, other])).toEqual([stored, other]);
});

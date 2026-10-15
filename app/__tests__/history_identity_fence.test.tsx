import React from 'react';
import { act, create } from 'react-test-renderer';
import { historyIdentityEquals, useHistoryLogic } from '../hooks/useHistoryLogic';
import { getHistory } from '../utils/getHistory';

jest.mock('react-native', () => ({ __esModule: true, Platform: { OS: 'android' } }));
jest.mock('../utils/debug_trace', () => ({ addDebugTrace: jest.fn() }));
jest.mock('../utils/getHistory', () => ({ getHistory: jest.fn() }));

function Probe({ identity, onResult, onMessages }: { identity: any; onResult: (value: any) => void; onMessages: (messages: any[]) => void }) {
  const logic = useHistoryLogic(onMessages, identity);
  onResult(logic);
  return null;
}

test('identity change fences old response and reset does not resurrect it', async () => {
  let resolveA!: (value: any) => void;
  (getHistory as jest.Mock).mockImplementationOnce(() => new Promise((resolve) => { resolveA = resolve; }));
  let identity = { username: 'A', characterId: 'luotianyi', token: 'token-A', resetEpoch: 1 };
  let result: any; let messages: any[] = []; let root!: ReturnType<typeof create>;
  act(() => { root = create(<Probe identity={identity} onResult={(value) => { result = value; }} onMessages={(value) => { messages = value; }} />); });
  const pending = result.refreshLatestHistory('A', 'token-A');
  identity = { username: 'B', characterId: 'luotianyi', token: 'token-B', resetEpoch: 2 };
  act(() => { root.update(<Probe identity={identity} onResult={(value) => { result = value; }} onMessages={(value) => { messages = value; }} />); });
  resolveA({ messages: [{ uuid: 'old-A', type: 'call', content: '[语音通话]', isUser: true }], startIndex: 0 });
  await pending;
  expect(messages).toEqual([]);
  expect(result.history_start_index).toBe(-1);
  act(() => root.unmount());
});

test('identity fence compares username, character, token, and reset epoch', () => {
  const identity = { username: 'A', characterId: 'luotianyi', token: 'token-A', resetEpoch: 0 };
  expect(historyIdentityEquals(identity, { ...identity })).toBe(true);
  expect(historyIdentityEquals(identity, { ...identity, characterId: 'other' })).toBe(false);
  expect(historyIdentityEquals(identity, { ...identity, token: 'token-B' })).toBe(false);
  expect(historyIdentityEquals(identity, { ...identity, resetEpoch: 1 })).toBe(false);
});

test('refresh supersession keeps the second owner loading until its response', async () => {
  let resolveFirst!: (value: any) => void;
  let resolveSecond!: (value: any) => void;
  (getHistory as jest.Mock)
    .mockImplementationOnce(() => new Promise((resolve) => { resolveFirst = resolve; }))
    .mockImplementationOnce(() => new Promise((resolve) => { resolveSecond = resolve; }));
  let result: any; let messages: any[] = []; let root!: ReturnType<typeof create>;
  act(() => { root = create(<Probe identity={{ username: 'A', characterId: 'luotianyi', token: 't', resetEpoch: 1 }} onResult={(value) => { result = value; }} onMessages={(value) => { messages = value; }} />); });
  const first = result.refreshLatestHistory('A', 't');
  const second = result.refreshLatestHistory('A', 't');
  await act(async () => { resolveFirst({ messages: [{ uuid: 'old', type: 'call', content: '[语音通话]', isUser: true }], startIndex: 0 }); await first; });
  expect(result.historyLoading).toBe(true);
  await act(async () => { resolveSecond({ messages: [{ uuid: 'new', type: 'call', content: '[语音通话]', isUser: true }], startIndex: 0 }); await second; });
  expect(result.historyLoading).toBe(false);
  expect(messages).toEqual(expect.arrayContaining([expect.objectContaining({ uuid: 'new' })]));
  act(() => root.unmount());
});

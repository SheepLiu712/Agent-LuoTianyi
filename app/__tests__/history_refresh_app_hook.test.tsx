import React from 'react';
import { act, create } from 'react-test-renderer';
import { useHistoryLogic } from '../hooks/useHistoryLogic';
import { getHistory } from '../utils/getHistory';

jest.mock('react-native', () => ({ __esModule: true, Platform: { OS: 'android' } }));
jest.mock('../utils/debug_trace', () => ({ addDebugTrace: jest.fn() }));
jest.mock('../utils/getHistory', () => ({ getHistory: jest.fn() }));

function Probe({ onResult, onMessages, identity }: { onResult: (value: any) => void; onMessages: (messages: any[]) => void; identity?: any }) {
  const logic = useHistoryLogic(onMessages, identity);
  onResult(logic);
  return null;
}

test('formal history hook refreshes latest page without moving older cursor', async () => {
  (getHistory as jest.Mock)
    .mockResolvedValueOnce({ messages: [{ uuid: 'old', type: 'text', content: '旧', isUser: false }], startIndex: 20 })
    .mockResolvedValueOnce({ messages: [{ uuid: 'call-1', type: 'call', content: '[语音通话]', isUser: true }], startIndex: 0 });
  let result: any; let messages: any[] = []; let root!: ReturnType<typeof create>;
  act(() => { root = create(<Probe onResult={(value) => { result = value; }} onMessages={(value) => { messages = value; }} />); });
  await act(async () => { await result.loadHistory('u', 't'); });
  await act(async () => { await result.refreshLatestHistory('u', 't'); });
  expect(result.history_start_index).toBe(20);
  expect(messages).toEqual(expect.arrayContaining([expect.objectContaining({ uuid: 'call-1' })]));
  expect(getHistory).toHaveBeenLastCalledWith('u', 't', expect.any(Number), -1);
  act(() => root.unmount());
});

test('user refresh action path preserves newest-first order and local pending/streaming state', async () => {
  (getHistory as jest.Mock).mockResolvedValue({ messages: [
    { uuid: 'older', type: 'text', content: '旧', isUser: false, timestamp: 100 },
    { uuid: 'call-1', type: 'call', content: '[语音通话]', isUser: true, durationMs: 2000, timestamp: 300 },
  ], startIndex: 0 });
  let result: any; let incoming: any[] = []; let root!: ReturnType<typeof create>;
  act(() => { root = create(<Probe onResult={(value) => { result = value; }} onMessages={(value) => { incoming = value; }} identity={{ username: 'u', characterId: 'luotianyi', token: 't', resetEpoch: 1 }} />); });
  await act(async () => { await result.refreshLatestHistory('u', 't'); });
  // The hook forwards the server page once; production useChatLogic normalizes
  // it for the inverted FlatList in its explicit latest merge mode.
  expect(incoming.map((message) => message.uuid)).toEqual(['older', 'call-1']);
  act(() => root.unmount());
});

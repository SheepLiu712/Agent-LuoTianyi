import React from 'react';
import { act, create } from 'react-test-renderer';
import { useHistoryLogic } from '../hooks/useHistoryLogic';
import { getHistory } from '../utils/getHistory';
import { mergeHistoryMessages } from '../utils/history_merge';

jest.mock('react-native', () => ({ __esModule: true, Platform: { OS: 'android' } }));
jest.mock('../utils/debug_trace', () => ({ addDebugTrace: jest.fn() }));
jest.mock('../utils/getHistory', () => ({ getHistory: jest.fn() }));
jest.mock('../hooks/useChatLogic', () => ({ mergeHistoryMessages: jest.fn() }));

function Probe({ onResult }: { onResult: (value: any) => void }) {
  const [messages, setMessages] = React.useState<any[]>([]);
  const logic = useHistoryLogic((incoming) => setMessages((previous) => mergeHistoryMessages(previous, incoming)));
  onResult({ ...logic, messages });
  return null;
}

describe('latest call history refresh', () => {
  afterEach(() => jest.clearAllMocks());

  it('refreshes after late settlement, merges one call, and updates an existing call summary', async () => {
    (getHistory as jest.Mock)
      .mockResolvedValueOnce({ messages: [{ uuid: 'old', type: 'text', content: '旧', isUser: false }], startIndex: 0 })
      .mockResolvedValueOnce({ messages: [{ uuid: 'call-1', type: 'call', content: '[语音通话]', isUser: true, callOutcome: 'connected', durationMs: 1000 }], startIndex: 0 })
      .mockResolvedValueOnce({ messages: [{ uuid: 'call-1', type: 'call', content: '[语音通话]', isUser: true, callOutcome: 'connected', durationMs: 2000 }], startIndex: 0 });
    let result: any; let root!: ReturnType<typeof create>;
    act(() => { root = create(<Probe onResult={(value) => { result = value; }} />); });
    await act(async () => { await result.loadHistory('u', 't'); await Promise.resolve(); });
    await act(async () => { await result.refreshLatestHistory('u', 't'); });
    expect(result.messages).toEqual(expect.arrayContaining([expect.objectContaining({ uuid: 'call-1', durationMs: 1000 })]));
    await act(async () => { await result.refreshLatestHistory('u', 't'); });
    expect(result.messages.filter((message: any) => message.uuid === 'call-1')).toHaveLength(1);
    expect(result.messages.find((message: any) => message.uuid === 'call-1').durationMs).toBe(2000);
    expect(getHistory).toHaveBeenLastCalledWith('u', 't', expect.any(Number), -1);
    act(() => root.unmount());
  });

  it('keeps older pagination cursor independent and ignores a superseded refresh response', async () => {
    let resolveRefresh!: (value: any) => void;
    (getHistory as jest.Mock)
      .mockResolvedValueOnce({ messages: [{ uuid: 'old', type: 'text', content: '旧', isUser: false }], startIndex: 20 })
      .mockImplementationOnce(() => new Promise((resolve) => { resolveRefresh = resolve; }));
    let result: any; let root!: ReturnType<typeof create>;
    act(() => { root = create(<Probe onResult={(value) => { result = value; }} />); });
    await act(async () => { await result.loadHistory('u', 't'); await Promise.resolve(); });
    const before = result.history_start_index;
    const pending = result.refreshLatestHistory('u', 't');
    act(() => root.unmount());
    resolveRefresh({ messages: [{ uuid: 'late', type: 'call', content: '[语音通话]', isUser: true }], startIndex: 0 });
    await pending;
    expect(before).toBe(20);
  });

  it('fences a superseded refresh and leaves the current request owner responsible for loading state', async () => {
    let resolveFirst!: (value: any) => void;
    (getHistory as jest.Mock).mockImplementationOnce(() => new Promise((resolve) => { resolveFirst = resolve; }));
    let result: any; let root!: ReturnType<typeof create>;
    act(() => { root = create(<Probe onResult={(value) => { result = value; }} />); });
    const first = result.refreshLatestHistory('u', 't');
    const second = result.refreshLatestHistory('u', 't');
    resolveFirst({ messages: [{ uuid: 'old-refresh', type: 'call', content: '[语音通话]', isUser: true }], startIndex: 0 });
    await first; await second;
    expect(result.historyLoading).toBe(false);
    act(() => root.unmount());
  });

});

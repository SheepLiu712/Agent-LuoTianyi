const mockAppState = { currentState: 'active' };

jest.mock('react-native', () => ({ AppState: mockAppState }));
jest.mock('expo-av', () => ({ Audio: { Sound: jest.fn() } }));
jest.mock('expo-file-system/legacy', () => ({
  documentDirectory: 'file://documents/',
  EncodingType: { Base64: 'base64' },
  makeDirectoryAsync: jest.fn().mockResolvedValue(undefined),
  writeAsStringAsync: jest.fn().mockResolvedValue(undefined),
  getInfoAsync: jest.fn().mockResolvedValue({ exists: true, size: 10 }),
  readAsStringAsync: jest.fn().mockResolvedValue(''),
}));

import * as FileSystem from 'expo-file-system/legacy';
import { AgentBinder } from '../utils/binder';
import { MessageProcessor } from '../utils/message_processor';
import { NetworkClient } from '../utils/network_client';

function fakeBinder() {
  return {
    emitAgentMessage: jest.fn(),
    emitErrorText: jest.fn(),
    emitMessageStatus: jest.fn(),
    emitLocalTtsState: jest.fn(),
  } as unknown as jest.Mocked<AgentBinder>;
}

async function drainIncoming(processor: MessageProcessor) {
  await (processor as unknown as { incomingMessageChain: Promise<void> }).incomingMessageChain;
}

function makeProcessor(feed: Array<[string, boolean]>, binder: jest.Mocked<AgentBinder>, isRecording: () => boolean) {
  return new MessageProcessor(
    {} as NetworkClient,
    binder,
    (base64, isFinal) => feed.push([base64, isFinal]),
    jest.fn(),
    undefined,
    isRecording,
  );
}

describe('MessageProcessor recording gate (AC-15)', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockAppState.currentState = 'active';
    (FileSystem.getInfoAsync as jest.Mock).mockResolvedValue({ exists: true, size: 10 });
  });

  it('does not play server audio while the user is recording but keeps it replayable', async () => {
    const feed: Array<[string, boolean]> = [];
    const binder = fakeBinder();
    const processor = makeProcessor(feed, binder, () => true);

    processor.onAgentMessage({ uuid: 'agent-1', text: '你好', audio: 'AAAA', is_final_package: true } as any);
    await drainIncoming(processor);

    expect(feed).toEqual([]);
    expect(processor.isServerAudioActive()).toBe(false);
    // 文本仍进入历史，音频仍落盘并挂到气泡上供用户手工重放。
    expect(binder.emitAgentMessage).toHaveBeenCalledWith(expect.objectContaining({ uuid: 'agent-1', text: '你好' }));
    expect(binder.emitAgentMessage).toHaveBeenCalledWith(
      expect.objectContaining({ uuid: 'agent-1', audio: expect.stringContaining('agent-1') }),
    );
  });

  it('still feeds server audio when no recording is active', async () => {
    const feed: Array<[string, boolean]> = [];
    const binder = fakeBinder();
    const processor = makeProcessor(feed, binder, () => false);

    processor.onAgentMessage({ uuid: 'agent-2', text: '在的', audio: 'BBBB' } as any);
    await drainIncoming(processor);

    expect(feed).toEqual([['BBBB', false]]);
  });

  it('keeps the priority accounting balanced when recording starts mid-stream', async () => {
    const feed: Array<[string, boolean]> = [];
    const binder = fakeBinder();
    let recording = false;
    const processor = makeProcessor(feed, binder, () => recording);

    processor.onAgentMessage({ uuid: 'agent-3', text: '第一句', audio: 'AAAA' } as any);
    recording = true;
    processor.onAgentMessage({ uuid: 'agent-3', audio: 'BBBB' } as any);
    processor.onAgentMessage({ uuid: 'agent-3', is_final_package: true } as any);
    await drainIncoming(processor);

    // 前一段已经投喂，后半段被抑制；尾包必须清空在线音频优先权，不能让后续句子永久排队。
    expect(feed).toEqual([['AAAA', false]]);
    expect(processor.isServerAudioActive()).toBe(false);
  });
});
describe('MessageProcessor abandons voice uploads cleanly', () => {

});

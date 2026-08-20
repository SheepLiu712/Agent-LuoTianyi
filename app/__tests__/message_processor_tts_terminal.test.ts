const mockAppState = { currentState: 'active' };

jest.mock('react-native', () => ({ AppState: mockAppState }));
jest.mock('expo-av', () => ({ Audio: {} }));
jest.mock('expo-file-system/legacy', () => ({
  documentDirectory: 'file://documents/',
  EncodingType: { Base64: 'base64' },
  makeDirectoryAsync: jest.fn().mockResolvedValue(undefined),
  writeAsStringAsync: jest.fn().mockResolvedValue(undefined),
  getInfoAsync: jest.fn().mockResolvedValue({ exists: false }),
  readAsStringAsync: jest.fn().mockResolvedValue(''),
}));

import * as FileSystem from 'expo-file-system/legacy';
import { AgentBinder } from '../utils/binder';
import {
  canRetryDurableMessage,
  getSendRetryDelayMs,
  MAX_DURABLE_MESSAGE_AGE_MS,
  MAX_DURABLE_RETRY_ATTEMPTS,
  MessageProcessor,
} from '../utils/message_processor';
import { NetworkClient } from '../utils/network_client';


function fakeBinder() {
  return {
    emitAgentMessage: jest.fn(),
    emitErrorText: jest.fn(),
    emitMessageStatus: jest.fn(),
  } as unknown as jest.Mocked<AgentBinder>;
}

async function drainIncoming(processor: MessageProcessor) {
  await (processor as unknown as { incomingMessageChain: Promise<void> }).incomingMessageChain;
}

async function flushAsyncWork() {
  for (let i = 0; i < 6; i += 1) {
    await Promise.resolve();
  }
}

describe('MessageProcessor TTS terminal contract', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockAppState.currentState = 'active';
  });

  it('finishes a zero-chunk error and preserves the server text', async () => {
    const binder = fakeBinder();
    const feedServerAudioChunk = jest.fn();
    const processor = new MessageProcessor(
      {} as NetworkClient,
      binder,
      feedServerAudioChunk,
    );

    processor.onAgentMessage({
      stream_type: 'chat',
      uuid: 'reply-1',
      text: '已经生成的文本',
      audio: '',
      is_final_package: true,
      audio_error: true,
      error_code: 'TTS_EMPTY',
    });
    await drainIncoming(processor);

    expect(feedServerAudioChunk).toHaveBeenCalledTimes(1);
    expect(feedServerAudioChunk).toHaveBeenCalledWith(expect.objectContaining({
      stream_type: 'chat',
      audio_id: 'reply-1',
      audio: '',
      is_final: true,
    }));
    expect(binder.emitAgentMessage).toHaveBeenCalledWith(
      expect.objectContaining({
        uuid: 'reply-1',
        text: '已经生成的文本',
        is_final_package: true,
        audio_error: true,
        error_code: 'TTS_EMPTY',
      }),
    );
  });

  it('finishes after a mid-stream error without saving partial audio', async () => {
    const binder = fakeBinder();
    let processor: MessageProcessor;
    const feedServerAudioChunk = jest.fn((packet: { is_final: boolean }) => {
      if (packet.is_final) {
        processor.onServerAudioFinished();
      }
    });
    processor = new MessageProcessor(
      {} as NetworkClient,
      binder,
      feedServerAudioChunk,
    );

    processor.onAgentMessage({
      stream_type: 'chat',
      uuid: 'reply-2',
      text: '已经生成的文本',
      audio: 'YXVkaW8=',
      is_final_package: false,
    });
    await drainIncoming(processor);
    processor.onAgentMessage({
      stream_type: 'chat',
      uuid: 'reply-2',
      audio: '',
      is_final_package: true,
      audio_error: true,
      error_code: 'TTS_STREAM_ERROR',
    });
    await drainIncoming(processor);

    expect(feedServerAudioChunk.mock.calls.filter((call) => call[0].is_final === true)).toHaveLength(1);
    expect(feedServerAudioChunk).toHaveBeenLastCalledWith(expect.objectContaining({
      stream_type: 'chat',
      audio_id: 'reply-2',
      audio: '',
      is_final: true,
    }));
    expect(FileSystem.writeAsStringAsync).not.toHaveBeenCalled();
    expect(binder.emitAgentMessage).toHaveBeenLastCalledWith(
      expect.objectContaining({
        uuid: 'reply-2',
        is_final_package: true,
        audio_error: true,
        error_code: 'TTS_STREAM_ERROR',
      }),
    );
  });

  it('clears the global audio-playing flag when playback completion times out', async () => {
    jest.useFakeTimers();
    try {
      const processor = new MessageProcessor(
        {} as NetworkClient,
        fakeBinder(),
        jest.fn(),
      );
      (processor as any).serverAudioPlaying = true;

      const completion = (processor as any).waitForServerAudioFinished(25);
      jest.advanceTimersByTime(25);
      await completion;

      expect((processor as any).serverAudioPlaying).toBe(false);
    } finally {
      jest.useRealTimers();
    }
  });

  it('persists complete audio without waiting for playback while backgrounded', async () => {
    mockAppState.currentState = 'background';
    const processor = new MessageProcessor(
      {} as NetworkClient,
      fakeBinder(),
      jest.fn(),
    );

    processor.onAgentMessage({
      stream_type: 'chat',
      uuid: 'reply-background',
      audio: 'YXVkaW8=',
      is_final_package: true,
    });
    await drainIncoming(processor);

    expect(FileSystem.writeAsStringAsync).toHaveBeenCalledTimes(1);
    expect((processor as any).serverAudioPlaying).toBe(false);
  });

  it('plays ephemeral touch audio without persisting it', async () => {
    mockAppState.currentState = 'background';
    const feedServerAudioChunk = jest.fn();
    const processor = new MessageProcessor(
      {} as NetworkClient,
      fakeBinder(),
      feedServerAudioChunk,
    );

    processor.onAgentMessage({
      stream_type: 'chat',
      uuid: 'touch-fast-reply',
      audio: 'dG91Y2gtYXVkaW8=',
      expression: '开心',
      is_final_package: true,
      display_in_chat: false,
      is_ephemeral: true,
    });
    await drainIncoming(processor);

    expect(feedServerAudioChunk).toHaveBeenCalledWith(expect.objectContaining({
      stream_type: 'chat',
      audio_id: 'touch-fast-reply',
      audio: 'dG91Y2gtYXVkaW8=',
      is_final: false,
    }));
    expect(feedServerAudioChunk).toHaveBeenCalledWith(expect.objectContaining({
      stream_type: 'chat',
      audio_id: 'touch-fast-reply',
      audio: '',
      is_final: true,
    }));
    expect(FileSystem.writeAsStringAsync).not.toHaveBeenCalled();
  });

  it('saves later sentences on arrival and displays them after prior playback', async () => {
    const binder = fakeBinder();
    const feedServerAudioChunk = jest.fn();
    const processor = new MessageProcessor(
      {} as NetworkClient,
      binder,
      feedServerAudioChunk,
    );

    processor.onAgentMessage({
      stream_type: 'chat',
      uuid: 'sentence-1',
      text: '第一句',
      expression: '开心',
      audio: 'YXVkaW8tMQ==',
      is_final_package: false,
    });
    await drainIncoming(processor);

    expect(binder.emitAgentMessage).toHaveBeenCalledWith(
      expect.objectContaining({
        uuid: 'sentence-1',
        text: '第一句',
        expression: '开心',
      }),
    );
    expect(feedServerAudioChunk).toHaveBeenCalledWith(expect.objectContaining({
      stream_type: 'chat',
      audio_id: 'sentence-1',
      audio: 'YXVkaW8tMQ==',
      is_final: false,
    }));

    processor.onAgentMessage({
      stream_type: 'chat',
      uuid: 'sentence-1',
      audio: 'YXVkaW8tMg==',
      is_final_package: true,
    });
    processor.onAgentMessage({
      stream_type: 'chat',
      uuid: 'sentence-2',
      text: '第二句',
      expression: '期待',
      audio: 'YXVkaW8tMw==',
      is_final_package: true,
    });
    await flushAsyncWork();

    // 两句话都已完整到达，因此第二句即使尚未展示/播放，也必须已经落盘。
    expect(FileSystem.writeAsStringAsync).toHaveBeenCalledTimes(2);
    const firstSavedBase64 = (FileSystem.writeAsStringAsync as jest.Mock).mock.calls[0][1];
    const secondSavedBase64 = (FileSystem.writeAsStringAsync as jest.Mock).mock.calls[1][1];
    expect(Buffer.from(firstSavedBase64, 'base64').toString('utf8')).toBe('audio-1audio-2');
    expect(Buffer.from(secondSavedBase64, 'base64').toString('utf8')).toBe('audio-3');
    expect(binder.emitAgentMessage).not.toHaveBeenCalledWith(
      expect.objectContaining({ uuid: 'sentence-2' }),
    );

    processor.onServerAudioFinished();
    await flushAsyncWork();

    expect(binder.emitAgentMessage).toHaveBeenCalledWith(
      expect.objectContaining({
        uuid: 'sentence-2',
        text: '第二句',
        expression: '期待',
      }),
    );
    expect(feedServerAudioChunk).toHaveBeenCalledWith(expect.objectContaining({
      stream_type: 'chat',
      audio_id: 'sentence-2',
      audio: 'YXVkaW8tMw==',
      is_final: false,
    }));

    processor.onServerAudioFinished();
    await drainIncoming(processor);
  });
});

test('message retry delay is exponential and capped at 30 seconds', () => {
  expect([0, 1, 2, 3, 4, 5, 8].map(getSendRetryDelayMs)).toEqual([
    1000,
    2000,
    4000,
    8000,
    16000,
    30000,
    30000,
  ]);
});

test('durable retry policy is bounded by attempts and total age', () => {
  const enqueuedAt = 10_000;
  expect(canRetryDurableMessage(0, enqueuedAt, 1000, enqueuedAt)).toBe(true);
  expect(canRetryDurableMessage(MAX_DURABLE_RETRY_ATTEMPTS, enqueuedAt, 1000, enqueuedAt)).toBe(false);
  expect(
    canRetryDurableMessage(0, enqueuedAt, 1000, enqueuedAt + MAX_DURABLE_MESSAGE_AGE_MS - 1000),
  ).toBe(false);
});

describe('MessageProcessor bounded delivery queue', () => {
  function queueItem(overrides: Record<string, unknown>) {
    return {
      clientMsgId: 'msg-1',
      retryAttempt: 0,
      enqueuedAtMs: Date.now(),
      ...overrides,
    };
  }

  it('drops a failed transient event and continues with the next durable message', async () => {
    const network = {
      sendTypingEvent: jest.fn().mockResolvedValue({ ok: false, error: 'disconnected' }),
      sendChat: jest.fn().mockResolvedValue({ ok: true }),
    } as unknown as NetworkClient;
    const binder = fakeBinder();
    const processor = new MessageProcessor(network, binder, jest.fn());
    (processor as any).sendQueue = [
      queueItem({ kind: 'typing', textLength: 3 }),
      queueItem({ kind: 'text', uuid: 'user-1', text: 'hello', clientMsgId: 'msg-2' }),
    ];

    await (processor as any).runSendLoop();

    expect((network as any).sendTypingEvent).toHaveBeenCalledTimes(1);
    expect((network as any).sendChat).toHaveBeenCalledWith('hello', false, 'msg-2');
    expect(processor.queueLength()).toBe(0);
  });

  it('marks an exhausted durable message as DELIVERY_UNCERTAIN', async () => {
    const network = {
      sendChat: jest.fn().mockResolvedValue({ ok: false, error: 'ack timeout' }),
    } as unknown as NetworkClient;
    const binder = fakeBinder();
    const processor = new MessageProcessor(network, binder, jest.fn());
    (processor as any).sendQueue = [queueItem({
      kind: 'text',
      uuid: 'user-2',
      text: 'hello',
      retryAttempt: MAX_DURABLE_RETRY_ATTEMPTS,
    })];

    await (processor as any).runSendLoop();

    expect(binder.emitMessageStatus).toHaveBeenCalledWith('user-2', 'failed');
    expect(binder.emitErrorText).toHaveBeenCalledWith(expect.stringContaining('DELIVERY_UNCERTAIN'));
    expect(processor.queueLength()).toBe(0);
  });
});

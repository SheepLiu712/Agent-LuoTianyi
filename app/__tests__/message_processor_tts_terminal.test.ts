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

describe('MessageProcessor TTS terminal contract', () => {
  beforeEach(() => {
    jest.clearAllMocks();
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
      uuid: 'reply-1',
      text: '已经生成的文本',
      audio: '',
      is_final_package: true,
      audio_error: true,
      error_code: 'TTS_EMPTY',
    });
    await drainIncoming(processor);

    expect(feedServerAudioChunk).toHaveBeenCalledTimes(1);
    expect(feedServerAudioChunk).toHaveBeenCalledWith('', true);
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
    const feedServerAudioChunk = jest.fn((_audio: string, isFinal: boolean) => {
      if (isFinal) {
        processor.onServerAudioFinished();
      }
    });
    processor = new MessageProcessor(
      {} as NetworkClient,
      binder,
      feedServerAudioChunk,
    );

    processor.onAgentMessage({
      uuid: 'reply-2',
      text: '已经生成的文本',
      audio: 'YXVkaW8=',
      is_final_package: false,
    });
    await drainIncoming(processor);
    processor.onAgentMessage({
      uuid: 'reply-2',
      audio: '',
      is_final_package: true,
      audio_error: true,
      error_code: 'TTS_STREAM_ERROR',
    });
    await drainIncoming(processor);

    expect(feedServerAudioChunk.mock.calls.filter((call) => call[1] === true)).toHaveLength(1);
    expect(feedServerAudioChunk).toHaveBeenLastCalledWith('', true);
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

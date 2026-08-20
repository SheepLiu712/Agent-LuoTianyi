const { createLive2DAudioStreamPlayer } = require('../public/live2d/audio_stream_player.js');

class FakeSource {
  onended: (() => void) | null = null;
  startedAt: number | null = null;
  stopped = false;

  connect() {}

  start(at: number) {
    this.startedAt = at;
  }

  stop() {
    this.stopped = true;
    this.onended?.();
  }

  finish() {
    this.onended?.();
  }
}

function createHarness() {
  const sources: FakeSource[] = [];
  const messages: Array<Record<string, unknown>> = [];
  const audioContext = {
    state: 'running',
    currentTime: 0,
    resume: jest.fn().mockResolvedValue(undefined),
    createBuffer: jest.fn((_channels: number, samples: number, sampleRate: number) => ({
      duration: samples / sampleRate,
      getChannelData: () => new Float32Array(samples),
    })),
    createBufferSource: jest.fn(() => {
      const source = new FakeSource();
      sources.push(source);
      return source;
    }),
  };
  const player = createLive2DAudioStreamPlayer({
    audioContext,
    analyser: {},
    postMessage: (message: Record<string, unknown>) => messages.push(message),
    requestFrame: jest.fn(),
    decodeBase64: () => new Uint8Array([0, 0, 0, 0]),
  });
  return { audioContext, messages, player, sources };
}

describe('Live2D audio stream player', () => {
  it('waits for chat playback to end before reporting sentence completion', async () => {
    const { messages, player, sources } = createHarness();

    await player.feed({
      stream_type: 'chat',
      audio_id: 'chat-sentence-1',
      audio: 'cGNt',
      is_final: false,
    });
    await player.feed({
      stream_type: 'chat',
      audio_id: 'chat-sentence-1',
      audio: '',
      is_final: true,
    });

    expect(messages).toEqual([]);
    sources[0].finish();
    expect(messages).toEqual([
      expect.objectContaining({
        type: 'audio_finished',
        stream_type: 'chat',
        audio_id: 'chat-sentence-1',
      }),
    ]);
  });

  it('reports chat interruption even though chat has no call response id', async () => {
    const { messages, player } = createHarness();
    await player.feed({
      stream_type: 'chat',
      audio_id: 'chat-sentence-1',
      audio: 'cGNt',
      is_final: false,
    });

    player.stop({ stream_type: 'chat', reason: 'preempted' });

    expect(messages).toEqual([
      expect.objectContaining({
        type: 'audio_stopped',
        stream_type: 'chat',
        audio_id: 'chat-sentence-1',
        reason: 'preempted',
      }),
    ]);
  });

  it('keeps call identity and drops packets for a cancelled response', async () => {
    const { messages, player } = createHarness();
    await player.feed({
      stream_type: 'call',
      response_id: 'response-1',
      audio_id: 'audio-1',
      audio: 'cGNt',
      is_final: false,
    });

    player.stop({
      stream_type: 'call',
      response_id: 'response-1',
      audio_ids: ['audio-1'],
      reason: 'user_barge_in',
    });
    const latePacket = await player.feed({
      stream_type: 'call',
      response_id: 'response-1',
      audio_id: 'audio-1',
      audio: 'cGNt',
      is_final: true,
    });

    expect(latePacket).toEqual({ accepted: false, reason: 'cancelled_response' });
    expect(messages).toEqual([
      expect.objectContaining({
        type: 'audio_stopped',
        stream_type: 'call',
        response_id: 'response-1',
        audio_id: 'audio-1',
        reason: 'user_barge_in',
      }),
    ]);
  });

  it('stops call playback without touching the independent chat player state', async () => {
    const { messages, player, sources } = createHarness();
    await player.feed({
      stream_type: 'chat',
      audio_id: 'chat-1',
      audio: 'cGNt',
      is_final: true,
    });
    await player.feed({
      stream_type: 'call',
      response_id: 'response-1',
      audio_id: 'call-1',
      audio: 'cGNt',
      is_final: true,
    });

    player.stop({
      stream_type: 'call',
      response_id: 'response-1',
      audio_ids: ['call-1'],
      reason: 'user_barge_in',
    });

    expect(sources[0].stopped).toBe(false);
    expect(sources[1].stopped).toBe(true);
    expect(messages).toEqual([
      expect.objectContaining({
        type: 'audio_stopped',
        stream_type: 'call',
        audio_id: 'call-1',
      }),
    ]);

    sources[0].finish();
    expect(messages[1]).toEqual(expect.objectContaining({
      type: 'audio_finished',
      stream_type: 'chat',
      audio_id: 'chat-1',
    }));
  });
});

jest.mock('expo-file-system/legacy', () => ({ getInfoAsync: jest.fn().mockResolvedValue({ exists: false }) }));
jest.mock('../config', () => ({ server_config: { BASE_URL: 'http://localhost:60030' } }));

import { getHistory } from '../utils/getHistory';

describe('audio history mapping', () => {
  it('maps duration, availability, and placeholder text for audio messages', async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        start_index: 0,
        history: [{ uuid: 'audio-1', type: 'audio', source: 'user', duration_ms: 1234, audio_available: false }],
      }),
    }) as unknown as typeof fetch;

    await expect(getHistory('alice', 'token', 20, 0)).resolves.toMatchObject({
      startIndex: 0,
      messages: [{
        uuid: 'audio-1',
        type: 'audio',
        content: '[语音消息]',
        durationMs: 1234,
        audioAvailable: false,
        audioPlayState: 'idle',
      }],
    });
  });
});

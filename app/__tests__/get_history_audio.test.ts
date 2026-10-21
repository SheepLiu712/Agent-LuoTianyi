import { getHistory, mapHistoryMessage } from '../utils/getHistory';

jest.mock('expo-file-system/legacy', () => ({ getInfoAsync: jest.fn().mockResolvedValue({ exists: false }) }));
jest.mock('../config', () => ({ server_config: { BASE_URL: 'http://localhost:60030' } }));

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

it('maps the HTTP call projection into the history bubble DTO', async () => {
  global.fetch = jest.fn().mockResolvedValue({ ok: true, json: async () => ({ start_index: 0, history: [
    { uuid: 'call-1', call_id: 'stable-call', type: 'call', source: 'user', outcome: 'connected', active_duration_ms: 323000 },
    { uuid: 'call-2', type: 'call', source: 'user', outcome: 'cancelled_before_answer', active_duration_ms: 0 },
    { uuid: 'call-3', type: 'call', source: 'user', outcome: 'declined', active_duration_ms: 0 },
  ] }) }) as unknown as typeof fetch;
  await expect(getHistory('alice', 'token', 20, 0)).resolves.toMatchObject({ messages: [
    { type: 'call', callId: 'stable-call', callOutcome: 'connected', durationMs: 323000 },
    { type: 'call', callOutcome: 'cancelled', durationMs: 0 },
    { type: 'call', callOutcome: 'declined', durationMs: 0 },
  ] });
  expect(mapHistoryMessage({ type: 'call', source: 'user', outcome: 'failed' }).callOutcome).toBeUndefined();
});

jest.mock('react-native', () => ({
  AppState: {
    addEventListener: jest.fn(() => ({ remove: jest.fn() })),
  },
}));

import { CallTransport } from '../utils/call_transport';
import { WSEventType } from '../types/ws_events';

function createTransport() {
  const transport = new CallTransport('user', 'token', {
    onEvent: jest.fn(),
    onStatus: jest.fn(),
    onError: jest.fn(),
  });
  (transport as any).callId = 'call-1';
  (transport as any).isStopped = false;
  (transport as any).status = 'active';
  return transport;
}

describe('CallTransport playback acknowledgement', () => {
  it('sends playback completion through the acknowledged transport path', async () => {
    const transport = createTransport();
    const sendWithAck = jest.fn().mockResolvedValue({ ok: true, request_id: 'ack-1' });
    (transport as any).sendWithAck = sendWithAck;

    await transport.playbackCompleted('audio-1', 'response-1');

    expect(sendWithAck).toHaveBeenCalledWith(
      WSEventType.CALL_PLAYBACK_COMPLETED,
      {
        call_id: 'call-1',
        audio_id: 'audio-1',
        response_id: 'response-1',
      },
      5000,
      expect.stringContaining('call-playback-completed-audio-1'),
    );
  });

  it('keeps the interruption reason and retries with one idempotency key', async () => {
    const transport = createTransport();
    const sendWithAck = jest.fn()
      .mockResolvedValueOnce({ ok: false, request_id: 'ack-1', error: 'disconnected' })
      .mockResolvedValueOnce({ ok: true, request_id: 'ack-1' });
    (transport as any).sendWithAck = sendWithAck;

    const result = await transport.playbackStopped('audio-1', 'response-1', 'user_barge_in');

    expect(result.ok).toBe(true);
    expect(sendWithAck).toHaveBeenCalledTimes(2);
    expect(sendWithAck.mock.calls[0][1]).toEqual({
      call_id: 'call-1',
      audio_id: 'audio-1',
      response_id: 'response-1',
      reason: 'user_barge_in',
    });
    expect(sendWithAck.mock.calls[1][3]).toBe(sendWithAck.mock.calls[0][3]);
  });
});

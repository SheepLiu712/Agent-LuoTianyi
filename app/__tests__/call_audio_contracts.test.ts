import { canStartRealtimeAudio } from '../utils/call_audio_contracts';

describe('call audio capability boundary', () => {
  it.each(['unresolved', 'unavailable'] as const)('does not start real-time audio while %s', (capability) => {
    expect(canStartRealtimeAudio(capability)).toBe(false);
  });

  it('allows the later native audio adapter to start only after availability is confirmed', () => {
    expect(canStartRealtimeAudio('available')).toBe(true);
  });
});

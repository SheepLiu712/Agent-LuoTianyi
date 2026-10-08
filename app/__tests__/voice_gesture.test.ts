import { voiceStateForMove } from '../utils/voice_gesture';

describe('voice gesture state', () => {
  it('enters cancel zone at 80dp and recovers when moved back', () => {
    expect(voiceStateForMove('Recording', 200, 120)).toBe('CancelZone');
    expect(voiceStateForMove('CancelZone', 200, 121)).toBe('Recording');
    expect(voiceStateForMove('CancelZone', 200, 120)).toBe('CancelZone');
  });

  it('leaves non-recording states unchanged', () => {
    expect(voiceStateForMove('TextMode', 200, 0)).toBe('TextMode');
    expect(voiceStateForMove('VoiceReady', 200, 0)).toBe('VoiceReady');
    expect(voiceStateForMove('Uploading', 200, 0)).toBe('Uploading');
  });
});

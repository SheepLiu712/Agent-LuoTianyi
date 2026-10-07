import { formatVoiceDuration, voiceBubbleWidth } from '../utils/voice_gesture';

describe('voice duration formatting and bubble sizing', () => {
  it.each([
    [0, `1''`], [500, `1''`], [1000, `1''`], [1100, `2''`],
    [15000, `15''`], [29100, `30''`], [30000, `30''`], [30500, `30''`],
  ])('formats %ims as %s', (durationMs, expected) => {
    expect(formatVoiceDuration(durationMs)).toBe(expected);
  });

  it('linearly interpolates width and clamps the endpoints', () => {
    expect(voiceBubbleWidth(0)).toBe(76);
    expect(voiceBubbleWidth(1000)).toBe(76);
    expect(voiceBubbleWidth(15000)).toBeCloseTo(76 + 14 * (124 / 29));
    expect(voiceBubbleWidth(30000)).toBe(200);
    expect(voiceBubbleWidth(30500)).toBe(200);
  });
});

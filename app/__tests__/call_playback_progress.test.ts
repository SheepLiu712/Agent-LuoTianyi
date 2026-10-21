import { createCallMouthBridge } from '../utils/call_audio/playback_progress';

describe('call playback visual bridge', () => {
  it('injects only a bounded numeric RMS value and never audio payload', () => {
    const inject = jest.fn();
    const bridge = createCallMouthBridge(inject);

    bridge.update(4);
    bridge.update(Number.NaN);

    expect(inject.mock.calls.map(([code]) => code)).toEqual([
      'window.setCallMouthRms(1); true;',
      'window.setCallMouthRms(0); true;',
    ]);
    expect(inject.mock.calls.join('')).not.toContain('base64');
  });

  it('isolates WebView injection failures and resets visually', () => {
    const bridge = createCallMouthBridge(() => { throw new Error('webview gone'); });
    expect(() => bridge.update(0.2)).not.toThrow();
    expect(() => bridge.reset()).not.toThrow();
  });

  it('uses distinct reset and RMS=0 commands and shares the chat analysis duration', () => {
    const inject = jest.fn();
    const bridge = createCallMouthBridge(inject);
    const window = jest.fn();
    const unsubscribe = bridge.subscribeAnalysisWindow!(window);
    bridge.configureAnalysisWindow(44_100, 128);
    expect(window).toHaveBeenLastCalledWith(128 / 44_100);
    bridge.configureAnalysisWindow(Number.NaN, 128);
    expect(window).toHaveBeenCalledTimes(2);
    bridge.update(0);
    bridge.reset();
    expect(inject.mock.calls.map(([code]) => code)).toEqual([
      'window.setCallMouthRms(0); true;', 'window.resetCallMouth(); true;',
    ]);
    unsubscribe();
    bridge.configureAnalysisWindow(48_000, 128);
    expect(window).toHaveBeenCalledTimes(2);
  });
});

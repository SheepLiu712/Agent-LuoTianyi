import React from 'react';
import { act, create, ReactTestRenderer } from 'react-test-renderer';
import { AppState, GestureResponderEvent } from 'react-native';
import { useVoiceInput } from '../hooks/useVoiceInput';
import { showMicrophoneSettings } from '../utils/voice_permission';
jest.mock('react-native', () => ({ AppState: { addEventListener: jest.fn(() => ({ remove: jest.fn() })) } }));
jest.mock('expo-haptics', () => ({ impactAsync: jest.fn().mockResolvedValue(undefined), ImpactFeedbackStyle: { Medium: 'medium' } }));
jest.mock('../utils/voice_recorder', () => ({ voiceRecorder: {} }));
jest.mock('../utils/voice_permission', () => ({ showMicrophoneSettings: jest.fn() }));
const event = { nativeEvent: { pageY: 200 } } as GestureResponderEvent;
let tree: ReactTestRenderer;
let state: ReturnType<typeof useVoiceInput>;
let active: boolean;
let options: any;
function Harness() { state = useVoiceInput({ ...options, active }); return null; }
const mount = async () => {
  await act(async () => { tree = create(<Harness />); });
  await act(async () => { state.toggleMode(); });
};
beforeEach(() => {
  jest.clearAllMocks(); active = true;
  options = {
    recorder: { getPermission: jest.fn().mockResolvedValue('granted'), requestPermission: jest.fn().mockResolvedValue('granted'),
      start: jest.fn().mockResolvedValue({ recordingId: 'one', localUri: 'file://one.m4a' }),
      cancel: jest.fn().mockResolvedValue(undefined), stop: jest.fn().mockResolvedValue({ localUri: 'file://one.m4a', durationMs: 1000 }) },
    onRecordingStarted: jest.fn(), onRecordingCancelled: jest.fn(), onRecordingCommitted: jest.fn(),
    onStopAllAudio: jest.fn().mockResolvedValue(undefined), onRecordingEnded: jest.fn(), onNotice: jest.fn(),
  };
});
afterEach(async () => { await act(async () => tree?.unmount()); });
async function endCapture(end: string) {
  await act(async () => {
    if (end === 'release') await state.pressOut();
    if (end === 'background') (AppState.addEventListener as jest.Mock).mock.calls[0][1]('background');
    if (end === 'navigation') { active = false; tree.update(<Harness />); }
    if (end === 'unmount') tree.unmount();
  });
}
it.each(['permission', 'playback', 'native'].flatMap((phase) => ['release', 'background', 'navigation', 'unmount'].map((end) => [phase, end])))
('invalidates startup during %s after %s', async (phase, end) => {
  let finish!: (value: any) => void;
  const gate = new Promise((resolve) => { finish = resolve; });
  const method = phase === 'permission' ? options.recorder.getPermission : phase === 'playback' ? options.onStopAllAudio : options.recorder.start;
  method.mockReturnValueOnce(gate);
  await mount(); let pending!: Promise<void>;
  await act(async () => { pending = state.pressIn(event); });
  expect(state.captureState).toBe('Starting');
  await act(async () => { state.toggleMode(); await state.pressIn(event); });
  expect(state.mode).toBe('voice');
  await endCapture(end);
  await act(async () => { finish(phase === 'permission' ? 'granted' : { recordingId: 'late' }); await pending; });
  expect(options.onRecordingStarted).not.toHaveBeenCalled();
  expect(options.onRecordingCommitted).not.toHaveBeenCalled();
  expect(options.onRecordingCancelled).not.toHaveBeenCalled();
  expect(options.recorder.cancel).toHaveBeenCalled();
  if (end !== 'unmount') expect(state.captureState).toBe('VoiceReady');
});
it.each(['native', 'background', 'navigation', 'unmount'])('cancels active recording once on %s', async (end) => {
  await mount(); await act(async () => { await state.pressIn(event); });
  if (end === 'native') await act(async () => { const notify = options.recorder.start.mock.calls[0][0].onInterrupted; notify(); notify(); });
  else await endCapture(end);
  expect(options.onRecordingCancelled).toHaveBeenCalledTimes(1);
  expect(options.onRecordingCancelled.mock.calls[0][0]).toBe('one');
  expect(options.recorder.cancel).toHaveBeenCalledTimes(1);
  expect(options.onRecordingCommitted).not.toHaveBeenCalled();
});
it.each(['blocked', 'denied'])('handles %s permission without starting, and rechecks on next press', async (permission) => {
  options.recorder.getPermission.mockResolvedValueOnce(permission);
  await mount(); await act(async () => { await state.pressIn(event); });
  if (permission === 'blocked') expect(showMicrophoneSettings).toHaveBeenCalledTimes(1);
  else expect(options.recorder.requestPermission).toHaveBeenCalledTimes(1);
  expect(options.recorder.start).not.toHaveBeenCalled();
  expect(options.onRecordingStarted).not.toHaveBeenCalled();
  expect(options.onStopAllAudio).not.toHaveBeenCalled();
  expect(state.captureState).toBe('VoiceReady');
  await act(async () => { await state.pressIn(event); });
  expect(options.recorder.getPermission).toHaveBeenCalledTimes(2);
  expect(state.captureState).toBe('Recording');
});

it.each([499, 500])('applies the minimum duration boundary at %ims', async (duration) => {
  jest.useFakeTimers({ now: 1000 });
  try {
    await mount(); await act(async () => { await state.pressIn(event); });
    await act(async () => { await jest.advanceTimersByTimeAsync(duration); await state.pressOut(); });
    if (duration < 500) {
      expect(options.onRecordingCancelled).toHaveBeenCalledWith('one', 'too_short');
      expect(options.onRecordingCommitted).not.toHaveBeenCalled();
      expect(options.onNotice).toHaveBeenCalledWith('说话时间太短');
    } else {
      expect(options.onRecordingCommitted).toHaveBeenCalledTimes(1);
      expect(options.onRecordingCancelled).not.toHaveBeenCalled();
    }
  } finally { jest.useRealTimers(); }
});

it.each([false, true])('30s forces a single end with cancel zone=%s', async (cancelZone) => {
  jest.useFakeTimers({ now: 1000 });
  options.recorder.stop.mockResolvedValue({ localUri: 'file://one.m4a', durationMs: 30100 });
  try {
    await mount(); await act(async () => { await state.pressIn(event); });
    if (cancelZone) await act(async () => { state.pressMove({ nativeEvent: { pageY: 100 } } as GestureResponderEvent); });
    await act(async () => { await jest.advanceTimersByTimeAsync(30100); await state.pressOut(); });
    expect(state.elapsedMs).toBeLessThanOrEqual(30000);
    if (cancelZone) {
      expect(options.onRecordingCancelled).toHaveBeenCalledTimes(1);
      expect(options.onRecordingCommitted).not.toHaveBeenCalled();
    } else {
      expect(options.onRecordingCommitted).toHaveBeenCalledWith({ uploadId: 'one', localUri: 'file://one.m4a', durationMs: 30000 });
      expect(options.recorder.stop).toHaveBeenCalledTimes(1);
    }
  } finally { jest.useRealTimers(); }
});

it('smooths/clamps metering and restores send after moving back from cancel zone', async () => {
  await mount(); await act(async () => { await state.pressIn(event); });
  const onMetering = options.recorder.start.mock.calls[0][0].onMetering;
  await act(async () => { onMetering(20); });
  expect(state.smoothedMeter).toBeCloseTo(0.3);
  await act(async () => { onMetering(-100); });
  expect(state.smoothedMeter).toBeCloseTo(0.21);
  await act(async () => { state.pressMove({ nativeEvent: { pageY: 120 } } as GestureResponderEvent); });
  expect(state.captureState).toBe('CancelZone');
  await act(async () => { state.pressMove({ nativeEvent: { pageY: 121 } } as GestureResponderEvent); });
  expect(state.captureState).toBe('Recording');
});

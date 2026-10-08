import React from 'react';
import { act, create, ReactTestRenderer } from 'react-test-renderer';
import { GestureResponderEvent } from 'react-native';
import { useVoiceInput } from '../hooks/useVoiceInput';
import { voiceRecorder } from '../utils/voice_recorder';

jest.mock('react-native', () => ({
  AppState: { addEventListener: jest.fn(() => ({ remove: jest.fn() })) },
}));
jest.mock('expo-haptics', () => ({ impactAsync: jest.fn().mockResolvedValue(undefined), ImpactFeedbackStyle: { Medium: 'medium' } }));
jest.mock('../utils/voice_recorder', () => ({ voiceRecorder: {
  getPermission: jest.fn().mockResolvedValue('granted'),
  requestPermission: jest.fn(),
  start: jest.fn(),
  stop: jest.fn(),
  cancel: jest.fn().mockResolvedValue(undefined),
  dispose: jest.fn().mockResolvedValue(undefined),
} }));

const event = { nativeEvent: { pageY: 200 } } as GestureResponderEvent;

function makeHarness() {
  let hooks!: ReturnType<typeof useVoiceInput>;
  let root!: ReactTestRenderer;
  const callbacks = {
    onRecordingStarted: jest.fn(),
    onRecordingCancelled: jest.fn(),
    onRecordingCommitted: jest.fn(),
    onStopAllAudio: jest.fn().mockResolvedValue(undefined),
    onNotice: jest.fn(),
  };
  function Harness() { hooks = useVoiceInput({ ...callbacks, recorder: voiceRecorder }); return null; }
  return {
    callbacks,
    get hooks() { return hooks; },
    mount: async () => { await act(async () => { root = create(<Harness />); }); },
    unmount: async () => { await act(async () => { root.unmount(); }); },
  };
}

describe('voice input guardrails', () => {
  let now: jest.SpyInstance;
  beforeEach(() => {
    jest.clearAllMocks();
    // clearAllMocks 不清实现：上一条用例设置的权限/返回值必须显式复位，否则会跨用例泄漏。
    (voiceRecorder.getPermission as jest.Mock).mockResolvedValue('granted');
    (voiceRecorder.requestPermission as jest.Mock).mockReset();
    (voiceRecorder.start as jest.Mock).mockReset();
    (voiceRecorder.stop as jest.Mock).mockReset();
    (voiceRecorder.cancel as jest.Mock).mockResolvedValue(undefined);
    (voiceRecorder.dispose as jest.Mock).mockResolvedValue(undefined);
    now = jest.spyOn(Date, 'now').mockReturnValue(1000);
  });
  afterEach(() => { now.mockRestore(); });

  // 启动窗口与中断路径（release/background/navigation/unmount/权限）由 voice_lifecycle 锁定；
  // 这里只锁 base 尚未覆盖的一条：recorder.stop() 抛错不得永久锁死 finishing，且必须发 recording_failed。
  it('recovers the state machine when recorder.stop throws', async () => {
    (voiceRecorder.start as jest.Mock).mockResolvedValueOnce({ recordingId: 'uuid-4', localUri: 'file://r.m4a' });
    (voiceRecorder.stop as jest.Mock).mockRejectedValueOnce(new Error('save failed'));
    const harness = makeHarness();
    await harness.mount();
    await act(async () => { harness.hooks.toggleMode(); });
    await act(async () => { await harness.hooks.pressIn(event); });
    expect(harness.hooks.captureState).toBe('Recording');
    now.mockReturnValue(2000);

    await act(async () => { await harness.hooks.pressOut(); });

    expect(harness.callbacks.onNotice).toHaveBeenCalledWith('录音保存失败，请重试');
    expect(harness.callbacks.onRecordingCancelled).toHaveBeenCalledWith('uuid-4', 'recording_failed');
    expect(harness.callbacks.onRecordingCommitted).not.toHaveBeenCalled();
    expect(harness.hooks.captureState).toBe('VoiceReady');

    // 恢复后必须能立刻再次录音（finishing 不残留）。
    (voiceRecorder.start as jest.Mock).mockResolvedValueOnce({ recordingId: 'uuid-5', localUri: 'file://r.m4a' });
    await act(async () => { await harness.hooks.pressIn(event); });
    expect(harness.hooks.captureState).toBe('Recording');
    await harness.unmount();
  });
});

import React from 'react';
import { act, create, ReactTestRenderer } from 'react-test-renderer';
import { AppState, GestureResponderEvent } from 'react-native';
import { useVoiceInput } from '../hooks/useVoiceInput';
import { MICROPHONE_AMBIGUOUS_MESSAGE, MICROPHONE_DENIED_NOTICE, MICROPHONE_PENDING_MESSAGE, PERMISSION_STUCK_AFTER_MS, showMicrophoneSettings } from '../utils/voice_permission';
jest.mock('react-native', () => ({ AppState: { addEventListener: jest.fn(() => ({ remove: jest.fn() })) } }));
jest.mock('expo-haptics', () => ({ impactAsync: jest.fn().mockResolvedValue(undefined), ImpactFeedbackStyle: { Medium: 'medium' } }));
jest.mock('../utils/voice_recorder', () => ({ voiceRecorder: {} }));
jest.mock('../utils/voice_permission', () => ({
  showMicrophoneSettings: jest.fn(),
  MICROPHONE_AMBIGUOUS_MESSAGE: '未获得麦克风权限，请再按住一次。',
  MICROPHONE_PENDING_MESSAGE: '上一次权限请求还没结束。',
  MICROPHONE_DENIED_NOTICE: { title: '未能获得麦克风权限', message: '再次尝试仍未获得麦克风权限，请到系统设置检查是否被禁止。' },
  MICROPHONE_RETRIES_BEFORE_SETTINGS: 2,
  PERMISSION_STUCK_AFTER_MS: 8000,
}));
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
it.each(['blocked', 'denied'])('requests again for initially %s permission without starting, and rechecks on next press', async (permission) => {
  options.recorder.getPermission.mockResolvedValueOnce(permission);
  await mount(); await act(async () => { await state.pressIn(event); });
  expect(options.recorder.requestPermission).toHaveBeenCalledTimes(1);
  expect(showMicrophoneSettings).not.toHaveBeenCalled();
  expect(options.recorder.start).not.toHaveBeenCalled();
  expect(options.onRecordingStarted).not.toHaveBeenCalled();
  expect(options.onStopAllAudio).not.toHaveBeenCalled();
  expect(state.captureState).toBe('VoiceReady');
  await act(async () => { await state.pressIn(event); });
  expect(options.recorder.getPermission).toHaveBeenCalledTimes(2);
  expect(state.captureState).toBe('Recording');
});

it.each(['granted', 'blocked'])('releases the input bar while the system permission request is pending (late %s)', async (late) => {
  let answer!: (value: string) => void;
  options.recorder.getPermission.mockResolvedValueOnce('denied').mockResolvedValueOnce('denied');
  options.recorder.requestPermission.mockReturnValueOnce(new Promise((resolve) => { answer = resolve; }));
  await mount();
  await act(async () => { await state.pressIn(event); await state.pressOut(); });
  // 授权请求还没返回（授权框没弹出或被系统吞掉）时，输入栏不能一直停在禁用态。
  expect(options.recorder.requestPermission).toHaveBeenCalledTimes(1);
  expect(state.captureState).toBe('VoiceReady');
  expect(options.onRecordingEnded).toHaveBeenCalledTimes(1);
  // 请求仍在途时再按：不叠加第二个系统请求，只给非模态“处理中”提示，不弹设置对话框。
  await act(async () => { await state.pressIn(event); });
  expect(options.recorder.requestPermission).toHaveBeenCalledTimes(1);
  expect(options.onNotice).toHaveBeenCalledWith(MICROPHONE_PENDING_MESSAGE);
  expect(showMicrophoneSettings).not.toHaveBeenCalled();
  expect(state.captureState).toBe('VoiceReady');
  // 迟到的授权结果不开始录音、不改状态；这次尝试已被更晚的按住取代，不追加提示。
  await act(async () => { answer(late); });
  expect(options.recorder.start).not.toHaveBeenCalled();
  expect(state.captureState).toBe('VoiceReady');
  expect(options.onNotice).toHaveBeenCalledTimes(1);
  expect(showMicrophoneSettings).not.toHaveBeenCalled();
  // 授权之后重新按住即可录音。
  await act(async () => { await state.pressIn(event); });
  expect(state.captureState).toBe('Recording');
});

it('reports a failed permission request instead of swallowing it', async () => {
  options.recorder.getPermission.mockResolvedValueOnce('denied');
  options.recorder.requestPermission.mockRejectedValueOnce(new Error('native permission request failed'));
  await mount();
  await act(async () => { await state.pressIn(event); });

  // 请求失败必须给用户可行动提示，且不得开始录音、不得改动输入栏状态。
  expect(options.recorder.start).not.toHaveBeenCalled();
  expect(options.recorder.requestPermission).toHaveBeenCalledTimes(1);
  expect(options.onNotice).toHaveBeenCalledWith('录音启动失败，请重试');
  expect(showMicrophoneSettings).not.toHaveBeenCalled();
  expect(state.captureState).toBe('VoiceReady');
  // 之后再按住仍可正常走授权/录音流程。
  options.recorder.getPermission.mockResolvedValueOnce('granted');
  await act(async () => { await state.pressIn(event); });
  expect(state.captureState).toBe('Recording');
});

it('does not auto-open the settings dialog on the first blocked result', async () => {
  let answer!: (value: string) => void;
  options.recorder.getPermission.mockResolvedValueOnce('denied');
  options.recorder.requestPermission.mockReturnValueOnce(new Promise((resolve) => { answer = resolve; }));
  await mount();
  await act(async () => { await state.pressIn(event); await state.pressOut(); });
  await act(async () => { answer('blocked'); });

  // 第一次未授权：只给非模态提示，不擅自升级成“永久拒绝/去设置”。
  expect(options.onNotice).toHaveBeenCalledWith(MICROPHONE_AMBIGUOUS_MESSAGE);
  expect(showMicrophoneSettings).not.toHaveBeenCalled();
  expect(options.recorder.start).not.toHaveBeenCalled();
  expect(state.captureState).toBe('VoiceReady');
});

it('offers the settings dialog after consecutive blocked results', async () => {
  options.recorder.getPermission.mockResolvedValue('denied');
  options.recorder.requestPermission.mockResolvedValue('blocked');
  await mount();

  await act(async () => { await state.pressIn(event); await state.pressOut(); });
  expect(showMicrophoneSettings).not.toHaveBeenCalled();

  await act(async () => { await state.pressIn(event); await state.pressOut(); });

  // 连续两次仍未授权：给出设置入口（永久拒绝的用户重试一次即可看到）。
  expect(showMicrophoneSettings).toHaveBeenCalledTimes(1);
  expect(showMicrophoneSettings).toHaveBeenCalledWith(expect.any(Function), MICROPHONE_DENIED_NOTICE);
  expect(options.recorder.start).not.toHaveBeenCalled();
  expect(state.captureState).toBe('VoiceReady');
});

it('resets the consecutive-failure count once permission is granted', async () => {
  options.recorder.getPermission.mockResolvedValue('denied');
  options.recorder.requestPermission.mockResolvedValue('blocked');
  options.recorder.getPermission
    .mockResolvedValueOnce('denied')    // 第一次：未授权 → 非模态
    .mockResolvedValueOnce('granted')   // 第二次：授权成功 → 计数清零
    .mockResolvedValueOnce('denied');   // 第三次：又未授权，但应重新从第一次算
  await mount();

  await act(async () => { await state.pressIn(event); await state.pressOut(); });
  expect(showMicrophoneSettings).not.toHaveBeenCalled();

  await act(async () => { await state.pressIn(event); await state.pressOut(); });
  expect(options.recorder.start).toHaveBeenCalledTimes(1);
  expect(state.captureState).toBe('VoiceReady');

  await act(async () => { await state.pressIn(event); await state.pressOut(); });

  // 授权成功已把计数清零，所以这次未授权仍只是第一次，不弹设置。
  expect(showMicrophoneSettings).not.toHaveBeenCalled();
});

it('offers the settings entry only after the pending request stays outstanding', async () => {
  let answer!: (value: string) => void;
  const nowSpy = jest.spyOn(Date, 'now');
  nowSpy.mockReturnValue(1_000_000);
  options.recorder.getPermission
    .mockResolvedValueOnce('denied')
    .mockResolvedValueOnce('denied')
    .mockResolvedValueOnce('denied');
  options.recorder.requestPermission.mockReturnValueOnce(new Promise((resolve) => { answer = resolve; }));
  try {
    await mount();
    await act(async () => { await state.pressIn(event); await state.pressOut(); });

    // 还没到阈值：只提示“处理中”，不弹设置对话框。
    nowSpy.mockReturnValue(1_000_000 + PERMISSION_STUCK_AFTER_MS - 1);
    await act(async () => { await state.pressIn(event); });
    expect(showMicrophoneSettings).not.toHaveBeenCalled();
    expect(options.recorder.requestPermission).toHaveBeenCalledTimes(1);

    // 超过阈值：给出设置出口，且始终不叠加第二个系统请求。
    nowSpy.mockReturnValue(1_000_000 + PERMISSION_STUCK_AFTER_MS);
    await act(async () => { await state.pressIn(event); });
    expect(showMicrophoneSettings).toHaveBeenCalledTimes(1);
    expect(options.recorder.requestPermission).toHaveBeenCalledTimes(1);
  } finally {
    nowSpy.mockRestore();
    await act(async () => { answer('granted'); });
  }
});

it('does not post a late permission notice after switching back to text mode', async () => {
  let answer!: (value: string) => void;
  options.recorder.getPermission.mockResolvedValueOnce('denied');
  options.recorder.requestPermission.mockReturnValueOnce(new Promise((resolve) => { answer = resolve; }));
  await mount();
  await act(async () => { await state.pressIn(event); });
  await act(async () => { state.toggleMode(); });
  expect(state.mode).toBe('text');

  await act(async () => { answer('blocked'); });

  expect(options.onNotice).not.toHaveBeenCalled();
  expect(showMicrophoneSettings).not.toHaveBeenCalled();
});

it('ignores a permission failure that arrives after a newer attempt', async () => {
  let rejectRequest!: (error: Error) => void;
  options.recorder.getPermission.mockResolvedValueOnce('denied');
  options.recorder.requestPermission.mockReturnValueOnce(
    new Promise((_resolve, rejectIt) => { rejectRequest = rejectIt; }),
  );
  await mount();
  // 第一次按住：进入授权请求并立刻释放输入栏。
  await act(async () => { await state.pressIn(event); });
  expect(state.captureState).toBe('VoiceReady');
  // 第二次按住：权限已可用，开始较新的录音。
  await act(async () => { await state.pressIn(event); });
  expect(state.captureState).toBe('Recording');
  // 旧请求这时才失败：不得用系统提示打扰正在进行的录音，也不得改动状态。
  await act(async () => { rejectRequest(new Error('late permission failure')); });
  expect(options.onNotice).not.toHaveBeenCalled();
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

import React from 'react';
import { act, create, ReactTestRenderer } from 'react-test-renderer';
import { AppState, GestureResponderEvent } from 'react-native';
import { useVoiceInput } from '../hooks/useVoiceInput';
import { subscribeVoiceHostStopped } from '../utils/voice_host_lifecycle';
jest.mock('react-native', () => ({ AppState: { addEventListener: jest.fn(() => ({ remove: jest.fn() })) } }));
jest.mock('expo-haptics', () => ({ impactAsync: jest.fn().mockResolvedValue(undefined), ImpactFeedbackStyle: { Medium: 'medium' } }));
jest.mock('../utils/voice_recorder', () => ({ voiceRecorder: {} }));
jest.mock('../utils/voice_host_lifecycle', () => ({ subscribeVoiceHostStopped: jest.fn(() => ({ remove: jest.fn() })) }));
const event = { nativeEvent: { pageY: 200 } } as GestureResponderEvent;
let tree: ReactTestRenderer;
let state: ReturnType<typeof useVoiceInput>;
let options: any;
function Harness() { state = useVoiceInput(options); return null; }
const mount = async () => {
  await act(async () => { tree = create(<Harness />); });
  await act(async () => { state.toggleMode(); });
};
beforeEach(() => {
  jest.clearAllMocks();
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
    if (end === 'unmount') tree.unmount();
  });
}
it.each(['permission', 'playback', 'native'].flatMap((phase) => ['release', 'background', 'unmount'].map((end) => [phase, end])))
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
it.each(['native', 'background', 'unmount'])('cancels active recording once on %s', async (end) => {
  await mount(); await act(async () => { await state.pressIn(event); });
  if (end === 'native') await act(async () => { const notify = options.recorder.start.mock.calls[0][0].onInterrupted; notify(); notify(); });
  else await endCapture(end);
  expect(options.onRecordingCancelled).toHaveBeenCalledTimes(1);
  expect(options.onRecordingCancelled.mock.calls[0][0]).toBe('one');
  expect(options.recorder.cancel).toHaveBeenCalledTimes(1);
  expect(options.onRecordingCommitted).not.toHaveBeenCalled();
});
const deniedText = '未获得麦克风权限，可重新按住再试';
const permissionErrorText = '无法获取麦克风权限状态，请重新按住再试。';
const press = () => act(async () => { await state.pressIn(event); });

it.each(['denied', 'error'])('松手后初始查询才返回 %s，仍在原界面处理权限且不录音', async result => {
  let settle!: () => void;
  options.recorder.getPermission.mockReturnValueOnce(new Promise((resolve, reject) => {
    settle = () => result === 'denied' ? resolve('denied') : reject(new Error('query failed'));
  }));
  options.recorder.requestPermission.mockResolvedValue('denied');
  await mount();
  let pressing!: Promise<void>;
  await act(async () => { pressing = state.pressIn(event); });
  await act(async () => { await state.pressOut(); });
  await act(async () => { settle(); await pressing; });
  expect(state.permissionNotice?.message).toBe(result === 'denied' ? deniedText : permissionErrorText);
  expect(options.recorder.requestPermission).toHaveBeenCalledTimes(result === 'denied' ? 1 : 0);
  expect(options.recorder.start).not.toHaveBeenCalled();
  expect(state.captureState).toBe('VoiceReady');
});

it('没有系统权限请求时切后台，返回前台不会恢复旧提示', async () => {
  options.recorder.getPermission.mockResolvedValueOnce('denied');
  options.recorder.requestPermission.mockResolvedValueOnce('denied');
  await mount();
  await press();
  expect(state.permissionNotice?.message).toBe(deniedText);
  const onAppState = (AppState.addEventListener as jest.Mock).mock.calls[0][1];
  await act(async () => { onAppState('background'); onAppState('active'); });
  expect(state.permissionNotice).toBeNull();
});

function deferPermission() {
  let answer!: (result: 'blocked' | 'denied' | 'granted') => void;
  options.recorder.getPermission.mockResolvedValue('denied');
  options.recorder.requestPermission.mockReturnValueOnce(new Promise(resolve => { answer = resolve; }));
  return (result: 'blocked' | 'denied' | 'granted') => act(async () => { answer(result); });
}

it.each(['blocked', 'denied'])('初始权限为 %s 仍向系统实际请求，授权后重新按住才开始录音', async (permission) => {
  options.recorder.getPermission.mockResolvedValueOnce(permission);
  await mount();
  await press();
  expect(options.recorder.requestPermission).toHaveBeenCalledTimes(1);
  expect(state.captureState).toBe('VoiceReady');
  expect(state.permissionNotice).toBeNull();
  expect(options.recorder.start).not.toHaveBeenCalled();
  expect(options.onRecordingStarted).not.toHaveBeenCalled();
  expect(options.onStopAllAudio).not.toHaveBeenCalled();
  await press();
  expect(state.captureState).toBe('Recording');
});

it.each(['denied', 'blocked'])('首次实际结果 %s 总是提示重新按住；重试 blocked 才显示去设置', async (first) => {
  options.recorder.getPermission.mockResolvedValue('blocked');
  options.recorder.requestPermission.mockResolvedValueOnce(first).mockResolvedValueOnce('blocked');
  await mount();
  await press();
  expect(state.permissionNotice).toMatchObject({ message: deniedText, settings: false });
  await act(async () => { state.dismissPermissionNotice(state.permissionNotice); });
  expect(state.permissionNotice).toBeNull();
  await press();
  expect(options.recorder.requestPermission).toHaveBeenCalledTimes(2);
  expect(state.permissionNotice?.settings).toBe(true);
  expect(options.recorder.start).not.toHaveBeenCalled();
  expect(options.onNotice).not.toHaveBeenCalled();
});

it('可再次询问时只提示重试；其后获得权限、再被回收时从首次未授权开始', async () => {
  options.recorder.getPermission.mockResolvedValue('denied');
  options.recorder.requestPermission.mockResolvedValueOnce('blocked').mockResolvedValueOnce('denied')
    .mockResolvedValueOnce('granted').mockResolvedValueOnce('blocked');
  await mount();
  await press();
  await press();
  expect(state.permissionNotice).toMatchObject({ message: deniedText, settings: false });
  await press();
  expect(state.permissionNotice).toBeNull();
  await press();
  expect(state.permissionNotice).toMatchObject({ message: deniedText, settings: false });
  expect(options.recorder.start).not.toHaveBeenCalled();
  expect(options.onNotice).not.toHaveBeenCalled();
});

it.each(['granted', 'blocked'] as const)('重复按住保留同一系统请求，待返回 %s 时收起等待提示并处理结果', async (late) => {
  jest.useFakeTimers();
  try {
    const answer = deferPermission();
    await mount();
    await press();
    await act(async () => { await state.pressOut(); });
    expect(state.captureState).toBe('VoiceReady');
    expect(options.onRecordingEnded).toHaveBeenCalledTimes(1);
    await act(async () => { await jest.advanceTimersByTimeAsync(9000); });
    await press();
    const first = state.permissionNotice;
    expect(first?.message).toContain('权限');
    expect(first?.settings).toBe(false);
    await act(async () => { state.dismissPermissionNotice(first); });
    expect(state.permissionNotice).toBeNull();
    await press();
    const second = state.permissionNotice;
    expect(second).not.toBeNull();
    expect(second).not.toBe(first);
    await press();
    expect(state.permissionNotice).toBe(second);
    await act(async () => { state.dismissPermissionNotice(first); });
    expect(state.permissionNotice).toBe(second);
    expect(options.recorder.requestPermission).toHaveBeenCalledTimes(1);
    await answer(late);
    if (late === 'granted') expect(state.permissionNotice).toBeNull();
    else expect(state.permissionNotice).toMatchObject({ message: deniedText, settings: false });
    expect(state.captureState).toBe('VoiceReady');
    expect(options.recorder.start).not.toHaveBeenCalled();
    expect(options.onNotice).not.toHaveBeenCalled();
  } finally { jest.useRealTimers(); }
});

it.each(['getPermission', 'requestPermission'])('权限接口 %s 抛错时在当前界面提示，之后仍可重新按住录音', async (method) => {
  options.recorder.getPermission.mockResolvedValueOnce('denied');
  if (method === 'getPermission') options.recorder.getPermission.mockReset().mockRejectedValueOnce(new Error('error'));
  else options.recorder.requestPermission.mockRejectedValueOnce(new Error('error'));
  await mount();
  await press();
  expect(state.permissionNotice).toMatchObject({ message: permissionErrorText, settings: false });
  expect(state.captureState).toBe('VoiceReady');
  expect(options.onNotice).not.toHaveBeenCalled();
  expect(options.recorder.start).not.toHaveBeenCalled();
  options.recorder.getPermission.mockResolvedValueOnce('granted');
  await press();
  expect(state.captureState).toBe('Recording');
  expect(state.permissionNotice).toBeNull();
});

it.each(['文字输入', '覆盖页', '主动后台'])('进入%s时关闭等待提示，回到原界面后旧结果不能补弹', async (destination) => {
  const answer = deferPermission();
  await mount();
  await press();
  await press();
  expect(state.permissionNotice).not.toBeNull();
  await act(async () => {
    if (destination === '文字输入') state.toggleMode();
    else if (destination === '覆盖页') state.leavePermissionPage();
    else {
      const handler = (subscribeVoiceHostStopped as jest.Mock).mock.calls[0][0];
      handler();
      (AppState.addEventListener as jest.Mock).mock.calls[0][1]('background');
    }
  });
  expect(state.permissionNotice).toBeNull();
  await act(async () => {
    if (destination === '文字输入') state.toggleMode();
    if (destination === '主动后台') (AppState.addEventListener as jest.Mock).mock.calls[0][1]('active');
  });
  await answer('blocked');
  expect(state.permissionNotice).toBeNull();
  expect(options.onNotice).not.toHaveBeenCalled();
  expect(options.recorder.start).not.toHaveBeenCalled();
});

it('权限框暂时遮住应用，处理结果等到返回原界面后显示', async () => {
  const answer = deferPermission();
  await mount();
  await press();
  const appStateChanged = (AppState.addEventListener as jest.Mock).mock.calls[0][1];
  await act(async () => { appStateChanged('background'); });
  await answer('blocked');
  expect(state.permissionNotice).toBeNull();
  await act(async () => { appStateChanged('active'); });
  expect(state.permissionNotice).toMatchObject({ message: deniedText, settings: false });
});

it('卸载时还有权限请求，返回结果不会启动录音或向聊天追加消息', async () => {
  const answer = deferPermission();
  await mount();
  await press();
  await act(async () => { tree.unmount(); });
  await answer('blocked');
  expect(options.recorder.start).not.toHaveBeenCalled();
  expect(options.onNotice).not.toHaveBeenCalled();
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

it('取消区继续累计时间和音量，滑回提交一次，下一次录音从零开始', async () => {
  jest.useFakeTimers({ now: 1000 });
  try {
    await mount();
    await act(async () => { await state.pressIn(event); });
    const onMetering = options.recorder.start.mock.calls[0][0].onMetering;
    await act(async () => { await jest.advanceTimersByTimeAsync(2000); onMetering(0); });
    await act(async () => { state.pressMove({ nativeEvent: { pageY: 121 } } as GestureResponderEvent); });
    expect(state.captureState).toBe('Recording');
    await act(async () => { state.pressMove({ nativeEvent: { pageY: 120 } } as GestureResponderEvent); });
    expect(state.captureState).toBe('CancelZone');
    await act(async () => { await jest.advanceTimersByTimeAsync(3000); onMetering(0); });
    expect(state.elapsedMs).toBe(5000);
    expect(state.smoothedMeter).toBeCloseTo(0.51);
    await act(async () => { state.pressMove({ nativeEvent: { pageY: 121 } } as GestureResponderEvent); });
    expect(state.elapsedMs).toBe(5000);
    expect(state.smoothedMeter).toBeCloseTo(0.51);
    await act(async () => { await state.pressOut(); await state.pressOut(); });
    expect(options.onRecordingCommitted).toHaveBeenCalledTimes(1);
    expect(state.captureState).toBe('Uploading');
    await act(async () => { state.onUploadStatus('one', 'submitted'); });
    await act(async () => { await state.pressIn(event); });
    expect(state.elapsedMs).toBe(0);
    expect(state.smoothedMeter).toBe(0);
  } finally { jest.useRealTimers(); }
});

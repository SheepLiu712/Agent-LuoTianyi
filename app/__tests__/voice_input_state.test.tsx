/**
 * useVoiceInput 状态机回归：提交后复位、stop() 抛错不锁死、快速点按、系统中断、卸载通知、30 秒上限。
 * 这些路径此前零覆盖，正是 N2（提交后卡死在 Uploading）与 AC-10/AC-12 缺口所在。
 */
import React from 'react';
import { act, create } from 'react-test-renderer';

jest.mock('expo-haptics', () => ({
  impactAsync: jest.fn().mockResolvedValue(undefined),
  ImpactFeedbackStyle: { Medium: 'medium' },
}));
jest.mock('expo-av', () => ({ Audio: { Sound: jest.fn() } }));
jest.mock('expo-file-system/legacy', () => ({
  deleteAsync: jest.fn().mockResolvedValue(undefined),
}));
const appStateHandlers: Array<(state: string) => void> = [];
jest.mock('react-native', () => ({
  Alert: { alert: jest.fn() },
  Linking: { openSettings: jest.fn().mockResolvedValue(undefined) },
  AppState: {
    addEventListener: jest.fn((_event: string, handler: (state: string) => void) => {
      appStateHandlers.push(handler);
      return { remove: jest.fn() };
    }),
  },
}));

import { useVoiceInput } from '../hooks/useVoiceInput';

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

type Recorder = {
  getPermission: jest.Mock;
  requestPermission: jest.Mock;
  start: jest.Mock;
  stop: jest.Mock;
  cancel: jest.Mock;
  dispose: jest.Mock;
};

function makeRecorder(): Recorder {
  return {
    getPermission: jest.fn().mockResolvedValue('granted'),
    requestPermission: jest.fn().mockResolvedValue('granted'),
    start: jest.fn().mockResolvedValue({ recordingId: '11111111-1111-4111-8111-111111111111', localUri: 'file://v.m4a' }),
    stop: jest.fn().mockResolvedValue({ localUri: 'file://v.m4a', durationMs: 1200 }),
    cancel: jest.fn().mockResolvedValue(undefined),
    dispose: jest.fn().mockResolvedValue(undefined),
  };
}

function makeOptions(recorder: Recorder) {
  return {
    onRecordingStarted: jest.fn(),
    onRecordingCancelled: jest.fn(),
    onRecordingCommitted: jest.fn(),
    onStopAllAudio: jest.fn().mockResolvedValue(undefined),
    onNotice: jest.fn(),
    recorder,
  };
}

let latest: any;
function Harness({ options }: { options: any }) {
  latest = useVoiceInput(options);
  return null;
}

async function renderHook(options: any) {
  let renderer: any;
  await act(async () => {
    renderer = create(React.createElement(Harness, { options }));
  });
  return renderer;
}

const pressEvent = { nativeEvent: { pageY: 100 } } as any;

describe('useVoiceInput state machine', () => {
  beforeEach(() => {
    jest.useFakeTimers();
    latest = undefined;
    appStateHandlers.length = 0;
  });
  afterEach(() => {
    jest.useRealTimers();
    jest.clearAllMocks();
  });

  it('resets to Sent after commit and allows another recording and text mode', async () => {
    const recorder = makeRecorder();
    const options = makeOptions(recorder);
    const renderer = await renderHook(options);

    act(() => { latest.toggleMode(); });
    await act(async () => { await latest.pressIn(pressEvent); });
    expect(latest.captureState).toBe('Recording');

    act(() => { jest.advanceTimersByTime(1000); });
    await act(async () => { await latest.pressOut(); });

    expect(options.onRecordingCommitted).toHaveBeenCalledTimes(1);
    expect(latest.captureState).toBe('Sent');

    // 提交后必须能再次录音（N2 的核心回归）。
    await act(async () => { await latest.pressIn(pressEvent); });
    expect(latest.captureState).toBe('Recording');
    expect(recorder.start).toHaveBeenCalledTimes(2);

    await act(async () => { await latest.pressOut(); });
    act(() => { latest.toggleMode(); });
    expect(latest.mode).toBe('text');
    expect(latest.captureState).toBe('TextMode');
    await act(async () => { renderer.unmount(); });
  });

  it('stays usable when recorder.stop() throws', async () => {
    const recorder = makeRecorder();
    recorder.stop.mockRejectedValueOnce(new Error('disk full'));
    const options = makeOptions(recorder);
    const renderer = await renderHook(options);

    act(() => { latest.toggleMode(); });
    await act(async () => { await latest.pressIn(pressEvent); });
    act(() => { jest.advanceTimersByTime(1000); });
    await act(async () => { await latest.pressOut(); });

    expect(options.onRecordingCommitted).not.toHaveBeenCalled();
    expect(options.onNotice).toHaveBeenCalledWith('录音保存失败，请重试');
    expect(latest.captureState).toBe('Failed');
    // finishing 必须已复位，否则后续所有按压都会被静默忽略。
    await act(async () => { await latest.pressIn(pressEvent); });
    expect(recorder.start).toHaveBeenCalledTimes(2);
    await act(async () => { renderer.unmount(); });
  });

  it('cancels a tap released before recording finished preparing', async () => {
    const recorder = makeRecorder();
    let resolveStart: (value: unknown) => void = () => undefined;
    recorder.start.mockImplementationOnce(() => new Promise((resolve) => { resolveStart = resolve; }));
    const options = makeOptions(recorder);
    const renderer = await renderHook(options);

    act(() => { latest.toggleMode(); });
    let pressInPromise: Promise<void>;
    await act(async () => { pressInPromise = latest.pressIn(pressEvent); });
    // 松手发生在权限检查/start 完成之前。
    await act(async () => { await latest.pressOut(); });
    await act(async () => {
      resolveStart({ recordingId: '22222222-2222-4222-8222-222222222222', localUri: 'file://v.m4a' });
      await pressInPromise;
    });

    expect(options.onRecordingCommitted).not.toHaveBeenCalled();
    expect(options.onRecordingCancelled).toHaveBeenCalledWith(
      '22222222-2222-4222-8222-222222222222',
      'too_short',
    );
    expect(options.onNotice).toHaveBeenCalledWith('说话时间太短');

    // 30 秒定时器不得把这条残片当成长录音提交。
    act(() => { jest.advanceTimersByTime(31000); });
    expect(options.onRecordingCommitted).not.toHaveBeenCalled();
    await act(async () => { renderer.unmount(); });
  });

  it('cancels when the recorder reports a system interruption', async () => {
    const recorder = makeRecorder();
    const options = makeOptions(recorder);
    const renderer = await renderHook(options);

    act(() => { latest.toggleMode(); });
    await act(async () => { await latest.pressIn(pressEvent); });
    const onInterrupted = recorder.start.mock.calls[0][0].onInterrupted as () => void;

    await act(async () => { onInterrupted(); });

    expect(recorder.cancel).toHaveBeenCalled();
    expect(options.onRecordingCancelled).toHaveBeenCalledWith(
      '11111111-1111-4111-8111-111111111111',
      'interrupted',
    );
    expect(latest.captureState).toBe('VoiceReady');
    act(() => { jest.advanceTimersByTime(31000); });
    expect(options.onRecordingCommitted).not.toHaveBeenCalled();
    await act(async () => { renderer.unmount(); });
  });

  it('notifies the server when unmounted mid-recording', async () => {
    const recorder = makeRecorder();
    const options = makeOptions(recorder);
    const renderer = await renderHook(options);

    act(() => { latest.toggleMode(); });
    await act(async () => { await latest.pressIn(pressEvent); });
    await act(async () => { renderer.unmount(); });

    expect(options.onRecordingCancelled).toHaveBeenCalledWith(
      '11111111-1111-4111-8111-111111111111',
      'unmounted',
    );
    expect(recorder.dispose).toHaveBeenCalled();
  });

  it('commits automatically at the 30 second cap', async () => {
    const recorder = makeRecorder();
    recorder.stop.mockResolvedValue({ localUri: 'file://v.m4a', durationMs: 30000 });
    const options = makeOptions(recorder);
    const renderer = await renderHook(options);

    act(() => { latest.toggleMode(); });
    await act(async () => { await latest.pressIn(pressEvent); });
    await act(async () => { jest.advanceTimersByTime(30100); });

    expect(options.onRecordingCommitted).toHaveBeenCalledTimes(1);
    expect(options.onRecordingCommitted.mock.calls[0][0].durationMs).toBeLessThanOrEqual(30000);
    await act(async () => { renderer.unmount(); });
  });

  it('offers a go-to-settings action when the permission is permanently blocked', async () => {
    const recorder = makeRecorder();
    recorder.getPermission.mockResolvedValue('denied');
    recorder.requestPermission.mockResolvedValue('blocked');
    const options = makeOptions(recorder);
    const renderer = await renderHook(options);

    act(() => { latest.toggleMode(); });
    await act(async () => { await latest.pressIn(pressEvent); });

    expect(recorder.start).not.toHaveBeenCalled();
    const { Alert, Linking } = jest.requireMock('react-native');
    const buttons = Alert.alert.mock.calls[0][2] as Array<{ text: string; onPress?: () => void }>;
    const settingsButton = buttons.find((button) => button.text === '去设置');
    expect(settingsButton).toBeTruthy();
    settingsButton?.onPress?.();
    expect(Linking.openSettings).toHaveBeenCalled();
    await act(async () => { renderer.unmount(); });
  });

  it('enters and leaves the cancel zone while recording', async () => {
    const recorder = makeRecorder();
    const options = makeOptions(recorder);
    const renderer = await renderHook(options);

    act(() => { latest.toggleMode(); });
    await act(async () => { await latest.pressIn({ nativeEvent: { pageY: 200 } } as any); });
    expect(latest.captureState).toBe('Recording');

    act(() => { latest.pressMove({ nativeEvent: { pageY: 100 } } as any); });
    expect(latest.captureState).toBe('CancelZone');
    expect(latest.isCancelZone).toBe(true);

    act(() => { latest.pressMove({ nativeEvent: { pageY: 200 } } as any); });
    expect(latest.captureState).toBe('Recording');
    expect(latest.isCancelZone).toBe(false);

    act(() => { latest.pressMove({ nativeEvent: { pageY: 100 } } as any); });
    act(() => { jest.advanceTimersByTime(1000); });
    await act(async () => { await latest.pressOut(); });

    expect(options.onRecordingCommitted).not.toHaveBeenCalled();
    expect(options.onRecordingCancelled).toHaveBeenCalledWith(
      '11111111-1111-4111-8111-111111111111',
      'gesture_cancel',
    );
    await act(async () => { renderer.unmount(); });
  });

  it('cancels a recording that is backgrounded before start finishes', async () => {
    const recorder = makeRecorder();
    let resolveStart: (value: unknown) => void = () => undefined;
    recorder.start.mockImplementationOnce(() => new Promise((resolve) => { resolveStart = resolve; }));
    const options = makeOptions(recorder);
    const renderer = await renderHook(options);

    act(() => { latest.toggleMode(); });
    let pressInPromise: Promise<void>;
    await act(async () => { pressInPromise = latest.pressIn(pressEvent); });
    // recorder.start() 还没完成时切后台：旧实现只在 Recording/CancelZone 才取消，残片会被 30 秒后提交。
    await act(async () => { appStateHandlers.forEach((handler) => handler('background')); });
    await act(async () => {
      resolveStart({ recordingId: '33333333-3333-4333-8333-333333333333', localUri: 'file://v.m4a' });
      await pressInPromise;
    });

    expect(options.onRecordingCancelled).toHaveBeenCalledWith(
      '33333333-3333-4333-8333-333333333333',
      'background',
    );
    expect(latest.captureState).toBe('VoiceReady');
    act(() => { jest.advanceTimersByTime(31000); });
    expect(options.onRecordingCommitted).not.toHaveBeenCalled();
    await act(async () => { renderer.unmount(); });
  });

  it('still cancels normally when backgrounded during an active recording', async () => {
    const recorder = makeRecorder();
    const options = makeOptions(recorder);
    const renderer = await renderHook(options);

    act(() => { latest.toggleMode(); });
    await act(async () => { await latest.pressIn(pressEvent); });
    await act(async () => { appStateHandlers.forEach((handler) => handler('background')); });

    expect(options.onRecordingCancelled).toHaveBeenCalledWith(
      '11111111-1111-4111-8111-111111111111',
      'background',
    );
    expect(latest.captureState).toBe('VoiceReady');
    await act(async () => { renderer.unmount(); });
  });
});

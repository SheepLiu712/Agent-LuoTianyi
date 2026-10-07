import * as FileSystem from 'expo-file-system/legacy';
import React from 'react';
import { act, create, ReactTestRenderer } from 'react-test-renderer';
import { GestureResponderEvent } from 'react-native';
import { useChatLogic } from '../hooks/useChatLogic';
import { NetworkClient } from '../utils/network_client';
import { voiceRecorder } from '../utils/voice_recorder';

jest.mock('react-native', () => ({ AppState: { currentState: 'active', addEventListener: jest.fn(() => ({ remove: jest.fn() })) } }));
jest.mock('expo-haptics', () => ({ impactAsync: jest.fn().mockResolvedValue(undefined), ImpactFeedbackStyle: { Medium: 'medium' } }));
jest.mock('expo-image-picker', () => ({}));
jest.mock('expo-av', () => ({ Audio: { Sound: jest.fn() } }));
jest.mock('expo-file-system/legacy', () => ({
  EncodingType: { Base64: 'base64' },
  getInfoAsync: jest.fn().mockResolvedValue({ exists: true, size: 3 }),
  readAsStringAsync: jest.fn().mockResolvedValue('AAAA'),
}));
jest.mock('../utils/live2d_helper', () => ({ setExpression: jest.fn() }));
jest.mock('../utils/voice_playback_manager', () => ({ voicePlaybackManager: { stop: jest.fn().mockResolvedValue(undefined), cacheLocal: jest.fn().mockResolvedValue('file://cached.m4a') } }));
jest.mock('../utils/network_client', () => ({ NetworkClient: jest.fn() }));
jest.mock('../utils/voice_recorder', () => ({ voiceRecorder: {
  getPermission: jest.fn().mockResolvedValue('granted'), start: jest.fn(),
  stop: jest.fn().mockResolvedValue({ localUri: 'file://recording.m4a', durationMs: 1000 }),
  cancel: jest.fn(), dispose: jest.fn(),
} }));

describe('voice upload result restores capture through chat, binder and send queue', () => {
  let root: ReactTestRenderer;
  let state: ReturnType<typeof useChatLogic>;
  let now: jest.SpyInstance;
  const event = { nativeEvent: { pageY: 200 } } as GestureResponderEvent;
  const webview = { current: null };
  function Harness() { state = useChatLogic(webview, 'user', 'token'); return null; }

  beforeEach(() => {
    jest.clearAllMocks();
    (FileSystem.getInfoAsync as jest.Mock).mockResolvedValue({ exists: true, size: 3 });
    now = jest.spyOn(Date, 'now').mockReturnValue(1000);
    (voiceRecorder.start as jest.Mock).mockReset()
      .mockResolvedValueOnce({ recordingId: 'first', localUri: 'file://recording.m4a' })
      .mockResolvedValueOnce({ recordingId: 'second', localUri: 'file://recording.m4a' });
  });
  afterEach(async () => { if (root) await act(async () => root.unmount()); now.mockRestore(); jest.useRealTimers(); });

  it.each(['submitted', 'failed'] as const)('restores after %s, allows switching and a second recording', async (status) => {
    let finish!: (value: object) => void;
    let terminal = new Promise((resolve) => { finish = resolve; });
    const sendVoicePhase = jest.fn(async (payload) => payload.phase === 'finalize' ? terminal : { ok: true });
    (NetworkClient as jest.Mock).mockImplementation(() => ({
      connectWs: jest.fn(), disconnectWs: jest.fn(), sendVoicePhase,
      sendVoiceRecordingStarted: jest.fn(), sendVoiceRecordingCancelled: jest.fn(),
    }));
    await act(async () => { root = create(<Harness />); });
    await act(async () => { state.voiceInput.toggleMode(); });
    await act(async () => { await state.voiceInput.pressIn(event); });
    now.mockReturnValue(2000);
    await act(async () => { await state.voiceInput.pressOut(); });
    expect(sendVoicePhase.mock.calls.map(([payload]) => payload.phase)).toEqual(['begin', 'chunk', 'finalize']);
    expect(state.voiceInput.captureState).toBe('Uploading');
    expect(state.messages.find((message) => message.uuid === 'first')?.sendStatus).toBe('waiting');
    await act(async () => {
      state.voiceInput.onUploadStatus('other-message', 'submitted');
      state.voiceInput.onUploadStatus('first', 'waiting');
      state.voiceInput.toggleMode();
      await state.voiceInput.pressIn(event);
    });
    expect(state.voiceInput.captureState).toBe('Uploading');
    expect(voiceRecorder.start).toHaveBeenCalledTimes(1);
    await act(async () => { finish(status === 'submitted'
      ? { ok: true, message_uuid: 'server-first', duration_ms: 1000 }
      : { ok: false, drop: true, error: 'invalid voice' }); });
    expect(state.messages.find((message) => message.uuid === 'first')?.sendStatus).toBe(status);
    expect(state.voiceInput.captureState).toBe('VoiceReady');
    expect(state.voiceInput.elapsedMs).toBe(0);
    await act(async () => { state.voiceInput.toggleMode(); });
    expect(state.voiceInput.mode).toBe('text');
    if (status === 'failed') {
      for (const retryStatus of ['failed', 'submitted']) {
        terminal = new Promise((resolve) => { finish = resolve; });
        const callsBeforeRetry = sendVoicePhase.mock.calls.length;
        await act(async () => {
          // 同一渲染帧内连点，再到等待 ACK 时点击，都不得重复入队。
          await Promise.all([state.retryVoice('first'), state.retryVoice('first')]);
        });
        await act(async () => { await state.retryVoice('first'); });
        expect(state.messages.find((message) => message.uuid === 'first')?.sendStatus).toBe('waiting');
        expect(state.voiceInput.captureState).toBe('Uploading');
        expect(sendVoicePhase.mock.calls.slice(callsBeforeRetry).filter(([payload]) => payload.phase !== 'abort').map(([payload]) => payload.phase)).toEqual(['begin', 'chunk', 'finalize']);
        expect(sendVoicePhase.mock.calls.every(([payload]) => payload.upload_id === 'first')).toBe(true);
        await act(async () => { finish(retryStatus === 'submitted'
          ? { ok: true, message_uuid: 'server-first' }
          : { ok: false, drop: true, error: 'invalid voice' }); });
        expect(state.messages.find((message) => message.uuid === 'first')?.sendStatus).toBe(retryStatus);
        expect(state.voiceInput.captureState).toBe('TextMode');
      }
      const callsAfterSuccess = sendVoicePhase.mock.calls.length;
      await act(async () => { await state.retryVoice('first'); });
      expect(sendVoicePhase).toHaveBeenCalledTimes(callsAfterSuccess);
    }
    await act(async () => { state.voiceInput.toggleMode(); });
    await act(async () => { await state.voiceInput.pressIn(event); });
    expect(voiceRecorder.start).toHaveBeenCalledTimes(2);
    expect(state.voiceInput.captureState).toBe('Recording');
    await act(async () => { state.voiceInput.onUploadStatus('first', 'failed'); });
    expect(state.voiceInput.captureState).toBe('Recording');
  });
  it('restores input and fails the bubble at 15s through the real queue after chunk ACK loss', async () => {
    now.mockRestore();
    jest.useFakeTimers({ now: 1000 });
    const sendVoicePhase = jest.fn((payload, _id, budgetMs) => payload.phase === 'chunk'
      ? new Promise((resolve) => setTimeout(() => resolve({ ok: false, error: 'disconnected' }), budgetMs))
      : Promise.resolve({ ok: true }));
    (NetworkClient as jest.Mock).mockImplementation(() => ({
      connectWs: jest.fn(), disconnectWs: jest.fn(), sendVoicePhase,
      sendVoiceRecordingStarted: jest.fn(), sendVoiceRecordingCancelled: jest.fn(),
    }));
    await act(async () => { root = create(<Harness />); });
    await act(async () => { state.voiceInput.toggleMode(); });
    await act(async () => { await state.voiceInput.pressIn(event); });
    await act(async () => { await jest.advanceTimersByTimeAsync(1000); });
    await act(async () => { await state.voiceInput.pressOut(); });
    await act(async () => { await jest.advanceTimersByTimeAsync(14999); });
    expect(state.voiceInput.captureState).toBe('Uploading');
    await act(async () => { await jest.advanceTimersByTimeAsync(1); });
    expect(state.voiceInput.captureState).toBe('VoiceReady');
    expect(state.messages.find((message) => message.uuid === 'first')?.sendStatus).toBe('failed');
    expect(sendVoicePhase.mock.calls.map((call) => call[1])).toEqual(['first:begin', 'first:chunk:0', 'first:chunk:0', 'first:chunk:0', 'first:abort']);
    await act(async () => { state.voiceInput.toggleMode(); });
    expect(state.voiceInput.mode).toBe('text');
  });

  it('reports a missing local file on manual retry and releases the input lock', async () => {
    const sendVoicePhase = jest.fn().mockResolvedValue({ ok: false, drop: true, error: 'rejected' });
    (NetworkClient as jest.Mock).mockImplementation(() => ({
      connectWs: jest.fn(), disconnectWs: jest.fn(), sendVoicePhase,
      sendVoiceRecordingStarted: jest.fn(), sendVoiceRecordingCancelled: jest.fn(),
    }));
    await act(async () => { root = create(<Harness />); });
    await act(async () => { state.voiceInput.toggleMode(); });
    await act(async () => { await state.voiceInput.pressIn(event); });
    now.mockReturnValue(2000);
    await act(async () => { await state.voiceInput.pressOut(); });
    const sent = sendVoicePhase.mock.calls.length;
    (FileSystem.getInfoAsync as jest.Mock).mockResolvedValue({ exists: false });
    await act(async () => { await state.retryVoice('first'); });
    expect(sendVoicePhase).toHaveBeenCalledTimes(sent);
    expect(state.voiceInput.captureState).toBe('VoiceReady');
    expect(state.messages.some((message) => message.content === '本地语音文件已不存在，无法重试')).toBe(true);
  });

  it('does not enqueue cancelled recordings', async () => {
    const sendVoicePhase = jest.fn();
    const cancelled = jest.fn();
    (NetworkClient as jest.Mock).mockImplementation(() => ({
      connectWs: jest.fn(), disconnectWs: jest.fn(), sendVoicePhase,
      sendVoiceRecordingStarted: jest.fn(), sendVoiceRecordingCancelled: cancelled,
    }));
    await act(async () => { root = create(<Harness />); });
    await act(async () => { state.voiceInput.toggleMode(); });
    await act(async () => { await state.voiceInput.pressIn(event); });
    now.mockReturnValue(2000);
    await act(async () => { state.voiceInput.pressMove({ nativeEvent: { pageY: 100 } } as GestureResponderEvent); });
    await act(async () => { await state.voiceInput.pressOut(); });
    expect(cancelled).toHaveBeenCalledWith('first');
    expect(sendVoicePhase).not.toHaveBeenCalled();
    expect(state.messages.filter((message) => message.type === 'audio')).toHaveLength(0);
  });

});

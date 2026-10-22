import * as FileSystem from 'expo-file-system/legacy';
import React from 'react';
import { act, create, ReactTestRenderer } from 'react-test-renderer';
import { Audio } from 'expo-av';
import { AppState, GestureResponderEvent } from 'react-native';
import { useChatLogic } from '../hooks/useChatLogic';
import { useCallSession } from '../hooks/useCallSession';
import { useHistoryLogic } from '../hooks/useHistoryLogic';
import type { CallTransportListener } from '../types/call_transport';
import { NetworkClient } from '../utils/network_client';
import { VoiceFileSystem } from './helpers/voice_filesystem';
import { VoicePlaybackManager, voicePlaybackManager } from '../utils/voice_playback_manager';
import { voiceRecorder } from '../utils/voice_recorder';

jest.mock('react-native', () => ({ Platform: { OS: 'android' }, BackHandler: { addEventListener: jest.fn(() => ({ remove: jest.fn() })) }, AppState: { currentState: 'active', addEventListener: jest.fn(() => ({ remove: jest.fn() })) } }));
jest.mock('expo-haptics', () => ({ impactAsync: jest.fn().mockResolvedValue(undefined), ImpactFeedbackStyle: { Medium: 'medium' } }));
jest.mock('expo-image-picker', () => ({}));
jest.mock('expo-av', () => ({ Audio: { Sound: jest.fn() } }));
jest.mock('expo-file-system/legacy', () => jest.requireActual('./helpers/voice_filesystem').createVoiceFileSystem());
jest.mock('../utils/live2d_helper', () => ({ setExpression: jest.fn() }));
jest.mock('../utils/network_client', () => ({ NetworkClient: jest.fn() }));
jest.mock('../utils/voice_recorder', () => ({ voiceRecorder: {
  getPermission: jest.fn().mockResolvedValue('granted'), start: jest.fn(),
  stop: jest.fn().mockResolvedValue({ localUri: 'file://recording.m4a', durationMs: 1000 }),
  cancel: jest.fn(), dispose: jest.fn(),
} }));



describe('recording and playback through chat, processor and native voice manager', () => {
  let root: ReactTestRenderer;
  let state: ReturnType<typeof useChatLogic>;
  let incoming: (payload: object) => void;
  let sound: Record<string, jest.Mock>;
  let now: jest.SpyInstance;
  const injectJavaScript = jest.fn();
  const webview = { current: { injectJavaScript } } as any;
  const event = { nativeEvent: { pageY: 200 } } as GestureResponderEvent;
  function Harness() { state = useChatLogic(webview, 'user', 'token', 'luotianyi'); return null; }
  const flush = () => new Promise<void>((resolve) => setImmediate(resolve));
  beforeEach(async () => {
    await voicePlaybackManager.clear();
    const fs = FileSystem as unknown as VoiceFileSystem;
    for (const file of ['history.m4a', 'user.m4a', 'agent.wav', 'recording.m4a']) fs.put(`file://${file}`, 'audio');
    jest.clearAllMocks();
    now = jest.spyOn(Date, 'now').mockReturnValue(1000);
    sound = Object.fromEntries(['loadAsync', 'playAsync', 'stopAsync', 'unloadAsync', 'setOnPlaybackStatusUpdate']
      .map((key) => [key, jest.fn().mockResolvedValue(undefined)]));
    (Audio.Sound as unknown as jest.Mock).mockImplementation(() => sound);
    (voiceRecorder.start as jest.Mock).mockResolvedValue({ recordingId: 'recording', localUri: 'file://recording.m4a' });
    (NetworkClient as jest.Mock).mockImplementation(() => ({
      connectWs: jest.fn((_user, _token, _character, callbacks) => { incoming = callbacks.onAgentMessage; }),
      disconnectWs: jest.fn(), sendVoicePhase: jest.fn().mockResolvedValue({ ok: true, message_uuid: 'server-recording' }),
      sendVoiceRecordingStarted: jest.fn(), sendVoiceRecordingCancelled: jest.fn(),
    }));
    await act(async () => { root = create(<Harness />); });
  });
  afterEach(async () => { await act(async () => root.unmount()); now.mockRestore(); });

  it('hangup inserts one local call immediately, then real history loading calibrates it without losing chat or changing its position', async () => {
    await act(async () => root.unmount());
    let listener!: CallTransportListener;
    let call!: ReturnType<typeof useCallSession>;
    let history!: ReturnType<typeof useHistoryLogic>;
    let finishClose!: () => void;
    const closing = new Promise<void>((resolve) => { finishClose = resolve; });
    const session = {
      prepare: jest.fn(async () => {}), start: jest.fn(async () => {}), hangup: jest.fn(async () => {}),
      close: jest.fn(() => closing),
      subscribe: (callback: CallTransportListener) => { listener = callback; return () => {}; },
      onError: () => () => {},
    };
    const onReturnToChat = jest.fn();
    const monotonicNow = () => 1100;
    function Combined() {
      state = useChatLogic(webview, 'user', 'token', 'luotianyi');
      call = useCallSession({ session, requestPermission: async () => 'granted',
        capabilities: { serverAvailable: true, nativeAvailable: true }, now: monotonicNow,
        onCallRecord: state.addLocalCallRecord, onReturnToChat });
      history = useHistoryLogic(state.addHistoryMessage);
      return null;
    }
    const originalFetch = global.fetch;
    const fetchHistory = jest.fn().mockResolvedValue({ ok: true, json: async () => ({ start_index: 0, history: [
      { uuid: 'old', type: 'text', source: 'agent', content: 'stale server copy' },
      { uuid: 'persisted-uuid', call_id: 'call-1', type: 'call', source: 'user',
        content: '[语音通话] 00:02', timestamp: '2026-10-21 12:00:00', outcome: 'connected', active_duration_ms: 2500 },
    ] }) });
    global.fetch = fetchHistory as unknown as typeof fetch;
    try {
      await act(async () => { root = create(<Combined />); });
      act(() => state.addHistoryMessage([{ uuid: 'old', type: 'text', isUser: false, content: 'live local copy', audioPlayState: 'playing' }]));
      await new Promise((resolve) => setTimeout(resolve, 20));
      const scrollToIndex = jest.fn();
      const scrollToOffset = jest.fn();
      (state.flatListRef as any).current = { scrollToIndex, scrollToOffset };
      await act(async () => { await call.start(false); });
      act(() => listener({ status: 'connected', callId: 'call-1', connectedAtMonotonicMs: 100, activeDurationMs: 1000 }));
      act(() => call.hangup());
      // Neither closure, reconnection nor server settlement needs to complete first.
      expect(state.messages[0]).toMatchObject({ uuid: 'call:call-1', callId: 'call-1', callOutcome: 'connected', durationMs: 1000 });
      expect(fetchHistory).not.toHaveBeenCalled();
      expect(call.state.phase).toBe('IDLE');
      const local = state.messages[0];
      await act(async () => { await flush(); });
      expect(onReturnToChat).toHaveBeenCalledTimes(1);
      await new Promise((resolve) => setTimeout(resolve, 20));
      expect(scrollToIndex).not.toHaveBeenCalled();
      expect(scrollToOffset).toHaveBeenCalledWith({ offset: 0, animated: false });
      await act(async () => { await history.loadHistory('user', 'token'); });
      expect(state.messages).toHaveLength(2);
      expect(state.messages[0]).toMatchObject({ uuid: 'persisted-uuid', callId: 'call-1', durationMs: 2500,
        timestamp: Date.UTC(2026, 9, 21, 4) });
      expect(state.messages[1]).toMatchObject({ uuid: 'old', content: 'live local copy', audioPlayState: 'playing' });
      expect(history.history_start_index).toBe(0);
      act(() => { state.addLocalCallRecord(local); listener({ status: 'closed', callId: 'call-1', activeDurationMs: 3000 }); });
      expect(state.messages).toHaveLength(2);
      expect(state.messages[0].durationMs).toBe(2500);
      act(() => state.addHistoryMessage([state.messages[0]]));
      expect(state.messages).toHaveLength(2);
    } finally { global.fetch = originalFetch; finishClose(); }
  });

  it('sends recording cancellation before disconnecting on chat unmount', async () => {
    await act(async () => { state.voiceInput.toggleMode(); });
    await act(async () => { await state.voiceInput.pressIn(event); });
    const network = (NetworkClient as jest.Mock).mock.results[0].value;
    await act(async () => { root.unmount(); });
    expect(network.sendVoiceRecordingCancelled).toHaveBeenCalledWith('recording');
    expect(network.sendVoiceRecordingCancelled.mock.invocationCallOrder[0])
      .toBeLessThan(network.disconnectWs.mock.invocationCallOrder[0]);
    expect(network.sendVoicePhase).not.toHaveBeenCalled();
  });

  it('reuses the recorded bytes after finalize ACK, history refresh and manager restart', async () => {
    const fs = FileSystem as unknown as VoiceFileSystem;
    await act(async () => { state.voiceInput.toggleMode(); });
    await act(async () => { await state.voiceInput.pressIn(event); });
    now.mockReturnValue(2000);
    await act(async () => { await state.voiceInput.pressOut(); await flush(); });
    expect(state.messages.find((m) => m.uuid === 'recording')?.sendStatus).toBe('submitted');
    expect(fs.files.has(VoicePlaybackManager.cacheUri('recording'))).toBe(false);
    expect(fs.files.get(VoicePlaybackManager.cacheUri('server-recording'))?.data.toString()).toBe('audio');
    await act(async () => { state.addHistoryMessage([{ uuid: 'server-recording', type: 'audio',
      content: '[voice]', isUser: true, timestamp: 2000, audioAvailable: true }]); });
    expect(state.messages.some((m) => m.uuid === 'recording')).toBe(false);
    await act(async () => { await state.toggleVoicePlayback('server-recording'); });
    expect(sound.playAsync).toHaveBeenCalledTimes(1);
    await act(async () => { await voicePlaybackManager.stop(); });
    const download = jest.fn();
    const restarted = new VoicePlaybackManager({ download });
    await restarted.play('server-recording', 'token');
    expect(download).not.toHaveBeenCalled();
    await restarted.stop();
  });

  it.each(['user', 'agent'])('stops %s history playback and resets the button before recording', async (kind) => {
    await act(async () => { state.addHistoryMessage([{ uuid: 'history', type: kind === 'user' ? 'audio' : 'text',
      content: 'history', isUser: kind === 'user', timestamp: 1, audioAvailable: true, audioLocalUri: 'file://history.m4a' }]); });
    await act(async () => { if (kind === 'user') await state.toggleVoicePlayback('history');
      else await state.handleToggleAgentAudio('history'); });
    expect(sound.playAsync).toHaveBeenCalledTimes(1);
    expect(state.messages.find((m) => m.uuid === 'history')?.audioPlayState).toBe('playing');
    await act(async () => { state.voiceInput.toggleMode(); });
    await act(async () => { await state.voiceInput.pressIn(event); });
    expect(sound.stopAsync).toHaveBeenCalled();
    expect(sound.unloadAsync).toHaveBeenCalled();
    expect(state.messages.find((m) => m.uuid === 'history')?.audioPlayState).toBe('idle');
    expect(injectJavaScript).toHaveBeenCalledWith('window.stopServerAudio(); true;');
    await act(async () => { await state.toggleVoicePlayback('history'); await state.handleToggleAgentAudio('history'); });
    expect(sound.playAsync).toHaveBeenCalledTimes(1);
  });

  it('switches between user and agent replay, then yields to online audio', async () => {
    await act(async () => { state.addHistoryMessage([
      { uuid: 'user', type: 'audio', content: 'voice', isUser: true, timestamp: 1, audioAvailable: true, audioLocalUri: 'file://user.m4a' },
      { uuid: 'agent', type: 'text', content: 'tts', isUser: false, timestamp: 2, audioAvailable: true, audioLocalUri: 'file://agent.wav' },
    ]); });
    await act(async () => { await state.toggleVoicePlayback('user'); });
    await act(async () => { await state.handleToggleAgentAudio('agent'); });
    expect(state.messages.find((m) => m.uuid === 'user')?.audioPlayState).toBe('idle');
    expect(state.messages.find((m) => m.uuid === 'agent')?.audioPlayState).toBe('playing');
    await act(async () => { await state.toggleVoicePlayback('user'); });
    expect(state.messages.find((m) => m.uuid === 'agent')?.audioPlayState).toBe('idle');
    const stops = sound.stopAsync.mock.calls.length;
    await act(async () => { incoming({ uuid: 'online', audio: 'YXVkaW8=', is_final_package: false }); await flush(); });
    expect(sound.stopAsync.mock.calls.length).toBeGreaterThan(stops);
    expect(state.messages.every((m) => m.audioPlayState !== 'playing')).toBe(true);
    await act(async () => { await state.toggleVoicePlayback('user'); await state.handleToggleAgentAudio('agent'); });
    expect(sound.playAsync).toHaveBeenCalledTimes(3);
  });

  it.each(['user', 'agent'])('toggles %s replay off and resets after natural completion', async (kind) => {
    await act(async () => { state.addHistoryMessage([{ uuid: 'history', type: kind === 'user' ? 'audio' : 'text', content: 'history', isUser: kind === 'user', timestamp: 1, audioAvailable: true, audioLocalUri: 'file://history.m4a' }]); });
    const toggle = () => kind === 'user' ? state.toggleVoicePlayback('history') : state.handleToggleAgentAudio('history');
    await act(async () => { await toggle(); });
    await act(async () => { await toggle(); });
    expect(sound.playAsync).toHaveBeenCalledTimes(1);
    expect(sound.stopAsync).toHaveBeenCalled();
    expect(state.messages.find((m) => m.uuid === 'history')?.audioPlayState).toBe('idle');
    await act(async () => { await toggle(); });
    await act(async () => { sound.setOnPlaybackStatusUpdate.mock.calls.at(-1)![0]({ isLoaded: true, didJustFinish: true }); });
    expect(state.messages.find((m) => m.uuid === 'history')?.audioPlayState).toBe('idle');
    await act(async () => { await toggle(); });
    expect(sound.playAsync).toHaveBeenCalledTimes(3);
  });

  it.each(['same', 'other', 'server', 'recording'])('cancels a pending user replay when interrupted by %s', async (interrupt) => {
    await act(async () => { state.addHistoryMessage([
      { uuid: 'user', type: 'audio', content: 'voice', isUser: true, timestamp: 1, audioAvailable: true, audioLocalUri: 'file://user.m4a' },
      { uuid: 'agent', type: 'text', content: 'tts', isUser: false, timestamp: 2, audioAvailable: true, audioLocalUri: 'file://agent.wav' },
    ]); });
    let release!: () => void;
    sound.loadAsync.mockImplementationOnce(() => new Promise<void>((resolve) => { release = resolve; }));
    let pending!: Promise<void>;
    await act(async () => { pending = state.toggleVoicePlayback('user'); await flush(); });
    expect(release).toBeDefined();
    await act(async () => {
      if (interrupt === 'same') await state.toggleVoicePlayback('user');
      else if (interrupt === 'other') await state.handleToggleAgentAudio('agent');
      else if (interrupt === 'server') { incoming({ uuid: 'online', audio: 'YXVkaW8=', is_final_package: false }); await flush(); }
      else { state.voiceInput.toggleMode(); }
    });
    if (interrupt === 'recording') await act(async () => { await state.voiceInput.pressIn(event); });
    await act(async () => { release(); await pending; });
    expect(sound.playAsync).toHaveBeenCalledTimes(interrupt === 'other' ? 1 : 0);
    expect(state.messages.find((m) => m.uuid === 'user')?.audioPlayState).toBe('idle');
  });

  it.each(['cancel', 'submit', 'background'])('saves incoming audio without replay after %s, including late tail packets', async (end) => {
    await act(async () => { incoming({ uuid: 'old', audio: 'YXVkaW8=', is_final_package: false }); await flush(); });
    expect(injectJavaScript.mock.calls.some(([code]) => code.includes('feedAudioChunk'))).toBe(true);
    await act(async () => { state.voiceInput.toggleMode(); });
    await act(async () => { await state.voiceInput.pressIn(event); });
    injectJavaScript.mockClear();
    await act(async () => {
      incoming({ uuid: 'complete', text: 'complete text', audio: 'YXVkaW8=', is_final_package: true });
      incoming({ uuid: 'during', text: 'saved text', audio: 'YXVkaW8=', is_final_package: false });
      await flush();
    });
    expect(state.messages.some((m) => m.content === 'saved text')).toBe(true);
    expect(state.messages.find((m) => m.uuid === 'complete')?.audioAvailable).toBe(true);
    expect(injectJavaScript.mock.calls.some(([code]) => code.includes('feedAudioChunk'))).toBe(false);
    now.mockReturnValue(2000);
    await act(async () => {
      if (end === 'submit') await state.voiceInput.pressOut();
      else if (end === 'cancel') await state.voiceInput.cancelBySystem('gesture_cancel');
      else (AppState.addEventListener as jest.Mock).mock.calls.at(-1)[1]('background');
      await flush();
      incoming({ uuid: 'old', audio: '', is_final_package: true });
      incoming({ uuid: 'during', audio: 'YXVkaW8=', is_final_package: true });
      await flush();
    });
    expect(injectJavaScript.mock.calls.some(([code]) => code.includes('feedAudioChunk'))).toBe(false);
    expect(FileSystem.writeAsStringAsync).toHaveBeenCalledWith(
      expect.stringContaining('during.wav'), expect.any(String), expect.any(Object));
    expect(state.messages.find((m) => m.uuid === 'during')?.audioAvailable).toBe(true);
    await act(async () => { await state.handleToggleAgentAudio('during'); });
    expect(sound.playAsync).toHaveBeenCalledTimes(1);
  });
});

import * as FileSystem from 'expo-file-system/legacy';
import React from 'react';
import { act, create, ReactTestRenderer } from 'react-test-renderer';
import { Audio } from 'expo-av';
import { AppState, GestureResponderEvent } from 'react-native';
import { useChatLogic } from '../hooks/useChatLogic';
import { NetworkClient } from '../utils/network_client';
import { voiceRecorder } from '../utils/voice_recorder';

jest.mock('react-native', () => ({ AppState: { currentState: 'active', addEventListener: jest.fn(() => ({ remove: jest.fn() })) } }));
jest.mock('expo-haptics', () => ({ impactAsync: jest.fn().mockResolvedValue(undefined), ImpactFeedbackStyle: { Medium: 'medium' } }));
jest.mock('expo-image-picker', () => ({}));
jest.mock('expo-av', () => ({ Audio: { Sound: jest.fn() } }));
jest.mock('expo-file-system/legacy', () => ({
  documentDirectory: 'file://documents/',
  makeDirectoryAsync: jest.fn().mockResolvedValue(undefined),
  writeAsStringAsync: jest.fn().mockResolvedValue(undefined),
  copyAsync: jest.fn().mockResolvedValue(undefined),
  EncodingType: { Base64: 'base64' },
  getInfoAsync: jest.fn().mockResolvedValue({ exists: true, size: 3 }),
  readAsStringAsync: jest.fn().mockResolvedValue('AAAA'),
}));
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
  function Harness() { state = useChatLogic(webview, 'user', 'token'); return null; }
  const flush = () => new Promise<void>((resolve) => setImmediate(resolve));
  beforeEach(async () => {
    jest.clearAllMocks();
    now = jest.spyOn(Date, 'now').mockReturnValue(1000);
    sound = Object.fromEntries(['loadAsync', 'playAsync', 'stopAsync', 'unloadAsync', 'setOnPlaybackStatusUpdate']
      .map((key) => [key, jest.fn().mockResolvedValue(undefined)]));
    (Audio.Sound as unknown as jest.Mock).mockImplementation(() => sound);
    (voiceRecorder.start as jest.Mock).mockResolvedValue({ recordingId: 'recording', localUri: 'file://recording.m4a' });
    (NetworkClient as jest.Mock).mockImplementation(() => ({
      connectWs: jest.fn((_user, _token, callbacks) => { incoming = callbacks.onAgentMessage; }),
      disconnectWs: jest.fn(), sendVoicePhase: jest.fn().mockResolvedValue({ ok: true }),
      sendVoiceRecordingStarted: jest.fn(), sendVoiceRecordingCancelled: jest.fn(),
    }));
    await act(async () => { root = create(<Harness />); });
  });
  afterEach(async () => { await act(async () => root.unmount()); now.mockRestore(); });

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

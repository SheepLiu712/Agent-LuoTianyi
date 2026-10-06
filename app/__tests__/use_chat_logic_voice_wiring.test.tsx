/**
 * 组装层回归：useChatLogic 必须把「录音闸门」接给 MessageProcessor、把重试接给绑定回调、
 * 在 finalize ACK 后迁移缓存键、并在开始录音时停掉语音条播发。
 *
 * 此前只有组件/处理器层测试：把 useChatLogic 的接线删掉（AC-15 闸门、N3 重试）整仓仍然全绿。
 * 这里通过捕获 useChatLogic 传给 useVoiceInput 的 options 来验证接线本身。
 */
import React from 'react';
import { act, create } from 'react-test-renderer';
import * as fs from 'fs';
import * as path from 'path';

jest.mock('react-native', () => ({
  Alert: { alert: jest.fn() },
  AppState: { currentState: 'active', addEventListener: jest.fn(() => ({ remove: jest.fn() })) },
  FlatList: 'FlatList',
  Linking: { openSettings: jest.fn() },
}));
jest.mock('react-native-webview', () => ({ WebView: 'WebView' }));
jest.mock('expo-image-picker', () => ({ launchImageLibraryAsync: jest.fn() }));
jest.mock('expo-av', () => ({ Audio: { Sound: jest.fn() } }));
jest.mock('expo-file-system/legacy', () => ({ deleteAsync: jest.fn().mockResolvedValue(undefined) }));
jest.mock('../utils/live2d_helper', () => ({ setExpression: jest.fn() }));

const playbackManager = {
  stop: jest.fn().mockResolvedValue(undefined),
  cacheLocal: jest.fn().mockResolvedValue('file://cache/x.m4a'),
  migrateCacheKey: jest.fn().mockResolvedValue('file://cache/message.m4a'),
  play: jest.fn().mockResolvedValue(undefined),
};
jest.mock('../utils/voice_playback_manager', () => ({ voicePlaybackManager: playbackManager }));

const networkClient = {
  connectWs: jest.fn(),
  disconnectWs: jest.fn(),
  sendVoiceRecordingStarted: jest.fn().mockResolvedValue(undefined),
  sendVoiceRecordingCancelled: jest.fn().mockResolvedValue(undefined),
  sendVoicePhase: jest.fn().mockResolvedValue({ ok: true }),
};
jest.mock('../utils/network_client', () => ({ NetworkClient: jest.fn(() => networkClient) }));

interface VoiceOptions {
  onRecordingStarted: (id: string) => void;
  onRecordingCancelled: (id: string, reason: string) => void;
  onRecordingCommitted: (value: { uploadId: string; localUri: string; durationMs: number }) => void;
  onStopAllAudio: () => Promise<void>;
  onNotice: (text: string) => void;
}
let voiceOptions: VoiceOptions;
jest.mock('../hooks/useVoiceInput', () => ({
  useVoiceInput: jest.fn((options: VoiceOptions) => {
    voiceOptions = options;
    return {
      mode: 'text', captureState: 'TextMode', elapsedMs: 0, smoothedMeter: 0, isCancelZone: false,
      toggleMode: jest.fn(), pressIn: jest.fn(), pressMove: jest.fn(), pressOut: jest.fn(), cancelBySystem: jest.fn(),
    };
  }),
}));

type ProcessorArgs = unknown[];
const processorArgs: ProcessorArgs[] = [];
const processor = {
  stop: jest.fn(),
  onAgentMessage: jest.fn(),
  onAgentStateChanged: jest.fn(),
  sendVoice: jest.fn().mockResolvedValue(undefined),
  sendText: jest.fn(),
  sendImage: jest.fn(),
  sendProactiveText: jest.fn(),
  sendTouch: jest.fn(),
  sendTypingEvent: jest.fn(),
  sendImageSelecting: jest.fn(),
  sendImageSelectingCancel: jest.fn(),
  playLocalTtsByUuid: jest.fn(),
  stopLocalTts: jest.fn(),
  onServerAudioFinished: jest.fn(),
  isServerAudioActive: jest.fn(() => false),
  setLocalAudioPath: jest.fn(),
  processLlmRequest: jest.fn(),
  getLlmMode: jest.fn(),
};
jest.mock('../utils/message_processor', () => ({
  MessageProcessor: jest.fn((...args: unknown[]) => {
    processorArgs.push(args);
    return processor;
  }),
}));

import { useChatLogic } from '../hooks/useChatLogic';

let latest: any;
function Harness() {
  latest = useChatLogic({ current: null } as any, 'user', 'token');
  return null;
}

async function renderHook() {
  let renderer: any;
  await act(async () => {
    renderer = create(React.createElement(Harness));
  });
  return renderer;
}

describe('useChatLogic voice wiring (assembly layer)', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    processorArgs.length = 0;
  });

  it('feeds the recording gate into MessageProcessor and tracks recording state', async () => {
    const renderer = await renderHook();

    expect(processorArgs).toHaveLength(1);
    const isVoiceRecording = processorArgs[0][5] as () => boolean;
    expect(typeof isVoiceRecording).toBe('function');
    expect(isVoiceRecording()).toBe(false);

    act(() => { voiceOptions.onRecordingStarted('rec-1'); });
    expect(isVoiceRecording()).toBe(true);
    act(() => { voiceOptions.onRecordingCancelled('rec-1', 'gesture_cancel'); });
    expect(isVoiceRecording()).toBe(false);

    act(() => { voiceOptions.onRecordingStarted('rec-2'); });
    act(() => { voiceOptions.onRecordingCommitted({ uploadId: 'up-2', localUri: 'file://v.m4a', durationMs: 1200 }); });
    expect(isVoiceRecording()).toBe(false);

    await act(async () => { renderer.unmount(); });
  });

  it('re-sends a failed voice through retryVoice with the same upload id', async () => {
    const renderer = await renderHook();

    act(() => { voiceOptions.onRecordingCommitted({ uploadId: 'up-3', localUri: 'file://v3.m4a', durationMs: 900 }); });
    await act(async () => { await latest.retryVoice('up-3'); });

    expect(processor.sendVoice).toHaveBeenCalledWith('up-3', 'file://v3.m4a', 900);

    await act(async () => { renderer.unmount(); });
  });

  it('re-points the optimistic bubble at the migrated cache file on the finalize ACK', async () => {
    const renderer = await renderHook();
    voiceOptions.onRecordingCommitted({ uploadId: 'up-4', localUri: 'file://v4.m4a', durationMs: 800 });
    const onVoiceFinalized = processorArgs[0][4] as (uploadId: string, messageUuid: string, durationMs?: number) => void;

    await act(async () => {
      onVoiceFinalized('up-4', 'message-4', 800);
      await new Promise((resolve) => setImmediate(resolve));
    });

    expect(playbackManager.migrateCacheKey).toHaveBeenCalledWith('up-4', 'message-4');
    // 乐观气泡 uuid 仍是 upload_id，ACK 后必须把 audioLocalUri 指向迁移后的文件，否则点播放会 404。
    expect(latest.messages.find((msg: any) => msg.uuid === 'up-4')?.audioLocalUri).toBe('file://cache/message.m4a');

    await act(async () => { renderer.unmount(); });
  });

  it('plays the optimistic bubble through the ACK-resolved message uuid', async () => {
    const renderer = await renderHook();
    voiceOptions.onRecordingCommitted({ uploadId: 'up-5', localUri: 'file://v5.m4a', durationMs: 700 });
    const onVoiceFinalized = processorArgs[0][4] as (uploadId: string, messageUuid: string, durationMs?: number) => void;
    await act(async () => {
      onVoiceFinalized('up-5', 'message-5', 700);
      await new Promise((resolve) => setImmediate(resolve));
    });
    playbackManager.cacheLocal.mockClear();
    playbackManager.play.mockClear();

    await act(async () => { await latest.toggleVoicePlayback('up-5'); });

    expect(playbackManager.cacheLocal).toHaveBeenCalledWith('message-5', 'file://cache/message.m4a');
    expect(playbackManager.play).toHaveBeenCalledWith('message-5', 'token', expect.any(Function));

    await act(async () => { renderer.unmount(); });
  });

  it('stops voice-bubble playback when a recording starts (AC-04)', async () => {
    const renderer = await renderHook();

    await act(async () => { await voiceOptions.onStopAllAudio(); });

    expect(playbackManager.stop).toHaveBeenCalled();

    await act(async () => { renderer.unmount(); });
  });

  it('passes retryVoice and the playback toggle from the chat screen (index.tsx)', () => {
    const source = fs.readFileSync(path.join(__dirname, '..', 'app', 'index.tsx'), 'utf8');

    expect(source).toMatch(/retryVoice/);
    expect(source).toMatch(/onRetryVoice=\{retryVoice\}/);
    expect(source).toMatch(/onToggleVoicePlayback=\{toggleVoicePlayback\}/);
  });
});

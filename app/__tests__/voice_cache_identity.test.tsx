/**
 * A1 回归：语音缓存身份必须在 finalize ACK 后从 upload_id 迁移到服务端 message_uuid。
 *
 * 背景：语音文件先按 upload_id 落盘，而鉴权下载端点只认 message_uuid。若不迁移，
 * 缓存被 LRU 淘汰后回放会请求 /media/audio/<upload_id> —— 必然 404。
 *
 * 脚手架沿用同目录 voice_upload_state.test.tsx（渲染真实 useChatLogic + mock 边界）。
 */
import * as FileSystem from 'expo-file-system/legacy';
import React from 'react';
import { act, create, ReactTestRenderer } from 'react-test-renderer';
import { GestureResponderEvent } from 'react-native';
import { useChatLogic } from '../hooks/useChatLogic';
import { NetworkClient } from '../utils/network_client';
import { voiceRecorder } from '../utils/voice_recorder';
import { voicePlaybackManager } from '../utils/voice_playback_manager';

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
jest.mock('../utils/voice_playback_manager', () => ({
  voicePlaybackManager: {
    stop: jest.fn().mockResolvedValue(undefined),
    cacheLocal: jest.fn().mockResolvedValue('file://cached.m4a'),
    migrateCacheKey: jest.fn().mockResolvedValue('file://cache/message.m4a'),
    play: jest.fn().mockResolvedValue(undefined),
    clear: jest.fn().mockResolvedValue(undefined),
  },
}));
jest.mock('../utils/network_client', () => ({ NetworkClient: jest.fn() }));
jest.mock('../utils/voice_recorder', () => ({ voiceRecorder: {
  getPermission: jest.fn().mockResolvedValue('granted'), start: jest.fn(),
  stop: jest.fn().mockResolvedValue({ localUri: 'file://recording.m4a', durationMs: 1000 }),
  cancel: jest.fn(), dispose: jest.fn(),
} }));

describe('voice cache identity (A1)', () => {
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
      .mockResolvedValueOnce({ recordingId: 'up-1', localUri: 'file://recording.m4a' });
  });
  afterEach(async () => { if (root) await act(async () => root.unmount()); now.mockRestore(); jest.useRealTimers(); });

  /** 走完一次录音→提交，并让 finalize 返回可控 ACK。 */
  async function commitVoice(finalize: Promise<object>) {
    (NetworkClient as jest.Mock).mockImplementation(() => ({
      connectWs: jest.fn(), disconnectWs: jest.fn(),
      sendVoicePhase: jest.fn(async (payload: { phase: string }) => (payload.phase === 'finalize' ? finalize : { ok: true })),
      sendVoiceRecordingStarted: jest.fn(), sendVoiceRecordingCancelled: jest.fn(),
    }));
    await act(async () => { root = create(<Harness />); });
    await act(async () => { state.voiceInput.toggleMode(); });
    await act(async () => { await state.voiceInput.pressIn(event); });
    now.mockReturnValue(2000);
    await act(async () => { await state.voiceInput.pressOut(); });
  }

  it('migrates the cache key and re-points the bubble on the finalize ACK', async () => {
    let settle!: (value: object) => void;
    const finalize = new Promise<object>((resolve) => { settle = resolve; });
    await commitVoice(finalize);

    await act(async () => {
      settle({ ok: true, message_uuid: 'message-1', duration_ms: 1000 });
      await new Promise((resolve) => setImmediate(resolve));
    });

    expect(voicePlaybackManager.migrateCacheKey).toHaveBeenCalledWith('up-1', 'message-1');
    // 乐观气泡 uuid 仍是 upload_id，ACK 后必须把 audioLocalUri 指向迁移后的文件，否则点播放会 404。
    expect(state.messages.find((message) => message.uuid === 'up-1')?.audioLocalUri).toBe('file://cache/message.m4a');
  });

  it('plays the optimistic bubble through the ACK-resolved message uuid', async () => {
    let settle!: (value: object) => void;
    const finalize = new Promise<object>((resolve) => { settle = resolve; });
    await commitVoice(finalize);

    await act(async () => {
      settle({ ok: true, message_uuid: 'message-2', duration_ms: 1000 });
      await new Promise((resolve) => setImmediate(resolve));
    });
    (voicePlaybackManager.play as jest.Mock).mockClear();
    (voicePlaybackManager.cacheLocal as jest.Mock).mockClear();

    await act(async () => { await state.toggleVoicePlayback('up-1'); });

    // 播放/下载必须用 message_uuid（鉴权下载端点只认它），界面状态仍按 upload_id 回写。
    expect(voicePlaybackManager.play).toHaveBeenCalledWith('message-2', 'token', expect.any(Function));
    expect(voicePlaybackManager.cacheLocal).toHaveBeenCalledWith('message-2', 'file://cache/message.m4a');
  });
});

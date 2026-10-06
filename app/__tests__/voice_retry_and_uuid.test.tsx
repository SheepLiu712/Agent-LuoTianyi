/**
 * N3/N7 回归：失败语音的失败图标必须接到重传入口，且 user_voice 协议的 upload_id 必须是规范 UUID。
 */
jest.mock('react-native', () => {
  const Image = Object.assign('Image', { resolveAssetSource: () => ({ uri: 'asset://error.png' }) });
  return {
    Image, Text: 'Text', TextInput: 'TextInput', TouchableOpacity: 'TouchableOpacity', View: 'View',
    ActivityIndicator: 'ActivityIndicator',
    StyleSheet: { create: (styles: any) => styles },
  };
});

const mockRecording = {
  setOnRecordingStatusUpdate: jest.fn(),
  setProgressUpdateInterval: jest.fn(),
  prepareToRecordAsync: jest.fn().mockResolvedValue(undefined),
  startAsync: jest.fn().mockResolvedValue(undefined),
  stopAndUnloadAsync: jest.fn().mockResolvedValue(undefined),
  getStatusAsync: jest.fn().mockResolvedValue({ durationMillis: 1234 }),
  getURI: jest.fn(() => 'file://voice.m4a'),
};
jest.mock('expo-av', () => ({
  Audio: {
    Recording: jest.fn(() => mockRecording),
    AndroidOutputFormat: { MPEG_4: 'mpeg4' },
    AndroidAudioEncoder: { AAC: 'aac' },
    IOSOutputFormat: { MPEG4AAC: 'mpeg4aac' },
    IOSAudioQuality: { HIGH: 'high' },
    setAudioModeAsync: jest.fn().mockResolvedValue(undefined),
  },
}));
jest.mock('expo-file-system/legacy', () => ({
  deleteAsync: jest.fn().mockResolvedValue(undefined),
}));

import { MessageItem } from '../components/ChatBubbles';
import { randomUuid, isUuid } from '../utils/uuid';
import { VoiceRecorder } from '../utils/voice_recorder';

const failedVoice = {
  uuid: '3f2504e0-4f89-41d3-9a0c-0305e82c3301',
  type: 'audio' as const,
  content: '[语音消息]',
  isUser: true,
  durationMs: 4000,
  sendStatus: 'failed' as const,
};

describe('voice retry wiring (N3)', () => {
  it('routes the failed status slot to retry and the control slot to playback', () => {
    const onToggleVoicePlayback = jest.fn();
    const onRetryVoice = jest.fn();
    const bubble = MessageItem({ message: failedVoice, onToggleVoicePlayback, onRetryVoice }) as any;

    expect(bubble.props.onRetry).not.toBe(bubble.props.onPlay);
    bubble.props.onRetry();
    expect(onRetryVoice).toHaveBeenCalledWith(failedVoice.uuid);
    expect(onToggleVoicePlayback).not.toHaveBeenCalled();

    bubble.props.onPlay();
    expect(onToggleVoicePlayback).toHaveBeenCalledWith(failedVoice.uuid);
  });
});

describe('voice protocol identifiers (N7)', () => {
  it('generates RFC 4122 v4 UUIDs that satisfy the server upload_id validator', () => {
    const values = new Set(Array.from({ length: 200 }, () => randomUuid()));
    expect(values.size).toBe(200);
    for (const value of values) {
      expect(isUuid(value)).toBe(true);
      expect(value[14]).toBe('4');
      expect('89ab').toContain(value[19].toLowerCase());
    }
  });

  it('hands the recorder id out as a protocol-ready UUID', async () => {
    const recorder = new VoiceRecorder();
    const started = await recorder.start({ onMetering: jest.fn() });

    expect(isUuid(started.recordingId)).toBe(true);
  });
});

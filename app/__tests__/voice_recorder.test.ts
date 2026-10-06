const mockRecording = {
  setOnRecordingStatusUpdate: jest.fn(),
  setProgressUpdateInterval: jest.fn(),
  prepareToRecordAsync: jest.fn().mockResolvedValue(undefined),
  startAsync: jest.fn().mockResolvedValue(undefined),
  stopAndUnloadAsync: jest.fn().mockResolvedValue(undefined),
  getStatusAsync: jest.fn().mockResolvedValue({ durationMillis: 1234 }),
  getURI: jest.fn(() => 'file://voice.m4a'),
};
const mockRecordingConstructor = jest.fn(() => mockRecording);
const mockAudio = {
  Recording: mockRecordingConstructor,
  AndroidOutputFormat: { MPEG_4: 'mpeg4' },
  AndroidAudioEncoder: { AAC: 'aac' },
  IOSOutputFormat: { MPEG4AAC: 'mpeg4aac' },
  IOSAudioQuality: { HIGH: 'high' },
  getPermissionsAsync: jest.fn(),
  requestPermissionsAsync: jest.fn(),
  setAudioModeAsync: jest.fn().mockResolvedValue(undefined),
};

jest.mock('expo-av', () => ({ Audio: mockAudio }));
jest.mock('expo-file-system/legacy', () => ({
  deleteAsync: jest.fn().mockResolvedValue(undefined),
}));

import * as FileSystem from 'expo-file-system/legacy';
import { VoiceRecorder } from '../utils/voice_recorder';

describe('VoiceRecorder', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockRecording.stopAndUnloadAsync.mockResolvedValue(undefined);
    mockRecording.getURI.mockReturnValue('file://voice.m4a');
    mockRecording.getStatusAsync.mockResolvedValue({ durationMillis: 1234 });
  });

  it('normalizes granted, denied, and blocked permissions', async () => {
    const recorder = new VoiceRecorder();
    mockAudio.getPermissionsAsync
      .mockResolvedValueOnce({ granted: true })
      .mockResolvedValueOnce({ granted: false, canAskAgain: true })
      .mockResolvedValueOnce({ granted: false, canAskAgain: false });
    await expect(recorder.getPermission()).resolves.toBe('granted');
    await expect(recorder.getPermission()).resolves.toBe('denied');
    await expect(recorder.getPermission()).resolves.toBe('blocked');

    mockAudio.requestPermissionsAsync.mockResolvedValueOnce({ granted: false, canAskAgain: false });
    await expect(recorder.requestPermission()).resolves.toBe('blocked');
  });

  it('starts, stops, and returns the URI and duration', async () => {
    const recorder = new VoiceRecorder();
    const result = await recorder.start({ onMetering: jest.fn() });
    expect(result.localUri).toBe('file://voice.m4a');
    await expect(recorder.stop()).resolves.toEqual({ localUri: 'file://voice.m4a', durationMs: 1234 });
    await expect(recorder.stop()).resolves.toBeNull();
  });

  it('rejects duplicate start and makes cancel/dispose idempotent', async () => {
    const recorder = new VoiceRecorder();
    await recorder.start({ onMetering: jest.fn() });
    await expect(recorder.start({ onMetering: jest.fn() })).rejects.toThrow('already active');
    await recorder.cancel();
    await recorder.cancel();
    await recorder.dispose();
    expect(FileSystem.deleteAsync).toHaveBeenCalledWith('file://voice.m4a', { idempotent: true });
  });

  it('silently ignores cleanup failures', async () => {
    const recorder = new VoiceRecorder();
    await recorder.start({ onMetering: jest.fn() });
    (FileSystem.deleteAsync as jest.Mock).mockRejectedValueOnce(new Error('disk')); 
    await expect(recorder.cancel()).resolves.toBeUndefined();
  });

  it('samples metering at 80 ms and forwards the real metering field', async () => {
    const recorder = new VoiceRecorder();
    const onMetering = jest.fn();
    await recorder.start({ onMetering });

    expect(mockRecording.setProgressUpdateInterval).toHaveBeenCalledWith(80);
    const onStatus = mockRecording.setOnRecordingStatusUpdate.mock.calls[0][0] as (status: any) => void;
    onStatus({ isRecording: true, isDoneRecording: false, durationMillis: 120, metering: -30 });
    expect(onMetering).toHaveBeenCalledWith(-30);
  });

  it('reports a system interruption only after startAsync and only once', async () => {
    const recorder = new VoiceRecorder();
    const onInterrupted = jest.fn();
    // prepare 阶段（startAsync 之前）的初始状态不得被误判为中断。
    mockRecording.prepareToRecordAsync.mockImplementationOnce(async () => {
      const onStatus = mockRecording.setOnRecordingStatusUpdate.mock.calls[0][0] as (status: any) => void;
      onStatus({ isRecording: false, isDoneRecording: true, durationMillis: 0 });
    });

    await recorder.start({ onMetering: jest.fn(), onInterrupted });

    expect(onInterrupted).not.toHaveBeenCalled();
    const onStatus = mockRecording.setOnRecordingStatusUpdate.mock.calls[0][0] as (status: any) => void;
    onStatus({ isRecording: false, isDoneRecording: true, durationMillis: 900 });
    onStatus({ isRecording: false, isDoneRecording: true, durationMillis: 950 });
    expect(onInterrupted).toHaveBeenCalledTimes(1);
  });

  it('treats an iOS media services reset as an interruption', async () => {
    const recorder = new VoiceRecorder();
    const onInterrupted = jest.fn();
    await recorder.start({ onMetering: jest.fn(), onInterrupted });

    const onStatus = mockRecording.setOnRecordingStatusUpdate.mock.calls[0][0] as (status: any) => void;
    onStatus({ isRecording: false, isDoneRecording: false, mediaServicesDidReset: true, durationMillis: 500 });

    expect(onInterrupted).toHaveBeenCalledTimes(1);
  });

  it('does not report an interruption for the status produced by our own stop', async () => {
    const recorder = new VoiceRecorder();
    const onInterrupted = jest.fn();
    await recorder.start({ onMetering: jest.fn(), onInterrupted });
    const onStatus = mockRecording.setOnRecordingStatusUpdate.mock.calls[0][0] as (status: any) => void;

    mockRecording.stopAndUnloadAsync.mockImplementationOnce(async () => {
      onStatus({ isRecording: false, isDoneRecording: true, durationMillis: 1234 });
    });
    await recorder.stop();

    expect(onInterrupted).not.toHaveBeenCalled();
  });

  it('falls back to the cached duration when getStatusAsync no longer reports it', async () => {
    const recorder = new VoiceRecorder();
    await recorder.start({ onMetering: jest.fn() });
    const onStatus = mockRecording.setOnRecordingStatusUpdate.mock.calls[0][0] as (status: any) => void;
    onStatus({ isRecording: true, isDoneRecording: false, durationMillis: 2200 });
    mockRecording.getStatusAsync.mockResolvedValueOnce({ durationMillis: 0 });

    await expect(recorder.stop()).resolves.toEqual({ localUri: 'file://voice.m4a', durationMs: 2200 });
  });

  it('treats an Android-style isRecording true->false transition as an interruption', async () => {
    const recorder = new VoiceRecorder();
    const onInterrupted = jest.fn();
    await recorder.start({ onMetering: jest.fn(), onInterrupted });
    const onStatus = mockRecording.setOnRecordingStatusUpdate.mock.calls[0][0] as (status: any) => void;

    // Android 原生状态没有 isDoneRecording / mediaServicesDidReset（AVManager 只给 canRecord/isRecording/durationMillis/metering）。
    onStatus({ isRecording: true, durationMillis: 400, metering: -20 });
    onStatus({ isRecording: false, durationMillis: 900 });

    expect(onInterrupted).toHaveBeenCalledTimes(1);
  });

  it('does not call an interrupted end during the pre-start window', async () => {
    const recorder = new VoiceRecorder();
    const onInterrupted = jest.fn();
    mockRecording.prepareToRecordAsync.mockImplementationOnce(async () => {
      const onStatus = mockRecording.setOnRecordingStatusUpdate.mock.calls[0][0] as (status: any) => void;
      onStatus({ isRecording: false, durationMillis: 0 });
    });

    await recorder.start({ onMetering: jest.fn(), onInterrupted });

    expect(onInterrupted).not.toHaveBeenCalled();
  });

  it('releases the recorder handle when prepare/start fails', async () => {
    const recorder = new VoiceRecorder();
    mockRecording.prepareToRecordAsync.mockRejectedValueOnce(new Error('mic busy'));

    await expect(recorder.start({ onMetering: jest.fn() })).rejects.toThrow('mic busy');

    // 必须就地 unload，否则 expo-av 保留 _recorderExists，之后所有录音只能重启 App 才能恢复。
    expect(mockRecording.stopAndUnloadAsync).toHaveBeenCalled();
  });
});

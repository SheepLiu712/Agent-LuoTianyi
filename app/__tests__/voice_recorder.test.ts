const mockRecording = {
  setOnRecordingStatusUpdate: jest.fn(),
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
});

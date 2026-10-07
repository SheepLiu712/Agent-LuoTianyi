import * as FileSystem from 'expo-file-system/legacy';
import { VoiceRecorder } from '../utils/voice_recorder';

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

jest.mock('expo-av', () => ({ get Audio() { return mockAudio; } }));
jest.mock('expo-file-system/legacy', () => ({
  deleteAsync: jest.fn().mockResolvedValue(undefined),
}));


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
    expect(mockRecording.setProgressUpdateInterval).toHaveBeenCalledWith(80);
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

it('reports unexpected native stop once but not prepare or explicit stop/cancel', async () => {
  const recorder = new VoiceRecorder();
  const interrupted = jest.fn();
  await recorder.start({ onMetering: jest.fn(), onInterrupted: interrupted });
  const callback = mockRecording.setOnRecordingStatusUpdate.mock.calls.at(-1)![0];
  callback({ isRecording: false }); callback({ isRecording: false });
  expect(interrupted).toHaveBeenCalledTimes(1);
  await recorder.cancel();
  callback({ isRecording: false });
  expect(interrupted).toHaveBeenCalledTimes(1);
  interrupted.mockClear();
  await recorder.start({ onMetering: jest.fn(), onInterrupted: interrupted });
  const normalCallback = mockRecording.setOnRecordingStatusUpdate.mock.calls.at(-1)![0];
  mockRecording.stopAndUnloadAsync.mockImplementationOnce(async () => normalCallback({ isRecording: false }));
  await recorder.stop();
  expect(interrupted).not.toHaveBeenCalled();
});

it.each(['prepare', 'start'])('cancellation while native %s waits cleans the late recorder', async (phase) => {
  let finish!: () => void;
  const gate = new Promise<void>((resolve) => { finish = resolve; });
  const method = phase === 'prepare' ? mockRecording.prepareToRecordAsync : mockRecording.startAsync;
  method.mockReturnValueOnce(gate);
  const recorder = new VoiceRecorder();
  const pending = recorder.start({ onMetering: jest.fn() });
  const rejected = expect(pending).rejects.toThrow('cancelled');
  await Promise.resolve(); await Promise.resolve();
  const cleanup = recorder.cancel();
  finish();
  await rejected; await cleanup;
  expect(FileSystem.deleteAsync).toHaveBeenCalledWith('file://voice.m4a', { idempotent: true });
  await expect(recorder.stop()).resolves.toBeNull();
  await recorder.start({ onMetering: jest.fn() });
  await recorder.cancel();
});

it('cleans prepared media when native start fails', async () => {
  const recorder = new VoiceRecorder();
  mockRecording.startAsync.mockRejectedValueOnce(new Error('microphone lost'));
  await expect(recorder.start({ onMetering: jest.fn() })).rejects.toThrow('microphone lost');
  expect(FileSystem.deleteAsync).toHaveBeenCalledWith('file://voice.m4a', { idempotent: true });
  await expect(recorder.stop()).resolves.toBeNull();
});



it('creates a distinct UUID for each recording that can be used as upload_id', async () => {
  const recorder = new VoiceRecorder();
  const first = await recorder.start({ onMetering: jest.fn() });
  await recorder.stop();
  const second = await recorder.start({ onMetering: jest.fn() });
  await recorder.cancel();
  for (const result of [first, second]) {
    expect(result.recordingId).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i);
  }
  expect(second.recordingId).not.toBe(first.recordingId);
});

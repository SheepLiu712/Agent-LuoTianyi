jest.mock('expo-av', () => ({ Audio: { Sound: jest.fn() } }));
jest.mock('expo-file-system/legacy', () => ({
  EncodingType: { Base64: 'base64' },
  documentDirectory: 'file://documents/',
  makeDirectoryAsync: jest.fn(),
  getInfoAsync: jest.fn(),
  writeAsStringAsync: jest.fn(),
  moveAsync: jest.fn(),
  copyAsync: jest.fn(),
  deleteAsync: jest.fn().mockResolvedValue(undefined),
}));

import * as FileSystem from 'expo-file-system/legacy';
import { VoicePlaybackManager } from '../utils/voice_playback_manager';

describe('VoicePlaybackManager cache/download seam', () => {
  beforeEach(() => jest.clearAllMocks());

  it('uses message_uuid cache paths and injectable authenticated download with atomic move', async () => {
    (FileSystem.getInfoAsync as jest.Mock).mockResolvedValueOnce({ exists: false })
      .mockResolvedValueOnce({ exists: true, size: 12 });
    const download = jest.fn().mockResolvedValue(undefined);
    const manager = new VoicePlaybackManager({ download });

    await expect(manager.ensureCached('message_uuid', 'token')).resolves.toBe('file://documents/voice_cache/message_uuid.m4a');
    expect(download).toHaveBeenCalledWith(
      'message_uuid',
      expect.stringMatching(/message_uuid\.m4a\.tmp-/),
      'token',
    );
    expect(FileSystem.moveAsync).toHaveBeenCalledWith({
      from: expect.stringMatching(/message_uuid\.m4a\.tmp-/),
      to: 'file://documents/voice_cache/message_uuid.m4a',
    });
  });

  it('coalesces concurrent downloads and allows retry after failure', async () => {
    (FileSystem.getInfoAsync as jest.Mock).mockResolvedValue({ exists: false });
    let rejectDownload: ((error: Error) => void) | undefined;
    const download = jest.fn().mockImplementation(() => new Promise<void>((_, reject) => { rejectDownload = reject; }));
    const manager = new VoicePlaybackManager({ download });
    const first = manager.ensureCached('same', 'token');
    const second = manager.ensureCached('same', 'token');
    await new Promise((resolve) => setImmediate(resolve));
    expect(download).toHaveBeenCalledTimes(1);
    rejectDownload?.(new Error('network'));
    await expect(first).rejects.toThrow('network');
    await expect(second).rejects.toThrow('network');
    download.mockResolvedValue(undefined);
    (FileSystem.getInfoAsync as jest.Mock).mockResolvedValueOnce({ exists: false }).mockResolvedValueOnce({ exists: true, size: 1 });
    await expect(manager.ensureCached('same', 'token')).resolves.toContain('/same.m4a');
    expect(download).toHaveBeenCalledTimes(2);
  });

  it('reports cache hit and miss', async () => {
    (FileSystem.getInfoAsync as jest.Mock).mockResolvedValueOnce({ exists: true, size: 2 }).mockResolvedValueOnce({ exists: false });
    const manager = new VoicePlaybackManager({ download: jest.fn() });
    await expect(manager.getCachedUri('hit')).resolves.toContain('/hit.m4a');
    await expect(manager.getCachedUri('miss')).resolves.toBeNull();
  });

  it('keeps one active sound, toggles the same uuid, and resets on finish', async () => {
    const sounds: any[] = [];
    (require('expo-av').Audio.Sound as jest.Mock).mockImplementation(() => {
      const sound = {
        loadAsync: jest.fn().mockResolvedValue(undefined),
        playAsync: jest.fn().mockResolvedValue(undefined),
        stopAsync: jest.fn().mockResolvedValue(undefined),
        unloadAsync: jest.fn().mockResolvedValue(undefined),
        setOnPlaybackStatusUpdate: jest.fn((callback) => { sound.callback = callback; }),
        callback: undefined as ((status: any) => void) | undefined,
      };
      sounds.push(sound);
      return sound;
    });
    (FileSystem.getInfoAsync as jest.Mock).mockResolvedValue({ exists: true, size: 1 });
    const manager = new VoicePlaybackManager({ download: jest.fn() });
    const state = jest.fn();
    await manager.play('a', 'token', state);
    await manager.play('b', 'token');
    expect(sounds[0].stopAsync).toHaveBeenCalled();
    expect(sounds[0].unloadAsync).toHaveBeenCalled();
    await manager.play('b', 'token');
    expect(sounds[1].stopAsync).toHaveBeenCalled();
    expect(sounds[1].unloadAsync).toHaveBeenCalled();
    await manager.play('c', 'token');
    sounds[2].callback?.({ isLoaded: true, didJustFinish: true });
    await Promise.resolve();
    expect(sounds[2].stopAsync).toHaveBeenCalled();
    await manager.stop();
    await manager.stop();
  });

  it('clear stops playback and deletes the cache directory', async () => {
    const sound = {
      loadAsync: jest.fn().mockResolvedValue(undefined), playAsync: jest.fn().mockResolvedValue(undefined),
      stopAsync: jest.fn().mockResolvedValue(undefined), unloadAsync: jest.fn().mockResolvedValue(undefined),
      setOnPlaybackStatusUpdate: jest.fn(),
    };
    (require('expo-av').Audio.Sound as jest.Mock).mockReturnValue(sound);
    (FileSystem.getInfoAsync as jest.Mock).mockResolvedValue({ exists: true, size: 1 });
    const manager = new VoicePlaybackManager({ download: jest.fn() });
    await manager.play('clear-me', 'token');
    await manager.clear();
    expect(sound.stopAsync).toHaveBeenCalled();
    expect(sound.unloadAsync).toHaveBeenCalled();
    expect(FileSystem.deleteAsync).toHaveBeenCalledWith('file://documents/voice_cache', { idempotent: true });
  });

  it('evicts the oldest idle entry but protects playing and downloading entries', async () => {
    const manager = new VoicePlaybackManager({ download: jest.fn() });
    (FileSystem.getInfoAsync as jest.Mock).mockImplementation(async (uri: string) => ({
      exists: true,
      size: uri.includes('/new.m4a') ? 60 * 1024 * 1024 : 40 * 1024 * 1024,
    }));
    await manager.cacheLocal('old', 'file://old');
    await manager.cacheLocal('protected', 'file://protected');
    (manager as any).entries.get('old').touched = 1;
    (manager as any).entries.get('protected').touched = 2;
    (manager as any).entries.get('protected').playing = true;
    await manager.cacheLocal('new', 'file://new');
    expect(FileSystem.deleteAsync).toHaveBeenCalledWith(expect.stringContaining('/old.m4a'), { idempotent: true });
    expect((manager as any).entries.has('protected')).toBe(true);
  });

  it('migrates the cache key from upload_id to message_uuid after the finalize ACK', async () => {
    const manager = new VoicePlaybackManager({ download: jest.fn() });
    (FileSystem.getInfoAsync as jest.Mock).mockImplementation(async (uri: string) => ({
      exists: !uri.includes('message-uuid'),
      size: 42,
    }));

    await manager.migrateCacheKey('upload-id', 'message-uuid');

    expect(FileSystem.moveAsync).toHaveBeenCalledWith({
      from: 'file://documents/voice_cache/upload-id.m4a',
      to: 'file://documents/voice_cache/message-uuid.m4a',
    });
    expect((manager as any).entries.has('upload-id')).toBe(false);
    expect((manager as any).entries.get('message-uuid')).toMatchObject({
      uri: 'file://documents/voice_cache/message-uuid.m4a',
      size: 42,
    });
  });

  it('drops the orphan upload_id file when the message_uuid cache already exists', async () => {
    const manager = new VoicePlaybackManager({ download: jest.fn() });
    (FileSystem.getInfoAsync as jest.Mock).mockResolvedValue({ exists: true, size: 42 });

    await manager.migrateCacheKey('upload-id', 'message-uuid');

    expect(FileSystem.moveAsync).not.toHaveBeenCalled();
    expect(FileSystem.deleteAsync).toHaveBeenCalledWith('file://documents/voice_cache/upload-id.m4a', { idempotent: true });
  });

  it('does nothing when there is no cached upload_id file', async () => {
    const manager = new VoicePlaybackManager({ download: jest.fn() });
    (FileSystem.getInfoAsync as jest.Mock).mockResolvedValue({ exists: false });

    await manager.migrateCacheKey('upload-id', 'message-uuid');
    await manager.migrateCacheKey('same', 'same');

    expect(FileSystem.moveAsync).not.toHaveBeenCalled();
    expect(FileSystem.deleteAsync).not.toHaveBeenCalled();
  });

  it('notifies idle when playback finishes so the bubble leaves the stop icon', async () => {
    const sounds: any[] = [];
    (require('expo-av').Audio.Sound as jest.Mock).mockImplementation(() => {
      const sound = {
        loadAsync: jest.fn().mockResolvedValue(undefined),
        playAsync: jest.fn().mockResolvedValue(undefined),
        stopAsync: jest.fn().mockResolvedValue(undefined),
        unloadAsync: jest.fn().mockResolvedValue(undefined),
        setOnPlaybackStatusUpdate: jest.fn((callback) => { sound.callback = callback; }),
        callback: undefined as ((status: any) => void) | undefined,
      };
      sounds.push(sound);
      return sound;
    });
    (FileSystem.getInfoAsync as jest.Mock).mockResolvedValue({ exists: true, size: 1 });
    const manager = new VoicePlaybackManager({ download: jest.fn() });
    const states: string[] = [];

    await manager.play('x', 'token', (state) => states.push(state));
    sounds[0].callback?.({ isLoaded: true, didJustFinish: true });
    await new Promise((resolve) => setImmediate(resolve));

    expect(states).toEqual(['loading', 'playing', 'idle']);
    expect(sounds[0].stopAsync).toHaveBeenCalled();
  });

  it('notifies idle for the preempted uuid but not for the new one', async () => {
    const sounds: any[] = [];
    (require('expo-av').Audio.Sound as jest.Mock).mockImplementation(() => {
      const sound = {
        loadAsync: jest.fn().mockResolvedValue(undefined),
        playAsync: jest.fn().mockResolvedValue(undefined),
        stopAsync: jest.fn().mockResolvedValue(undefined),
        unloadAsync: jest.fn().mockResolvedValue(undefined),
        setOnPlaybackStatusUpdate: jest.fn(),
      };
      sounds.push(sound);
      return sound;
    });
    (FileSystem.getInfoAsync as jest.Mock).mockResolvedValue({ exists: true, size: 1 });
    const manager = new VoicePlaybackManager({ download: jest.fn() });
    const first: string[] = [];
    const second: string[] = [];

    await manager.play('a', 'token', (state) => first.push(state));
    await manager.play('b', 'token', (state) => second.push(state));

    expect(first).toEqual(['loading', 'playing', 'idle']);
    expect(second).toEqual(['loading', 'playing']);
  });

  it('accounts the target file size when the destination already exists', async () => {
    const manager = new VoicePlaybackManager({ download: jest.fn() });
    (FileSystem.getInfoAsync as jest.Mock).mockImplementation(async (uri: string) => ({
      exists: true,
      size: uri.includes('message-uuid') ? 3000 : 1000,
    }));

    const uri = await manager.migrateCacheKey('upload-id', 'message-uuid');

    expect(uri).toBe('file://documents/voice_cache/message-uuid.m4a');
    // 目标已存在时沿用源文件大小会让 LRU 少算 2000B。
    expect((manager as any).entries.get('message-uuid').size).toBe(3000);
  });

  it('returns null when there is nothing to migrate', async () => {
    const manager = new VoicePlaybackManager({ download: jest.fn() });
    (FileSystem.getInfoAsync as jest.Mock).mockResolvedValue({ exists: false });

    await expect(manager.migrateCacheKey('upload-id', 'message-uuid')).resolves.toBeNull();
    await expect(manager.migrateCacheKey('same', 'same')).resolves.toBeNull();
  });
});

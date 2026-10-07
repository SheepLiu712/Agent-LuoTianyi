import { Audio } from 'expo-av';
import * as FileSystem from 'expo-file-system/legacy';
import { readFileSync } from 'fs';
import { join } from 'path';
import { VoicePlaybackManager, VOICE_CACHE_LIMIT_BYTES } from '../utils/voice_playback_manager';
import { VoiceFileSystem } from './helpers/voice_filesystem';

jest.mock('expo-av', () => ({ Audio: { Sound: jest.fn() } }));
jest.mock('expo-file-system/legacy', () => jest.requireActual('./helpers/voice_filesystem').createVoiceFileSystem());
const fs = FileSystem as unknown as VoiceFileSystem;
const uri = VoicePlaybackManager.cacheUri;
const tick = () => new Promise<void>((resolve) => setImmediate(resolve));
function deferred() {
  let resolve!: () => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<void>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
const sample = readFileSync(join(__dirname, 'fixtures/voice-cache.m4a'));
// ISO BMFF permits a trailing free box: keep valid AAC media while padding to exactly 1 MiB.
const padding = Buffer.alloc(1024 * 1024 - sample.length);
padding.writeUInt32BE(padding.length); padding.write('free', 4);
const oneMiB = Buffer.concat([sample, padding]);
const totalAudio = () => [...fs.files].filter(([path]) => path.endsWith('.m4a') && path.includes('/voice_cache/'))
  .reduce((sum, [, file]) => sum + file.data.length, 0);

function setup() {
  const download = jest.fn(async (_uuid: string, destination: string, _token: string, _signal?: AbortSignal) => { fs.put(destination, sample); });
  return { download, manager: new VoicePlaybackManager({ download }) };
}

describe('persistent voice cache and playback', () => {
  let sound: Record<string, jest.Mock>;
  beforeEach(() => {
    fs.files.clear(); jest.clearAllMocks();
    sound = Object.fromEntries(['loadAsync', 'playAsync', 'stopAsync', 'unloadAsync', 'setOnPlaybackStatusUpdate']
      .map((key) => [key, jest.fn().mockResolvedValue(undefined)]));
    (Audio.Sound as unknown as jest.Mock).mockImplementation(() => sound);
  });

  it('downloads only on cache miss, passes credentials, and atomically publishes one shared download', async () => {
    const { manager, download } = setup();
    await manager.initialize();
    expect(download).not.toHaveBeenCalled();
    const result = await Promise.all([manager.ensureCached('message', 'token'), manager.ensureCached('message', 'token')]);
    expect(result).toEqual([uri('message'), uri('message')]);
    expect(download).toHaveBeenCalledTimes(1);
    expect(download).toHaveBeenCalledWith('message', expect.stringContaining('message.m4a.tmp-'), 'token', expect.any(AbortSignal));
    expect(FileSystem.moveAsync).toHaveBeenCalledWith({ from: expect.stringContaining('message.m4a.tmp-'), to: uri('message') });
    expect(fs.files.get(uri('message'))?.data).toEqual(sample);
    await manager.ensureCached('message', 'token');
    expect(download).toHaveBeenCalledTimes(1);
  });

  it('uses Bearer authentication in the production download adapter', async () => {
    const originalFetch = globalThis.fetch;
    const originalReader = globalThis.FileReader;
    const fetchMock = jest.fn().mockResolvedValue({ ok: true, blob: async () => ({}) });
    globalThis.fetch = fetchMock;
    globalThis.FileReader = class {
      result = `data:audio/mp4;base64,${sample.toString('base64')}`;
      onloadend?: () => void;
      readAsDataURL() { this.onloadend?.(); }
    } as unknown as typeof FileReader;
    try {
      const manager = new VoicePlaybackManager();
      await manager.initialize();
      expect(fetchMock).not.toHaveBeenCalled();
      await manager.ensureCached('message', 'secret-token');
      expect(fetchMock).toHaveBeenCalledWith(expect.stringMatching(/\/media\/audio\/message$/), {
        headers: { Authorization: 'Bearer secret-token' }, signal: expect.any(AbortSignal),
      });
      expect(fs.files.get(uri('message'))?.data).toEqual(sample);
    } finally { globalThis.fetch = originalFetch; globalThis.FileReader = originalReader; }
  });

  it('cleans partial failures and retries', async () => {
    const { manager, download } = setup();
    download.mockImplementationOnce(async (_uuid, temp) => { fs.put(temp, sample); throw new Error('network'); });
    await expect(manager.ensureCached('retry', 'token')).rejects.toThrow('network');
    expect([...fs.files.keys()].some((path) => path.includes('.tmp-'))).toBe(false);
    expect(await manager.ensureCached('retry', 'token')).toBe(uri('retry'));
    expect(download).toHaveBeenCalledTimes(2);
  });

  it('counts 120 valid 1 MiB files across restarts and preserves last access order', async () => {
    fs.put('file://source', oneMiB);
    const first = setup().manager;
    for (let i = 0; i < 60; i++) await first.cacheLocal(`old-${i}`, 'file://source');
    const second = setup().manager;
    for (let i = 0; i < 60; i++) await second.cacheLocal(`new-${i}`, 'file://source');
    expect(totalAudio()).toBe(VOICE_CACHE_LIMIT_BYTES);
    for (let i = 0; i < 20; i++) expect(fs.files.has(uri(`old-${i}`))).toBe(false);
    await second.getCachedUri('old-20');
    const third = setup().manager;
    await third.cacheLocal('next', 'file://source');
    expect(totalAudio()).toBe(VOICE_CACHE_LIMIT_BYTES);
    expect(fs.files.has(uri('old-20'))).toBe(true);
    expect(fs.files.has(uri('old-21'))).toBe(false);
  });

  it('recovers old files with missing or corrupt index and deletes orphan temporary files', async () => {
    for (let i = 0; i < 120; i++) { fs.put(uri(`legacy-${i}`), oneMiB); fs.files.get(uri(`legacy-${i}`))!.modified = i; }
    fs.put('file://documents/voice_cache/index.json', '{broken');
    fs.put(`${uri('interrupted')}.tmp-1`, oneMiB);
    const { manager, download } = setup();
    await manager.initialize();
    expect(totalAudio()).toBe(VOICE_CACHE_LIMIT_BYTES);
    expect(fs.files.has(uri('legacy-0'))).toBe(false);
    expect([...fs.files.keys()].some((path) => path.includes('.tmp'))).toBe(false);
    expect(await manager.ensureCached('legacy-119', 'token')).toBe(uri('legacy-119'));
    expect(download).not.toHaveBeenCalled();
  });

  it('serializes an early finalize ACK behind the local copy and uses only the permanent identity after restart', async () => {
    fs.put('file://recording', sample);
    const { manager } = setup();
    const copying = manager.cacheLocal('upload', 'file://recording');
    const finalized = manager.finalizeUpload('upload', 'message');
    await Promise.all([copying, finalized]);
    expect(fs.files.has(uri('upload'))).toBe(false);
    expect(fs.files.get(uri('message'))?.data).toEqual(sample);
    // A late callback with the obsolete upload path must not recreate the old file.
    await manager.cacheLocal('upload', uri('upload'));
    expect(fs.files.has(uri('upload'))).toBe(false);
    const next = setup();
    await next.manager.ensureCached('message', 'token');
    expect(next.download).not.toHaveBeenCalled();
    expect(totalAudio()).toBe(sample.length);
  });

  it('keeps the already published message file and removes a duplicate upload file', async () => {
    fs.put(uri('upload'), sample); fs.put(uri('message'), sample);
    const { manager } = setup();
    await manager.finalizeUpload('upload', 'message');
    expect(totalAudio()).toBe(sample.length);
    expect(fs.files.has(uri('upload'))).toBe(false);
  });

  it('protects playing audio during eviction and toggles/reset states', async () => {
    fs.put('file://source', oneMiB);
    const { manager } = setup();
    await manager.cacheLocal('playing', 'file://source');
    const state = jest.fn();
    await manager.play('playing', 'token', state);
    for (let i = 0; i < 100; i++) await manager.cacheLocal(`other-${i}`, 'file://source');
    expect(fs.files.has(uri('playing'))).toBe(true);
    expect(totalAudio()).toBe(VOICE_CACHE_LIMIT_BYTES);
    await manager.play('playing', 'token');
    expect(sound.stopAsync).toHaveBeenCalled();
    expect(sound.unloadAsync).toHaveBeenCalled();
    expect(state).toHaveBeenLastCalledWith('idle');
  });

  it('stops the previous sound on switching and resets on natural completion', async () => {
    fs.put(uri('a'), sample); fs.put(uri('b'), sample);
    const { manager } = setup();
    const state = jest.fn();
    await manager.play('a', 'token', state);
    await manager.play('b', 'token');
    expect(state).toHaveBeenLastCalledWith('idle');
    expect(sound.stopAsync).toHaveBeenCalledTimes(1);
    sound.setOnPlaybackStatusUpdate.mock.calls.at(-1)[0]({ isLoaded: true, didJustFinish: true });
    await tick();
    expect(sound.stopAsync).toHaveBeenCalledTimes(2);
  });

  it('does not delete a downloading file during eviction', async () => {
    const gate = deferred();
    const { manager, download } = setup();
    let temporary = '';
    download.mockImplementationOnce(async (_uuid, temp) => { temporary = temp; fs.put(temp, oneMiB); await gate.promise; });
    const pending = manager.ensureCached('downloading', 'token');
    await tick();
    fs.put('file://source', oneMiB);
    for (let i = 0; i < 101; i++) await manager.cacheLocal(`idle-${i}`, 'file://source');
    expect(fs.files.has(temporary)).toBe(true);
    gate.resolve(); await pending;
    expect(fs.files.has(uri('downloading'))).toBe(true);
    expect(totalAudio()).toBe(VOICE_CACHE_LIMIT_BYTES);
  });

  it.each(['download', 'load'])('invalidates pending %s when stopped', async (stage) => {
    const gate = deferred();
    const { manager, download } = setup();
    if (stage === 'load') { fs.put(uri('pending'), sample); sound.loadAsync.mockReturnValue(gate.promise); }
    else download.mockImplementationOnce(async (_uuid, temp) => { await gate.promise; fs.put(temp, sample); });
    const state = jest.fn();
    const playing = manager.play('pending', 'token', state);
    await tick();
    await manager.stop();
    gate.resolve(); await playing;
    expect(sound.playAsync).not.toHaveBeenCalled();
    expect(state).toHaveBeenLastCalledWith('idle');
    if (stage === 'load') expect(sound.unloadAsync).toHaveBeenCalled();
  });

  it('aborts and drains downloads before logout cleanup, without resurrecting old audio', async () => {
    const gate = deferred();
    const { manager, download } = setup();
    // Deliberately ignore abort: clear must still wait for a late writer before deleting the directory.
    download.mockImplementationOnce(async (_uuid, temp) => { await gate.promise; fs.put(temp, sample); });
    const pending = manager.ensureCached('old', 'old-token');
    const rejected = expect(pending).rejects.toThrow('voice cache was cleared');
    await tick();
    const clearing = manager.clear();
    expect(download.mock.calls[0][3]?.aborted).toBe(true);
    await expect(manager.cacheLocal('late', 'file://source')).rejects.toThrow('voice cache was cleared');
    await expect(manager.ensureCached('late', 'token')).rejects.toThrow('voice cache was cleared');
    gate.resolve(); await clearing; await rejected;
    expect([...fs.files.keys()].filter((path) => path.includes('/voice_cache/'))).toEqual([]);
    expect(await manager.ensureCached('new', 'new-token')).toBe(uri('new'));
    expect(fs.files.has(uri('old'))).toBe(false);
  });
});

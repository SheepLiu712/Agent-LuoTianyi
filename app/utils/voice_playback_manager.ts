import { Audio } from 'expo-av';
import * as FileSystem from 'expo-file-system/legacy';
import { server_config } from '../config';

export type VoicePlaybackState = 'idle' | 'loading' | 'playing' | 'failed';

export interface VoicePlaybackNetwork {
  download: (messageUuid: string, destination: string, token: string, signal?: AbortSignal) => Promise<void>;
}

type CacheEntry = { uri: string; size: number; touched: number; playing: boolean };

const CACHE_LIMIT = 100 * 1024 * 1024;
const cacheDir = () => `${FileSystem.documentDirectory}voice_cache`;

async function responseToBase64(response: Response): Promise<string> {
  const blob = await response.blob();
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onloadend = () => {
      const value = reader.result;
      if (typeof value !== 'string' || !value.includes(',')) reject(new Error('audio response is empty'));
      else resolve(value.slice(value.indexOf(',') + 1));
    };
    reader.onerror = () => reject(new Error('audio response could not be read'));
    reader.readAsDataURL(blob);
  });
}

export class VoicePlaybackManager {
  private readonly entries = new Map<string, CacheEntry>();
  private readonly downloads = new Map<string, Promise<string>>();
  private readonly aliases = new Map<string, string>();
  private readonly controllers = new Map<string, AbortController>();
  private diskQueue: Promise<unknown> = Promise.resolve();
  private initialized = false;
  private generation = 0;
  private clearing: Promise<void> | null = null;
  private loadingUuid: string | null = null;
  private tempSequence = 0;
  private sound: Audio.Sound | null = null;
  private playingUuid: string | null = null;
  private requestId = 0;
  private onState?: (state: VoicePlaybackState) => void;

  constructor(private readonly network: VoicePlaybackNetwork = {
    download: async (uuid, destination, token, signal) => {
      const response = await fetch(`${server_config.BASE_URL}/media/audio/${encodeURIComponent(uuid)}`, {
        headers: { Authorization: `Bearer ${token}` },
        signal,
      });
      if (!response.ok) throw new Error(`audio download failed (${response.status})`);
      const base64 = await responseToBase64(response);
      await FileSystem.writeAsStringAsync(destination, base64, { encoding: FileSystem.EncodingType.Base64 });
    },
  }) {}

  static cacheUri(uuid: string) { return `${cacheDir()}/${uuid}.m4a`; }

  // All filesystem mutations and index snapshots are serialized. Network I/O stays outside this queue.
  private onDisk<T>(operation: () => Promise<T>): Promise<T> {
    const result = this.diskQueue.then(operation);
    this.diskQueue = result.catch(() => undefined);
    return result;
  }

  private checkGeneration(generation: number) {
    if (generation !== this.generation || this.clearing) throw new Error('voice cache was cleared');
  }

  private canonical(uuid: string) { return this.aliases.get(uuid) || uuid; }

  private async saveIndex() {
    const touched = Object.fromEntries([...this.entries].map(([uuid, entry]) => [uuid, entry.touched]));
    const uri = `${cacheDir()}/index.json`;
    await FileSystem.writeAsStringAsync(`${uri}.tmp`, JSON.stringify(touched));
    await FileSystem.moveAsync({ from: `${uri}.tmp`, to: uri });
  }

  private async restore() {
    if (this.initialized) return;
    await FileSystem.makeDirectoryAsync(cacheDir(), { intermediates: true });
    let touched: Record<string, number> = {};
    try {
      const parsed = JSON.parse(await FileSystem.readAsStringAsync(`${cacheDir()}/index.json`));
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) touched = parsed;
    } catch { /* Missing or damaged metadata: recover sizes and timestamps from actual files. */ }
    this.entries.clear();
    for (const name of await FileSystem.readDirectoryAsync(cacheDir())) {
      if (name === 'index.json') continue;
      const uri = `${cacheDir()}/${name}`;
      if (!name.endsWith('.m4a')) {
        await FileSystem.deleteAsync(uri, { idempotent: true });
        continue;
      }
      const info = await FileSystem.getInfoAsync(uri);
      if (!info.exists || info.isDirectory) continue;
      const uuid = name.slice(0, -4);
      this.entries.set(uuid, { uri, size: info.size, touched: Number.isFinite(touched[uuid])
        ? touched[uuid] : (info.modificationTime || 0) * 1000, playing: false });
    }
    await this.evictIfNeeded();
    await this.saveIndex();
    this.initialized = true;
  }

  async initialize(): Promise<void> {
    const generation = this.generation;
    return this.onDisk(async () => { this.checkGeneration(generation); await this.restore(); });
  }

  private async findCached(uuid: string): Promise<string | null> {
    const uri = VoicePlaybackManager.cacheUri(uuid);
    const info = await FileSystem.getInfoAsync(uri);
    if (!info.exists) { this.entries.delete(uuid); return null; }
    this.entries.set(uuid, { uri, size: info.size, touched: Date.now(),
      playing: this.playingUuid === uuid });
    return uri;
  }

  async getCachedUri(uuid: string): Promise<string | null> {
    const generation = this.generation;
    return this.onDisk(async () => {
      this.checkGeneration(generation);
      await this.restore();
      const uri = await this.findCached(this.canonical(uuid));
      await this.saveIndex();
      return uri;
    });
  }

  async cacheLocal(uuid: string, sourceUri: string): Promise<string> {
    const generation = this.generation;
    return this.onDisk(async () => {
      this.checkGeneration(generation);
      await this.restore();
      uuid = this.canonical(uuid);
      const uri = VoicePlaybackManager.cacheUri(uuid);
      if (!await this.findCached(uuid)) {
        const temp = `${uri}.tmp-${this.tempSequence++}`;
        try {
          await FileSystem.copyAsync({ from: sourceUri, to: temp });
          await FileSystem.moveAsync({ from: temp, to: uri });
        } finally { await FileSystem.deleteAsync(temp, { idempotent: true }); }
        await this.findCached(uuid);
      }
      await this.evictIfNeeded();
      await this.saveIndex();
      return uri;
    });
  }

  async finalizeUpload(uploadId: string, messageUuid: string): Promise<string | null> {
    const generation = this.generation;
    // Queued behind cacheLocal even if ACK beats the original copy operation.
    return this.onDisk(async () => {
      this.checkGeneration(generation);
      await this.restore();
      if (this.playingUuid === uploadId || this.loadingUuid === uploadId) await this.stop();
      const source = VoicePlaybackManager.cacheUri(uploadId);
      const destination = VoicePlaybackManager.cacheUri(messageUuid);
      if (uploadId !== messageUuid && await this.findCached(uploadId)) {
        if (await this.findCached(messageUuid)) await FileSystem.deleteAsync(source, { idempotent: true });
        else await FileSystem.moveAsync({ from: source, to: destination });
        this.entries.delete(uploadId);
      }
      this.aliases.set(uploadId, messageUuid);
      const uri = await this.findCached(messageUuid);
      await this.evictIfNeeded();
      await this.saveIndex();
      return uri;
    });
  }

  async ensureCached(uuid: string, token: string): Promise<string> {
    this.checkGeneration(this.generation);
    uuid = this.canonical(uuid);
    const existing = this.downloads.get(uuid);
    if (existing) return existing;
    const generation = this.generation;
    const controller = new AbortController();
    const uri = VoicePlaybackManager.cacheUri(uuid);
    const temp = `${uri}.tmp-${generation}-${this.tempSequence++}`;
    const promise = (async () => {
      try {
        const cached = await this.getCachedUri(uuid);
        if (cached) return cached;
        this.checkGeneration(generation);
        await this.network.download(uuid, temp, token, controller.signal);
        return await this.onDisk(async () => {
          this.checkGeneration(generation);
          await FileSystem.moveAsync({ from: temp, to: uri });
          await this.findCached(uuid);
          await this.evictIfNeeded();
          await this.saveIndex();
          return uri;
        });
      } finally {
        await this.onDisk(async () => { await FileSystem.deleteAsync(temp, { idempotent: true }); });
        this.downloads.delete(uuid);
        this.controllers.delete(uuid);
        if (generation === this.generation && !this.clearing) await this.onDisk(async () => {
          await this.evictIfNeeded();
          await this.saveIndex();
        });
      }
    })();
    this.downloads.set(uuid, promise);
    this.controllers.set(uuid, controller);
    return promise;
  }

  async play(uuid: string, token: string, onState?: (state: VoicePlaybackState) => void): Promise<void> {
    uuid = this.canonical(uuid);
    if (this.playingUuid === uuid) { await this.stop(); return; }
    const stopped = this.stop();
    const id = this.requestId;
    this.loadingUuid = uuid;
    this.onState = onState;
    onState?.('loading');
    let sound: Audio.Sound | null = null;
    try {
      await stopped;
      if (id !== this.requestId) return;
      const uri = await this.ensureCached(uuid, token);
      if (id !== this.requestId) return;
      sound = new Audio.Sound();
      await sound.loadAsync({ uri }, { shouldPlay: false }, false);
      if (id !== this.requestId) { await sound.unloadAsync(); return; }
      this.sound = sound;
      this.playingUuid = uuid;
      const entry = this.entries.get(uuid);
      if (entry) { entry.playing = true; entry.touched = Date.now(); }
      sound.setOnPlaybackStatusUpdate((status) => {
        if (id !== this.requestId || !status.isLoaded) return;
        if (status.didJustFinish) void this.stop();
      });
      await sound.playAsync();
      if (id === this.requestId) onState?.('playing');
    } catch (error) {
      if (id !== this.requestId) {
        await sound?.unloadAsync().catch(() => undefined);
        return;
      }
      await this.stop();
      await sound?.unloadAsync().catch(() => undefined);
      onState?.('failed');
      throw error;
    }
  }

  async stop(): Promise<void> {
    ++this.requestId;
    const sound = this.sound;
    const uuid = this.playingUuid;
    const notify = this.onState;
    this.onState = undefined;
    this.sound = null; this.playingUuid = null; this.loadingUuid = null;
    if (uuid) { const entry = this.entries.get(uuid); if (entry) entry.playing = false; }
    notify?.('idle');
    if (sound) { await sound.stopAsync().catch(() => undefined); await sound.unloadAsync().catch(() => undefined); }
  }

  async clear(): Promise<void> {
    if (this.clearing) return this.clearing;
    ++this.generation;
    const stopped = this.stop();
    const pending = [...this.downloads.values()];
    for (const controller of this.controllers.values()) controller.abort();
    const cleanup = (async () => {
      await stopped;
      await Promise.allSettled(pending);
      await this.onDisk(async () => {
        this.entries.clear(); this.aliases.clear();
        this.initialized = false;
        await FileSystem.deleteAsync(cacheDir(), { idempotent: true });
      });
    })();
    this.clearing = cleanup;
    try { await cleanup; } finally { this.clearing = null; }
  }

  private async evictIfNeeded() {
    let total = [...this.entries.values()].reduce((sum, entry) => sum + entry.size, 0);
    while (total > CACHE_LIMIT) {
      const candidate = [...this.entries.entries()]
        .filter(([uuid, entry]) => !entry.playing && uuid !== this.loadingUuid && !this.downloads.has(uuid))
        .sort((a, b) => a[1].touched - b[1].touched)[0];
      if (!candidate) break;
      await FileSystem.deleteAsync(candidate[1].uri, { idempotent: true });
      this.entries.delete(candidate[0]); total -= candidate[1].size;
    }
  }
}

export const voicePlaybackManager = new VoicePlaybackManager();
export const VOICE_CACHE_LIMIT_BYTES = CACHE_LIMIT;

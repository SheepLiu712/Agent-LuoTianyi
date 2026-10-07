import { Audio } from 'expo-av';
import * as FileSystem from 'expo-file-system/legacy';
import { server_config } from '../config';

export type VoicePlaybackState = 'idle' | 'loading' | 'playing' | 'failed';

export interface VoicePlaybackNetwork {
  download: (messageUuid: string, destination: string, token: string) => Promise<void>;
}

type CacheEntry = { uri: string; size: number; touched: number; playing: boolean; downloading: boolean };

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
  private sound: Audio.Sound | null = null;
  private playingUuid: string | null = null;
  private requestId = 0;
  private onState?: (state: VoicePlaybackState) => void;

  constructor(private readonly network: VoicePlaybackNetwork = {
    download: async (uuid, destination, token) => {
      const response = await fetch(`${server_config.BASE_URL}/media/audio/${encodeURIComponent(uuid)}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!response.ok) throw new Error(`audio download failed (${response.status})`);
      const base64 = await responseToBase64(response);
      await FileSystem.writeAsStringAsync(destination, base64, { encoding: FileSystem.EncodingType.Base64 });
    },
  }) {}

  static cacheUri(uuid: string) { return `${cacheDir()}/${uuid}.m4a`; }

  async getCachedUri(uuid: string): Promise<string | null> {
    const uri = VoicePlaybackManager.cacheUri(uuid);
    const info = await FileSystem.getInfoAsync(uri);
    if (!info.exists) return null;
    const size = typeof (info as { size?: number }).size === 'number' ? (info as { size: number }).size : 0;
    this.entries.set(uuid, { uri, size, touched: Date.now(), playing: this.playingUuid === uuid, downloading: this.downloads.has(uuid) });
    return uri;
  }

  async cacheLocal(uuid: string, sourceUri: string): Promise<string> {
    const uri = VoicePlaybackManager.cacheUri(uuid);
    await FileSystem.makeDirectoryAsync(cacheDir(), { intermediates: true });
    if (sourceUri !== uri) await FileSystem.copyAsync({ from: sourceUri, to: uri });
    const info = await FileSystem.getInfoAsync(uri);
    this.entries.set(uuid, { uri, size: typeof (info as { size?: number }).size === 'number' ? (info as { size: number }).size : 0, touched: Date.now(), playing: false, downloading: false });
    await this.evictIfNeeded();
    return uri;
  }

  /**
   * 把缓存键从 upload_id 迁移到服务端 message_uuid。
   *
   * 语音文件先按 upload_id 落盘，而鉴权下载端点只认 message_uuid；不迁移的话，
   * 缓存被 LRU 淘汰后回放会去请求 /media/audio/<upload_id> —— 必然 404。
   * 目标已存在时丢弃源文件，并按**目标文件真实大小**记账（沿用源大小会少算 LRU 占用）。
   */
  async migrateCacheKey(fromUuid: string, toUuid: string): Promise<string | null> {
    if (!fromUuid || !toUuid || fromUuid === toUuid) return null;
    const fromUri = VoicePlaybackManager.cacheUri(fromUuid);
    const source = await FileSystem.getInfoAsync(fromUri);
    if (!source.exists) return null;
    const toUri = VoicePlaybackManager.cacheUri(toUuid);
    const target = await FileSystem.getInfoAsync(toUri);
    await FileSystem.makeDirectoryAsync(cacheDir(), { intermediates: true });
    let size: number;
    if (target.exists) {
      size = typeof (target as { size?: number }).size === 'number' ? (target as { size: number }).size : 0;
      await FileSystem.deleteAsync(fromUri, { idempotent: true });
    } else {
      await FileSystem.moveAsync({ from: fromUri, to: toUri });
      size = typeof (source as { size?: number }).size === 'number' ? (source as { size: number }).size : 0;
    }
    this.entries.delete(fromUuid);
    this.entries.set(toUuid, { uri: toUri, size, touched: Date.now(), playing: false, downloading: false });
    await this.evictIfNeeded();
    return toUri;
  }

  async ensureCached(uuid: string, token: string): Promise<string> {
    const existing = this.downloads.get(uuid);
    if (existing) return existing;
    const cached = await this.getCachedUri(uuid);
    if (cached) return cached;
    const inFlightAfterCacheCheck = this.downloads.get(uuid);
    if (inFlightAfterCacheCheck) return inFlightAfterCacheCheck;
    const promise = (async () => {
      const uri = VoicePlaybackManager.cacheUri(uuid);
      const temp = `${uri}.tmp-${Date.now()}`;
      await FileSystem.makeDirectoryAsync(cacheDir(), { intermediates: true });
      this.entries.set(uuid, { uri, size: 0, touched: Date.now(), playing: false, downloading: true });
      try {
        await this.network.download(uuid, temp, token);
        await FileSystem.moveAsync({ from: temp, to: uri });
        const info = await FileSystem.getInfoAsync(uri);
        this.entries.set(uuid, { uri, size: typeof (info as { size?: number }).size === 'number' ? (info as { size: number }).size : 0, touched: Date.now(), playing: false, downloading: false });
        await this.evictIfNeeded();
        return uri;
      } catch (error) {
        await FileSystem.deleteAsync(temp, { idempotent: true }).catch(() => undefined);
        this.entries.delete(uuid);
        throw error;
      } finally { this.downloads.delete(uuid); }
    })();
    this.downloads.set(uuid, promise);
    return promise;
  }

  async play(uuid: string, token: string, onState?: (state: VoicePlaybackState) => void): Promise<void> {
    if (this.playingUuid === uuid) { await this.stop(); return; }
    const stopped = this.stop();
    const id = this.requestId;
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
    this.sound = null; this.playingUuid = null;
    if (uuid) { const entry = this.entries.get(uuid); if (entry) entry.playing = false; }
    notify?.('idle');
    if (sound) { await sound.stopAsync().catch(() => undefined); await sound.unloadAsync().catch(() => undefined); }
  }

  async clear(): Promise<void> {
    await this.stop();
    this.downloads.clear(); this.entries.clear();
    await FileSystem.deleteAsync(cacheDir(), { idempotent: true });
  }

  private async evictIfNeeded() {
    let total = [...this.entries.values()].reduce((sum, entry) => sum + entry.size, 0);
    while (total > CACHE_LIMIT) {
      const candidate = [...this.entries.entries()]
        .filter(([, entry]) => !entry.playing && !entry.downloading)
        .sort((a, b) => a[1].touched - b[1].touched)[0];
      if (!candidate) break;
      await FileSystem.deleteAsync(candidate[1].uri, { idempotent: true });
      this.entries.delete(candidate[0]); total -= candidate[1].size;
    }
  }
}

export const voicePlaybackManager = new VoicePlaybackManager();
export const VOICE_CACHE_LIMIT_BYTES = CACHE_LIMIT;

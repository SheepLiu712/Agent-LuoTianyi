import type { AccountSession } from '../account/credentials';

export type AvatarSide = 'user' | 'agent';
export type AvatarImage = string | null;
export interface AvatarSnapshot { revision: string; user: AvatarImage; agent: AvatarImage; sync_token?: string }
interface ServerState { pending: AvatarSide[]; revision?: string }
interface LocalAvatars {
  user?: AvatarImage;
  agent?: AvatarImage;
  servers: Record<string, ServerState>;
  lastServer?: string;
}
export interface AvatarState {
  user: AvatarImage;
  agent: AvatarImage;
  ready: boolean;
  syncing: boolean;
  pending: boolean;
  error: string | null;
}
interface Storage {
  getItem(key: string): Promise<string | null>;
  setItem(key: string, value: string): Promise<unknown>;
}
const sides: AvatarSide[] = ['user', 'agent'];
const writes = new Map<string, Promise<unknown>>();
export const emptyAvatars: AvatarState = { user: null, agent: null, ready: false, syncing: false, pending: false, error: null };

export function normalizeAvatarServer(url: string) {
  const parsed = new URL(url);
  return `${parsed.origin}${parsed.pathname.replace(/\/+$/, '')}`;
}

/** Owns one logged-in session. Disposing it prevents late network results from touching the local copy. */
export class AvatarSync {
  private local: LocalAvatars = { servers: {} };
  private state: AvatarState = { ...emptyAvatars };
  private versions = { user: 0, agent: 0 };
  private active = true;
  private foreground = true;
  private request?: AbortController;
  private syncPromise?: Promise<void>;
  private retryTimer?: ReturnType<typeof setTimeout>;
  private retryAttempt = 0;
  private lastSuccessfulCheck = 0;
  private listeners = new Set<(state: AvatarState) => void>();
  private key: string;
  private server: string;
  private syncToken = '';
  private static readonly FRESH_CHECK_MS = 5 * 60 * 1000;
  private static readonly RETRY_DELAYS_MS = [10_000, 30_000, 120_000];

  constructor(private session: AccountSession, private storage: Storage, private requestFetch: typeof fetch = fetch,
    private tokenStorage?: Storage) {
    this.key = `avatars:${encodeURIComponent(session.username)}`;
    this.server = normalizeAvatarServer(session.serverUrl);
  }

  subscribe(listener: (state: AvatarState) => void) {
    this.listeners.add(listener);
    listener(this.state);
    return () => { this.listeners.delete(listener); };
  }

  private publish(patch: Partial<AvatarState> = {}) {
    if (!this.active) return;
    this.state = { ...this.state, user: this.local.user ?? null, agent: this.local.agent ?? null,
      pending: Boolean(this.local.servers[this.server]?.pending.length), ...patch };
    this.listeners.forEach(listener => listener(this.state));
  }

  private persist() {
    const json = JSON.stringify(this.local);
    const next = (writes.get(this.key) ?? Promise.resolve()).catch(() => {}).then(() => this.storage.setItem(this.key, json));
    writes.set(this.key, next);
    return next;
  }

  async start() {
    try {
      await writes.get(this.key)?.catch(() => {});
      const saved = await this.storage.getItem(this.key);
      const token = await this.tokenStorage?.getItem(`${this.key}:${this.server}`);
      if (!this.active) return;
      this.syncToken = token || '';
      if (saved) this.local = JSON.parse(saved);
      if (!this.local.servers[this.server] || this.local.lastServer !== this.server) {
        this.local.servers[this.server] = { pending: sides.filter(side => this.local[side] !== undefined) };
      }
      this.local.lastServer = this.server;
      // The shared local images may have changed on a different server since the last session.
      this.local.servers[this.server].revision = undefined;
      this.publish({ ready: true });
      await this.sync(true);
    } catch {
      this.publish({ error: '无法读取或保存本地头像，请重试。' });
    }
  }

  async save(side: AvatarSide, image: AvatarImage) {
    if (!this.active || !this.state.ready) return;
    this.versions[side]++;
    this.local[side] = image;
    const pending = this.local.servers[this.server].pending;
    if (!pending.includes(side)) pending.push(side);
    this.publish({ error: null });
    try {
      await this.persist();
    } catch {
      this.publish({ error: '本地头像保存失败，请重试保存。' });
      return;
    }
    await this.sync(true);
  }

  private apply(snapshot: AvatarSnapshot, versions: typeof this.versions) {
    const remote = this.local.servers[this.server];
    for (const side of sides) {
      if (this.versions[side] === versions[side] && !remote.pending.includes(side)) this.local[side] = snapshot[side];
    }
    remote.revision = snapshot.revision;
    this.publish();
  }

  /** Start or join a check. A PUT response is itself a full snapshot, so no follow-up GET is needed. */
  sync(resetRetries = false): Promise<void> {
    if (!this.active || !this.state.ready || !this.foreground) return Promise.resolve();
    if (resetRetries) {
      this.retryAttempt = 0;
      this.clearRetry();
    }
    if (this.syncPromise) return this.syncPromise;

    this.publish({ syncing: true });
    const request = this.request = new AbortController();
    const timeout = setTimeout(() => request.abort(), 15_000);
    const operation = this.performSync().finally(() => {
      clearTimeout(timeout);
      this.request = undefined;
      this.publish({ syncing: false });
      if (this.syncPromise === operation) this.syncPromise = undefined;
    });
    this.syncPromise = operation;
    return operation;
  }

  private async performSync() {
    try {
      const remote = this.local.servers[this.server];
      if (remote.pending.length) await this.persist();
      if (!this.active) return;
      let uploaded = false;
      while (this.active && this.foreground) {
        const side = remote.pending[0];
        if (side) {
          const versions = { ...this.versions };
          const snapshot = await this.fetchSnapshot(side, this.local[side] ?? null);
          if (!this.active) return;
          if (this.versions[side] === versions[side]) remote.pending = remote.pending.filter(value => value !== side);
          this.apply(snapshot!, versions);
          await this.persist();
          uploaded = true;
          continue;
        }
        // Upload responses carry the complete snapshot; only a read-only sync needs a GET.
        if (!uploaded) {
          const versions = { ...this.versions };
          const snapshot = await this.fetchSnapshot();
          if (!this.active) return;
          if (snapshot) {
            this.apply(snapshot, versions);
            await this.persist();
          }
          if (remote.pending.length) continue;
        }
        break;
      }
      this.retryAttempt = 0;
      this.clearRetry();
      this.publish({ error: null });
    } catch {
      this.publish({ error: this.local.servers[this.server]?.pending.length
        ? '头像已在本机生效，同步失败。'
        : '头像同步失败。' });
      if (this.local.servers[this.server]?.pending.length) this.scheduleRetry();
    }
  }

  private clearRetry() {
    if (this.retryTimer) clearTimeout(this.retryTimer);
    this.retryTimer = undefined;
  }

  private scheduleRetry() {
    this.clearRetry();
    if (!this.active || !this.foreground || this.retryAttempt >= AvatarSync.RETRY_DELAYS_MS.length) return;
    const delay = AvatarSync.RETRY_DELAYS_MS[this.retryAttempt++];
    this.retryTimer = setTimeout(() => {
      this.retryTimer = undefined;
      void this.sync();
    }, delay);
  }

  setForeground(foreground: boolean): Promise<void> {
    this.foreground = foreground;
    if (!foreground) {
      this.clearRetry();
      return Promise.resolve();
    }
    if (this.state.ready && (this.local.servers[this.server]?.pending.length
      || Date.now() - this.lastSuccessfulCheck >= AvatarSync.FRESH_CHECK_MS)) return this.sync(true);
    return Promise.resolve();
  }

  /** Called on editor open; joins an in-flight request rather than starting another. */
  check() {
    this.retryAttempt = 0;
    this.clearRetry();
    return this.sync();
  }

  private async fetchSnapshot(side?: AvatarSide, image?: AvatarImage): Promise<AvatarSnapshot | null> {
    const revision = this.local.servers[this.server].revision;
    const options: RequestInit = {
      method: side ? 'PUT' : 'GET',
      headers: { Authorization: `Bearer ${this.syncToken || this.session.token}`, ...(side ? { 'Content-Type': 'application/json' }
        : revision ? { 'If-None-Match': revision } : {}) },
      ...(side ? { body: JSON.stringify({ image }) } : {}),
      signal: this.request?.signal,
    };
    const url = `${this.server}/avatars${side ? `/${side}` : ''}?username=${encodeURIComponent(this.session.username)}`;
    let response = await this.requestFetch(url, options);
    if (!this.active) return null;
    if (response.status === 401 && this.syncToken) {
      this.syncToken = '';
      await this.tokenStorage?.setItem(`${this.key}:${this.server}`, '');
      if (!this.active) return null;
      response = await this.requestFetch(url, { ...options,
        headers: { ...options.headers, Authorization: `Bearer ${this.session.token}` } });
    }
    if (!side && response.status === 304) {
      this.lastSuccessfulCheck = Date.now();
      const renewed = response.headers.get('X-Avatar-Token');
      if (this.active && renewed && renewed !== this.syncToken) {
        this.syncToken = renewed;
        await this.tokenStorage?.setItem(`${this.key}:${this.server}`, renewed);
      }
      return null;
    }
    if (!response.ok) throw new Error(`avatar_http_${response.status}`);
    const snapshot: AvatarSnapshot = await response.json();
    if (!this.active) return null;
    this.lastSuccessfulCheck = Date.now();
    if (snapshot.sync_token && snapshot.sync_token !== this.syncToken) {
      this.syncToken = snapshot.sync_token;
      await this.tokenStorage?.setItem(`${this.key}:${this.server}`, snapshot.sync_token);
    }
    return snapshot;
  }

  retry() {
    if (!this.state.ready) return this.start();
    this.retryAttempt = 0;
    this.clearRetry();
    return this.sync();
  }

  dispose() {
    this.active = false;
    this.clearRetry();
    this.request?.abort();
    this.listeners.clear();
  }
}

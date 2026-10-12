import { Audio } from 'expo-av';
import Constants from 'expo-constants';
import { Platform } from 'react-native';

import type {
  CallCapabilities,
  CallNativeAudioPort,
  CallSocketFactory,
  CallSwitchPort,
} from '../../types/call_transport';
import { server_config } from '../../config';
import { auth } from '../../components/auth';
import { CallSession } from './call_session';
import { CallTransportSession } from '../call_transport/call_transport';
import { createPlatformCallSocketFactory } from '../call_transport/websocket_adapter';
import { AndroidCallAudio, isAndroidCallAudioModuleAvailable } from '../call_audio/native_call_audio';

export type CallCapabilityReason =
  | 'available'
  | 'disabled'
  | 'untrusted_host'
  | 'provider_unavailable'
  | 'call_tts_unavailable'
  | 'summary_unavailable'
  | 'settlement_unavailable'
  | 'stage_binding_unavailable'
  | 'recovery_unavailable'
  | 'character_unavailable'
  | 'runtime_not_ready';

export interface ServerCallCapability {
  available: boolean;
  character_id: string;
  reason: CallCapabilityReason;
}

export interface CallAttemptPorts {
  session: CallSession;
  initializeNative(): Promise<boolean>;
  close(): Promise<void>;
}

export interface ProductionCallResolverOptions {
  characterId: string;
  switchPort: CallSwitchPort;
  fetchImpl?: typeof fetch;
  sockets?: CallSocketFactory;
  createNativeAudio?: () => AndroidCallAudio;
  nativeInitializeTimeoutMs?: number;
  nativeOwnership?: NativeCallOwnership;
  credentials?: { username: string; token: string };
}

export class NativeCallOwnership {
  private owner: symbol | null = null;

  available(): boolean {
    return this.owner === null;
  }

  acquire(owner: symbol): boolean {
    if (this.owner !== null) return false;
    this.owner = owner;
    return true;
  }

  release(owner: symbol): void {
    if (this.owner === owner) this.owner = null;
  }
}

const productionNativeOwnership = new NativeCallOwnership();

const CAPABILITY_REASONS = new Set<CallCapabilityReason>([
  'available', 'disabled', 'untrusted_host', 'provider_unavailable', 'call_tts_unavailable',
  'summary_unavailable', 'settlement_unavailable', 'stage_binding_unavailable', 'recovery_unavailable',
  'character_unavailable', 'runtime_not_ready',
]);

const clock = {
  monotonicMs: () => globalThis.performance?.now?.() ?? Date.now(),
  wallClockMs: () => Date.now(),
  setTimeout: (callback: () => void, delayMs: number) => setTimeout(callback, delayMs),
  clearTimeout: (handle: unknown) => clearTimeout(handle as ReturnType<typeof setTimeout>),
};

export class ProductionCallResolver {
  private readonly fetchImpl: typeof fetch;
  private readonly sockets: CallSocketFactory;
  private readonly createNativeAudio: () => AndroidCallAudio;
  private readonly nativeOwnership: NativeCallOwnership;
  private capability: ServerCallCapability | null = null;
  private readonly attempts = new Set<CallAttemptPorts>();
  private nativeOwner: CallAttemptPorts | null = null;
  private probeGeneration = 0;
  private closed = false;

  constructor(private readonly options: ProductionCallResolverOptions) {
    this.fetchImpl = options.fetchImpl ?? fetch;
    this.sockets = options.sockets ?? browserSocketFactory;
    this.createNativeAudio = options.createNativeAudio ?? (() => new AndroidCallAudio());
    this.nativeOwnership = options.nativeOwnership ?? productionNativeOwnership;
  }

  technicalNativeAvailable(): boolean {
    return Platform.OS === 'android' && Constants.executionEnvironment !== 'storeClient' && isAndroidCallAudioModuleAvailable();
  }

  async refreshCapability(): Promise<ServerCallCapability> {
    const generation = ++this.probeGeneration;
    const token = this.options.credentials?.token ?? auth.message_token;
    const characterId = this.options.characterId;
    if (!token) return this.storeUnavailable('runtime_not_ready');
    const url = `${server_config.BASE_URL.replace(/\/+$/, '')}/call/capability?character_id=${encodeURIComponent(this.options.characterId)}`;
    const response = await this.fetchImpl(url, {
      method: 'GET',
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!this.isCurrentProbe(generation, token, characterId)) return this.staleProbeResult(characterId);
    if (response.status === 401) throw new Error('CALL_AUTH_REQUIRED');
    if (!response.ok) return this.storeUnavailable('runtime_not_ready');
    const body = await response.json() as Partial<ServerCallCapability>;
    if (
      typeof body.available !== 'boolean' ||
      body.character_id !== characterId ||
      typeof body.reason !== 'string' ||
      !CAPABILITY_REASONS.has(body.reason as CallCapabilityReason) ||
      body.available !== (body.reason === 'available')
    ) throw new Error('INVALID_CALL_CAPABILITY_RESPONSE');
    if (!this.isCurrentProbe(generation, token, characterId)) return this.staleProbeResult(characterId);
    this.capability = body as ServerCallCapability;
    return this.capability;
  }

  currentCapabilities(): CallCapabilities {
    return {
      serverAvailable: this.capability?.available === true,
      nativeAvailable: this.technicalNativeAvailable() && this.nativeOwnership.available(),
    };
  }

  createAttempt(): CallAttemptPorts {
    if (this.closed) throw new Error('CALL_RESOLVER_CLOSED');
    if (!this.capability?.available) throw new Error('SERVER_CALL_UNAVAILABLE');
    if (!this.technicalNativeAvailable()) throw new Error('NATIVE_CALL_UNAVAILABLE');
    const username = this.options.credentials?.username ?? auth.username;
    const token = this.options.credentials?.token ?? auth.message_token;
    if (!username || !token) throw new Error('CALL_AUTH_REQUIRED');
    if (this.nativeOwner) throw new Error('NATIVE_INITIALIZATION_BUSY');
    const ownershipToken = Symbol('native-call-attempt');
    if (!this.nativeOwnership.acquire(ownershipToken)) throw new Error('NATIVE_INITIALIZATION_BUSY');
    let nativeAudio: AndroidCallAudio;
    try {
      nativeAudio = this.createNativeAudio();
    } catch (error) {
      this.nativeOwnership.release(ownershipToken);
      throw error;
    }
    let initialized = false;
    let closed = false;
    let initializePromise: Promise<boolean> | null = null;
    const fatalNativeFailure = (event?: { code?: string }) => {
      if (event?.code === 'audio_focus_lost') {
        transport.forceRecovery('AUDIO_FOCUS_LOST');
        return;
      }
      void attempt.close();
    };
    nativeAudio.setCoordinatorEvents({ onFailure: fatalNativeFailure, onBackgrounded: fatalNativeFailure });
    const nativePort: CallNativeAudioPort = {
      getCapability: () => nativeAudio.getCapability(),
      startCapture: (format, onFrame) => nativeAudio.startCapture(format, onFrame),
      stopCapture: () => nativeAudio.stopCapture(),
      enqueue: (chunk) => nativeAudio.enqueue(chunk),
      stop: (stream) => nativeAudio.stop(stream),
      tombstone: (stream) => nativeAudio.tombstone(stream),
      pauseCapture: () => nativeAudio.pauseCapture(),
      resumeCapture: () => nativeAudio.resumeCapture(),
      subscribeConsumption: (listener) => nativeAudio.subscribeConsumption(listener),
    };
    const transport = new CallTransportSession({
      url: callWebSocketUrl(server_config.BASE_URL),
      credentials: { username, token },
      characterId: this.options.characterId,
      sockets: this.sockets,
      nativeAudio: nativePort,
      clock,
      serverAvailable: true,
      nativeAvailable: true,
    });
    let attempt!: CallAttemptPorts;
    const session = new CallSession(transport, this.options.switchPort, this.options.characterId, async () => {
      if (closed) return;
      closed = true;
        if (initialized) {
          await nativeAudio.close();
          if (this.nativeOwner === attempt) this.nativeOwner = null;
        }
      this.attempts.delete(attempt);
        if (!initializePromise && this.nativeOwner === attempt) this.nativeOwner = null;
        if (!initializePromise || initialized) this.nativeOwnership.release(ownershipToken);
    });
    attempt = {
      session,
      initializeNative: async () => {
        if (closed) return false;
        if (!initializePromise) {
          const owned = nativeAudio.initialize().then(async (capability) => {
            const available = capability === 'available';
            if (closed && available) await nativeAudio.close();
            else initialized = available;
            return !closed && available;
          }).catch(async () => {
            if (!closed) {
              closed = true;
              this.attempts.delete(attempt);
              await nativeAudio.close().catch(() => undefined);
            }
            return false;
          }).finally(() => {
            if (!initialized && !closed) {
              closed = true;
              this.attempts.delete(attempt);
            }
            if ((closed || !initialized) && this.nativeOwner === attempt) this.nativeOwner = null;
            if (closed || !initialized) this.nativeOwnership.release(ownershipToken);
          });
          initializePromise = settleInitialize(owned, this.options.nativeInitializeTimeoutMs ?? 8_000);
        }
        return initializePromise;
      },
      close: async () => {
        await session.close();
        if (!initializePromise) this.nativeOwnership.release(ownershipToken);
      },
    };
    this.nativeOwner = attempt;
    this.attempts.add(attempt);
    return attempt;
  }

  async initializeSession(session: CallSession): Promise<boolean> {
    const attempt = [...this.attempts].find((candidate) => candidate.session === session);
    return attempt ? attempt.initializeNative() : false;
  }

  async close(): Promise<void> {
    this.closed = true;
    this.probeGeneration += 1;
    const attempts = [...this.attempts];
    this.attempts.clear();
    await Promise.allSettled(attempts.map((attempt) => attempt.close()));
    this.capability = null;
  }

  private isCurrentProbe(generation: number, token: string, characterId: string): boolean {
    const currentToken = this.options.credentials?.token ?? auth.message_token;
    return !this.closed && generation === this.probeGeneration && token === currentToken && characterId === this.options.characterId;
  }

  private staleProbeResult(characterId: string): ServerCallCapability {
    return { available: false, character_id: characterId, reason: 'runtime_not_ready' };
  }

  private storeUnavailable(reason: CallCapabilityReason): ServerCallCapability {
    this.capability = { available: false, character_id: this.options.characterId, reason };
    return this.capability;
  }
}

function settleInitialize(operation: Promise<boolean>, timeoutMs: number): Promise<boolean> {
  return new Promise<boolean>((resolve) => {
    let reported = false;
    const timeout = setTimeout(() => {
      reported = true;
      resolve(false);
    }, timeoutMs);
    void operation.then((value) => {
      clearTimeout(timeout);
      if (!reported) resolve(value);
    });
  });
}

export async function requestCallMicrophonePermission(): Promise<'granted' | 'denied' | 'permanently_denied'> {
  const result = await Audio.requestPermissionsAsync();
  if (result.granted) return 'granted';
  return result.canAskAgain === false ? 'permanently_denied' : 'denied';
}

const browserSocketFactory: CallSocketFactory = createPlatformCallSocketFactory();

function callWebSocketUrl(baseUrl: string): string {
  const normalized = baseUrl.replace(/\/+$/, '');
  if (normalized.startsWith('https://')) return `wss://${normalized.slice(8)}/call_ws`;
  if (normalized.startsWith('http://')) return `ws://${normalized.slice(7)}/call_ws`;
  throw new Error('INVALID_SERVER_URL');
}

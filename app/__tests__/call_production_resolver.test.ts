import { NativeCallOwnership, ProductionCallResolver } from '../utils/call_session/production_resolver';
import { auth } from '../components/auth';

jest.mock('expo-av', () => ({ Audio: { requestPermissionsAsync: jest.fn() } }));
jest.mock('expo-constants', () => ({ __esModule: true, default: { executionEnvironment: 'standalone' } }));
jest.mock('react-native', () => ({ Platform: { OS: 'android' } }));
jest.mock('../utils/call_audio/native_call_audio', () => {
  class FakeAudio {
    initialize = jest.fn(async () => 'available');
    getCapability = jest.fn(async () => 'available');
    startCapture = jest.fn(async () => undefined);
    stopCapture = jest.fn(async () => undefined);
    pauseCapture = jest.fn(async () => undefined);
    resumeCapture = jest.fn(async () => undefined);
    enqueue = jest.fn(async () => undefined);
    stop = jest.fn(async () => undefined);
    tombstone = jest.fn(async () => undefined);
    subscribeConsumption = jest.fn(() => jest.fn());
    close = jest.fn(async () => undefined);
    setCoordinatorEvents = jest.fn();
  }
  return { AndroidCallAudio: FakeAudio, isAndroidCallAudioModuleAvailable: jest.fn(() => true) };
});

class Socket {
  readyState = 0;
  listeners = new Map<string, Set<(event: any) => void>>();
  send = jest.fn();
  close = jest.fn();
  addEventListener(type: string, listener: (event: any) => void) {
    const set = this.listeners.get(type) ?? new Set();
    set.add(listener); this.listeners.set(type, set);
  }
  removeEventListener(type: string, listener: (event: any) => void) { this.listeners.get(type)?.delete(listener); }
}

describe('production call resolver', () => {
  it('releases native ownership when creating the native adapter throws', async () => {
    const ownership = new NativeCallOwnership();
    const audio = new (jest.requireMock('../utils/call_audio/native_call_audio').AndroidCallAudio)();
    const createNativeAudio = jest.fn()
      .mockImplementationOnce(() => { throw new Error('adapter construction failed'); })
      .mockReturnValue(audio);
    const resolver = new ProductionCallResolver({
      characterId: 'luotianyi', switchPort: { prepare: jest.fn() },
      fetchImpl: jest.fn(async () => ({
        ok: true, status: 200, json: async () => ({ available: true, character_id: 'luotianyi', reason: 'available' }),
      })) as unknown as typeof fetch,
      createNativeAudio, nativeOwnership: ownership,
    });
    await resolver.refreshCapability();
    expect(() => resolver.createAttempt()).toThrow('adapter construction failed');
    expect(ownership.available()).toBe(true);
    const next = resolver.createAttempt();
    await next.close();
    await resolver.close();
  });

  beforeEach(() => {
    auth.username = 'alice';
    auth.message_token = 'secret';
  });

  it.each([
    [false, 'disabled'],
    [false, 'runtime_not_ready'],
    [true, 'available'],
  ] as const)('validates server capability %s/%s', async (available, reason) => {
    const fetchImpl = jest.fn(async () => ({
      ok: true, status: 200,
      json: async () => ({ available, character_id: 'luotianyi', reason }),
    })) as unknown as typeof fetch;
    const resolver = new ProductionCallResolver({
      characterId: 'luotianyi', switchPort: { prepare: jest.fn() }, fetchImpl,
      sockets: { create: () => new Socket() },
    });

    await resolver.refreshCapability();

    expect(resolver.currentCapabilities()).toEqual({ serverAvailable: available, nativeAvailable: true });
    expect(fetchImpl).toHaveBeenCalledWith(expect.stringContaining('/call/capability?character_id=luotianyi'), {
      method: 'GET', headers: { Authorization: 'Bearer secret' },
    });
  });

  it('treats 401 as re-login and rejects malformed capability bodies', async () => {
    const unauthorized = new ProductionCallResolver({
      characterId: 'luotianyi', switchPort: { prepare: jest.fn() },
      fetchImpl: jest.fn(async () => ({ ok: false, status: 401 })) as unknown as typeof fetch,
    });
    await expect(unauthorized.refreshCapability()).rejects.toThrow('CALL_AUTH_REQUIRED');

    const malformed = new ProductionCallResolver({
      characterId: 'luotianyi', switchPort: { prepare: jest.fn() },
      fetchImpl: jest.fn(async () => ({ ok: true, status: 200, json: async () => ({ available: true }) })) as unknown as typeof fetch,
    });
    await expect(malformed.refreshCapability()).rejects.toThrow('INVALID_CALL_CAPABILITY_RESPONSE');
  });

  it('creates a fresh owned native/session attempt and closes it without a call id', async () => {
    const audioInstances: any[] = [];
    const resolver = new ProductionCallResolver({
      characterId: 'luotianyi', switchPort: { prepare: jest.fn() },
      fetchImpl: jest.fn(async () => ({
        ok: true, status: 200, json: async () => ({ available: true, character_id: 'luotianyi', reason: 'available' }),
      })) as unknown as typeof fetch,
      sockets: { create: () => new Socket() },
      createNativeAudio: () => {
        const audio = new (jest.requireMock('../utils/call_audio/native_call_audio').AndroidCallAudio)();
        audioInstances.push(audio); return audio;
      },
    });
    await resolver.refreshCapability();

    const first = resolver.createAttempt();
    expect(() => resolver.createAttempt()).toThrow('NATIVE_INITIALIZATION_BUSY');
    await expect(first.initializeNative()).resolves.toBe(true);
    await first.close();
    const second = resolver.createAttempt();
    expect(first.session).not.toBe(second.session);
    await second.close();

    expect(audioInstances[0].close).toHaveBeenCalledTimes(1);
    expect(audioInstances[1].close).not.toHaveBeenCalled();
  });

  it('owns pending native initialization and closes a late available device exactly once', async () => {
    let resolveInitialize!: (value: string) => void;
    const audio = new (jest.requireMock('../utils/call_audio/native_call_audio').AndroidCallAudio)();
    audio.initialize = jest.fn(() => new Promise((resolve) => { resolveInitialize = resolve; }));
    const resolver = new ProductionCallResolver({
      characterId: 'luotianyi', switchPort: { prepare: jest.fn() },
      fetchImpl: jest.fn(async () => ({
        ok: true, status: 200, json: async () => ({ available: true, character_id: 'luotianyi', reason: 'available' }),
      })) as unknown as typeof fetch,
      sockets: { create: () => new Socket() }, createNativeAudio: () => audio,
      nativeInitializeTimeoutMs: 1,
    });
    await resolver.refreshCapability();
    const attempt = resolver.createAttempt();
    const initializing = attempt.initializeNative();
    await expect(initializing).resolves.toBe(false);
    await attempt.close();
    expect(() => resolver.createAttempt()).toThrow('NATIVE_INITIALIZATION_BUSY');
    resolveInitialize('available');
    await new Promise((resolve) => setImmediate(resolve));
    expect(audio.close).toHaveBeenCalledTimes(1);
    const nextAttempt = resolver.createAttempt();
    await nextAttempt.close();
  });

  it('keeps pending native ownership exclusive across credential resolvers', async () => {
    let resolveInitialize!: (value: string) => void;
    const ownership = new NativeCallOwnership();
    const firstAudio = new (jest.requireMock('../utils/call_audio/native_call_audio').AndroidCallAudio)();
    firstAudio.initialize = jest.fn(() => new Promise((resolve) => { resolveInitialize = resolve; }));
    const capability = jest.fn(async () => ({
      ok: true, status: 200,
      json: async () => ({ available: true, character_id: 'luotianyi', reason: 'available' }),
    })) as unknown as typeof fetch;
    const first = new ProductionCallResolver({
      characterId: 'luotianyi', switchPort: { prepare: jest.fn() }, fetchImpl: capability,
      createNativeAudio: () => firstAudio, nativeInitializeTimeoutMs: 1, nativeOwnership: ownership,
      credentials: { username: 'alice', token: 'a' },
    });
    const second = new ProductionCallResolver({
      characterId: 'luotianyi', switchPort: { prepare: jest.fn() }, fetchImpl: capability,
      nativeOwnership: ownership, credentials: { username: 'bob', token: 'b' },
    });
    await first.refreshCapability();
    await second.refreshCapability();
    const attempt = first.createAttempt();
    await expect(attempt.initializeNative()).resolves.toBe(false);
    await first.close();
    expect(second.currentCapabilities().nativeAvailable).toBe(false);
    expect(() => second.createAttempt()).toThrow('NATIVE_INITIALIZATION_BUSY');
    resolveInitialize('available');
    await new Promise((resolve) => setImmediate(resolve));
    expect(firstAudio.close).toHaveBeenCalledTimes(1);
    expect(second.currentCapabilities().nativeAvailable).toBe(true);
    const secondAttempt = second.createAttempt();
    await secondAttempt.close();
    await second.close();
  });

  it('ignores stale capability responses and stale 401 after credentials change or close', async () => {
    let resolveFirst!: (value: any) => void;
    const fetchImpl = jest.fn()
      .mockImplementationOnce(() => new Promise((resolve) => { resolveFirst = resolve; }))
      .mockResolvedValueOnce({
        ok: true, status: 200, json: async () => ({ available: true, character_id: 'luotianyi', reason: 'available' }),
      }) as unknown as typeof fetch;
    const resolver = new ProductionCallResolver({ characterId: 'luotianyi', switchPort: { prepare: jest.fn() }, fetchImpl });
    const first = resolver.refreshCapability();
    auth.message_token = 'new-token';
    const second = resolver.refreshCapability();
    resolveFirst({ ok: false, status: 401 });
    await expect(first).resolves.toMatchObject({ available: false });
    await expect(second).resolves.toMatchObject({ available: true });
    expect(resolver.currentCapabilities().serverAvailable).toBe(true);
    await resolver.close();
  });

  it('maps audio focus loss to transport recovery but fatal native errors close the attempt', async () => {
    const audio = new (jest.requireMock('../utils/call_audio/native_call_audio').AndroidCallAudio)();
    let events: any;
    audio.setCoordinatorEvents.mockImplementation((value: any) => { events = value; });
    const socket = new Socket();
    const resolver = new ProductionCallResolver({
      characterId: 'luotianyi', switchPort: { prepare: jest.fn() },
      fetchImpl: jest.fn(async () => ({
        ok: true, status: 200, json: async () => ({ available: true, character_id: 'luotianyi', reason: 'available' }),
      })) as unknown as typeof fetch,
      sockets: { create: () => socket }, createNativeAudio: () => audio,
    });
    await resolver.refreshCapability();
    const attempt = resolver.createAttempt();
    const recovery = jest.spyOn((attempt.session as any).transport, 'forceRecovery');
    events.onFailure({ code: 'audio_focus_lost' });
    expect(recovery).toHaveBeenCalledWith('AUDIO_FOCUS_LOST');
    events.onFailure({ code: 'worker_failed' });
    await new Promise((resolve) => setImmediate(resolve));
    const replacement = resolver.createAttempt();
    await replacement.close();
    await resolver.close();
  });
});

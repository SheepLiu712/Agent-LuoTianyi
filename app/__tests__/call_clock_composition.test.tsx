import React from 'react';
import { act, create } from 'react-test-renderer';
import { CallScreen } from '../components/call/CallScreen';
import { useCallSession } from '../hooks/useCallSession';
import { CallSession } from '../utils/call_session/call_session';
import { CallTransportSession } from '../utils/call_transport/call_transport';
import { encodeControlMessage } from '../utils/call_protocol/control';
import type {
  CallClock, CallNativeAudioPort, CallSocket, CallSocketData, CallSocketEventMap, CallSocketFactory,
} from '../types/call_transport';
import type { PlaybackConsumptionReceipt } from '../utils/call_audio_contracts';
import { THEMES } from '../utils/theme';
import { callMonotonicNowMs } from '../utils/call_clock';

jest.mock('react-native-safe-area-context', () => ({ useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }) }));
jest.mock('react-native', () => ({
  __esModule: true,
  Platform: { OS: 'android' },
  AppState: { addEventListener: () => ({ remove: jest.fn() }) },
  BackHandler: { addEventListener: () => ({ remove: jest.fn() }) },
  Image: 'Image', Pressable: 'Pressable', Text: 'Text', View: 'View',
  StyleSheet: { absoluteFillObject: { position: 'absolute' }, create: (styles: any) => styles },
}));

const CALL_ID = '11111111-1111-1111-1111-111111111111';
const SERVER_EPOCH = 1_700_000_000_000;

class CompositionClock implements CallClock {
  timers: { callback: () => void; due: number }[] = [];
  monotonicMs(): number { return callMonotonicNowMs(); }
  wallClockMs(): number { return Date.now(); }
  setTimeout(callback: () => void, delayMs: number): unknown {
    const timer = { callback, due: this.monotonicMs() + delayMs };
    this.timers.push(timer);
    return timer;
  }
  clearTimeout(handle: unknown): void { this.timers = this.timers.filter((timer) => timer !== handle); }
}

class CompositionSocket implements CallSocket {
  readyState = 1;
  private listeners = new Map<keyof CallSocketEventMap, Set<(event: never) => void>>();
  send(_data: string | Uint8Array): void {}
  close(): void { this.readyState = 3; }
  addEventListener<Type extends keyof CallSocketEventMap>(type: Type, listener: (event: CallSocketEventMap[Type]) => void): void {
    const listeners = this.listeners.get(type) ?? new Set();
    listeners.add(listener as (event: never) => void);
    this.listeners.set(type, listeners);
  }
  removeEventListener<Type extends keyof CallSocketEventMap>(type: Type, listener: (event: CallSocketEventMap[Type]) => void): void {
    this.listeners.get(type)?.delete(listener as (event: never) => void);
  }
  emit<Type extends keyof CallSocketEventMap>(type: Type, event: CallSocketEventMap[Type]): void {
    for (const listener of this.listeners.get(type) ?? []) listener(event as never);
  }
  message(data: CallSocketData): void { this.emit('message', { data }); }
}

class CompositionSockets implements CallSocketFactory {
  sockets: CompositionSocket[] = [];
  create(): CallSocket { const socket = new CompositionSocket(); this.sockets.push(socket); return socket; }
}

function compositionNative(): CallNativeAudioPort {
  return {
    getCapability: async () => 'available',
    startCapture: async (_format, _onFrame) => {},
    stopCapture: async () => {},
    enqueue: async (_chunk) => {},
    stop: async (_stream) => {},
    tombstone: async (_stream) => {},
    pauseCapture: async () => {},
    resumeCapture: async () => {},
    playReplyFailureTone: async () => {},
    subscribeConsumption: (_listener: (receipt: PlaybackConsumptionReceipt) => void) => () => {},
  };
}

function serverControl(message: Parameters<typeof encodeControlMessage>[0]): string {
  return encodeControlMessage(message, { transport: 'call_ws', direction: 'server_to_client' });
}

async function flush(): Promise<void> { for (let i = 0; i < 12; i += 1) await Promise.resolve(); }

function textOf(node: any): string {
  return React.Children.toArray(node?.props?.children).map((child: any) => typeof child === 'string' ? child : textOf(child)).join('');
}

describe('call clock production composition', () => {
  beforeEach(() => {
    jest.useFakeTimers();
    jest.spyOn(Date, 'now').mockReturnValue(1_700_000_001_000);
    jest.spyOn(globalThis.performance, 'now').mockReturnValue(10_000);
  });
  afterEach(() => { jest.restoreAllMocks(); jest.useRealTimers(); });

  test.each([
    { dialingMs: 0, elapsedMs: 1_000 },
    { dialingMs: 10_000, elapsedMs: 5_000 },
  ])('shows the server-connected duration on the first ACTIVE render after $dialingMs ms of dialing', async ({ dialingMs, elapsedMs }) => {
    jest.spyOn(Date, 'now').mockReturnValue(SERVER_EPOCH + elapsedMs - dialingMs);
    const receivedMonotonicMs = 10_000 + dialingMs;
    const anchor = receivedMonotonicMs - elapsedMs;
    const clock = new CompositionClock();
    const sockets = new CompositionSockets();
    const transport = new CallTransportSession({
      url: 'ws://example/call_ws', credentials: { username: 'u', token: 't' }, characterId: 'luotianyi',
      sockets, nativeAudio: compositionNative(), clock, serverAvailable: true, nativeAvailable: true,
    });
    const session = new CallSession(transport, { prepare: async () => {} }, 'luotianyi');
    let result: any;
    function Harness() {
      result = useCallSession({
        session,
        capabilities: { serverAvailable: true, nativeAvailable: true },
        requestPermission: async () => 'granted',
      });
      return result.state.phase === 'IDLE' ? null : <CallScreen state={result.state} theme={THEMES.dark} onHangup={result.hangup} onBack={jest.fn()} />;
    }

    let tree!: ReturnType<typeof create>;
    act(() => { tree = create(<Harness />); });
    try {
      await act(async () => { expect(await result.start(false)).toBe(true); });
      await act(async () => { await Promise.resolve(); });
      act(() => { sockets.sockets[0].message(JSON.stringify({ type: 'system_ready', payload: {} })); });
      act(() => { sockets.sockets[0].message(JSON.stringify({ type: 'auth_ok', payload: {} })); });
      await act(async () => { await flush(); });
      const requestId = transport.state.clientRequestId!;
      act(() => { sockets.sockets[0].message(serverControl({ protocol: 'call.v1', type: 'call.state', seq: 1, call_id: CALL_ID, client_request_id: requestId, state: 'preparing' })); });
      expect(result.state.phase).toBe('PREPARING');
      // Keep the same mounted screen while dialing time passes, then deliver a
      // delayed ACTIVE. No UI tick may be needed to show its initial duration.
      jest.spyOn(Date, 'now').mockReturnValue(SERVER_EPOCH + elapsedMs);
      jest.spyOn(globalThis.performance, 'now').mockReturnValue(receivedMonotonicMs);
      act(() => { jest.advanceTimersByTime(dialingMs); });
      act(() => { sockets.sockets[0].message(serverControl({ protocol: 'call.v1', type: 'call.active', seq: 2, call_id: CALL_ID, connected_at_ms: SERVER_EPOCH })); });
      await act(async () => { await flush(); });

      const visibleTimer = () => tree.root.findAllByType('Text' as any).map(textOf).filter((value) => /^\d+:\d+$/.test(value));
      expect(result.state).toMatchObject({ phase: 'ACTIVE', activeStartedAtMs: anchor, connectedAtServerMs: SERVER_EPOCH });
      expect(transport.state.activeDurationMs).toBe(elapsedMs);
      expect(visibleTimer()).toEqual([`00:0${elapsedMs / 1000}`]);

      // Changing the wall clock after connection must not change the duration.
      jest.spyOn(Date, 'now').mockReturnValue(SERVER_EPOCH - 3_600_000);
      jest.spyOn(globalThis.performance, 'now').mockReturnValue(receivedMonotonicMs + 1_000);
      act(() => { jest.advanceTimersByTime(1000); });
      expect(transport.state.activeDurationMs).toBe(elapsedMs + 1_000);
      expect(visibleTimer()).toEqual([`00:0${elapsedMs / 1000 + 1}`]);

      act(() => { sockets.sockets[0].emit('close', { code: 1006 }); });
      expect(result.state.phase).toBe('RECONNECTING');
      expect(result.state.activeDurationAtDisconnectMs).toBe(elapsedMs + 1_000);
      act(() => { sockets.sockets[1].message(JSON.stringify({ type: 'system_ready', payload: {} })); });
      act(() => { sockets.sockets[1].message(JSON.stringify({ type: 'auth_ok', payload: {} })); });
      act(() => { sockets.sockets[1].message(serverControl({
        protocol: 'call.v1', type: 'call.resumed', call_id: CALL_ID, character_id: 'luotianyi',
        last_contiguous_client_seq: 1, last_contiguous_server_seq: 2,
      })); });
      await act(async () => { await flush(); });
      expect(result.state).toMatchObject({ phase: 'ACTIVE', activeStartedAtMs: anchor });
      expect(visibleTimer()).toEqual([`00:0${elapsedMs / 1000 + 1}`]);

      act(() => { result.hangup(); });
      expect(result.state.phase).toBe('IDLE');
      act(() => { jest.advanceTimersByTime(1000); });
      expect(tree.root.findAllByType(CallScreen)).toHaveLength(0);
    } finally {
      act(() => tree.unmount());
    }
  });
});

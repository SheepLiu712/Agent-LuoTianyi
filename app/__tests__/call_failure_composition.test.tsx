import React from 'react';
import { act, create } from 'react-test-renderer';
import { CallFailureBanner } from '../components/call/CallFailureBanner';
import { useCallSession } from '../hooks/useCallSession';
import { CallSession } from '../utils/call_session/call_session';
import { CallTransportSession } from '../utils/call_transport/call_transport';
import { encodeControlMessage } from '../utils/call_protocol/control';
import type { CallEnded, CallEndReason } from '../utils/call_protocol/control_types';
import type { CallClock, CallNativeAudioPort, CallSocket, CallSocketData, CallSocketEventMap, CallSocketFactory } from '../types/call_transport';
import type { PlaybackConsumptionReceipt } from '../utils/call_audio_contracts';
import { THEMES } from '../utils/theme';

jest.mock('react-native', () => ({
  __esModule: true,
  Platform: { OS: 'android' },
  AppState: { addEventListener: () => ({ remove: jest.fn() }) },
  BackHandler: { addEventListener: () => ({ remove: jest.fn() }) },
  Pressable: 'Pressable', Text: 'Text', View: 'View',
  StyleSheet: { absoluteFillObject: {}, create: (styles: any) => styles },
}));

class Socket implements CallSocket {
  readyState = 1;
  private listeners = new Map<keyof CallSocketEventMap, Set<(event: never) => void>>();
  send(_data: string | Uint8Array): void {}
  close(): void { this.readyState = 3; }
  addEventListener<Type extends keyof CallSocketEventMap>(type: Type, listener: (event: CallSocketEventMap[Type]) => void): void {
    const listeners = this.listeners.get(type) ?? new Set();
    listeners.add(listener as (event: never) => void);
    this.listeners.set(type, listeners);
  }
  removeEventListener<Type extends keyof CallSocketEventMap>(type: Type, listener: (event: CallSocketEventMap[Type]) => void): void { this.listeners.get(type)?.delete(listener as (event: never) => void); }
  emit<Type extends keyof CallSocketEventMap>(type: Type, event: CallSocketEventMap[Type]): void { for (const listener of this.listeners.get(type) ?? []) listener(event as never); }
  message(data: CallSocketData): void { this.emit('message', { data }); }
}

class Sockets implements CallSocketFactory {
  socket = new Socket();
  create(): CallSocket { this.socket = new Socket(); return this.socket; }
}

class Clock implements CallClock {
  now = 100;
  monotonicMs(): number { return this.now; }
  wallClockMs(): number { return 1_700_000_001_000; }
  setTimeout(callback: () => void, delayMs: number): unknown { return globalThis.setTimeout(callback, delayMs); }
  clearTimeout(handle: unknown): void { globalThis.clearTimeout(handle as ReturnType<typeof setTimeout>); }
}

type CallNativeAudioPortWithFailureTone = CallNativeAudioPort & {
  playReplyFailureTone(): Promise<void>;
};

const native: CallNativeAudioPortWithFailureTone = {
  getCapability: async () => 'available', startCapture: async () => {}, stopCapture: async () => {}, enqueue: async () => {},
  stop: async () => {}, tombstone: async () => {}, pauseCapture: async () => {}, resumeCapture: async () => {},
  playReplyFailureTone: async () => {},
  subscribeConsumption: (_listener: (receipt: PlaybackConsumptionReceipt) => void) => () => {},
};
const CALL_ID = '11111111-1111-1111-1111-111111111111';

function control(message: Parameters<typeof encodeControlMessage>[0]): string {
  return encodeControlMessage(message, { transport: 'call_ws', direction: 'server_to_client' });
}

async function flush() { for (let i = 0; i < 12; i += 1) await Promise.resolve(); }

function textOf(node: any): string {
  return React.Children.toArray(node?.props?.children).map((child: any) => typeof child === 'string' ? child : textOf(child)).join('');
}

function mountCall() {
  const sockets = new Sockets();
  const onFailure = jest.fn();
  const onReturnToChat = jest.fn();
  const release = jest.fn();
  const unsubscribeConsumption = jest.fn();
  const audio = {
    ...native,
    stop: jest.fn(async () => {}),
    stopCapture: jest.fn(async () => {}),
    subscribeConsumption: () => unsubscribeConsumption,
  };
  let transport!: CallTransportSession;
  let result!: ReturnType<typeof useCallSession>;
  let tree!: ReturnType<typeof create>;
  function createSession() {
    transport = new CallTransportSession({
      url: 'ws://example/call_ws', credentials: { username: 'u', token: 't' }, characterId: 'luotianyi',
      sockets, nativeAudio: audio, clock: new Clock(), serverAvailable: true, nativeAvailable: true,
    });
    return new CallSession(transport, { prepare: async () => {} }, 'luotianyi', release);
  }
  function Harness() {
    result = useCallSession({ createSession, capabilities: { serverAvailable: true, nativeAvailable: true },
      requestPermission: async () => 'granted', onFailure, onReturnToChat });
    return result.failureNotice ? <CallFailureBanner notice={result.failureNotice} theme={THEMES.dark} onDismiss={result.dismissFailure} /> : null;
  }
  act(() => { tree = create(<Harness />); });
  return {
    sockets, onFailure, onReturnToChat, release, unsubscribeConsumption, audio,
    get result() { return result; },
    get transport() { return transport; },
    rendered: () => tree.root.findAllByType('Text' as any).map(textOf).join(''),
    async start(connected = false) {
      await act(async () => { expect(await result.start(false)).toBe(true); });
      await act(async () => {
        sockets.socket.message(JSON.stringify({ type: 'system_ready', payload: {} }));
        sockets.socket.message(JSON.stringify({ type: 'auth_ok', payload: {} }));
        await flush();
        sockets.socket.message(control({ protocol: 'call.v1', type: 'call.state', seq: 1, call_id: CALL_ID,
          client_request_id: transport.state.clientRequestId!, state: 'ringing' }));
        await flush();
        if (connected) {
          sockets.socket.message(control({ protocol: 'call.v1', type: 'call.active', seq: 2, call_id: CALL_ID, connected_at_ms: 1_700_000_000_500 }));
          await flush();
        }
      });
      expect(result.state.phase).toBe(connected ? 'ACTIVE' : 'PREPARING');
    },
    ended(reason: CallEndReason, connected = false, outcome?: CallEnded['outcome']) {
      return control({ protocol: 'call.v1', type: 'call.ended', seq: connected ? 3 : 2, call_id: CALL_ID,
        outcome: outcome ?? (connected ? 'connected' : 'cancelled_before_answer'), end_reason: reason,
        active_duration_ms: connected ? 500 : 0 });
    },
    async sendEnded(reason: CallEndReason, connected = false, outcome?: CallEnded['outcome']) {
      await act(async () => { sockets.socket.message(this.ended(reason, connected, outcome)); await flush(); });
    },
    unmount() { act(() => tree.unmount()); },
  };
}

describe('call.ended production composition', () => {
  test.each([
    ['setup_timeout', '呼叫超时'],
    ['provider_failed', '通话服务异常'],
    ['recovery_timeout', '通话连接中断'],
    ['system_failure', '通话异常结束'],
  ] as const)('%s keeps a visible safe notice before and after connection', async (reason, title) => {
    for (const connected of [false, true]) {
      const call = mountCall();
      try {
        await call.start(connected);
        await call.sendEnded(reason, connected);
        expect(call.result.state.phase).toBe('IDLE');
        expect(call.rendered()).toContain(title);
        expect(call.rendered()).not.toContain(reason);
        expect(call.rendered()).not.toContain(CALL_ID);
        expect(call.transport.state).toMatchObject({ status: 'closed', endReason: reason,
          outcome: connected ? 'connected' : 'cancelled_before_answer', activeDurationMs: connected ? 500 : 0 });
        expect(call.onFailure).toHaveBeenCalledTimes(1);
        expect(call.onReturnToChat).toHaveBeenCalledTimes(1);
        expect(call.release).toHaveBeenCalledTimes(1);
        expect(call.unsubscribeConsumption).toHaveBeenCalledTimes(1);
        expect(call.audio.stop).toHaveBeenCalled();
        expect(call.audio.stopCapture).toHaveBeenCalled();
        expect(call.sockets.socket.readyState).toBe(3);
      } finally { call.unmount(); }
    }
  });

  test.each([
    ['user_hangup', false, 'cancelled_before_answer'],
    ['user_hangup', true, 'connected'],
    ['agent_hangup', true, 'connected'],
    ['declined', false, 'declined'],
    ['time_limit', true, 'connected'],
  ] as const)('%s connected=%s returns silently', async (reason, connected, outcome) => {
    const call = mountCall();
    try {
      await call.start(connected);
      await call.sendEnded(reason, connected, outcome);
      expect(call.result.state.phase).toBe('IDLE');
      expect(call.result.failureNotice).toBeNull();
      expect(call.rendered()).toBe('');
      expect(call.onFailure).not.toHaveBeenCalled();
      expect(call.onReturnToChat).toHaveBeenCalledTimes(1);
      expect(call.release).toHaveBeenCalledTimes(1);
    } finally { call.unmount(); }
  });

  test.each([false, true])('local hangup connected=%s ignores a late abnormal end', async (connected) => {
    const call = mountCall();
    try {
      await call.start(connected);
      await act(async () => { call.result.hangup(); await flush(); });
      await call.sendEnded('provider_failed', connected);
      expect(call.result.state.phase).toBe('IDLE');
      expect(call.result.failureNotice).toBeNull();
      expect(call.onFailure).not.toHaveBeenCalled();
      expect(call.onReturnToChat).toHaveBeenCalledTimes(1);
      expect(call.release).toHaveBeenCalledTimes(1);
    } finally { call.unmount(); }
  });

  test('setup error keeps the original failed terminal snapshot when the hook closes the session', async () => {
    const call = mountCall();
    try {
      await call.start();
      await act(async () => {
        call.sockets.socket.message(control({ protocol: 'call.v1', type: 'error', code: 'CALL_SETUP_FAILED',
          message: 'provider=https://secret.example/token=abc stack Error: leaked', retryable: false,
          call_id: CALL_ID }));
        await flush();
      });
      expect(call.result.state.phase).toBe('IDLE');
      expect(call.rendered()).toContain('通话失败');
      expect(call.rendered()).not.toMatch(/secret|abc|stack|CALL_SETUP_FAILED/);
      expect(call.transport.state).toMatchObject({ status: 'failed', errorCode: 'CALL_SETUP_FAILED' });
      expect(call.onFailure).toHaveBeenCalledTimes(1);
      expect(call.onReturnToChat).toHaveBeenCalledTimes(1);
      expect(call.release).toHaveBeenCalledTimes(1);
      expect(call.unsubscribeConsumption).toHaveBeenCalledTimes(1);
    } finally { call.unmount(); }
  });

  test('duplicate terminal events and retired sockets cannot revive a dismissed notice or affect a new attempt', async () => {
    const call = mountCall();
    try {
      await call.start();
      const oldSocket = call.sockets.socket;
      const oldEnd = call.ended('provider_failed');
      await act(async () => { oldSocket.message(oldEnd); oldSocket.message(oldEnd); await flush(); });
      expect(call.onFailure).toHaveBeenCalledTimes(1);
      act(() => call.result.dismissFailure());
      await act(async () => { oldSocket.message(oldEnd); oldSocket.emit('close', { code: 1006 }); await flush(); });
      expect(call.result.failureNotice).toBeNull();
      await call.start(true);
      await act(async () => { oldSocket.message(oldEnd); await flush(); });
      expect(call.result.state.phase).toBe('ACTIVE');
      expect(call.result.failureNotice).toBeNull();
      await call.sendEnded('system_failure', true);
      expect(call.rendered()).toContain('通话异常结束');
      expect(call.onFailure).toHaveBeenCalledTimes(2);
      expect(call.onReturnToChat).toHaveBeenCalledTimes(2);
      expect(call.release).toHaveBeenCalledTimes(2);
      await call.start();
      expect(call.result.failureNotice).toBeNull();
      await call.sendEnded('declined', false, 'declined');
      expect(call.onFailure).toHaveBeenCalledTimes(2);
    } finally { call.unmount(); }
  });
});

describe('call failure production composition', () => {
  test('FakeSocket → CallTransportSession → CallSession → hook/reducer → visible banner', async () => {
    const sockets = new Sockets();
    const transport = new CallTransportSession({
      url: 'ws://example/call_ws', credentials: { username: 'u', token: 't' }, characterId: 'luotianyi',
      sockets, nativeAudio: native, clock: new Clock(), serverAvailable: true, nativeAvailable: true,
    });
    const session = new CallSession(transport, { prepare: async () => {} }, 'luotianyi');
    let result: any;
    let tree!: ReturnType<typeof create>;
    function Harness() {
      result = useCallSession({ session, capabilities: { serverAvailable: true, nativeAvailable: true }, requestPermission: async () => 'granted' });
      return result.failureNotice ? <CallFailureBanner notice={result.failureNotice} theme={THEMES.dark} onDismiss={result.dismissFailure} /> : null;
    }
    act(() => { tree = create(<Harness />); });
    await act(async () => { expect(await result.start(false)).toBe(true); });
    act(() => { sockets.socket.message(JSON.stringify({ type: 'system_ready', payload: {} })); });
    act(() => { sockets.socket.message(JSON.stringify({ type: 'auth_ok', payload: {} })); });
    await act(async () => { await flush(); });
    const requestId = transport.state.clientRequestId!;
    act(() => { sockets.socket.message(control({ protocol: 'call.v1', type: 'call.state', seq: 1, call_id: CALL_ID, client_request_id: requestId, state: 'preparing' })); });
    act(() => { sockets.socket.emit('close', { code: 1006 }); });
    await act(async () => { await flush(); });
    expect(result.state.phase).toBe('IDLE');
    expect(transport.state).toMatchObject({ status: 'failed', errorCode: 'CALL_CONNECTION_LOST' });
    const rendered = tree.root.findAllByType('Text' as any).map(textOf).join('');
    expect(rendered).toContain('通话连接失败');
    expect(rendered).toContain('检查网络后重试');
    expect(rendered).not.toContain(CALL_ID);
    act(() => tree.unmount());
  });
});

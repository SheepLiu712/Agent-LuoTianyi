import React from 'react';
import { act, create } from 'react-test-renderer';
import { CallFailureBanner } from '../components/call/CallFailureBanner';
import { useCallSession } from '../hooks/useCallSession';
import { CallSession } from '../utils/call_session/call_session';
import { CallTransportSession } from '../utils/call_transport/call_transport';
import { encodeControlMessage } from '../utils/call_protocol/control';
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
  create(): CallSocket { return this.socket; }
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
    const rendered = tree.root.findAllByType('Text' as any).map(textOf).join('');
    expect(rendered).toContain('通话连接失败');
    expect(rendered).toContain('检查网络后重试');
    expect(rendered).not.toContain(CALL_ID);
    act(() => tree.unmount());
  });
});

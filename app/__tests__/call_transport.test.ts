jest.mock('react-native', () => ({
  AppState: {
    currentState: 'active',
    addEventListener: jest.fn(() => ({ remove: jest.fn() })),
  },
}));
jest.mock('../config', () => ({
  server_config: { BASE_URL: 'http://localhost:60030' },
}));
jest.mock('../utils/debug_trace', () => ({ addDebugTrace: jest.fn() }));

import { CallCallbacks } from '../types/call';
import { CallTransport } from '../utils/call_transport';

class FakeWebSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;
  static instances: FakeWebSocket[] = [];

  readyState = FakeWebSocket.OPEN;
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;

  constructor(readonly url: string) {
    FakeWebSocket.instances.push(this);
  }

  send(message: string) {
    this.sent.push(message);
  }

  close() {
    this.readyState = FakeWebSocket.CLOSED;
    this.onclose?.();
  }

  receive(message: Record<string, unknown>) {
    this.onmessage?.({ data: JSON.stringify(message) });
  }
}

describe('CallTransport protocol and reconnect behavior', () => {
  let originalWebSocket: typeof WebSocket;
  let callbacks: jest.Mocked<CallCallbacks>;
  let transport: CallTransport;

  beforeEach(() => {
    jest.useFakeTimers();
    FakeWebSocket.instances = [];
    originalWebSocket = globalThis.WebSocket;
    Object.defineProperty(globalThis, 'WebSocket', {
      configurable: true,
      value: FakeWebSocket,
    });
    callbacks = {
      onEvent: jest.fn(),
      onStatus: jest.fn(),
      onError: jest.fn(),
      onConnectedAt: jest.fn(),
    };
    transport = new CallTransport('alice', 'secret', callbacks);
    transport.start();
  });

  afterEach(() => {
    transport.stop();
    jest.clearAllTimers();
    jest.useRealTimers();
    Object.defineProperty(globalThis, 'WebSocket', {
      configurable: true,
      value: originalWebSocket,
    });
  });

  it('authenticates only after SYSTEM_READY and advertises negative ACK support', () => {
    const ws = FakeWebSocket.instances[0];

    ws.onopen?.();
    expect(ws.sent).toHaveLength(0);

    ws.receive({ type: 'system_ready', payload: {} });
    expect(ws.sent).toHaveLength(1);
    expect(JSON.parse(ws.sent[0])).toMatchObject({
      type: 'user_auth',
      payload: {
        username: 'alice',
        token: 'secret',
        capabilities: ['negative_ack_v1'],
      },
    });
  });

  it('AUTH_ERROR stops reconnects without resetting the backoff', () => {
    const ws = FakeWebSocket.instances[0];
    (transport as any).reconnectAttempts = 3;

    ws.receive({ type: 'auth_error', payload: { message: 'invalid token' } });

    expect((transport as any).reconnectAttempts).toBe(3);
    expect((transport as any).isStopped).toBe(true);
    expect(callbacks.onError).toHaveBeenCalledWith('invalid token');
    jest.advanceTimersByTime(10000);
    expect(FakeWebSocket.instances).toHaveLength(1);
  });

  it('resets reconnect backoff only after AUTH_OK', () => {
    const ws = FakeWebSocket.instances[0];
    (transport as any).reconnectAttempts = 3;

    ws.onopen?.();
    ws.receive({ type: 'system_ready', payload: {} });
    expect((transport as any).reconnectAttempts).toBe(3);

    ws.receive({ type: 'auth_ok', payload: {} });
    expect((transport as any).reconnectAttempts).toBe(0);
  });

  it.each([
    ['server_ack', { ok: false, code: 'OVERLOADED', message: 'busy' }],
    ['error', { code: 'CALL_DISABLED', message: 'disabled' }],
  ])('resolves %s negative responses for the matching request', (type, payload) => {
    const resolve = jest.fn();
    const timer = setTimeout(() => undefined, 10000);
    (transport as any).ackWaiters.set('request-1', { resolve, timer });

    FakeWebSocket.instances[0].receive({ type, reply_to: 'request-1', payload });

    expect(resolve).toHaveBeenCalledWith(expect.objectContaining({
      ok: false,
      request_id: 'request-1',
      code: payload.code,
      error: payload.message,
    }));
    expect((transport as any).ackWaiters.has('request-1')).toBe(false);
  });

  it('does not report a transient socket error before reconnecting on close', () => {
    const ws = FakeWebSocket.instances[0];

    ws.onerror?.();
    expect(callbacks.onError).not.toHaveBeenCalled();

    ws.onclose?.();
    expect(callbacks.onError).not.toHaveBeenCalled();
    jest.advanceTimersByTime(2000);
    expect(FakeWebSocket.instances).toHaveLength(2);
  });

  it('reports an error only after the reconnect limit is exhausted', () => {
    (transport as any).reconnectAttempts = 5;

    FakeWebSocket.instances[0].onclose?.();

    expect(callbacks.onError).toHaveBeenCalledWith('通话网络连接已断开，请稍后重试');
    expect(callbacks.onStatus).toHaveBeenLastCalledWith('ended');
    expect((transport as any).isStopped).toBe(true);
  });

  it('does not consume an audio sequence while the socket is unavailable', () => {
    const ws = FakeWebSocket.instances[0];
    ws.readyState = FakeWebSocket.CLOSED;

    expect(transport.appendAudio('dropped', 0)).toBe(false);
    expect(ws.sent).toHaveLength(0);

    ws.readyState = FakeWebSocket.OPEN;
    expect(transport.appendAudio('resumed', 0)).toBe(true);
    expect(JSON.parse(ws.sent[0])).toMatchObject({
      type: 'call.audio.append',
      payload: { audio: 'resumed', seq: 0 },
    });
  });
});

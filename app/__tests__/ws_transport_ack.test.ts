jest.mock('react-native', () => ({
  AppState: {
    currentState: 'active',
    addEventListener: jest.fn(() => ({ remove: jest.fn() })),
  },
}));
jest.mock('../config', () => ({
  server_config: { BASE_URL: 'http://localhost:60030' },
}));

import { normalizeServerAck } from '../utils/ws_ack';
import { WebSocketTransport } from '../utils/ws_transport';

describe('normalizeServerAck', () => {
  it('keeps legacy ACK payloads compatible', () => {
    expect(normalizeServerAck({ received_event_type: 'user_text' }, 'msg-1')).toEqual({
      ok: true,
      request_id: 'msg-1',
    });
  });

  it('marks overload NACKs as retryable', () => {
    expect(
      normalizeServerAck(
        { ok: false, code: 'OVERLOADED', message: 'ingress queue is full', retryable: true },
        'msg-2',
      ),
    ).toEqual({
      ok: false,
      request_id: 'msg-2',
      error: '[OVERLOADED] ingress queue is full',
      code: 'OVERLOADED',
      retryable: true,
      drop: false,
    });
  });

  it('marks permanent rejection as terminal', () => {
    expect(normalizeServerAck({ ok: false, code: 'BAD_MESSAGE' }, 'msg-3')).toMatchObject({
      ok: false,
      drop: true,
      retryable: false,
    });
  });
});

describe('WebSocketTransport readiness failures', () => {
  function transport() {
    return new WebSocketTransport('alice', 'token', {
      onAgentMessage: jest.fn(),
      onAgentStateChanged: jest.fn(),
      onError: jest.fn(),
    });
  }

  it('keeps the same id retryable while temporarily not ready', async () => {
    const ws = transport();
    (ws as any).waitUntilReady = jest.fn().mockResolvedValue('timeout');

    await expect(ws.submitUserText('hello', false, 10, 'msg-not-ready')).resolves.toMatchObject({
      ok: false,
      request_id: 'msg-not-ready',
      retryable: true,
      drop: false,
    });
  });

  it('drops only an explicit authentication rejection', async () => {
    const ws = transport();
    (ws as any).waitUntilReady = jest.fn().mockResolvedValue('auth_rejected');

    await expect(ws.submitUserText('hello', false, 10, 'msg-auth')).resolves.toMatchObject({
      ok: false,
      request_id: 'msg-auth',
      code: 'AUTH_REJECTED',
      retryable: false,
      drop: true,
    });
  });

  it('advertises negative ACK support in the auth payload', () => {
    const ws = transport();
    const send = jest.fn();
    const originalWebSocket = globalThis.WebSocket;
    Object.defineProperty(globalThis, 'WebSocket', {
      configurable: true,
      value: { OPEN: 1 },
    });

    try {
      (ws as any).ws = { readyState: 1, send };
      (ws as any).sendAuth();

      const envelope = JSON.parse(send.mock.calls[0][0]);
      expect(envelope.payload.capabilities).toEqual(['negative_ack_v1']);
    } finally {
      Object.defineProperty(globalThis, 'WebSocket', {
        configurable: true,
        value: originalWebSocket,
      });
    }
  });

  it('suppresses reconnect after AUTH_ERROR and resets backoff only on AUTH_OK', () => {
    const ws = transport();
    const close = jest.fn();
    (ws as any).ws = { close };
    (ws as any).reconnectAttempts = 5;

    (ws as any).handleServerMessage(JSON.stringify({
      type: 'auth_error',
      payload: { code: 'INVALID_TOKEN', message: 'invalid token' },
    }));

    expect((ws as any).authRejected).toBe(true);
    expect((ws as any).canReconnectAfterClose()).toBe(false);
    expect((ws as any).reconnectAttempts).toBe(5);
    expect(close).toHaveBeenCalledTimes(1);

    (ws as any).handleServerMessage(JSON.stringify({ type: 'auth_ok', payload: {} }));
    expect((ws as any).authRejected).toBe(false);
    expect((ws as any).canReconnectAfterClose()).toBe(true);
    expect((ws as any).reconnectAttempts).toBe(0);
  });
});

import { NetworkClient, type ConnectCallbacks } from '../utils/network_client';

jest.mock('expo-file-system/legacy', () => ({}));
jest.mock('../utils/image_compression', () => ({
  compressImageForUpload: jest.fn(),
  MAX_IMAGE_FILE_SIZE_BYTES: 6 * 1024 * 1024,
}));
jest.mock('react-native', () => ({
  AppState: {
    currentState: 'active',
    addEventListener: jest.fn(() => ({ remove: jest.fn() })),
  },
}));
jest.mock('../config', () => ({
  server_config: { BASE_URL: 'http://localhost:60030' },
}));

class FakeWebSocket {
  static readonly OPEN = 1;
  static instances: FakeWebSocket[] = [];

  readyState = FakeWebSocket.OPEN;
  sent: Record<string, unknown>[] = [];
  onopen: (() => void) | null = null;
  onclose: ((event: Record<string, unknown>) => void) | null = null;
  onerror: ((event: Record<string, unknown>) => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;

  constructor(readonly url: string) {
    FakeWebSocket.instances.push(this);
  }

  send(raw: string) {
    this.sent.push(JSON.parse(raw));
  }

  close(code = 1000, reason = '') {
    this.readyState = 3;
    this.onclose?.({ code, reason, wasClean: code === 1000 });
  }

  open() {
    this.onopen?.();
  }

  message(message: Record<string, unknown>) {
    this.onmessage?.({ data: JSON.stringify(message) });
  }

  serverClose(code = 1013) {
    this.readyState = 3;
    this.onclose?.({ code, reason: '', wasClean: false });
  }
}

const callbacks: ConnectCallbacks = {
  onAgentMessage: jest.fn(),
  onAgentStateChanged: jest.fn(),
  onError: jest.fn(),
};

function bindChat(socket: FakeWebSocket, interactionId = 'chat-1') {
  socket.open();
  socket.message({ type: 'auth_ok', payload: {} });
  socket.message({
    type: 'chat.ready',
    payload: { character_id: 'luotianyi', interaction_id: interactionId, schema_version: 1 },
  });
}

describe('chat readiness production composition', () => {
  const originalWebSocket = globalThis.WebSocket;

  beforeEach(() => {
    jest.useFakeTimers();
    FakeWebSocket.instances = [];
    Object.defineProperty(globalThis, 'WebSocket', {
      configurable: true,
      value: FakeWebSocket,
    });
  });

  afterEach(() => {
    jest.useRealTimers();
    Object.defineProperty(globalThis, 'WebSocket', {
      configurable: true,
      value: originalWebSocket,
    });
  });

  it('does not send chat after auth_ok until the real ChatStage binding is ready', async () => {
    const client = new NetworkClient();
    client.connectWs('alice', 'token', 'luotianyi', callbacks);
    const socket = FakeWebSocket.instances[0];
    socket.open();
    socket.message({ type: 'auth_ok', payload: {} });

    const pending = client.sendChat('hello', false, 'message-1');
    await jest.advanceTimersByTimeAsync(160);
    expect(socket.sent.some((message) => message.type === 'user_text')).toBe(false);

    socket.message({
      type: 'chat.ready',
      payload: { character_id: 'luotianyi', interaction_id: 'chat-1', schema_version: 1 },
    });
    await jest.advanceTimersByTimeAsync(80);
    expect(socket.sent).toContainEqual(expect.objectContaining({ type: 'user_text', client_msg_id: 'message-1' }));
    socket.message({ type: 'server_ack', reply_to: 'message-1', payload: { ok: true } });
    await expect(pending).resolves.toMatchObject({ ok: true });
    client.disconnectWs();
  });

  it.each(['INTERACTION_OWNED_BY_CALL', 'INTERACTION_FINALIZING'])(
    'retries bounded %s rejection and sends on the second bound socket',
    async (code) => {
      const client = new NetworkClient();
      const reconnecting = client.reconnectWs('alice', 'token', 'luotianyi', callbacks, 10_000);
      const first = FakeWebSocket.instances[0];
      first.open();
      first.message({ type: 'auth_ok', payload: {} });
      first.message({
        type: 'error',
        payload: { code, message: 'owned', retryable: true },
      });
      first.serverClose();

      await jest.advanceTimersByTimeAsync(2_000);
      const second = FakeWebSocket.instances[1];
      bindChat(second, 'chat-2');
      await jest.advanceTimersByTimeAsync(80);
      await expect(reconnecting).resolves.toBe(true);

      const sent = client.sendChat('after call', false, 'message-2');
      await jest.advanceTimersByTimeAsync(80);
      expect(second.sent).toContainEqual(expect.objectContaining({ type: 'user_text', client_msg_id: 'message-2' }));
      second.message({ type: 'server_ack', reply_to: 'message-2', payload: { ok: true } });
      await expect(sent).resolves.toMatchObject({ ok: true });
      client.disconnectWs();
    },
  );

  it('ignores every late callback from a rejected socket after its replacement exists', async () => {
    const client = new NetworkClient();
    const reconnecting = client.reconnectWs('alice', 'token', 'luotianyi', callbacks, 10_000);
    const first = FakeWebSocket.instances[0];
    const lateOpen = first.onopen;
    const lateMessage = first.onmessage;
    const lateClose = first.onclose;
    const lateError = first.onerror;
    first.open();
    first.message({ type: 'auth_ok', payload: {} });
    first.message({ type: 'error', payload: { code: 'INTERACTION_OWNED_BY_CALL', retryable: true } });
    first.serverClose();
    await jest.advanceTimersByTimeAsync(2_000);
    const second = FakeWebSocket.instances[1];

    lateOpen?.();
    lateMessage?.({ data: JSON.stringify({ type: 'auth_ok', payload: {} }) });
    lateMessage?.({ data: JSON.stringify({ type: 'chat.ready', payload: {
      character_id: 'luotianyi', interaction_id: 'stale', schema_version: 1,
    } }) });
    await jest.advanceTimersByTimeAsync(80);
    expect(await Promise.race([reconnecting.then(() => 'settled'), Promise.resolve('pending')])).toBe('pending');

    bindChat(second, 'current');
    await jest.advanceTimersByTimeAsync(80);
    await expect(reconnecting).resolves.toBe(true);
    const socketCount = FakeWebSocket.instances.length;
    lateError?.({ type: 'error' });
    lateClose?.({ code: 1013, reason: '', wasClean: false });
    await jest.advanceTimersByTimeAsync(30_000);
    expect(FakeWebSocket.instances).toHaveLength(socketCount);

    const sent = client.sendChat('current owner', false, 'current-message');
    await jest.advanceTimersByTimeAsync(80);
    expect(second.sent).toContainEqual(expect.objectContaining({ client_msg_id: 'current-message' }));
    second.message({ type: 'server_ack', reply_to: 'current-message', payload: { ok: true } });
    await expect(sent).resolves.toMatchObject({ ok: true });
    client.disconnectWs();
  });

  it('rejects chat.ready for another character and keeps chat unavailable', async () => {
    const client = new NetworkClient();
    client.connectWs('alice', 'token', 'current-character', callbacks);
    const socket = FakeWebSocket.instances[0];
    socket.open();
    socket.message({ type: 'auth_ok', payload: {} });
    socket.message({ type: 'chat.ready', payload: {
      character_id: 'other-character', interaction_id: 'wrong', schema_version: 1,
    } });
    const pending = client.sendChat('blocked', false, 'wrong-character-message');
    await jest.advanceTimersByTimeAsync(160);
    expect(socket.sent.some((message) => message.type === 'user_text')).toBe(false);
    client.disconnectWs();
    await jest.advanceTimersByTimeAsync(80);
    await expect(pending).resolves.toMatchObject({ ok: false, drop: true });
  });

  it('does not retry rejected credentials', async () => {
    const client = new NetworkClient();
    const reconnecting = client.reconnectWs('alice', 'bad-token', 'luotianyi', callbacks, 10_000);
    const socket = FakeWebSocket.instances[0];
    socket.open();
    socket.message({ type: 'auth_error', payload: { message: 'invalid token' } });
    await jest.advanceTimersByTimeAsync(10_000);
    await expect(reconnecting).resolves.toBe(false);
    expect(FakeWebSocket.instances).toHaveLength(1);
  });

  it('stops ownership retries when the explicit budget is exhausted', async () => {
    const client = new NetworkClient();
    const reconnecting = client.reconnectWs('alice', 'token', 'luotianyi', callbacks, 3_000);
    const first = FakeWebSocket.instances[0];
    first.open();
    first.message({ type: 'auth_ok', payload: {} });
    first.message({
      type: 'error',
      payload: { code: 'INTERACTION_OWNED_BY_CALL', message: 'owned', retryable: true },
    });
    first.serverClose();
    await jest.advanceTimersByTimeAsync(2_000);
    const second = FakeWebSocket.instances[1];
    second.open();
    second.message({ type: 'auth_ok', payload: {} });
    second.message({
      type: 'error',
      payload: { code: 'INTERACTION_OWNED_BY_CALL', message: 'owned', retryable: true },
    });
    second.serverClose();
    await jest.advanceTimersByTimeAsync(1_080);
    await expect(reconnecting).resolves.toBe(false);
    const socketCount = FakeWebSocket.instances.length;
    await jest.advanceTimersByTimeAsync(30_000);
    expect(FakeWebSocket.instances).toHaveLength(socketCount);
  });

  it('does not revive chat when a late ready arrives after logout', async () => {
    const client = new NetworkClient();
    const reconnecting = client.reconnectWs('alice', 'token', 'luotianyi', callbacks, 10_000);
    const socket = FakeWebSocket.instances[0];
    socket.open();
    socket.message({ type: 'auth_ok', payload: {} });
    client.disconnectWs();
    socket.message({
      type: 'chat.ready',
      payload: { character_id: 'luotianyi', interaction_id: 'late', schema_version: 1 },
    });
    await jest.advanceTimersByTimeAsync(80);
    await expect(reconnecting).resolves.toBe(false);
    await expect(client.sendChat('must not send')).resolves.toMatchObject({ drop: true });
  });

  it('waits for switch_ready with the same client request id before closing chat', async () => {
    const client = new NetworkClient();
    client.connectWs('alice', 'token', 'luotianyi', callbacks);
    const socket = FakeWebSocket.instances[0];
    bindChat(socket);

    const switching = client.prepareCallSwitch('request-1', 'luotianyi');
    await jest.advanceTimersByTimeAsync(80);
    expect(socket.sent).toContainEqual({
      protocol: 'call.v1',
      type: 'call.switch_prepare',
      client_request_id: 'request-1',
      character_id: 'luotianyi',
    });
    expect(socket.readyState).toBe(FakeWebSocket.OPEN);
    socket.message({
      protocol: 'call.v1',
      type: 'call.switch_ready',
      client_request_id: 'request-1',
      character_id: 'luotianyi',
    });
    await expect(switching).resolves.toBeUndefined();
    expect(socket.readyState).toBe(3);
  });

  it('rejects a switch marker with the wrong character and preserves the current chat', async () => {
    const client = new NetworkClient();
    client.connectWs('alice', 'token', 'luotianyi', callbacks);
    const socket = FakeWebSocket.instances[0];
    bindChat(socket);
    const switching = client.prepareCallSwitch('request-2', 'luotianyi');
    await jest.advanceTimersByTimeAsync(80);
    socket.message({
      protocol: 'call.v1', type: 'call.switch_ready', client_request_id: 'request-2', character_id: 'other',
    });
    await expect(switching).rejects.toThrow('CALL_SWITCH_REJECTED:CHARACTER_ID_MISMATCH');
    expect(socket.readyState).toBe(FakeWebSocket.OPEN);

    const sent = client.sendChat('still bound', false, 'message-after-bad-switch');
    await jest.advanceTimersByTimeAsync(80);
    expect(socket.sent).toContainEqual(expect.objectContaining({ client_msg_id: 'message-after-bad-switch' }));
    socket.message({ type: 'server_ack', reply_to: 'message-after-bad-switch', payload: { ok: true } });
    await expect(sent).resolves.toMatchObject({ ok: true });
    client.disconnectWs();
  });
});

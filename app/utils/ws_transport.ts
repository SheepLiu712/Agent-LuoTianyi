import { server_config } from '../config';
import { AgentMessagePayload } from '../types/chat';
import { addDebugTrace } from './debug_trace';

interface AckResult {
  ok: boolean;
  request_id: string;
  error?: string;
  drop?: boolean;
}

interface ServerEnvelope {
  type?: string;
  payload?: Record<string, unknown>;
  reply_to?: string;
}

interface AckWaiter {
  resolve: (result: AckResult) => void;
  timer: ReturnType<typeof setTimeout>;
}

export interface WsCallbacks {
  onAgentMessage: (payload: AgentMessagePayload) => void;
  onAgentStateChanged: (state: string) => void;
  onError: (errorText: string) => void;
}

export class WebSocketTransport {
  private ws: WebSocket | null = null;
  private readonly username: string;
  private readonly token: string;
  private readonly callbacks: WsCallbacks;
  private readonly ackWaiters = new Map<string, AckWaiter>();
  private readonly heartbeatIntervalMs = 10000;
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private pingId = 0;
  private reconnectAttempts = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private isStopped = true;
  private isConnected = false;
  private isAuthed = false;

  constructor(username: string, token: string, callbacks: WsCallbacks) {
    this.username = username;
    this.token = token;
    this.callbacks = callbacks;
  }

  start() {
    this.isStopped = false;
    addDebugTrace('ws', 'start transport', { username: this.username });
    this.connect();
  }

  stop() {
    this.isStopped = true;
    this.isConnected = false;
    this.isAuthed = false;
    addDebugTrace('ws', 'stop transport');
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.stopHeartbeat();
    this.rejectAllWaiters('websocket stopped');
    if (this.ws) {
      this.ws.onopen = null;
      this.ws.onclose = null;
      this.ws.onerror = null;
      this.ws.onmessage = null;
      this.ws.close();
      this.ws = null;
    }
  }

  async submitUserText(message: string, ackTimeout = 10000): Promise<AckResult> {
    return this.sendWithAck('user_text', { message }, ackTimeout);
  }

  async submitUserImage(
    imageBase64: string,
    mimeType: string,
    imageClientPath: string,
    ackTimeout = 10000,
  ): Promise<AckResult> {
    return this.sendWithAck(
      'user_image',
      {
        image_base64: imageBase64,
        mime_type: mimeType,
        image_client_path: imageClientPath,
      },
      ackTimeout,
    );
  }

  async submitUserTyping(textLength: number, ackTimeout = 5000): Promise<AckResult> {
    return this.sendWithAck('user_typing', { is_typing: true, text_length: textLength }, ackTimeout);
  }

  private connect() {
    if (this.isStopped) {
      return;
    }

    const wsUrl = this.buildWsUrl(server_config.BASE_URL);
    this.ws = new WebSocket(wsUrl);

    this.ws.onopen = () => {
      this.isConnected = true;
      this.reconnectAttempts = 0;
      this.sendAuth();
      this.startHeartbeat();
    };

    this.ws.onmessage = (event) => {
      this.handleServerMessage(event.data);
    };

    this.ws.onerror = () => {
      addDebugTrace('ws', 'onerror');
      this.callbacks.onError('WebSocket 连接发生错误。');
    };

    this.ws.onclose = () => {
      this.isConnected = false;
      this.isAuthed = false;
      this.stopHeartbeat();
      if (!this.isStopped) {
        this.scheduleReconnect();
      }
    };
  }

  private scheduleReconnect() {
    const delay = Math.min(2 ** Math.max(this.reconnectAttempts, 1), 30) * 1000;
    this.reconnectAttempts += 1;
    addDebugTrace('ws', 'schedule reconnect', { delayMs: delay, reconnectAttempts: this.reconnectAttempts });
    this.reconnectTimer = setTimeout(() => {
      this.connect();
    }, delay);
  }

  private buildWsUrl(baseUrl: string) {
    if (baseUrl.startsWith('https://')) {
      return `wss://${baseUrl.slice('https://'.length).replace(/\/$/, '')}/chat_ws`;
    }
    if (baseUrl.startsWith('http://')) {
      return `ws://${baseUrl.slice('http://'.length).replace(/\/$/, '')}/chat_ws`;
    }
    throw new Error('base_url must start with http:// or https://');
  }

  private sendAuth() {
    this.sendRaw({
      type: 'user_auth',
      client_msg_id: `auth-${Date.now()}`,
      ts: Date.now(),
      payload: {
        username: this.username,
        token: this.token,
      },
    });
  }

  private startHeartbeat() {
    this.stopHeartbeat();
    this.heartbeatTimer = setInterval(() => {
      if (!this.isConnected || !this.isAuthed) {
        return;
      }
      this.pingId += 1;
      this.sendRaw({
        type: 'hb_ping',
        client_msg_id: `ping-${this.pingId}`,
        ts: Date.now(),
        payload: { ping_id: this.pingId },
      });
    }, this.heartbeatIntervalMs);
  }

  private stopHeartbeat() {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
  }

  private async waitUntilReady(timeoutMs = 10000) {
    const start = Date.now();
    addDebugTrace('ws', 'waitUntilReady begin', {
      timeoutMs,
      isConnected: this.isConnected,
      isAuthed: this.isAuthed,
    });
    while (!this.isStopped && (!this.isConnected || !this.isAuthed)) {
      if (Date.now() - start > timeoutMs) {
        addDebugTrace('ws', 'waitUntilReady timeout', {
          waitedMs: Date.now() - start,
          isConnected: this.isConnected,
          isAuthed: this.isAuthed,
        });
        throw new Error('websocket not ready');
      }
      await new Promise((resolve) => setTimeout(resolve, 80));
    }
    addDebugTrace('ws', 'waitUntilReady ok', { waitedMs: Date.now() - start });
  }

  private async sendWithAck(
    eventType: string,
    payload: Record<string, unknown>,
    timeoutMs: number,
  ): Promise<AckResult> {
    const requestId = `c-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    addDebugTrace('ack', 'prepare sendWithAck', { eventType, requestId, timeoutMs });

    try {
      await this.waitUntilReady();
    } catch {
      addDebugTrace('ack', 'sendWithAck blocked: websocket not ready', { eventType, requestId });
      return {
        ok: false,
        request_id: requestId,
        error: 'not logged in',
        drop: true,
      };
    }

    return new Promise<AckResult>((resolve) => {
      const timer = setTimeout(() => {
        this.ackWaiters.delete(requestId);
        addDebugTrace('ack', 'ack timeout', { eventType, requestId, timeoutMs });
        resolve({
          ok: false,
          request_id: requestId,
          error: 'Wait server ack timeout',
        });
      }, timeoutMs);

      this.ackWaiters.set(requestId, { resolve, timer });
      addDebugTrace('ack', 'send raw with waiter', {
        eventType,
        requestId,
        pendingWaiters: this.ackWaiters.size,
      });
      this.sendRaw({
        type: eventType,
        client_msg_id: requestId,
        ts: Date.now(),
        payload,
      });
    });
  }

  private sendRaw(message: Record<string, unknown>) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      addDebugTrace('ws', 'sendRaw skipped: socket not open', {
        readyState: this.ws?.readyState,
        type: String(message.type || ''),
      });
      return;
    }
    this.ws.send(JSON.stringify(message));
  }

  private handleServerMessage(raw: unknown) {
    try {
      const envelope = JSON.parse(String(raw)) as ServerEnvelope;
      const eventType = envelope.type || '';
      const payload = envelope.payload || {};
      if (eventType === 'system_ready') {
        addDebugTrace('ws', 'recv system_ready');
        this.sendAuth();
        return;
      }

      if (eventType === 'auth_ok') {
        this.isAuthed = true;
        return;
      }

      if (eventType === 'auth_error') {
        this.isAuthed = false;
        addDebugTrace('ws', 'recv auth_error', { message: String(payload.message || '鉴权失败') });
        this.callbacks.onError(String(payload.message || '鉴权失败'));
        return;
      }

      if (eventType === 'server_ack') {
        const replyTo = envelope.reply_to;
        if (replyTo && this.ackWaiters.has(replyTo)) {
          const waiter = this.ackWaiters.get(replyTo)!;
          clearTimeout(waiter.timer);
          this.ackWaiters.delete(replyTo);
          addDebugTrace('ack', 'recv ack', { replyTo, pendingWaiters: this.ackWaiters.size });
          waiter.resolve({ ok: true, request_id: replyTo });
        }
        return;
      }

      if (eventType === 'agent_state_changed') {
        this.callbacks.onAgentStateChanged(String(payload.state || 'waiting'));
        return;
      }

      if (eventType === 'agent_message') {
        this.callbacks.onAgentMessage(payload as AgentMessagePayload);
        return;
      }

      if (eventType === 'error') {
        addDebugTrace('ws', 'recv protocol error', { message: String(payload.message || '协议错误') });
        this.callbacks.onError(String(payload.message || '协议错误'));
      }
    } catch {
      addDebugTrace('ws', 'recv parse error');
      this.callbacks.onError('收到无法解析的 WebSocket 消息');
    }
  }

  private rejectAllWaiters(errorText: string) {
    addDebugTrace('ack', 'reject all waiters', { count: this.ackWaiters.size, errorText });
    for (const [requestId, waiter] of this.ackWaiters.entries()) {
      clearTimeout(waiter.timer);
      waiter.resolve({
        ok: false,
        request_id: requestId,
        error: errorText,
      });
    }
    this.ackWaiters.clear();
  }
}

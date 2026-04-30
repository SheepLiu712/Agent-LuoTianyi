import { AppState } from 'react-native';
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
  private reconnectDueAt: number | null = null;
  private reconnectDelayMs: number | null = null;
  private reconnectPausedForBackground = false;
  private appStateSubscription: { remove: () => void } | null = null;
  private isStopped = true;
  private isConnected = false;
  private isAuthed = false;

  constructor(username: string, token: string, callbacks: WsCallbacks) {
    this.username = username;
    this.token = token;
    this.callbacks = callbacks;
  }

  private isBackgrounded() {
    return AppState.currentState !== 'active';
  }

  private describeWebSocketEvent(event: unknown) {
    if (!event || typeof event !== 'object') {
      return { rawType: typeof event, rawValue: String(event) };
    }

    const eventRecord = event as Record<string, unknown>;
    const target = eventRecord.target as Record<string, unknown> | undefined;
    const currentTarget = eventRecord.currentTarget as Record<string, unknown> | undefined;

    return {
      eventType: typeof eventRecord.type === 'string' ? eventRecord.type : undefined,
      message: typeof eventRecord.message === 'string' ? eventRecord.message : undefined,
      code: typeof eventRecord.code === 'number' ? eventRecord.code : undefined,
      reason: typeof eventRecord.reason === 'string' ? eventRecord.reason : undefined,
      wasClean: typeof eventRecord.wasClean === 'boolean' ? eventRecord.wasClean : undefined,
      readyState: typeof target?.readyState === 'number' ? target.readyState : undefined,
      targetUrl: typeof target?.url === 'string' ? target.url : undefined,
      currentTargetUrl: typeof currentTarget?.url === 'string' ? currentTarget.url : undefined,
      keys: Object.keys(eventRecord),
    };
  }

  private handleAppStateChange = (nextAppState: string) => {
    addDebugTrace('ws', 'app state change', {
      nextAppState,
      isConnected: this.isConnected,
      isAuthed: this.isAuthed,
      hasReconnectTimer: !!this.reconnectTimer,
      reconnectPausedForBackground: this.reconnectPausedForBackground,
      reconnectDueAt: this.reconnectDueAt,
    });

    if (nextAppState === 'active') {
      this.resumeReconnectIfNeeded();
      return;
    }

    this.pauseReconnectIfNeeded();
  };

  start() {
    this.isStopped = false;
    addDebugTrace('ws', 'start transport', { username: this.username });
    if (!this.appStateSubscription) {
      this.appStateSubscription = AppState.addEventListener('change', this.handleAppStateChange);
    }
    this.connect();
  }

  stop() {
    this.isStopped = true;
    this.isConnected = false;
    this.isAuthed = false;
    addDebugTrace('ws', 'stop transport');
    this.clearReconnectTimer();
    this.stopHeartbeat();
    this.rejectAllWaiters('websocket stopped');
    this.reconnectPausedForBackground = false;
    this.reconnectDueAt = null;
    this.reconnectDelayMs = null;
    if (this.appStateSubscription) {
      this.appStateSubscription.remove();
      this.appStateSubscription = null;
    }
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

    this.ws.onerror = (event) => {
      const detail = this.describeWebSocketEvent(event);
      addDebugTrace('ws', 'onerror', detail);
      if (this.isBackgrounded()) {
        addDebugTrace('ws', 'onerror suppressed while backgrounded', detail);
        return;
      }
      this.callbacks.onError('WebSocket 连接发生错误。');
    };

    this.ws.onclose = (event) => {
      const detail = this.describeWebSocketEvent(event);
      addDebugTrace('ws', 'onclose', detail);
      this.isConnected = false;
      this.isAuthed = false;
      this.stopHeartbeat();
      if (this.isStopped) {
        return;
      }

      if (this.isBackgrounded()) {
        this.deferReconnectWhileBackgrounded();
        return;
      }

      this.scheduleReconnect();
    };
  }

  private deferReconnectWhileBackgrounded() {
    const delay = Math.min(2 ** Math.max(this.reconnectAttempts, 1), 30) * 1000;
    this.reconnectAttempts += 1;
    this.reconnectPausedForBackground = true;
    this.reconnectDelayMs = delay;
    this.reconnectDueAt = Date.now() + delay;
    addDebugTrace('ws', 'defer reconnect while backgrounded', {
      delayMs: delay,
      reconnectAttempts: this.reconnectAttempts,
      reconnectDueAt: this.reconnectDueAt,
    });
  }

  private clearReconnectTimer() {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  private armReconnectTimer(delayMs: number) {
    this.clearReconnectTimer();
    this.reconnectPausedForBackground = false;
    this.reconnectDelayMs = delayMs;
    this.reconnectDueAt = Date.now() + delayMs;
    addDebugTrace('ws', 'arm reconnect timer', {
      delayMs,
      reconnectAttempts: this.reconnectAttempts,
      reconnectDueAt: this.reconnectDueAt,
    });
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.reconnectDueAt = null;
      this.reconnectDelayMs = null;
      this.connect();
    }, delayMs);
  }

  private scheduleReconnect() {
    const delay = Math.min(2 ** Math.max(this.reconnectAttempts, 1), 30) * 1000;
    this.reconnectAttempts += 1;
    this.armReconnectTimer(delay);
  }

  private pauseReconnectIfNeeded() {
    if (!this.reconnectTimer) {
      return;
    }

    const remainingMs = Math.max((this.reconnectDueAt || Date.now()) - Date.now(), 0);
    this.clearReconnectTimer();
    this.reconnectPausedForBackground = true;
    this.reconnectDelayMs = remainingMs;
    this.reconnectDueAt = Date.now() + remainingMs;
    addDebugTrace('ws', 'pause reconnect while backgrounded', {
      remainingMs,
      reconnectAttempts: this.reconnectAttempts,
    });
  }

  private resumeReconnectIfNeeded() {
    if (!this.isStopped && this.reconnectPausedForBackground && !this.reconnectTimer) {
      const delayMs = Math.max(this.reconnectDelayMs ?? 0, 0);
      addDebugTrace('ws', 'resume reconnect on foreground', {
        delayMs,
        reconnectAttempts: this.reconnectAttempts,
      });
      this.armReconnectTimer(delayMs);
    }
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

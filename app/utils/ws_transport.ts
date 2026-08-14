import { AppState } from 'react-native';
import { server_config } from '../config';
import { AgentMessagePayload } from '../types/chat';
import { WSEventType } from '../types/ws_events';
import { addDebugTrace } from './debug_trace';
import { AckResult, normalizeServerAck } from './ws_ack';
import {
  buildChatCompletionsPayload,
  callLlmProvider,
  CLIENT_JSON_UNSUPPORTED_MARKER,
} from './llm_client';
import { getModuleConfig } from './llm_key_storage';

export type { AckResult } from './ws_ack';
export { normalizeServerAck } from './ws_ack';

export const WS_CLIENT_CAPABILITIES = ['negative_ack_v1'] as const;

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
  private hasNotifiedReconnectStruggle = false;
  private appStateSubscription: { remove: () => void } | null = null;
  private isStopped = true;
  private isConnected = false;
  private isAuthed = false;
  private authRejected = false;
  private clientMode = { text: false, vlm: false }; // 服务端当前客户端 LLM 模式（随连接重置）

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
    this.authRejected = false;
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
    this.hasNotifiedReconnectStruggle = false;
    addDebugTrace('ws', 'stop transport');
    this.clearReconnectTimer();
    this.stopHeartbeat();
    this.rejectAllWaiters('websocket stopped', {
      code: 'TRANSPORT_STOPPED',
      retryable: false,
      drop: true,
    });
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

  async submitUserText(message: string, isProactive = false, ackTimeout = 10000, clientMsgId?: string): Promise<AckResult> {
    const cfg = await getModuleConfig('llm_models');
    const payload: Record<string, unknown> = { message };
    if (isProactive) {
      payload.is_proactive = true;
    }
    this.clientMode.text = Boolean(cfg?.enabled);
    payload.llm_mode = { ...this.clientMode };
    return this.sendWithAck(WSEventType.USER_TEXT, payload, ackTimeout, clientMsgId);
  }

  async submitUserImage(
    imageBase64: string,
    mimeType: string,
    imageClientPath: string,
    ackTimeout = 10000,
    clientMsgId?: string,
  ): Promise<AckResult> {
    const cfg = await getModuleConfig('vlm_models');
    const payload: Record<string, unknown> = {
      image_base64: imageBase64,
      mime_type: mimeType,
      image_client_path: imageClientPath,
    };
    this.clientMode.vlm = Boolean(cfg?.enabled);
    payload.llm_mode = { ...this.clientMode };
    return this.sendWithAck(WSEventType.USER_IMAGE, payload, ackTimeout, clientMsgId);
  }

  async submitUserTyping(textLength: number, ackTimeout = 5000, clientMsgId?: string): Promise<AckResult> {
    return this.sendWithAck(
      WSEventType.USER_TYPING,
      { is_typing: true, text_length: textLength },
      ackTimeout,
      clientMsgId,
    );
  }

  async submitUserTouch(
    touchArea: string | string[],
    clickFrequency?: Record<string, number>,
    touchMeta?: Record<string, unknown>,
    ackTimeout = 5000,
    clientMsgId?: string,
  ): Promise<AckResult> {
    const payload: Record<string, unknown> = {};
    if (typeof touchArea === 'string') {
      payload.touch_area = touchArea;
    } else {
      payload.touchArea = touchArea;
    }
    if (clickFrequency) {
      payload.click_frequency = clickFrequency;
    }
    if (touchMeta) {
      Object.assign(payload, touchMeta);
    }
    return this.sendWithAck(WSEventType.USER_TOUCH, payload, ackTimeout, clientMsgId);
  }

  async submitUserImageSelecting(ackTimeout = 5000, clientMsgId?: string): Promise<AckResult> {
    return this.sendWithAck(WSEventType.USER_IMAGE_SELECTING, {}, ackTimeout, clientMsgId);
  }

  async submitUserImageSelectingCancel(ackTimeout = 5000, clientMsgId?: string): Promise<AckResult> {
    return this.sendWithAck(WSEventType.USER_IMAGE_SELECTING_CANCEL, {}, ackTimeout, clientMsgId);
  }

  private connect() {
    if (this.isStopped) {
      return;
    }

    const wsUrl = this.buildWsUrl(server_config.BASE_URL);
    this.ws = new WebSocket(wsUrl);

    this.ws.onopen = () => {
      this.isConnected = true;
      this.clientMode = { text: false, vlm: false };
      this.reconnectAttempts = 0;
      this.sendAuth();
      this.startHeartbeat();
    };

    this.ws.onmessage = (event) => {
      this.handleServerMessage(event.data);
    };

    this.ws.onerror = (event) => {
      // 瞬时网络抖动/服务器短暂不可用都会触发 onerror，随后 onclose 会自动重连。
      // 这里不直接向用户抛"连接错误"，避免在自动重连自愈期间刷出多条错误气泡（Bug#10）。
      // 持续重连失败时的提示由 notifyReconnectStruggleIfNeeded 在 onclose 中统一给出。
      const detail = this.describeWebSocketEvent(event);
      addDebugTrace('ws', 'onerror', detail);
    };

    this.ws.onclose = (event) => {
      const detail = this.describeWebSocketEvent(event);
      addDebugTrace('ws', 'onclose', detail);
      this.isConnected = false;
      this.isAuthed = false;
      this.stopHeartbeat();
      this.rejectAllWaiters('websocket disconnected', {
        code: 'DISCONNECTED',
        retryable: true,
        drop: false,
      });
      if (this.isStopped) {
        return;
      }
      if (!this.canReconnectAfterClose()) {
        addDebugTrace('ws', 'reconnect suppressed after authentication rejection');
        return;
      }

      if (this.isBackgrounded()) {
        this.deferReconnectWhileBackgrounded();
        return;
      }

      this.scheduleReconnect();
      this.notifyReconnectStruggleIfNeeded();
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

  private notifyReconnectStruggleIfNeeded() {
    // 仅当连续多次重连失败（指数退避累计约 14 秒）时，温和提示一次，
    // 避免瞬时抖动刷出多条"连接错误"。重连成功或 stop 后重置，下次断线可再次提示。
    if (this.isBackgrounded() || this.hasNotifiedReconnectStruggle) {
      return;
    }
    if (this.reconnectAttempts >= 3) {
      this.hasNotifiedReconnectStruggle = true;
      this.callbacks.onError('网络连接不稳定，正在自动重连…');
    }
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
      type: WSEventType.USER_AUTH,
      client_msg_id: `auth-${Date.now()}`,
      ts: Date.now(),
      payload: {
        username: this.username,
        token: this.token,
        capabilities: [...WS_CLIENT_CAPABILITIES],
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
        type: WSEventType.HB_PING,
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

  private async waitUntilReady(
    timeoutMs = 10000,
  ): Promise<'ready' | 'auth_rejected' | 'stopped' | 'timeout'> {
    const start = Date.now();
    while (!this.isStopped && (!this.isConnected || !this.isAuthed)) {
      if (this.authRejected) {
        return 'auth_rejected';
      }
      if (Date.now() - start > timeoutMs) {
        addDebugTrace('ws', 'waitUntilReady timeout', {
          waitedMs: Date.now() - start,
          isConnected: this.isConnected,
          isAuthed: this.isAuthed,
        });
        return 'timeout';
      }
      await new Promise((resolve) => setTimeout(resolve, 80));
    }
    if (this.authRejected) {
      return 'auth_rejected';
    }
    if (this.isStopped) {
      return 'stopped';
    }
    return 'ready';
  }

  private canReconnectAfterClose() {
    return !this.authRejected;
  }

  private async sendWithAck(
    eventType: string,
    payload: Record<string, unknown>,
    timeoutMs: number,
    clientMsgId?: string,
  ): Promise<AckResult> {
    const requestId = clientMsgId || `c-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

    const readiness = await this.waitUntilReady();
    if (readiness !== 'ready') {
      const permanent = readiness === 'auth_rejected' || readiness === 'stopped';
      addDebugTrace('ack', 'sendWithAck blocked: websocket not ready', { eventType, requestId });
      return {
        ok: false,
        request_id: requestId,
        error: readiness === 'auth_rejected' ? 'authentication rejected' : 'websocket not ready',
        code: readiness === 'auth_rejected' ? 'AUTH_REJECTED' : 'NOT_READY',
        retryable: !permanent,
        drop: permanent,
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
      const sent = this.sendRaw({
        type: eventType,
        client_msg_id: requestId,
        ts: Date.now(),
        payload,
      });
      if (!sent) {
        clearTimeout(timer);
        this.ackWaiters.delete(requestId);
        resolve({
          ok: false,
          request_id: requestId,
          error: 'websocket disconnected before send',
          code: 'DISCONNECTED',
          retryable: true,
          drop: false,
        });
      }
    });
  }

  private sendRaw(message: Record<string, unknown>): boolean {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      addDebugTrace('ws', 'sendRaw skipped: socket not open', {
        readyState: this.ws?.readyState,
        type: String(message.type || ''),
      });
      return false;
    }
    try {
      this.ws.send(JSON.stringify(message));
      return true;
    } catch {
      addDebugTrace('ws', 'sendRaw failed', { type: String(message.type || '') });
      return false;
    }
  }

  private handleServerMessage(raw: unknown) {
    try {
      const envelope = JSON.parse(String(raw)) as ServerEnvelope;
      const eventType = envelope.type || '';
      const payload = envelope.payload || {};
      if (eventType === WSEventType.SYSTEM_READY) {
        addDebugTrace('ws', 'recv system_ready');
        this.sendAuth();
        return;
      }

      if (eventType === WSEventType.AUTH_OK) {
        this.authRejected = false;
        this.isAuthed = true;
        this.reconnectAttempts = 0;
        this.hasNotifiedReconnectStruggle = false;
        return;
      }

      if (eventType === WSEventType.AUTH_ERROR) {
        this.isAuthed = false;
        this.authRejected = true;
        this.rejectAllWaiters(String(payload.message || 'authentication rejected'), {
          code: 'AUTH_REJECTED',
          retryable: false,
          drop: true,
        });
        addDebugTrace('ws', 'recv auth_error', { message: String(payload.message || '鉴权失败') });
        this.callbacks.onError(String(payload.message || '鉴权失败'));
        this.clearReconnectTimer();
        this.stopHeartbeat();
        try {
          this.ws?.close();
        } catch {
          // The close path already suppresses reconnect for rejected credentials.
        }
        return;
      }

      if (eventType === WSEventType.SERVER_ACK) {
        const replyTo = envelope.reply_to;
        if (replyTo && this.ackWaiters.has(replyTo)) {
          const waiter = this.ackWaiters.get(replyTo)!;
          clearTimeout(waiter.timer);
          this.ackWaiters.delete(replyTo);
          waiter.resolve(normalizeServerAck(payload, replyTo));
        }
        return;
      }

      if (eventType === WSEventType.AGENT_STATE_CHANGED) {
        this.callbacks.onAgentStateChanged(String(payload.state || 'waiting'));
        return;
      }

      if (eventType === WSEventType.LLM_REQUEST) {
        void this.handleLlmRequest(payload);
        return;
      }

      if (eventType === WSEventType.AGENT_MESSAGE) {
        this.callbacks.onAgentMessage(payload as AgentMessagePayload);
        return;
      }

      if (eventType === WSEventType.SERVER_ERROR) {
        addDebugTrace('ws', 'recv protocol error', { message: String(payload.message || '协议错误') });
        this.callbacks.onError(String(payload.message || '协议错误'));
      }
    } catch {
      addDebugTrace('ws', 'recv parse error');
      this.callbacks.onError('收到无法解析的 WebSocket 消息');
    }
  }

  private async handleLlmRequest(payload: Record<string, unknown>) {
    const requestId = String(payload.request_id || '');
    if (!requestId) {
      return;
    }
    const sendError = (error: string) => {
      this.sendRaw({
        type: WSEventType.LLM_RESPONSE,
        ts: Date.now(),
        payload: { request_id: requestId, error },
      });
    };
    try {
      const isImage = typeof payload.image_base64 === 'string' && !!payload.image_base64;
      const cfg = isImage
        ? await getModuleConfig('vlm_models')
        : await getModuleConfig('llm_models');
      if (!cfg || !cfg.enabled || !cfg.apiKey) {
        addDebugTrace('llm', 'llm_request without api key');
        sendError('no api key configured on client');
        return;
      }
      const baseUrl = cfg.baseUrl || '';
      if (!baseUrl) {
        sendError('LLM 配置不完整，请在 LLM 模型设置中重新保存');
        return;
      }
      const url = `${baseUrl.replace(/\/+$/, '')}/chat/completions`;
      const model = cfg.model || '';
      if (!model) {
        sendError('missing provider info');
        return;
      }
      const serverParams = (payload.params || {}) as Record<string, unknown>;
      let cachedParams: Record<string, unknown> = {};
      if (cfg.paramsText) {
        try {
          const parsed = JSON.parse(cfg.paramsText);
          if (typeof parsed === 'object' && parsed !== null && !Array.isArray(parsed)) {
            cachedParams = parsed as Record<string, unknown>;
          }
        } catch {
          // 忽略损坏的参数缓存
        }
      }

      const caps = cfg.modelCapabilities ?? {};
      const capableThinking = Boolean(caps.can_enable_thinking);
      const capableJson = Boolean(caps.can_use_json);
      const serverEnableThinking = Boolean(payload.enable_thinking);
      const serverUseJson = Boolean(payload.use_json);
      if (serverUseJson && !capableJson) {
        sendError(CLIENT_JSON_UNSUPPORTED_MARKER);
        return;
      }
      const body = buildChatCompletionsPayload({
        prompt: String(payload.prompt || ''),
        model,
        params: { ...serverParams, ...cachedParams },
        enableThinking: capableThinking && serverEnableThinking,
        useJson: serverUseJson,
        imageBase64: typeof payload.image_base64 === 'string' ? payload.image_base64 : undefined,
      });
      const result = await callLlmProvider({ url, apiKey: cfg.apiKey, body });
      this.sendRaw({
        type: WSEventType.LLM_RESPONSE,
        ts: Date.now(),
        payload: {
          request_id: requestId,
          content: result.content,
          usage: result.usage ?? null,
        },
      });
    } catch (e) {
      addDebugTrace('llm', 'llm_request failed', { error: String(e) });
      sendError(e instanceof Error ? e.message : String(e));
    }
  }

  private rejectAllWaiters(
    errorText: string,
    options: Pick<AckResult, 'code' | 'retryable' | 'drop'> = {},
  ) {
    addDebugTrace('ack', 'reject all waiters', { count: this.ackWaiters.size, errorText });
    for (const [requestId, waiter] of this.ackWaiters.entries()) {
      clearTimeout(waiter.timer);
      waiter.resolve({
        ok: false,
        request_id: requestId,
        error: errorText,
        ...options,
      });
    }
    this.ackWaiters.clear();
  }
}

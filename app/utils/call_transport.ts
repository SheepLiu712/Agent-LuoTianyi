import { AppState } from 'react-native';
import { server_config } from '../config';
import { CallAckResult, CallCallbacks, CallEventEnvelope, CallStatus } from '../types/call';
import { WSEventType } from '../types/ws_events';
import { addDebugTrace } from './debug_trace';

interface AckWaiter {
  resolve: (result: CallAckResult) => void;
  timer: ReturnType<typeof setTimeout>;
}

function makeRequestId(prefix: string) {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export class CallTransport {
  private static readonly MAX_RECONNECT_ATTEMPTS = 5;
  private ws: WebSocket | null = null;
  private readonly username: string;
  private readonly token: string;
  private readonly callbacks: CallCallbacks;
  private readonly ackWaiters = new Map<string, AckWaiter>();
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectAttempts = 0;
  private isStopped = true;
  private isAuthed = false;
  private callId: string | null = null;
  private status: CallStatus = 'idle';
  private appStateSubscription: { remove: () => void } | null = null;
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private pingId = 0;

  constructor(username: string, token: string, callbacks: CallCallbacks) {
    this.username = username;
    this.token = token;
    this.callbacks = callbacks;
  }

  start() {
    this.isStopped = false;
    this.setStatus('connecting');
    if (!this.appStateSubscription) {
      this.appStateSubscription = AppState.addEventListener('change', (state) => {
        if (state === 'active' && !this.ws && !this.isStopped) {
          this.connect();
        }
      });
    }
    this.connect();
  }

  stop() {
    this.isStopped = true;
    this.clearReconnectTimer();
    this.stopHeartbeat();
    this.rejectAll('通话连接已停止');
    this.isAuthed = false;
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
    this.setStatus('idle');
  }

  async startCall(): Promise<CallAckResult> {
    this.callId = null;
    this.setStatus('requesting');
    return this.sendWithAck(WSEventType.CALL_START, {}, 5000, makeRequestId('call-start'));
  }

  appendAudio(audio: string, seq: number): boolean {
    return this.sendRaw({
      type: WSEventType.CALL_AUDIO_APPEND,
      ts: Date.now(),
      payload: { call_id: this.callId, audio, seq },
    });
  }

  hangup(): Promise<CallAckResult> {
    this.setStatus('ending');
    return this.sendWithAck(WSEventType.CALL_HANGUP, { call_id: this.callId }, 5000, makeRequestId('call-hangup'));
  }

  playbackCompleted(audioId: string, responseId?: string) {
    this.sendRaw({
      type: WSEventType.CALL_PLAYBACK_COMPLETED,
      ts: Date.now(),
      payload: { call_id: this.callId, audio_id: audioId, response_id: responseId },
    });
  }

  playbackStopped(audioId: string, responseId?: string) {
    this.sendRaw({
      type: WSEventType.CALL_PLAYBACK_STOPPED,
      ts: Date.now(),
      payload: { call_id: this.callId, audio_id: audioId, response_id: responseId },
    });
  }

  private connect() {
    if (this.isStopped || (this.ws && this.ws.readyState !== WebSocket.CLOSED)) {
      return;
    }
    const base = server_config.BASE_URL.replace(/\/$/, '');
    const wsBase = base.startsWith('https://')
      ? `wss://${base.slice('https://'.length)}`
      : `ws://${base.slice('http://'.length)}`;
    const ws = new WebSocket(`${wsBase}/call_ws`);
    this.ws = ws;
    ws.onopen = () => {
      this.isAuthed = false;
    };
    ws.onmessage = (event) => this.handleMessage(event.data);
    // A WebSocket error is normally followed by close. Let close drive the
    // bounded reconnect flow so a recoverable interruption does not alarm the user.
    ws.onerror = () => {
      addDebugTrace('call_ws', 'connection error; waiting for close');
    };
    ws.onclose = () => {
      this.ws = null;
      this.isAuthed = false;
      this.stopHeartbeat();
      if (this.isStopped) return;
      if (this.status === 'active' || this.status === 'requesting' || this.status === 'reconnecting') {
        this.setStatus('reconnecting');
      }
      this.scheduleReconnect();
    };
  }

  private sendAuth() {
    this.sendRaw({
      type: WSEventType.USER_AUTH,
      client_msg_id: makeRequestId('call-auth'),
      ts: Date.now(),
      payload: {
        username: this.username,
        token: this.token,
        capabilities: ['negative_ack_v1'],
      },
    });
  }

  private handleMessage(raw: unknown) {
    try {
      const envelope = JSON.parse(String(raw)) as CallEventEnvelope;
      const type = envelope.type || '';
      const payload = envelope.payload || {};
      if (type === WSEventType.SYSTEM_READY) {
        this.sendAuth();
        return;
      }
      if (type === WSEventType.AUTH_OK) {
        this.isAuthed = true;
        this.reconnectAttempts = 0;
        this.startHeartbeat();
        if (this.callId && this.status === 'reconnecting') {
          void this.sendWithAck(WSEventType.CALL_RESUME, { call_id: this.callId }, 4000, makeRequestId('call-resume'));
        }
        return;
      }
      if (type === WSEventType.AUTH_ERROR) {
        this.isStopped = true;
        this.clearReconnectTimer();
        this.stopHeartbeat();
        this.rejectAll('通话身份验证失败');
        this.callbacks.onError(
          typeof payload.message === 'string' ? payload.message : '通话身份验证失败',
        );
        this.setStatus('ended');
        this.ws?.close();
        return;
      }
      if (type === WSEventType.SERVER_ACK) {
        const replyTo = envelope.reply_to;
        if (typeof payload.call_id === 'string') this.callId = payload.call_id;
        const waiter = replyTo ? this.ackWaiters.get(replyTo) : undefined;
        if (waiter) {
          clearTimeout(waiter.timer);
          this.ackWaiters.delete(replyTo!);
          waiter.resolve({
            ok: payload.ok !== false,
            request_id: replyTo!,
            code: typeof payload.code === 'string' ? payload.code : undefined,
            message: typeof payload.message === 'string' ? payload.message : undefined,
            error: typeof payload.message === 'string' ? payload.message : undefined,
          });
        }
        return;
      }
      if (type === WSEventType.SERVER_ERROR) {
        const replyTo = envelope.reply_to;
        const waiter = replyTo ? this.ackWaiters.get(replyTo) : undefined;
        if (waiter) {
          clearTimeout(waiter.timer);
          this.ackWaiters.delete(replyTo!);
          waiter.resolve({
            ok: false,
            request_id: replyTo!,
            code: typeof payload.code === 'string' ? payload.code : undefined,
            message: typeof payload.message === 'string' ? payload.message : undefined,
            error: typeof payload.message === 'string' ? payload.message : '电话服务拒绝了请求',
          });
        }
        return;
      }
      if (type === WSEventType.CALL_REQUESTED && typeof payload.call_id === 'string') {
        this.callId = payload.call_id;
        this.setStatus('requesting');
      }
      if (type === WSEventType.CALL_CONNECTED) {
        if (typeof payload.connected_at === 'string') this.callbacks.onConnectedAt?.(payload.connected_at);
        this.setStatus('active');
      }
      if (type === WSEventType.CALL_RESUMED) this.setStatus('active');
      if (type === WSEventType.CALL_ENDED) {
        this.setStatus('ended');
        this.callId = null;
      }
      if (type === WSEventType.CALL_REJECTED) this.setStatus('ended');
      this.callbacks.onEvent(type, payload);
    } catch (error) {
      addDebugTrace('call_ws', 'parse failed', { error: String(error) });
      this.callbacks.onError('无法解析电话服务消息');
    }
  }

  private async sendWithAck(type: string, payload: Record<string, unknown>, timeoutMs: number, requestId: string) {
    const readyAt = Date.now() + Math.min(timeoutMs, 5000);
    while (!this.isStopped && (!this.isAuthed || !this.ws || this.ws.readyState !== WebSocket.OPEN) && Date.now() < readyAt) {
      await new Promise((resolve) => setTimeout(resolve, 80));
    }
    if (!this.isAuthed || !this.ws || this.ws.readyState !== WebSocket.OPEN) {
      return { ok: false, request_id: requestId, error: '通话连接尚未就绪' };
    }
    return new Promise<CallAckResult>((resolve) => {
      const timer = setTimeout(() => {
        this.ackWaiters.delete(requestId);
        resolve({ ok: false, request_id: requestId, error: '等待电话服务确认超时' });
      }, timeoutMs);
      this.ackWaiters.set(requestId, { resolve, timer });
      this.sendRaw({ type, client_msg_id: requestId, ts: Date.now(), payload });
    });
  }

  private sendRaw(message: Record<string, unknown>): boolean {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return false;
    this.ws.send(JSON.stringify(message));
    return true;
  }

  private scheduleReconnect() {
    if (this.reconnectTimer || this.isStopped) return;
    if (this.reconnectAttempts >= CallTransport.MAX_RECONNECT_ATTEMPTS) {
      this.isStopped = true;
      this.rejectAll('通话网络重连失败');
      this.setStatus('ended');
      this.callbacks.onError('通话网络连接已断开，请稍后重试');
      return;
    }
    const delay = Math.min(2 ** Math.max(this.reconnectAttempts, 1), 2) * 1000;
    this.reconnectAttempts += 1;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, delay);
  }

  private clearReconnectTimer() {
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
  }

  private startHeartbeat() {
    this.stopHeartbeat();
    this.heartbeatTimer = setInterval(() => {
      if (!this.isAuthed) return;
      this.pingId += 1;
      this.sendRaw({
        type: WSEventType.HB_PING,
        client_msg_id: makeRequestId(`call-ping-${this.pingId}`),
        ts: Date.now(),
        payload: { ping_id: this.pingId },
      });
    }, 10000);
  }

  private stopHeartbeat() {
    if (this.heartbeatTimer) clearInterval(this.heartbeatTimer);
    this.heartbeatTimer = null;
  }

  private rejectAll(error: string) {
    for (const [id, waiter] of this.ackWaiters) {
      clearTimeout(waiter.timer);
      waiter.resolve({ ok: false, request_id: id, error });
    }
    this.ackWaiters.clear();
  }

  private setStatus(status: CallStatus) {
    this.status = status;
    this.callbacks.onStatus(status);
  }
}

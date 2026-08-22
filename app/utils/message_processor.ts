import { Buffer } from 'buffer';
import { AppState } from 'react-native';
import { Audio } from 'expo-av';
import * as FileSystem from 'expo-file-system/legacy';
import { AudioStreamType, Live2DAudioPacket, Live2DAudioStopCommand } from '../types/audio';
import { AgentMessagePayload } from '../types/chat';
import { AgentBinder } from './binder';
import { addDebugTrace } from './debug_trace';
import { NetworkClient } from './network_client';

type SendKind =
  | 'text'
  | 'proactive'
  | 'image'
  | 'typing'
  | 'touch'
  | 'image_selecting'
  | 'image_selecting_cancel';

type SendItem = { clientMsgId: string; retryAttempt: number; enqueuedAtMs: number } & (
  | { kind: 'text'; uuid: string; text: string }
  | { kind: 'proactive'; uuid: string; text: string }
  | { kind: 'image'; uuid: string; imageUri: string; mimeType: string }
  | { kind: 'typing'; textLength: number }
  | { kind: 'touch'; touchArea: string | string[]; clickFrequency?: Record<string, number>; touchMeta?: Record<string, unknown> }
  | { kind: 'image_selecting' }
  | { kind: 'image_selecting_cancel' }
);

export const MAX_DURABLE_RETRY_ATTEMPTS = 8;
export const MAX_DURABLE_MESSAGE_AGE_MS = 4 * 60 * 1000;

export function isDurableSendKind(kind: SendKind) {
  return kind === 'text' || kind === 'image' || kind === 'proactive';
}

export function canRetryDurableMessage(
  retryAttempt: number,
  enqueuedAtMs: number,
  retryDelayMs: number,
  nowMs = Date.now(),
) {
  return (
    retryAttempt < MAX_DURABLE_RETRY_ATTEMPTS
    && nowMs - enqueuedAtMs + retryDelayMs < MAX_DURABLE_MESSAGE_AGE_MS
  );
}

interface SendResult {
  ok: boolean;
  error?: string;
  drop?: boolean;
}

function isTerminalSendError(errorText?: string) {
  const text = (errorText || '').toLowerCase();
  return text.includes('failed to read image file');
}

export function getSendRetryDelayMs(retryAttempt: number) {
  return Math.min(2 ** Math.max(0, retryAttempt), 30) * 1000;
}

function getErrorMessage(error: unknown) {
  if (error instanceof Error) {
    return error.message || String(error);
  }
  if (typeof error === 'string') {
    return error;
  }
  try {
    return JSON.stringify(error);
  } catch {
    return String(error);
  }
}

function normalizeBase64Chunk(input: string) {
  const idx = input.indexOf(',');
  const raw = idx >= 0 ? input.slice(idx + 1) : input;
  return raw.replace(/\s+/g, '').replace(/-/g, '+').replace(/_/g, '/');
}

function padBase64(input: string) {
  const mod = input.length % 4;
  if (mod === 0) {
    return input;
  }
  if (mod === 2) {
    return `${input}==`;
  }
  if (mod === 3) {
    return `${input}=`;
  }
  return input;
}

function isValidBase64(input: string) {
  return /^[A-Za-z0-9+/]*={0,2}$/.test(input);
}

function decodeChunkBase64(chunk: string, index: number) {
  const normalized = padBase64(normalizeBase64Chunk(chunk));
  if (!isValidBase64(normalized)) {
    throw new Error(`invalid base64 chars at chunk index ${index}`);
  }
  return Buffer.from(normalized, 'base64');
}

function mergeAudioChunksAsBase64(chunks: string[]) {
  const buffers = chunks.map((chunk, index) => decodeChunkBase64(chunk, index));
  return Buffer.concat(buffers).toString('base64');
}

export class MessageProcessor {
  private readonly networkClient: NetworkClient;
  private readonly binder: AgentBinder;
  private readonly feedServerAudioChunk: (packet: Live2DAudioPacket) => void;
  private readonly stopServerAudio: (command: Live2DAudioStopCommand) => void;
  private sendQueue: SendItem[] = [];
  private sendLoopRunning = false;
  private stopRequested = false;
  private localSound: Audio.Sound | null = null;
  private localPlayingUuid: string | null = null;
  private localPlaybackRequestId = 0;
  private serverAudioPlaying = false;
  private pendingServerAudioChunks = 0;
  private readonly audioChunksByUuid = new Map<string, string[]>();
  private readonly audioPathByUuid = new Map<string, string>();
  private readonly transientMessageUuids = new Set<string>();
  private lastTypingSentAt = 0;
  private readonly serverAudioFinishWaiters: (() => void)[] = [];
  private incomingMessageChain: Promise<void> = Promise.resolve();
  // 消息级幂等：uuid -> 已处理过的分片包签名集合（text+audio+expression+final），用于跳过服务端 at-least-once 重发的重复分片
  private readonly seenPacketsByUuid = new Map<string, Set<string>>();
  private static readonly MAX_TRACKED_MESSAGES = 50;

  constructor(
    networkClient: NetworkClient,
    binder: AgentBinder,
    feedServerAudioChunk: (packet: Live2DAudioPacket) => void,
    stopServerAudio?: (command: Live2DAudioStopCommand) => void,
  ) {
    this.networkClient = networkClient;
    this.binder = binder;
    this.feedServerAudioChunk = feedServerAudioChunk;
    this.stopServerAudio = stopServerAudio || (() => {});
  }

  stop() {
    this.stopRequested = true;
    this.sendQueue = [];
    this.stopServerAudio({
      stream_type: AudioStreamType.CHAT,
      reason: 'chat_processor_stopped',
    });
    void this.stopLocalTts();
  }

  queueLength() {
    return this.sendQueue.length;
  }

  setLocalAudioPath(convUuid: string, localUri: string) {
    this.audioPathByUuid.set(convUuid, localUri);
  }

  async sendText(uuid: string, text: string) {
    this.sendQueue.push({
      kind: 'text', uuid, text, clientMsgId: this.nextClientMsgId(), retryAttempt: 0, enqueuedAtMs: Date.now(),
    });
    addDebugTrace('send', 'enqueue text', { uuid, queueLength: this.sendQueue.length, textLength: text.length });
    this.binder.emitMessageStatus(uuid, 'waiting');
    this.startSendLoop();
  }

  async sendProactiveText(uuid: string, text: string) {
    this.sendQueue.push({
      kind: 'proactive', uuid, text, clientMsgId: this.nextClientMsgId(), retryAttempt: 0, enqueuedAtMs: Date.now(),
    });
    addDebugTrace('send', 'enqueue proactive text', { uuid, queueLength: this.sendQueue.length, textLength: text.length });
    this.startSendLoop();
  }

  async sendImage(uuid: string, imageUri: string, mimeType: string) {
    this.sendQueue.push({
      kind: 'image', uuid, imageUri, mimeType, clientMsgId: this.nextClientMsgId(), retryAttempt: 0, enqueuedAtMs: Date.now(),
    });
    addDebugTrace('send', 'enqueue image', { uuid, queueLength: this.sendQueue.length, mimeType });
    this.binder.emitMessageStatus(uuid, 'waiting');
    this.startSendLoop();
  }

  async sendTouch(touchArea: string | string[], clickFrequency?: Record<string, number>, touchMeta?: Record<string, unknown>) {
    if (this.hasServerAudioPriority()) {
      addDebugTrace('send', 'touch suppressed by server audio', { touchArea });
      return;
    }
    addDebugTrace('send', 'enqueue touch', { touchArea, queueLength: this.sendQueue.length });
    this.sendQueue.push({
      kind: 'touch', touchArea, clickFrequency, touchMeta, clientMsgId: this.nextClientMsgId(), retryAttempt: 0,
      enqueuedAtMs: Date.now(),
    });
    this.startSendLoop();
  }

  async sendTypingEvent(textLength: number) {
    const now = Date.now();
    // 0 长度事件表示用户清空了输入，必须立即发送、不受节流限制（对齐桌面端实现）
    if (now - this.lastTypingSentAt < 400 && textLength > 0) {
      return;
    }
    if (this.sendQueue.length > 0) {
      return;
    }
    this.lastTypingSentAt = now;
    this.sendQueue.push({
      kind: 'typing', textLength, clientMsgId: this.nextClientMsgId(), retryAttempt: 0, enqueuedAtMs: Date.now(),
    });
    addDebugTrace('send', 'enqueue typing', { queueLength: this.sendQueue.length, textLength });
    this.startSendLoop();
  }

  async sendImageSelecting() {
    addDebugTrace('send', 'enqueue image_selecting');
    this.sendQueue.push({
      kind: 'image_selecting', clientMsgId: this.nextClientMsgId(), retryAttempt: 0, enqueuedAtMs: Date.now(),
    });
    this.startSendLoop();
  }

  async sendImageSelectingCancel() {
    addDebugTrace('send', 'enqueue image_selecting_cancel');
    this.sendQueue.push({
      kind: 'image_selecting_cancel', clientMsgId: this.nextClientMsgId(), retryAttempt: 0, enqueuedAtMs: Date.now(),
    });
    this.startSendLoop();
  }

  async playLocalTtsByUuid(convUuid: string) {
    if (this.hasServerAudioPriority()) {
      addDebugTrace('audio', 'play blocked by server audio playing', { convUuid });
      return false;
    }

    const requestId = ++this.localPlaybackRequestId;

    const localUri = this.audioPathByUuid.get(convUuid);
    if (!localUri) {
      addDebugTrace('audio', 'play blocked: no local path found', { convUuid });
      return false;
    }

    try {
      const info = await FileSystem.getInfoAsync(localUri);
      if (!info.exists) {
        addDebugTrace('audio', 'play blocked: local file missing', { convUuid, localUri });
        return false;
      }
    } catch (error) {
      addDebugTrace('audio', 'play blocked: file stat failed', {
        convUuid,
        localUri,
        error: getErrorMessage(error),
      });
      return false;
    }

    if (!this.canStartLocalPlayback(requestId)) {
      addDebugTrace('audio', 'play cancelled by server audio while checking local file', { convUuid });
      return false;
    }

    if (this.localPlayingUuid === convUuid) {
      addDebugTrace('audio', 'play toggled off same uuid', { convUuid });
      await this.stopLocalTtsNow();
      return false;
    }

    await this.stopLocalTtsNow();
    if (!this.canStartLocalPlayback(requestId)) {
      return false;
    }

    let sound: Audio.Sound | null = null;
    try {
      sound = new Audio.Sound();
      const playbackSound = sound;
      // 先静默加载，再次确认没有服务端音频占用播放权，最后才开始回放。
      // 这样服务端音频在文件加载期间到达时，本地音频不会短暂抢播。
      await playbackSound.loadAsync({ uri: localUri }, { shouldPlay: false });
      if (!this.canStartLocalPlayback(requestId)) {
        await playbackSound.unloadAsync();
        return false;
      }
      playbackSound.setOnPlaybackStatusUpdate((status) => {
        if (!status.isLoaded) {
          return;
        }
        if (status.didJustFinish && this.localSound === playbackSound) {
          const finishedUuid = this.localPlayingUuid;
          this.localPlayingUuid = null;
          void playbackSound.unloadAsync();
          this.localSound = null;
          if (finishedUuid) {
            this.binder.emitLocalTtsState('finished', finishedUuid);
          }
        }
      });
      this.localSound = playbackSound;
      this.localPlayingUuid = convUuid;
      await playbackSound.playAsync();
      if (!this.canStartLocalPlayback(requestId) || this.localSound !== playbackSound) {
        if (this.localSound === playbackSound) {
          await this.stopLocalTtsNow();
        }
        return false;
      }
      addDebugTrace('audio', 'playLocalTtsByUuid success', { convUuid, localUri });
      return true;
    } catch (error) {
      if (!this.canStartLocalPlayback(requestId)) {
        if (sound && this.localSound === sound) {
          this.localSound = null;
          this.localPlayingUuid = null;
        }
        if (sound) {
          try {
            await sound.unloadAsync();
          } catch {
            // 服务端抢占期间的清理失败不应覆盖在线音频处理。
          }
        }
        return false;
      }
      let fileSize: number | null = null;
      let wavHeader: string | null = null;
      try {
        const info = await FileSystem.getInfoAsync(localUri);
        const sizeValue = (info as { size?: number }).size;
        fileSize = typeof sizeValue === 'number' ? sizeValue : null;
      } catch {
        // ignore file stat errors for diagnostics
      }

      try {
        const base64 = await FileSystem.readAsStringAsync(localUri, {
          encoding: FileSystem.EncodingType.Base64,
        });
        const probeBytes = Buffer.from(base64.slice(0, 64), 'base64');
        const riff = probeBytes.toString('ascii', 0, 4);
        const wave = probeBytes.toString('ascii', 8, 12);
        wavHeader = `${riff}/${wave}`;
      } catch {
        wavHeader = 'probe_failed';
      }

      const errorMessage = getErrorMessage(error);
      addDebugTrace('audio', 'playLocalTtsByUuid failed on load/play', {
        convUuid,
        localUri,
        fileSize,
        wavHeader,
        error: errorMessage,
      });
      this.binder.emitErrorText(
        `音频播放失败: ${errorMessage}${fileSize !== null ? ` (size=${fileSize}, header=${wavHeader || 'unknown'})` : ''}`,
      );
      this.localSound = null;
      this.localPlayingUuid = null;
      return false;
    }
  }

  async stopLocalTts() {
    this.localPlaybackRequestId += 1;
    await this.stopLocalTtsNow();
  }

  private async stopLocalTtsNow() {
    const sound = this.localSound;
    const stoppedUuid = this.localPlayingUuid;
    this.localSound = null;
    this.localPlayingUuid = null;

    if (sound) {
      try {
        await sound.stopAsync();
      } catch (error) {
        addDebugTrace('audio', 'stop local tts failed', { error: getErrorMessage(error) });
      }
      try {
        await sound.unloadAsync();
      } catch (error) {
        addDebugTrace('audio', 'unload local tts failed', { error: getErrorMessage(error) });
      }
    }

    if (stoppedUuid) {
      this.binder.emitLocalTtsState('stopped', stoppedUuid);
    }
  }

  private hasServerAudioPriority() {
    return this.serverAudioPlaying || this.pendingServerAudioChunks > 0;
  }

  isServerAudioActive() {
    return this.hasServerAudioPriority();
  }

  private canStartLocalPlayback(requestId: number) {
    return requestId === this.localPlaybackRequestId
      && !this.hasServerAudioPriority()
      && !this.stopRequested;
  }

  onAgentStateChanged(state: string) {
    this.binder.emitAgentThinking(state === 'thinking');
  }

  onAgentMessage(payload: AgentMessagePayload) {
    if (payload.stream_type !== AudioStreamType.CHAT) {
      addDebugTrace('agent', 'non-chat packet rejected by chat processor', {
        streamType: payload.stream_type,
      });
      return;
    }
    // 消息级幂等：服务端 at-least-once 重发的重复分片在入口直接跳过，
    // 展示与音频两条路径都不再处理（若只在展示路径去重，重复音频仍会被串行链消费）。
    if (this.isDuplicatePacket(payload.uuid || `agent-${Date.now()}`, payload)) {
      return;
    }
    let serverAudioPreemption = Promise.resolve();
    if (payload.audio) {
      // 在异步消息链开始处理前先占用在线音频优先权，关闭点击回放及其加载竞态。
      this.pendingServerAudioChunks += 1;
      this.localPlaybackRequestId += 1;
      // 调用时会同步摘除当前回放状态，异步部分负责真正 stop/unload。
      serverAudioPreemption = this.stopLocalTtsNow();
    }
    // 音频聚合与尾包落盘不进入展示/播放串行链，后续句子即使尚未展示也能立即保存。
    const audioPersistence = this.persistAgentAudioOnArrival(payload);
    // 展示和音频作为同一个串行单元处理：第一句话在空闲链上立即显示并开始播放；
    // 后续句话则等待上一句话播放完成后，才显示文字/表情并开始播放自己的音频。
    this.incomingMessageChain = this.incomingMessageChain
      .then(async () => {
        this.handleAgentMessageDisplay(payload);
        await this.handleAgentMessageAudio(payload, serverAudioPreemption, audioPersistence);
      })
      .catch((error) => {
        addDebugTrace('agent', 'handleAgentMessage failed', {
          error: getErrorMessage(error),
        });
      });
  }

  private isDuplicatePacket(convUuid: string, payload: AgentMessagePayload): boolean {
    // 签名覆盖 text/audio/expression/is_final_package：同一 uuid 的合法分片内容互不相同，
    // 只有服务端 at-least-once 重发的完全相同的分片才会命中同一签名。
    const signature = [
      payload.text || '',
      payload.audio || '',
      payload.expression || '',
      payload.is_final_package ? 'F' : '',
    ].join('|');

    let seen = this.seenPacketsByUuid.get(convUuid);
    if (!seen) {
      seen = new Set();
      this.seenPacketsByUuid.set(convUuid, seen);
      // 防止 uuid 集合无限增长：超出上限时按插入顺序淘汰最旧的 uuid
      if (this.seenPacketsByUuid.size > MessageProcessor.MAX_TRACKED_MESSAGES) {
        const oldestKey = this.seenPacketsByUuid.keys().next().value;
        if (oldestKey !== undefined) {
          this.seenPacketsByUuid.delete(oldestKey);
        }
      }
    }
    if (seen.has(signature)) {
      addDebugTrace('agent', 'duplicate agent_message packet skipped', { uuid: convUuid });
      return true;
    }
    seen.add(signature);
    return false;
  }

  private handleAgentMessageDisplay(payload: AgentMessagePayload) {
    const convUuid = payload.uuid || `agent-${Date.now()}`;
    const displayInChat = payload.display_in_chat !== false;

    if (!displayInChat) {
      this.transientMessageUuids.add(convUuid);
    }

    if (displayInChat && payload.text && payload.text.trim().length > 0) {
      this.binder.emitAgentMessage({
        stream_type: AudioStreamType.CHAT,
        uuid: convUuid,
        text: payload.text,
        expression: payload.expression || undefined,
        is_final_package: payload.is_final_package,
        audio_error: payload.audio_error,
        error_code: payload.error_code,
        display_in_chat: payload.display_in_chat,
        is_ephemeral: payload.is_ephemeral,
      });
    } else {
      this.binder.emitAgentMessage({
        stream_type: AudioStreamType.CHAT,
        uuid: convUuid,
        expression: payload.expression || undefined,
        is_final_package: payload.is_final_package,
        audio_error: payload.audio_error,
        error_code: payload.error_code,
        display_in_chat: payload.display_in_chat,
        is_ephemeral: payload.is_ephemeral,
      });
    }
  }

  private async handleAgentMessageAudio(
    payload: AgentMessagePayload,
    serverAudioPreemption: Promise<void>,
    audioPersistence: Promise<string | null>,
  ) {
    const convUuid = payload.uuid || `agent-${Date.now()}`;
    const audioChunk = payload.audio || '';

    if (audioChunk) {
      this.serverAudioPlaying = true;
      this.pendingServerAudioChunks = Math.max(0, this.pendingServerAudioChunks - 1);
      // onAgentMessage 已经立即发起停止；这里等待同一次停止完成，之后才能投喂在线音频。
      await serverAudioPreemption;
    }

    if (audioChunk && (this.localPlayingUuid || this.localSound)) {
      // 必须等消息回放真正停止后，才把在线音频交给 WebView 播放器。
      await this.stopLocalTtsNow();
    }

    if (audioChunk) {
      this.feedServerAudioChunk({
        stream_type: AudioStreamType.CHAT,
        audio_id: convUuid,
        audio: audioChunk,
        is_final: false,
      });
    }

    if (payload.is_final_package) {
      this.feedServerAudioChunk({
        stream_type: AudioStreamType.CHAT,
        audio_id: convUuid,
        audio: '',
        is_final: true,
      });
      const isTransient = this.transientMessageUuids.has(convUuid);
      if (payload.audio_error) {
        addDebugTrace('audio', 'server audio stream ended with error', {
          convUuid,
          errorCode: payload.error_code || 'UNKNOWN',
        });
      } else {
        const savedUri = await audioPersistence;
        if (savedUri && !isTransient) {
          // 此时该句已经轮到展示，避免提前发送 audio 更新而创建空白气泡。
          this.binder.emitAgentMessage({
            stream_type: AudioStreamType.CHAT,
            uuid: convUuid,
            audio: savedUri,
          });
        }
      }
      // 落盘可能早于该句展示，临时消息状态由展示阶段在尾包处统一清理。
      this.transientMessageUuids.delete(convUuid);
      if (AppState.currentState === 'active') {
        await this.waitForServerAudioFinished();
      } else {
        this.onServerAudioFinished();
      }
    }
  }

  private persistAgentAudioOnArrival(payload: AgentMessagePayload): Promise<string | null> {
    const convUuid = payload.uuid || `agent-${Date.now()}`;
    const audioChunk = payload.audio || '';

    if (payload.is_ephemeral) {
      // 触摸快速反射没有聊天气泡和历史回放入口，只播放，不持久化。
      this.audioChunksByUuid.delete(convUuid);
      return Promise.resolve(null);
    }

    if (audioChunk) {
      const list = this.audioChunksByUuid.get(convUuid) || [];
      list.push(audioChunk);
      this.audioChunksByUuid.set(convUuid, list);
    }

    if (!payload.is_final_package) {
      return Promise.resolve(null);
    }
    const completedChunks = this.audioChunksByUuid.get(convUuid) || [];
    this.audioChunksByUuid.delete(convUuid);
    if (payload.audio_error) {
      return Promise.resolve(null);
    }
    return this.saveAudioToLocal(convUuid, completedChunks);
  }

  onServerAudioFinished() {
    this.serverAudioPlaying = false;
    const waiters = this.serverAudioFinishWaiters.splice(0);
    for (const resolve of waiters) {
      resolve();
    }
  }

  private waitForServerAudioFinished(timeoutMs = 90000) {
    if (!this.serverAudioPlaying) {
      return Promise.resolve();
    }

    return new Promise<void>((resolve) => {
      const onFinished = () => {
        clearTimeout(timeoutId);
        const idx = this.serverAudioFinishWaiters.indexOf(onFinished);
        if (idx >= 0) {
          this.serverAudioFinishWaiters.splice(idx, 1);
        }
        resolve();
      };

      const timeoutId = setTimeout(() => {
        addDebugTrace('audio', 'waitForServerAudioFinished timeout', {
          timeoutMs,
        });
        this.onServerAudioFinished();
      }, timeoutMs);

      this.serverAudioFinishWaiters.push(onFinished);
    });
  }

  private startSendLoop() {
    if (this.sendLoopRunning) {
      return;
    }
    this.sendLoopRunning = true;
    this.stopRequested = false;
    addDebugTrace('send', 'start send loop', { queueLength: this.sendQueue.length });
    void this.runSendLoop();
  }

  private nextClientMsgId() {
    return `c-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  }

  private async runSendLoop() {
    while (!this.stopRequested) {
      if (this.sendQueue.length === 0) {
        this.sendLoopRunning = false;
        return;
      }

      const item = this.sendQueue[0];
      const durable = isDurableSendKind(item.kind);
      if (durable && Date.now() - item.enqueuedAtMs >= MAX_DURABLE_MESSAGE_AGE_MS) {
        this.failDeliveryUncertain(item, 'message exceeded the automatic delivery window');
        this.sendQueue.shift();
        continue;
      }

      const result = await this.sendOne(item);
      const tracksMessageStatus = durable && 'uuid' in item;

      if (result.ok) {
        addDebugTrace('send', 'send success', { kind: item.kind, queueLength: this.sendQueue.length });
        if (tracksMessageStatus) {
          this.binder.emitMessageStatus(item.uuid, 'submitted');
        }
        this.sendQueue.shift();
        continue;
      }

      if (!durable) {
        addDebugTrace('send', 'transient event dropped after send failure', {
          kind: item.kind,
          error: result.error,
        });
        this.sendQueue.shift();
        continue;
      }

      if (result.drop || isTerminalSendError(result.error)) {
        addDebugTrace('send', 'send failed terminal', {
          kind: item.kind,
          error: result.error,
          drop: result.drop,
        });
        if (tracksMessageStatus) {
          this.binder.emitMessageStatus(item.uuid, 'failed');
        }
        this.sendQueue.shift();
        continue;
      }

      const retryDelayMs = getSendRetryDelayMs(item.retryAttempt);
      if (!canRetryDurableMessage(item.retryAttempt, item.enqueuedAtMs, retryDelayMs)) {
        this.failDeliveryUncertain(item, result.error || 'delivery acknowledgement was not received');
        this.sendQueue.shift();
        continue;
      }
      item.retryAttempt += 1;
      addDebugTrace('send', 'send failed retry', {
        kind: item.kind,
        error: result.error,
        retryAttempt: item.retryAttempt,
        retryDelayMs,
      });
      if (tracksMessageStatus) {
        this.binder.emitMessageStatus(item.uuid, 'waiting');
      }
      await new Promise((resolve) => setTimeout(resolve, retryDelayMs));
    }

    this.sendLoopRunning = false;
  }

  private failDeliveryUncertain(item: SendItem, reason: string) {
    addDebugTrace('send', 'durable message delivery is uncertain', {
      kind: item.kind,
      clientMsgId: item.clientMsgId,
      retryAttempt: item.retryAttempt,
      ageMs: Date.now() - item.enqueuedAtMs,
      code: 'DELIVERY_UNCERTAIN',
      reason,
    });
    if ('uuid' in item) {
      this.binder.emitMessageStatus(item.uuid, 'failed');
    }
    this.binder.emitErrorText('[DELIVERY_UNCERTAIN] 消息发送结果无法确认，请检查会话后再重试。');
  }

  private async sendOne(item: SendItem): Promise<SendResult> {
    if (item.kind === 'text') {
      return this.networkClient.sendChat(item.text, false, item.clientMsgId);
    }
    if (item.kind === 'proactive') {
      return this.networkClient.sendChat(item.text, true, item.clientMsgId);
    }
    if (item.kind === 'image') {
      return this.networkClient.sendImage(item.imageUri, item.mimeType, item.clientMsgId);
    }
    if (item.kind === 'touch') {
      return this.networkClient.sendTouch(item.touchArea, item.clickFrequency, item.touchMeta, item.clientMsgId);
    }
    if (item.kind === 'image_selecting') {
      return this.networkClient.sendImageSelecting(item.clientMsgId);
    }
    if (item.kind === 'image_selecting_cancel') {
      return this.networkClient.sendImageSelectingCancel(item.clientMsgId);
    }
    return this.networkClient.sendTypingEvent(item.textLength, item.clientMsgId);
  }

  private async saveAudioToLocal(convUuid: string, chunks: string[]): Promise<string | null> {
    if (chunks.length === 0) {
      return null;
    }

    const baseDir = `${FileSystem.documentDirectory}tts_output`;
    const fileUri = `${baseDir}/${convUuid}.wav`;
    const mergedBase64 = mergeAudioChunksAsBase64(chunks);

    try {
      await FileSystem.makeDirectoryAsync(baseDir, { intermediates: true });
      await FileSystem.writeAsStringAsync(fileUri, mergedBase64, {
        encoding: FileSystem.EncodingType.Base64,
      });
      this.audioPathByUuid.set(convUuid, fileUri);
      return fileUri;
    } catch (error) {
      const errorMessage = getErrorMessage(error);
      addDebugTrace('audio', 'save local audio failed', {
        convUuid,
        baseDir,
        fileUri,
        chunkCount: chunks.length,
        mergedBase64Length: mergedBase64.length,
        error: errorMessage,
      });
      this.binder.emitErrorText(`本地音频保存失败: ${errorMessage}`);
      return null;
    }
  }
}

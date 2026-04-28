import { Buffer } from 'buffer';
import { Audio } from 'expo-av';
import * as FileSystem from 'expo-file-system/legacy';
import { AgentMessagePayload } from '../types/chat';
import { AgentBinder } from './binder';
import { addDebugTrace } from './debug_trace';
import { NetworkClient } from './network_client';

type SendItem =
  | { kind: 'text'; uuid: string; text: string }
  | { kind: 'image'; uuid: string; imageUri: string; mimeType: string }
  | { kind: 'typing'; textLength: number };

interface SendResult {
  ok: boolean;
  error?: string;
  drop?: boolean;
}

function isTerminalSendError(errorText?: string) {
  const text = (errorText || '').toLowerCase();
  return text.includes('not logged in') || text.includes('failed to read image file');
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
  private readonly feedServerAudioChunk: (base64Audio: string, isFinal: boolean) => void;
  private sendQueue: SendItem[] = [];
  private sendLoopRunning = false;
  private stopRequested = false;
  private localSound: Audio.Sound | null = null;
  private localPlayingUuid: string | null = null;
  private serverAudioPlaying = false;
  private readonly audioChunksByUuid = new Map<string, string[]>();
  private readonly audioPathByUuid = new Map<string, string>();
  private lastTypingSentAt = 0;
  private readonly serverAudioFinishWaiters: (() => void)[] = [];
  private incomingMessageChain: Promise<void> = Promise.resolve();

  constructor(
    networkClient: NetworkClient,
    binder: AgentBinder,
    feedServerAudioChunk: (base64Audio: string, isFinal: boolean) => void,
  ) {
    this.networkClient = networkClient;
    this.binder = binder;
    this.feedServerAudioChunk = feedServerAudioChunk;
  }

  stop() {
    this.stopRequested = true;
    this.sendQueue = [];
    void this.stopLocalTts();
  }

  queueLength() {
    return this.sendQueue.length;
  }

  setLocalAudioPath(convUuid: string, localUri: string) {
    this.audioPathByUuid.set(convUuid, localUri);
  }

  async sendText(uuid: string, text: string) {
    this.sendQueue.push({ kind: 'text', uuid, text });
    addDebugTrace('send', 'enqueue text', { uuid, queueLength: this.sendQueue.length, textLength: text.length });
    this.binder.emitMessageStatus(uuid, 'waiting');
    this.startSendLoop();
  }

  async sendImage(uuid: string, imageUri: string, mimeType: string) {
    this.sendQueue.push({ kind: 'image', uuid, imageUri, mimeType });
    addDebugTrace('send', 'enqueue image', { uuid, queueLength: this.sendQueue.length, mimeType });
    this.binder.emitMessageStatus(uuid, 'waiting');
    this.startSendLoop();
  }

  async sendTypingEvent(textLength: number) {
    const now = Date.now();
    if (now - this.lastTypingSentAt < 400) {
      return;
    }
    if (this.sendQueue.length > 0) {
      return;
    }
    this.lastTypingSentAt = now;
    this.sendQueue.push({ kind: 'typing', textLength });
    addDebugTrace('send', 'enqueue typing', { queueLength: this.sendQueue.length, textLength });
    this.startSendLoop();
  }

  async playLocalTtsByUuid(convUuid: string) {

    if (this.serverAudioPlaying) {
      addDebugTrace('audio', 'play blocked by server audio playing', { convUuid });
      return false;
    }

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

    if (this.localPlayingUuid === convUuid) {
      addDebugTrace('audio', 'play toggled off same uuid', { convUuid });
      await this.stopLocalTts();
      return false;
    }

    await this.stopLocalTts();

    try {
      const sound = new Audio.Sound();
      await sound.loadAsync({ uri: localUri }, { shouldPlay: true });
      sound.setOnPlaybackStatusUpdate((status) => {
        if (!status.isLoaded) {
          return;
        }
        if (status.didJustFinish) {
          const finishedUuid = this.localPlayingUuid;
          this.localPlayingUuid = null;
          void sound.unloadAsync();
          this.localSound = null;
          if (finishedUuid) {
            this.binder.emitLocalTtsState('finished', finishedUuid);
          }
        }
      });
      this.localSound = sound;
      this.localPlayingUuid = convUuid;
      addDebugTrace('audio', 'playLocalTtsByUuid success', { convUuid, localUri });
      return true;
    } catch (error) {
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
    if (!this.localSound) {
      if (this.localPlayingUuid) {
        const stoppedUuid = this.localPlayingUuid;
        this.localPlayingUuid = null;
        this.binder.emitLocalTtsState('stopped', stoppedUuid);
      }
      return;
    }

    const stoppedUuid = this.localPlayingUuid;
    try {
      await this.localSound.stopAsync();
      await this.localSound.unloadAsync();
    } finally {
      this.localSound = null;
      this.localPlayingUuid = null;
      if (stoppedUuid) {
        this.binder.emitLocalTtsState('stopped', stoppedUuid);
      }
    }
  }

  onAgentStateChanged(state: string) {
    this.binder.emitAgentThinking(state === 'thinking');
  }

  onAgentMessage(payload: AgentMessagePayload) {
    this.incomingMessageChain = this.incomingMessageChain
      .then(() => this.handleAgentMessage(payload))
      .catch((error) => {
        addDebugTrace('agent', 'handleAgentMessage failed', {
          error: getErrorMessage(error),
        });
      });
  }

  private async handleAgentMessage(payload: AgentMessagePayload) {
    const convUuid = payload.uuid || `agent-${Date.now()}`;

    if (this.localPlayingUuid) {
      void this.stopLocalTts();
    }

    if (payload.text && payload.text.trim().length > 0) {
      this.binder.emitAgentMessage({
        uuid: convUuid,
        text: payload.text,
        expression: payload.expression || undefined,
        is_final_package: payload.is_final_package,
      });
    } else {
      this.binder.emitAgentMessage({
        uuid: convUuid,
        expression: payload.expression || undefined,
        is_final_package: payload.is_final_package,
      });
    }

    const audioChunk = payload.audio || '';
    if (audioChunk) {
      const list = this.audioChunksByUuid.get(convUuid) || [];
      list.push(audioChunk);
      this.audioChunksByUuid.set(convUuid, list);
      this.serverAudioPlaying = true;
      this.feedServerAudioChunk(audioChunk, false);
    }

    if (payload.is_final_package) {
      this.feedServerAudioChunk('', true);
      await this.waitForServerAudioFinished();
      await this.saveAudioToLocal(convUuid);
    }
  }

  onServerAudioFinished() {
    this.serverAudioPlaying = false;
    const waiters = this.serverAudioFinishWaiters.splice(0);
    for (const resolve of waiters) {
      resolve();
    }
  }

  private waitForServerAudioFinished(timeoutMs = 30000) {
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
        onFinished();
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

  private async runSendLoop() {
    while (!this.stopRequested) {
      if (this.sendQueue.length === 0) {
        this.sendLoopRunning = false;
        return;
      }

      const item = this.sendQueue[0];
      const result = await this.sendOne(item);

      if (item.kind === 'typing') {
        addDebugTrace('send', 'typing sent', { ok: result.ok, error: result.error });
        this.sendQueue.shift();
        continue;
      }

      if (result.ok) {
        addDebugTrace('send', 'send success', { uuid: item.uuid, kind: item.kind, queueLength: this.sendQueue.length });
        this.binder.emitMessageStatus(item.uuid, 'submitted');
        this.sendQueue.shift();
        continue;
      }

      if (result.drop || isTerminalSendError(result.error)) {
        addDebugTrace('send', 'send failed terminal', {
          uuid: item.uuid,
          kind: item.kind,
          error: result.error,
          drop: result.drop,
        });
        this.binder.emitMessageStatus(item.uuid, 'failed');
        this.sendQueue.shift();
        continue;
      }

      addDebugTrace('send', 'send failed retry', {
        uuid: item.uuid,
        kind: item.kind,
        error: result.error,
      });
      this.binder.emitMessageStatus(item.uuid, 'waiting');
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }

    this.sendLoopRunning = false;
  }

  private async sendOne(item: SendItem): Promise<SendResult> {
    addDebugTrace('send', 'sendOne begin', {
      kind: item.kind,
      uuid: item.kind === 'typing' ? undefined : item.uuid,
      queueLength: this.sendQueue.length,
    });
    if (item.kind === 'text') {
      return this.networkClient.sendChat(item.text);
    }
    if (item.kind === 'image') {
      return this.networkClient.sendImage(item.imageUri, item.mimeType);
    }
    return this.networkClient.sendTypingEvent(item.textLength);
  }

  private async saveAudioToLocal(convUuid: string) {
    const chunks = this.audioChunksByUuid.get(convUuid);
    if (!chunks || chunks.length === 0) {
      return;
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
      this.binder.emitAgentMessage({
        uuid: convUuid,
        audio: fileUri,
      });
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
    } finally {
      this.audioChunksByUuid.delete(convUuid);
    }
  }
}

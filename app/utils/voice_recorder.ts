import { Audio } from 'expo-av';
import * as FileSystem from 'expo-file-system/legacy';
import { randomUuid } from './uuid';

export type VoicePermission = 'granted' | 'denied' | 'blocked';
export interface VoiceRecorderApi {
  getPermission(): Promise<VoicePermission>;
  requestPermission(): Promise<VoicePermission>;
  start(options: { onMetering: (db: number) => void; onInterrupted?: () => void }): Promise<{ recordingId: string; localUri: string }>;
  stop(): Promise<{ localUri: string; durationMs: number } | null>;
  cancel(): Promise<void>;
  dispose(): Promise<void>;
}

function normalizePermission(response: { granted: boolean; canAskAgain?: boolean }): VoicePermission {
  if (response.granted) return 'granted';
  return response.canAskAgain === false ? 'blocked' : 'denied';
}

export class VoiceRecorder implements VoiceRecorderApi {
  private recording: Audio.Recording | null = null;
  private uri: string | null = null;
  private recordingId: string | null = null;
  private stopping = false;
  private interrupted = false;
  private armed = false;
  private lastDurationMs = 0;

  async getPermission() {
    return normalizePermission(await Audio.getPermissionsAsync());
  }

  async requestPermission() {
    return normalizePermission(await Audio.requestPermissionsAsync());
  }

  async start({ onMetering, onInterrupted }: { onMetering: (db: number) => void; onInterrupted?: () => void }) {
    if (this.recording) throw new Error('voice recording already active');
    await Audio.setAudioModeAsync({ allowsRecordingIOS: true, playsInSilentModeIOS: true });
    const recording = new Audio.Recording();
    // recordingId 同时作为 user_voice 协议的 upload_id，必须满足服务端 UUID 值域校验。
    const recordingId = randomUuid();
    this.stopping = false;
    this.interrupted = false;
    this.armed = false;
    this.lastDurationMs = 0;
    let sawRecording = false;
    recording.setOnRecordingStatusUpdate((status: Audio.RecordingStatus) => {
      if (typeof status.durationMillis === 'number' && status.durationMillis > this.lastDurationMs) {
        this.lastDurationMs = status.durationMillis;
      }
      if (status.isRecording) {
        sawRecording = true;
        if (typeof status.metering === 'number') onMetering(status.metering);
      }
      // 系统中断（来电、输入设备被抢、iOS media services reset）：录音自行结束而我们没有主动 stop。
      // iOS 有 mediaServicesDidReset；Android 原生状态只有 canRecord/isRecording/durationMillis/metering，
      // 因此还要用「已经真的在录 → 现在不再录」这一转移来兜底。armed 保证 prepare 阶段的初始状态不算数。
      const stoppedByItself = sawRecording && status.isRecording === false;
      if (
        this.armed &&
        !this.stopping &&
        !this.interrupted &&
        (status.isDoneRecording || status.mediaServicesDidReset || stoppedByItself)
      ) {
        this.interrupted = true;
        onInterrupted?.();
      }
    });
    try {
      await recording.prepareToRecordAsync({
        android: { extension: '.m4a', outputFormat: Audio.AndroidOutputFormat.MPEG_4, audioEncoder: Audio.AndroidAudioEncoder.AAC, sampleRate: 44100, numberOfChannels: 1, bitRate: 128000 },
        ios: { extension: '.m4a', outputFormat: Audio.IOSOutputFormat.MPEG4AAC, audioQuality: Audio.IOSAudioQuality.HIGH, sampleRate: 44100, numberOfChannels: 1, bitRate: 128000 },
        web: { mimeType: 'audio/webm', bitsPerSecond: 128000 },
        isMeteringEnabled: true,
      });
      await recording.startAsync();
    } catch (error) {
      // prepare/start 失败时必须就地清理：expo-av 只在 stopAndUnload 时释放内部的 _recorderExists，
      // 句柄此刻还没存进 this.recording，否则之后所有录音都会抛
      // "Only one Recording object can be prepared at a given time."，只能重启 App。
      try {
        await recording.stopAndUnloadAsync();
      } catch {
        // 清理是尽力而为。
      }
      await this.remove(recording.getURI() || null);
      throw error;
    }
    this.recording = recording;
    this.recordingId = recordingId;
    this.uri = recording.getURI();
    this.armed = true;
    // AC-05：音量反馈按约 80 ms 周期采样（expo-av 默认 500 ms）。
    recording.setProgressUpdateInterval(80);
    return { recordingId, localUri: this.uri || '' };
  }

  async stop() {
    const recording = this.recording;
    if (!recording) return null;
    this.recording = null;
    this.stopping = true;
    const uri = recording.getURI() || this.uri;
    try {
      await recording.stopAndUnloadAsync();
      const status = await recording.getStatusAsync();
      this.uri = null;
      this.recordingId = null;
      if (!uri) return null;
      // stopAndUnloadAsync 之后部分平台 getStatusAsync 可能不再返回时长，回退到状态回调缓存值。
      const durationMs = Math.max(status.durationMillis || 0, this.lastDurationMs);
      return { localUri: uri, durationMs: Math.max(0, Math.round(durationMs)) };
    } catch (error) {
      await this.remove(uri);
      this.uri = null;
      this.recordingId = null;
      throw error;
    }
  }

  async cancel() {
    const recording = this.recording;
    const uri = recording?.getURI() || this.uri;
    this.recording = null;
    this.stopping = true;
    this.uri = null;
    this.recordingId = null;
    if (recording) {
      try { await recording.stopAndUnloadAsync(); } catch { /* idempotent cleanup */ }
    }
    await this.remove(uri);
  }

  async dispose() { await this.cancel(); }

  private async remove(uri: string | null | undefined) {
    if (!uri) return;
    try { await FileSystem.deleteAsync(uri, { idempotent: true }); } catch { /* cleanup is best effort */ }
  }
}

export const voiceRecorder = new VoiceRecorder();

import { Audio } from 'expo-av';
import { randomUUID } from 'expo-crypto';
import * as FileSystem from 'expo-file-system/legacy';

export type VoicePermission = 'granted' | 'denied' | 'blocked';
/**
 * 一次权限请求的结果。
 *
 * Expo SDK 54 在目标 Android 状态下无法可靠区分"系统框被取消"与"永久拒绝"；
 * 因此只表示是否获得授权，不推断用户意图或系统框是否出现。
 */
export type VoicePermissionRequest = 'granted' | 'not_granted';

export interface VoiceRecorderApi {
  getPermission(): Promise<VoicePermission>;
  requestPermission(): Promise<VoicePermissionRequest>;
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
  private generation = 0;
  private pendingStart: Promise<{ recordingId: string; localUri: string }> | null = null;
  private hasStarted = false;

  async getPermission() {
    return normalizePermission(await Audio.getPermissionsAsync());
  }

  /**
   * 请求麦克风权限。
   *
   * Expo 返回的非授权字段在不同 Android/OEM 状态下无法可靠区分"取消"与"永久拒绝"；
   * 因此仅报告 not_granted，交互层恢复输入栏并给出重试与手动设置指引。
   */
  async requestPermission(): Promise<VoicePermissionRequest> {
    const response = await Audio.requestPermissionsAsync();
    return response.granted ? 'granted' : 'not_granted';
  }

  async start(options: { onMetering: (db: number) => void; onInterrupted?: () => void }) {
    if (this.recording || this.pendingStart) throw new Error('voice recording already active');
    const generation = ++this.generation;
    const pending = this.startNative(options, generation);
    this.pendingStart = pending;
    try { return await pending; }
    finally { if (this.pendingStart === pending) this.pendingStart = null; }
  }

  private async startNative(
    { onMetering, onInterrupted }: { onMetering: (db: number) => void; onInterrupted?: () => void },
    generation: number,
  ) {
    const recording = new Audio.Recording();
    const recordingId = randomUUID();
    const check = () => { if (generation !== this.generation) throw new Error('voice recording cancelled'); };
    this.recording = recording;
    this.hasStarted = false;
    let interrupted = false;
    recording.setProgressUpdateInterval(80);
    recording.setOnRecordingStatusUpdate((status) => {
      if (this.recording !== recording || generation !== this.generation) return;
      if (status.isRecording) {
        this.hasStarted = true;
        if (typeof status.metering === 'number') onMetering(status.metering);
      } else if (this.hasStarted && !interrupted) {
        interrupted = true;
        onInterrupted?.();
      }
    });
    try {
      await Audio.setAudioModeAsync({ allowsRecordingIOS: true, playsInSilentModeIOS: true });
      check();
      await recording.prepareToRecordAsync({
        android: { extension: '.m4a', outputFormat: Audio.AndroidOutputFormat.MPEG_4, audioEncoder: Audio.AndroidAudioEncoder.AAC, sampleRate: 44100, numberOfChannels: 1, bitRate: 128000 },
        ios: { extension: '.m4a', outputFormat: Audio.IOSOutputFormat.MPEG4AAC, audioQuality: Audio.IOSAudioQuality.HIGH, sampleRate: 44100, numberOfChannels: 1, bitRate: 128000 },
        web: { mimeType: 'audio/webm', bitsPerSecond: 128000 },
        isMeteringEnabled: true,
      });
      check();
      await recording.startAsync();
      check();
      if (interrupted) throw new Error('voice recording interrupted');
      this.hasStarted = true;
      this.recordingId = recordingId;
      this.uri = recording.getURI();
      return { recordingId, localUri: this.uri || '' };
    } catch (error) {
      this.recording = null;
      try { await recording.stopAndUnloadAsync(); } catch { /* not yet prepared */ }
      await this.remove(recording.getURI());
      throw error;
    }
  }

  async stop() {
    const recording = this.recording;
    if (!recording) return null;
    this.recording = null;
    const uri = recording.getURI() || this.uri;
    try {
      await recording.stopAndUnloadAsync();
      const status = await recording.getStatusAsync();
      this.uri = null;
      this.recordingId = null;
      if (!uri) return null;
      return { localUri: uri, durationMs: Math.max(0, Math.round(status.durationMillis || 0)) };
    } catch (error) {
      await this.remove(uri);
      this.uri = null;
      this.recordingId = null;
      throw error;
    }
  }

  async cancel() {
    this.generation += 1;
    if (this.pendingStart) await this.pendingStart.catch(() => undefined);
    const recording = this.recording;
    const uri = recording?.getURI() || this.uri;
    this.recording = null;
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

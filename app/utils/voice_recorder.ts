import { Audio } from 'expo-av';
import { randomUUID } from 'expo-crypto';
import * as FileSystem from 'expo-file-system/legacy';

export type VoicePermission = 'granted' | 'denied' | 'blocked';
/**
 * 一次权限请求的结果。`cancelled` 与 `blocked` 必须分开：
 * 系统权限框被返回键取消、以及用户只是本次没允许，都不等于"永久拒绝"。
 */
export type VoicePermissionRequest = 'granted' | 'cancelled' | 'blocked';

/** 系统权限框需要用户操作，不可能在极短时间内返回；低于该时长视为系统根本没有弹框。 */
export const PERMISSION_DIALOG_MIN_MS = 300;

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

  constructor(private readonly now: () => number = Date.now) {}

  async getPermission() {
    return normalizePermission(await Audio.getPermissionsAsync());
  }

  /**
   * 请求麦克风权限，并区分"本次取消"与"确认无法再询问"。
   *
   * Android 上一次性授权被回收、以及系统框被返回键取消，都会得到
   * `granted=false / canAskAgain=false`，仅看字段无法区分，因此用返回时机判断：
   * 真正弹过框必须等用户操作，快速返回说明系统没有弹框（已被明确拒绝且不再询问）。
   */
  async requestPermission(): Promise<VoicePermissionRequest> {
    const startedAt = this.now();
    const response = await Audio.requestPermissionsAsync();
    if (response.granted) return 'granted';
    return this.now() - startedAt < PERMISSION_DIALOG_MIN_MS ? 'blocked' : 'cancelled';
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

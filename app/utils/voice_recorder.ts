import { Audio } from 'expo-av';
import * as FileSystem from 'expo-file-system/legacy';

export type VoicePermission = 'granted' | 'denied' | 'blocked';
export interface VoiceRecorderApi {
  getPermission(): Promise<VoicePermission>;
  requestPermission(): Promise<VoicePermission>;
  start(options: { onMetering: (db: number) => void }): Promise<{ recordingId: string; localUri: string }>;
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

  async getPermission() {
    return normalizePermission(await Audio.getPermissionsAsync());
  }

  async requestPermission() {
    return normalizePermission(await Audio.requestPermissionsAsync());
  }

  async start({ onMetering }: { onMetering: (db: number) => void }) {
    if (this.recording) throw new Error('voice recording already active');
    await Audio.setAudioModeAsync({ allowsRecordingIOS: true, playsInSilentModeIOS: true });
    const recording = new Audio.Recording();
    const recordingId = `recording-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    recording.setOnRecordingStatusUpdate((status) => {
      if (status.isRecording && typeof status.metering === 'number') onMetering(status.metering);
    });
    await recording.prepareToRecordAsync({
      android: { extension: '.m4a', outputFormat: Audio.AndroidOutputFormat.MPEG_4, audioEncoder: Audio.AndroidAudioEncoder.AAC, sampleRate: 44100, numberOfChannels: 1, bitRate: 128000 },
      ios: { extension: '.m4a', outputFormat: Audio.IOSOutputFormat.MPEG4AAC, audioQuality: Audio.IOSAudioQuality.HIGH, sampleRate: 44100, numberOfChannels: 1, bitRate: 128000 },
      web: { mimeType: 'audio/webm', bitsPerSecond: 128000 },
      isMeteringEnabled: true,
    });
    await recording.startAsync();
    this.recording = recording;
    this.recordingId = recordingId;
    this.uri = recording.getURI();
    return { recordingId, localUri: this.uri || '' };
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

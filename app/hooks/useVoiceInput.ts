import * as Haptics from 'expo-haptics';
import { AppState, GestureResponderEvent } from 'react-native';
import { useCallback, useEffect, useRef, useState } from 'react';
import { SendStatus, VoiceCaptureState } from '../types/chat';
import { MAX_VOICE_DURATION_MS, MIN_VOICE_DURATION_MS, voiceStateForMove } from '../utils/voice_gesture';
import { VoiceRecorderApi, voiceRecorder } from '../utils/voice_recorder';

interface Options { onRecordingStarted: (id: string) => void; onRecordingCancelled: (id: string, reason: string) => void; onRecordingCommitted: (value: { uploadId: string; localUri: string; durationMs: number }) => void; onStopAllAudio: () => Promise<void>; onRecordingEnded?: () => void; onNotice: (text: string) => void; recorder?: VoiceRecorderApi; }
export function useVoiceInput(options: Options) {
  const recorder = options.recorder || voiceRecorder;
  const onRecordingEnded = useRef(options.onRecordingEnded);
  onRecordingEnded.current = options.onRecordingEnded;
  const [mode, setMode] = useState<'text' | 'voice'>('text');
  const [captureState, setCaptureState] = useState<VoiceCaptureState>('TextMode');
  const [elapsedMs, setElapsedMs] = useState(0);
  const [smoothedMeter, setSmoothedMeter] = useState(0);
  const initialY = useRef(0); const id = useRef<string | null>(null); const startedAt = useRef(0); const cancelZone = useRef(false); const finishing = useRef(false);
  const pendingUploadId = useRef<string | null>(null);
  const uploadReturnState = useRef<VoiceCaptureState>('VoiceReady');
  const beginRetryUpload = useCallback((uploadId: string) => {
    if (pendingUploadId.current || finishing.current || (captureState !== 'TextMode' && captureState !== 'VoiceReady')) return false;
    uploadReturnState.current = captureState;
    pendingUploadId.current = uploadId;
    setCaptureState('Uploading');
    return true;
  }, [captureState]);
  const onUploadStatus = useCallback((uploadId: string, status: SendStatus) => {
    if (pendingUploadId.current !== uploadId || (status !== 'submitted' && status !== 'failed')) return;
    pendingUploadId.current = null;
    id.current = null;
    setElapsedMs(0);
    setSmoothedMeter(0);
    setCaptureState(uploadReturnState.current);
  }, []);
  const toggleMode = useCallback(() => { if (captureState === 'TextMode') { setMode('voice'); setCaptureState('VoiceReady'); } else if (captureState === 'VoiceReady') { setMode('text'); setCaptureState('TextMode'); } }, [captureState]);
  const cancel = useCallback(async (reason: string) => {
    if (finishing.current) return;
    finishing.current = true;
    const current = id.current;
    try {
      await recorder.cancel();
      if (current) options.onRecordingCancelled(current, reason);
    } finally {
      id.current = null;
      setElapsedMs(0);
      setSmoothedMeter(0);
      setCaptureState('VoiceReady');
      finishing.current = false;
      onRecordingEnded.current?.();
    }
  }, [options, recorder]);
  const pressIn = useCallback(async (event: GestureResponderEvent) => {
    if (captureState !== 'VoiceReady' || finishing.current) return;
    initialY.current = event.nativeEvent.pageY;
    const permission = await recorder.getPermission();
    if (permission !== 'granted') { setCaptureState('PermissionPrompt'); const result = permission === 'denied' ? await recorder.requestPermission() : permission; if (result === 'blocked') options.onNotice('麦克风权限已关闭，请前往设置开启'); setCaptureState('VoiceReady'); return; }
    try {
      await options.onStopAllAudio();
      const started = await recorder.start({ onMetering: (db) => setSmoothedMeter((prev) => prev * 0.7 + Math.max(0, Math.min(1, (db + 60) / 60)) * 0.3) });
      id.current = started.recordingId; startedAt.current = Date.now(); cancelZone.current = false; setElapsedMs(0); setCaptureState('Recording'); options.onRecordingStarted(started.recordingId);
    } catch {
      onRecordingEnded.current?.();
      setCaptureState('VoiceReady');
      options.onNotice('录音启动失败，请重试');
    }
  }, [captureState, options, recorder]);
  const pressMove = useCallback((event: GestureResponderEvent) => { const next = voiceStateForMove(captureState, initialY.current, event.nativeEvent.pageY); if (next === 'CancelZone' && !cancelZone.current) { cancelZone.current = true; void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium).catch(() => undefined); } if (next === 'Recording') cancelZone.current = false; setCaptureState(next); }, [captureState]);
  const pressOut = useCallback(async () => {
    if (captureState !== 'Recording' && captureState !== 'CancelZone') return;
    const elapsed = Math.min(MAX_VOICE_DURATION_MS, Date.now() - startedAt.current);
    if (captureState === 'CancelZone' || elapsed < MIN_VOICE_DURATION_MS) {
      await cancel(elapsed < MIN_VOICE_DURATION_MS ? 'too_short' : 'gesture_cancel');
      if (elapsed < MIN_VOICE_DURATION_MS) options.onNotice('说话时间太短');
      return;
    }
    if (finishing.current) return;
    finishing.current = true;
    const current = id.current;
    try {
      const result = await recorder.stop();
      if (current && result) {
        uploadReturnState.current = 'VoiceReady';
        pendingUploadId.current = current;
        setCaptureState('Uploading');
        options.onRecordingCommitted({ uploadId: current, localUri: result.localUri, durationMs: Math.min(MAX_VOICE_DURATION_MS, result.durationMs || elapsed) });
      } else {
        setCaptureState('VoiceReady');
        if (current) options.onRecordingCancelled(current, 'recording_failed');
      }
    } catch {
      pendingUploadId.current = null;
      setCaptureState('VoiceReady');
      if (current) options.onRecordingCancelled(current, 'recording_failed');
      options.onNotice('录音保存失败，请重试');
    } finally {
      finishing.current = false;
      onRecordingEnded.current?.();
    }
  }, [cancel, captureState, options, recorder]);
  useEffect(() => { if (captureState !== 'Recording' && captureState !== 'CancelZone') return; const timer = setInterval(() => { const elapsed = Math.min(MAX_VOICE_DURATION_MS, Date.now() - startedAt.current); setElapsedMs(elapsed); if (elapsed >= MAX_VOICE_DURATION_MS) void pressOut(); }, 100); return () => clearInterval(timer); }, [captureState, pressOut]);
  useEffect(() => { const sub = AppState.addEventListener('change', (state) => { if (state !== 'active' && (captureState === 'Recording' || captureState === 'CancelZone')) void cancel('background'); }); return () => sub.remove(); }, [cancel, captureState]);
  useEffect(() => () => { void recorder.dispose(); onRecordingEnded.current?.(); }, [recorder]);
  return { mode, captureState, elapsedMs, smoothedMeter, isCancelZone: captureState === 'CancelZone', toggleMode, beginRetryUpload, onUploadStatus, pressIn, pressMove, pressOut, cancelBySystem: cancel };
}

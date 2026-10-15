import * as Haptics from 'expo-haptics';
import { AppState, GestureResponderEvent } from 'react-native';
import { useCallback, useEffect, useRef, useState } from 'react';
import { SendStatus, VoiceCaptureState } from '../types/chat';
import { MAX_VOICE_DURATION_MS, MIN_VOICE_DURATION_MS, voiceStateForMove } from '../utils/voice_gesture';
import { VoiceRecorderApi, voiceRecorder } from '../utils/voice_recorder';
import { showMicrophoneSettings } from '../utils/voice_permission';

interface Options {
  onRecordingStarted: (id: string) => void;
  onRecordingCancelled: (id: string, reason: string) => void;
  onRecordingCommitted: (value: { uploadId: string; localUri: string; durationMs: number }) => void;
  onStopAllAudio: () => Promise<void>;
  onRecordingEnded?: () => void;
  onNotice: (text: string) => void;
  recorder?: VoiceRecorderApi;
  active?: boolean;
}

export function useVoiceInput(options: Options) {
  const recorder = options.recorder || voiceRecorder;
  const callbacks = useRef(options);
  callbacks.current = options;
  const mounted = useRef(true);
  const [mode, setMode] = useState<'text' | 'voice'>('text');
  const [captureState, setCaptureState] = useState<VoiceCaptureState>('TextMode');
  const state = useRef<VoiceCaptureState>('TextMode');
  const transition = useCallback((next: VoiceCaptureState) => {
    state.current = next;
    if (mounted.current) setCaptureState(next);
  }, []);
  const [elapsedMs, setElapsedMs] = useState(0);
  const [smoothedMeter, setSmoothedMeter] = useState(0);
  const initialY = useRef(0);
  const id = useRef<string | null>(null);
  const startedAt = useRef(0);
  const cancelZone = useRef(false);
  const finishing = useRef(false);
  const generation = useRef(0);
  const starting = useRef(false);
  const cancelling = useRef<Promise<void> | null>(null);
  const pendingUploadId = useRef<string | null>(null);
  const uploadReturnState = useRef<VoiceCaptureState>('VoiceReady');
  // 系统授权请求可能迟迟不返回（授权框未弹出或被系统吞掉）：只记录它在途，输入栏不等它。
  const permissionRequest = useRef<Promise<void> | null>(null);

  const resetCapture = useCallback(() => {
    if (mounted.current) { setElapsedMs(0); setSmoothedMeter(0); }
    transition('VoiceReady');
  }, [transition]);
  const beginRetryUpload = useCallback((uploadId: string) => {
    if (pendingUploadId.current || finishing.current || starting.current || cancelling.current ||
      (state.current !== 'TextMode' && state.current !== 'VoiceReady')) return false;
    uploadReturnState.current = state.current;
    pendingUploadId.current = uploadId;
    transition('Uploading');
    return true;
  }, [transition]);
  const onUploadStatus = useCallback((uploadId: string, status: SendStatus) => {
    if (pendingUploadId.current !== uploadId || (status !== 'submitted' && status !== 'failed')) return;
    pendingUploadId.current = null;
    id.current = null;
    if (mounted.current) { setElapsedMs(0); setSmoothedMeter(0); }
    transition(uploadReturnState.current);
  }, [transition]);
  const toggleMode = useCallback(() => {
    if (starting.current || cancelling.current) return;
    if (state.current === 'TextMode') { setMode('voice'); transition('VoiceReady'); }
    else if (state.current === 'VoiceReady') { setMode('text'); transition('TextMode'); }
  }, [transition]);

  const cancel = useCallback((reason: string): Promise<void> => {
    if (cancelling.current) return cancelling.current;
    if (finishing.current || (!starting.current && !id.current)) return Promise.resolve();
    generation.current += 1;
    const current = id.current;
    id.current = null;
    // Notify synchronously before the chat effect tears down its connection.
    if (current) callbacks.current.onRecordingCancelled(current, reason);
    const cleanup = Promise.resolve().then(() => recorder.cancel()).catch(() => {
      callbacks.current.onNotice('录音清理失败，请重试');
    }).finally(() => {
      cancelling.current = null;
      if (!starting.current) resetCapture();
      callbacks.current.onRecordingEnded?.();
    });
    cancelling.current = cleanup;
    return cleanup;
  }, [recorder, resetCapture]);

  const pressIn = useCallback(async (event: GestureResponderEvent) => {
    if (state.current !== 'VoiceReady' || starting.current || cancelling.current || finishing.current ||
      !mounted.current || callbacks.current.active === false) return;
    starting.current = true;
    const attempt = ++generation.current;
    const valid = () => attempt === generation.current && mounted.current && callbacks.current.active !== false;
    initialY.current = event.nativeEvent.pageY;
    transition('Starting');
    try {
      const permission = await recorder.getPermission();
      if (!valid()) return;
      if (permission !== 'granted') {
        transition('PermissionPrompt');
        if (permissionRequest.current) {
          showMicrophoneSettings(
            callbacks.current.onNotice,
            '权限请求仍在处理中。请稍候重试，或在系统设置中查看麦克风权限。',
          );
          return;
        }
        // 单次授权回收后，Expo 可能把状态报告成 blocked；一次状态检查不足以证明不能再次询问。
        // 必须先实际发起一次请求，再根据真实请求结果决定是否引导去系统设置。
        // 授权结果从不开始录音（授权框已打断手势，授权后需重新按住），所以不必等它返回才释放输入栏。
        // 迟到的结果只在“这次尝试仍是当前尝试”时才有意义：更晚的按住或已卸载都不该被它打扰。
        const request = recorder.requestPermission().then((result) => {
          if (result === 'blocked' && valid()) showMicrophoneSettings(callbacks.current.onNotice);
        }, () => {
          // 授权请求本身失败（原生拒绝/抛错）：与录音启动失败同样给出可行动提示，不能静默。
          if (valid()) callbacks.current.onNotice('录音启动失败，请重试');
        }).finally(() => {
          if (permissionRequest.current === request) permissionRequest.current = null;
        });
        permissionRequest.current = request;
        return;
      }
      await callbacks.current.onStopAllAudio();
      if (!valid()) return;
      const started = await recorder.start({
        onMetering: (db) => { if (valid()) setSmoothedMeter((prev) => prev * 0.7 + Math.max(0, Math.min(1, (db + 60) / 60)) * 0.3); },
        onInterrupted: () => { void cancel('system_interruption'); },
      });
      if (!valid()) { await recorder.cancel(); return; }
      id.current = started.recordingId;
      startedAt.current = Date.now();
      cancelZone.current = false;
      setElapsedMs(0);
      transition('Recording');
      callbacks.current.onRecordingStarted(started.recordingId);
    } catch {
      await recorder.cancel().catch(() => undefined);
      if (valid()) callbacks.current.onNotice('录音启动失败，请重试');
    } finally {
      starting.current = false;
      if (!id.current) {
        await cancelling.current;
        resetCapture();
        callbacks.current.onRecordingEnded?.();
      }
    }
  }, [cancel, recorder, resetCapture, transition]);

  const pressMove = useCallback((event: GestureResponderEvent) => {
    const next = voiceStateForMove(state.current, initialY.current, event.nativeEvent.pageY);
    if (next === 'CancelZone' && !cancelZone.current) {
      cancelZone.current = true;
      void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium).catch(() => undefined);
    }
    if (next === 'Recording') cancelZone.current = false;
    transition(next);
  }, [transition]);
  const pressOut = useCallback(async () => {
    if (cancelling.current) return;
    // Permission dialogs end the native gesture too; their result never starts recording.
    if (state.current === 'PermissionPrompt') return;
    if (starting.current) { await cancel('released_while_starting'); return; }
    if (state.current !== 'Recording' && state.current !== 'CancelZone') return;
    const elapsed = Math.min(MAX_VOICE_DURATION_MS, Date.now() - startedAt.current);
    if (state.current === 'CancelZone' || elapsed < MIN_VOICE_DURATION_MS) {
      await cancel(elapsed < MIN_VOICE_DURATION_MS ? 'too_short' : 'gesture_cancel');
      if (elapsed < MIN_VOICE_DURATION_MS) callbacks.current.onNotice('说话时间太短');
      return;
    }
    if (finishing.current) return;
    finishing.current = true;
    const current = id.current;
    id.current = null;
    transition('Uploading');
    try {
      const result = await recorder.stop();
      if (current && result) {
        uploadReturnState.current = 'VoiceReady';
        pendingUploadId.current = current;
        callbacks.current.onRecordingCommitted({ uploadId: current, localUri: result.localUri,
          durationMs: Math.min(MAX_VOICE_DURATION_MS, result.durationMs || elapsed) });
      } else {
        resetCapture();
        if (current) callbacks.current.onRecordingCancelled(current, 'recording_failed');
      }
    } catch {
      pendingUploadId.current = null;
      resetCapture();
      if (current) callbacks.current.onRecordingCancelled(current, 'recording_failed');
      callbacks.current.onNotice('录音保存失败，请重试');
    } finally {
      finishing.current = false;
      callbacks.current.onRecordingEnded?.();
    }
  }, [cancel, recorder, resetCapture, transition]);
  useEffect(() => {
    if (captureState !== 'Recording' && captureState !== 'CancelZone') return;
    const timer = setInterval(() => {
      const elapsed = Math.min(MAX_VOICE_DURATION_MS, Date.now() - startedAt.current);
      setElapsedMs(elapsed);
      if (elapsed >= MAX_VOICE_DURATION_MS) void pressOut();
    }, 100);
    return () => clearInterval(timer);
  }, [captureState, pressOut]);
  useEffect(() => {
    const sub = AppState.addEventListener('change', (next) => { if (next !== 'active') void cancel('background'); });
    return () => sub.remove();
  }, [cancel]);
  useEffect(() => { if (options.active === false) void cancel('navigation'); }, [options.active, cancel]);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; void cancel('unmount'); };
  }, [cancel]);
  return { mode, captureState, elapsedMs, smoothedMeter, isCancelZone: captureState === 'CancelZone', toggleMode,
    beginRetryUpload, onUploadStatus, pressIn, pressMove, pressOut, cancelBySystem: cancel };
}

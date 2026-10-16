import * as Haptics from 'expo-haptics';
import { AppState, GestureResponderEvent } from 'react-native';
import { useCallback, useEffect, useRef, useState } from 'react';
import { SendStatus, VoiceCaptureState } from '../types/chat';
import { MAX_VOICE_DURATION_MS, MIN_VOICE_DURATION_MS, voiceStateForMove } from '../utils/voice_gesture';
import { VoiceRecorderApi, voiceRecorder } from '../utils/voice_recorder';
import {
  MICROPHONE_AMBIGUOUS_MESSAGE,
  MICROPHONE_DENIED_NOTICE,
  MICROPHONE_PENDING_MESSAGE,
  MICROPHONE_RETRIES_BEFORE_SETTINGS,
  PERMISSION_STUCK_AFTER_MS,
  showMicrophoneSettings,
} from '../utils/voice_permission';

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
  // 在途请求的起始时间：用于判断“是否已经卡住很久”，不用于推断用户意图。
  const permissionStartedAt = useRef(0);
  // 连续未授权次数：一次状态检查 / 一次请求都无法区分取消、拒绝与永久拒绝，
  // 因此按“连续失败”升级到设置入口，而不是猜原因。
  const deniedAttempts = useRef(0);

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
    else if (state.current === 'VoiceReady') {
      // #309 承诺：切回文字输入后，旧的权限结果不应再来打扰当前交互。
      if (permissionRequest.current) generation.current += 1;
      setMode('text');
      transition('TextMode');
    }
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
          // 已有在途请求：不叠加第二个。只有它长时间没返回，才给设置出口；否则只提示“处理中”。
          const waited = Date.now() - permissionStartedAt.current;
          if (waited >= PERMISSION_STUCK_AFTER_MS) showMicrophoneSettings(callbacks.current.onNotice);
          else callbacks.current.onNotice(MICROPHONE_PENDING_MESSAGE);
          return;
        }
        // 单次授权回收后，Expo 可能把状态报告成 blocked；一次状态检查不足以证明不能再次询问，
        // 也无法区分取消 / 普通拒绝 / 永久拒绝。因此不按原因判断，而按“连续失败次数”升级：
        // 第一次未授权只给非模态提示，连续多次仍未授权才提供设置入口。
        // 授权结果从不开始录音（授权框已打断手势，授权后需重新按住），所以不必等它返回才释放输入栏。
        // 迟到的结果只在“这次尝试仍是当前尝试”时才有意义：更晚的按住或已卸载都不该被它打扰。
        permissionStartedAt.current = Date.now();
        const request = recorder.requestPermission().then((result) => {
          if (!valid()) return;
          if (result === 'granted') {
            deniedAttempts.current = 0;
            return;
          }
          if (result === 'blocked') {
            deniedAttempts.current += 1;
            if (deniedAttempts.current >= MICROPHONE_RETRIES_BEFORE_SETTINGS) {
              showMicrophoneSettings(callbacks.current.onNotice, MICROPHONE_DENIED_NOTICE);
            } else {
              callbacks.current.onNotice(MICROPHONE_AMBIGUOUS_MESSAGE);
            }
          }
        }, () => {
          // 授权请求本身失败（原生拒绝/抛错）：与录音启动失败同样给出可行动提示，不能静默。
          if (valid()) callbacks.current.onNotice('录音启动失败，请重试');
        }).finally(() => {
          if (permissionRequest.current === request) permissionRequest.current = null;
        });
        permissionRequest.current = request;
        return;
      }
      // 权限本已可用（例如用户刚在系统设置里授权）：连续失败计数清零。
      deniedAttempts.current = 0;
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

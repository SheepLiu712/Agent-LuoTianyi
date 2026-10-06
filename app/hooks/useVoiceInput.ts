import * as Haptics from 'expo-haptics';
import { Alert, AppState, GestureResponderEvent, Linking } from 'react-native';
import { useCallback, useEffect, useRef, useState } from 'react';
import { VoiceCaptureState } from '../types/chat';
import { MAX_VOICE_DURATION_MS, MIN_VOICE_DURATION_MS, voiceStateForMove } from '../utils/voice_gesture';
import { VoiceRecorderApi, voiceRecorder } from '../utils/voice_recorder';

interface Options { onRecordingStarted: (id: string) => void; onRecordingCancelled: (id: string, reason: string) => void; onRecordingCommitted: (value: { uploadId: string; localUri: string; durationMs: number }) => void; onStopAllAudio: () => Promise<void>; onNotice: (text: string) => void; recorder?: VoiceRecorderApi; }

/** 录音已结束、可以立刻再次按住录音的稳定状态。 */
const RECORDABLE_STATES: VoiceCaptureState[] = ['VoiceReady', 'Sent', 'Failed'];
/** 允许切回文字模式的状态：上传本身在后台继续，不得锁住模式切换。 */
const TEXT_TOGGLE_STATES: VoiceCaptureState[] = ['VoiceReady', 'Uploading', 'Sent', 'Failed'];

export function useVoiceInput(options: Options) {
  const recorder = options.recorder || voiceRecorder;
  const [mode, setMode] = useState<'text' | 'voice'>('text');
  const [captureState, setCaptureState] = useState<VoiceCaptureState>('TextMode');
  const [elapsedMs, setElapsedMs] = useState(0);
  const [smoothedMeter, setSmoothedMeter] = useState(0);
  const stateRef = useRef<VoiceCaptureState>('TextMode');
  const initialY = useRef(0); const id = useRef<string | null>(null); const startedAt = useRef(0); const cancelZone = useRef(false); const finishing = useRef(false);
  const starting = useRef(false); const pendingRelease = useRef(false);
  const abortedDuringStart = useRef(false);
  const cancelNotifierRef = useRef(options.onRecordingCancelled);
  cancelNotifierRef.current = options.onRecordingCancelled;

  const updateState = useCallback((next: VoiceCaptureState) => { stateRef.current = next; setCaptureState(next); }, []);

  const toggleMode = useCallback(() => {
    const current = stateRef.current;
    if (current === 'TextMode') { setMode('voice'); updateState('VoiceReady'); return; }
    if (TEXT_TOGGLE_STATES.includes(current)) { setMode('text'); updateState('TextMode'); }
  }, [updateState]);

  const cancel = useCallback(async (reason: string) => {
    if (finishing.current) return;
    finishing.current = true;
    const current = id.current;
    id.current = null;
    try {
      await recorder.cancel();
      if (current) options.onRecordingCancelled(current, reason);
    } catch {
      // 取消是尽力而为：底层清理失败也必须复位状态，否则 UI 永久停在录音遮罩。
    } finally {
      setElapsedMs(0);
      setSmoothedMeter(0);
      updateState('VoiceReady');
      finishing.current = false;
    }
  }, [options, recorder, updateState]);

  const pressIn = useCallback(async (event: GestureResponderEvent) => {
    if (!RECORDABLE_STATES.includes(stateRef.current) || finishing.current || starting.current) return;
    initialY.current = event.nativeEvent.pageY;
    starting.current = true;
    pendingRelease.current = false;
    abortedDuringStart.current = false;
    try {
      const permission = await recorder.getPermission();
      if (permission !== 'granted') {
        updateState('PermissionPrompt');
        const result = permission === 'denied' ? await recorder.requestPermission() : permission;
        if (result === 'blocked') {
          // AC-03：永久拒绝必须给出可直达系统设置的动作，而不是只有纯文本提示。
          options.onNotice('麦克风权限已关闭，请前往设置开启');
          Alert.alert('麦克风权限已关闭', '请在系统设置中允许本应用使用麦克风后再录音。', [
            { text: '取消', style: 'cancel' },
            { text: '去设置', onPress: () => { void Linking.openSettings(); } },
          ]);
        } else if (result !== 'granted') options.onNotice('未获得麦克风权限，无法录音');
        updateState('VoiceReady');
        return;
      }
      await options.onStopAllAudio();
      const started = await recorder.start({
        onMetering: (db) => setSmoothedMeter((prev) => prev * 0.7 + Math.max(0, Math.min(1, (db + 60) / 60)) * 0.3),
        onInterrupted: () => { void cancel('interrupted'); },
      });
      id.current = started.recordingId; startedAt.current = Date.now(); cancelZone.current = false; setElapsedMs(0);
      updateState('Recording');
      options.onRecordingStarted(started.recordingId);
      if (abortedDuringStart.current) {
        // 启动窗口内被切后台/系统中断：recorder 已被取消，这里必须收尾并通知服务端。
        abortedDuringStart.current = false;
        await cancel('background');
        return;
      }
      if (pendingRelease.current) {
        // 快速点按：开始录音完成前就松手，按“过短”取消，避免 30 秒后把残片当成长录音提交。
        pendingRelease.current = false;
        await cancel('too_short');
        options.onNotice('说话时间太短');
      }
    } catch {
      id.current = null;
      options.onNotice('录音启动失败，请重试');
      updateState('Failed');
    } finally {
      starting.current = false;
    }
  }, [cancel, options, recorder, updateState]);

  const pressMove = useCallback((event: GestureResponderEvent) => { const next = voiceStateForMove(stateRef.current, initialY.current, event.nativeEvent.pageY); if (next === 'CancelZone' && !cancelZone.current) { cancelZone.current = true; void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium).catch(() => undefined); } if (next === 'Recording') cancelZone.current = false; updateState(next); }, [updateState]);

  const pressOut = useCallback(async () => {
    const current = stateRef.current;
    if (starting.current && (current === 'VoiceReady' || current === 'PermissionPrompt')) {
      // 权限检查/recorder.start 尚未完成：记录这次松手，准备完成后按“过短”处理。
      pendingRelease.current = true;
      return;
    }
    if (current !== 'Recording' && current !== 'CancelZone') return;
    const elapsed = Math.min(MAX_VOICE_DURATION_MS, Date.now() - startedAt.current);
    if (current === 'CancelZone' || elapsed < MIN_VOICE_DURATION_MS) {
      await cancel(elapsed < MIN_VOICE_DURATION_MS ? 'too_short' : 'gesture_cancel');
      if (elapsed < MIN_VOICE_DURATION_MS) options.onNotice('说话时间太短');
      return;
    }
    if (finishing.current) return;
    finishing.current = true;
    const recording = id.current;
    try {
      const result = await recorder.stop();
      if (recording && result) {
        updateState('Uploading');
        options.onRecordingCommitted({ uploadId: recording, localUri: result.localUri, durationMs: Math.min(MAX_VOICE_DURATION_MS, result.durationMs || elapsed) });
        updateState('Sent');
      } else {
        updateState('VoiceReady');
      }
    } catch {
      // recorder.stop() 在删除本地文件后会重新抛出；这里必须复位状态，否则 finishing 永久为真。
      options.onNotice('录音保存失败，请重试');
      updateState('Failed');
    } finally {
      id.current = null;
      setElapsedMs(0);
      setSmoothedMeter(0);
      finishing.current = false;
    }
  }, [cancel, options, recorder, updateState]);

  useEffect(() => { if (captureState !== 'Recording' && captureState !== 'CancelZone') return; const timer = setInterval(() => { const elapsed = Math.min(MAX_VOICE_DURATION_MS, Date.now() - startedAt.current); setElapsedMs(elapsed); if (elapsed >= MAX_VOICE_DURATION_MS) void pressOut(); }, 100); return () => clearInterval(timer); }, [captureState, pressOut]);
  useEffect(() => {
    const sub = AppState.addEventListener('change', (state) => {
      if (state === 'active') return;
      if (stateRef.current === 'Recording' || stateRef.current === 'CancelZone') {
        void cancel('background');
        return;
      }
      // 启动窗口（权限检查/onStopAllAudio/recorder.start 未完成）切后台同样必须收尾，
      // 否则 pressIn 恢复后会照常进入 Recording，30 秒后把残片提交上传。
      if (starting.current) {
        abortedDuringStart.current = true;
        void recorder.cancel();
      }
    });
    return () => sub.remove();
  }, [cancel, recorder]);
  useEffect(() => () => {
    const current = id.current;
    id.current = null;
    if (current) cancelNotifierRef.current(current, 'unmounted');
    void recorder.dispose();
  }, [recorder]);
  return { mode, captureState, elapsedMs, smoothedMeter, isCancelZone: captureState === 'CancelZone', toggleMode, pressIn, pressMove, pressOut, cancelBySystem: cancel };
}

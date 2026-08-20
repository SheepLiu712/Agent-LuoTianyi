import { useCallback, useEffect, useRef, useState } from 'react';
import { WebView } from 'react-native-webview';
import { AudioStreamType, Live2DAudioPacket, Live2DAudioStopCommand } from '../types/audio';
import { CallStatus } from '../types/call';
import { WSEventType } from '../types/ws_events';
import { CallTransport } from '../utils/call_transport';
import { addDebugTrace } from '../utils/debug_trace';
import { PcmRecorder } from '../modules/pcm-recorder';
import { setExpression } from '../utils/live2d_helper';

export function useCallLogic(
  webviewRef: React.RefObject<WebView | null>,
  username: string,
  token: string,
  onEnded?: () => void,
  enabled = true,
) {
  const [status, setStatus] = useState<CallStatus>('idle');
  const [error, setError] = useState<string | null>(null);
  const [connectedAtMs, setConnectedAtMs] = useState<number | null>(null);
  const transportRef = useRef<CallTransport | null>(null);
  const recorderRef = useRef<PcmRecorder | null>(null);
  const audioSeqRef = useRef(0);
  const cancelledResponseIdsRef = useRef(new Set<string>());

  const stopRecorder = useCallback(async () => {
    if (recorderRef.current) {
      await recorderRef.current.stop().catch((stopError) => {
        addDebugTrace('call_audio', 'stop recorder failed', { error: String(stopError) });
      });
      recorderRef.current = null;
    }
  }, []);

  const startRecorder = useCallback(async () => {
    await stopRecorder();
    const recorder = new PcmRecorder();
    recorderRef.current = recorder;
    try {
      await recorder.start(({ audio }) => {
        const callSeq = audioSeqRef.current++;
        transportRef.current?.appendAudio(audio, callSeq);
      }, (recordingError) => {
        addDebugTrace('call_audio', 'pcm recorder capture failed', recordingError);
        setError(recordingError.message);
      });
    } catch (recorderError) {
      recorderRef.current = null;
      setError(String(recorderError));
    }
  }, [stopRecorder]);

  useEffect(() => {
    if (!enabled) return;
    const transport = new CallTransport(username, token, {
      onStatus: (nextStatus) => {
        setStatus(nextStatus);
        if (nextStatus === 'active') void startRecorder();
        if (nextStatus === 'reconnecting') void stopRecorder();
        if (nextStatus === 'ended' || nextStatus === 'idle') void stopRecorder();
      },
      onConnectedAt: (timestamp) => {
        const parsed = Date.parse(timestamp);
        if (!Number.isNaN(parsed)) setConnectedAtMs(parsed);
      },
      onError: (message) => setError(message),
      onEvent: (type, payload) => {
        if (type === WSEventType.CALL_AUDIO_CHUNK) {
          if (payload.stream_type !== AudioStreamType.CALL) {
            addDebugTrace('call_audio', 'non-call packet rejected by call player', {
              streamType: payload.stream_type,
            });
            return;
          }
          const audio = typeof payload.audio === 'string' ? payload.audio : '';
          const audioId = typeof payload.audio_id === 'string' ? payload.audio_id : '';
          const responseId = typeof payload.response_id === 'string' ? payload.response_id : '';
          const isFinal = Boolean(payload.is_final);
          if (!audioId || !responseId || cancelledResponseIdsRef.current.has(responseId)) {
            addDebugTrace('call_audio', 'invalid or cancelled call packet dropped', {
              audioId,
              responseId,
              cancelled: cancelledResponseIdsRef.current.has(responseId),
            });
            return;
          }
          if (typeof payload.expression === 'string' && payload.expression) {
            setExpression(payload.expression, webviewRef);
          }
          const packet: Live2DAudioPacket = {
            stream_type: AudioStreamType.CALL,
            audio_id: audioId,
            response_id: responseId,
            audio,
            is_final: isFinal,
          };
          webviewRef.current?.injectJavaScript(
            `window.feedAudioPacket(${JSON.stringify(packet)}); true;`,
          );
        } else if (type === WSEventType.CALL_STOP_PLAYBACK) {
          if (payload.stream_type !== AudioStreamType.CALL) return;
          const responseId = typeof payload.response_id === 'string' ? payload.response_id : '';
          const audioIds = Array.isArray(payload.audio_ids)
            ? payload.audio_ids.filter((value): value is string => typeof value === 'string' && value.length > 0)
            : [];
          const reason = typeof payload.reason === 'string' ? payload.reason : 'stopped';
          if (responseId) cancelledResponseIdsRef.current.add(responseId);
          const command: Live2DAudioStopCommand = {
            stream_type: AudioStreamType.CALL,
            response_id: responseId || undefined,
            audio_ids: audioIds,
            reason,
          };
          webviewRef.current?.injectJavaScript(
            `window.stopAudioStream(${JSON.stringify(command)}); true;`,
          );
        } else if (type === WSEventType.CALL_ENDED) {
          cancelledResponseIdsRef.current.clear();
          void stopRecorder();
          onEnded?.();
        } else if (type === WSEventType.CALL_REJECTED) {
          setError(String(payload.message || payload.code || '电话请求被拒绝'));
          void stopRecorder();
          onEnded?.();
        }
      },
    });
    transportRef.current = transport;
    transport.start();
    return () => {
      cancelledResponseIdsRef.current.clear();
      void stopRecorder();
      transport.stop();
      transportRef.current = null;
    };
  }, [enabled, onEnded, startRecorder, stopRecorder, token, username, webviewRef]);

  const startCall = useCallback(async () => {
    setError(null);
    audioSeqRef.current = 0;
    cancelledResponseIdsRef.current.clear();
    const result = await transportRef.current?.startCall();
    if (result && !result.ok) setError(result.message || result.error || '电话建立失败');
    return result;
  }, []);

  const hangup = useCallback(async () => {
    await stopRecorder();
    const result = await transportRef.current?.hangup();
    if (result && !result.ok) setError(result.message || result.error || '挂断失败');
    return result;
  }, [stopRecorder]);

  const handleWebViewMessage = useCallback((event: any) => {
    try {
      const data = JSON.parse(event.nativeEvent.data);
      if (data.stream_type !== AudioStreamType.CALL) return;
      if (data.type === 'audio_finished' && data.audio_id) {
        void transportRef.current?.playbackCompleted(
          String(data.audio_id),
          typeof data.response_id === 'string' ? data.response_id : undefined,
        );
      } else if (data.type === 'audio_stopped' && data.audio_id) {
        void transportRef.current?.playbackStopped(
          String(data.audio_id),
          typeof data.response_id === 'string' ? data.response_id : undefined,
          typeof data.reason === 'string' ? data.reason : 'stopped',
        );
      }
    } catch {
      // Live2D 页面也会发送 modelLoaded/touch 等非通话消息，忽略格式错误。
    }
  }, []);

  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  useEffect(() => {
    if (status !== 'active' || connectedAtMs === null) {
      if (status !== 'active') setElapsedSeconds(0);
      return;
    }
    const update = () => setElapsedSeconds(Math.max(0, Math.floor((Date.now() - connectedAtMs) / 1000)));
    update();
    const timer = setInterval(update, 1000);
    return () => clearInterval(timer);
  }, [connectedAtMs, status]);

  return { status, error, elapsedSeconds, startCall, hangup, handleWebViewMessage };
}

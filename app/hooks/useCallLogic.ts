import { useCallback, useEffect, useRef, useState } from 'react';
import { WebView } from 'react-native-webview';
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
        const callSeq = audioSeqRef.current;
        if (transportRef.current?.appendAudio(audio, callSeq)) {
          audioSeqRef.current += 1;
        }
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
          const audio = typeof payload.audio === 'string' ? payload.audio : '';
          const audioId = typeof payload.audio_id === 'string' ? payload.audio_id : '';
          const responseId = typeof payload.response_id === 'string' ? payload.response_id : '';
          const isFinal = Boolean(payload.is_final);
          if (typeof payload.expression === 'string' && payload.expression) {
            setExpression(payload.expression, webviewRef);
          }
          webviewRef.current?.injectJavaScript(
            `window.feedAudioChunk(${JSON.stringify(audio)},${JSON.stringify(isFinal)},${JSON.stringify(audioId)},${JSON.stringify(responseId)}); true;`,
          );
        } else if (type === WSEventType.CALL_STOP_PLAYBACK) {
          webviewRef.current?.injectJavaScript('window.stopAudioPlayback && window.stopAudioPlayback(); true;');
        } else if (type === WSEventType.CALL_ENDED) {
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
      void stopRecorder();
      transport.stop();
      transportRef.current = null;
    };
  }, [enabled, onEnded, startRecorder, stopRecorder, token, username, webviewRef]);

  const startCall = useCallback(async () => {
    setError(null);
    audioSeqRef.current = 0;
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
      if (data.type === 'audio_finished' && data.audio_id) {
        transportRef.current?.playbackCompleted(String(data.audio_id), typeof data.response_id === 'string' ? data.response_id : undefined);
      } else if (data.type === 'audio_stopped' && data.audio_id) {
        transportRef.current?.playbackStopped(String(data.audio_id), typeof data.response_id === 'string' ? data.response_id : undefined);
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

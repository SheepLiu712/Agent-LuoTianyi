import * as FileSystem from 'expo-file-system/legacy';
import * as ImagePicker from 'expo-image-picker';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { FlatList } from 'react-native';
import { WebView } from 'react-native-webview';
import { setExpression } from '../utils/live2d_helper';
import { AgentBinder } from '../utils/binder';
import { MessageProcessor } from '../utils/message_processor';
import { NetworkClient } from '../utils/network_client';
import { AgentMessagePayload, ChatMessage, createSystemChatMessage } from '../types/chat';
import { addDebugTrace } from '../utils/debug_trace';
import { useVoiceInput } from './useVoiceInput';
import { voicePlaybackManager } from '../utils/voice_playback_manager';
import { runImageSelection } from '../utils/image_selection';

function createUuid(prefix: string) {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export const useChatLogic = (
  webviewRef: React.RefObject<WebView | null>,
  username: string,
  messageToken: string,
) => {
  const [inputText, setInputText] = useState('');
  const [thinking, setThinking] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [currentPlayingUuid, setCurrentPlayingUuid] = useState<string | null>(null);
  const flatListRef = useRef<FlatList>(null);

  const networkClientRef = useRef<NetworkClient | null>(null);
  const binderRef = useRef<AgentBinder | null>(null);
  const messageProcessorRef = useRef<MessageProcessor | null>(null);
  const recordingAudioRef = useRef(false);
  const playbackGeneration = useRef(0);
  const clickTimestampsRef = useRef<number[]>([]);
  const voiceFilesRef = useRef(new Map<string, { localUri: string; durationMs: number }>());
  const voiceAckMapRef = useRef(new Map<string, string>());

  const updateMessageByUuid = useCallback((uuid: string, updater: (msg: ChatMessage) => ChatMessage) => {
    setMessages((prev) => prev.map((msg) => (msg.uuid === uuid ? updater(msg) : msg)));
  }, []);

  const appendOrMergeAgentMessage = useCallback(
    (payload: AgentMessagePayload) => {
      const convUuid = payload.uuid || createUuid('agent');

      setMessages((prev) => {
        const index = prev.findIndex((msg) => msg.uuid === convUuid && !msg.isUser);
        const expression = payload.expression;
        if (expression) {
          setExpression(expression, webviewRef);
        }

        if (payload.display_in_chat === false) {
          return prev;
        }

        // Some packets only carry state/expression updates; do not render empty bubbles.
        if (!payload.text && !payload.audio && index < 0) {
          return prev;
        }

        if (index >= 0) {
          const target = prev[index];
          const merged: ChatMessage = {
            ...target,
            // 服务端约定文本只在每句话的首包携带（global_speaking_worker 首个分片带 text）。
            // 同 uuid 的重复文本包（at-least-once 重发）直接忽略，避免"同一句话显示两次"。
            content: payload.text && !target.content ? payload.text : target.content,
            audioAvailable: payload.audio ? true : target.audioAvailable,
            audioLocalUri: payload.audio || target.audioLocalUri,
          };
          const next = [...prev];
          next[index] = merged;
          return next;
        }

        const newMsg: ChatMessage = {
          uuid: convUuid,
          type: 'text',
          content: payload.text || '',
          isUser: false,
          timestamp: Date.now(),
          audioAvailable: !!payload.audio,
          audioLocalUri: payload.audio || undefined,
          audioPlayState: 'idle',
        };

        return [newMsg, ...prev];
      });
    },
    [webviewRef],
  );

  const appendSystemMessage = useCallback((text: string) => {
    if (!text) {
      return;
    }
    const message = createSystemChatMessage(text, createUuid('system'));
    setMessages((prev) => [message, ...prev]);
  }, []);

  const stopUserVoicePlayback = useCallback(async () => {
    playbackGeneration.current += 1;
    setCurrentPlayingUuid(null);
    setMessages((prev) => prev.map((message) => ({ ...message, audioPlayState: 'idle',
      audioDownloadState: message.audioDownloadState === 'loading' ? undefined : message.audioDownloadState })));
    await voicePlaybackManager.stop();
  }, []);

  const voiceInput = useVoiceInput({
    onRecordingStarted: (recordingId) => { void binderRef.current?.sendVoiceRecordingStarted(recordingId); },
    onRecordingCancelled: (recordingId) => { void binderRef.current?.sendVoiceRecordingCancelled(recordingId); },
    onRecordingCommitted: ({ uploadId, localUri, durationMs }) => {
      voiceFilesRef.current.set(uploadId, { localUri, durationMs });
      void voicePlaybackManager.cacheLocal(uploadId, localUri).then((cachedUri) => updateMessageByUuid(uploadId, (msg) => ({ ...msg, audioLocalUri: cachedUri, audioAvailable: true })));
      setMessages((prev) => [{ uuid: uploadId, type: 'audio', content: '[语音消息]', isUser: true, timestamp: Date.now(), durationMs, audioLocalUri: localUri, audioAvailable: true, sendStatus: 'waiting' }, ...prev]);
      void binderRef.current?.sendVoice(uploadId, localUri, durationMs);
    },
    onStopAllAudio: async () => {
      recordingAudioRef.current = true;
      await Promise.all([messageProcessorRef.current?.setRecordingActive(true), stopUserVoicePlayback()]);
    },
    onRecordingEnded: () => {
      recordingAudioRef.current = false;
      void messageProcessorRef.current?.setRecordingActive(false);
    },
    onNotice: appendSystemMessage,
  });

  const onVoiceUploadStatus = voiceInput.onUploadStatus;

  useEffect(() => {
    if (!username || !messageToken) {
      return;
    }

    const networkClient = new NetworkClient();
    networkClientRef.current = networkClient;

    const binder = new AgentBinder(
      {
        sendText: async (uuid, text) => {
          await messageProcessorRef.current?.sendText(uuid, text);
        },
        sendImage: async (uuid, imageUri, mimeType) => {
          await messageProcessorRef.current?.sendImage(uuid, imageUri, mimeType);
        },
        sendProactiveText: async (uuid, text) => {
          await messageProcessorRef.current?.sendProactiveText(uuid, text);
        },
        sendTouch: async (touchArea, clickFrequency, touchMeta) => {
          await messageProcessorRef.current?.sendTouch(touchArea, clickFrequency, touchMeta);
        },
        sendTyping: async (textLength) => {
          await messageProcessorRef.current?.sendTypingEvent(textLength);
        },
        sendImageSelecting: async () => {
          await messageProcessorRef.current?.sendImageSelecting();
        },
        sendImageSelectingCancel: async () => {
          await messageProcessorRef.current?.sendImageSelectingCancel();
        },
        sendVoiceRecordingStarted: async (recordingId) => { await networkClientRef.current?.sendVoiceRecordingStarted(recordingId); },
        sendVoiceRecordingCancelled: async (recordingId) => { await networkClientRef.current?.sendVoiceRecordingCancelled(recordingId); },
        sendVoice: async (uuid, localUri, durationMs) => { await messageProcessorRef.current?.sendVoice(uuid, localUri, durationMs); },
        retryVoice: async (uuid) => {
          const file = voiceFilesRef.current.get(uuid);
          const processor = messageProcessorRef.current;
          if (!file || !(await FileSystem.getInfoAsync(file.localUri)).exists) throw new Error('本地语音文件已不存在，无法重试');
          if (!processor) throw new Error('发送服务不可用，请稍后重试');
          await processor.sendVoice(uuid, file.localUri, file.durationMs);
        },
        playLocalTts: async (convUuid) => {
          addDebugTrace('audio-ui', 'binder playLocalTts called', { convUuid });
          return (await messageProcessorRef.current?.playLocalTtsByUuid(convUuid)) || false;
        },
        stopLocalTts: async () => {
          addDebugTrace('audio-ui', 'binder stopLocalTts called');
          await messageProcessorRef.current?.stopLocalTts();
        },
      },
      {
        onAgentMessage: (payload) => {
          appendOrMergeAgentMessage(payload);
        },
        onMessageStatus: (uuid, status) => {
          addDebugTrace('ui', 'message status update', { uuid, status });
          updateMessageByUuid(uuid, (msg) => ({ ...msg, sendStatus: status }));
          onVoiceUploadStatus(uuid, status);
        },
        onAgentThinking: (isThinking) => {
          setThinking(isThinking);
        },
        onLocalTtsState: (_event, convUuid) => {
          updateMessageByUuid(convUuid, (msg) => ({ ...msg, audioPlayState: 'idle' }));
          setCurrentPlayingUuid((prev) => (prev === convUuid ? null : prev));
        },
        onErrorText: (text) => {
          addDebugTrace('ui', 'error text', { text });
          appendSystemMessage(text);
        },
      },
    );

    binderRef.current = binder;

    const processor = new MessageProcessor(
      networkClient,
      binder,
      (base64Audio, isFinal) => {
        const jsCode = `window.feedAudioChunk(${JSON.stringify(base64Audio)}, ${isFinal ? 'true' : 'false'}); true;`;
        webviewRef.current?.injectJavaScript(jsCode);
      },
      () => {
        const jsCode = `window.stopServerAudio(); true;`;
        webviewRef.current?.injectJavaScript(jsCode);
      },
      (uploadId, messageUuid, durationMs) => {
        voiceAckMapRef.current.set(uploadId, messageUuid);
        updateMessageByUuid(uploadId, (msg) => ({
          ...msg,
          durationMs: durationMs ?? msg.durationMs,
          sendStatus: 'submitted',
        }));
        // 缓存按 upload_id 落盘，但鉴权下载只认 message_uuid：迁移缓存键并回指气泡，
        // 避免缓存被 LRU 淘汰后回放请求打到不存在的 upload_id 上（404）。
        void voicePlaybackManager.migrateCacheKey(uploadId, messageUuid).then((migratedUri) => {
          if (!migratedUri) return;
          updateMessageByUuid(uploadId, (msg) => ({ ...msg, audioLocalUri: migratedUri }));
        });
      },
      stopUserVoicePlayback,
    );

    messageProcessorRef.current = processor;

    networkClient.connectWs(username, messageToken, {
      onAgentMessage: (payload) => {
        processor.onAgentMessage(payload);
      },
      onAgentStateChanged: (state) => {
        processor.onAgentStateChanged(state);
      },
      onError: (errorText) => {
        binder.emitErrorText(errorText);
      },
      onLlmRequest: (payload) => processor.processLlmRequest(payload),
      getLlmMode: () => processor.getLlmMode(),
    });

    return () => {
      processor.stop();
      void stopUserVoicePlayback();
      networkClient.disconnectWs();
      messageProcessorRef.current = null;
      binderRef.current = null;
      networkClientRef.current = null;
    };
  }, [appendOrMergeAgentMessage, appendSystemMessage, messageToken, onVoiceUploadStatus, stopUserVoicePlayback, updateMessageByUuid, username, webviewRef]);

  const canSend = useMemo(() => inputText.trim().length > 0, [inputText]);
  const canSendImage = true;

  const handleWebViewMessage = useCallback((event: any) => {
    try {
      const data = JSON.parse(event.nativeEvent.data);
      if (data.type === 'audio_finished' || data.type === 'audio_stopped') {
        messageProcessorRef.current?.onServerAudioFinished();
        return;
      }
      if (data.type === 'touch') {
        // WebView 已经绘制触摸圆环；在线音频期间不再统计或发送触摸。
        if (messageProcessorRef.current?.isServerAudioActive()) {
          return;
        }
        const now = Date.now();
        const timestamps = clickTimestampsRef.current;
        timestamps.push(now);
        // Keep only last 30s of clicks
        const cutoff = now - 30000;
        while (timestamps.length > 0 && timestamps[0] < cutoff) {
          timestamps.shift();
        }
        const count10s = timestamps.filter((t) => t > now - 10000).length;
        const count30s = timestamps.length;
        clickTimestampsRef.current = timestamps;
        // 新格式：touchArea 是字符串数组，附加 timeSinceLastSentTouch 和 touchCount
        const touchArea = data.touchArea || ['头'];
        void binderRef.current?.sendTouch(
          touchArea,
          { count_10s: count10s, count_30s: count30s },
          {
            timeSinceLastSentTouch: data.timeSinceLastSentTouch || 0,
            touchCount: data.touchCount || 1,
          },
        );
        return;
      }
    } catch {
      // ignore malformed WebView messages
    }
  }, []);

  const handleInputChange = useCallback((text: string) => {
    setInputText(text);
    const trimmedLength = text.trim().length;
    // 清空输入时也发送 text_length=0 事件，通知服务端"用户已清空输入"并立即提取，而非继续等待补全
    void binderRef.current?.sendTyping(trimmedLength);
  }, []);

  const handleSendText = useCallback(async () => {
    if (!canSend) {
      return;
    }

    const uuid = createUuid('user');
    const text = inputText;
    setInputText('');
    addDebugTrace('ui', 'send text tapped', { uuid, textLength: text.length });

    setMessages((prev) => [
      {
        uuid,
        type: 'text',
        content: text,
        isUser: true,
        timestamp: Date.now(),
        sendStatus: 'waiting',
      },
      ...prev,
    ]);

    await binderRef.current?.sendText(uuid, text);
  }, [canSend, inputText]);

  const handleSendImage = useCallback(async () => {
    await runImageSelection({
      sendSelecting: async () => {
        await binderRef.current?.sendImageSelecting();
      },
      cancelSelecting: async () => {
        await binderRef.current?.sendImageSelectingCancel();
      },
      launchPicker: () =>
        ImagePicker.launchImageLibraryAsync({
          mediaTypes: ['images'],
          allowsEditing: false,
          quality: 1,
        }),
      emitError: (message) => binderRef.current?.emitErrorText(message),
      onSelected: async (asset) => {
        const imageUri = asset.uri;
        const mimeType = asset.mimeType || 'image/jpeg';
        const uuid = createUuid('user-img');
        addDebugTrace('ui', 'send image selected', { uuid, imageUri, mimeType });

        setMessages((prev) => [
          {
            uuid,
            type: 'image',
            content: imageUri,
            isUser: true,
            timestamp: Date.now(),
            sendStatus: 'waiting',
          },
          ...prev,
        ]);

        await binderRef.current?.sendImage(uuid, imageUri, mimeType);
      },
    });
  }, []);

  const handleToggleAgentAudio = useCallback(
    async (uuid: string) => {
      if (recordingAudioRef.current || messageProcessorRef.current?.isServerAudioActive()) return;
      const generation = ++playbackGeneration.current;
      addDebugTrace('audio-ui', 'tap audio button', { uuid, currentPlayingUuid });
      const target = messages.find((msg) => msg.uuid === uuid && !msg.isUser);
      if (!target || !target.audioAvailable) {
        addDebugTrace('audio-ui', 'tap ignored: target missing or audio unavailable', {
          uuid,
          found: !!target,
          audioAvailable: target?.audioAvailable,
        });
        return;
      }

      addDebugTrace('audio-ui', 'audio target resolved', {
        uuid,
        audioLocalUri: target.audioLocalUri,
        audioAvailable: target.audioAvailable,
      });

      if (target.audioLocalUri) {
        messageProcessorRef.current?.setLocalAudioPath(uuid, target.audioLocalUri);
      }

      if (currentPlayingUuid === uuid) {
        await binderRef.current?.stopLocalTts();
        return;
      }

      await voicePlaybackManager.stop();
      if (generation !== playbackGeneration.current || recordingAudioRef.current) return;
      const ok = await binderRef.current?.playLocalTts(uuid);
      if (!ok || generation !== playbackGeneration.current || recordingAudioRef.current) {
        addDebugTrace('audio-ui', 'playLocalTts returned false', { uuid });
        return;
      }

      if (currentPlayingUuid) {
        updateMessageByUuid(currentPlayingUuid, (msg) => ({ ...msg, audioPlayState: 'idle' }));
      }

      updateMessageByUuid(uuid, (msg) => ({ ...msg, audioPlayState: 'playing' }));
      setCurrentPlayingUuid(uuid);
    },
    [currentPlayingUuid, messages, updateMessageByUuid],
  );

  const addHistoryMessage = useCallback((newMessages: ChatMessage[]) => {
    for (const msg of newMessages) {
      if (!msg.isUser && msg.audioAvailable && msg.audioLocalUri) {
        messageProcessorRef.current?.setLocalAudioPath(msg.uuid, msg.audioLocalUri);
      }
    }

    setMessages((prev) => {
      const nowScrollIndex = prev.length - 1;
      // 按 uuid 去重：历史消息与实时消息（或分页重叠）可能包含同一条消息，避免重复渲染
      const serverUuids = new Set(newMessages.map((msg) => msg.uuid));
      const optimisticToReplace = new Set(
        [...voiceAckMapRef.current.entries()]
          .filter(([, messageUuid]) => serverUuids.has(messageUuid))
          .map(([uploadId]) => uploadId),
      );
      const retained = prev.filter((msg) => !optimisticToReplace.has(msg.uuid));
      const existingUuids = new Set(retained.map((msg) => msg.uuid));
      const normalized = newMessages
        .filter((msg) => !existingUuids.has(msg.uuid))
        .map((msg) => ({
          ...msg,
          sendStatus: msg.isUser ? 'submitted' : msg.sendStatus,
          audioPlayState: msg.audioPlayState || 'idle',
          audioDownloadState: msg.type === 'audio' ? 'idle' : msg.audioDownloadState,
        }));
      const next = [...retained, ...normalized.reverse()];

      if (nowScrollIndex >= 0) {
        // 快速滑动时目标 index 可能尚未渲染，scrollToIndex 会抛 invariant violation 导致应用闪退。
        // 捕获异常并回退到 offset 定位（见 index.tsx 的 onScrollToIndexFailed），即使失败也不影响列表。
        setTimeout(() => {
          try {
            flatListRef.current?.scrollToIndex({ index: nowScrollIndex, animated: false });
          } catch {
            addDebugTrace('history', 'scrollToIndex failed, fallback to offset', { index: nowScrollIndex });
          }
        }, 10);
      } else {
        setTimeout(() => {
          flatListRef.current?.scrollToOffset({ offset: 0, animated: false });
        }, 10);
      }
      return next;
    });
  }, []);

  const toggleVoicePlayback = useCallback(async (uuid: string) => {
    if (recordingAudioRef.current || messageProcessorRef.current?.isServerAudioActive()) return;
    const generation = ++playbackGeneration.current;
    const target = messages.find((msg) => msg.uuid === uuid && msg.type === 'audio');
    if (!target || target.audioAvailable === false) {
      appendSystemMessage('这条语音暂时无法播放');
      return;
    }
    if (currentPlayingUuid === uuid) {
      await voicePlaybackManager.stop();
      updateMessageByUuid(uuid, (msg) => ({ ...msg, audioPlayState: 'idle' }));
      setCurrentPlayingUuid(null);
      return;
    }
    updateMessageByUuid(uuid, (msg) => ({ ...msg, audioDownloadState: 'loading' }));
    try {
      await binderRef.current?.stopLocalTts();
      // 播放/下载统一使用 ACK 解析出的 message_uuid（协议下载端点只认它），
      // 界面状态仍按 upload_id 回写；无 ACK 时回退到气泡自身 uuid。
      const playbackKey = voiceAckMapRef.current.get(uuid) ?? uuid;
      if (target.audioLocalUri) await voicePlaybackManager.cacheLocal(playbackKey, target.audioLocalUri);
      if (generation !== playbackGeneration.current || recordingAudioRef.current) return;
      await voicePlaybackManager.play(playbackKey, messageToken, (state) => {
        if (generation !== playbackGeneration.current) return;
        updateMessageByUuid(uuid, (msg) => ({ ...msg, audioDownloadState: state === 'loading' ? 'loading' : state === 'failed' ? 'failed' : 'ready', audioPlayState: state === 'playing' ? 'playing' : 'idle' }));
        if (state === 'playing') setCurrentPlayingUuid(uuid);
        else setCurrentPlayingUuid((prev) => prev === uuid ? null : prev);
        if (state === 'failed') appendSystemMessage('语音加载失败，请稍后重试');
      });
      if (currentPlayingUuid && currentPlayingUuid !== uuid) updateMessageByUuid(currentPlayingUuid, (msg) => ({ ...msg, audioPlayState: 'idle' }));
    } catch {
      if (generation !== playbackGeneration.current) return;
      updateMessageByUuid(uuid, (msg) => ({ ...msg, audioDownloadState: 'failed', audioPlayState: 'idle' }));
      appendSystemMessage('语音加载失败，请稍后重试');
    }
  }, [appendSystemMessage, currentPlayingUuid, messageToken, messages, updateMessageByUuid]);

  const retryVoice = async (uuid: string) => {
    const target = messages.find((message) => message.uuid === uuid);
    if (!target?.isUser || target.type !== 'audio' || target.sendStatus !== 'failed') return;
    if (!voiceInput.beginRetryUpload(uuid)) return;
    updateMessageByUuid(uuid, (message) => ({ ...message, sendStatus: 'waiting' }));
    try {
      const binder = binderRef.current;
      if (!binder) throw new Error('发送服务不可用，请稍后重试');
      await binder.retryVoice(uuid);
      // 入队并非发送完成；由发送队列的终态通知解除重试锁定。
    } catch (error) {
      updateMessageByUuid(uuid, (message) => ({ ...message, sendStatus: 'failed' }));
      voiceInput.onUploadStatus(uuid, 'failed');
      appendSystemMessage(error instanceof Error ? error.message : '语音重试失败，请稍后重试');
    }
  };

  return {
    inputText,
    messages,
    flatListRef,
    canSend,
    canSendImage,
    thinking,
    setInputText: handleInputChange,
    addHistoryMessage,
    handleSendText,
    handleSendImage,
    handleWebViewMessage,
    handleToggleAgentAudio,
    toggleVoicePlayback,
    retryVoice,
    voiceInput,
  };
};

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
  const clickTimestampsRef = useRef<number[]>([]);

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
    });

    return () => {
      processor.stop();
      networkClient.disconnectWs();
      messageProcessorRef.current = null;
      binderRef.current = null;
      networkClientRef.current = null;
    };
  }, [appendOrMergeAgentMessage, appendSystemMessage, messageToken, updateMessageByUuid, username, webviewRef]);

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
    // 通知服务端用户开始选择图片，延长等待时间
    await binderRef.current?.sendImageSelecting();

    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ['images'],
      allowsEditing: false,
      quality: 1,
    });

    if (result.canceled || !result.assets || result.assets.length === 0) {
      // 用户取消选择：通知服务端重置等待时间
      await binderRef.current?.sendImageSelectingCancel();
      return;
    }

    const asset = result.assets[0];
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
  }, []);

  const handleToggleAgentAudio = useCallback(
    async (uuid: string) => {
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

      const ok = await binderRef.current?.playLocalTts(uuid);
      if (!ok) {
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
      const existingUuids = new Set(prev.map((msg) => msg.uuid));
      const normalized = newMessages
        .filter((msg) => !existingUuids.has(msg.uuid))
        .map((msg) => ({
          ...msg,
          sendStatus: msg.isUser ? 'submitted' : msg.sendStatus,
          audioPlayState: msg.audioPlayState || 'idle',
        }));
      const next = [...prev, ...normalized.reverse()];

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
  };
};

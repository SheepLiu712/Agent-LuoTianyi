import * as ImagePicker from 'expo-image-picker';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { FlatList } from 'react-native';
import { WebView } from 'react-native-webview';
import { setExpression } from '../utils/live2d_helper';
import { AgentBinder } from '../utils/binder';
import { MessageProcessor } from '../utils/message_processor';
import { NetworkClient } from '../utils/network_client';
import { AgentMessagePayload, ChatMessage } from '../types/chat';
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

        // Some packets only carry state/expression updates; do not render empty bubbles.
        if (!payload.text && !payload.audio && index < 0) {
          return prev;
        }

        if (index >= 0) {
          const target = prev[index];
          const merged: ChatMessage = {
            ...target,
            content: payload.text ? `${target.content}${payload.text}` : target.content,
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
        sendTyping: async (textLength) => {
          await messageProcessorRef.current?.sendTypingEvent(textLength);
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
          appendOrMergeAgentMessage({ uuid: createUuid('error'), text });
        },
      },
    );

    binderRef.current = binder;

    const processor = new MessageProcessor(networkClient, binder, (base64Audio, isFinal) => {
      const jsCode = `window.feedAudioChunk(${JSON.stringify(base64Audio)}, ${isFinal ? 'true' : 'false'}); true;`;
      webviewRef.current?.injectJavaScript(jsCode);
    });

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
  }, [appendOrMergeAgentMessage, messageToken, updateMessageByUuid, username, webviewRef]);

  const canSend = useMemo(() => inputText.trim().length > 0, [inputText]);
  const canSendImage = true;

  const handleWebViewMessage = useCallback((event: any) => {
    try {
      const data = JSON.parse(event.nativeEvent.data);
      if (data.type === 'audio_finished') {
        messageProcessorRef.current?.onServerAudioFinished();
      }
    } catch {
      // ignore malformed WebView messages
    }
  }, []);

  const handleInputChange = useCallback((text: string) => {
    setInputText(text);
    const trimmedLength = text.trim().length;
    if (trimmedLength > 0) {
      void binderRef.current?.sendTyping(trimmedLength);
    }
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
    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ['images'],
      allowsEditing: false,
      quality: 1,
    });

    if (result.canceled || !result.assets || result.assets.length === 0) {
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
      const normalized = newMessages.map((msg) => ({
        ...msg,
        sendStatus: msg.isUser ? 'submitted' : msg.sendStatus,
        audioPlayState: msg.audioPlayState || 'idle',
      }));
      const next = [...prev, ...normalized.reverse()];

      if (nowScrollIndex >= 0) {
        setTimeout(() => {
          flatListRef.current?.scrollToIndex({ index: nowScrollIndex, animated: false });
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

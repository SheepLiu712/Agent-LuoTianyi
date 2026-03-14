import * as ImagePicker from 'expo-image-picker';
import { useCallback, useEffect, useRef, useState } from 'react';
import { FlatList, Keyboard } from 'react-native';
import { WebView } from 'react-native-webview';
import { ChatMessage } from '../components/ChatBubbles';
import { imageChatStream, textChatStream } from '../utils/chat_stream';
import { setExpression } from '../utils/live2d_helper';


interface AgentResponse {
  text: string;
  audio: any;
  expression: string;
  is_final_package: boolean;
}

export const useChatLogic = (webviewRef?: React.RefObject<WebView | null>) => {
  const [inputText, setInputText] = useState('');
  const [thinking, setThinking] = useState(false); // 表示是否AI正在生成回复，用于表明系统没有卡死
  const [processing, setProcessing] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([
  ]);
  const flatListRef = useRef<FlatList>(null);
  const audioFinishedResolver = useRef<(() => void) | null>(null);

  // 计算是否可以发送
  const canSend = inputText.trim().length > 0 && !processing;
  const canSendImage = !processing;

  const handleWebViewMessage = useCallback((event: any) => {
    try {
      const data = JSON.parse(event.nativeEvent.data);
      if (data.type === 'audio_finished') {
        if (audioFinishedResolver.current) {
          audioFinishedResolver.current(); // 唤醒 processAgentResponse
          audioFinishedResolver.current = null;
        }
      } else {
        console.log('收到 WebView 消息:', data);
      }
    } catch (e) {
      console.error("WebView message parse error", e);
    }
  }, []);

  const addAgentMessage = useCallback((text: string) => {
    const agentMessage: ChatMessage = {
      uuid: Date.now().toString() + Math.random().toString(36).substring(2), // 确保唯一
      type: 'text',
      content: text,
      isUser: false,
      timestamp: Date.now()
    };
    setMessages(prev => [agentMessage, ...prev]);
    flatListRef.current?.scrollToOffset({ offset: 0, animated: true });
  }, []);

  // 处理 thinking 状态
  useEffect(() => {
    let timeout: ReturnType<typeof setTimeout>;
    if (thinking) {
      // 延迟 150ms 显示加载动画
      timeout = setTimeout(() => {
        setMessages(prev => {
          // 避免重复添加
          if (prev.some(msg => msg.type === 'loading')) return prev;

          const loadingMessage: ChatMessage = {
            uuid: 'loading-indicator',
            type: 'loading',
            content: '.',
            isUser: false,
            timestamp: Date.now()
          };
          return [loadingMessage, ...prev];
        });
      }, 150);
    } else {
      // 立即移除加载动画
      setMessages(prev => prev.filter(msg => msg.type !== 'loading'));
    }

    return () => clearTimeout(timeout);
  }, [thinking]);

  const processAgentResponse = useCallback(async (createStream: () => AsyncGenerator<AgentResponse>) => {
    let retryCount = 0;
    const maxRetries = 2;

    while (retryCount <= maxRetries) {
      const stream = createStream();
      let canRestart = true; // 如果还没有收到任何数据包，允许在错误发生后重试一次
      let isSuccessful = true; // 标记是否没有发生错误
      setThinking(true);
      setProcessing(true);

      try {
        for await (const response of stream) {
          setThinking(false);
          canRestart = false; // 已经收到数据包了，错误发生后不允许重试了
          if (response.text)
            addAgentMessage(response.text);
          if (response.expression)
            setExpression(response.expression, webviewRef!);
          if (response.audio) {
            // 发送音频数据块
            webviewRef!.current?.injectJavaScript(`window.feedAudioChunk('${response.audio}', false); true;`);
          }

          if (response.is_final_package) {
            // 发送结束标志
            webviewRef!.current?.injectJavaScript(`window.feedAudioChunk('', true); true;`);
            await new Promise<void>((resolve) => {
              audioFinishedResolver.current = resolve;
            });
          }
        }
      } catch (e: any) {
        isSuccessful = false;
        console.error("Error processing agent response:", e);
      } finally {
        const willRetry = !isSuccessful && canRestart && retryCount < maxRetries;
        if (!willRetry) {
          setThinking(false);
          if(!isSuccessful) {
            addAgentMessage("哎呀，信号被吃掉了！试着重新说一遍吧。");
            setExpression('呆呆脸', webviewRef!);
          }
          setProcessing(false);
          break; // 不需要重试了，退出循环
        }

        retryCount++;
        console.log(`Retry processing agent response... (${retryCount}/${maxRetries})`);
        await new Promise(resolve => setTimeout(resolve, 500)); // 等待 0.5 秒重试
      }
    }
  }, [addAgentMessage, webviewRef]);

  // 发送文本消息
  const handleSendText = async () => {
    if (!canSend) {
      return;
    }

    const newMessage: ChatMessage = {
      uuid: Date.now().toString(),
      type: 'text',
      content: inputText,
      isUser: true,
      timestamp: Date.now()
    };
    setMessages([newMessage, ...messages]);
    setInputText('');
    Keyboard.dismiss();


    // 调用流式聊天接口
    processAgentResponse(() => textChatStream(inputText));
  };

  // 发送图片消息
  const handleSendImage = async () => {
    if (!canSendImage) {
      return;
    }

    // 1. 调用图片选择器
    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: "images",
      allowsEditing: false,
      quality: 1,
    });

    if (result.canceled || !result.assets || result.assets.length === 0) {
      return;
    }

    const asset = result.assets[0];
    const imageUri = asset.uri;
    const mimeType = asset.mimeType || 'image/jpeg';

    // 2. 增加 ChatMessage
    const newMessage: ChatMessage = {
      uuid: Date.now().toString(),
      type: 'image',
      content: imageUri,
      isUser: true,
      timestamp: Date.now()
    };
    setMessages(prev => [newMessage, ...prev]);

    // 3. 调用流式聊天接口
    try {
      // 4. 调用 processAgentResponse
      await processAgentResponse(() => imageChatStream(imageUri, mimeType));
    } catch (error) {
      console.error("Image chat failed", error);
      addAgentMessage("Image upload failed: " + error);
      setProcessing(false);
    }
  };

  const addHistoryMessage = useCallback((newMessages: ChatMessage[]) => {
    setMessages(prev => {
      const nowScrollIndex = prev.length - 1; // 当前最新消息的索引
      // 将newMessages倒序添加到前面，这样FlatList才能正确显示历史消息

      const next = [...prev, ...newMessages.reverse()]; // inverted order
      // 恢复之前的滚动位置
      if (nowScrollIndex >= 0) {
        setTimeout(() => {
          flatListRef.current?.scrollToIndex({ index: nowScrollIndex, animated: false });
        }, 10);
      } else {
        // 如果之前没有消息了，直接滚动到最后
        setTimeout(() => {
          flatListRef.current?.scrollToOffset({ offset: 0, animated: false });
        }, 10);
      }
      return next;
    });
  }, []);

  return {
    // 状态
    inputText,
    processing,
    messages,
    flatListRef,
    canSend,
    canSendImage,

    // 方法
    setInputText,
    addHistoryMessage,
    handleSendText,
    handleSendImage,
    handleWebViewMessage
  };
};

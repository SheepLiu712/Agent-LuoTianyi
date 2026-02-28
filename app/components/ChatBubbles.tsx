import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { CachedImage } from './CachedImage';

// 消息类型定义
export interface ChatMessage {
  uuid: string;
  type: 'text' | 'image' | 'loading';
  content: string; // 对于文本是文字内容，对于图片是图片路径
  isUser: boolean;
  timestamp?: number;
}

// 文本气泡组件
export const ChatBubble: React.FC<{ message: ChatMessage }> = ({ message }) => {
  const { content, isUser } = message;

  return (
    <View style={styles.bubbleContainer}>
      <View
        style={[
          styles.bubble,
          isUser ? styles.userBubble : styles.botBubble,
        ]}
      >
        <Text style={styles.bubbleText}>{content}</Text>
      </View>
    </View>
  );
};

// 图片气泡组件
export const ChatImageBubble: React.FC<{ message: ChatMessage }> = ({ message }) => {
  const { content, isUser, uuid } = message;

  return (
    <View style={styles.imageBubbleContainer}>
      <View style={isUser ? styles.imageWrapperUser : styles.imageWrapperBot}>
        <CachedImage
          message_id={uuid}
          localUri={content}
          style={styles.chatImage}
          maxHeight={200}
          maxWidth={200}
          
        />
      </View>
    </View>
  );
};


// 加载中气泡组件
export const ChatLoadingBubble: React.FC<{ message: ChatMessage }> = ({ message }) => {
  const [dots, setDots] = React.useState('.');

  React.useEffect(() => {
    const interval = setInterval(() => {
      setDots(prev => {
        if (prev.length >= 3) return '.';
        return prev + '.';
      });
    }, 1000); // 每秒增加一个点
    return () => clearInterval(interval);
  }, []);

  return (
    <View style={styles.bubbleContainer}>
        <View style={[styles.bubble, styles.botBubble]}>
            <Text style={styles.bubbleText}>{dots}</Text>
        </View>
    </View>
  );
};

// 统一的消息渲染组件
export const MessageItem: React.FC<{ message: ChatMessage }> = ({ message }) => {
  if (message.type === 'loading') { // 如果是加载中状态，显示加载气泡
      return <ChatLoadingBubble message={message} />; 
  }
  if (message.type === 'image') {
    return <ChatImageBubble message={message} />;
  }
  return <ChatBubble message={message} />;
};

const styles = StyleSheet.create({
  // 文本气泡样式
  bubbleContainer: {
    paddingHorizontal: 10,
    paddingVertical: 5,
  },
  bubble: {
    maxWidth: '80%',
    paddingHorizontal: 15,
    paddingVertical: 10,
    borderRadius: 10,
  },
  userBubble: {
    alignSelf: 'flex-end',
    backgroundColor: '#FFFFFF', // 白色，对应 Python 版本的用户气泡
    borderBottomRightRadius: 2,
  },
  botBubble: {
    alignSelf: 'flex-start',
    backgroundColor: '#88EDFF', // 天依蓝，对应 Python 版本的机器人气泡
    borderBottomLeftRadius: 2,
  },
  bubbleText: {
    fontSize: 16,
    color: '#000000',
  },

  // 图片气泡样式
  imageBubbleContainer: {
    paddingHorizontal: 10,
    paddingVertical: 5,
  },
  imageWrapperUser: {
    alignSelf: 'flex-end',
    maxWidth: '80%',
  },
  imageWrapperBot: {
    alignSelf: 'flex-start',
    maxWidth: '80%',
  },
  chatImage: {
    borderRadius: 10,
  },
});

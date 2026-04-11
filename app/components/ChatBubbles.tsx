import React from 'react';
import { Image, ImageSourcePropType, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { CachedImage } from './CachedImage';
import { ChatMessage } from '../types/chat';

interface MessageItemProps {
  message: ChatMessage;
  onToggleAgentAudio?: (uuid: string) => void;
}

function userStatusIcon(status?: ChatMessage['sendStatus']): ImageSourcePropType | null {
  if (status === 'failed') return require('../assets/images/failed_msg.png');
  if (status === 'waiting') return require('../assets/images/waiting_msg.png');
  return null;
}

function agentAudioIcon(playState?: ChatMessage['audioPlayState']): ImageSourcePropType {
  if (playState === 'playing') return require('../assets/images/stop_agent_msg.png');
  return require('../assets/images/play_agent_msg.png');
}

// 文本气泡组件
export const ChatBubble: React.FC<MessageItemProps> = ({ message, onToggleAgentAudio }) => {
  const { content, isUser, sendStatus, audioPlayState, uuid } = message;
  const statusIcon = userStatusIcon(sendStatus);
  const showPlayButton = !isUser && message.audioAvailable; // 只有机器人消息且有音频时才显示播放按钮
  return (
    <View style={[styles.rowContainer, isUser ? styles.rowUser : styles.rowBot]}>
      {isUser ? (
        <View style={[styles.statusSlot, styles.userStatusSlot]}>
          {!!statusIcon && <Image source={statusIcon} style={styles.statusIcon} resizeMode="contain" />}
        </View>
      ) : null}

      <View
        style={[
          styles.bubble,
          isUser ? styles.userBubble : styles.botBubble,
        ]}
      >
        <Text style={styles.bubbleText}>{content}</Text>
      </View>

      {!isUser ? (
        <View style={[styles.statusSlot, styles.agentControlSlot]}>
          {showPlayButton ? (
            <TouchableOpacity
              style={styles.playButton}
              onPress={() => onToggleAgentAudio?.(uuid)}
            >
              <Image source={agentAudioIcon(audioPlayState)} style={styles.playButtonIcon} resizeMode="contain" />
            </TouchableOpacity>
          ) : null}
        </View>
      ) : null}
    </View>
  );
};

// 图片气泡组件
export const ChatImageBubble: React.FC<MessageItemProps> = ({ message }) => {
  const { content, isUser, uuid, sendStatus } = message;
  const statusIcon = userStatusIcon(sendStatus);

  return (
    <View style={[styles.rowContainer, isUser ? styles.rowUser : styles.rowBot]}>
      {isUser ? (
        <View style={[styles.statusSlot, styles.userStatusSlot]}>
          {!!statusIcon && <Image source={statusIcon} style={styles.statusIcon} resizeMode="contain" />}
        </View>
      ) : null}

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

// 统一的消息渲染组件
export const MessageItem: React.FC<MessageItemProps> = ({ message, onToggleAgentAudio }) => {
  if (message.type === 'image') {
    return <ChatImageBubble message={message} onToggleAgentAudio={onToggleAgentAudio} />;
  }
  return <ChatBubble message={message} onToggleAgentAudio={onToggleAgentAudio} />;
};

const styles = StyleSheet.create({
  rowContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 6,
    paddingVertical: 5,
  },
  rowUser: {
    justifyContent: 'flex-end',
  },
  rowBot: {
    justifyContent: 'flex-start',
  },
  statusSlot: {
    width: 32,
    height: 32,
    justifyContent: 'center',
  },
  userStatusSlot: {
    alignItems: 'flex-end',
    marginRight: 4,
  },
  agentControlSlot: {
    alignItems: 'flex-start',
    marginLeft: 4,
  },
  statusIcon: {
    width: 32,
    height: 32,
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
    includeFontPadding: false,
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
  playButton: {
    width: 32,
    height: 32,
    alignItems: 'center',
    justifyContent: 'center',
  },
  playButtonIcon: {
    width: 32,
    height: 32,
  },
});

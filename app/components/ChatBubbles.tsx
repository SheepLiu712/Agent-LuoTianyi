import React from 'react';
import { Image, ImageSourcePropType, Pressable, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { CachedImage } from './CachedImage';
import { ChatMessage } from '../types/chat';
import { AppTheme, THEMES } from '../utils/theme';

interface MessageItemProps {
  message: ChatMessage;
  onToggleAgentAudio?: (uuid: string) => void;
  theme?: AppTheme;
  selectionMode?: boolean;
  selected?: boolean;
  onLongPressMessage?: (uuid: string) => void;
  onToggleSelect?: (uuid: string) => void;
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

// 勾选框组件
const CheckIndicator: React.FC<{ selected: boolean; theme: AppTheme; isUser: boolean }> = ({ selected, theme, isUser }) => {
  return (
    <View style={[styles.checkWrapper, isUser ? styles.checkWrapperUser : styles.checkWrapperBot]}>
      <View
        style={[
          styles.checkBox,
          {
            backgroundColor: selected ? theme.accent : 'transparent',
            borderColor: selected ? theme.accent : theme.border,
          },
        ]}
      >
        {selected ? (
          <Text style={[styles.checkMark, { color: theme.name === 'dark' ? '#0F1419' : '#ffffff' }]}>✓</Text>
        ) : null}
      </View>
    </View>
  );
};

// 文本气泡组件
export const ChatBubble: React.FC<MessageItemProps> = ({
  message,
  onToggleAgentAudio,
  theme = THEMES.light,
  selectionMode = false,
  selected = false,
  onLongPressMessage,
  onToggleSelect,
}) => {
  const { content, isUser, sendStatus, audioPlayState, uuid } = message;
  const statusIcon = userStatusIcon(sendStatus);
  const showPlayButton = !isUser && message.audioAvailable; // 只有机器人消息且有音频时才显示播放按钮

  const handlePress = () => {
    if (selectionMode) {
      onToggleSelect?.(uuid);
    }
  };

  const handleLongPress = () => {
    if (!selectionMode) {
      onLongPressMessage?.(uuid);
    }
  };

  return (
    <Pressable
      onLongPress={handleLongPress}
      onPress={handlePress}
      delayLongPress={400}
    >
      <View style={[styles.rowContainer, isUser ? styles.rowUser : styles.rowBot]}>
        {selectionMode && !isUser ? <CheckIndicator selected={selected} theme={theme} isUser={false} /> : null}

        {isUser ? (
          <View style={[styles.statusSlot, styles.userStatusSlot]}>
            {!selectionMode && !!statusIcon && <Image source={statusIcon} style={styles.statusIcon} resizeMode="contain" />}
          </View>
        ) : null}

        <View
          style={[
            styles.bubble,
            isUser ? styles.userBubble : styles.botBubble,
            { backgroundColor: isUser ? theme.userBubble : theme.botBubble },
            selectionMode && selected && styles.bubbleSelected,
          ]}
        >
          <Text style={[styles.bubbleText, { color: isUser ? theme.userBubbleText : theme.bubbleText }]}>{content}</Text>
        </View>

        {!isUser ? (
          <View style={[styles.statusSlot, styles.agentControlSlot]}>
            {showPlayButton && !selectionMode ? (
              <TouchableOpacity
                style={styles.playButton}
                onPress={() => onToggleAgentAudio?.(uuid)}
              >
                <Image source={agentAudioIcon(audioPlayState)} style={styles.playButtonIcon} resizeMode="contain" />
              </TouchableOpacity>
            ) : null}
          </View>
        ) : null}

        {selectionMode && isUser ? <CheckIndicator selected={selected} theme={theme} isUser={true} /> : null}
      </View>
    </Pressable>
  );
};

// 图片气泡组件
export const ChatImageBubble: React.FC<MessageItemProps> = ({
  message,
  theme = THEMES.light,
  selectionMode = false,
  selected = false,
  onLongPressMessage,
  onToggleSelect,
}) => {
  const { content, isUser, uuid, sendStatus } = message;
  const statusIcon = userStatusIcon(sendStatus);

  const handlePress = () => {
    if (selectionMode) {
      onToggleSelect?.(uuid);
    }
  };

  const handleLongPress = () => {
    if (!selectionMode) {
      onLongPressMessage?.(uuid);
    }
  };

  return (
    <Pressable onLongPress={handleLongPress} onPress={handlePress} delayLongPress={400}>
      <View style={[styles.rowContainer, isUser ? styles.rowUser : styles.rowBot]}>
        {selectionMode && !isUser ? <CheckIndicator selected={selected} theme={theme} isUser={false} /> : null}

        {isUser ? (
          <View style={[styles.statusSlot, styles.userStatusSlot]}>
            {!selectionMode && !!statusIcon && <Image source={statusIcon} style={styles.statusIcon} resizeMode="contain" />}
          </View>
        ) : null}

        <View
          style={[
            isUser ? styles.imageWrapperUser : styles.imageWrapperBot,
            selectionMode && selected && styles.bubbleSelected,
          ]}
        >
          <CachedImage
            message_id={uuid}
            localUri={content}
            style={styles.chatImage}
            maxHeight={200}
            maxWidth={200}
          />
        </View>

        {selectionMode && isUser ? <CheckIndicator selected={selected} theme={theme} isUser={true} /> : null}
      </View>
    </Pressable>
  );
};

// 统一的消息渲染组件
export const MessageItem: React.FC<MessageItemProps> = ({
  message,
  onToggleAgentAudio,
  theme = THEMES.light,
  selectionMode = false,
  selected = false,
  onLongPressMessage,
  onToggleSelect,
}) => {
  if (message.type === 'image') {
    return (
      <ChatImageBubble
        message={message}
        onToggleAgentAudio={onToggleAgentAudio}
        theme={theme}
        selectionMode={selectionMode}
        selected={selected}
        onLongPressMessage={onLongPressMessage}
        onToggleSelect={onToggleSelect}
      />
    );
  }
  return (
    <ChatBubble
      message={message}
      onToggleAgentAudio={onToggleAgentAudio}
      theme={theme}
      selectionMode={selectionMode}
      selected={selected}
      onLongPressMessage={onLongPressMessage}
      onToggleSelect={onToggleSelect}
    />
  );
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
  checkWrapper: {
    width: 28,
    height: 28,
    justifyContent: 'center',
    alignItems: 'center',
    marginHorizontal: 2,
  },
  checkWrapperUser: {
    marginLeft: 4,
    marginRight: 2,
    alignItems: 'flex-end',
    alignSelf: 'center',
  },
  checkWrapperBot: {
    marginLeft: 4,
    marginRight: 2,
    alignItems: 'flex-start',
  },
  checkBox: {
    width: 22,
    height: 22,
    borderRadius: 11,
    borderWidth: 1.5,
    alignItems: 'center',
    justifyContent: 'center',
  },
  checkMark: {
    fontSize: 14,
    fontWeight: '900',
  },
  bubbleSelected: {
    opacity: 0.7,
    transform: [{ scale: 0.98 }],
  },
});

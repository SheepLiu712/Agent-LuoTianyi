import React, { useEffect, useRef, useState } from 'react';
import { ActivityIndicator, FlatList, Keyboard, StyleSheet, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import type { AccountSession } from '../account/credentials';
import type { AppTheme } from '../../shared/ui/theme';
import { addDebugTrace } from '../../utils/debug_trace';
import { MessageItem } from './ChatBubbles';
import { VoiceInputBar } from './VoiceInputBar';
import { VoiceRecordingOverlay } from './VoiceRecordingOverlay';
import type { useChatLogic } from './useChatLogic';
import { useHistoryLogic } from './useHistoryLogic';

interface Props {
  chat: ReturnType<typeof useChatLogic>;
  session: AccountSession;
  theme: AppTheme;
  topOffset: number;
}
export function ChatScreen({ chat, session, theme, topOffset }: Props) {
  const { username, token } = session;
  const { inputText, messages, flatListRef, canSend, canSendImage, setInputText, addHistoryMessage,
    handleSendText, handleSendImage, handleToggleAgentAudio, toggleVoicePlayback, retryVoice, voiceInput } = chat;
  const insets = useSafeAreaInsets();
  const [keyboardHeight, setKeyboardHeight] = useState(0);
  const [inputHeight, setInputHeight] = useState(40);
  const { loadHistory, historyLoading } = useHistoryLogic(addHistoryMessage);
  useEffect(() => {
    const showSubscription = Keyboard.addListener('keyboardDidShow', (e) => {
      setKeyboardHeight(e.endCoordinates.height);
    });
    const hideSubscription = Keyboard.addListener('keyboardDidHide', () => {
      setKeyboardHeight(0);
    });

    return () => {
      showSubscription.remove();
      hideSubscription.remove();
    };
  }, []);

  const historyLoadedRef = useRef(false);
  useEffect(() => {
    if (historyLoadedRef.current) {
      return;
    }
    if (username && token) {
      historyLoadedRef.current = true;
      loadHistory(username, token);
    }
  }, [username, token, loadHistory]);

  const renderFooter = () => {
    if (!historyLoading) {
      return null;
    }
    return (
      <View style={{ paddingVertical: 20 }}>
        <ActivityIndicator size="small" color="#999" />
      </View>
    );
  };

  return (
    <>
      <View style={{ flex: 1, marginTop: topOffset, marginBottom: keyboardHeight }}>
        <View style={{ flex: 1 }}>
          <FlatList
            ref={flatListRef}
            data={messages}
            inverted={true}
            renderItem={({ item }) => <MessageItem session={session} message={item} onToggleAgentAudio={handleToggleAgentAudio} onToggleVoicePlayback={toggleVoicePlayback} onRetryVoice={retryVoice} theme={theme} />}
            keyExtractor={(item) => item.uuid}
            onEndReached={() => {
              if (username && token && !historyLoading) {
                loadHistory(username, token);
              }
            }}
            onEndReachedThreshold={0.1}
            onScrollToIndexFailed={(info) => {
              // scrollToIndex 目标未渲染时的兜底：按平均行高估算偏移量，避免闪退
              addDebugTrace('history', 'scrollToIndex failed', {
                index: info.index,
                averageItemLength: info.averageItemLength,
              });
              flatListRef.current?.scrollToOffset({
                offset: info.averageItemLength * info.index,
                animated: false,
              });
            }}
            ListFooterComponent={renderFooter}
            style={[styles.chatList, { backgroundColor: theme.chatList }]}
            contentContainerStyle={styles.chatListContent}
            showsVerticalScrollIndicator={true}
            onScrollBeginDrag={Keyboard.dismiss}
          />
        </View>

        <View
          style={[
            styles.inputContainer,
            { paddingBottom: Math.max(insets.bottom, 10), backgroundColor: theme.inputBar, borderTopColor: theme.inputBorder },
          ]}
        >
          <VoiceInputBar
            mode={voiceInput.mode}
            inputText={inputText}
            inputHeight={inputHeight}
            onInputHeightChange={setInputHeight}
            onInputChange={setInputText}
            onToggleMode={voiceInput.toggleMode}
            onSendText={handleSendText}
            onSendImage={handleSendImage}
            canSend={canSend}
            canSendImage={canSendImage}
            captureState={voiceInput.captureState}
            pressIn={voiceInput.pressIn}
            pressMove={voiceInput.pressMove}
            pressOut={voiceInput.pressOut}
            cancelBySystem={voiceInput.cancelBySystem}
            theme={theme}
          />
        </View>
      </View>

      {voiceInput.captureState === 'Recording' || voiceInput.captureState === 'CancelZone' ? <VoiceRecordingOverlay elapsedMs={voiceInput.elapsedMs} cancelZone={voiceInput.isCancelZone} meter={voiceInput.smoothedMeter} theme={theme} topInset={insets.top} bottomInset={insets.bottom} /> : null}

    </>
  );
}

const styles = StyleSheet.create({
  chatList: {
    flex: 1,
    backgroundColor: '#E8E8E8',
  },
  chatListContent: {
    paddingTop: 10,
    paddingBottom: 10,
  },
  inputContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#f0f0f0',
    padding: 10,
    borderTopWidth: 1,
    borderTopColor: '#ddd',
  },
});

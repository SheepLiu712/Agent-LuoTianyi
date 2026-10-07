import MaterialIcons from '@expo/vector-icons/MaterialIcons';
import React from 'react';
import { GestureResponderEvent, Image, Keyboard, StyleSheet, Text, TextInput, TouchableOpacity, View } from 'react-native';
import { VoiceCaptureState } from '../types/chat';
import { AppTheme, THEMES } from '../utils/theme';

interface Props {
  mode: 'text' | 'voice';
  inputText: string;
  inputHeight: number;
  onInputHeightChange: (height: number) => void;
  onInputChange: (text: string) => void;
  onToggleMode: () => void;
  onSendText: () => void;
  onSendImage: () => void;
  canSend: boolean;
  canSendImage: boolean;
  captureState: VoiceCaptureState;
  pressIn: (event: GestureResponderEvent) => void;
  pressMove: (event: GestureResponderEvent) => void;
  pressOut: () => void;
  cancelBySystem?: (reason: string) => Promise<void>;
  theme?: AppTheme;
}

export function VoiceInputBar({
  mode, inputText, inputHeight, onInputHeightChange, onInputChange, onToggleMode,
  onSendText, onSendImage, canSend, canSendImage, captureState,
  pressIn, pressMove, pressOut, cancelBySystem, theme = THEMES.light,
}: Props) {
  const voice = mode === 'voice';
  const recording = captureState === 'Recording' || captureState === 'CancelZone';
  const canToggle = captureState === 'TextMode' || captureState === 'VoiceReady';
  const imageEnabled = canSendImage && (captureState === 'TextMode' || captureState === 'VoiceReady');
  const toggleMode = () => {
    if (!canToggle) return;
    if (!voice) Keyboard.dismiss();
    onToggleMode();
  };

  return (
    <View style={styles.container}>
      <TouchableOpacity
        accessibilityRole="button"
        accessibilityLabel={voice ? '切换到文字输入' : '切换到语音输入'}
        accessibilityState={{ disabled: !canToggle }}
        style={[styles.modeButton, { backgroundColor: theme.inputBackground, borderColor: theme.border }, !canToggle && styles.disabled]}
        onPress={toggleMode}
        disabled={!canToggle}
        activeOpacity={0.65}
      >
        <MaterialIcons name={voice ? 'keyboard' : 'mic-none'} size={24} color={theme.text} />
      </TouchableOpacity>
      {voice ? (
        <View
          accessibilityLabel="按住说话，上滑取消发送"
          onStartShouldSetResponder={() => captureState === 'VoiceReady'}
          onResponderGrant={pressIn}
          onResponderMove={pressMove}
          onResponderRelease={pressOut}
          onResponderTerminationRequest={() => false}
          onResponderTerminate={() => { void cancelBySystem?.('gesture_interrupted'); }}
          style={[styles.hold, { backgroundColor: captureState === 'CancelZone' ? theme.voiceCancel : recording ? theme.voicePressed : theme.voiceSurface }]}
        >
          <Text style={[styles.holdText, { color: theme.text }]}>
            {captureState === 'Starting' ? '正在启动...' : captureState === 'CancelZone' ? '松开取消' : recording ? '松开发送' : '按住说话'}
          </Text>
        </View>
      ) : (
        <TextInput
          accessibilityLabel="消息输入框"
          style={[styles.input, { backgroundColor: theme.inputBackground, color: theme.inputText, height: Math.min(Math.max(44, inputHeight), 120) }]}
          placeholder="给天依发消息..."
          placeholderTextColor={theme.placeholder}
          value={inputText}
          onChangeText={onInputChange}
          onContentSizeChange={(event) => onInputHeightChange(event.nativeEvent.contentSize.height)}
          multiline
        />
      )}
      <TouchableOpacity accessibilityRole="button" accessibilityLabel="发送图片" style={styles.button} onPress={onSendImage} disabled={!imageEnabled}>
        <Image source={imageEnabled ? require('../assets/images/image_button_activate.png') : require('../assets/images/image_button_un.png')} style={styles.icon} />
      </TouchableOpacity>
      {!voice && (
        <TouchableOpacity accessibilityRole="button" accessibilityLabel="发送文字" style={styles.button} onPress={onSendText} disabled={!canSend}>
          <Image source={canSend ? require('../assets/images/send_button_activate.png') : require('../assets/images/send_button_un.png')} style={styles.icon} />
        </TouchableOpacity>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, flexDirection: 'row', alignItems: 'center', gap: 8 },
  modeButton: { width: 44, height: 44, borderRadius: 22, borderWidth: 1, alignItems: 'center', justifyContent: 'center' },
  disabled: { opacity: 0.45 },
  button: { width: 40, height: 44, alignItems: 'center', justifyContent: 'center' },
  icon: { width: 30, height: 30 },
  input: { flex: 1, minWidth: 0, borderRadius: 20, paddingHorizontal: 15, paddingVertical: 10, textAlignVertical: 'top' },
  hold: { flex: 1, minWidth: 0, minHeight: 44, borderRadius: 20, alignItems: 'center', justifyContent: 'center' },
  holdText: { fontSize: 15, fontWeight: '500' },
});

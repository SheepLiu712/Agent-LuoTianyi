import React from 'react';
import { act, create, ReactTestRenderer } from 'react-test-renderer';
import { Keyboard } from 'react-native';

import { VoiceInputBar } from '../components/VoiceInputBar';
import { useVoiceInput } from '../hooks/useVoiceInput';

jest.mock('react-native', () => ({
  Image: 'Image', Text: 'Text', TextInput: 'TextInput', TouchableOpacity: 'TouchableOpacity', View: 'View',
  StyleSheet: { create: (styles: unknown) => styles },
  Keyboard: { dismiss: jest.fn() },
  AppState: { addEventListener: jest.fn(() => ({ remove: jest.fn() })) },
}));
jest.mock('@expo/vector-icons/MaterialIcons', () => 'MaterialIcons');
jest.mock('expo-haptics', () => ({ impactAsync: jest.fn(), ImpactFeedbackStyle: { Medium: 'medium' } }));
jest.mock('../utils/voice_recorder', () => ({ voiceRecorder: { dispose: jest.fn() } }));

function Composer() {
  const [draft, setDraft] = React.useState('未发送的草稿');
  const voice = useVoiceInput({
    onRecordingStarted: jest.fn(), onRecordingCancelled: jest.fn(), onRecordingCommitted: jest.fn(),
    onStopAllAudio: jest.fn(), onNotice: jest.fn(),
  });
  return <VoiceInputBar {...voice} inputText={draft} onInputChange={setDraft}
    inputHeight={44} onInputHeightChange={jest.fn()} onToggleMode={voice.toggleMode}
    onSendText={jest.fn()} onSendImage={jest.fn()} canSend canSendImage />;
}

it('switches via the left mode control with the real capture hook, dismisses keyboard and preserves draft', async () => {
  let tree!: ReactTestRenderer;
  await act(async () => { tree = create(<Composer />); });
  const control = (label: string) => tree.root.findAllByProps({ accessibilityLabel: label })[0];
  expect(control('切换到语音输入')).toBeDefined();
  await act(async () => { control('消息输入框').props.onChangeText('保留这段文字'); });
  await act(async () => { control('切换到语音输入').props.onPress(); });
  expect(Keyboard.dismiss).toHaveBeenCalledTimes(1);
  expect(tree.root.findAllByProps({ accessibilityLabel: '消息输入框' })).toHaveLength(0);
  expect(tree.root.findAllByProps({ accessibilityLabel: '发送文字' })).toHaveLength(0);
  expect(control('发送图片').props.disabled).toBe(false);
  expect(control('按住说话，上滑取消发送').props.onStartShouldSetResponder()).toBe(true);
  await act(async () => { control('切换到文字输入').props.onPress(); });
  expect(control('消息输入框').props.value).toBe('保留这段文字');
  expect(control('发送文字')).toBeDefined();
  await act(async () => { tree.unmount(); });
});

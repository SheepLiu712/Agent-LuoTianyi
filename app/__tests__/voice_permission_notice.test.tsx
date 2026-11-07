import React from 'react';
import { act, create } from 'react-test-renderer';
import { Modal, Pressable, Text } from 'react-native';
import { VoicePermissionNotice } from '../components/VoicePermissionNotice';
import { useMicrophonePermission } from '../hooks/useMicrophonePermission';
import { THEMES } from '../utils/theme';
import { permissionMessages } from '../utils/voice_permission';
import type { VoiceRecorderApi } from '../utils/voice_recorder';

jest.mock('react-native', () => ({
  AppState: { currentState: 'active' },
  Modal: 'Modal', Pressable: 'Pressable', Text: 'Text', View: 'View',
  StyleSheet: { create: (styles: unknown) => styles },
}));

it('lets the user dismiss a waiting notice, see it on another press and clears it when Android grants permission', async () => {
  let finish!: (value: 'granted') => void;
  const recorder: VoiceRecorderApi = {
    getPermission: jest.fn().mockResolvedValue('denied'),
    requestPermission: jest.fn(() => new Promise(resolve => { finish = resolve; })),
    start: jest.fn(), stop: jest.fn(), cancel: jest.fn(), dispose: jest.fn(),
  };
  let permission!: ReturnType<typeof useMicrophonePermission>;
  function Probe() {
    permission = useMicrophonePermission(recorder);
    return permission.permissionNotice ? <VoicePermissionNotice notice={permission.permissionNotice}
      top={32} theme={THEMES.light} onDismiss={permission.dismissPermissionNotice}
      onOpenSettings={permission.openPermissionSettings} /> : null;
  }
  let tree!: ReturnType<typeof create>;
  act(() => { tree = create(<Probe />); });
  const press = () => act(async () => { await permission.checkPermission(); });
  await press();
  await press();
  expect(tree.root.findAllByType(Modal)).toHaveLength(0);
  expect(tree.root.findAllByType(Text).map((node) => node.props.children)).toContain(permissionMessages.waiting);
  act(() => tree.root.findByProps({ accessibilityLabel: '关闭麦克风提示' }).props.onPress());
  expect(tree.toJSON()).toBeNull();
  await press();
  expect(tree.root.findByProps({ accessibilityLabel: '关闭麦克风提示' })).toBeDefined();
  await act(async () => { finish('granted'); });
  expect(tree.toJSON()).toBeNull();
  expect(recorder.requestPermission).toHaveBeenCalledTimes(1);
  act(() => tree.unmount());
});

it('shows a two-choice settings dialog and treats Android back like cancel', () => {
  const notice = { settings: true, message: permissionMessages.settings };
  const onDismiss = jest.fn();
  const onOpenSettings = jest.fn();
  let tree!: ReturnType<typeof create>;
  act(() => {
    tree = create(<VoicePermissionNotice notice={notice} top={32} theme={THEMES.dark}
      onDismiss={onDismiss} onOpenSettings={onOpenSettings} />);
  });
  const buttons = tree.root.findAllByType(Pressable);
  expect(buttons.map((button) => button.findByType(Text).props.children)).toEqual(['取消', '去设置']);
  act(() => tree.root.findByType(Modal).props.onRequestClose());
  act(() => buttons[0].props.onPress());
  expect(onDismiss.mock.calls).toEqual([[notice], [notice]]);
  expect(onOpenSettings).not.toHaveBeenCalled();
  act(() => buttons[1].props.onPress());
  expect(onOpenSettings).toHaveBeenCalledWith(notice);
  act(() => tree.unmount());
});

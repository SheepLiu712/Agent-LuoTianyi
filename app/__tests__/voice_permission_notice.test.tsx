import { AppNotices, usePageNotices } from '../shell/notices/AppNotices';
jest.mock('react-native-safe-area-context', () => ({ useSafeAreaInsets: () => ({ top: 0, bottom: 0 }) }));
import React from 'react';
import { act, create } from 'react-test-renderer';
import { Modal, Pressable, Text } from 'react-native';
import { VoicePermissionNotice } from '../features/chat/VoicePermissionNotice';
import { useMicrophonePermission } from '../features/chat/useMicrophonePermission';
import { THEMES } from '../shared/ui/theme';
import { permissionMessages } from '../features/chat/voice_permission';
import type { VoiceRecorderApi } from '../features/chat/voice_recorder';

jest.mock('react-native', () => ({
  Platform: { OS: 'android' }, AppState: { currentState: 'active' },
  Modal: 'Modal', useWindowDimensions: () => ({ width: 390, fontScale: 1 }), KeyboardAvoidingView: 'KeyboardAvoidingView', ScrollView: 'ScrollView', Pressable: 'Pressable', Text: 'Text', View: 'View',
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
    const show = usePageNotices('chat');
    permission = useMicrophonePermission(recorder);
    return permission.permissionNotice ? <VoicePermissionNotice notice={permission.permissionNotice}
      show={show} theme={THEMES.light} onDismiss={permission.dismissPermissionNotice}
      onOpenSettings={permission.openPermissionSettings} /> : null;
  }
  let tree!: ReturnType<typeof create>;
  act(() => { tree = create(<AppNotices><Probe /></AppNotices>); });
  const press = () => act(async () => { await permission.checkPermission(); });
  await press();
  await press();
  expect(tree.root.findAllByType(Modal)).toHaveLength(0);
  expect(tree.root.findAllByType(Text).map((node) => node.props.children)).toContain(permissionMessages.waiting);
  act(() => tree.root.findByProps({ accessibilityLabel: '关闭麦克风提示' }).props.onPress());
  expect(tree.root.findAllByType(Pressable)).toHaveLength(0);
  await press();
  expect(tree.root.findByProps({ accessibilityLabel: '关闭麦克风提示' })).toBeDefined();
  await act(async () => { finish('granted'); });
  expect(tree.root.findAllByType(Pressable)).toHaveLength(0);
  expect(recorder.requestPermission).toHaveBeenCalledTimes(1);
  act(() => tree.unmount());
});

it('shows a two-choice settings dialog and treats Android back like cancel', () => {
  const notice = { settings: true, message: permissionMessages.settings };
  const onDismiss = jest.fn();
  const onOpenSettings = jest.fn();
  let tree!: ReturnType<typeof create>;
  function Probe() {
    const show = usePageNotices('chat');
    return <VoicePermissionNotice notice={notice} theme={THEMES.dark} show={show}
      onDismiss={onDismiss} onOpenSettings={onOpenSettings} />;
  }
  act(() => { tree = create(<AppNotices><Probe /></AppNotices>); });
  const buttons = tree.root.findAllByType(Pressable);
  expect(buttons.map((button) => button.findByType(Text).props.children)).toEqual(['取消', '去设置']);
  act(() => tree.root.findByType(Modal).props.onRequestClose());

  expect(onDismiss.mock.calls).toEqual([[notice]]);
  expect(onOpenSettings).not.toHaveBeenCalled();
  act(() => tree.unmount());
  act(() => { tree = create(<AppNotices><Probe /></AppNotices>); });
  act(() => tree.root.findAllByType(Pressable)[1].props.onPress());
  expect(onOpenSettings).toHaveBeenCalledWith(notice);
  act(() => tree.unmount());
});

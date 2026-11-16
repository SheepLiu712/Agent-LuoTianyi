import React from 'react';
import { act, create, type ReactTestRenderer } from 'react-test-renderer';
import { Modal, Pressable, Text } from 'react-native';
import { AppNotices, usePageNotices } from '../shell/notices/AppNotices';
import { THEMES } from '../shared/ui/theme';

jest.mock('react-native-safe-area-context', () => ({ useSafeAreaInsets: () => ({ top: 0, bottom: 0 }) }));
jest.mock('react-native', () => ({
  useWindowDimensions: () => ({ width: 390, fontScale: 1 }), Platform: { OS: 'android' },
  KeyboardAvoidingView: 'KeyboardAvoidingView', View: 'View', ScrollView: 'ScrollView',
  Modal: 'Modal', Pressable: 'Pressable', Text: 'Text', StyleSheet: {},
}));

it('阻挡提示依次插队；切页清除原页提示，旧的关闭动作不能影响后一页', () => {
  let show!: ReturnType<typeof usePageNotices>;
  let root!: ReactTestRenderer;
  function Screen({ page }: { page: string }) { show = usePageNotices(page); return null; }
  const render = (page: string) => <AppNotices><Screen page={page} /></AppNotices>;
  act(() => { root = create(render('聊天')); });
  const shown = () => root.root.findAllByType(Text).map(node => node.props.children);
  const publish = (message: string, blocking = false) => show({ message, blocking, theme: THEMES.light });
  let closeA!: () => void;
  let closeB!: () => void;
  act(() => { closeA = publish('A'); closeB = publish('B'); publish('C', true); publish('D', true); });
  expect(shown()).toContain('C');
  const closeC = root.root.findByType(Pressable).props.onPress;
  act(() => { closeC(); closeC(); });
  expect(shown()).toContain('D');
  act(() => root.root.findByType(Modal).props.onRequestClose());
  expect(shown()).toContain('A');
  act(closeA);
  expect(shown()).toContain('B');
  act(() => {
    show({ message: '应用提示', scope: 'app', theme: THEMES.light });
    publish('暂时阻挡', true);
  });
  const stale = show;
  act(() => root.update(render('动态')));
  expect(shown()).toContain('应用提示');
  act(() => { closeB(); stale({ message: '过期结果', theme: THEMES.light }); publish('新结果'); });
  act(() => root.root.findByType(Pressable).props.onPress());
  expect(shown()).toContain('新结果');
  act(() => root.unmount());
});

it.each([
  { twoButtons: true, direction: 'column' },
  { twoButtons: false, direction: 'row' },
])('显式窄条在双按钮时使用卡片，在单按钮时保留横排：$twoButtons', ({ twoButtons, direction }) => {
  function Page() {
    const show = usePageNotices('聊天');
    React.useEffect(() => show({
      message: '继续操作？', theme: THEMES.light, layout: 'banner',
      primary: { label: '继续' }, cancel: twoButtons ? { label: '取消' } : undefined,
    }), [show]);
    return null;
  }
  let root!: ReactTestRenderer;
  act(() => { root = create(<AppNotices><Page /></AppNotices>); });
  const card = root.root.findByProps({ accessibilityRole: 'alert' });
  expect(card.props.style.flexDirection).toBe(direction);
  expect(root.root.findAllByType(Pressable).map(button => button.findByType(Text).props.children))
    .toEqual(twoButtons ? ['取消', '继续'] : ['继续']);
  act(() => root.unmount());
});

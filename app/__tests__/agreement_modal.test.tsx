import React, { ElementType } from 'react';
import { act, create, ReactTestInstance, ReactTestRenderer } from 'react-test-renderer';
import { AgreementModal } from '../features/account/AgreementModal';
import { THEMES } from '../shared/ui/theme';

let appStateListener: ((state: string) => void) | undefined;

jest.mock('react-native-safe-area-context', () => ({
  useSafeAreaInsets: () => ({ top: 24, bottom: 16, left: 0, right: 0 }),
}));


jest.mock('react-native', () => ({
  ActivityIndicator: 'ActivityIndicator',
  Platform: { OS: 'ios' },
  AppState: {
    currentState: 'active',
    addEventListener: jest.fn((_event: string, listener: (state: string) => void) => {
      appStateListener = listener;
      return { remove: jest.fn() };
    }),
  },
  Modal: 'Modal',
  ScrollView: 'ScrollView',
  StyleSheet: { create: (styles: unknown) => styles },
  Text: 'Text',
  TouchableOpacity: 'TouchableOpacity',
  View: 'View',
}));

const agreement = {
  version: 'v1',
  title: '用户协议',
  format: 'agreement.richtext.v1' as const,
  blocks: [{ runs: [{ text: '正文' }] }],
};
const VIEW = 'View' as unknown as ElementType;
const TEXT = 'Text' as unknown as ElementType;
const TOUCHABLE = 'TouchableOpacity' as unknown as ElementType;
const SCROLL = 'ScrollView' as unknown as ElementType;
const MODAL = 'Modal' as unknown as ElementType;

function button(tree: ReactTestRenderer, label: string): ReactTestInstance {
  const result = tree.root.findAllByType(TOUCHABLE).find((item) => item.findAll((child) => child.props.children === label).length > 0);
  if (!result) throw new Error(`missing button ${label}`);
  return result;
}

function renderModal(onSubmit = jest.fn().mockResolvedValue({ success: true }), onCancel = jest.fn()) {
  return create(
    <AgreementModal
      visible
      agreement={agreement}
      loading={false}
      theme={THEMES.light}
      onRetry={jest.fn()}
      onSubmit={onSubmit}
      onCancel={onCancel}
    />,
  );
}

function markShortDocument(tree: ReactTestRenderer) {
  const reader = tree.root.findAllByType(VIEW).find((item) => item.props.onLayout);
  const scroll = tree.root.findByType(SCROLL);
  act(() => reader?.props.onLayout({ nativeEvent: { layout: { height: 300 } } }));
  act(() => scroll.props.onContentSizeChange(100, 100));
}

async function advance(ms: number) {
  await act(async () => {
    jest.advanceTimersByTime(ms);
  });
}

describe('AgreementModal 真实组件行为', () => {
  beforeEach(() => {
    jest.useFakeTimers();
    jest.setSystemTime(0);
    appStateListener = undefined;
  });

  afterEach(() => jest.useRealTimers());

  it('短正文自动到底，累计五秒后允许提交', async () => {
    const submit = jest.fn().mockResolvedValue({ success: true });
    let tree!: ReactTestRenderer;
    act(() => { tree = renderModal(submit); });
    const reader = tree.root.findAllByType(VIEW).find((item) => item.props.onLayout);
    const scroll = tree.root.findByType(SCROLL);
    act(() => reader?.props.onLayout({ nativeEvent: { layout: { height: 300 } } }));
    act(() => scroll.props.onContentSizeChange(100, 100));
    expect(button(tree, '我已阅读并同意用户协议').props.disabled).toBe(true);
    await advance(5250);
    expect(button(tree, '我已阅读并同意用户协议').props.disabled).toBe(false);
    act(() => { void button(tree, '我已阅读并同意用户协议').props.onPress(); });
    expect(submit).toHaveBeenCalledTimes(1);
  });

  it('下载重试成功且容器尺寸不变时，短正文无需额外滚动', async () => {
    let tree!: ReactTestRenderer;
    const props = { visible: true, theme: THEMES.light, onRetry: jest.fn(), onSubmit: jest.fn(), onCancel: jest.fn() };
    act(() => { tree = create(<AgreementModal {...props} agreement={null} loading={false} error="加载失败" />); });
    const reader = tree.root.findAllByType(VIEW).find(item => item.props.onLayout);
    act(() => reader?.props.onLayout({ nativeEvent: { layout: { height: 300 } } }));
    act(() => { tree.update(<AgreementModal {...props} agreement={agreement} loading={false} />); });
    act(() => tree.root.findByType(SCROLL).props.onContentSizeChange(100, 100));
    await advance(5000);
    expect(button(tree, '我已阅读并同意用户协议').props.disabled).toBe(false);
    act(() => tree.unmount());
  });

  it('未到底时即使前台满五秒也不能提交', async () => {
    const submit = jest.fn().mockResolvedValue({ success: true });
    let tree!: ReactTestRenderer;
    act(() => { tree = renderModal(submit); });
    const reader = tree.root.findAllByType(VIEW).find((item) => item.props.onLayout);
    const scroll = tree.root.findByType(SCROLL);
    act(() => reader?.props.onLayout({ nativeEvent: { layout: { height: 100 } } }));
    act(() => scroll.props.onContentSizeChange(100, 400));
    await advance(5250);
    expect(button(tree, '我已阅读并同意用户协议').props.disabled).toBe(true);
    await act(async () => button(tree, '我已阅读并同意用户协议').props.onPress());
    expect(submit).not.toHaveBeenCalled();
  });

  it('切后台先结算前台片段，后台十秒不计时，回来仍需三秒', async () => {
    let tree!: ReactTestRenderer;
    act(() => { tree = renderModal(); });
    markShortDocument(tree);
    await advance(2000);
    act(() => appStateListener?.('background'));
    await advance(10000);
    act(() => appStateListener?.('active'));
    await advance(2750);
    expect(button(tree, '我已阅读并同意用户协议').props.disabled).toBe(true);
    await advance(500);
    expect(button(tree, '我已阅读并同意用户协议').props.disabled).toBe(false);
  });

  it('隐藏再打开或协议换版都会重置阅读状态', async () => {
    const onSubmit = jest.fn().mockResolvedValue({ success: false, code: 'AGREEMENT_CHANGED', agreement: { ...agreement, version: 'v2' } });
    let tree!: ReactTestRenderer;
    act(() => { tree = renderModal(onSubmit); });
    await advance(5250);
    await act(async () => button(tree, '我已阅读并同意用户协议').props.onPress());
    expect(button(tree, '我已阅读并同意用户协议').props.disabled).toBe(true);
    tree.update(<AgreementModal visible={false} agreement={agreement} loading={false} theme={THEMES.light} onRetry={jest.fn()} onSubmit={onSubmit} onCancel={jest.fn()} />);
    tree.update(<AgreementModal visible agreement={{ ...agreement, version: 'v3' }} loading={false} theme={THEMES.light} onRetry={jest.fn()} onSubmit={onSubmit} onCancel={jest.fn()} />);
    expect(button(tree, '我已阅读并同意用户协议').props.disabled).toBe(true);
  });

  it('换版响应不带正文时使旧阅读失效，下载新版后须重新阅读五秒', async () => {
    const submit = jest.fn().mockResolvedValue({ success: false, code: 'AGREEMENT_CHANGED', message: '用户协议已更新，请重新阅读' });
    let tree!: ReactTestRenderer;
    act(() => { tree = renderModal(submit); });
    markShortDocument(tree);
    await advance(5000);
    await act(async () => button(tree, '我已阅读并同意用户协议').props.onPress());
    expect(button(tree, '我已阅读并同意用户协议').props.disabled).toBe(true);
    expect(button(tree, '重试')).toBeDefined();
    expect(tree.root.findAllByType(SCROLL)).toHaveLength(0);
    await advance(10000);
    await act(async () => button(tree, '我已阅读并同意用户协议').props.onPress());
    expect(submit).toHaveBeenCalledTimes(1);
    act(() => tree.update(<AgreementModal visible agreement={{ ...agreement, version: 'v2' }} loading={false} theme={THEMES.light} onRetry={jest.fn()} onSubmit={submit} onCancel={jest.fn()} />));
    markShortDocument(tree);
    await advance(4750);
    expect(button(tree, '我已阅读并同意用户协议').props.disabled).toBe(true);
    await advance(250);
    expect(button(tree, '我已阅读并同意用户协议').props.disabled).toBe(false);
    // 关闭窗口后服务端允许重新启用历史版本，失效标记不能跨次打开保留。
    act(() => tree.update(<AgreementModal visible={false} agreement={agreement} loading={false} theme={THEMES.light} onRetry={jest.fn()} onSubmit={submit} onCancel={jest.fn()} />));
    act(() => tree.update(<AgreementModal visible agreement={agreement} loading={false} theme={THEMES.light} onRetry={jest.fn()} onSubmit={submit} onCancel={jest.fn()} />));
    markShortDocument(tree);
    expect(button(tree, '我已阅读并同意用户协议').props.disabled).toBe(true);
    await advance(5000);
    expect(button(tree, '我已阅读并同意用户协议').props.disabled).toBe(false);
    act(() => tree.unmount());
  });

  it('提交失败保留阅读状态，提交中阻止按钮与 Android 返回，reject 也恢复操作', async () => {
    let resolve!: (value: { success: boolean }) => void;
    const submit = jest.fn().mockImplementation(() => new Promise((r) => { resolve = r; }));
    const cancel = jest.fn();
    let tree!: ReactTestRenderer;
    act(() => { tree = renderModal(submit, cancel); });
    markShortDocument(tree);
    await advance(5000);
    const confirm = button(tree, '我已阅读并同意用户协议');
    act(() => { void confirm.props.onPress(); });
    expect(confirm.props.disabled).toBe(true);
    act(() => tree.root.findByType(MODAL).props.onRequestClose());
    expect(cancel).not.toHaveBeenCalled();
    await act(async () => {
      resolve({ success: false });
      await Promise.resolve();
    });
    expect(button(tree, '我已阅读并同意用户协议').props.disabled).toBe(false);
    expect(tree.root.findAllByType(TEXT).some(node => node.props.children === '协议提交失败，请重试')).toBe(true);

    const reject = jest.fn().mockRejectedValue(new Error('network'));
    act(() => { tree.update(<AgreementModal visible agreement={agreement} loading={false} theme={THEMES.light} onRetry={jest.fn()} onSubmit={reject} onCancel={cancel} />); });
    await act(async () => button(tree, '我已阅读并同意用户协议').props.onPress());
    expect(button(tree, '我已阅读并同意用户协议').props.disabled).toBe(false);
  });

  it('同一渲染帧内连续点击只提交一次', async () => {
    const submit = jest.fn().mockImplementation(() => new Promise(() => {}));
    let tree!: ReactTestRenderer;
    act(() => { tree = renderModal(submit); });
    markShortDocument(tree);
    await advance(5000);
    const press = button(tree, '我已阅读并同意用户协议').props.onPress;
    act(() => { void press(); void press(); });
    expect(submit).toHaveBeenCalledTimes(1);
    act(() => tree.unmount());
  });

  it('安全区底部留白，遮罩点击不穿透，协议正文仍为只读入口', () => {
    let tree!: ReactTestRenderer;
    act(() => { tree = renderModal(); });
    const modal = tree.root.findByType(MODAL);
    expect(modal.props.transparent).toBe(true);
    const card = tree.root.findAllByType(VIEW).find((item) => item.props.style?.[1]?.paddingBottom !== undefined);
    expect(card).toBeDefined();
    expect(tree.root.findByType(SCROLL)).toBeDefined();
  });
});

describe('协议加载期间的前后台切换', () => {
  beforeEach(() => { jest.useFakeTimers(); jest.setSystemTime(0); });
  afterEach(() => jest.useRealTimers());

  it('后台收到正文后，回到前台仍需阅读完整五秒', async () => {
    let tree!: ReactTestRenderer;
    const props = { visible: true, theme: THEMES.light, onRetry: jest.fn(), onSubmit: jest.fn(), onCancel: jest.fn() };
    act(() => { tree = create(<AgreementModal {...props} agreement={null} loading />); });
    act(() => appStateListener?.('background'));
    act(() => { tree.update(<AgreementModal {...props} agreement={agreement} loading={false} />); });
    markShortDocument(tree);
    await advance(5250);
    act(() => appStateListener?.('active'));
    expect(button(tree, '我已阅读并同意用户协议').props.disabled).toBe(true);
    await advance(4750);
    expect(button(tree, '我已阅读并同意用户协议').props.disabled).toBe(true);
    await advance(250);
    expect(button(tree, '我已阅读并同意用户协议').props.disabled).toBe(false);
    act(() => tree.unmount());
  });

  it('系统时间向前跳变不能跳过阅读倒计时', async () => {
    let tree!: ReactTestRenderer;
    act(() => { tree = renderModal(); });
    markShortDocument(tree);
    await advance(2000);
    jest.setSystemTime(3600000);
    await advance(250);
    expect(button(tree, '我已阅读并同意用户协议').props.disabled).toBe(true);
    await advance(2750);
    expect(button(tree, '我已阅读并同意用户协议').props.disabled).toBe(false);
    act(() => tree.unmount());
  });
});

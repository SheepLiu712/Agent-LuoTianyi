/**
 * UA-1 App 用户协议只读查阅页（issue #295）。
 *
 * 覆盖的行为契约：
 * - 整屏覆盖主界面，并绘制在 Live2D 固定层与抽屉之上
 *   （回归：根节点缺 absoluteFill 时它只是主界面 flex 列的兄弟节点、层级为 0，
 *    会被 Live2D 层与聊天区盖住，只剩中间一条白带）；
 * - 顶栏承载返回与居中标题，正文区左上角另设大标题（排在版本号之前）；
 * - 版本与正文来自 GET /auth/agreement；加载失败可重试；关闭返回原界面；
 * - 只读范围：没有倒计时、同意或拒绝。
 */

import React, { ElementType } from 'react';
import { act, create, ReactTestInstance, ReactTestRenderer } from 'react-test-renderer';

import AgreementScreen from '../app/agreement';
import { fetchCurrentAgreement } from '../hooks/useAuth';
import { THEMES } from '../utils/theme';

jest.mock('react-native', () => ({
  ActivityIndicator: 'ActivityIndicator',
  ScrollView: 'ScrollView',
  StyleSheet: {
    create: (styles: unknown) => styles,
    absoluteFillObject: { position: 'absolute', left: 0, right: 0, top: 0, bottom: 0 },
  },
  Text: 'Text',
  TouchableOpacity: 'TouchableOpacity',
  View: 'View',
}));

jest.mock('react-native-safe-area-context', () => ({
  useSafeAreaInsets: () => ({ top: 24, bottom: 12, left: 0, right: 0 }),
}));

jest.mock('../hooks/useAuth', () => ({ fetchCurrentAgreement: jest.fn() }));

// 与上面 useSafeAreaInsets 的 mock 保持一致。
const INSETS = { top: 24, bottom: 12, left: 0, right: 0 };

// index.tsx 中主界面各层的层级，覆盖层必须高于它们。
const LIVE2D_LAYER_Z_INDEX = 10;
const DRAWER_Z_INDEX = 100;

const PAGE_TITLE = '用户协议';
const TEXT_BACK = '返回';
const TEXT_RETRY = '重试';
const VERSION = 'terms-2026-10-v1';
const VERSION_LABEL = `版本：${VERSION}`;
const BODY_TEXT = '第一条 本协议用于校验查阅页的整屏覆盖。';
const PAYLOAD = {
  version: VERSION,
  title: PAGE_TITLE,
  format: 'blocks-v1',
  blocks: [{ font_size: 16, align: 'left', runs: [{ text: BODY_TEXT }] }],
};

const fetchMock = fetchCurrentAgreement as unknown as jest.Mock;

// react-native 被替换成字符串宿主组件，按名字断言时绕开 ElementType 的类型限制。
const VIEW = 'View' as unknown as ElementType;
const TEXT = 'Text' as unknown as ElementType;
const TOUCHABLE = 'TouchableOpacity' as unknown as ElementType;

function flattenStyle(style: unknown): Record<string, unknown> {
  if (Array.isArray(style)) {
    return style.reduce<Record<string, unknown>>(
      (acc, item) => ({ ...acc, ...flattenStyle(item) }),
      {},
    );
  }
  if (style && typeof style === 'object') {
    return style as Record<string, unknown>;
  }
  return {};
}

function textsOf(instance: ReactTestInstance): string[] {
  return instance
    .findAllByType(TEXT)
    .map((node) => node.props.children)
    .filter((child): child is string => typeof child === 'string');
}

function viewWithText(instance: ReactTestInstance, text: string): ReactTestInstance {
  const node = instance.findAllByType(TEXT).find((child) => child.props.children === text);
  if (!node) {
    throw new Error(`未找到文本“${text}”`);
  }
  return node;
}

function viewsWithText(instance: ReactTestInstance, text: string): ReactTestInstance[] {
  return instance.findAllByType(TEXT).filter((child) => child.props.children === text);
}

function buttonLabeled(tree: ReactTestRenderer, label: string): ReactTestInstance {
  const button = tree.root
    .findAllByType(TOUCHABLE)
    .find((node) => node.findAll((child) => child.props.children === label).length > 0);
  if (!button) {
    throw new Error(`未找到“${label}”按钮`);
  }
  return button;
}

function screenRoot(tree: ReactTestRenderer): ReactTestInstance {
  return tree.root.findAllByType(VIEW)[0];
}

async function renderScreen(onClose: () => void = () => {}) {
  let tree!: ReactTestRenderer;
  await act(async () => {
    tree = create(<AgreementScreen onClose={onClose} theme={THEMES.light} />);
  });
  return tree;
}

describe('用户协议查阅页', () => {
  beforeEach(() => {
    fetchMock.mockReset();
    fetchMock.mockResolvedValue({ success: true, data: PAYLOAD });
  });

  it('整屏覆盖主界面，并压在 Live2D 层与抽屉之上', async () => {
    const tree = await renderScreen();
    const style = flattenStyle(screenRoot(tree).props.style);

    expect(style.position).toBe('absolute');
    expect([style.left, style.right, style.top, style.bottom]).toEqual([0, 0, 0, 0]);
    expect(style.zIndex as number).toBeGreaterThan(LIVE2D_LAYER_Z_INDEX);
    expect(style.zIndex as number).toBeGreaterThan(DRAWER_Z_INDEX);
  });

  it('按系统安全区留出上下内边距', async () => {
    const tree = await renderScreen();
    const style = flattenStyle(screenRoot(tree).props.style);

    expect(style.paddingTop).toBe(INSETS.top);
    expect(style.paddingBottom).toBe(INSETS.bottom);
  });

  it('顶栏承载返回与居中标题，正文区另有一个排在版本号之前的大标题', async () => {
    const tree = await renderScreen();
    const root = screenRoot(tree);
    const headerBar = buttonLabeled(tree, TEXT_BACK).parent as ReactTestInstance;

    expect(textsOf(headerBar)).toEqual([TEXT_BACK, PAGE_TITLE]);

    // 两处标题：顶栏居中标题在前，正文区大标题在后。
    const titles = viewsWithText(root, PAGE_TITLE);
    expect(titles).toHaveLength(2);
    expect(flattenStyle(titles[0].props.style).textAlign).toBe('center');
    expect(flattenStyle(titles[1].props.style).textAlign).not.toBe('center');

    const texts = textsOf(root);
    expect(texts.lastIndexOf(PAGE_TITLE)).toBeLessThan(texts.indexOf(VERSION_LABEL));
  });

  it('正文区大标题比版本号更醒目', async () => {
    const tree = await renderScreen();
    const root = screenRoot(tree);
    const titles = viewsWithText(root, PAGE_TITLE);
    const pageTitleStyle = flattenStyle(titles[titles.length - 1].props.style);
    const versionStyle = flattenStyle(viewWithText(root, VERSION_LABEL).props.style);

    expect(pageTitleStyle.fontSize as number).toBeGreaterThan(versionStyle.fontSize as number);
  });

  it('加载中与加载失败时也保留标题', async () => {
    fetchMock.mockImplementation(() => new Promise(() => {}));
    const loadingTree = await renderScreen();
    expect(textsOf(screenRoot(loadingTree))).toContain(PAGE_TITLE);

    fetchMock.mockReset();
    fetchMock.mockResolvedValue({ success: false, message: '网络错误' });
    const failedTree = await renderScreen();
    expect(textsOf(screenRoot(failedTree))).toContain(PAGE_TITLE);
  });

  it('渲染服务端返回的版本号与正文', async () => {
    const tree = await renderScreen();
    const texts = textsOf(tree.root);

    expect(texts).toContain(VERSION_LABEL);
    expect(texts).toContain(BODY_TEXT);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('加载失败给出重试，重试成功后展示正文', async () => {
    fetchMock.mockReset();
    fetchMock.mockResolvedValueOnce({ success: false, message: '网络错误' });

    const tree = await renderScreen();
    expect(textsOf(tree.root).some((text) => text.includes('加载用户协议失败'))).toBe(true);

    fetchMock.mockResolvedValueOnce({ success: true, data: PAYLOAD });
    await act(async () => {
      buttonLabeled(tree, TEXT_RETRY).props.onPress();
    });

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(textsOf(tree.root)).toContain(VERSION_LABEL);
  });

  it('返回关闭查阅页', async () => {
    const onClose = jest.fn();
    const tree = await renderScreen(onClose);

    await act(async () => {
      buttonLabeled(tree, TEXT_BACK).props.onPress();
    });

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('只读范围：没有倒计时、同意或拒绝', async () => {
    const tree = await renderScreen();

    expect(textsOf(tree.root).filter((text) => /同意|拒绝|倒计时/.test(text))).toEqual([]);
  });
});

/**
 * Android 中文两端对齐组件（issue #313）。
 *
 * 覆盖：
 * - 宽度未知/单行/测量失败时保留系统 justify 占位；
 * - 一遍测量后非末行按字符间隙加 letterSpacing，末行不拉伸；
 * - 粗体 run 原样参与排版；
 * - fontScale 折算、容器宽度变化重新测量；
 * - RichAgreement 对 Android + justify 的行统一启用该路径；center/非 Android 保持原路径。
 *
 * 原生排版效果（右边缘是否真的贴齐）由真机/模拟器验收，属性测试不能替代。
 */

import React, { ElementType } from 'react';
import { act, create, ReactTestInstance, ReactTestRenderer } from 'react-test-renderer';

import { AndroidJustifiedText } from '../components/AndroidJustifiedText';
import { RichAgreement } from '../components/RichAgreement';
import type { AgreementPayload } from '../utils/agreement';
import { THEMES } from '../utils/theme';

const mockWindow = { width: 400, height: 800, fontScale: 1 };

jest.mock('react-native', () => ({
  Platform: { OS: 'android', select: (options: Record<string, unknown>) => options.android },
  ScrollView: 'ScrollView',
  StyleSheet: { create: (styles: unknown) => styles },
  Text: 'Text',
  View: 'View',
  useWindowDimensions: () => mockWindow,
}));

const TEXT = 'Text' as unknown as ElementType;
const RUNS: [string, boolean][] = [
  ['第一条 ', false],
  ['重点', true],
  ['内容。', false],
];
const RUNS_NO_BOLD: [string, boolean][] = [['第一条 重点内容。', false]];

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

function byTestId(tree: ReactTestRenderer, testID: string): ReactTestInstance {
  return tree.root.findByProps({ testID });
}

function allByTestId(tree: ReactTestRenderer, testID: string): ReactTestInstance[] {
  return tree.root.findAllByProps({ testID });
}

function renderComponent(): ReactTestRenderer {
  let tree!: ReactTestRenderer;
  act(() => {
    tree = create(
      <AndroidJustifiedText runs={RUNS} fontSize={16} lineHeight={24} color="#111111" />,
    );
  });
  return tree;
}

function layout(tree: ReactTestRenderer, width: number) {
  act(() => {
    byTestId(tree, 'agreement-justify-root').props.onLayout({
      nativeEvent: { layout: { width } },
    });
  });
}

function emitFirst(
  tree: ReactTestRenderer,
  lines: { text: string; width: number }[],
) {
  act(() => {
    byTestId(tree, 'agreement-justify-measure-first').props.onTextLayout({
      nativeEvent: { lines },
    });
  });
}

function runFirstPass(tree: ReactTestRenderer, width = 100) {
  layout(tree, width);
  emitFirst(tree, [
    { text: '第一条 ', width: 40 },
    { text: '重点内容。', width: 60 },
  ]);
}

beforeEach(() => {
  mockWindow.fontScale = 1;
});

describe('AndroidJustifiedText', () => {
  it('宽度未知时先渲染系统 justify 占位，不启动测量', () => {
    const tree = renderComponent();
    const placeholder = byTestId(tree, 'agreement-justify-placeholder');

    expect(flattenStyle(placeholder.props.style)).toMatchObject({
      fontSize: 16,
      lineHeight: 24,
      color: '#111111',
      textAlign: 'justify',
    });
    expect(allByTestId(tree, 'agreement-justify-measure-first')).toHaveLength(0);
  });

  it('一遍测量后非末行补到容器宽度，末行不拉伸', () => {
    const tree = renderComponent();
    runFirstPass(tree);

    const final = byTestId(tree, 'agreement-justify-final');
    expect(flattenStyle(final.props.style)).toMatchObject({
      width: 102,
      fontSize: 16,
      lineHeight: 24,
      color: '#111111',
      textAlign: 'left',
    });
    expect(allByTestId(tree, 'agreement-justify-measure-first')).toHaveLength(0);

    // 第一行“第一条 ”4 个字符、3 个间隙；(100-40)/3 = 20。
    // 字间距只加在相邻字符之间的间隙：头部 span 为“第一条”，
    // 行尾字符“ ”单独成 span、不追加间距，行宽精确等于容器宽。
    const spaced = final
      .findAllByType(TEXT)
      .filter((node) => flattenStyle(node.props.style).letterSpacing === 20);
    expect(spaced).toHaveLength(1);
    const spacedTexts = spaced[0]
      .findAllByType(TEXT)
      .map((node) => node.props.children)
      .filter((child): child is string => typeof child === 'string');
    expect(spacedTexts).toEqual(['第一条']);
    const wrapSpace = final
      .findAllByType(TEXT)
      .find((node) => node.props.children === ' ');
    expect(wrapSpace).toBeDefined();
    expect(flattenStyle(wrapSpace?.props.style).letterSpacing).toBeUndefined();
  });

  it('粗体 run 保持 bold，并跟着所在行参与排版', () => {
    const tree = renderComponent();
    runFirstPass(tree);
    const final = byTestId(tree, 'agreement-justify-final');

    const bold = final.findAllByType(TEXT).find((node) => node.props.children === '重点');
    expect(bold).toBeDefined();
    expect(flattenStyle(bold?.props.style)).toEqual({ fontWeight: 'bold' });

    // 末行“重点内容。”不拉伸；它包含粗体“重点”和普通“内容。”两个 run。
    const lastLineRuns = final
      .findAllByType(TEXT)
      .filter((node) => node.props.children === '重点' || node.props.children === '内容。');
    expect(lastLineRuns).toHaveLength(2);
    lastLineRuns.forEach((node) => {
      expect(flattenStyle(node.props.style).letterSpacing).toBeUndefined();
    });
  });

  it('文本不变但粗体分布变化时重新测量', () => {
    const tree = renderComponent();
    runFirstPass(tree);
    expect(allByTestId(tree, 'agreement-justify-final')).toHaveLength(1);

    act(() => {
      tree.update(
        <AndroidJustifiedText
          runs={RUNS_NO_BOLD}
          fontSize={16}
          lineHeight={24}
          color="#111111"
        />,
      );
    });

    expect(allByTestId(tree, 'agreement-justify-final')).toHaveLength(0);
    expect(allByTestId(tree, 'agreement-justify-measure-first')).toHaveLength(1);
  });

  it('letterSpacing 按系统字号缩放折算', () => {
    mockWindow.fontScale = 2;
    const tree = renderComponent();
    runFirstPass(tree);

    const final = byTestId(tree, 'agreement-justify-final');
    const spaced = final
      .findAllByType(TEXT)
      .filter((node) => flattenStyle(node.props.style).letterSpacing === 10);
    expect(spaced).toHaveLength(1);
  });

  it('只有一行时不拉伸', () => {
    const tree = renderComponent();
    layout(tree, 100);
    emitFirst(tree, [{ text: '第一条 重点内容。', width: 80 }]);

    expect(allByTestId(tree, 'agreement-justify-final')).toHaveLength(0);
    expect(allByTestId(tree, 'agreement-justify-placeholder')).toHaveLength(1);
  });

  it('第一遍无法映射回原文时回退到系统 justify', () => {
    const tree = renderComponent();
    layout(tree, 100);
    emitFirst(tree, [
      { text: '不存在', width: 50 },
      { text: '内容', width: 50 },
    ]);

    expect(allByTestId(tree, 'agreement-justify-final')).toHaveLength(0);
    expect(allByTestId(tree, 'agreement-justify-placeholder')).toHaveLength(1);
  });

  it('容器宽度变化后重新测量', () => {
    const tree = renderComponent();
    runFirstPass(tree);
    expect(allByTestId(tree, 'agreement-justify-final')).toHaveLength(1);

    layout(tree, 200);

    expect(allByTestId(tree, 'agreement-justify-final')).toHaveLength(0);
    const first = byTestId(tree, 'agreement-justify-measure-first');
    expect(flattenStyle(first.props.style).width).toBe(200);
  });

  it('系统字号变化后重新测量', () => {
    const tree = renderComponent();
    runFirstPass(tree);
    expect(allByTestId(tree, 'agreement-justify-final')).toHaveLength(1);

    act(() => {
      mockWindow.fontScale = 1.4;
      tree.update(
        <AndroidJustifiedText runs={RUNS} fontSize={16} lineHeight={24} color="#111111" />,
      );
    });

    expect(allByTestId(tree, 'agreement-justify-final')).toHaveLength(0);
    expect(allByTestId(tree, 'agreement-justify-measure-first')).toHaveLength(1);
  });

  it('多行结果在同一个 Text 内用换行分隔', () => {
    const tree = renderComponent();
    runFirstPass(tree);
    const final = byTestId(tree, 'agreement-justify-final');

    // 两个显示行由一个换行符分隔；换行是外层 Text 的直接子节点，
    // 保证不因拆行而在行间多出 includeFontPadding。第一行拆出
    // 行尾字符后是两个 span，加上第二行共三个非文本子节点。
    const stringChildren = final.children.filter(
      (child): child is string => typeof child === 'string',
    );
    expect(stringChildren).toEqual(['\n']);
    expect(final.children.filter((child) => typeof child !== 'string')).toHaveLength(3);
  });
});

describe('RichAgreement 的 Android justify 切换', () => {
  const PAYLOAD: AgreementPayload = {
    version: 'terms-2026-10-v1',
    title: '用户协议',
    format: 'agreement.richtext.v1',
    blocks: [
      { font_size: 16, align: 'justify', runs: [{ text: '连续中文段落' }] },
      { font_size: 16, align: 'justify', runs: [{ text: 'English only paragraph' }] },
      { font_size: 16, align: 'center', runs: [{ text: '居中段落' }] },
    ],
  };

  it('Android justify 行统一启用字符级对齐，center 保持原路径', () => {
    let tree!: ReactTestRenderer;
    act(() => {
      tree = create(<RichAgreement data={PAYLOAD} theme={THEMES.light} />);
    });

    // 中文 + 纯英文两个 justify block 都走 AndroidJustifiedText；center 仍走 RN Text。
    expect(allByTestId(tree, 'agreement-justify-root')).toHaveLength(2);
    expect(allByTestId(tree, 'agreement-justify-placeholder')).toHaveLength(2);

    const english = tree.root
      .findAllByType(TEXT)
      .find((node) => node.props.children === 'English only paragraph');
    expect(english).toBeDefined();
    // 英文 run 的父级是 renderRuns 的包裹 Text，再上一层是字符级占位 Text。
    const englishPlaceholder = english?.parent?.parent;
    expect(englishPlaceholder?.props.testID).toBe('agreement-justify-placeholder');
    expect(flattenStyle(englishPlaceholder?.props.style).textAlign).toBe('justify');

    const center = tree.root
      .findAllByType(TEXT)
      .find((node) => node.props.children === '居中段落');
    expect(center).toBeDefined();
    expect(flattenStyle(center?.parent?.props.style).textAlign).toBe('center');
  });
});

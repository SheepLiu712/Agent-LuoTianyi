/**
 * Android 字符级两端对齐组件（issue #313）。
 *
 * 覆盖：
 * - 宽度未知/单行/测量失败时保留系统 justify 占位；
 * - 按需测量：第一遍确定折行；仅当非末行以行尾空格结尾时，第二遍测量裁剪后的
 *   行宽；字间距超过 0.03px 时按 AOSP 关闭连字重测；
 * - 非末行按 AOSP 公式加 letterSpacing，末行不拉伸；
 * - 粗体 run 原样参与排版；
 * - fontScale/屏幕密度折算、容器宽度变化重新测量；
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
const mockDensity = 1;

jest.mock('react-native', () => ({
  PixelRatio: { get: () => mockDensity },
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

function renderComponent(runs: [string, boolean][] = RUNS): ReactTestRenderer {
  let tree!: ReactTestRenderer;
  act(() => {
    tree = create(
      <AndroidJustifiedText runs={runs} fontSize={16} lineHeight={24} color="#111111" />,
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

function emitSecond(
  tree: ReactTestRenderer,
  lines: { text: string; width: number }[],
) {
  act(() => {
    byTestId(tree, 'agreement-justify-measure-second').props.onTextLayout({
      nativeEvent: { lines },
    });
  });
}

function emitThird(
  tree: ReactTestRenderer,
  lines: { text: string; width: number }[],
) {
  act(() => {
    byTestId(tree, 'agreement-justify-measure-third').props.onTextLayout({
      nativeEvent: { lines },
    });
  });
}

// 第一遍：原文“第一条 重点内容。”在 100dp 宽下折成两行，折行空格留在第一行。
// 第二遍：AOSP 会裁掉非末行的行尾空格，因此第一行只测“第一条”的宽度。
// 第三遍：字间距 (100-30)/2 = 35px 远大于 0.03px，按 AOSP 关闭连字后重测。
function runFullPass(tree: ReactTestRenderer, width = 100) {
  layout(tree, width);
  emitFirst(tree, [
    { text: '第一条 ', width: 40 },
    { text: '重点内容。', width: 60 },
  ]);
  emitSecond(tree, [
    { text: '第一条', width: 30 },
    { text: '重点内容。', width: 60 },
  ]);
  emitThird(tree, [
    { text: '第一条', width: 30 },
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

  it('第一遍只确定折行行尾，尚不渲染最终结果', () => {
    const tree = renderComponent();
    layout(tree, 100);
    emitFirst(tree, [
      { text: '第一条 ', width: 40 },
      { text: '重点内容。', width: 60 },
    ]);

    expect(allByTestId(tree, 'agreement-justify-final')).toHaveLength(0);
    expect(allByTestId(tree, 'agreement-justify-placeholder')).toHaveLength(1);
    const second = byTestId(tree, 'agreement-justify-measure-second');
    // 第二遍测量的是裁剪行尾空格后的“第一条”，不是带空格的原始文本。
    expect(second.findAllByType(TEXT).map((node) => node.props.children)).toContain('第一条');
    expect(second.findAllByType(TEXT).map((node) => node.props.children)).not.toContain('第一条 ');
    expect(allByTestId(tree, 'agreement-justify-measure-third')).toHaveLength(0);
  });

  it('第二遍字间距超过 0.03px 时关闭连字重测（AOSP 0.03 分支）', () => {
    const tree = renderComponent();
    layout(tree, 100);
    emitFirst(tree, [
      { text: '第一条 ', width: 40 },
      { text: '重点内容。', width: 60 },
    ]);
    emitSecond(tree, [
      { text: '第一条', width: 30 },
      { text: '重点内容。', width: 60 },
    ]);

    expect(allByTestId(tree, 'agreement-justify-final')).toHaveLength(0);
    const third = byTestId(tree, 'agreement-justify-measure-third');
    // 只有命中阈值的非末行关闭连字；末行不参与 justification。
    const noLigatureLines = third
      .findAllByType(TEXT)
      .filter((node) => {
        const fontVariant = flattenStyle(node.props.style).fontVariant as string[] | undefined;
        return fontVariant?.[0] === 'no-common-ligatures';
      });
    expect(noLigatureLines).toHaveLength(1);
    expect(
      noLigatureLines[0]
        .findAllByType(TEXT)
        .map((node) => node.props.children)
        .filter((child): child is string => typeof child === 'string'),
    ).toEqual(['第一条']);
  });

  it('非末行没有行尾空格时跳过第二遍，直接按第一遍宽度计算', () => {
    const runs: [string, boolean][] = [
      ['甲乙丙丁戊', false],
      ['末行', false],
    ];
    const tree = renderComponent(runs);
    layout(tree, 100);
    emitFirst(tree, [
      { text: '甲乙丙丁戊', width: 50 },
      { text: '末行', width: 20 },
    ]);

    // 第一遍宽度不含行尾空格，已是 AOSP measure(end)；字间距 12.5 > 0.03，
    // 只需再做 AOSP 的 0.03 连字重测，不需要第二遍裁剪测量。
    expect(allByTestId(tree, 'agreement-justify-measure-second')).toHaveLength(0);
    expect(allByTestId(tree, 'agreement-justify-measure-third')).toHaveLength(1);
  });

  it('字间距不超过 0.03px 时不做第三遍，第一遍后直接显示', () => {
    const runs: [string, boolean][] = [
      ['甲乙丙丁戊', false],
      ['末行', false],
    ];
    const tree = renderComponent(runs);
    layout(tree, 100);
    emitFirst(tree, [
      { text: '甲乙丙丁戊', width: 99.9 },
      { text: '末行', width: 20 },
    ]);

    // (100 - 99.9) / 4 = 0.025，不超过 0.03，不进入连字重测。
    expect(allByTestId(tree, 'agreement-justify-measure-second')).toHaveLength(0);
    expect(allByTestId(tree, 'agreement-justify-measure-third')).toHaveLength(0);
    expect(allByTestId(tree, 'agreement-justify-final')).toHaveLength(1);
  });

  it('三遍测量后非末行补到容器宽度，末行不拉伸', () => {
    const tree = renderComponent();
    runFullPass(tree);

    const final = byTestId(tree, 'agreement-justify-final');
    expect(flattenStyle(final.props.style)).toMatchObject({
      // 100 + 最大字间距 35 + 1dp 折行保护
      width: 136,
      fontSize: 16,
      lineHeight: 24,
      color: '#111111',
      textAlign: 'left',
    });
    expect(allByTestId(tree, 'agreement-justify-measure-first')).toHaveLength(0);
    expect(allByTestId(tree, 'agreement-justify-measure-second')).toHaveLength(0);
    expect(allByTestId(tree, 'agreement-justify-measure-third')).toHaveLength(0);

    // 第一行“第一条”3 个字形簇、2 个间隙；(100 - 30) / 2 = 35。
    // AOSP 对整行统一应用 paint letterSpacing，这里同样只包一层行 span。
    const spaced = final
      .findAllByType(TEXT)
      .filter((node) => flattenStyle(node.props.style).letterSpacing === 35);
    expect(spaced).toHaveLength(1);
    const spacedTexts = spaced[0]
      .findAllByType(TEXT)
      .map((node) => node.props.children)
      .filter((child): child is string => typeof child === 'string');
    expect(spacedTexts).toEqual(['第一条']);
  });

  it('按 AOSP 裁掉折行处的行尾空格', () => {
    const tree = renderComponent();
    runFullPass(tree);
    const final = byTestId(tree, 'agreement-justify-final');

    // 原文“第一条 ”在非末行被裁成“第一条”，最终文本里不再出现折行空格。
    expect(
      final.findAllByType(TEXT).filter((node) => node.props.children === '第一条'),
    ).toHaveLength(1);
    expect(
      final.findAllByType(TEXT).filter((node) => node.props.children === ' '),
    ).toHaveLength(0);
  });

  it('粗体 run 保持 bold，并跟着所在行参与排版', () => {
    const tree = renderComponent();
    runFullPass(tree);
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
    runFullPass(tree);
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
    runFullPass(tree);

    // 像素间距仍为 (100-30)/2 = 35；fontScale=2、density=1 时 prop = 17.5。
    const final = byTestId(tree, 'agreement-justify-final');
    const spaced = final
      .findAllByType(TEXT)
      .filter((node) => flattenStyle(node.props.style).letterSpacing === 17.5);
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

  it('第二遍测量行数与第一遍不一致时回退到系统 justify', () => {
    const tree = renderComponent();
    layout(tree, 100);
    emitFirst(tree, [
      { text: '第一条 ', width: 40 },
      { text: '重点内容。', width: 60 },
    ]);
    emitSecond(tree, [{ text: '第一条', width: 30 }]);

    expect(allByTestId(tree, 'agreement-justify-final')).toHaveLength(0);
    expect(allByTestId(tree, 'agreement-justify-placeholder')).toHaveLength(1);
  });

  it('容器宽度变化后重新测量', () => {
    const tree = renderComponent();
    runFullPass(tree);
    expect(allByTestId(tree, 'agreement-justify-final')).toHaveLength(1);

    layout(tree, 200);

    expect(allByTestId(tree, 'agreement-justify-final')).toHaveLength(0);
    const first = byTestId(tree, 'agreement-justify-measure-first');
    expect(flattenStyle(first.props.style).width).toBe(200);
  });

  it('系统字号变化后重新测量', () => {
    const tree = renderComponent();
    runFullPass(tree);
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
    runFullPass(tree);
    const final = byTestId(tree, 'agreement-justify-final');

    // 两个行 span 由一个换行符分隔；换行是外层 Text 的直接子节点，
    // 保证不因拆行而在行间多出 includeFontPadding。
    const stringChildren = final.children.filter(
      (child): child is string => typeof child === 'string',
    );
    expect(stringChildren).toEqual(['\n']);
    expect(final.children.filter((child) => typeof child !== 'string')).toHaveLength(2);
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

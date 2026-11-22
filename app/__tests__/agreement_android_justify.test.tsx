import React, { ElementType } from 'react';
import { Platform } from 'react-native';
import { act, create, ReactTestInstance, ReactTestRenderer } from 'react-test-renderer';

import { AndroidJustifiedText } from '../features/account/AndroidJustifiedText';
import { RichAgreement } from '../features/account/RichAgreement';
import type { AgreementPayload } from '../utils/agreement';
import { THEMES } from '../shared/ui/theme';

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

function flattenStyle(style: unknown): Record<string, unknown> {
  if (Array.isArray(style)) {
    return style.reduce<Record<string, unknown>>(
      (acc, item) => ({ ...acc, ...flattenStyle(item) }), {},
    );
  }
  return style && typeof style === 'object' ? style as Record<string, unknown> : {};
}

function textContent(node: ReactTestInstance | string): string {
  return typeof node === 'string' ? node : node.children.map(textContent).join('');
}

function textWithStyle(node: ReactTestInstance, property: string, value: unknown): string {
  function collect(current: ReactTestInstance | string, inherited: unknown): string {
    if (typeof current === 'string') {
      return inherited === value ? current : '';
    }
    const style = flattenStyle(current.props.style);
    return current.children.map((child) => collect(child, style[property] ?? inherited)).join('');
  }
  return collect(node, undefined);
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

function emitFirst(tree: ReactTestRenderer, lines: { text: string; width: number }[]) {
  act(() => {
    byTestId(tree, 'agreement-justify-measure-first').props.onTextLayout({ nativeEvent: { lines } });
  });
}

function emitSecond(tree: ReactTestRenderer, lines: { text: string; width: number }[]) {
  act(() => {
    byTestId(tree, 'agreement-justify-measure-second').props.onTextLayout({ nativeEvent: { lines } });
  });
}

function runFullPass(tree: ReactTestRenderer) {
  layout(tree, 100);
  emitFirst(tree, [{ text: '第一条 ', width: 40 }, { text: '重点内容。', width: 60 }]);
  emitSecond(tree, [{ text: '第一条\n', width: 30 }, { text: '重点内容。', width: 60 }]);
}

beforeEach(() => {
  mockWindow.fontScale = 1;
  Platform.OS = 'android';
});

describe('AndroidJustifiedText（模拟测量事件，不验证原生绘制）', () => {
  it.each([[1, 35], [2, 17.5]])('fontScale=%s 时按可见宽度计算，保留原文、粗体和统一断行策略', (fontScale, spacing) => {
    mockWindow.fontScale = fontScale;
    const tree = renderComponent();
    const placeholder = byTestId(tree, 'agreement-justify-placeholder');
    expect(textContent(placeholder)).toBe('第一条 重点内容。');
    expect(placeholder.props.textBreakStrategy).toBe('simple');
    expect(flattenStyle(placeholder.props.style)).toMatchObject({
      fontSize: 16, lineHeight: 24, color: '#111111', textAlign: 'justify',
    });
    expect(allByTestId(tree, 'agreement-justify-measure-first')).toHaveLength(0);
    layout(tree, 100);
    expect(byTestId(tree, 'agreement-justify-measure-first').props.textBreakStrategy).toBe('simple');
    emitFirst(tree, [{ text: '第一条 ', width: 40 }, { text: '重点内容。', width: 60 }]);
    const second = byTestId(tree, 'agreement-justify-measure-second');
    expect(second.props.textBreakStrategy).toBe('simple');
    expect(textContent(second)).toBe('第一条\n重点内容。');
    expect(textContent(byTestId(tree, 'agreement-justify-placeholder'))).toBe('第一条 重点内容。');
    expect(allByTestId(tree, 'agreement-justify-final')).toHaveLength(0);
    emitSecond(tree, [{ text: '第一条\n', width: 30 }, { text: '重点内容。', width: 60 }]);
    const final = byTestId(tree, 'agreement-justify-final');
    expect(final.props.textBreakStrategy).toBe('simple');
    expect(textContent(final)).toBe('第一条 重点内容。');
    expect(textWithStyle(final, 'letterSpacing', spacing)).toBe('第一');
    expect(textWithStyle(final, 'letterSpacing', undefined)).toBe('条 重点内容。');
    expect(textWithStyle(final, 'fontWeight', 'bold')).toBe('重点');
    expect(flattenStyle(final.props.style)).toMatchObject({
      fontSize: 16, lineHeight: 24, color: '#111111', textAlign: 'justify', width: 100,
    });
    expect(allByTestId(tree, 'agreement-justify-measure-first')).toHaveLength(0);
    expect(allByTestId(tree, 'agreement-justify-measure-second')).toHaveLength(0);
  });

  it.each([
    ['甲  乙', '甲  ', '甲', '乙', 10, 0],
    ['hello  world', 'hello  ', 'hello', 'world', 50, 12.5],
  ])('最终显示完整保留 %s 的连续空格', (source, first, visible, last, width, spacing) => {
    const tree = renderComponent([[source, false]]);
    layout(tree, 100);
    emitFirst(tree, [{ text: first, width: width + 20 }, { text: last, width: 50 }]);
    emitSecond(tree, [{ text: `${visible}\n`, width }, { text: last, width: 50 }]);
    const displayed = byTestId(tree, spacing > 0 ? 'agreement-justify-final' : 'agreement-justify-placeholder');
    expect(textContent(displayed)).toBe(source);
    expect(textWithStyle(displayed, 'letterSpacing', undefined)).toContain('  ');
    expect(textWithStyle(displayed, 'letterSpacing', spacing || undefined)).toBe(spacing ? 'hell' : source);
  });

  it.each([
    {
      name: '纯英文双空格',
      runs: [['hello  world  office', false]] as [string, boolean][],
      lines: [{ text: 'hello  world  ', width: 95 }, { text: 'office', width: 40 }],
      bold: '',
    },
    {
      name: '混排空格跨粗体片段',
      runs: [['中文 ', false], ['API ', true], [' 重点', false], ['内容', true]] as [string, boolean][],
      lines: [{ text: '中文 API  ', width: 80 }, { text: '重点内容', width: 40 }],
      bold: 'API 内容',
    },
  ])('$name 的非末行有词间空格时保留默认排版', ({ runs, lines, bold }) => {
    const tree = renderComponent(runs);
    layout(tree, 100);
    emitFirst(tree, lines);
    const source = runs.map(([text]) => text).join('');
    const fallback = byTestId(tree, 'agreement-justify-placeholder');
    expect(textContent(fallback)).toBe(source);
    expect(textWithStyle(fallback, 'fontWeight', 'bold')).toBe(bold);
    expect(textWithStyle(fallback, 'letterSpacing', undefined)).toBe(source);
    expect(flattenStyle(fallback.props.style).textAlign).toBe('justify');
    expect(allByTestId(tree, 'agreement-justify-measure-second')).toHaveLength(0);
    expect(allByTestId(tree, 'agreement-justify-final')).toHaveLength(0);
  });

  it('同段只补齐不足宽的中文行，默认英文行、满宽行和带空格末行保持自然排版', () => {
    const runs: [string, boolean][] = [
      ['英文 ', false], ['office ', true], ['甲乙丙丁戊己庚辛末行 API  ', false],
    ];
    const tree = renderComponent(runs);
    layout(tree, 100);
    expect(flattenStyle(byTestId(tree, 'agreement-justify-measure-first').props.style).textAlign).toBe('justify');
    emitFirst(tree, [
      { text: '英文 office ', width: 80 }, { text: '甲乙丙丁', width: 100 },
      { text: '戊己庚辛', width: 64 }, { text: '末行 API  ', width: 60 },
    ]);
    const final = byTestId(tree, 'agreement-justify-final');
    expect(textContent(final)).toBe('英文 office 甲乙丙丁戊己庚辛末行 API  ');
    expect(textWithStyle(final, 'letterSpacing', 12)).toBe('戊己庚');
    expect(textWithStyle(final, 'letterSpacing', undefined)).toBe('英文 office 甲乙丙丁辛末行 API  ');
    expect(textWithStyle(final, 'fontWeight', 'bold')).toBe('office ');
    expect(flattenStyle(final.props.style)).toMatchObject({ textAlign: 'justify', width: 100 });
    expect(allByTestId(tree, 'agreement-justify-measure-second')).toHaveLength(0);
  });

  it('补充平面汉字在最后可见字符处分割后保持完整', () => {
    const tree = renderComponent([['甲𠀀末行', false]]);
    layout(tree, 100);
    emitFirst(tree, [{ text: '甲𠀀', width: 40 }, { text: '末行', width: 40 }]);
    const final = byTestId(tree, 'agreement-justify-final');
    expect(textContent(final)).toBe('甲𠀀末行');
    expect(textWithStyle(final, 'letterSpacing', 60)).toBe('甲');
    expect(textWithStyle(final, 'letterSpacing', undefined)).toBe('𠀀末行');
  });

  it('文本不变但粗体值变化时重新测量', () => {
    const tree = renderComponent();
    runFullPass(tree);
    act(() => {
      tree.update(
        <AndroidJustifiedText runs={[['第一条 重点内容。', false]]} fontSize={16} lineHeight={24} color="#111111" />,
      );
    });
    expect(allByTestId(tree, 'agreement-justify-final')).toHaveLength(0);
    expect(allByTestId(tree, 'agreement-justify-measure-first')).toHaveLength(1);
  });

  it('第一遍无法映射回原文时保留原文占位', () => {
    const tree = renderComponent();
    layout(tree, 100);
    emitFirst(tree, [{ text: '不存在', width: 50 }, { text: '内容', width: 50 }]);
    expect(allByTestId(tree, 'agreement-justify-final')).toHaveLength(0);
    expect(textContent(byTestId(tree, 'agreement-justify-placeholder'))).toBe('第一条 重点内容。');
  });

  it('第二遍测量行数与第一遍不一致时保留原文占位', () => {
    const tree = renderComponent();
    layout(tree, 100);
    emitFirst(tree, [{ text: '第一条 ', width: 40 }, { text: '重点内容。', width: 60 }]);
    emitSecond(tree, [{ text: '第一条', width: 30 }]);
    expect(allByTestId(tree, 'agreement-justify-final')).toHaveLength(0);
    expect(textContent(byTestId(tree, 'agreement-justify-placeholder'))).toBe('第一条 重点内容。');
  });

  it('容器变宽后采用新折行，不沿用原来的两行', () => {
    const tree = renderComponent();
    runFullPass(tree);
    layout(tree, 200);
    expect(allByTestId(tree, 'agreement-justify-final')).toHaveLength(0);
    expect(flattenStyle(byTestId(tree, 'agreement-justify-measure-first').props.style).width).toBe(200);
    emitFirst(tree, [{ text: '第一条 重点内容。', width: 100 }]);
    expect(textContent(byTestId(tree, 'agreement-justify-placeholder'))).toBe('第一条 重点内容。');
  });

  it('系统字号变化后重新判断折行，行内出现分隔空格时回退', () => {
    const tree = renderComponent();
    runFullPass(tree);
    act(() => {
      mockWindow.fontScale = 1.4;
      tree.update(
        <AndroidJustifiedText runs={RUNS} fontSize={16} lineHeight={24} color="#111111" />,
      );
    });
    expect(allByTestId(tree, 'agreement-justify-final')).toHaveLength(0);
    emitFirst(tree, [{ text: '第一条 重点', width: 86 }, { text: '内容。', width: 42 }]);
    const fallback = byTestId(tree, 'agreement-justify-placeholder');
    expect(textContent(fallback)).toBe('第一条 重点内容。');
    expect(textWithStyle(fallback, 'fontWeight', 'bold')).toBe('重点');
    expect(allByTestId(tree, 'agreement-justify-final')).toHaveLength(0);
  });

  it('自然折行的非末行无需补宽时保持默认排版，不重建正文', () => {
    const tree = renderComponent([['甲乙丙丁末行', false]]);
    layout(tree, 64);
    emitFirst(tree, [{ text: '甲乙丙丁', width: 64 }, { text: '末行', width: 32 }]);
    expect(textContent(byTestId(tree, 'agreement-justify-placeholder'))).toBe('甲乙丙丁末行');
    expect(allByTestId(tree, 'agreement-justify-final')).toHaveLength(0);
    expect(allByTestId(tree, 'agreement-justify-measure-second')).toHaveLength(0);
  });

  it('不能把包含行尾空格的满行宽误判为可见文字已无需补宽', () => {
    const tree = renderComponent();
    layout(tree, 100);
    emitFirst(tree, [{ text: '第一条 ', width: 100 }, { text: '重点内容。', width: 60 }]);
    emitSecond(tree, [{ text: '第一条\n', width: 90 }, { text: '重点内容。', width: 60 }]);
    const final = byTestId(tree, 'agreement-justify-final');
    expect(textWithStyle(final, 'letterSpacing', 5)).toBe('第一');
    expect(textContent(final)).toBe('第一条 重点内容。');
  });

  it('已复现的连字候选词混排样例直接回退，保留原文和粗体', () => {
    const runs: [string, boolean][] = [
      ['中英文 ', false], ['office efficient affinity ', true],
      ['术语跨行验证，原有粗体边界应保留，自动折行非末行需要左右贴齐，末行不拉伸。', false],
    ];
    const tree = renderComponent(runs);
    layout(tree, 320);
    emitFirst(tree, [
      { text: '中英文 office efficient affinity 术语跨行验', width: 294.6666564941406 },
      { text: '证，原有粗体边界应保留，自动折行非末行需', width: 320 },
      { text: '要左右贴齐，末行不拉伸。', width: 192 },
    ]);
    const fallback = byTestId(tree, 'agreement-justify-placeholder');
    expect(textContent(fallback)).toBe(runs.map(([text]) => text).join(''));
    expect(textWithStyle(fallback, 'fontWeight', 'bold')).toBe('office efficient affinity ');
    expect(allByTestId(tree, 'agreement-justify-final')).toHaveLength(0);
    layout(tree, 200);
    expect(allByTestId(tree, 'agreement-justify-measure-first')).toHaveLength(1);
  });

  it('宽度变化后忽略旧一轮的测量回调', () => {
    const tree = renderComponent();
    layout(tree, 100);
    emitFirst(tree, [{ text: '第一条 ', width: 40 }, { text: '重点内容。', width: 60 }]);
    const oldLayout = byTestId(tree, 'agreement-justify-measure-second').props.onTextLayout;
    layout(tree, 200);
    act(() => {
      oldLayout({ nativeEvent: { lines: [
        { text: '第一条\n', width: 30 }, { text: '重点内容。', width: 60 },
      ] } });
    });
    expect(allByTestId(tree, 'agreement-justify-final')).toHaveLength(0);
    expect(allByTestId(tree, 'agreement-justify-measure-first')).toHaveLength(1);
  });
});

describe('RichAgreement 的平台和显式换行边界', () => {
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

  function renderAgreement(data = PAYLOAD): ReactTestRenderer {
    let tree!: ReactTestRenderer;
    act(() => { tree = create(<RichAgreement data={data} theme={THEMES.light} />); });
    return tree;
  }

  it('Android 的中文和英文 justify 段落共用对齐组件，居中段落不变', () => {
    const tree = renderAgreement();
    const placeholders = allByTestId(tree, 'agreement-justify-placeholder');
    expect(placeholders.map(textContent)).toEqual(['连续中文段落', 'English only paragraph']);
    const center = tree.root.findAllByType(TEXT).find((node) => node.props.children === '居中段落');
    expect(flattenStyle(center?.parent?.props.style).textAlign).toBe('center');
  });

  it('非 Android 维持普通 Text 路径', () => {
    Platform.OS = 'ios';
    const tree = renderAgreement();
    expect(allByTestId(tree, 'agreement-justify-root')).toHaveLength(0);
    expect(textContent(tree.root)).toContain('连续中文段落');
    expect(textContent(tree.root)).toContain('English only paragraph');
  });

  it('显式换行、连续空行和空格原样保留，换行前的短行不拉伸', () => {
    const tree = renderAgreement({ ...PAYLOAD, blocks: [{
      font_size: 16,
      align: 'justify',
      runs: [{ text: '甲  \n\n乙', bold: true }],
    }] });
    const roots = allByTestId(tree, 'agreement-justify-root');
    expect(roots).toHaveLength(2);
    roots.forEach((root) => {
      act(() => { root.props.onLayout({ nativeEvent: { layout: { width: 100 } } }); });
    });
    allByTestId(tree, 'agreement-justify-measure-first').forEach((measure) => {
      act(() => { measure.props.onTextLayout({
        nativeEvent: { lines: [{ text: textContent(measure), width: 40 }] },
      }); });
    });
    expect(allByTestId(tree, 'agreement-justify-final')).toHaveLength(0);
    const placeholders = allByTestId(tree, 'agreement-justify-placeholder');
    expect(placeholders.map(textContent)).toEqual(['甲  ', '乙']);
    placeholders.forEach((node) => {
      expect(textWithStyle(node, 'letterSpacing', undefined)).toBe(textContent(node));
    });
    const emptyLines = tree.root.findAllByType(TEXT).filter((node) => node.children.length === 0);
    expect(emptyLines).toHaveLength(1);
    expect(flattenStyle(emptyLines[0].props.style).lineHeight).toBe(24);
    expect(textWithStyle(tree.root, 'fontWeight', 'bold')).toBe('甲  乙');
  });
});

it('协议换版只移动粗体边界时立即显示新版格式并重新测量', () => {
  const agreement = (version: string, first: string, rest: string): AgreementPayload => ({
    version, title: '用户协议', format: 'agreement.richtext.v1',
    blocks: [{ font_size: 16, align: 'justify', runs: [
      { text: first, bold: true }, { text: rest, bold: false },
    ] }],
  });
  let tree!: ReactTestRenderer;
  act(() => { tree = create(<RichAgreement data={agreement('v1', '甲乙', '丙丁戊己')} theme={THEMES.light} />); });
  layout(tree, 100);
  emitFirst(tree, [{ text: '甲乙丙', width: 60 }, { text: '丁戊己', width: 60 }]);
  expect(textWithStyle(byTestId(tree, 'agreement-justify-final'), 'fontWeight', 'bold')).toBe('甲乙');
  act(() => { tree.update(<RichAgreement data={agreement('v2', '甲', '乙丙丁戊己')} theme={THEMES.light} />); });
  const displayed = allByTestId(tree, 'agreement-justify-final')[0] || byTestId(tree, 'agreement-justify-placeholder');
  expect(textContent(displayed)).toBe('甲乙丙丁戊己');
  expect(textWithStyle(displayed, 'fontWeight', 'bold')).toBe('甲');
  emitFirst(tree, [{ text: '甲乙丙', width: 55 }, { text: '丁戊己', width: 60 }]);
  expect(textWithStyle(byTestId(tree, 'agreement-justify-final'), 'fontWeight', 'bold')).toBe('甲');
});

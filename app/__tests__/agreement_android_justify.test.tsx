import React, { ElementType } from 'react';
import { Platform } from 'react-native';
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
  emitFirst(tree, [
    { text: '第一条 ', width: 40 },
    { text: '重点内容。', width: 60 },
  ]);
  emitSecond(tree, [
    { text: '第一条\n', width: 30 },
    { text: '重点内容。', width: 60 },
  ]);
}

beforeEach(() => {
  mockWindow.fontScale = 1;
  Platform.OS = 'android';
});

describe('AndroidJustifiedText（模拟测量事件，不验证原生绘制）', () => {
  it('宽度未知时保留原文和系统 justify 占位，不启动测量', () => {
    const tree = renderComponent();
    const placeholder = byTestId(tree, 'agreement-justify-placeholder');
    expect(textContent(placeholder)).toBe('第一条 重点内容。');
    expect(flattenStyle(placeholder.props.style)).toMatchObject({
      fontSize: 16, lineHeight: 24, color: '#111111', textAlign: 'justify',
    });
    expect(allByTestId(tree, 'agreement-justify-measure-first')).toHaveLength(0);
  });

  it('有折行空格时只在第二遍测量文本中裁剪，显示占位仍保留原文', () => {
    const tree = renderComponent();
    layout(tree, 100);
    emitFirst(tree, [
      { text: '第一条 ', width: 40 }, { text: '重点内容。', width: 60 },
    ]);
    expect(textContent(byTestId(tree, 'agreement-justify-measure-second'))).toBe('第一条\n重点内容。');
    expect(textContent(byTestId(tree, 'agreement-justify-placeholder'))).toBe('第一条 重点内容。');
    expect(allByTestId(tree, 'agreement-justify-final')).toHaveLength(0);
  });

  it('没有非末行尾部空格时只测一遍，末行的尾部空格不触发重测', () => {
    const tree = renderComponent([['甲乙丙丁戊末行  ', false]]);
    layout(tree, 100);
    emitFirst(tree, [
      { text: '甲乙丙丁戊', width: 50 }, { text: '末行  ', width: 30 },
    ]);
    const final = byTestId(tree, 'agreement-justify-final');
    expect(textContent(final)).toBe('甲乙丙丁戊\n末行  ');
    expect(textWithStyle(final, 'letterSpacing', 12.5)).toBe('甲乙丙丁');
    expect(textWithStyle(final, 'letterSpacing', undefined)).toBe('戊\n末行  ');
    expect(allByTestId(tree, 'agreement-justify-measure-second')).toHaveLength(0);
  });

  it('使用第二遍的可见宽度计算间距，最后可见字符和尾部空格不加间距', () => {
    const tree = renderComponent();
    runFullPass(tree);
    const final = byTestId(tree, 'agreement-justify-final');
    expect(textContent(final)).toBe('第一条 \n重点内容。');
    expect(textWithStyle(final, 'letterSpacing', 35)).toBe('第一');
    expect(textWithStyle(final, 'letterSpacing', undefined)).toBe('条 \n重点内容。');
    expect(flattenStyle(final.props.style)).toMatchObject({
      fontSize: 16, lineHeight: 24, color: '#111111', textAlign: 'left',
    });
    expect(flattenStyle(final.props.style).width).toBeGreaterThanOrEqual(110);
    expect(allByTestId(tree, 'agreement-justify-measure-first')).toHaveLength(0);
    expect(allByTestId(tree, 'agreement-justify-measure-second')).toHaveLength(0);
  });

  it.each([
    ['甲  乙', '甲  ', '甲', '乙', 10, 0],
    ['hello  world', 'hello  ', 'hello', 'world', 50, 12.5],
  ])('最终 Text 完整保留 %s 的连续空格', (source, first, visible, last, width, spacing) => {
    const tree = renderComponent([[source, false]]);
    layout(tree, 100);
    emitFirst(tree, [{ text: first, width: width + 20 }, { text: last, width: 50 }]);
    emitSecond(tree, [{ text: `${visible}\n`, width }, { text: last, width: 50 }]);
    const final = byTestId(tree, 'agreement-justify-final');
    expect(textContent(final)).toBe(`${first}\n${last}`);
    expect(textContent(final).replaceAll('\n', '')).toBe(source);
    expect(textWithStyle(final, 'letterSpacing', undefined)).toContain('  ');
    if (spacing > 0) {
      expect(textWithStyle(final, 'letterSpacing', spacing)).toBe('hell');
    } else {
      expect(textWithStyle(final, 'letterSpacing', undefined)).toBe(`${first}\n${last}`);
    }
  });

  it('软折行的中英混排和连续空格跨粗体片段后保留原文及格式', () => {
    const runs: [string, boolean][] = [
      ['中文 ', false], ['API ', true], [' 重点', false], ['内容', true],
    ];
    const tree = renderComponent(runs);
    layout(tree, 100);
    emitFirst(tree, [{ text: '中文 API  ', width: 80 }, { text: '重点内容', width: 40 }]);
    const second = byTestId(tree, 'agreement-justify-measure-second');
    expect(textWithStyle(second, 'fontWeight', 'bold')).toBe('API内容');
    emitSecond(tree, [{ text: '中文 API\n', width: 60 }, { text: '重点内容', width: 40 }]);
    const final = byTestId(tree, 'agreement-justify-final');
    expect(textContent(final)).toBe('中文 API  \n重点内容');
    expect(textWithStyle(final, 'fontWeight', 'bold')).toBe('API 内容');
    expect(textWithStyle(final, 'letterSpacing', 8)).toBe('中文 AP');
    expect(textWithStyle(final, 'letterSpacing', undefined)).toBe('I  \n重点内容');
  });

  it('补充平面汉字在最后可见字符处分割后保持完整', () => {
    const tree = renderComponent([['甲𠀀末行', false]]);
    layout(tree, 100);
    emitFirst(tree, [{ text: '甲𠀀', width: 40 }, { text: '末行', width: 40 }]);
    const final = byTestId(tree, 'agreement-justify-final');
    expect(textContent(final)).toBe('甲𠀀\n末行');
    expect(textWithStyle(final, 'letterSpacing', 60)).toBe('甲');
    expect(textWithStyle(final, 'letterSpacing', undefined)).toBe('𠀀\n末行');
  });

  it('末行的局部粗体保持 bold 且不被拉伸', () => {
    const tree = renderComponent();
    runFullPass(tree);
    const final = byTestId(tree, 'agreement-justify-final');
    expect(textWithStyle(final, 'fontWeight', 'bold')).toBe('重点');
    expect(textWithStyle(final, 'letterSpacing', undefined)).toContain('重点内容。');
  });

  it('文本不变但粗体值变化时重新测量', () => {
    const tree = renderComponent();
    runFullPass(tree);
    act(() => {
      tree.update(
        <AndroidJustifiedText runs={RUNS_NO_BOLD} fontSize={16} lineHeight={24} color="#111111" />,
      );
    });
    expect(allByTestId(tree, 'agreement-justify-final')).toHaveLength(0);
    expect(allByTestId(tree, 'agreement-justify-measure-first')).toHaveLength(1);
  });

  it('letterSpacing 按系统字号缩放折算，空格宽度不再次缩放', () => {
    mockWindow.fontScale = 2;
    const tree = renderComponent();
    runFullPass(tree);
    const final = byTestId(tree, 'agreement-justify-final');
    expect(textWithStyle(final, 'letterSpacing', 17.5)).toBe('第一');
    expect(flattenStyle(final.props.style).width).toBeGreaterThanOrEqual(110);
  });

  it('单行保留自然排版和原文空格', () => {
    const tree = renderComponent([['短句  ', false]]);
    layout(tree, 100);
    emitFirst(tree, [{ text: '短句  ', width: 50 }]);
    const placeholder = byTestId(tree, 'agreement-justify-placeholder');
    expect(textContent(placeholder)).toBe('短句  ');
    expect(textWithStyle(placeholder, 'letterSpacing', undefined)).toBe('短句  ');
    expect(allByTestId(tree, 'agreement-justify-final')).toHaveLength(0);
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

  it('系统字号变化后用新的折行与宽度重算', () => {
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
    const final = byTestId(tree, 'agreement-justify-final');
    expect(textContent(final)).toBe('第一条 重点\n内容。');
    const spacing = final.findAllByType(TEXT)
      .map((node) => flattenStyle(node.props.style).letterSpacing)
      .find((value) => typeof value === 'number');
    expect(spacing).toBeCloseTo(2);
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
    const measures = allByTestId(tree, 'agreement-justify-measure-first');
    measures.forEach((measure) => {
      act(() => { measure.props.onTextLayout({
        nativeEvent: { lines: [{ text: textContent(measure), width: 40 }] },
      }); });
    });
    expect(allByTestId(tree, 'agreement-justify-final')).toHaveLength(0);
    expect(allByTestId(tree, 'agreement-justify-placeholder').map(textContent)).toEqual(['甲  ', '乙']);
    const emptyLines = tree.root.findAllByType(TEXT).filter((node) => node.children.length === 0);
    expect(emptyLines).toHaveLength(1);
    expect(flattenStyle(emptyLines[0].props.style).lineHeight).toBe(24);
    expect(textWithStyle(tree.root, 'fontWeight', 'bold')).toBe('甲  乙');
  });
});

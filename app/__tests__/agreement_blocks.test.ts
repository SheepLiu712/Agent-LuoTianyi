/**
 * RichAgreement 渲染契约（UA-1 · issue #295）。
 *
 * 与桌面 render_agreement_document 同契约：
 * - 段落字号只接受 12–32 的整数，其余回退默认 16；
 * - 段落对齐只有 center，其余（含缺省）都按 justify；
 * - \n 拆成独立显示行，普通空格与连续空格原样保留。
 */

import {
  ALIGN_CENTER,
  ALIGN_JUSTIFY,
  DEFAULT_BLOCK_FONT_SIZE,
  MAX_BLOCK_FONT_SIZE,
  MIN_BLOCK_FONT_SIZE,
  blockFontSize,
  blockTextAlign,
  splitRunsOnNewline,
} from '../components/RichAgreement';

jest.mock('react-native', () => ({
  ScrollView: 'ScrollView',
  StyleSheet: { create: (styles: unknown) => styles },
  Text: 'Text',
  View: 'View',
}));

describe('RichAgreement 渲染契约', () => {
  it('段落字号在 12–32 内原样使用', () => {
    expect(blockFontSize({ runs: [], font_size: MIN_BLOCK_FONT_SIZE })).toBe(MIN_BLOCK_FONT_SIZE);
    expect(blockFontSize({ runs: [], font_size: 22 })).toBe(22);
    expect(blockFontSize({ runs: [], font_size: MAX_BLOCK_FONT_SIZE })).toBe(MAX_BLOCK_FONT_SIZE);
  });

  it('段落字号越界或非法时回退默认值', () => {
    const fallback = DEFAULT_BLOCK_FONT_SIZE;
    expect(blockFontSize({ runs: [], font_size: MIN_BLOCK_FONT_SIZE - 1 })).toBe(fallback);
    expect(blockFontSize({ runs: [], font_size: MAX_BLOCK_FONT_SIZE + 1 })).toBe(fallback);
    expect(blockFontSize({ runs: [], font_size: 16.5 })).toBe(fallback);
    expect(blockFontSize({ runs: [] })).toBe(fallback);
    expect(blockFontSize({ runs: [], font_size: Number.NaN })).toBe(fallback);
  });

  it('段落对齐按已校验的 center / justify 与缺省值映射', () => {
    expect(blockTextAlign({ runs: [], align: ALIGN_CENTER })).toBe('center');
    expect(blockTextAlign({ runs: [], align: ALIGN_JUSTIFY })).toBe('justify');
    expect(blockTextAlign({ runs: [] })).toBe('justify');
  });

  it('按 \\n 拆成独立显示行，保留加粗标记', () => {
    expect(
      splitRunsOnNewline([
        { text: '甲', bold: true },
        { text: '\n乙\n', bold: false },
        { text: '丙', bold: false },
      ]),
    ).toEqual([
      [['甲', true]],
      [['乙', false]],
      [['丙', false]],
    ]);
  });

  it('保留普通空格与连续空格，不折叠', () => {
    expect(splitRunsOnNewline([{ text: '示例：甲  乙    丙' }])).toEqual([
      [['示例：甲  乙    丙', false]],
    ]);
  });

  it('空 runs 与结尾换行都落成空显示行', () => {
    expect(splitRunsOnNewline([])).toEqual([[]]);
    expect(splitRunsOnNewline([{ text: '正文\n' }])).toEqual([[['正文', false]], []]);
  });
});

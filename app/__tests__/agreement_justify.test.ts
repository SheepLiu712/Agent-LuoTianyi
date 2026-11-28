import {
  buildJustifiedLines,
  buildLineDescriptors,
  computeLetterSpacing,
  runsToText,
  trimLineEndSpaces,
} from '../utils/agreement_justify';

describe('agreement_justify', () => {
  it('测宽只裁剪尾部连续空白，保留行首空格及不可裁剪字符', () => {
    const spaces = ' \t\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2008\u2009\u200A\u205F\u3000';
    expect(trimLineEndSpaces(`  甲${spaces}`)).toBe('  甲');
    expect(trimLineEndSpaces(spaces)).toBe('');
    for (const suffix of ['\u00A0', '\u2007', '\u200B', '\n']) {
      expect(trimLineEndSpaces(`甲\u3000${suffix}`)).toBe(`甲\u3000${suffix}`);
    }
    expect(trimLineEndSpaces('甲\u2007\u3000')).toBe('甲\u2007');
  });

  describe('原文映射', () => {
    it('测量文本与完整显示内容分离，空格跨片段时保留粗体边界', () => {
      const runs = [
        { text: '第一条 ', bold: false },
        { text: ' 重点', bold: true },
        { text: '内容。', bold: false },
      ];
      const lines = buildLineDescriptors(runs, [{ text: '第一条  ' }, { text: '重点内容。' }])!;
      expect(lines.map((line) => runsToText(line.displayRuns)).join('')).toBe('第一条  重点内容。');
      expect(lines[0]).toMatchObject({
        visibleText: '第一条', trailingText: '  ', displayText: '第一条  ', isLast: false,
      });
      expect(lines[0].visibleRuns).toEqual([{ text: '第一条', bold: false }]);
      expect(lines[0].trailingRuns).toEqual([
        { text: ' ', bold: false }, { text: ' ', bold: true },
      ]);
      expect(lines[1].displayRuns).toEqual([
        { text: '重点', bold: true }, { text: '内容。', bold: false },
      ]);
      expect(lines[1]).toMatchObject({ visibleText: '重点内容。', trailingText: '', isLast: true });
    });

    it.each([
      [[{ text: 'hello  ' }, { text: 'world' }]],
      [[{ text: 'hello' }, { text: 'world' }]],
    ])('测量是否返回折行空格都不影响显示原文：%j', (measured) => {
      const lines = buildLineDescriptors([{ text: 'hello  world', bold: false }], measured)!;
      expect(lines.map((line) => runsToText(line.displayRuns)).join('')).toBe('hello  world');
      expect(lines[0].trailingText).toBe('  ');
      expect(lines[0].visibleText).toBe('hello');
    });

    it('末行保留行首和行尾空格，非末行保留不可换行空格', () => {
      const lines = buildLineDescriptors(
        [{ text: '甲\u00A0  乙  ', bold: false }], [{ text: '甲\u00A0' }, { text: '  乙' }],
      )!;
      expect(lines[0]).toMatchObject({ visibleText: '甲\u00A0', trailingText: '' });
      expect(lines[1]).toMatchObject({ visibleText: '  乙  ', trailingText: '', isLast: true });
      expect(lines.map((line) => runsToText(line.displayRuns)).join('')).toBe('甲\u00A0  乙  ');
    });

    it('测量没有行或无法匹配原文时不生成排版数据', () => {
      expect(buildLineDescriptors([{ text: '原文', bold: false }], [{ text: '改写' }])).toBeNull();
      expect(buildLineDescriptors([{ text: '原文', bold: false }], [])).toBeNull();
    });
  });

  describe('间距计算', () => {
    it.each([1, 2])('四个字符的剩余宽度均分到三个间隙，并按 fontScale=%s 换算', (fontScale) => {
      expect(computeLetterSpacing(100, 200, 4, fontScale)).toBeCloseTo(100 / 3 / fontScale);
    });

    it('无剩余空间、少于两个字符或非法测量时不拉伸', () => {
      expect(computeLetterSpacing(200, 200, 4, 1)).toBe(0);
      expect(computeLetterSpacing(300, 200, 4, 1)).toBe(0);
      expect(computeLetterSpacing(100, 200, 1, 1)).toBe(0);
      expect(computeLetterSpacing(Number.NaN, 200, 4, 1)).toBe(0);
      expect(computeLetterSpacing(100, 200, 4, 0)).toBe(0);
    });

    it('已满行和有词间空格的行不加间距，无间隙的非末行按可见宽度补齐', () => {
      const texts = ['甲乙丙丁', 'office affinity ', '第一条  ', '甲  ', '  ', '末行'];
      const source = texts.join('');
      const descriptors = buildLineDescriptors(
        [{ text: source, bold: false }], texts.map((text) => ({ text })),
      )!;
      const lines = buildJustifiedLines(descriptors, [100, 80, 30, 16, 0, 32], 100, 1)!;
      expect(lines.map((line) => line.letterSpacing)).toEqual([0, 0, 35, 0, 0, 0]);
      expect(lines.map((line) => runsToText(line.displayRuns)).join('')).toBe(source);
    });

    it('行数或宽度异常时不生成排版结果', () => {
      const descriptors = buildLineDescriptors(
        [{ text: '第一条末行', bold: false }], [{ text: '第一条' }, { text: '末行' }],
      )!;
      expect(buildJustifiedLines(descriptors, [30], 100, 1)).toBeNull();
      expect(buildJustifiedLines(descriptors, [30, Number.NaN], 100, 1)).toBeNull();
      expect(buildJustifiedLines(descriptors, [-1, 60], 100, 1)).toBeNull();
      expect(buildJustifiedLines(descriptors, [30, 60], 0, 1)).toBeNull();
      expect(buildJustifiedLines(descriptors, [30, 60], 100, 0)).toBeNull();
    });
  });
});

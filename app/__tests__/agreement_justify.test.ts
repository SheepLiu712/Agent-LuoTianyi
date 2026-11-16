import {
  buildJustifiedLines,
  buildLineDescriptors,
  computeLetterSpacing,
  countCodePoints,
  isLineEndSpace,
  runsToText,
  sliceRuns,
  trimLineEndSpaces,
} from '../utils/agreement_justify';

describe('agreement_justify', () => {
  describe('isLineEndSpace / trimLineEndSpaces', () => {
    it('识别普通空格、制表符、全角空格等行尾空白', () => {
      const chars = [
        ' ', '\t', '\u1680', '\u2000', '\u2001', '\u2002', '\u2003', '\u2004',
        '\u2005', '\u2006', '\u2008', '\u2009', '\u200A', '\u205F', '\u3000',
      ];
      chars.forEach((ch) => expect(isLineEndSpace(ch)).toBe(true));
    });

    it('不把 NBSP、figure space、零宽空格与换行当作可裁剪行尾空白', () => {
      ['\u00A0', '\u2007', '\u200B', '\n', 'a', ''].forEach((ch) => {
        expect(isLineEndSpace(ch)).toBe(false);
      });
    });

    it('只裁剪测量文本末尾的连续空白', () => {
      expect(trimLineEndSpaces('甲   ')).toBe('甲');
      expect(trimLineEndSpaces('甲\u3000\u2000\t')).toBe('甲');
      expect(trimLineEndSpaces('   ')).toBe('');
      expect(trimLineEndSpaces('甲\u00A0')).toBe('甲\u00A0');
      expect(trimLineEndSpaces('甲\u3000\u2007')).toBe('甲\u3000\u2007');
      expect(trimLineEndSpaces('甲\u2007\u3000')).toBe('甲\u2007');
      expect(trimLineEndSpaces('  甲')).toBe('  甲');
    });
  });

  describe('countCodePoints', () => {
    it('按码点计数，不把补充平面汉字的代理对拆成两个字符', () => {
      expect(countCodePoints('中a')).toBe(2);
      expect(countCodePoints('甲乙丙')).toBe(3);
      expect(countCodePoints('𠀀')).toBe(1);
      expect(countCodePoints('')).toBe(0);
    });
  });

  describe('runsToText / sliceRuns', () => {
    it('按原文顺序拼接 runs', () => {
      expect(runsToText([
        { text: '第一条 ', bold: false },
        { text: '重点', bold: true },
      ])).toBe('第一条 重点');
    });

    it('按 UTF-16 偏移切分并保留 bold 边界', () => {
      const runs = [
        { text: '甲乙丙', bold: false },
        { text: '丁戊', bold: true },
      ];
      expect(sliceRuns(runs, 1, 4)).toEqual([
        { text: '乙丙', bold: false },
        { text: '丁', bold: true },
      ]);
      expect(sliceRuns(runs, 3, 5)).toEqual([{ text: '丁戊', bold: true }]);
      expect(sliceRuns(runs, 0, 0)).toEqual([]);
    });
  });

  describe('buildLineDescriptors', () => {
    it('完整显示行与可见测量文本分离，保留粗体标记', () => {
      const descriptors = buildLineDescriptors([
        { text: '第一条 ', bold: false },
        { text: '重点', bold: true },
        { text: '内容。', bold: false },
      ], [{ text: '第一条 ' }, { text: '重点内容。' }])!;

      expect(descriptors[0]).toMatchObject({
        visibleText: '第一条',
        trailingText: ' ',
        displayText: '第一条 ',
        isLast: false,
      });
      expect(descriptors[0].displayRuns).toEqual([{ text: '第一条 ', bold: false }]);
      expect(descriptors[0].visibleRuns).toEqual([{ text: '第一条', bold: false }]);
      expect(descriptors[0].trailingRuns).toEqual([{ text: ' ', bold: false }]);
      expect(descriptors[1].displayRuns).toEqual([
        { text: '重点', bold: true },
        { text: '内容。', bold: false },
      ]);
      expect(descriptors[1]).toMatchObject({
        visibleText: '重点内容。', trailingText: '', isLast: true,
      });
    });

    it.each([
      ['甲  乙', '甲  ', '乙'],
      ['hello  world', 'hello  ', 'world'],
    ])('软折行后完整保留 %s 的原始空格', (source, first, last) => {
      const descriptors = buildLineDescriptors(
        [{ text: source, bold: false }], [{ text: first }, { text: last }],
      )!;
      expect(descriptors.map((line) => runsToText(line.displayRuns)).join('')).toBe(source);
      expect(descriptors[0].trailingText).toBe('  ');
      expect(descriptors[0].visibleText).toBe(first.trimEnd());
    });

    it('测量文本未返回折行空格时，仍从原文保留空格', () => {
      const descriptors = buildLineDescriptors(
        [{ text: 'hello  world', bold: false }], [{ text: 'hello' }, { text: 'world' }],
      )!;
      expect(descriptors.map((line) => runsToText(line.displayRuns)).join('')).toBe('hello  world');
      expect(descriptors[0].trailingText).toBe('  ');
    });

    it('行尾空格跨粗体片段时保留各片段的格式', () => {
      const descriptors = buildLineDescriptors([
        { text: '甲乙 ', bold: false },
        { text: ' 丙丁', bold: true },
      ], [{ text: '甲乙  ' }, { text: '丙丁' }])!;
      expect(descriptors[0].trailingRuns).toEqual([
        { text: ' ', bold: false }, { text: ' ', bold: true },
      ]);
      expect(descriptors[1].displayRuns).toEqual([{ text: '丙丁', bold: true }]);
    });

    it('末行与行首空格均完整保留', () => {
      const descriptors = buildLineDescriptors(
        [{ text: '  甲  ', bold: false }], [{ text: '  甲' }],
      )!;
      expect(descriptors[0]).toMatchObject({
        visibleText: '  甲  ', trailingText: '', displayText: '  甲  ', isLast: true,
      });
    });

    it('非末行的 NBSP 保留在可见部分', () => {
      const descriptors = buildLineDescriptors(
        [{ text: '甲\u00A0乙', bold: false }], [{ text: '甲\u00A0' }, { text: '乙' }],
      )!;
      expect(descriptors[0].visibleText).toBe('甲\u00A0');
      expect(descriptors[0].trailingText).toBe('');
    });

    it('无法映射测量行时返回 null', () => {
      expect(buildLineDescriptors([{ text: '原文', bold: false }], [{ text: '改写' }])).toBeNull();
      expect(buildLineDescriptors([{ text: '原文', bold: false }], [])).toBeNull();
    });
  });

  describe('computeLetterSpacing', () => {
    it('把剩余 100dp 均分到四个字符的三个间隙', () => {
      expect(computeLetterSpacing(100, 200, 4, 1)).toBeCloseTo(100 / 3);
    });

    it('按 fontScale 折算 RN 的 SP 语义', () => {
      expect(computeLetterSpacing(100, 200, 4, 2)).toBeCloseTo(100 / 3 / 2);
    });

    it('无剩余空间、少于两个字符或非法输入时不拉伸', () => {
      expect(computeLetterSpacing(200, 200, 4, 1)).toBe(0);
      expect(computeLetterSpacing(300, 200, 4, 1)).toBe(0);
      expect(computeLetterSpacing(100, 200, 1, 1)).toBe(0);
      expect(computeLetterSpacing(Number.NaN, 200, 4, 1)).toBe(0);
      expect(computeLetterSpacing(100, 200, 4, 0)).toBe(0);
    });
  });

  describe('buildJustifiedLines', () => {
    function createDescriptors() {
      return buildLineDescriptors(
        [{ text: '第一条 重点内容。', bold: false }],
        [{ text: '第一条 ' }, { text: '重点内容。' }],
      )!;
    }

    it('无词间空格的非末行用可见宽度计算，末行不拉伸', () => {
      const lines = buildJustifiedLines(createDescriptors(), [30, 60], 100, 1)!;
      expect(lines[0]).toMatchObject({
        visibleText: '第一条', trailingText: ' ', codePointCount: 3,
        letterSpacing: 35, isLast: false,
      });
      expect(lines[1]).toMatchObject({ letterSpacing: 0, isLast: true });
    });

    it('letterSpacing 按 fontScale 折算', () => {
      expect(buildJustifiedLines(createDescriptors(), [30, 60], 100, 2)![0].letterSpacing).toBe(17.5);
    });

    it('逐行短路：已满行和有词间空格的行不加间距，后续中文行仍补齐', () => {
      const descriptors = buildLineDescriptors(
        [{ text: '甲乙丙丁office affinity 甲乙丙丁末行', bold: false }],
        [{ text: '甲乙丙丁' }, { text: 'office affinity ' }, { text: '甲乙丙丁' }, { text: '末行' }],
      )!;
      const lines = buildJustifiedLines(descriptors, [100, 80, 64, 32], 100, 1)!;
      expect(lines.map((line) => line.letterSpacing)).toEqual([0, 0, 12, 0]);
      expect(lines.map((line) => runsToText(line.displayRuns)).join('')).toBe('甲乙丙丁office affinity 甲乙丙丁末行');
    });

    it.each(['甲', ''])('可见部分为“%s”时不产生间距，仍保留原文', (visible) => {
      const source = `${visible}  乙`;
      const descriptors = buildLineDescriptors(
        [{ text: source, bold: false }], [{ text: `${visible}  ` }, { text: '乙' }],
      )!;
      const lines = buildJustifiedLines(descriptors, [visible.length * 10, 20], 100, 1)!;
      expect(lines[0].letterSpacing).toBe(0);
      expect(lines.map((line) => runsToText(line.displayRuns)).join('')).toBe(source);
    });

    it('行数或宽度异常时返回 null', () => {
      const descriptors = createDescriptors();
      expect(buildJustifiedLines(descriptors, [30], 100, 1)).toBeNull();
      expect(buildJustifiedLines(descriptors, [30, Number.NaN], 100, 1)).toBeNull();
      expect(buildJustifiedLines(descriptors, [-1, 60], 100, 1)).toBeNull();
      expect(buildJustifiedLines(descriptors, [30, 60], 0, 1)).toBeNull();
      expect(buildJustifiedLines(descriptors, [30, 60], 100, 0)).toBeNull();
    });
  });
});

/**
 * Android 字符级两端对齐的纯排版计算（issue #313）。
 *
 * 预期值逐项对应 AOSP android-15.0.0_r1：
 * - `TextLine.isLineEndSpace`（TextLine.java:1872-1877）
 * - `Layout.getLineVisibleEnd(..., true)`（Layout.java:793-794、2753-2776）
 * - `TextLine.justify` 的 LETTER_SPACING 分支（TextLine.java:293-329）
 *
 * 这些用例是移植一致性检查：字符集、裁剪、字形簇计数、公式与 0.03 阈值
 * 都必须与源码逐项相同；原生绘制效果由真机验收，属性测试不能替代。
 */

import {
  buildJustifiedLines,
  buildLineDescriptors,
  countClusters,
  isLineEndSpace,
  justifyLine,
  runsToText,
  sliceRuns,
  trimLineEndSpaces,
  visibleLineText,
} from '../utils/agreement_justify';

describe('agreement_justify 的 AOSP 一致性', () => {
  describe('TextLine.isLineEndSpace', () => {
    it('命中 AOSP 的完整字符集', () => {
      const chars = [
        ' ',
        '\t',
        '\u1680',
        '\u2000',
        '\u2001',
        '\u2002',
        '\u2003',
        '\u2004',
        '\u2005',
        '\u2006',
        '\u2008',
        '\u2009',
        '\u200A',
        '\u205F',
        '\u3000',
      ];
      chars.forEach((ch) => {
        expect(isLineEndSpace(ch)).toBe(true);
      });
    });

    it('不包含 NBSP、figure space、零宽空格与换行', () => {
      // AOSP 明确排除 0x2007；0x00A0 不在集合内；\n 由 Layout 另行处理。
      ['\u00A0', '\u2007', '\u200B', '\n', '\u3001', 'a', ''].forEach((ch) => {
        expect(isLineEndSpace(ch)).toBe(false);
      });
    });
  });

  describe('trimLineEndSpaces / visibleLineText', () => {
    it('裁掉行尾所有 AOSP line-end space', () => {
      expect(trimLineEndSpaces('甲   ')).toBe('甲');
      expect(trimLineEndSpaces('甲\u3000\u2000\t')).toBe('甲');
      expect(trimLineEndSpaces('   ')).toBe('');
      expect(trimLineEndSpaces('甲')).toBe('甲');
    });

    it('NBSP 与 figure space 不是行尾空格，保留', () => {
      expect(trimLineEndSpaces('甲\u00A0')).toBe('甲\u00A0');
      expect(trimLineEndSpaces('甲\u2007')).toBe('甲\u2007');
      // 从行尾向前裁剪：末尾是 U+2007 时循环立即停止，前面的 U+3000 也不会被裁。
      expect(trimLineEndSpaces('甲\u3000\u2007')).toBe('甲\u3000\u2007');
      expect(trimLineEndSpaces('甲\u2007\u3000')).toBe('甲\u2007');
    });

    it('段落末行保留行尾空格，其余行裁剪', () => {
      expect(visibleLineText('甲  ', false)).toBe('甲');
      expect(visibleLineText('甲  ', true)).toBe('甲  ');
    });
  });

  describe('countClusters', () => {
    it('按码点统计；CJK/ASCII 每个码点即一个字形簇', () => {
      expect(countClusters('中a')).toBe(2);
      expect(countClusters('甲乙丙')).toBe(3);
      expect(countClusters('𠀀')).toBe(1);
      expect(countClusters('')).toBe(0);
    });
  });

  describe('runsToText / sliceRuns', () => {
    it('按原文顺序拼接 runs', () => {
      expect(
        runsToText([
          { text: '第一条 ', bold: false },
          { text: '重点', bold: true },
        ]),
      ).toBe('第一条 重点');
    });

    it('按 UTF-16 偏移切分，并在行边界保留 bold 标记', () => {
      const runs = [
        { text: '甲乙丙', bold: false },
        { text: '丁戊', bold: true },
      ];

      expect(sliceRuns(runs, 1, 4)).toEqual([
        { text: '乙丙', bold: false },
        { text: '丁', bold: true },
      ]);
      expect(sliceRuns(runs, 0, 0)).toEqual([]);
      expect(sliceRuns(runs, 3, 5)).toEqual([{ text: '丁戊', bold: true }]);
    });
  });

  describe('buildLineDescriptors', () => {
    it('把自然折行映射回原文，并跨行保留 bold run', () => {
      const runs = [
        { text: '第一条 本协议用于', bold: false },
        { text: '校验', bold: true },
        { text: '。', bold: false },
      ];

      expect(buildLineDescriptors(runs, [{ text: '第一条 ' }, { text: '本协议用于校验。' }]))
        .toEqual([
          {
            // 非末行按 Layout.getLineVisibleEnd 裁掉行尾空格。
            runs: [{ text: '第一条', bold: false }],
            text: '第一条',
            isLast: false,
          },
          {
            runs: [
              { text: '本协议用于', bold: false },
              { text: '校验', bold: true },
              { text: '。', bold: false },
            ],
            text: '本协议用于校验。',
            isLast: true,
          },
        ]);
    });

    it('折行处的普通空格在非末行被裁掉，末行保留', () => {
      const runs = [{ text: 'hello world', bold: false }];

      // Android 通常把折行空格算在前一行；即使平台不返回，也能按空位跳过。
      for (const lines of [
        [{ text: 'hello ' }, { text: 'world' }],
        [{ text: 'hello' }, { text: 'world' }],
      ]) {
        expect(buildLineDescriptors(runs, lines)).toEqual([
          {
            runs: [{ text: 'hello', bold: false }],
            text: 'hello',
            isLast: false,
          },
          {
            runs: [{ text: 'world', bold: false }],
            text: 'world',
            isLast: true,
          },
        ]);
      }
    });

    it('末行的行尾空格按 AOSP 保留（trailingSpaceAtLastLineIsVisible=true）', () => {
      expect(buildLineDescriptors([{ text: '甲  ', bold: false }], [{ text: '甲' }])).toEqual([
        {
          runs: [{ text: '甲  ', bold: false }],
          text: '甲  ',
          isLast: true,
        },
      ]);
    });

    it('非末行的 NBSP 不属于 line-end space，保留', () => {
      expect(
        buildLineDescriptors([{ text: '甲\u00A0乙', bold: false }], [
          { text: '甲\u00A0' },
          { text: '乙' },
        ]),
      ).toEqual([
        {
          runs: [{ text: '甲\u00A0', bold: false }],
          text: '甲\u00A0',
          isLast: false,
        },
        {
          runs: [{ text: '乙', bold: false }],
          text: '乙',
          isLast: true,
        },
      ]);
    });

    it('行首空格属于当前行，不被裁剪', () => {
      expect(buildLineDescriptors([{ text: '  甲', bold: false }], [{ text: '  甲' }])).toEqual([
        {
          runs: [{ text: '  甲', bold: false }],
          text: '  甲',
          isLast: true,
        },
      ]);
    });

    it('无法把测量行映射回原文时返回 null', () => {
      expect(buildLineDescriptors([{ text: '原文', bold: false }], [{ text: '被平台改写' }])).toBeNull();
      expect(buildLineDescriptors([{ text: '原文', bold: false }], [])).toBeNull();
    });
  });

  describe('justifyLine（TextLine.justify LETTER_SPACING 分支）', () => {
    it('按 (justifyWidth - width) / (lettersCount - 1) 计算', () => {
      expect(
        justifyLine({
          text: '甲乙丙',
          widthPx: 100,
          justifyWidthPx: 200,
          textSizePx: 16,
        }),
      ).toEqual({
        text: '甲乙丙',
        lettersCount: 3,
        spacingPx: 50,
        spacingEm: 3.125,
        ligatureDisabled: true,
      });
    });

    it('测量前先裁掉行尾空格，再计数与计算', () => {
      expect(
        justifyLine({
          text: '甲乙  ',
          widthPx: 100,
          justifyWidthPx: 200,
          textSizePx: 16,
        }),
      ).toEqual({
        text: '甲乙',
        lettersCount: 2,
        spacingPx: 100,
        spacingEm: 6.25,
        ligatureDisabled: true,
      });
    });

    it('lettersCount < 2 时 AOSP 直接返回，不产生间距', () => {
      ['甲', '甲  ', ''].forEach((text) => {
        expect(
          justifyLine({ text, widthPx: 100, justifyWidthPx: 200, textSizePx: 16 }),
        ).toBeNull();
      });
    });

    it('0.03 阈值按像素比较：> 0.03 命中连字关闭分支', () => {
      const base = {
        text: '甲乙',
        widthPx: 100,
        textSizePx: 16,
      };
      expect(
        justifyLine({ ...base, justifyWidthPx: 100.02 })?.ligatureDisabled,
      ).toBe(false);
      expect(
        justifyLine({ ...base, justifyWidthPx: 100.04 })?.ligatureDisabled,
      ).toBe(true);
    });

    it('不压缩保护：宽度超过行宽时 AOSP 公式给出负间距', () => {
      // AOSP 没有 0 下限；这里保留公式结果，避免加入源码之外的逻辑。
      const result = justifyLine({
        text: '甲 乙',
        widthPx: 300,
        justifyWidthPx: 200,
        textSizePx: 16,
      });
      expect(result?.lettersCount).toBe(3);
      expect(result?.spacingPx).toBe(-50);
      expect(result?.ligatureDisabled).toBe(false);
    });
  });

  describe('buildJustifiedLines', () => {
    const descriptors = [
      {
        runs: [{ text: '甲乙丙丁戊', bold: false }],
        text: '甲乙丙丁戊',
        isLast: false,
      },
      {
        runs: [{ text: '末行', bold: false }],
        text: '末行',
        isLast: true,
      },
    ];

    it('非末行按 AOSP 公式计算，末行固定 0', () => {
      expect(buildJustifiedLines(descriptors, [100, 40], 200, 16, 1, 1)).toEqual([
        {
          runs: [{ text: '甲乙丙丁戊', bold: false }],
          text: '甲乙丙丁戊',
          isLast: false,
          lettersCount: 5,
          spacingPx: 25,
          ligatureDisabled: true,
          letterSpacing: 25,
        },
        {
          runs: [{ text: '末行', bold: false }],
          text: '末行',
          isLast: true,
          lettersCount: 2,
          spacingPx: 0,
          ligatureDisabled: false,
          letterSpacing: 0,
        },
      ]);
    });

    it('letterSpacing prop 按 fontScale 与屏幕密度折算', () => {
      // 像素间距 25；RN prop 在 fontScale=2、density=3 时为 25 / (2*3)。
      const lines = buildJustifiedLines(descriptors, [100, 40], 200, 32, 2, 3);
      expect(lines?.[0].letterSpacing).toBeCloseTo(25 / 6, 10);
      expect(lines?.[1].letterSpacing).toBe(0);
    });

    it('lettersCount < 2 的非末行不产生间距', () => {
      const single = [
        { runs: [{ text: '甲', bold: false }], text: '甲', isLast: false },
        { runs: [{ text: '末行', bold: false }], text: '末行', isLast: true },
      ];
      const lines = buildJustifiedLines(single, [10, 40], 200, 16, 1, 1);
      expect(lines?.[0].spacingPx).toBe(0);
      expect(lines?.[0].letterSpacing).toBe(0);
    });

    it('行数或宽度异常时返回 null，由调用方回退', () => {
      expect(buildJustifiedLines(descriptors, [100], 200, 16, 1, 1)).toBeNull();
      expect(buildJustifiedLines(descriptors, [100, Number.NaN], 200, 16, 1, 1)).toBeNull();
      expect(buildJustifiedLines(descriptors, [100, 40], 0, 16, 1, 1)).toBeNull();
      expect(buildJustifiedLines(descriptors, [100, 40], 200, 0, 1, 1)).toBeNull();
      expect(buildJustifiedLines(descriptors, [100, 40], 200, 16, 0, 1)).toBeNull();
      expect(buildJustifiedLines(descriptors, [100, 40], 200, 16, 1, 0)).toBeNull();
    });
  });
});

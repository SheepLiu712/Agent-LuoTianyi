/**
 * Android 中文两端对齐的纯排版计算（issue #313）。
 *
 * 覆盖：折行结果到 runs 的映射、字符间隙计数、
 * fontScale 折算，以及测量异常时的回退信号。
 */

import {
  buildJustifiedLines,
  buildLineDescriptors,
  computeLetterSpacing,
  countClusters,
  runsToText,
  sliceRuns,
  splitTrailingChar,
} from '../utils/agreement_justify';

describe('agreement_justify 纯排版计算', () => {
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

  describe('splitTrailingChar', () => {
    it('分离行尾字符：头部参与间距，尾部保持原样', () => {
      expect(
        splitTrailingChar([
          { text: '第一条 ', bold: false },
          { text: '重点', bold: true },
        ]),
      ).toEqual({
        head: [
          { text: '第一条 ', bold: false },
          { text: '重', bold: true },
        ],
        tail: { text: '点', bold: true },
      });
      expect(splitTrailingChar([{ text: '甲', bold: false }])).toEqual({
        head: [],
        tail: null,
      });
    });
  });

  describe('字符计数', () => {
    it('按码点统计字符，代理对算一个字符', () => {
      expect(countClusters('中a')).toBe(2);
      expect(countClusters('𠀀')).toBe(1);
      expect(countClusters('')).toBe(0);
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
            runs: [{ text: '第一条 ', bold: false }],
            text: '第一条 ',
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

    it('折行处的空格保留在该行文本中，不参与可见切分', () => {
      const runs = [{ text: 'hello world', bold: false }];

      // Android 通常把折行空格算在前一行；即使平台不返回，也能按空位跳过。
      for (const lines of [
        [{ text: 'hello ' }, { text: 'world' }],
        [{ text: 'hello' }, { text: 'world' }],
      ]) {
        expect(buildLineDescriptors(runs, lines)).toEqual([
          {
            runs: [{ text: 'hello ', bold: false }],
            text: 'hello ',
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

    it('最后一行保留原文末尾空格（不拉伸）', () => {
      expect(buildLineDescriptors([{ text: '甲  ', bold: false }], [{ text: '甲' }])).toEqual([
        {
          runs: [{ text: '甲  ', bold: false }],
          text: '甲  ',
          isLast: true,
        },
      ]);
    });

    it('行首空格属于当前行', () => {
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

  describe('computeLetterSpacing', () => {
    it('把剩余宽度均分到字符间隙', () => {
      expect(computeLetterSpacing(100, 200, 4, 1)).toBe(25);
    });

    it('按 fontScale 折算 RN 的 SP 语义', () => {
      // RN 的 letterSpacing prop 会按系统字号缩放；屏幕上的实际间距要保持 25dp，
      // fontScale=2 时传入值应为 12.5。
      expect(computeLetterSpacing(100, 200, 4, 2)).toBe(12.5);
    });

    it('无间隙、无剩余宽度或非法输入时不拉伸', () => {
      expect(computeLetterSpacing(100, 200, 0, 1)).toBe(0);
      expect(computeLetterSpacing(200, 200, 4, 1)).toBe(0);
      expect(computeLetterSpacing(300, 200, 4, 1)).toBe(0);
      expect(computeLetterSpacing(Number.NaN, 200, 4, 1)).toBe(0);
      expect(computeLetterSpacing(100, 200, 4, 0)).toBe(0);
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

    it('非末行按 (容器宽 - 自然宽)/(字符数-1) 计算，末行固定 0', () => {
      expect(buildJustifiedLines(descriptors, [100, 40], 200, 1)).toEqual([
        {
          runs: [{ text: '甲乙丙丁戊', bold: false }],
          text: '甲乙丙丁戊',
          isLast: false,
          gapCount: 4,
          letterSpacing: 25,
        },
        {
          runs: [{ text: '末行', bold: false }],
          text: '末行',
          isLast: true,
          gapCount: 1,
          letterSpacing: 0,
        },
      ]);
    });

    it('行数或宽度异常时返回 null，由调用方回退', () => {
      expect(buildJustifiedLines(descriptors, [100], 200, 1)).toBeNull();
      expect(buildJustifiedLines(descriptors, [100, Number.NaN], 200, 1)).toBeNull();
      expect(buildJustifiedLines(descriptors, [100, 40], 0, 1)).toBeNull();
    });

    it('自然宽度超过容器时 spacing 为 0，不压缩字形', () => {
      expect(buildJustifiedLines(descriptors, [250, 40], 200, 1)).toEqual([
        {
          runs: [{ text: '甲乙丙丁戊', bold: false }],
          text: '甲乙丙丁戊',
          isLast: false,
          gapCount: 4,
          letterSpacing: 0,
        },
        {
          runs: [{ text: '末行', bold: false }],
          text: '末行',
          isLast: true,
          gapCount: 1,
          letterSpacing: 0,
        },
      ]);
    });
  });
});

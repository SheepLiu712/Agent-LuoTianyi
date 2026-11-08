/**
 * Android 中文两端对齐（issue #313）的纯排版计算。
 *
 * 背景：React Native 的 `textAlign: 'justify'` 在 Android 上映射到
 * `Layout.JUSTIFICATION_MODE_INTER_WORD`，只拉伸普通空格。连续中文没有空格，
 * 右边缘不会贴齐。Android 15 的系统实现（`TextLine.justify` 的
 * `JUSTIFICATION_MODE_INTER_CHARACTER`）用字间距补齐：
 *
 *   letterSpacing = (justifyWidth - naturalWidth) / (clusterCount - 1)
 *
 * 本模块复刻这套算法：先由 RN 的 `onTextLayout` 取得自然折行和每行自然宽度，
 * 再按字符间隙均分剩余宽度，交给 RN `Text` 的 `letterSpacing` 渲染。
 * 这里只做纯计算，不依赖 React Native，便于单测覆盖边界。
 */

export interface JustifyRun {
  text: string;
  bold: boolean;
}

export interface MeasuredLineLike {
  text: string;
  width?: number;
}

export interface LineDescriptor {
  /** 该显示行的 runs 与文本；折行处的空格是原文的一部分，参与字间距分配。 */
  runs: JustifyRun[];
  text: string;
  isLast: boolean;
}

export interface JustifiedLine extends LineDescriptor {
  /** 传给 RN Text 的 letterSpacing（dp）；已按 fontScale 折算。 */
  letterSpacing: number;
  /** 可拉伸的字符间隙数；用于测试和诊断。 */
  gapCount: number;
}

export function runsToText(runs: readonly JustifyRun[]): string {
  return runs.map((run) => run.text).join('');
}

/**
 * 统计可拉伸的字符数。
 *
 * Android 的 `LineInfo.getClusterCount()` 按字形簇计数；协议正文以中日韩文字和
 * ASCII 为主，每个码点就是一个字形簇。这里用码点计数即可覆盖契约范围；
 * 组合附加符号或 ZWJ emoji 会多算，最坏结果是该行略短，不会越界。
 */
export function countClusters(text: string): number {
  return Array.from(text).length;
}

/** 按 UTF-16 偏移切出 runs 的子集，保留 bold 边界。 */
export function sliceRuns(
  runs: readonly JustifyRun[],
  start: number,
  end: number,
): JustifyRun[] {
  if (end <= start) {
    return [];
  }
  const sliced: JustifyRun[] = [];
  let offset = 0;
  for (const run of runs) {
    const runStart = offset;
    const runEnd = offset + run.text.length;
    const from = Math.max(start, runStart);
    const to = Math.min(end, runEnd);
    if (to > from) {
      sliced.push({ text: run.text.slice(from - runStart, to - runStart), bold: run.bold });
    }
    offset = runEnd;
  }
  return sliced;
}

/**
 * 把 RN 给出的自然折行映射回原始 runs。
 *
 * `onTextLayout` 只返回每行文本，不返回行列 span；这里按顺序在原文里定位每行。
 * 协议正文以中文为主，折行多发生在字符之间；折行点也可能落在空格上
 * （如纯英文段落）。该空格属于原文：平台若未把它计入某一行，按原文
 * 把它归到前一行；行尾剩余的空格并入最后一行。
 * 定位失败（文本被平台改写、行数异常）时返回 null，由调用方回退到系统 justify。
 */
export function buildLineDescriptors(
  runs: readonly JustifyRun[],
  measuredLines: readonly MeasuredLineLike[],
): LineDescriptor[] | null {
  if (measuredLines.length === 0) {
    return null;
  }

  const fullText = runsToText(runs);
  const drafts: { start: number; end: number; isLast: boolean }[] = [];
  let cursor = 0;

  for (let index = 0; index < measuredLines.length; index += 1) {
    const raw = measuredLines[index].text;
    let start = cursor;

    if (!fullText.startsWith(raw, cursor)) {
      const found = fullText.indexOf(raw, cursor);
      if (found < 0) {
        return null;
      }
      start = found;
    }

    if (start > cursor) {
      const skipped = fullText.slice(cursor, start);
      const previous = drafts[drafts.length - 1];
      if (skipped.trim().length > 0 || !previous) {
        return null;
      }
      // 平台可能未把折行处的空格算进某一行；按原文归到前一行。
      previous.end = start;
    }

    const end = start + raw.length;
    drafts.push({ start, end, isLast: index === measuredLines.length - 1 });
    cursor = end;
  }

  if (cursor < fullText.length) {
    const rest = fullText.slice(cursor);
    const last = drafts[drafts.length - 1];
    if (!last || rest.trim().length > 0) {
      return null;
    }
    // 末尾剩余空白字符：并入最后一行，原文不丢。
    last.end = fullText.length;
  }

  return drafts.map((draft) => ({
    runs: sliceRuns(runs, draft.start, draft.end),
    text: fullText.slice(draft.start, draft.end),
    isLast: draft.isLast,
  }));
}

/**
 * 把行尾最后一个字符从 runs 中分离出来。
 *
 * 字间距只存在于相邻字符之间的间隙里；行尾字符之后没有"下一个字符"，
 * 不需要间距。把它单独成 span 后，行宽精确等于
 * 自然行宽 + 间距 × (字符数 − 1) = 容器宽度。
 * 整行只有一个字符时无需拆分，返回 tail 为 null。
 */
export function splitTrailingChar(
  runs: readonly JustifyRun[],
): { head: JustifyRun[]; tail: JustifyRun | null } {
  const text = runsToText(runs);
  const chars = Array.from(text);
  if (chars.length <= 1) {
    return { head: [], tail: null };
  }
  const tailChar = chars[chars.length - 1];
  const tailStart = text.length - tailChar.length;
  return {
    head: sliceRuns(runs, 0, tailStart),
    tail: sliceRuns(runs, tailStart, text.length)[0] ?? null,
  };
}

/**
 * 计算一行需要追加的 letterSpacing。
 *
 * `fontScale` 的折算来自 RN 的实现：`letterSpacing` prop 会按 SP 缩放
 * （`PixelUtil.toPixelFromSP`），而 `onTextLayout` 的宽度已经包含系统字号缩放。
 * 因此要让屏幕上的实际间距为 `extra / gapCount` dp，需要再除以 fontScale。
 */
export function computeLetterSpacing(
  naturalWidth: number,
  targetWidth: number,
  gapCount: number,
  fontScale: number,
): number {
  if (gapCount < 1 || !(fontScale > 0)) {
    return 0;
  }
  const extra = targetWidth - naturalWidth;
  if (!Number.isFinite(extra) || extra <= 0) {
    return 0;
  }
  return extra / gapCount / fontScale;
}

/**
 * 由 `onTextLayout` 得到的自然行宽生成最终排版。
 *
 * 返回 null 表示测量结果不可信（行数/宽度异常）；自然行宽超过容器时
 * 不压缩字形，spacing 置 0，交给最终 Text 的宽度余量处理。
 */
export function buildJustifiedLines(
  descriptors: readonly LineDescriptor[],
  naturalWidths: readonly number[],
  targetWidth: number,
  fontScale: number,
): JustifiedLine[] | null {
  if (descriptors.length !== naturalWidths.length) {
    return null;
  }
  if (!Number.isFinite(targetWidth) || targetWidth <= 0) {
    return null;
  }

  const result: JustifiedLine[] = [];
  for (let index = 0; index < descriptors.length; index += 1) {
    const descriptor = descriptors[index];
    const width = naturalWidths[index];
    if (!Number.isFinite(width) || width < 0) {
      return null;
    }

    const gapCount = Math.max(0, countClusters(descriptor.text) - 1);
    result.push({
      ...descriptor,
      gapCount,
      letterSpacing: descriptor.isLast
        ? 0
        : computeLetterSpacing(width, targetWidth, gapCount, fontScale),
    });
  }
  return result;
}

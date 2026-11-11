/**
 * Android 字符级两端对齐（issue #313）。
 *
 * 本模块逐行复刻 AOSP `android-15.0.0_r1` 的字符级 justification：
 *
 * 1. `TextLine.isLineEndSpace(char)`（TextLine.java:1872-1877）
 *    —— 行尾空格的精确字符集；
 * 2. `Layout.getLineVisibleEnd(..., trailingSpaceAtLastLineIsVisible=true)`
 *    （Layout.java:793-794、2753-2776）——段落末行保留行尾空格，
 *    其余可见行裁掉行尾空格；
 * 3. `TextLine.justify` 的 `JUSTIFICATION_MODE_LETTER_SPACING` 分支
 *    （TextLine.java:293-329）——裁剪后测量、字形簇计数、
 *    `(justifyWidth - width) / (lettersCount - 1)`，以及 0.03 阈值。
 *
 * 平台差异：AOSP 在 `mAddedLetterSpacingInPx > 0.03` 时关闭连字
 * （`"liga" off, "cliga" off`）并重新测量；RN `Text` 不暴露 OpenType
 * feature 设置，无法执行该重测。中文正文没有连字，该差异只影响含连字的
 * 拉丁文本；`justifyLine` 用 `ligatureDisabled` 如实标记该分支已命中。
 *
 * 本模块只做纯计算，不依赖 React Native；宽度与字号由调用方换算成
 * 与 AOSP 一致的像素单位传入。
 */

export interface JustifyRun {
  text: string;
  bold: boolean;
}

export interface MeasuredLineLike {
  text: string;
}

export interface LineDescriptor {
  /** 该显示行的 runs（已按可见行尾裁剪）。 */
  runs: JustifyRun[];
  /** 该显示行的可见文本；末行按 AOSP 保留行尾空格。 */
  text: string;
  /** 是否为该段落的最后一个显示行。 */
  isLast: boolean;
}

export interface JustifyLineInput {
  /** 该行文本（调用方可先裁剪；本函数会按 AOSP 再裁剪一次）。 */
  text: string;
  /** `measure(end)` 的结果，单位与 AOSP 一致（像素）。 */
  widthPx: number;
  /** 行可用宽度（像素）。 */
  justifyWidthPx: number;
  /** 文本字号（像素，含系统字号缩放）。 */
  textSizePx: number;
}

export interface JustifyLineResult {
  /** 裁剪行尾空格后的可见文本。 */
  text: string;
  /** `LineInfo.getClusterCount()` 的字形簇数。 */
  lettersCount: number;
  /** `mAddedLetterSpacingInPx`。 */
  spacingPx: number;
  /** `mAddedLetterSpacingInPx / textSize`（em）。 */
  spacingEm: number;
  /** AOSP 的 >0.03 分支是否命中；RN 无法执行其连字关闭重测。 */
  ligatureDisabled: boolean;
}

export interface JustifiedLine extends LineDescriptor {
  /** 传给 RN Text 的 letterSpacing（dp）；已按 fontScale 与屏幕密度折算。 */
  letterSpacing: number;
  /** AOSP 的 mAddedLetterSpacingInPx。 */
  spacingPx: number;
  /** 字形簇数。 */
  lettersCount: number;
  /** 是否命中 AOSP 的连字关闭分支（RN 未执行其重测）。 */
  ligatureDisabled: boolean;
}

/**
 * `TextLine.isLineEndSpace(char)` 的逐字复刻。
 *
 * AOSP 使用 UTF-16 `char`；这里同样只取第一个 code unit，不按码点处理。
 */
export function isLineEndSpace(ch: string): boolean {
  const code = ch.charCodeAt(0);
  return (
    code === 0x20 ||
    code === 0x09 ||
    code === 0x1680 ||
    (code >= 0x2000 && code <= 0x200a && code !== 0x2007) ||
    code === 0x205f ||
    code === 0x3000
  );
}

/** 按 AOSP 的行尾字符集裁掉行尾空格。 */
export function trimLineEndSpaces(text: string): string {
  let end = text.length;
  while (end > 0 && isLineEndSpace(text.charAt(end - 1))) {
    end -= 1;
  }
  return text.slice(0, end);
}

/**
 * `Layout.getLineVisibleEnd(..., trailingSpaceAtLastLineIsVisible=true)`。
 *
 * 段落最后一个显示行保留行尾空格；其余行裁掉行尾空格。
 */
export function visibleLineText(text: string, isLastLineOfParagraph: boolean): string {
  return isLastLineOfParagraph ? text : trimLineEndSpaces(text);
}

/**
 * `LineInfo.getClusterCount()` 的复刻。
 *
 * Android 按字形簇计数；协议正文以中日韩文字和 ASCII 为主，每个码点即一个
 * 字形簇，因此这里用码点计数。若正文引入组合附加符号或 ZWJ emoji，需要
 * 替换为 UAX #29 字形簇分割才能保持与系统一致。
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

export function runsToText(runs: readonly JustifyRun[]): string {
  return runs.map((run) => run.text).join('');
}

/**
 * 把 RN 给出的自然折行映射回原始 runs，并应用 AOSP 的可见行尾规则。
 *
 * `onTextLayout` 按平台折行返回每行文本；这里按顺序在原文里定位每行。
 * 非末行裁掉行尾空格（Layout.getLineVisibleEnd），末行保留（同 AOSP 的
 * `trailingSpaceAtLastLineIsVisible=true`）。
 * 定位失败（文本被平台改写、行数异常）时返回 null，由调用方回退。
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
    last.end = fullText.length;
  }

  return drafts.map((draft) => {
    const raw = fullText.slice(draft.start, draft.end);
    const text = visibleLineText(raw, draft.isLast);
    return {
      runs: sliceRuns(runs, draft.start, draft.start + text.length),
      text,
      isLast: draft.isLast,
    };
  });
}

/**
 * `TextLine.justify` 的 `JUSTIFICATION_MODE_LETTER_SPACING` 分支复刻。
 *
 * 行尾空格先按 `isLineEndSpace` 裁掉；少于 2 个字形簇时 AOSP 直接返回
 * （不设置间距），这里返回 null。间距公式与 0.03 阈值逐行对应：
 *
 *   mAddedLetterSpacingInPx = (justifyWidth - width) / (lettersCount - 1)
 *   if (mAddedLetterSpacingInPx > 0.03) { 关闭连字并重测 }
 */
export function justifyLine(input: JustifyLineInput): JustifyLineResult | null {
  const text = trimLineEndSpaces(input.text);
  const lettersCount = countClusters(text);
  if (lettersCount < 2) {
    return null;
  }
  const spacingPx = (input.justifyWidthPx - input.widthPx) / (lettersCount - 1);
  return {
    text,
    lettersCount,
    spacingPx,
    spacingEm: spacingPx / input.textSizePx,
    ligatureDisabled: spacingPx > 0.03,
  };
}

/**
 * 按 AOSP 公式为每一行生成最终排版参数。
 *
 * - 末行不参与 justification（Layout.isJustificationRequired 为 false）；
 * - 非末行调用 `justifyLine`；`lettersCount < 2` 时 AOSP 直接返回，
 *   对应 spacing 0；
 * - `fontScale`/`density` 用于把 AOSP 的像素间距换算成 RN `letterSpacing`
 *   prop（RN 的 prop 按 SP 缩放，实际 em = prop / fontSize）。
 */
export function buildJustifiedLines(
  descriptors: readonly LineDescriptor[],
  naturalWidthsPx: readonly number[],
  justifyWidthPx: number,
  textSizePx: number,
  fontScale: number,
  density: number,
): JustifiedLine[] | null {
  if (descriptors.length !== naturalWidthsPx.length) {
    return null;
  }
  if (
    !Number.isFinite(justifyWidthPx) ||
    justifyWidthPx <= 0 ||
    !(textSizePx > 0) ||
    !(fontScale > 0) ||
    !(density > 0)
  ) {
    return null;
  }

  const result: JustifiedLine[] = [];
  for (let index = 0; index < descriptors.length; index += 1) {
    const descriptor = descriptors[index];
    const widthPx = naturalWidthsPx[index];
    if (!Number.isFinite(widthPx) || widthPx < 0) {
      return null;
    }

    if (descriptor.isLast) {
      result.push({
        ...descriptor,
        letterSpacing: 0,
        spacingPx: 0,
        lettersCount: countClusters(descriptor.text),
        ligatureDisabled: false,
      });
      continue;
    }

    const justified = justifyLine({
      text: descriptor.text,
      widthPx,
      justifyWidthPx,
      textSizePx,
    });
    if (!justified) {
      result.push({
        ...descriptor,
        letterSpacing: 0,
        spacingPx: 0,
        lettersCount: countClusters(descriptor.text),
        ligatureDisabled: false,
      });
      continue;
    }

    result.push({
      ...descriptor,
      text: justified.text,
      letterSpacing: justified.spacingPx / (fontScale * density),
      spacingPx: justified.spacingPx,
      lettersCount: justified.lettersCount,
      ligatureDisabled: justified.ligatureDisabled,
    });
  }
  return result;
}

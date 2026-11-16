export interface JustifyRun {
  text: string;
  bold: boolean;
}

export interface MeasuredLineLike {
  text: string;
}

export interface LineDescriptor {
  displayRuns: JustifyRun[];
  visibleRuns: JustifyRun[];
  trailingRuns: JustifyRun[];
  visibleText: string;
  trailingText: string;
  displayText: string;
  isLast: boolean;
}

export interface JustifiedLine extends LineDescriptor {
  letterSpacing: number;
  codePointCount: number;
}

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

export function trimLineEndSpaces(text: string): string {
  let end = text.length;
  while (end > 0 && isLineEndSpace(text.charAt(end - 1))) {
    end -= 1;
  }
  return text.slice(0, end);
}

export function countCodePoints(text: string): number {
  return Array.from(text).length;
}

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
    const displayText = fullText.slice(draft.start, draft.end);
    const visibleText = draft.isLast ? displayText : trimLineEndSpaces(displayText);
    const trailingText = displayText.slice(visibleText.length);
    return {
      displayRuns: sliceRuns(runs, draft.start, draft.end),
      visibleRuns: sliceRuns(runs, draft.start, draft.start + visibleText.length),
      trailingRuns: sliceRuns(runs, draft.start + visibleText.length, draft.end),
      visibleText,
      trailingText,
      displayText,
      isLast: draft.isLast,
    };
  });
}

export function computeLetterSpacing(
  visibleWidth: number,
  containerWidth: number,
  codePointCount: number,
  fontScale: number,
): number {
  if (
    !Number.isFinite(visibleWidth) ||
    visibleWidth < 0 ||
    !Number.isFinite(containerWidth) ||
    containerWidth <= 0 ||
    !(codePointCount >= 2) ||
    !(fontScale > 0)
  ) {
    return 0;
  }
  const extra = containerWidth - visibleWidth;
  if (!(extra > 0)) {
    return 0;
  }
  return extra / (codePointCount - 1) / fontScale;
}

export function usesNativeJustification(line: LineDescriptor): boolean {
  return line.isLast || /\S +\S/u.test(line.visibleText);
}

export function buildJustifiedLines(
  descriptors: readonly LineDescriptor[],
  visibleWidths: readonly number[],
  containerWidth: number,
  fontScale: number,
): JustifiedLine[] | null {
  if (
    descriptors.length !== visibleWidths.length ||
    !Number.isFinite(containerWidth) ||
    containerWidth <= 0 ||
    !(fontScale > 0)
  ) {
    return null;
  }

  const result: JustifiedLine[] = [];
  for (let index = 0; index < descriptors.length; index += 1) {
    const descriptor = descriptors[index];
    const visibleWidth = visibleWidths[index];
    if (!Number.isFinite(visibleWidth) || visibleWidth < 0) {
      return null;
    }

    const codePointCount = countCodePoints(descriptor.visibleText);
    result.push({
      ...descriptor,
      codePointCount,
      letterSpacing: usesNativeJustification(descriptor)
        ? 0
        : computeLetterSpacing(visibleWidth, containerWidth, codePointCount, fontScale),
    });
  }
  return result;
}

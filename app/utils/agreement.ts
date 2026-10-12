export const AGREEMENT_FORMAT = 'agreement.richtext.v1';
export const DEFAULT_BLOCK_FONT_SIZE = 16;
export const MIN_BLOCK_FONT_SIZE = 12;
export const MAX_BLOCK_FONT_SIZE = 32;

export const ALIGN_CENTER = 'center';
export const ALIGN_JUSTIFY = 'justify';

const TOP_LEVEL_KEYS = new Set(['version', 'title', 'format', 'blocks']);
const BLOCK_KEYS = new Set(['font_size', 'align', 'runs']);
const RUN_KEYS = new Set(['text', 'bold']);

export interface AgreementRun {
  text: string;
  bold?: boolean;
}

export interface AgreementBlock {
  font_size?: number;
  align?: typeof ALIGN_CENTER | typeof ALIGN_JUSTIFY;
  runs: AgreementRun[];
}

export interface AgreementPayload {
  version: string;
  title: string;
  format: typeof AGREEMENT_FORMAT;
  blocks: AgreementBlock[];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function hasOnlyKeys(value: Record<string, unknown>, allowed: Set<string>): boolean {
  return Object.keys(value).every((key) => allowed.has(key));
}

export function parseAgreementPayload(value: unknown): AgreementPayload | null {
  if (!isRecord(value) || !hasOnlyKeys(value, TOP_LEVEL_KEYS)) {
    return null;
  }
  if (typeof value.version !== 'string' || value.version.length === 0) {
    return null;
  }
  if (typeof value.title !== 'string' || value.title.trim().length === 0) {
    return null;
  }
  if (value.format !== AGREEMENT_FORMAT || !Array.isArray(value.blocks) || value.blocks.length === 0) {
    return null;
  }

  let hasText = false;
  const blocks: AgreementBlock[] = [];
  for (const candidate of value.blocks) {
    if (!isRecord(candidate) || !hasOnlyKeys(candidate, BLOCK_KEYS)) {
      return null;
    }

    const fontSize = Object.hasOwn(candidate, 'font_size')
      ? candidate.font_size
      : DEFAULT_BLOCK_FONT_SIZE;
    if (
      typeof fontSize !== 'number' ||
      !Number.isInteger(fontSize) ||
      fontSize < MIN_BLOCK_FONT_SIZE ||
      fontSize > MAX_BLOCK_FONT_SIZE
    ) {
      return null;
    }

    const align = Object.hasOwn(candidate, 'align') ? candidate.align : ALIGN_JUSTIFY;
    if (align !== ALIGN_CENTER && align !== ALIGN_JUSTIFY) {
      return null;
    }
    if (!Array.isArray(candidate.runs) || candidate.runs.length === 0) {
      return null;
    }

    const runs: AgreementRun[] = [];
    for (const runCandidate of candidate.runs) {
      if (!isRecord(runCandidate) || !hasOnlyKeys(runCandidate, RUN_KEYS)) {
        return null;
      }
      if (typeof runCandidate.text !== 'string') {
        return null;
      }
      const bold = Object.hasOwn(runCandidate, 'bold') ? runCandidate.bold : false;
      if (typeof bold !== 'boolean') {
        return null;
      }
      hasText ||= runCandidate.text.trim().length > 0;
      runs.push({ text: runCandidate.text, bold });
    }

    blocks.push({ font_size: fontSize, align, runs });
  }

  if (!hasText) {
    return null;
  }

  return {
    version: value.version,
    title: value.title,
    format: AGREEMENT_FORMAT,
    blocks,
  };
}

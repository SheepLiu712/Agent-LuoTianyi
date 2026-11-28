import * as DocumentPicker from 'expo-document-picker';
import * as FileSystem from 'expo-file-system/legacy';
import * as Sharing from 'expo-sharing';
import type { AccountSession } from '../account/credentials';

export type TransferScope = 'all' | 'chat' | 'memory';
export type ExportFormat = 'zip' | 'markdown' | 'txt';
export type SourceFormat = 'auto' | 'native' | 'chatgpt' | 'sillytavern' | 'generic';
export type ImportMode = 'merge' | 'replace';

export interface TransferCounts {
  conversations: number;
  memories: number;
  media?: number;
}

export interface ImportPreview {
  preview_id: string;
  source_format: Exclude<SourceFormat, 'auto'>;
  scope: TransferScope;
  counts: TransferCounts;
  warnings: string[];
}

export interface ImportExtraction {
  status: 'not_requested' | 'succeeded' | 'failed' | 'unavailable';
  memories: number;
  error?: string;
}

export interface ImportResult {
  success: boolean;
  committed: boolean;
  failed_phase: 'commit' | null;
  imported?: TransferCounts;
  skipped?: TransferCounts;
  backup_id?: string | null;
  extraction?: ImportExtraction;
  warnings?: string[];
  error?: string;
  rollback_error?: string | null;
}

const MAX_IMPORT_BYTES = 1024 * 1024 * 1024;
const EXPORT_FILES: Record<ExportFormat, { extension: string; mimeType: string }> = {
  zip: { extension: 'zip', mimeType: 'application/zip' },
  markdown: { extension: 'md', mimeType: 'text/markdown' },
  txt: { extension: 'txt', mimeType: 'text/plain' },
};

export class DataTransferError extends Error {
  constructor(message: string, readonly status?: number, readonly backupId?: string) {
    super(message);
  }
}

function httpError(status: number, detail?: unknown) {
  const messages: Record<number, string> = {
    400: '请求或数据文件无效，请检查所选文件和格式。',
    401: '登录已失效，请重新登录后再试。',
    403: '当前账号无权访问这份数据。',
    404: '预览或备份不存在。请重新预览文件，或确认备份仍可用。',
    409: '当前操作冲突。请等通话或数据操作结束后再试，预览失效时请重新预览。',
    410: '预览已过期，请重新选择文件。',
    413: '文件超过服务端限制，上传上限为 1 GiB。',
    422: '文件内容或选项无法验证，请确认文件格式和导入范围。',
  };
  const problem = typeof detail === 'object' && detail !== null ? detail as { code?: unknown; backup_id?: unknown } : undefined;
  const explanation = typeof detail === 'string' ? detail : problem?.code;
  const backupId = typeof problem?.backup_id === 'string' ? problem.backup_id : undefined;
  const message = messages[status] ?? `服务器请求失败（HTTP ${status}）。`;
  return new DataTransferError(
    status < 500 && typeof explanation === 'string' ? `${message}\n${explanation.slice(0, 500)}` : message,
    status,
    backupId,
  );
}

function parseResponse<T>(text: string, status: number): T {
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch {
    if (status < 200 || status >= 300) throw httpError(status);
    throw new DataTransferError('服务器未返回有效的数据结果。');
  }
  if (status < 200 || status >= 300) {
    throw httpError(status, (data as { detail?: unknown } | null)?.detail);
  }
  if (!data || typeof data !== 'object' || Array.isArray(data)) {
    throw new DataTransferError('服务器未返回有效的数据结果。');
  }
  return data as T;
}

function validCounts(counts: TransferCounts | null | undefined): boolean {
  return Boolean(counts && Number.isInteger(counts.conversations) && Number.isInteger(counts.memories)
    && (counts.media === undefined || Number.isInteger(counts.media)));
}

function validWarnings(warnings: unknown): boolean {
  return Array.isArray(warnings) && warnings.every(warning => typeof warning === 'string');
}

function transferUrl(session: AccountSession, path: string) {
  return `${session.serverUrl.replace(/\/+$/, '')}/user/data${path}`;
}

function bearer(session: AccountSession) {
  return { Authorization: `Bearer ${session.token}` };
}

export async function pickImportFile() {
  const result = await DocumentPicker.getDocumentAsync({
    type: '*/*',
    copyToCacheDirectory: true,
    multiple: false,
    base64: false,
  });
  return result.canceled ? null : result.assets[0] ?? null;
}

export async function previewImport(
  session: AccountSession,
  file: DocumentPicker.DocumentPickerAsset,
  source: SourceFormat,
  scope: TransferScope,
  characterId: string,
): Promise<ImportPreview> {
  const isCacheCopy = FileSystem.cacheDirectory && file.uri.startsWith(FileSystem.cacheDirectory);
  try {
    if (file.size !== undefined && file.size > MAX_IMPORT_BYTES) throw httpError(413);
    if (!file.uri.startsWith('file://')) {
      throw new DataTransferError('无法读取所选文件。请先将文件保存到设备，再重新选择。');
    }
    const info = await FileSystem.getInfoAsync(file.uri);
    if (!info.exists || info.isDirectory) throw new DataTransferError('所选文件不可读取，请重新选择。');
    if (info.size > MAX_IMPORT_BYTES) throw httpError(413);

    const query = new URLSearchParams({ source_format: source, scope, character_id: characterId });
    const response = await FileSystem.uploadAsync(transferUrl(session, `/import/preview?${query}`), file.uri, {
      httpMethod: 'POST',
      uploadType: FileSystem.FileSystemUploadType.BINARY_CONTENT,
      headers: { ...bearer(session), 'Content-Type': 'application/octet-stream' },
    });
    const preview = parseResponse<ImportPreview>(response.body, response.status);
    if (typeof preview.preview_id !== 'string' || !preview.preview_id || !validCounts(preview.counts)
      || !validWarnings(preview.warnings)
      || !(preview.scope === 'chat' || preview.scope === 'memory' || preview.scope === 'all')
      || !(['native', 'chatgpt', 'sillytavern', 'generic'] as const).includes(preview.source_format)) {
      throw new DataTransferError('服务器未返回有效的文件预览。');
    }
    return preview;
  } finally {
    if (isCacheCopy) await FileSystem.deleteAsync(file.uri, { idempotent: true }).catch(() => undefined);
  }
}

export async function commitImport(
  session: AccountSession,
  previewId: string,
  mode: ImportMode,
  confirmReplace: boolean,
  extractMemories: boolean,
): Promise<ImportResult> {
  if (mode === 'replace' && !confirmReplace) throw new DataTransferError('请先确认本次替换操作。');
  const response = await fetch(transferUrl(session, '/import/commit'), {
    method: 'POST',
    headers: { ...bearer(session), 'Content-Type': 'application/json' },
    body: JSON.stringify({
      preview_id: previewId,
      mode,
      confirm_replace: mode === 'replace' && confirmReplace,
      extract_memories: extractMemories,
    }),
  });
  const result = parseResponse<ImportResult>(await response.text(), response.status);
  const validCommitted = result.success === true && result.committed === true && result.failed_phase === null
    && validCounts(result.imported) && validCounts(result.skipped) && result.extraction
    && (['not_requested', 'succeeded', 'failed', 'unavailable'] as const).includes(result.extraction.status)
    && Number.isInteger(result.extraction.memories) && validWarnings(result.warnings);
  const validFailed = result.success === false && result.committed === false && result.failed_phase === 'commit';
  if (!validCommitted && !validFailed) {
    throw new DataTransferError('服务器未返回完整的导入结果。');
  }
  return result;
}

interface TransferFile {
  uri: string;
  mimeType: string;
}

async function downloadFile(session: AccountSession, path: string, name: string, format: ExportFormat): Promise<TransferFile> {
  if (!FileSystem.cacheDirectory) throw new DataTransferError('应用缓存不可用，无法下载文件。');
  const directory = `${FileSystem.cacheDirectory}data-transfer/`;
  await FileSystem.makeDirectoryAsync(directory, { intermediates: true });
  const stamp = new Date().toISOString().replace(/[:.]/g, '-');
  const { extension, mimeType } = EXPORT_FILES[format];
  const uri = `${directory}${name}-${stamp}.${extension}`;
  try {
    const task = FileSystem.createDownloadResumable(transferUrl(session, path), uri, { headers: bearer(session) });
    const response = await task.downloadAsync();
    if (!response) throw new DataTransferError('文件下载未完成，请重试。');
    if (response.status !== 200) throw httpError(response.status);
    return { uri: response.uri, mimeType };
  } catch (error) {
    await FileSystem.deleteAsync(uri, { idempotent: true }).catch(() => undefined);
    throw error;
  }
}

export function downloadExport(session: AccountSession, scope: TransferScope, format: ExportFormat) {
  const query = new URLSearchParams({ scope, format });
  return downloadFile(session, `/export?${query}`, `agentluo-${scope}`, format);
}

export function downloadBackup(session: AccountSession, backupId: string) {
  return downloadFile(session, `/backups/${encodeURIComponent(backupId)}`, 'agentluo-backup', 'zip');
}

export async function shareTransferFile(file: TransferFile) {
  if (!(await Sharing.isAvailableAsync())) throw new DataTransferError('此设备无法打开系统分享。');
  // 系统分享返回后，接收应用仍可能读取此文件，因此由系统回收应用缓存。
  await Sharing.shareAsync(file.uri, { dialogTitle: '保存或分享文件', mimeType: file.mimeType });
}

import * as DocumentPicker from 'expo-document-picker';
import * as FileSystem from 'expo-file-system/legacy';
import * as Sharing from 'expo-sharing';
import {
  commitImport, DataTransferError, downloadBackup, downloadExport, pickImportFile, previewImport, shareTransferFile,
} from '../../features/data-transfer/dataTransferApi';

jest.mock('expo-document-picker', () => ({ getDocumentAsync: jest.fn() }));
jest.mock('expo-sharing', () => ({ isAvailableAsync: jest.fn(), shareAsync: jest.fn() }));
jest.mock('expo-file-system/legacy', () => ({
  cacheDirectory: 'file:///cache/', FileSystemUploadType: { BINARY_CONTENT: 0 },
  getInfoAsync: jest.fn(), uploadAsync: jest.fn(), createDownloadResumable: jest.fn(),
  makeDirectoryAsync: jest.fn().mockResolvedValue(undefined), deleteAsync: jest.fn().mockResolvedValue(undefined),
}));

const session = { username: 'current', token: 'session-token', serverUrl: 'https://chosen-server/' };
const file = { uri: 'file:///cache/picked.zip', name: 'picked.zip', size: 1024, mimeType: 'application/zip', lastModified: 0 };
const preview = { preview_id: 'preview-1', source_format: 'native', scope: 'all',
  counts: { conversations: 3, memories: 1, media: 2 }, warnings: [] };
const committed = { success: true, committed: true, failed_phase: null, imported: preview.counts,
  skipped: { conversations: 0, memories: 0 }, backup_id: 'backup-1',
  extraction: { status: 'not_requested', memories: 0 }, warnings: [] };
const originalFetch = global.fetch;
const fetchMock = jest.fn();
const downloadAsync = jest.fn();

beforeEach(() => {
  jest.clearAllMocks();
  global.fetch = fetchMock;
  jest.mocked(FileSystem.getInfoAsync).mockResolvedValue({ exists: true, isDirectory: false, size: 1024, uri: file.uri } as any);
  jest.mocked(FileSystem.uploadAsync).mockResolvedValue({ status: 200, body: JSON.stringify(preview), headers: {}, mimeType: 'application/json' });
  jest.mocked(FileSystem.createDownloadResumable).mockReturnValue({ downloadAsync } as any);
  downloadAsync.mockResolvedValue({ status: 200, uri: 'file:///cache/download.zip' });
  jest.mocked(Sharing.isAvailableAsync).mockResolvedValue(true);
  fetchMock.mockResolvedValue({ status: 200, text: async () => JSON.stringify(committed) });
});
afterAll(() => { global.fetch = originalFetch; });

it('系统选择文件不请求Base64；取消选择不产生预览', async () => {
  jest.mocked(DocumentPicker.getDocumentAsync).mockResolvedValue({ canceled: true, assets: null });
  expect(await pickImportFile()).toBeNull();
  expect(DocumentPicker.getDocumentAsync).toHaveBeenCalledWith({
    type: '*/*', copyToCacheDirectory: true, multiple: false, base64: false,
  });
  expect(FileSystem.uploadAsync).not.toHaveBeenCalled();
});

it('以文件URI原生二进制POST预览，仅使用session Bearer并释放选取的缓存副本', async () => {
  expect(await previewImport(session, file, 'auto', 'all', 'luotianyi')).toEqual(preview);
  const [url, uri, options] = jest.mocked(FileSystem.uploadAsync).mock.calls[0];
  expect(url).toBe('https://chosen-server/user/data/import/preview?source_format=auto&scope=all&character_id=luotianyi');
  expect(uri).toBe(file.uri);
  expect(options).toEqual({ httpMethod: 'POST', uploadType: 0,
    headers: { Authorization: 'Bearer session-token', 'Content-Type': 'application/octet-stream' } });
  expect(FileSystem.deleteAsync).toHaveBeenCalledWith(file.uri, { idempotent: true });
  expect(fetchMock).not.toHaveBeenCalled();
});

it('1GiB超限在上传前拒绝，磁盘真实大小也受限制', async () => {
  await expect(previewImport(session, { ...file, size: 1024 * 1024 * 1024 + 1 }, 'auto', 'all', 'luotianyi'))
    .rejects.toMatchObject({ status: 413 });
  jest.mocked(FileSystem.getInfoAsync).mockResolvedValue({ exists: true, isDirectory: false, size: 1024 * 1024 * 1024 + 1 } as any);
  await expect(previewImport(session, file, 'native', 'all', 'luotianyi')).rejects.toMatchObject({ status: 413 });
  expect(FileSystem.uploadAsync).not.toHaveBeenCalled();
});

it('预览鉴权失败保留HTTP语义，读取失败不删除外部原文件', async () => {
  jest.mocked(FileSystem.uploadAsync).mockResolvedValue({ status: 401, body: '{"detail":"expired"}', headers: {}, mimeType: 'application/json' });
  await expect(previewImport(session, { ...file, uri: 'file:///documents/original.zip' }, 'auto', 'all', 'luotianyi'))
    .rejects.toMatchObject({ status: 401 });
  expect(FileSystem.deleteAsync).not.toHaveBeenCalled();
});

it('未确认替换不请求；提交JSON保持所选提取布尔值并不指定目标用户', async () => {
  await expect(commitImport(session, 'preview-1', 'replace', false, true)).rejects.toThrow('请先确认');
  expect(fetchMock).not.toHaveBeenCalled();
  expect(await commitImport(session, 'preview-1', 'replace', true, true)).toEqual(committed);
  expect(fetchMock).toHaveBeenCalledWith('https://chosen-server/user/data/import/commit', {
    method: 'POST', headers: { Authorization: 'Bearer session-token', 'Content-Type': 'application/json' },
    body: JSON.stringify({ preview_id: 'preview-1', mode: 'replace', confirm_replace: true, extract_memories: true }),
  });
});

it('HTTP200业务失败保留备份、错误和未提交状态', async () => {
  const failed = { success: false, committed: false, failed_phase: 'commit', backup_id: 'rescue', error: 'prepare_failed' };
  fetchMock.mockResolvedValue({ status: 200, text: async () => JSON.stringify(failed) });
  expect(await commitImport(session, 'preview-1', 'replace', true, false)).toEqual(failed);
});

it('异常HTTP的恢复备份仍携带到页面；拒绝缺字段的成功结果', async () => {
  fetchMock.mockResolvedValue({ status: 500, text: async () => JSON.stringify({ detail: { backup_id: 'rescue' } }) });
  await expect(commitImport(session, 'preview-1', 'replace', true, false)).rejects.toMatchObject({ backupId: 'rescue', status: 500 });
  fetchMock.mockResolvedValue({ status: 200, text: async () => JSON.stringify({ success: true }) });
  await expect(commitImport(session, 'preview-1', 'merge', false, false)).rejects.toBeInstanceOf(DataTransferError);
});

it('导出与备份原生流式下载后分享本地URI，错误文件不可分享', async () => {
  const exported = await downloadExport(session, 'memory', 'markdown');
  expect(FileSystem.createDownloadResumable).toHaveBeenLastCalledWith(
    'https://chosen-server/user/data/export?scope=memory&format=markdown', expect.stringMatching(/\.md$/),
    { headers: { Authorization: 'Bearer session-token' } },
  );
  await shareTransferFile(exported);
  expect(Sharing.shareAsync).toHaveBeenCalledWith('file:///cache/download.zip', { dialogTitle: '保存或分享文件', mimeType: 'text/markdown' });
  await downloadBackup(session, 'backup/with space');
  expect(FileSystem.createDownloadResumable).toHaveBeenLastCalledWith(
    'https://chosen-server/user/data/backups/backup%2Fwith%20space', expect.stringMatching(/\.zip$/), expect.any(Object),
  );
  downloadAsync.mockResolvedValue({ status: 409 });
  await expect(downloadExport(session, 'all', 'zip')).rejects.toMatchObject({ status: 409 });
  expect(FileSystem.deleteAsync).toHaveBeenCalledWith(expect.stringMatching(/data-transfer\/.*\.zip$/), { idempotent: true });
});


it('超过旧64MiB的文件仍通过原生文件上传，不读取Base64到内存', async () => {
  const size = 65 * 1024 * 1024;
  jest.mocked(FileSystem.getInfoAsync).mockResolvedValue({ exists: true, isDirectory: false, size } as any);
  await expect(previewImport(session, { ...file, size }, 'native', 'all', 'luotianyi')).resolves.toMatchObject({ preview_id: 'preview-1' });
  expect(FileSystem.uploadAsync).toHaveBeenCalled();
  expect(fetchMock).not.toHaveBeenCalled();
});

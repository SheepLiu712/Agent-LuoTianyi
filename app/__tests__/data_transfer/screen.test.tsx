import React from 'react';
import { act, create, type ReactTestRenderer } from 'react-test-renderer';
import { BackHandler, Modal, Pressable, Switch, Text, useWindowDimensions } from 'react-native';
import { DataTransferScreen } from '../../features/data-transfer/DataTransferScreen';
import * as api from '../../features/data-transfer/dataTransferApi';
import { AppNotices } from '../../shell/notices/AppNotices';
import { THEMES } from '../../shared/ui/theme';

jest.mock('../../features/data-transfer/dataTransferApi', () => ({
  ...jest.requireActual('../../features/data-transfer/dataTransferApi'),
  commitImport: jest.fn(), previewImport: jest.fn(), pickImportFile: jest.fn(),
  downloadExport: jest.fn(), downloadBackup: jest.fn(), shareTransferFile: jest.fn(),
}));
jest.mock('expo-document-picker', () => ({}));
jest.mock('expo-sharing', () => ({}));
jest.mock('expo-file-system/legacy', () => ({}));
jest.mock('react-native-safe-area-context', () => ({ useSafeAreaInsets: () => ({ top: 24, bottom: 24 }) }));
jest.mock('react-native', () => ({
  useWindowDimensions: jest.fn(() => ({ width: 375, height: 800, fontScale: 1 })), Platform: { OS: 'android' },
  BackHandler: { addEventListener: jest.fn(() => ({ remove: jest.fn() })) },
  ActivityIndicator: 'ActivityIndicator', View: 'View', ScrollView: 'ScrollView', Switch: 'Switch',
  Modal: 'Modal', Pressable: 'Pressable', Text: 'Text', KeyboardAvoidingView: 'KeyboardAvoidingView',
  StyleSheet: { create: (styles: any) => styles, absoluteFillObject: {}, absoluteFill: {} },
}));

const session = { username: 'current', token: 'session-token', serverUrl: 'https://chosen-server' };
const nativePreview = { preview_id: 'preview-1', source_format: 'native' as const, scope: 'all' as const,
  counts: { conversations: 3, memories: 1, media: 2 }, warnings: ['缺失原媒体'] };
const committed = { success: true, committed: true, failed_phase: null, imported: nativePreview.counts,
  skipped: { conversations: 0, memories: 0 }, backup_id: 'backup-1',
  extraction: { status: 'not_requested' as const, memories: 0 }, warnings: [] };
let root: ReactTestRenderer;
const pause = jest.fn();
const resume = jest.fn();
const close = jest.fn();
const label = (name: string) => root.root.findAllByType(Pressable).find(node => node.props.accessibilityLabel === name)!;
const text = () => root.root.findAllByType(Text).map(node => node.props.children).flat(Infinity).join(' ');
async function press(name: string) { await act(async () => { label(name).props.onPress(); }); }
async function mount(theme = THEMES.light, selectImport = true) {
  await act(async () => { root = create(<AppNotices><DataTransferScreen session={session} characterId="luotianyi"
    theme={theme} onClose={close} pauseChat={pause} resumeChat={resume} /></AppNotices>); });
  if (selectImport) await press('导入');
}
beforeEach(() => {
  jest.clearAllMocks();
  pause.mockReturnValue(true);
  resume.mockResolvedValue(true);
  jest.mocked(api.pickImportFile).mockResolvedValue({ uri: 'file:///cache/file.zip', name: 'file.zip', size: 12, lastModified: 0 });
  jest.mocked(api.previewImport).mockResolvedValue(nativePreview);
  jest.mocked(api.commitImport).mockResolvedValue(committed);
  jest.mocked(api.downloadExport).mockResolvedValue({ uri: 'file:///export.zip', mimeType: 'application/zip' });
  jest.mocked(api.downloadBackup).mockResolvedValue({ uri: 'file:///backup.zip', mimeType: 'application/zip' });
});
afterEach(async () => { if (root) await act(async () => root.unmount()); });

it('取消文件不改预览；确认提示可取消，真实替换仅在确认后一次提交', async () => {
  await mount();
  jest.mocked(api.pickImportFile).mockResolvedValueOnce(null);
  await press('选择文件并预览');
  expect(api.previewImport).not.toHaveBeenCalled();
  await press('选择文件并预览');
  expect(text()).toContain('聊天 3 条，长期记忆 1 条，媒体 2 个');
  expect(text()).toContain('缺失原媒体');
  await press('备份后替换');
  expect(text()).toContain('长期记忆、画像与聊天偏好');
  expect(api.commitImport).not.toHaveBeenCalled();
  await act(async () => { root.root.findByType(Modal).props.onRequestClose(); });
  expect(api.commitImport).not.toHaveBeenCalled();
  await press('备份后替换');
  const confirm = root.root.findAllByType(Pressable).find(node => node.findAllByType(Text).some(t => t.props.children === '确认替换'))!;
  await act(async () => { confirm.props.onPress(); confirm.props.onPress(); });
  expect(api.commitImport).toHaveBeenCalledTimes(1);
  expect(api.commitImport).toHaveBeenCalledWith(session, 'preview-1', 'replace', true, false);
  expect(pause).toHaveBeenCalledTimes(1);
  expect(resume).toHaveBeenCalledWith(true);
  expect(text()).toContain('导入完成');
  await press('下载替换前的恢复备份');
  expect(api.downloadBackup).toHaveBeenCalledWith(session, 'backup-1');
  expect(api.shareTransferFile).toHaveBeenCalledWith({ uri: 'file:///backup.zip', mimeType: 'application/zip' });
});

it('异步busy立即阻挡重复点击与返回，完成后恢复', async () => {
  let resolve!: (value: any) => void;
  jest.mocked(api.pickImportFile).mockReturnValueOnce(new Promise(done => { resolve = done; }));
  await mount();
  const choose = label('选择文件并预览').props.onPress;
  await act(async () => { choose(); choose(); });
  expect(api.pickImportFile).toHaveBeenCalledTimes(1);
  expect(label('返回').props.disabled).toBe(true);
  await press('返回');
  const back = jest.mocked(BackHandler.addEventListener).mock.calls.at(-1)![1];
  await act(async () => { back(); });
  expect(close).not.toHaveBeenCalled();
  await act(async () => { resolve(null); });
  await press('返回');
  expect(close).toHaveBeenCalledTimes(1);
});

it('默认不提取；外部chat有效范围确认不声称替换记忆，提取失败可同预览重试', async () => {
  await mount();
  await press('展开导入高级设置');
  await press('ChatGPT');
  await press('收起导入高级设置');
  jest.mocked(api.previewImport).mockResolvedValue({ ...nativePreview, source_format: 'chatgpt', scope: 'chat' });
  await press('选择文件并预览');
  expect(api.previewImport).toHaveBeenCalledWith(session, expect.any(Object), 'chatgpt', 'chat', 'luotianyi');
  expect(root.root.findByType(Switch).props.value).toBe(false);
  await press('备份后替换');
  const noticeText = root.root.findAllByProps({ accessibilityRole: 'alert' })[0];
  expect(noticeText.findAllByType(Text).map(node => node.props.children).join(' ')).not.toContain('画像');
  await act(async () => { root.root.findByType(Modal).props.onRequestClose(); });
  await act(async () => { root.root.findByType(Switch).props.onValueChange(true); });
  jest.mocked(api.commitImport).mockResolvedValueOnce({ ...committed,
    extraction: { status: 'failed', memories: 0, error: '模型暂不可用' } });
  await press('合并去重');
  expect(api.commitImport).toHaveBeenLastCalledWith(session, 'preview-1', 'merge', false, true);
  expect(text()).toContain('长期记忆提取失败');
  jest.mocked(api.commitImport).mockResolvedValueOnce({ ...committed, extraction: { status: 'succeeded', memories: 2 } });
  await press('重试记忆提取');
  expect(api.commitImport).toHaveBeenLastCalledWith(session, 'preview-1', 'merge', false, true);
  expect(text()).toContain('已提取 2 条长期记忆');
});

it('HTTP200失败不显示成功，仍展示备份；409可重试且失败后仍恢复聊天', async () => {
  await mount();
  await press('选择文件并预览');
  jest.mocked(api.commitImport).mockResolvedValueOnce({ success: false, committed: false,
    failed_phase: 'commit', backup_id: 'rescue', error: 'prepare_failed' });
  await press('合并去重');
  expect(text()).toContain('导入未完成');
  expect(text()).not.toContain('导入完成');
  await press('下载替换前的恢复备份');
  expect(api.downloadBackup).toHaveBeenLastCalledWith(session, 'rescue');
  jest.mocked(api.commitImport).mockRejectedValueOnce(new api.DataTransferError('通话仍在收尾，请稍后重试。', 409));
  await press('合并去重');
  expect(text()).toContain('通话仍在收尾');
  expect(resume).toHaveBeenLastCalledWith(true);
  await act(async () => { root.root.findByType(Modal).props.onRequestClose(); });
  await press('合并去重');
  expect(text()).toContain('导入完成');
});

it('导出选项传递正确，分享前恢复聊天；重连失败提供显式重试', async () => {
  await mount();
  await press('导出');
  await press('展开导出高级设置');
  await press('Markdown');
  await press('收起导出高级设置');
  resume.mockResolvedValueOnce(false);
  await press('导出并打开系统分享');
  expect(api.downloadExport).toHaveBeenCalledWith(session, 'all', 'markdown');
  expect(resume).toHaveBeenCalledWith(false);
  expect(api.shareTransferFile).toHaveBeenCalledTimes(1);
  expect(text()).toContain('聊天连接待恢复');
  await press('刷新聊天并重连');
  expect(resume).toHaveBeenLastCalledWith(true);
  expect(text()).not.toContain('聊天连接待恢复');
});

it.each([THEMES.light, THEMES.dark])('沿用$name主题，小屏大字使用可折行的48dp控件', async theme => {
  jest.mocked(useWindowDimensions).mockReturnValue({ width: 375, height: 667, scale: 1, fontScale: 2 });
  await mount(theme);
  const button = label('选择文件并预览');
  expect(button.props.accessibilityState).toEqual({ disabled: false });
  expect(button.props.style({ pressed: false })[0]).toMatchObject({ minHeight: 48 });
  expect(button.props.style({ pressed: false })[1].backgroundColor).toBe(theme.accentSoft);
  await press('导出');
  await press('展开导出高级设置');
  const group = root.root.findByProps({ accessibilityRole: 'radiogroup', accessibilityLabel: '导出范围' });
  expect(group.props.style.flexWrap).toBe('wrap');
  const selected = group.findAllByType(Pressable).find(node => node.props.accessibilityState.checked);
  expect(selected?.props.accessibilityRole).toBe('radio');
});

it('高级设置在原位展开收起，详细统计仍在二级页面查看', async () => {
  await mount();
  expect(text()).not.toContain('保存格式');
  expect(text()).not.toContain('文件来源');

  await press('导出');
  await press('展开导出高级设置');
  expect(text()).toContain('保存格式');
  expect(root.root.findAllByType(Modal)).toHaveLength(0);
  await press('收起导出高级设置');
  expect(text()).not.toContain('保存格式');
  await press('导入');
  await press('展开导入高级设置');
  expect(text()).toContain('文件来源');
  expect(root.root.findAllByType(Modal)).toHaveLength(0);
  await press('收起导入高级设置');
  expect(text()).not.toContain('文件来源');

  await press('选择文件并预览');
  expect(text()).toContain('导入预览');

  await press('合并去重');
  expect(text()).toContain('导入完成');
  expect(text()).not.toContain('聊天 3 条，长期记忆 1 条，媒体 2 个');

  await press('展开详细信息');
  expect(text()).toContain('聊天 3 条，长期记忆 1 条，媒体 2 个');
});

it('默认隐藏说明和内部状态，说明与结果详情仅在二级入口显示', async () => {
  await mount();
  expect(text()).not.toContain('1 GiB');
  await press('使用须知');
  expect(text()).toContain('1 GiB');
  await act(async () => { root.root.findByType(Modal).props.onRequestClose(); });
  await press('选择文件并预览');
  await press('合并去重');
  expect(text()).not.toContain('本次未请求');
  expect(label('刷新聊天并重连')).toBeUndefined();
  await press('展开详细信息');
  expect(text()).toContain('本次未请求');
  await act(async () => { root.root.findByType(Modal).props.onRequestClose(); });
  expect(text()).not.toContain('本次未请求');
});

it('文件错误默认只展示中文提示，技术详情需主动打开', async () => {
  await mount();
  jest.mocked(api.previewImport).mockRejectedValueOnce(new api.DataTransferError('文件无效，请重新选择。\nExpected UTF-8 JSON', 400));
  await press('选择文件并预览');
  expect(text()).toContain('文件无效');
  expect(text()).not.toContain('Expected UTF-8 JSON');
  const details = root.root.findAllByType(Pressable).find(node => node.findAllByType(Text).some(t => t.props.children === '查看详细信息'))!;
  await act(async () => { details.props.onPress(); });
  expect(text()).toContain('Expected UTF-8 JSON');
});

it('默认显示导出标签；切换保留导入预览且说明弹窗有蒙版', async () => {
  await mount(THEMES.light, false);
  expect(label('导出').props.accessibilityState.selected).toBe(true);
  expect(label('选择文件并预览')).toBeUndefined();
  await press('导入');
  await press('选择文件并预览');
  await press('导出');
  expect(text()).not.toContain('导入预览');
  await press('导入');
  expect(text()).toContain('file.zip');
  await press('使用须知');
  expect(JSON.stringify(root.toJSON())).toContain('rgba(0,0,0,0.45)');
});

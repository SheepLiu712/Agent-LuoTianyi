import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, BackHandler, Modal, Pressable, ScrollView, StyleSheet, Switch, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import type { AppTheme } from '../../shared/ui/theme';
import { usePageNotices } from '../../shell/notices/AppNotices';
import type { AccountSession } from '../account/credentials';
import {
  commitImport, DataTransferError, downloadBackup, downloadExport, pickImportFile, previewImport, shareTransferFile,
  type ExportFormat, type ImportExtraction, type ImportMode, type ImportPreview, type ImportResult,
  type SourceFormat, type TransferCounts, type TransferScope,
} from './dataTransferApi';

const SCOPE_LABELS: Record<TransferScope, string> = { all: '全部', chat: '聊天', memory: '记忆' };
const SCOPE_CONTENT: Record<TransferScope, string> = {
  all: '聊天及关联媒体、长期记忆、画像与聊天偏好',
  chat: '聊天及关联媒体',
  memory: '长期记忆、画像与聊天偏好',
};
const EXPORT_LABELS: Record<ExportFormat, string> = { zip: 'ZIP 恢复包', markdown: 'Markdown', txt: 'TXT' };
const SOURCE_LABELS: Record<SourceFormat, string> = {
  auto: '自动识别', native: '本项目 ZIP', chatgpt: 'ChatGPT', sillytavern: 'SillyTavern', generic: '通用 JSON',
};

const OPERATION_LABELS = {
  export: '正在导出文件…', preview: '正在选择或预览文件…', commit: '正在导入并恢复聊天…',
  backup: '正在下载恢复备份…', refresh: '正在刷新并重连聊天…',
};
type Operation = keyof typeof OPERATION_LABELS;

interface Props {
  session: AccountSession;
  characterId: string;
  theme: AppTheme;
  onClose(): void;
  pauseChat(): boolean;
  resumeChat(refreshHistory: boolean): Promise<boolean>;
}

function Action({ label, onPress, disabled, theme, tone = 'neutral' }: {
  label: string;
  onPress(): void;
  disabled: boolean;
  theme: AppTheme;
  tone?: 'neutral' | 'primary' | 'danger';
}) {
  const backgroundColor = tone === 'danger' ? theme.dangerSurface : tone === 'primary' ? theme.accentSoft : theme.surfaceAlt;
  return <Pressable accessibilityRole="button" accessibilityLabel={label} accessibilityState={{ disabled }}
    onPress={onPress} disabled={disabled}
    style={({ pressed }) => [styles.action, { backgroundColor, opacity: disabled ? 0.55 : pressed ? 0.75 : 1 }]}>
    <Text style={[styles.buttonText, { color: tone === 'danger' ? theme.dangerText : theme.text }]}>{label}</Text>
  </Pressable>;
}

function Choices<T extends string>({ label, labels, value, onChange, disabled, theme }: {
  label: string;
  labels: Record<T, string>;
  value: T;
  onChange(value: T): void;
  disabled: boolean;
  theme: AppTheme;
}) {
  return <View style={styles.group}>
    <Text style={[styles.label, { color: theme.text }]}>{label}</Text>
    <View accessibilityRole="radiogroup" accessibilityLabel={label} style={styles.choices}>
      {(Object.keys(labels) as T[]).map(option => {
        const selected = option === value;
        return <Pressable key={option} accessibilityRole="radio" accessibilityLabel={labels[option]}
          accessibilityState={{ checked: selected, disabled }} disabled={disabled}
          onPress={() => { if (!selected) onChange(option); }}
          style={({ pressed }) => [styles.option, {
            backgroundColor: selected ? theme.accentSoft : theme.surfaceAlt,
            borderColor: selected ? theme.accentText : theme.border,
            opacity: disabled ? 0.55 : pressed ? 0.75 : 1,
          }]}>
          <Text style={[styles.body, { color: theme.text, fontWeight: selected ? '700' : '400' }]}>
            {labels[option]}
          </Text>
        </Pressable>;
      })}
    </View>
  </View>;
}

function Card({ title, theme, children }: React.PropsWithChildren<{ title: string; theme: AppTheme }>) {
  return <View style={[styles.card, { backgroundColor: theme.surface, borderColor: theme.border }]}>
    <Text accessibilityRole="header" style={[styles.sectionTitle, { color: theme.text }]}>{title}</Text>
    {children}
  </View>;
}

function Disclosure({ title, theme, children }: React.PropsWithChildren<{ title: string; theme: AppTheme }>) {
  const [open, setOpen] = useState(false);
  const insets = useSafeAreaInsets();
  return <View>
    <Pressable accessibilityRole="button" accessibilityLabel={`展开${title}`} accessibilityState={{ expanded: open }}
      onPress={() => setOpen(true)}
      style={({ pressed }) => [styles.disclosureHeader, { opacity: pressed ? 0.75 : 1 }]}>
      <Text style={[styles.label, { color: theme.text }]}>{title}</Text>
      <Text style={[styles.body, { color: theme.textMuted }]}>›</Text>
    </Pressable>
    {open && <Modal visible animationType="slide" onRequestClose={() => setOpen(false)}>
      <View style={[styles.secondary, { backgroundColor: theme.surface, paddingTop: insets.top }]}>
        <View style={[styles.header, { borderBottomColor: theme.border }]}>
          <Action label="返回迁移页面" disabled={false} onPress={() => setOpen(false)} theme={theme} />
          <Text accessibilityRole="header" style={[styles.pageTitle, { color: theme.text }]}>{title}</Text>
        </View>
        <ScrollView contentContainerStyle={[styles.content, { paddingBottom: Math.max(24, insets.bottom + 16) }]}>
          {children}
        </ScrollView>
      </View>
    </Modal>}
  </View>;
}

function countsText(counts: TransferCounts) {
  const media = counts.media === undefined ? '' : `，媒体 ${counts.media} 个`;
  return `聊天 ${counts.conversations} 条，长期记忆 ${counts.memories} 条${media}`;
}

function extractionText(extraction: ImportExtraction) {
  switch (extraction.status) {
    case 'not_requested': return '本次未请求提取长期记忆。';
    case 'succeeded': return `已提取 ${extraction.memories} 条长期记忆。`;
    case 'failed': return `长期记忆提取失败。聊天导入结果见上方。${extraction.error ? `\n${extraction.error}` : ''}`;
    case 'unavailable': return '此服务器当前无法提取长期记忆。聊天导入结果见上方。';
  }
}

export function DataTransferScreen({ session, characterId, theme, onClose, pauseChat, resumeChat }: Props) {
  const insets = useSafeAreaInsets();
  const showNotice = usePageNotices('data-transfer');
  const [exportScope, setExportScope] = useState<TransferScope>('all');
  const [exportFormat, setExportFormat] = useState<ExportFormat>('zip');
  const [importScope, setImportScope] = useState<TransferScope>('all');
  const [source, setSource] = useState<SourceFormat>('auto');
  const [preview, setPreview] = useState<{ fileName: string; data: ImportPreview }>();
  const [extractMemories, setExtractMemories] = useState(false);
  const [result, setResult] = useState<ImportResult>();
  const [retryPreviewId, setRetryPreviewId] = useState<string>();
  const [failureBackupId, setFailureBackupId] = useState<string>();
  const [operation, setOperation] = useState<Operation>();
  const [needsReconnect, setNeedsReconnect] = useState(false);
  const operationRef = useRef<Operation | 'confirm' | undefined>(undefined);
  const busy = operation !== undefined;
  const externalSource = source !== 'auto' && source !== 'native';
  const externalPreview = preview && preview.data.source_format !== 'native';
  const body = [styles.body, { color: theme.textSoft }];
  const imported = result?.imported ?? { conversations: 0, memories: 0, media: 0 };
  const skipped = result?.skipped ?? { conversations: 0, memories: 0, media: 0 };
  const extraction = result?.extraction ?? { status: 'not_requested' as const, memories: 0 };

  const goBack = useCallback(() => {
    if (!operationRef.current) onClose();
  }, [onClose]);

  useEffect(() => {
    const subscription = BackHandler.addEventListener('hardwareBackPress', () => { goBack(); return true; });
    return () => subscription.remove();
  }, [goBack]);

  function resetPreview() {
    setPreview(undefined);
    setExtractMemories(false);
  }

  async function run(kind: Operation, task: () => Promise<void>) {
    if (operationRef.current) return;
    operationRef.current = kind;
    setOperation(kind);
    try {
      await task();
    } catch (error) {
      const message = error instanceof DataTransferError ? error.message : '操作未完成，请检查网络或文件权限后重试。';
      const uncertain = kind === 'commit' && (!(error instanceof DataTransferError) || !error.status || error.status >= 500);
      if (error instanceof DataTransferError && error.backupId) setFailureBackupId(error.backupId);
      const summary = message.split('\n')[0];
      showNotice({ theme, title: '操作未完成', position: 'center', blocking: true,
        message: uncertain ? `${summary}\n请先刷新聊天确认结果，再决定是否重新导入。` : summary,
        ...(summary !== message ? {
          cancel: { label: '关闭' },
          primary: { label: '查看详细信息', action: () => showNotice({
            theme, title: '错误详情', message, position: 'center', blocking: true,
          }) },
        } : {}),
      });
    } finally {
      operationRef.current = undefined;
      setOperation(undefined);
    }
  }

  async function reconnect(refreshHistory: boolean) {
    try {
      setNeedsReconnect(!(await resumeChat(refreshHistory)));
    } catch {
      setNeedsReconnect(true);
    }
  }

  async function withChatPaused<T>(task: () => Promise<T>, shouldRefresh: (value: T) => boolean = () => false, refreshOnError = false) {
    if (!pauseChat()) throw new DataTransferError('聊天有正在录制或发送的消息，请等待结束后再试。', 409);
    let refreshHistory = refreshOnError;
    try {
      const value = await task();
      refreshHistory = shouldRefresh(value);
      return value;
    } finally {
      await reconnect(refreshHistory);
    }
  }

  function exportData() {
    void run('export', async () => {
      const file = await withChatPaused(() => downloadExport(session, exportScope, exportFormat));
      await shareTransferFile(file);
    });
  }

  function chooseFile() {
    void run('preview', async () => {
      const file = await pickImportFile();
      if (!file) return;
      resetPreview();
      const data = await previewImport(session, file, source, externalSource ? 'chat' : importScope, characterId);
      setPreview({ fileName: file.name, data });
    });
  }

  function submit(mode: ImportMode, confirmed: boolean) {
    if (!preview) return;
    const { data } = preview;
    void run('commit', async () => {
      const committed = await withChatPaused(
        () => commitImport(session, data.preview_id, mode, confirmed, Boolean(externalPreview && extractMemories)),
        value => value.committed && data.scope !== 'memory',
        data.scope !== 'memory',
      );
      setResult(committed);
      setRetryPreviewId(committed.committed ? data.preview_id : undefined);
      if (committed.success) resetPreview();
    });
  }

  function retryExtraction() {
    if (!retryPreviewId) return;
    void run('commit', async () => {
      const retried = await withChatPaused(() => commitImport(session, retryPreviewId, 'merge', false, true));
      setResult(retried);
    });
  }

  function saveBackup(backupId: string) {
    void run('backup', async () => shareTransferFile(await downloadBackup(session, backupId)));
  }

  function confirmReplace() {
    if (!preview || operationRef.current) return;
    operationRef.current = 'confirm';
    showNotice({
      theme,
      title: '备份后替换？',
      message: `服务器会先生成恢复 ZIP，再替换当前账号的${SCOPE_CONTENT[preview.data.scope]}。完成后可下载备份。`,
      cancel: { label: '取消', action: () => { operationRef.current = undefined; } },
      primary: { label: '确认替换', action: () => { operationRef.current = undefined; submit('replace', true); } },
    });
  }

  return <View style={[styles.screen, { backgroundColor: theme.root, paddingTop: insets.top }]}
    accessibilityViewIsModal>
    <View style={[styles.header, { backgroundColor: theme.surface, borderBottomColor: theme.border }]}>
      <Action label="返回" disabled={busy} onPress={goBack} theme={theme} />
      <Text accessibilityRole="header" style={[styles.pageTitle, { color: theme.text }]}>聊天与记忆迁移</Text>
    </View>
    <ScrollView contentContainerStyle={[styles.content, { paddingBottom: Math.max(24, insets.bottom + 16) }]}
      style={styles.scroll}>
      {operation && <View style={[styles.progress, { backgroundColor: theme.surfaceAlt }]}>
        <ActivityIndicator color={theme.accentText} />
        <Text accessibilityLiveRegion="polite" style={[styles.body, styles.flexText, { color: theme.text }]}>
          {OPERATION_LABELS[operation]}
        </Text>
      </View>}
      {needsReconnect && <Card title="聊天连接待恢复" theme={theme}>
        <Text style={body} accessibilityLiveRegion="polite">可以手动刷新历史并重新连接。</Text>
        <Action label="刷新聊天并重连" disabled={busy} theme={theme} onPress={() => { void run('refresh', () => reconnect(true)); }} />
      </Card>}
      {failureBackupId && <Card title="可用的恢复备份" theme={theme}>
        <Action label="下载失败操作的恢复备份" disabled={busy} theme={theme} onPress={() => saveBackup(failureBackupId)} />
      </Card>}
      <Pressable accessibilityRole="button" accessibilityLabel="使用须知" onPress={() => showNotice({
        theme, title: '使用须知', position: 'center', blocking: true,
        message: '1. 上传与下载上限 64 MiB，解压后上限 256 MiB、4096 项。\n\n2. 导入和导出时请暂停聊天，过程中服务器可能断开聊天连接。\n\n3. 外部聊天默认只进入历史，开启提取长期记忆后才会调用模型提取。',
      })} style={styles.usage}>
        <Text style={[styles.label, { color: theme.accentText }]}>使用须知</Text>
      </Pressable>
      <Card title="导出" theme={theme}>
        <Text style={body}>导出 {SCOPE_LABELS[exportScope]} · {EXPORT_LABELS[exportFormat]}。</Text>
        <Action label="导出并打开系统分享" onPress={exportData} disabled={busy} theme={theme} tone="primary" />
        <Disclosure title="导出高级设置" theme={theme}>
          <Choices label="导出范围" labels={SCOPE_LABELS} value={exportScope} onChange={setExportScope} disabled={busy} theme={theme} />
          <Choices label="保存格式" labels={EXPORT_LABELS} value={exportFormat} onChange={setExportFormat} disabled={busy} theme={theme} />
          <Text style={body}>{exportFormat === 'zip' ? 'ZIP 保留恢复所需的目录结构。' : '阅读副本仅供查看。需要还原时请选择 ZIP。'}</Text>
        </Disclosure>
      </Card>
      <Card title="导入" theme={theme}>
        <Text style={body}>{externalSource ? '外部文件导入纯文字聊天。' : `恢复 ${SCOPE_LABELS[importScope]}。`}</Text>
        <Action label="选择文件并预览" onPress={chooseFile} disabled={busy} theme={theme} tone="primary" />
        <Disclosure title="导入高级设置" theme={theme}>
          <Choices label="文件来源" labels={SOURCE_LABELS} value={source} onChange={value => { setSource(value); resetPreview(); }} disabled={busy} theme={theme} />
          {externalSource ? <Text style={body}>外部文件导入纯文字聊天。</Text> :
            <Choices label="导入范围" labels={SCOPE_LABELS} value={importScope} onChange={value => { setImportScope(value); resetPreview(); }} disabled={busy} theme={theme} />}
          <Text style={body}>请选择恢复 ZIP、ChatGPT 的 conversations.json、SillyTavern 的 JSONL 或通用 JSON。上传上限 64 MiB，ZIP 展开上限 256 MiB。</Text>
        </Disclosure>
        {preview && <View style={[styles.preview, { backgroundColor: theme.surfaceAlt }]}>
          <Text accessibilityRole="header" style={[styles.label, { color: theme.text }]}>导入预览</Text>
          <Text style={body} accessibilityLiveRegion="polite">
            {`${preview.fileName}\n${SOURCE_LABELS[preview.data.source_format]} · ${SCOPE_LABELS[preview.data.scope]}\n${countsText(preview.data.counts)}`}
          </Text>
          {preview.data.warnings.map((warning, index) => <Text key={index} style={body}>• {warning}</Text>)}
          {externalPreview && <View style={styles.group}>
            <View style={styles.switchRow}>
              <Text style={[styles.label, styles.flexText, { color: theme.text }]}>提取长期记忆</Text>
              <Switch accessibilityLabel="提取长期记忆" disabled={busy} value={extractMemories} onValueChange={setExtractMemories} />
            </View>
            <Pressable accessibilityRole="button" accessibilityLabel="记忆提取说明" onPress={() => showNotice({
              theme, title: '记忆提取说明', position: 'center', blocking: true,
              message: '外部聊天默认仅进入历史。开启后，服务器会调用模型提取本批记录中的用户事实；外部助手不会被视为当前角色。模型提取失败不会撤销已导入的聊天。',
            })}><Text style={[styles.body, { color: theme.accentText }]}>记忆提取说明</Text></Pressable>
          </View>}
          <Action label="合并去重" onPress={() => submit('merge', false)} disabled={busy} theme={theme} tone="primary" />
          <Action label="备份后替换" onPress={confirmReplace} disabled={busy} theme={theme} tone="danger" />
        </View>}
      </Card>
      {result && <Card title={result.success ? '导入完成' : '导入未完成'} theme={theme}>
        {!result.success && <Text style={body} accessibilityLiveRegion="polite">导入未完成，请查看详细信息后重试。</Text>}
        {extraction.status === 'succeeded' && <Text style={body}>{`已提取 ${extraction.memories} 条长期记忆。`}</Text>}
        {(extraction.status === 'failed' || extraction.status === 'unavailable') &&
          <Text style={body}>长期记忆提取失败，可重试；已导入的聊天保留。</Text>}
        {retryPreviewId && (extraction.status === 'failed' || extraction.status === 'unavailable') &&
          <Action label="重试记忆提取" disabled={busy} theme={theme} onPress={retryExtraction} />}
        {result.backup_id && <Action label="下载替换前的恢复备份" disabled={busy} theme={theme} onPress={() => {
          if (result.backup_id) saveBackup(result.backup_id);
        }} />}
        {Boolean(result.warnings?.length) && <Text style={body}>有提示，请查看详细信息。</Text>}
        <Disclosure title="详细信息" theme={theme}>
          <Text style={body}>{extractionText(extraction)}</Text>
          {result.error && <Text style={body}>{result.error}</Text>}
          {result.rollback_error && <Text style={body}>恢复提示：{result.rollback_error}</Text>}
          <Text style={body}>{`导入 ${countsText(imported)}\n跳过 ${countsText(skipped)}`}</Text>
          {(result.warnings ?? []).map((warning, index) => <Text key={index} style={body}>• {warning}</Text>)}
        </Disclosure>
      </Card>}
    </ScrollView>
  </View>;
}

const styles = StyleSheet.create({
  screen: { ...StyleSheet.absoluteFillObject, zIndex: 110 },
  secondary: { flex: 1 },
  usage: { alignSelf: 'flex-end', minHeight: 48, justifyContent: 'center' },
  header: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 16, paddingVertical: 8, borderBottomWidth: 1 },
  pageTitle: { flex: 1, fontSize: 20, fontWeight: '700' },
  scroll: { flex: 1 },
  content: { width: '100%', maxWidth: 720, alignSelf: 'center', paddingHorizontal: 16, paddingTop: 16, gap: 16 },
  card: { borderWidth: 1, borderRadius: 12, padding: 16, gap: 12 },
  sectionTitle: { fontSize: 18, fontWeight: '700' },
  label: { fontSize: 15, fontWeight: '600' },
  body: { fontSize: 14, lineHeight: 20 },
  flexText: { flex: 1 },
  group: { gap: 8 },
  choices: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  option: { minHeight: 48, justifyContent: 'center', borderRadius: 8, borderWidth: 1, paddingHorizontal: 12, paddingVertical: 8 },
  action: { minHeight: 48, minWidth: 48, justifyContent: 'center', alignItems: 'center', borderRadius: 8, paddingHorizontal: 12, paddingVertical: 8 },
  buttonText: { fontSize: 15, fontWeight: '700', textAlign: 'center' },
  preview: { borderRadius: 8, padding: 12, gap: 12 },
  progress: { flexDirection: 'row', alignItems: 'center', gap: 8, padding: 12, borderRadius: 8 },
  switchRow: { flexDirection: 'row', alignItems: 'center', minHeight: 48, gap: 8 },
  disclosureHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', minHeight: 48, borderRadius: 8, paddingHorizontal: 12, paddingVertical: 8 },
});

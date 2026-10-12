/**
 * 用户协议只读查阅页（UA-1 · issue #295）。
 *
 * 范围（对齐 #295 的验收标准与「范围与 PR」）：
 * - 设置入口点击“用户协议”后全屏只读查阅当前协议正文与版本；
 *   整屏覆盖：根节点与 preferences / dynamics / llm_settings 一致地用
 *   absoluteFillObject 铺满窗口，并以高于 Live2D 层（zIndex 10）与抽屉（zIndex 100）
 *   的层级绘制，否则只会挤占主界面的一块空间、被主界面盖住；
 * - 失败可重试，失败态给出红叉提示并只保留顶栏标题（隐藏正文区大标题）；
 *   重试按钮与桌面端 retry_btn 同为次要样式（浅灰底、深色字，非主色按钮）；
 *   错误文案由 useAuth 归一成字符串（spec：加载失败提示为“用户协议加载失败，请重试”），
 *   不把服务端 detail 对象插值成 ``[object Object]``；
 *   关闭返回原界面会话，不写签署；
 *   header 沿用 preferences / dynamics / llm_settings 的约定（16/12 内边距、
 *   minWidth 56 的纯文字返回、accentText 16px/600、居中页标题 + 56 宽右侧占位）；
 *   正文区左上角另设 32px 大标题（ui.svg「03 App · 设置查阅」的大标题形态），
 *   与版本号共用正文左边缘；两处标题按评审结论并存；
 * - 不启用登录或注册门禁：没有倒计时、同意或拒绝操作；
 * - 正文渲染由 RichAgreement 提供，供后续签署流程复用。
 */

import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import MaterialIcons from '@expo/vector-icons/MaterialIcons';

import { RichAgreement } from '../components/RichAgreement';
import { fetchCurrentAgreement } from '../hooks/useAuth';
import { AgreementPayload } from '../utils/agreement';
import { AppTheme } from '../utils/theme';

const TEXT_TITLE = '用户协议';
const TEXT_BACK = '返回';
const TEXT_RETRY = '重试';
const TEXT_LOAD_FAILED = '用户协议加载失败，请重试';

interface Props {
  onClose: () => void;
  theme: AppTheme;
}

export default function AgreementScreen({ onClose, theme }: Props) {
  const insets = useSafeAreaInsets();
  const [data, setData] = useState<AgreementPayload | null>(null);
  const [failure, setFailure] = useState<string>('');
  const [loading, setLoading] = useState<boolean>(false);
  const abortRef = useRef<AbortController | null>(null);
  const requestIdRef = useRef(0);

  const reload = useCallback(async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const requestId = ++requestIdRef.current;
    setLoading(true);
    setFailure('');
    const result = await fetchCurrentAgreement({ signal: controller.signal });
    if (requestId !== requestIdRef.current) {
      return;
    }
    abortRef.current = null;
    if (result.success) {
      setData(result.data);
    } else {
      setFailure(result.message || TEXT_LOAD_FAILED);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    reload();
    return () => {
      requestIdRef.current += 1;
      abortRef.current?.abort();
      abortRef.current = null;
    };
  }, [reload]);

  return (
    <View
      style={[
        styles.root,
        {
          backgroundColor: theme.surface,
          paddingTop: insets.top,
          paddingBottom: insets.bottom,
        },
      ]}
    >
      <View
        style={[
          styles.header,
          { backgroundColor: theme.surface, borderBottomColor: theme.border },
        ]}
      >
        <TouchableOpacity style={styles.backButton} onPress={onClose} activeOpacity={0.72}>
          <Text style={[styles.backText, { color: theme.accentText }]}>{TEXT_BACK}</Text>
        </TouchableOpacity>
        <Text style={[styles.headerTitle, { color: theme.text }]}>{TEXT_TITLE}</Text>
        <View style={styles.headerSpacer} />
      </View>

      <View style={styles.body}>
        {failure === '' ? (
          <Text style={[styles.pageTitle, { color: theme.text }]}>{data?.title || TEXT_TITLE}</Text>
        ) : null}
        {loading ? (
          <View style={styles.centerBlock}>
            <ActivityIndicator color={theme.accent} />
          </View>
        ) : failure !== '' ? (
          <View style={styles.centerBlock}>
            <MaterialIcons name="close" size={44} color={theme.dangerText} />
            <Text style={[styles.failureText, { color: theme.dangerText }]}>{failure}</Text>
            <TouchableOpacity
              style={[styles.retryButton, { backgroundColor: theme.surfaceAlt }]}
              onPress={reload}
              activeOpacity={0.78}
            >
              <Text style={[styles.retryText, { color: theme.text }]}>{TEXT_RETRY}</Text>
            </TouchableOpacity>
          </View>
        ) : (
          <>
            {data?.version ? (
              <Text style={[styles.version, { color: theme.textMuted }]}>
                {`版本：${data.version}`}
              </Text>
            ) : null}
            <RichAgreement data={data} theme={theme} />
          </>
        )}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  root: {
    ...StyleSheet.absoluteFillObject,
    zIndex: 140,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderBottomWidth: 1,
  },
  backButton: { minWidth: 56, paddingVertical: 6 },
  backText: { fontSize: 16, fontWeight: '600' },
  headerTitle: { flex: 1, textAlign: 'center', fontSize: 17, fontWeight: '700' },
  headerSpacer: { width: 56 },
  pageTitle: { fontSize: 32, fontWeight: '700', marginBottom: 6 },
  body: { flex: 1, paddingHorizontal: 20, paddingTop: 14 },
  centerBlock: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 12 },
  failureText: { fontSize: 13, textAlign: 'center' },
  // 与桌面端 retry_btn 同一次要样式：浅灰底 + 深色字、最小高度 44、圆角 8、14 号字、左右 16
  retryButton: {
    minHeight: 44,
    paddingHorizontal: 16,
    paddingVertical: 10,
    borderRadius: 8,
    alignItems: 'center',
    justifyContent: 'center',
  },
  retryText: { fontSize: 14, fontWeight: '600' },
  version: { fontSize: 12, marginBottom: 8 },
});
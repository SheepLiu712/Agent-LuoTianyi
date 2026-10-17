import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, AppState, Modal, ScrollView, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { AgreementPayload } from '../utils/agreement';
import { RichAgreement } from './RichAgreement';
import { AppTheme } from '../utils/theme';

const REQUIRED_SECONDS = 5;

export interface AgreementModalProps {
  visible: boolean;
  agreement: AgreementPayload | null;
  loading: boolean;
  error?: string;
  theme: AppTheme;
  submitLabel?: string;
  onRetry: () => void;
  onSubmit: () => Promise<{ success: boolean; code?: string; message?: string; agreement?: AgreementPayload }>;
  onCancel: () => void;
}

/** Shared signing reader. The read state is deliberately local to one opening. */
export function AgreementModal({
  visible, agreement, loading, error, theme, submitLabel = '我已阅读并同意用户协议', onRetry, onSubmit, onCancel,
}: AgreementModalProps) {
  const insets = useSafeAreaInsets();
  const [elapsed, setElapsed] = useState(0);
  const [atBottom, setAtBottom] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const elapsedRef = useRef(0);
  const activeSince = useRef<number | null>(null);
  const submittingRef = useRef(false);
  const [contentHeight, setContentHeight] = useState(0);
  const [viewportHeight, setViewportHeight] = useState(0);

  const settleActiveInterval = useCallback((updateState = true) => {
    if (activeSince.current === null) return;
    const now = Date.now();
    elapsedRef.current = Math.min(REQUIRED_SECONDS, elapsedRef.current + Math.max(0, now - activeSince.current) / 1000);
    activeSince.current = null;
    if (updateState) setElapsed(elapsedRef.current);
  }, []);

  useEffect(() => {
    if (!visible) return;
    elapsedRef.current = 0;
    setElapsed(0); setAtBottom(false); setSubmitting(false); submittingRef.current = false;
    activeSince.current = null;
    setContentHeight(0); setViewportHeight(0);
  }, [visible, agreement?.version]);

  useEffect(() => () => {
    activeSince.current = null;
  }, []);

  useEffect(() => {
    if (!visible || loading || !agreement) return;
    activeSince.current = Date.now();
    const timer = setInterval(() => {
      if (activeSince.current === null) return;
      const now = Date.now();
      elapsedRef.current = Math.min(REQUIRED_SECONDS, elapsedRef.current + Math.max(0, now - activeSince.current) / 1000);
      activeSince.current = now;
      setElapsed(elapsedRef.current);
    }, 250);
    return () => {
      clearInterval(timer);
      settleActiveInterval(false);
    };
  }, [visible, loading, agreement, settleActiveInterval]);

  useEffect(() => {
    if (!visible) return;
    const sub = AppState.addEventListener('change', (next) => {
      if (next === 'active') {
        if (activeSince.current === null) activeSince.current = Date.now();
      } else {
        settleActiveInterval();
      }
    });
    return () => sub.remove();
  }, [visible, settleActiveInterval]);

  const handleScroll = useCallback((event: any) => {
    const { contentOffset, layoutMeasurement, contentSize } = event.nativeEvent;
    if (contentOffset.y + layoutMeasurement.height >= contentSize.height - 2) setAtBottom(true);
  }, []);
  const shortDocument = contentHeight > 0 && viewportHeight > 0 && contentHeight <= viewportHeight + 2;
  const ready = Boolean(agreement) && (atBottom || shortDocument) && elapsed >= REQUIRED_SECONDS && !submitting;
  const remaining = Math.max(0, Math.ceil(REQUIRED_SECONDS - elapsed));
  const helper = elapsed < REQUIRED_SECONDS
    ? `请继续阅读，还需 ${remaining} 秒`
    : !(atBottom || shortDocument) ? '请阅读至协议底部' : '';

  const submit = async () => {
    if (!ready) return;
    submittingRef.current = true;
    setSubmitting(true);
    try {
      const result = await onSubmit();
      if (result.success) return;
      setSubmitting(false);
      submittingRef.current = false;
      if (result.code === 'AGREEMENT_CHANGED' && result.agreement) {
        elapsedRef.current = 0;
        setElapsed(0); setAtBottom(false);
      }
    } catch {
      setSubmitting(false);
      submittingRef.current = false;
    }
  };

  const handleCancel = useCallback(() => {
    if (submitting || submittingRef.current) return;
    onCancel();
  }, [onCancel, submitting]);

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={handleCancel}>
      <View style={styles.overlay}>
        <View style={[styles.card, { backgroundColor: theme.surface, paddingBottom: insets.bottom + 12 }]}>
          <View style={[styles.header, { borderBottomColor: theme.border }]}>
            <Text style={[styles.title, { color: theme.text }]}>{agreement?.title || '用户协议'}</Text>
            <Text style={[styles.version, { color: theme.textMuted }]}>{agreement ? `版本：${agreement.version}` : ''}</Text>
          </View>
          <View style={styles.reader} onLayout={(e) => { setViewportHeight(e.nativeEvent.layout.height); }}>
            {loading ? <View style={styles.center}><ActivityIndicator color={theme.accent} /><Text style={{ color: theme.textMuted }}>协议加载中…</Text></View> : error ? (
              <View style={styles.center}><Text style={[styles.error, { color: theme.dangerText }]}>{error}</Text><TouchableOpacity style={[styles.retry, { backgroundColor: theme.surfaceAlt }]} onPress={onRetry}><Text style={{ color: theme.text }}>重试</Text></TouchableOpacity></View>
            ) : (
              <ScrollView
                onScroll={handleScroll} scrollEventThrottle={250}
                onContentSizeChange={(_width: number, height: number) => { setContentHeight(height); if (height <= viewportHeight + 2) setAtBottom(true); }}
                showsVerticalScrollIndicator
              >
                <RichAgreement data={agreement} theme={theme} />
              </ScrollView>
            )}
          </View>
          <View style={styles.actions}>
            <Text style={[styles.helper, { color: theme.textMuted }]}>{helper}</Text>
            <View style={styles.buttons}>
              <TouchableOpacity style={[styles.button, { backgroundColor: theme.surfaceAlt }]} disabled={submitting} onPress={handleCancel}><Text style={{ color: theme.text }}>不同意并退出</Text></TouchableOpacity>
              <TouchableOpacity style={[styles.button, { backgroundColor: ready ? theme.accent : '#D1D5DB' }]} disabled={!ready} onPress={submit}><Text style={{ color: ready ? '#fff' : '#6B7280', fontWeight: '600' }}>{submitting ? '正在提交…' : submitLabel}</Text></TouchableOpacity>
            </View>
          </View>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  overlay: { flex: 1, backgroundColor: 'rgba(31,41,55,0.72)', justifyContent: 'center', padding: 18 },
  card: { maxHeight: '92%', borderRadius: 16, overflow: 'hidden' },
  header: { padding: 18, borderBottomWidth: 1 },
  title: { fontSize: 22, fontWeight: '700' },
  version: { marginTop: 5, fontSize: 12 },
  reader: { flex: 1, minHeight: 240, paddingHorizontal: 16 },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 12 },
  error: { textAlign: 'center', fontSize: 14 },
  retry: { paddingHorizontal: 18, paddingVertical: 11, borderRadius: 8 },
  actions: { paddingHorizontal: 16, paddingTop: 12 },
  helper: { minHeight: 20, textAlign: 'center', fontSize: 13 },
  buttons: { flexDirection: 'row', gap: 10, marginTop: 8 },
  button: { flex: 1, minHeight: 46, alignItems: 'center', justifyContent: 'center', borderRadius: 9, paddingHorizontal: 8 },
});

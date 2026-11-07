import React from 'react';
import { Modal, Pressable, StyleSheet, Text, View } from 'react-native';
import type { AppTheme } from '../utils/theme';
import type { PermissionNotice } from '../utils/voice_permission';
import { NoticeBanner } from './NoticeBanner';

interface Props {
  notice: PermissionNotice;
  theme: AppTheme;
  top: number;
  onDismiss: (notice: PermissionNotice) => void;
  onOpenSettings: (notice: PermissionNotice) => void;
}

export function VoicePermissionNotice({ notice, theme, top, onDismiss, onOpenSettings }: Props) {
  const dismiss = () => onDismiss(notice);
  if (!notice.settings) {
    return <NoticeBanner message={notice.message} theme={theme} top={top}
      dismissLabel="关闭麦克风提示" onDismiss={dismiss} />;
  }
  return (
    <Modal transparent visible onRequestClose={dismiss}>
      <View style={styles.backdrop}>
        <View accessibilityViewIsModal style={[styles.card, { backgroundColor: theme.surface }]}>
          <Text accessibilityRole="alert" style={[styles.message, { color: theme.text }]}>{notice.message}</Text>
          <View style={styles.actions}>
            <Pressable accessibilityRole="button" onPress={dismiss} style={styles.button}>
              <Text style={{ color: theme.text }}>取消</Text>
            </Pressable>
            <Pressable accessibilityRole="button" onPress={() => onOpenSettings(notice)} style={styles.button}>
              <Text style={{ color: theme.accentText }}>去设置</Text>
            </Pressable>
          </View>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    flex: 1, backgroundColor: 'rgba(0, 0, 0, 0.45)', justifyContent: 'center',
    alignItems: 'center', padding: 24,
  },
  card: { width: '100%', maxWidth: 420, borderRadius: 14, padding: 20 },
  message: { fontSize: 16 },
  actions: { flexDirection: 'row', marginTop: 16 },
  button: { flex: 1, minHeight: 44, alignItems: 'center', justifyContent: 'center' },
});

import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import type { AppTheme } from '../../utils/theme';
import type { CallFailureNotice } from '../../utils/call_failure';

interface Props {
  notice: CallFailureNotice;
  theme: AppTheme;
  onDismiss: () => void;
}

export function CallFailureBanner({ notice, theme, onDismiss }: Props) {
  return (
    <View accessibilityRole="alert" style={[styles.banner, { backgroundColor: theme.surface, borderColor: theme.border, shadowColor: theme.shadow }]}>
      <View style={styles.copy}>
        <Text style={[styles.title, { color: theme.text }]}>{notice.title}</Text>
        <Text style={[styles.message, { color: theme.textMuted }]}>{notice.message}</Text>
      </View>
      <Pressable accessibilityRole="button" accessibilityLabel="关闭通话提示" onPress={onDismiss} hitSlop={12}>
        <Text style={[styles.dismiss, { color: theme.accentText }]}>知道了</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  banner: {
    position: 'absolute', top: 54, left: 16, right: 16, zIndex: 80,
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    paddingHorizontal: 16, paddingVertical: 12, borderWidth: 1, borderRadius: 14,
    shadowOpacity: 0.16, shadowRadius: 8, shadowOffset: { width: 0, height: 3 }, elevation: 5,
  },
  copy: { flex: 1, paddingRight: 12 },
  title: { fontSize: 15, fontWeight: '700' },
  message: { fontSize: 13, lineHeight: 18, marginTop: 3 },
  dismiss: { fontSize: 13, fontWeight: '700' },
});

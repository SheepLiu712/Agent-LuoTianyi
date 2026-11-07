import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import type { AppTheme } from '../utils/theme';

interface Props {
  title?: string;
  message: string;
  theme: AppTheme;
  dismissLabel: string;
  onDismiss: () => void;
  top?: number;
}

export function NoticeBanner({ title, message, theme, dismissLabel, onDismiss, top = 54 }: Props) {
  return (
    <View accessibilityRole="alert" style={[styles.banner, {
      top, backgroundColor: theme.surface, borderColor: theme.border, shadowColor: theme.shadow,
    }]}>
      <View style={styles.copy}>
        {title ? <Text style={[styles.title, { color: theme.text }]}>{title}</Text> : null}
        <Text style={[styles.message, { color: theme.textMuted }]}>{message}</Text>
      </View>
      <Pressable accessibilityRole="button" accessibilityLabel={dismissLabel} onPress={onDismiss} hitSlop={12}>
        <Text style={[styles.dismiss, { color: theme.accentText }]}>知道了</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  banner: {
    position: 'absolute', left: 16, right: 16, zIndex: 80,
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    paddingHorizontal: 16, paddingVertical: 12, borderWidth: 1, borderRadius: 14,
    shadowOpacity: 0.16, shadowRadius: 8, shadowOffset: { width: 0, height: 3 }, elevation: 5,
  },
  copy: { flex: 1, paddingRight: 12 },
  title: { fontSize: 15, fontWeight: '700' },
  message: { fontSize: 13, marginTop: 3 },
  dismiss: { fontSize: 13, fontWeight: '700' },
});

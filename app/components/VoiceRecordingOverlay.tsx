import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { AppTheme, THEMES } from '../utils/theme';
export function VoiceRecordingOverlay({ elapsedMs, cancelZone, meter, theme = THEMES.light }: { elapsedMs: number; cancelZone: boolean; meter: number; theme?: AppTheme }) {
  const seconds = Math.min(30, Math.floor(elapsedMs / 1000));
  return <View pointerEvents="none" style={[StyleSheet.absoluteFillObject, styles.overlay, { backgroundColor: theme.voiceOverlay }]}><View style={styles.center}><View style={[styles.ripple, { transform: [{ scale: 1 + meter * 0.25 }], borderColor: theme.voiceRipple }]} /><View style={[styles.ripple, styles.middle, { transform: [{ scale: 1 + meter * 0.18 }], borderColor: theme.voiceRipple }]} /><View style={[styles.ripple, styles.outer, { transform: [{ scale: 1 + meter * 0.12 }], borderColor: theme.voiceRipple }]} /><Text style={styles.timer}>{seconds}'' / 30''</Text><Text style={styles.notice}>{cancelZone ? '↑ 松开取消发送' : '↑ 上滑取消发送'}</Text></View></View>;
}
const styles = StyleSheet.create({ overlay: { justifyContent: 'center', alignItems: 'center' }, center: { alignItems: 'center' }, ripple: { position: 'absolute', width: 56, height: 56, borderRadius: 28, borderWidth: 2, opacity: 0.9 }, middle: { width: 90, height: 90, borderRadius: 45, opacity: 0.55 }, outer: { width: 124, height: 124, borderRadius: 62, opacity: 0.28 }, timer: { color: '#fff', fontSize: 16, marginTop: 100 }, notice: { color: '#fff', marginTop: 12, fontSize: 16 } });

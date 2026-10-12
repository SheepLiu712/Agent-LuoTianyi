import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import type { ChatMessage } from '../../types/chat';
import type { AppTheme } from '../../utils/theme';

export function CallHistoryBubble({ message, theme }: { message: ChatMessage; theme: AppTheme }) {
  const connected = message.callOutcome === 'connected';
  const outcome = connected ? '' : message.callOutcome === 'declined' ? '未接听' : message.callOutcome === 'cancelled' ? '已取消' : '通话失败';
  const duration = message.durationMs ? `${String(Math.floor(message.durationMs / 60000)).padStart(2, '0')}:${String(Math.floor(message.durationMs / 1000) % 60).padStart(2, '0')}` : '00:00';
  const label = connected ? `[语音通话] ${duration}` : `[语音通话] ${outcome}`;
  return <View style={[styles.row, message.isUser ? styles.user : styles.agent]}><View accessible accessibilityLabel={label} style={[styles.card, { backgroundColor: message.isUser ? theme.userBubble : theme.botBubble }]}><Text style={{ color: message.isUser ? theme.userBubbleText : theme.bubbleText, fontWeight: '700' }}>{label}</Text></View></View>;
}
const styles = StyleSheet.create({ row: { flexDirection: 'row', paddingHorizontal: 10, paddingVertical: 5 }, user: { justifyContent: 'flex-end' }, agent: { justifyContent: 'flex-start' }, card: { borderRadius: 12, paddingHorizontal: 15, paddingVertical: 11, minWidth: 142 } });

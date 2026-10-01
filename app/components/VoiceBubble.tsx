import React from 'react';
import { Image, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { ChatMessage } from '../types/chat';
import { formatVoiceDuration, voiceBubbleWidth } from '../utils/voice_gesture';
import { AppTheme, THEMES } from '../utils/theme';

export function VoiceBubble({ message, theme = THEMES.light, onPlay, onRetry }: { message: ChatMessage; theme?: AppTheme; onPlay?: () => void; onRetry?: () => void }) {
  const playing = message.audioPlayState === 'playing';
  const waiting = message.sendStatus === 'waiting';
  const status = message.sendStatus === 'failed' ? require('../assets/images/failed_msg.png') : waiting ? require('../assets/images/waiting_msg.png') : null;
  return <View style={styles.row} accessible accessibilityLabel={`用户语音消息，${formatVoiceDuration(message.durationMs || 0)}，${playing ? '停止' : '播放'}`}>
    <TouchableOpacity disabled={message.sendStatus !== 'failed'} onPress={onRetry} style={styles.slot}>{status ? <Image source={status} style={styles.icon} /> : null}</TouchableOpacity>
    <TouchableOpacity disabled={waiting} onPress={onPlay} style={styles.slot}><Text style={[styles.control, { color: theme.userBubbleText }]}>{playing ? '■' : '▶'}</Text></TouchableOpacity>
    <View style={[styles.bubble, { width: voiceBubbleWidth(message.durationMs || 0), backgroundColor: theme.userBubble }]}><Text style={{ color: theme.userBubbleText }}>{formatVoiceDuration(message.durationMs || 0)}</Text><View style={styles.audioIcon}><View style={[styles.dot, { backgroundColor: theme.userBubbleText }]} /><View style={[styles.arc, { borderColor: theme.userBubbleText }]} /><View style={[styles.arc, styles.arc2, { borderColor: theme.userBubbleText }]} /></View></View>
  </View>;
}
const styles = StyleSheet.create({ row: { flexDirection: 'row', alignItems: 'center', justifyContent: 'flex-end', paddingHorizontal: 6, paddingVertical: 5 }, slot: { width: 32, height: 32, alignItems: 'center', justifyContent: 'center' }, icon: { width: 32, height: 32 }, control: { fontSize: 18 }, bubble: { minWidth: 76, height: 40, paddingHorizontal: 15, borderRadius: 10, borderBottomRightRadius: 2, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }, audioIcon: { width: 28, height: 24, alignItems: 'center', justifyContent: 'center' }, dot: { width: 5, height: 5, borderRadius: 3 }, arc: { position: 'absolute', width: 14, height: 14, borderWidth: 2, borderLeftColor: 'transparent', borderTopColor: 'transparent', borderBottomColor: 'transparent', borderRadius: 8 }, arc2: { width: 22, height: 22, borderWidth: 2 } });

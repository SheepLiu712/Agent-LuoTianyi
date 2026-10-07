import MaterialIcons from '@expo/vector-icons/MaterialIcons';
import React, { useEffect, useState } from 'react';
import { Image, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { ChatMessage } from '../types/chat';
import { formatVoiceDuration, voiceBubbleWidth } from '../utils/voice_gesture';
import { AppTheme, THEMES } from '../utils/theme';

export function VoiceBubble({ message, theme = THEMES.light, onPlay, onRetry }: { message: ChatMessage; theme?: AppTheme; onPlay?: () => void; onRetry?: () => void }) {
  const playing = message.audioPlayState === 'playing';
  const loading = message.audioDownloadState === 'loading';
  const waiting = message.sendStatus === 'waiting';
  const unavailable = message.audioAvailable === false;
  const sendFailed = message.sendStatus === 'failed';
  const unavailableLabel = unavailable ? '语音不可用，无法重试' : undefined;
  return <View style={styles.row} accessibilityLabel={`用户语音消息，${formatVoiceDuration(message.durationMs || 0)}，${unavailable ? unavailableLabel : waiting ? '发送中' : sendFailed ? '发送失败' : '已发送'}`}>
    <View style={styles.slot}>
      {sendFailed ? <TouchableOpacity accessibilityRole="button" accessibilityLabel="重试发送语音" onPress={onRetry} disabled={!onRetry} style={styles.retryButton}>
        <MaterialIcons name="refresh" size={22} color="#ffffff" />
      </TouchableOpacity> : waiting ? <Image accessibilityLabel="语音发送中" source={require('../assets/images/waiting_msg.png')} style={styles.icon} /> : null}
    </View>
    <TouchableOpacity onPress={onPlay} disabled={waiting || unavailable || !onPlay} accessibilityRole="button" accessibilityLabel={unavailable ? unavailableLabel : playing ? '停止播放语音' : loading ? '取消加载语音' : '播放语音'} accessibilityState={{ disabled: waiting || unavailable || !onPlay, busy: loading }} style={[styles.bubble, { width: voiceBubbleWidth(message.durationMs || 0), backgroundColor: theme.userBubble, opacity: playing ? 0.7 : 1 }]}><Text style={{ color: theme.userBubbleText }}>{formatVoiceDuration(message.durationMs || 0)}</Text><VoiceAudioIcon key={`${message.uuid}:${playing}`} playing={playing} color={theme.userBubbleText} /></TouchableOpacity>
  </View>;
}
function VoiceAudioIcon({ playing, color }: { playing: boolean; color: string }) {
  const [frame, setFrame] = useState(0);
  useEffect(() => {
    if (!playing) return;
    const timer = setInterval(() => setFrame((current) => (current + 1) % 3), 300);
    return () => clearInterval(timer);
  }, [playing]);
  const visibleArcs = playing ? frame : 2;
  return <View style={styles.audioIcon} testID="voice-audio-icon">
    <View style={[styles.dot, { backgroundColor: color }]} />
    {visibleArcs >= 1 && <View style={[styles.arc, { borderColor: color }]} />}
    {visibleArcs >= 2 && <View style={[styles.arc, styles.arc2, { borderColor: color }]} />}
  </View>;
}

const styles = StyleSheet.create({ row: { flexDirection: 'row', alignItems: 'center', justifyContent: 'flex-end', paddingHorizontal: 6, paddingVertical: 5 }, retryButton: { width: 28, height: 28, borderRadius: 14, backgroundColor: '#D9363E', alignItems: 'center', justifyContent: 'center' }, slot: { width: 32, height: 32, alignItems: 'center', justifyContent: 'center' }, icon: { width: 32, height: 32 }, bubble: { minWidth: 76, height: 40, paddingHorizontal: 15, borderRadius: 10, borderBottomRightRadius: 2, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }, audioIcon: { width: 28, height: 24, alignItems: 'center', justifyContent: 'center' }, dot: { width: 5, height: 5, borderRadius: 3 }, arc: { position: 'absolute', width: 14, height: 14, borderWidth: 2, borderLeftColor: 'transparent', borderTopColor: 'transparent', borderBottomColor: 'transparent', borderRadius: 8 }, arc2: { width: 22, height: 22, borderWidth: 2 } });

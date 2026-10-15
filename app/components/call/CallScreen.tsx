import React, { useEffect, useState } from 'react';
import { Image, Pressable, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import type { AppTheme } from '../../utils/theme';
import type { CallState } from '../../types/call';
import { getCallActiveDurationMs } from '../../utils/call_state';
import { callMonotonicNowMs } from '../../utils/call_clock';
import { useCallKeepAwake } from '../../hooks/useCallKeepAwake';

interface Props {
  state: CallState;
  theme: AppTheme;
  onHangup: () => void;
  onBack: () => void;
  now?: () => number;
}

const labels: Record<string, string> = { REQUESTING_PERMISSION: '需要麦克风权限', SWITCH_PREPARING: '准备通话', CONNECTING: '连接中', PREPARING: '准备中', RINGING: '呼叫中', ACTIVE: '通话中', RECONNECTING: '正在重新连接', ENDING: '正在结束', ENDED: '通话已结束', FAILED: '通话失败', DECLINED: '通话未接通' };
function clock(ms: number) { const seconds = Math.floor(ms / 1000); return `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`; }

export function CallScreen({ state, theme, onHangup, onBack, now = callMonotonicNowMs }: Props) {
  useCallKeepAwake(state.phase);
  const insets = useSafeAreaInsets();
  const [currentNow, setCurrentNow] = useState(now);
  useEffect(() => {
    if (state.phase !== 'ACTIVE' && state.phase !== 'RECONNECTING') return;
    let mounted = true;
    const id = setInterval(() => {
      if (mounted) setCurrentNow(now());
    }, 1000);
    return () => {
      mounted = false;
      clearInterval(id);
    };
  }, [now, state.phase]);
  const active = state.phase === 'ACTIVE' || state.phase === 'RECONNECTING';
  const ended = ['ENDED', 'FAILED', 'DECLINED'].includes(state.phase);
  return <View style={[styles.root, { backgroundColor: active ? 'transparent' : theme.name === 'dark' ? '#111820' : '#27363d', paddingTop: Math.max(insets.top, 48), paddingBottom: Math.max(insets.bottom, 24) }]}>
    {/* ACTIVE/RECONNECTING reuses the parent-owned chat Live2D WebView. */}
    <View style={[styles.scrim, state.phase === 'ACTIVE' && styles.activeScrim]} />
    <Pressable accessibilityLabel="返回聊天" onPress={onBack} style={styles.back}><Text style={styles.backText}>‹</Text></Pressable>
    <View style={styles.center}>
      <Image source={require('../../assets/images/tianyi_icon.png')} style={styles.avatar} />
      <Text style={styles.name}>洛天依</Text>
      <Text style={styles.status}>{labels[state.phase] ?? '通话'}</Text>
      {active ? <Text style={styles.timer}>{clock(getCallActiveDurationMs(state, currentNow))}</Text> : null}
      {state.phase === 'RECONNECTING' ? <View style={styles.reconnect}><Text style={styles.reconnectText}>连接中断，正在恢复。不会重复播放开场语音</Text></View> : null}
      {ended ? <Text style={styles.outcome}>{state.endReason === 'failed' ? '请稍后重试' : '本次通话已结束'}</Text> : null}
    </View>
    {!ended ? <Pressable accessibilityLabel="挂断通话" onPress={onHangup} style={styles.hangup}><Text style={styles.hangupText}>挂断</Text></Pressable> : null}
    {state.phase === 'REQUESTING_PERMISSION' ? <Text style={styles.notice}>允许麦克风权限后才能开始通话</Text> : null}
    {state.phase === 'ENDING' ? <Text style={styles.notice}>正在停止音频</Text> : null}
  </View>;
}

const styles = StyleSheet.create({ root: { ...StyleSheet.absoluteFillObject, zIndex: 30, alignItems: 'center' }, scrim: { ...StyleSheet.absoluteFillObject, backgroundColor: 'rgba(8,14,18,.58)' }, activeScrim: { backgroundColor: 'transparent' }, back: { position: 'absolute', left: 18, top: 48, width: 48, height: 48, justifyContent: 'center' }, backText: { color: '#fff', fontSize: 42, lineHeight: 42, fontWeight: '200' }, center: { alignItems: 'center', marginTop: '24%' }, avatar: { width: 112, height: 112, borderRadius: 56, borderWidth: 2, borderColor: 'rgba(255,255,255,.65)' }, name: { color: '#fff', fontSize: 24, fontWeight: '700', marginTop: 18 }, status: { color: '#fff', fontSize: 16, marginTop: 8 }, timer: { color: '#fff', fontSize: 34, fontVariant: ['tabular-nums'], marginTop: 18 }, reconnect: { marginTop: 22, backgroundColor: 'rgba(15,25,30,.78)', paddingHorizontal: 18, paddingVertical: 12, borderRadius: 16 }, reconnectText: { color: '#fff', fontSize: 14 }, outcome: { color: 'rgba(255,255,255,.76)', marginTop: 20 }, hangup: { position: 'absolute', bottom: 34, width: 80, height: 80, borderRadius: 40, backgroundColor: '#e65f63', alignItems: 'center', justifyContent: 'center' }, hangupText: { color: '#fff', fontSize: 15, fontWeight: '700' }, notice: { position: 'absolute', bottom: 126, color: '#fff', fontSize: 14 } });

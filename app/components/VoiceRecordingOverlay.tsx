import MaterialIcons from '@expo/vector-icons/MaterialIcons';
import React, { useState } from 'react';
import { StyleSheet, Text, useWindowDimensions, View } from 'react-native';
import { AppTheme, THEMES } from '../utils/theme';

interface Props {
  elapsedMs: number;
  cancelZone: boolean;
  meter: number;
  theme?: AppTheme;
  topInset?: number;
  bottomInset?: number;
}

// 固定、左右对称的权重只决定外形，条高始终由本次真实录音音量驱动。
const METER_WEIGHTS = [0.12, 0.2, 0.3, 0.26, 0.42, 0.36, 0.55, 0.7, 0.6, 0.8, 0.65, 0.85, 1,
  0.85, 0.65, 0.8, 0.6, 0.7, 0.55, 0.36, 0.42, 0.26, 0.3, 0.2, 0.12];

export function VoiceRecordingOverlay({
  elapsedMs, cancelZone, meter, theme = THEMES.light, topInset = 0, bottomInset = 0,
}: Props) {
  const { width: windowWidth, fontScale } = useWindowDimensions();
  const [width, setWidth] = useState(windowWidth);
  const seconds = Math.max(0, Math.min(30, Math.floor(elapsedMs / 1000)));
  const level = Math.max(0, Math.min(1, meter));
  const backgroundColor = cancelZone ? theme.voiceRecordingCancel : theme.accent;
  const color = cancelZone ? theme.voiceRecordingCancelText : theme.voiceRecordingText;
  const timer = `${seconds}″ / 30″`;

  return (
    <View
      testID="voice-recording-overlay"
      pointerEvents="none"
      onLayout={(event) => setWidth(event.nativeEvent.layout.width)}
      style={[StyleSheet.absoluteFillObject, styles.overlay, { backgroundColor: theme.voiceOverlay }]}
    >
      <View style={[styles.safeCenter, { top: topInset, bottom: bottomInset }]}>
        <View testID="voice-recording-card" style={[styles.card, { backgroundColor }]}>
          <View style={[styles.heading, { minHeight: 24 * fontScale }]}>
            {/* 两态共用取消文案的排版空间，放大字号换行时也不改变卡片尺寸。 */}
            <Text
              accessibilityElementsHidden={!cancelZone}
              importantForAccessibility={cancelZone ? 'auto' : 'no-hide-descendants'}
              style={[styles.cancelText, { color, opacity: cancelZone ? 1 : 0 }]}
            >松手取消发送</Text>
            {!cancelZone && <View style={styles.timer}><Text style={[styles.timerText, { color }]}>{timer}</Text></View>}
          </View>
          <View style={styles.meter} accessibilityLabel="当前录音音量">
            {METER_WEIGHTS.map((weight, index) => (
              <View key={index} testID="voice-meter-bar" style={[styles.bar, { height: 3 + 25 * weight * level, backgroundColor: color }]} />
            ))}
          </View>
        </View>
      </View>
      <View testID="voice-recording-bottom" style={[styles.bottom, { height: bottomInset + 160 }]}>
        {/* 将圆压成椭圆：顶点为 0，两端为 40，下方矩形接满到页面底部。 */}
        <View style={{ position: 'absolute', width, height: width, top: 40 - width / 2,
          borderRadius: width / 2, backgroundColor, transform: [{ scaleY: 80 / width }] }} />
        <View style={[styles.bottomFill, { backgroundColor }]} />
        {!cancelZone && <View style={[styles.sendLabel, { bottom: bottomInset + 100 }]}>
          <Text style={[styles.sendText, { color, transform: [{ translateY: 10 * fontScale }] }]}>松手发送</Text>
        </View>}
        <View style={[styles.mic, { bottom: bottomInset + 40 }]}>
          <MaterialIcons name="mic" size={32} color={color} />
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  overlay: { zIndex: 110, overflow: 'hidden' },
  safeCenter: { position: 'absolute', left: 24, right: 24, alignItems: 'center', justifyContent: 'center' },
  card: { width: 240, maxWidth: '100%', minHeight: 120, borderRadius: 16, padding: 20,
    justifyContent: 'center', alignItems: 'center', gap: 16 },
  heading: { width: '100%', justifyContent: 'center' },
  cancelText: { fontSize: 16, lineHeight: 24, textAlign: 'center', includeFontPadding: false },
  timer: { ...StyleSheet.absoluteFillObject, alignItems: 'center', justifyContent: 'center' },
  timerText: { fontSize: 20, lineHeight: 24, includeFontPadding: false },
  meter: { height: 28, flexDirection: 'row', alignItems: 'center', gap: 3 },
  bar: { width: 3, borderRadius: 1.5 },
  bottom: { position: 'absolute', bottom: 0, left: 0, right: 0, overflow: 'hidden' },
  bottomFill: { position: 'absolute', top: 40, bottom: 0, left: 0, right: 0 },
  sendLabel: { position: 'absolute', left: 0, right: 0, alignItems: 'center' },
  sendText: { fontSize: 14, lineHeight: 20, includeFontPadding: false, textAlign: 'center' },
  mic: { position: 'absolute', left: 0, right: 0, height: 32, alignItems: 'center' },
});

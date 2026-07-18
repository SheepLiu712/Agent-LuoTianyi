import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { PermissionsAndroid, Platform, Pressable, StyleSheet, Text, useWindowDimensions, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { WebView } from 'react-native-webview';
import Constants from 'expo-constants';
import { auth } from '../components/auth';
import { useCallLogic } from '../hooks/useCallLogic';
import { addDebugTrace } from '../utils/debug_trace';

export default function CallScreen({ onClose }: { onClose: () => void }) {
  const { username, message_token } = auth;
  const insets = useSafeAreaInsets();
  const { width, height } = useWindowDimensions();
  const webviewRef = useRef<WebView>(null);
  const debuggerHost = Constants.expoConfig?.hostUri || 'localhost:8081';
  const assetRoot = 'file:///android_asset/public/';
  const webRoot = __DEV__ ? `http://${debuggerHost}/` : assetRoot;
  const live2dUrl = `${webRoot}live2d/live2d.html?mode=call`;
  const [permissionReady, setPermissionReady] = useState(false);
  const [permissionError, setPermissionError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    if (Platform.OS !== 'android') {
      setPermissionReady(true);
      return () => { cancelled = true; };
    }
    void PermissionsAndroid.request(PermissionsAndroid.PERMISSIONS.RECORD_AUDIO).then((result) => {
      if (cancelled) return;
      if (result === PermissionsAndroid.RESULTS.GRANTED) {
        setPermissionReady(true);
      } else {
        setPermissionError('需要麦克风权限才能进行语音通话');
      }
    }).catch(() => {
      if (!cancelled) setPermissionError('无法获取麦克风权限');
    });
    return () => { cancelled = true; };
  }, []);

  const handleEnded = useCallback(() => {
    onClose();
  }, [onClose]);
  const { status, error, elapsedSeconds, startCall, hangup, handleWebViewMessage } = useCallLogic(
    webviewRef,
    username,
    message_token,
    handleEnded,
    permissionReady,
  );

  useEffect(() => {
    if (!permissionReady) return;
    void startCall();
  }, [permissionReady, startCall]);

  const blocked = status !== 'active';
  const statusText = useMemo(() => {
    if (status === 'active') return `通话中 ${String(Math.floor(elapsedSeconds / 60)).padStart(2, '0')}:${String(elapsedSeconds % 60).padStart(2, '0')}`;
    if (status === 'reconnecting') return '正在恢复通话…';
    if (status === 'ending') return '正在挂断…';
    return permissionReady ? '正在接通…' : '正在准备麦克风…';
  }, [elapsedSeconds, permissionReady, status]);

  return (
    <View style={styles.root}>
      <WebView
        ref={webviewRef}
        source={{ uri: live2dUrl }}
        style={{ width, height }}
        originWhitelist={[webRoot]}
        javaScriptEnabled
        domStorageEnabled
        onMessage={handleWebViewMessage}
        onError={(event) => addDebugTrace('call_live2d', 'webview failed', { error: event.nativeEvent.description })}
      />
      {blocked ? <View pointerEvents="none" style={styles.frostedMask} /> : null}
      <View pointerEvents="none" style={[styles.statusContainer, { top: insets.top + 24 }]}>
        <Text style={styles.statusText}>{statusText}</Text>
        {permissionError || error ? <Text style={styles.errorText}>{permissionError || error}</Text> : null}
      </View>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="挂断"
        onPress={() => permissionError ? onClose() : void hangup()}
        disabled={status === 'ending' || status === 'ended'}
        style={[styles.hangupButton, { bottom: Math.max(insets.bottom + height * 0.12, 56), opacity: status === 'ending' ? 0.55 : 1 }]}
      >
        <Text style={styles.hangupIcon}>×</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: '#11151A' },
  frostedMask: { ...StyleSheet.absoluteFillObject, backgroundColor: 'rgba(90, 96, 103, 0.48)', zIndex: 12 },
  statusContainer: { position: 'absolute', left: 0, right: 0, alignItems: 'center', zIndex: 13 },
  statusText: { color: '#FFFFFF', fontSize: 16, fontWeight: '600', textShadowColor: '#00000099', textShadowRadius: 6 },
  errorText: { color: '#FFD3D3', fontSize: 12, marginTop: 6, paddingHorizontal: 24, textAlign: 'center' },
  hangupButton: {
    position: 'absolute',
    alignSelf: 'center',
    left: '50%',
    marginLeft: -34,
    width: 68,
    height: 68,
    borderRadius: 34,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#E5484D',
    zIndex: 11,
    elevation: 10,
  },
  hangupIcon: { color: '#FFFFFF', fontSize: 42, lineHeight: 48, fontWeight: '300', transform: [{ rotate: '45deg' }] },
});

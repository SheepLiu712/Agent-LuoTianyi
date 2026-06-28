import Constants from 'expo-constants';
import AsyncStorage from '@react-native-async-storage/async-storage';
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Animated,
  Easing,
  FlatList,
  Image,
  Keyboard,
  PanResponder,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  useColorScheme,
  useWindowDimensions,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { WebView } from 'react-native-webview';
import { auth } from '../components/auth';
import { MessageItem } from '../components/ChatBubbles';
import { useChatLogic } from '../hooks/useChatLogic';
import { useHistoryLogic } from '../hooks/useHistoryLogic';
import { addDebugTrace, clearDebugTrace, DebugTraceEntry, subscribeDebugTrace } from '../utils/debug_trace';
import { COLOR_MODE_LABELS, COLOR_MODE_STORAGE_KEY, ColorMode, resolveTheme } from '../utils/theme';
import PreferencesScreen from './preferences';

export default function Index({ onLogout }: { onLogout?: () => void }) {
  const { username, message_token } = auth;
  const insets = useSafeAreaInsets();
  const systemScheme = useColorScheme();
  const { width: screenWidth, height: screenHeight } = useWindowDimensions();
  const live2dHeight = screenHeight * 0.4;
  const drawerWidth = useMemo(() => Math.round(screenWidth * 0.38), [screenWidth]);
  const [keyboardHeight, setKeyboardHeight] = useState(0);
  const [thinkingFrame, setThinkingFrame] = useState(0);
  const [debugOpen, setDebugOpen] = useState(false);
  const [debugEntries, setDebugEntries] = useState<DebugTraceEntry[]>([]);
  const [showPreferences, setShowPreferences] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [colorMode, setColorMode] = useState<ColorMode>('light');
  const webviewRef = useRef<WebView>(null);
  const drawerProgress = useRef(new Animated.Value(0)).current;
  const theme = useMemo(() => resolveTheme(colorMode, systemScheme), [colorMode, systemScheme]);

  const debuggerHost = Constants.expoConfig?.hostUri || 'localhost:8081';
  const live2dAssetRoot = 'file:///android_asset/public/';
  const live2dRoot = __DEV__ ? `http://${debuggerHost}/` : live2dAssetRoot;
  const live2dUrl = `${live2dRoot}live2d/live2d.html`;

  const isAllowedWebviewUrl = (url: string) => {
    return __DEV__ ? url.startsWith(live2dRoot) : url.startsWith(live2dAssetRoot);
  };

  const {
    inputText,
    messages,
    flatListRef,
    canSend,
    canSendImage,
    thinking,
    setInputText,
    addHistoryMessage,
    handleSendText,
    handleSendImage,
    handleWebViewMessage,
    handleToggleAgentAudio,
  } = useChatLogic(webviewRef, username, message_token);

  const { loadHistory, historyLoading } = useHistoryLogic(addHistoryMessage);

  const animateDrawer = useCallback((open: boolean) => {
    setDrawerOpen(open);
    Animated.timing(drawerProgress, {
      toValue: open ? 1 : 0,
      duration: 240,
      easing: Easing.out(Easing.cubic),
      useNativeDriver: true,
    }).start();
  }, [drawerProgress]);

  const openDrawer = useCallback(() => animateDrawer(true), [animateDrawer]);
  const closeDrawer = useCallback(() => animateDrawer(false), [animateDrawer]);

  const panResponder = useMemo(
    () =>
      PanResponder.create({
        onMoveShouldSetPanResponderCapture: (_event, gestureState) => {
          const isHorizontal = Math.abs(gestureState.dx) > 18 && Math.abs(gestureState.dx) > Math.abs(gestureState.dy) * 1.4;
          return isHorizontal && drawerOpen && gestureState.dx < 0;
        },
        onMoveShouldSetPanResponder: (_event, gestureState) => {
          const isHorizontal = Math.abs(gestureState.dx) > 18 && Math.abs(gestureState.dx) > Math.abs(gestureState.dy) * 1.4;
          return isHorizontal && drawerOpen && gestureState.dx < 0;
        },
        onPanResponderMove: (_event, gestureState) => {
          const base = drawerOpen ? drawerWidth : 0;
          const next = Math.max(0, Math.min(drawerWidth, base + gestureState.dx));
          drawerProgress.setValue(next / drawerWidth);
        },
        onPanResponderRelease: (_event, gestureState) => {
          const shouldOpen = gestureState.dx > -drawerWidth * 0.25;
          animateDrawer(shouldOpen);
        },
        onPanResponderTerminate: () => {
          animateDrawer(drawerOpen);
        },
      }),
    [animateDrawer, drawerOpen, drawerProgress, drawerWidth],
  );

  useEffect(() => {
    const unsubscribe = subscribeDebugTrace((entries) => {
      setDebugEntries(entries);
    });
    return unsubscribe;
  }, []);

  useEffect(() => {
    let active = true;
    AsyncStorage.getItem(COLOR_MODE_STORAGE_KEY)
      .then((storedMode) => {
        if (!active) {
          return;
        }
        if (storedMode === 'light' || storedMode === 'dark' || storedMode === 'system') {
          setColorMode(storedMode);
        }
      })
      .catch((error) => {
        addDebugTrace('theme', 'load color mode failed', { error: String(error) });
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!thinking) {
      setThinkingFrame(0);
      return;
    }
    const timer = setInterval(() => {
      setThinkingFrame((prev) => (prev + 1) % 3);
    }, 500);
    return () => clearInterval(timer);
  }, [thinking]);

  const thinkingBubbleFrames = [
    require('../assets/images/thinking_bubble1.png'),
    require('../assets/images/thinking_bubble2.png'),
    require('../assets/images/thinking_bubble3.png'),
  ];

  useEffect(() => {
    const showSubscription = Keyboard.addListener('keyboardDidShow', (e) => {
      setKeyboardHeight(e.endCoordinates.height);
    });
    const hideSubscription = Keyboard.addListener('keyboardDidHide', () => {
      setKeyboardHeight(0);
    });

    return () => {
      showSubscription.remove();
      hideSubscription.remove();
    };
  }, []);

  const historyLoadedRef = useRef(false);
  useEffect(() => {
    if (historyLoadedRef.current) {
      return;
    }
    if (username && message_token) {
      historyLoadedRef.current = true;
      loadHistory(username, message_token);
    }
  }, [username, message_token, loadHistory]);

  const renderFooter = () => {
    if (!historyLoading) {
      return null;
    }
    return (
      <View style={{ paddingVertical: 20 }}>
        <ActivityIndicator size="small" color="#999" />
      </View>
    );
  };

  const visibleDebugEntries = debugEntries.slice(-50).reverse();

  const formatDebugTs = (ts: number) => {
    const d = new Date(ts);
    return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(
      d.getSeconds(),
    ).padStart(2, '0')}.${String(d.getMilliseconds()).padStart(3, '0')}`;
  };

  const drawerTranslateX = drawerProgress.interpolate({
    inputRange: [0, 1],
    outputRange: [-drawerWidth, 0],
  });
  const dimOpacity = drawerProgress.interpolate({
    inputRange: [0, 1],
    outputRange: [0, 0.45],
  });

  const handleToggleDebug = () => {
    setDebugOpen((prev) => !prev);
    closeDrawer();
  };

  const handleOpenPreferences = () => {
    setShowPreferences(true);
    closeDrawer();
  };

  const handleLogout = () => {
    closeDrawer();
    onLogout?.();
  };

  const handleColorMode = (mode: ColorMode) => {
    setColorMode(mode);
    AsyncStorage.setItem(COLOR_MODE_STORAGE_KEY, mode).catch((error) => {
      addDebugTrace('theme', 'save color mode failed', { error: String(error) });
    });
  };

  return (
    <View style={[styles.root, { backgroundColor: theme.root }]}>
      <View style={{ height: insets.top, backgroundColor: theme.safeArea }} />

      <View style={[styles.live2dFixedLayer, { top: insets.top, height: live2dHeight }]}>
        <Image
          source={require('../assets/live2d/backgrounds/bg2.jpg')}
          style={[StyleSheet.absoluteFillObject, styles.backgroundImage]}
          resizeMode="cover"
        />
        <WebView
          ref={webviewRef}
          source={{ uri: live2dUrl }}
          style={styles.webview}
          originWhitelist={[live2dRoot]}
          scrollEnabled={false}
          bounces={false}
          allowFileAccess={true}
          allowFileAccessFromFileURLs={true}
          allowUniversalAccessFromFileURLs={false}
          allowsInlineMediaPlayback={true}
          mediaPlaybackRequiresUserAction={false}
          javaScriptEnabled={true}
          domStorageEnabled={true}
          startInLoadingState={true}
          mixedContentMode="never"
          onShouldStartLoadWithRequest={(request) => isAllowedWebviewUrl(request.url)}
          onMessage={handleWebViewMessage}
          onError={(event) => {
            addDebugTrace('webview', 'error', { detail: JSON.stringify(event.nativeEvent) });
          }}
          onHttpError={(event) => {
            addDebugTrace('webview', 'http error', { detail: JSON.stringify(event.nativeEvent) });
          }}
        />

        <TouchableOpacity style={[styles.menuButton, { backgroundColor: theme.menuButton }]} onPress={openDrawer} activeOpacity={0.75}>
          <Image source={require('../assets/images/menu.png')} style={[styles.menuIcon, { tintColor: theme.text }]} />
        </TouchableOpacity>

        {thinking ? (
          <View style={styles.thinkingBubble}>
            <Image source={thinkingBubbleFrames[thinkingFrame]} style={styles.thinkingBubbleImage} resizeMode="contain" />
          </View>
        ) : null}

        <View pointerEvents="none" style={[StyleSheet.absoluteFillObject, styles.live2dThemeOverlay, { backgroundColor: theme.live2dOverlay }]} />

        {debugOpen ? (
          <View style={[styles.debugPanel, { backgroundColor: theme.debugBackground, borderColor: theme.debugBorder }]}>
            <View style={styles.debugHeaderRow}>
              <Text style={[styles.debugHeaderText, { color: theme.debugHeader }]}>发送调试日志（最近 {visibleDebugEntries.length} 条）</Text>
              <TouchableOpacity onPress={clearDebugTrace}>
                <Text style={[styles.debugClearText, { color: theme.debugAction }]}>清空</Text>
              </TouchableOpacity>
            </View>
            <ScrollView style={styles.debugScroll} contentContainerStyle={styles.debugScrollContent}>
              {visibleDebugEntries.map((entry) => (
                <Text key={entry.id} style={[styles.debugLine, { color: theme.debugText }]}>
                  [{formatDebugTs(entry.ts)}] [{entry.scope}] {entry.message}
                  {entry.detail ? ` | ${entry.detail}` : ''}
                </Text>
              ))}
            </ScrollView>
          </View>
        ) : null}
      </View>

      {showPreferences ? <PreferencesScreen onClose={() => setShowPreferences(false)} theme={theme} /> : null}

      <View style={{ flex: 1, marginTop: live2dHeight, marginBottom: keyboardHeight }}>
        <View style={{ flex: 1 }}>
          <FlatList
            ref={flatListRef}
            data={messages}
            inverted={true}
            renderItem={({ item }) => <MessageItem message={item} onToggleAgentAudio={handleToggleAgentAudio} theme={theme} />}
            keyExtractor={(item) => item.uuid}
            onEndReached={() => {
              if (username && message_token && !historyLoading) {
                loadHistory(username, message_token);
              }
            }}
            onEndReachedThreshold={0.1}
            ListFooterComponent={renderFooter}
            style={[styles.chatList, { backgroundColor: theme.chatList }]}
            contentContainerStyle={styles.chatListContent}
            showsVerticalScrollIndicator={true}
            onScrollBeginDrag={Keyboard.dismiss}
          />
        </View>

        <View
          style={[
            styles.inputContainer,
            { paddingBottom: Math.max(insets.bottom, 10), backgroundColor: theme.inputBar, borderTopColor: theme.inputBorder },
          ]}
        >
          <TextInput
            style={[styles.inputField, { backgroundColor: theme.inputBackground, color: theme.inputText }]}
            placeholder="给天依发消息..."
            placeholderTextColor={theme.placeholder}
            value={inputText}
            onChangeText={setInputText}
            multiline={false}
          />

          <TouchableOpacity style={styles.iconButton} onPress={handleSendImage} disabled={!canSendImage}>
            <Image
              source={
                canSendImage ? require('../assets/images/image_button_activate.png') : require('../assets/images/image_button_un.png')
              }
              style={styles.iconImage}
            />
          </TouchableOpacity>

          <TouchableOpacity style={styles.iconButton} onPress={handleSendText} disabled={!canSend}>
            <Image
              source={canSend ? require('../assets/images/send_button_activate.png') : require('../assets/images/send_button_un.png')}
              style={styles.iconImage}
            />
          </TouchableOpacity>
        </View>
      </View>

      <Animated.View
        pointerEvents={drawerOpen ? 'auto' : 'none'}
        style={[StyleSheet.absoluteFillObject, styles.dimLayer, { backgroundColor: theme.dim, opacity: dimOpacity }]}
      >
        <Pressable style={StyleSheet.absoluteFillObject} onPress={closeDrawer} />
      </Animated.View>

      <Animated.View
        {...panResponder.panHandlers}
        style={[
          styles.drawer,
          {
            width: drawerWidth,
            paddingTop: insets.top + 18,
            paddingBottom: Math.max(insets.bottom, 16),
            backgroundColor: theme.surface,
            borderRightColor: theme.border,
            shadowColor: theme.shadow,
            transform: [{ translateX: drawerTranslateX }],
          },
        ]}
      >
        <Text style={[styles.drawerTitle, { color: theme.text }]}>菜单</Text>
        <Text style={[styles.drawerSubtitle, { color: theme.textMuted }]}>洛天依 Agent</Text>

        <TouchableOpacity style={[styles.drawerItem, { backgroundColor: theme.surfaceAlt }]} onPress={handleToggleDebug} activeOpacity={0.78}>
          <Text style={[styles.drawerItemText, { color: theme.text }]}>{debugOpen ? '收起调试界面' : '打开调试界面'}</Text>
        </TouchableOpacity>

        <TouchableOpacity style={[styles.drawerItem, { backgroundColor: theme.surfaceAlt }]} onPress={handleOpenPreferences} activeOpacity={0.78}>
          <Text style={[styles.drawerItemText, { color: theme.text }]}>配置偏好</Text>
        </TouchableOpacity>

        <View style={[styles.drawerSection, { borderTopColor: theme.border }]}>
          <Text style={[styles.drawerSectionLabel, { color: theme.textMuted }]}>颜色模式</Text>
          {(Object.keys(COLOR_MODE_LABELS) as ColorMode[]).map((mode) => (
            <TouchableOpacity
              key={mode}
              style={[
                styles.colorModeItem,
                { backgroundColor: theme.surface, borderColor: theme.border },
                colorMode === mode && { backgroundColor: theme.accentSoft, borderColor: theme.accent },
              ]}
              onPress={() => handleColorMode(mode)}
              activeOpacity={0.78}
            >
              <Text style={[styles.colorModeText, { color: theme.textSoft }, colorMode === mode && { color: theme.accentText, fontWeight: '700' }]}>
                {COLOR_MODE_LABELS[mode]}
              </Text>
            </TouchableOpacity>
          ))}
        </View>

        <View style={styles.drawerSpacer} />

        {onLogout ? (
          <TouchableOpacity style={[styles.drawerItem, { backgroundColor: theme.dangerSurface }]} onPress={handleLogout} activeOpacity={0.78}>
            <Text style={[styles.drawerItemText, { color: theme.dangerText }]}>登出</Text>
          </TouchableOpacity>
        ) : null}
      </Animated.View>
    </View>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
    backgroundColor: 'white',
  },
  backgroundImage: {
    width: '100%',
    height: '100%',
    transform: [{ scale: 1.1 }, { translateX: 0 }, { translateY: 0 }],
  },
  live2dFixedLayer: {
    position: 'absolute',
    left: 0,
    right: 0,
    backgroundColor: 'transparent',
    zIndex: 10,
    overflow: 'hidden',
  },
  thinkingBubble: {
    position: 'absolute',
    right: '6%',
    top: '25%',
    width: 92,
    aspectRatio: 1,
  },
  thinkingBubbleImage: {
    width: '100%',
    height: '100%',
  },
  live2dThemeOverlay: {
    zIndex: 50,
  },
  webview: {
    flex: 1,
    backgroundColor: 'transparent',
  },
  menuButton: {
    position: 'absolute',
    left: 10,
    top: 10,
    width: 36,
    height: 36,
    borderRadius: 18,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: 'rgba(255, 255, 255, 0.72)',
    zIndex: 60,
    elevation: 12,
  },
  menuIcon: {
    width: 22,
    height: 22,
    resizeMode: 'contain',
  },
  chatList: {
    flex: 1,
    backgroundColor: '#E8E8E8',
  },
  chatListContent: {
    paddingTop: 10,
    paddingBottom: 10,
  },
  inputContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#f0f0f0',
    padding: 10,
    borderTopWidth: 1,
    borderTopColor: '#ddd',
  },
  inputField: {
    flex: 1,
    height: 40,
    backgroundColor: '#ffffff',
    borderRadius: 20,
    paddingHorizontal: 15,
    marginRight: 10,
  },
  iconButton: {
    padding: 5,
    marginLeft: 5,
  },
  iconImage: {
    width: 30,
    height: 30,
    resizeMode: 'stretch',
  },
  debugPanel: {
    position: 'absolute',
    left: 8,
    right: 8,
    top: 54,
    bottom: 8,
    borderWidth: 1,
    borderColor: '#203244',
    borderRadius: 10,
    backgroundColor: '#0f1720',
    zIndex: 70,
    elevation: 14,
    overflow: 'hidden',
  },
  debugHeaderRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 10,
    paddingTop: 8,
    paddingBottom: 6,
  },
  debugHeaderText: {
    color: '#b9d7ff',
    fontSize: 12,
    fontWeight: '600',
  },
  debugClearText: {
    color: '#79ffa8',
    fontSize: 12,
    fontWeight: '600',
  },
  debugScroll: {
    flex: 1,
  },
  debugScrollContent: {
    paddingHorizontal: 10,
    paddingBottom: 10,
  },
  debugLine: {
    color: '#d9e4f0',
    fontSize: 11,
    lineHeight: 15,
    marginBottom: 2,
  },
  dimLayer: {
    zIndex: 90,
    backgroundColor: '#000',
  },
  drawer: {
    position: 'absolute',
    left: 0,
    top: 0,
    bottom: 0,
    zIndex: 100,
    elevation: 18,
    backgroundColor: '#ffffff',
    borderRightWidth: 1,
    borderRightColor: '#d9e1e8',
    paddingHorizontal: 12,
    shadowColor: '#000',
    shadowOpacity: 0.18,
    shadowRadius: 12,
    shadowOffset: { width: 4, height: 0 },
  },
  drawerTitle: {
    fontSize: 19,
    fontWeight: '700',
    color: '#243447',
  },
  drawerSubtitle: {
    marginTop: 3,
    marginBottom: 18,
    fontSize: 12,
    color: '#7b8794',
  },
  drawerItem: {
    minHeight: 42,
    borderRadius: 8,
    paddingHorizontal: 10,
    paddingVertical: 10,
    justifyContent: 'center',
    backgroundColor: '#f4f8fb',
    marginBottom: 10,
  },
  drawerItemText: {
    fontSize: 14,
    fontWeight: '600',
    color: '#243447',
  },
  drawerSection: {
    marginTop: 2,
    paddingTop: 10,
    borderTopWidth: 1,
    borderTopColor: '#edf1f5',
  },
  drawerSectionLabel: {
    fontSize: 12,
    fontWeight: '700',
    color: '#778492',
    marginBottom: 8,
  },
  colorModeItem: {
    minHeight: 34,
    borderRadius: 8,
    paddingHorizontal: 10,
    justifyContent: 'center',
    marginBottom: 6,
    backgroundColor: '#ffffff',
    borderWidth: 1,
    borderColor: '#e3e8ee',
  },
  colorModeItemSelected: {
    backgroundColor: '#e8f6ff',
    borderColor: '#66CCFF',
  },
  colorModeText: {
    fontSize: 13,
    color: '#4b5967',
  },
  colorModeTextSelected: {
    color: '#1674a3',
    fontWeight: '700',
  },
  drawerSpacer: {
    flex: 1,
  },
  logoutItem: {
    backgroundColor: '#fff1f1',
  },
  logoutItemText: {
    color: '#c24141',
  },
});

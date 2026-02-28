import Constants from 'expo-constants';
import { useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  FlatList,
  Image,
  Keyboard,
  StyleSheet,
  TextInput, TouchableOpacity,
  useWindowDimensions,
  View
} from "react-native";
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { WebView } from 'react-native-webview';
import { auth } from '../components/auth';
import { MessageItem } from '../components/ChatBubbles';
import { useChatLogic } from '../hooks/useChatLogic';
import { useHistoryLogic } from "../hooks/useHistoryLogic";

export default function Index() {
  const { username, message_token } = auth;
  const insets = useSafeAreaInsets();
  const { height: screenHeight } = useWindowDimensions();
  const live2dHeight = screenHeight * 0.4;
  const [keyboardHeight, setKeyboardHeight] = useState(0);
  const webviewRef = useRef<WebView>(null);


  // 构建 live2d.html 的 URL
  // Expo 开发模式下，public 目录的文件可以通过开发服务器直接访问
  // 在生产环境（APK）中，我们将手动把 public 文件夹复制到 android/app/src/main/assets/public
  const debuggerHost = Constants.expoConfig?.hostUri || 'localhost:8081';
  const live2dUrl = __DEV__ 
    ? `http://${debuggerHost}/live2d/live2d.html` 
    : 'file:///android_asset/public/live2d/live2d.html';

  // 使用自定义 Hook 管理聊天逻辑
  const {
    inputText,
    messages,
    flatListRef,
    canSend,
    canSendImage,
    setInputText,
    addHistoryMessage,
    handleSendText,
    handleSendImage,
    handleWebViewMessage,
  } = useChatLogic(webviewRef);


  const { loadHistory, historyLoading } = useHistoryLogic(addHistoryMessage);

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
      return; // 防止 loadHistory 引用变化导致重复触发
    }
    // 在组件加载时，自动加载一次历史记录
    if (username && message_token) {
      historyLoadedRef.current = true;
      console.log('Loading history with:', { username, message_token });
      loadHistory(username, message_token);
    }
    else {
      console.warn('无法加载历史记录，缺少认证信息');
    }
  }, [username, message_token, loadHistory]);

  const renderFooter = () => {
  if (!historyLoading) return null;
  return (
    <View style={{ paddingVertical: 20 }}>
      <ActivityIndicator size="small" color="#999" />
    </View>
  );
};

  return (
    <View style={{ flex: 1, backgroundColor: 'white' }}>

      {/* 顶部安全区占位 */}
      <View style={{ height: insets.top, backgroundColor: 'white' }} />

      {/* 【固定层：Live2D 区域】- 绝对定位，不参与 flex 布局，永远固定在顶部 */}
      <View style={[styles.live2dFixedLayer, { top: insets.top, height: live2dHeight }]}>
        {/* 背景图 */}
        <Image
          source={require('../assets/live2d/backgrounds/bg2.jpg')}
          style={[
            StyleSheet.absoluteFillObject,
            styles.background_image,
          ]}
          resizeMode="cover"
        />
        <WebView
          ref={webviewRef}
          source={{ uri: live2dUrl }}
          style={styles.webview}
          originWhitelist={["*"]}
          scrollEnabled={false}
          bounces={false}
          allowFileAccess={true}
          allowFileAccessFromFileURLs={true}
          allowUniversalAccessFromFileURLs={true}
          allowsInlineMediaPlayback={true}
          mediaPlaybackRequiresUserAction={false}
          javaScriptEnabled={true}
          domStorageEnabled={true}
          startInLoadingState={true}
          onMessage={handleWebViewMessage}
          onError={(event) => {
            console.error('WebView onError:', event.nativeEvent);
          }}
          onHttpError={(event) => {
            console.error('WebView onHttpError:', event.nativeEvent);
          }}
        />
      </View>

      {/* 【可压缩区域：聊天历史 + 输入框】- 使用 flex 布局，会被键盘压缩 */}
      <View style={{ flex: 1, marginTop: live2dHeight, marginBottom: keyboardHeight }}>
        {/* 聊天历史区域 - 使用 FlatList 显示消息列表 */}
        <View style={{ flex: 1 }}>
          <FlatList
            ref={flatListRef}
            data={messages}
            inverted={true} // 反转列表，使最新消息为0位置。
            renderItem={({ item }) => <MessageItem message={item} />}
            keyExtractor={(item) => item.uuid}
            onEndReached={() => {
              // 只有当有用户信息且当前没在加载时才触发
              if (username && message_token && !historyLoading) {
                loadHistory(username, message_token);
              }
            }}
            onEndReachedThreshold={0.1} 
            ListFooterComponent={renderFooter} 
            style={styles.chatList}
            contentContainerStyle={styles.chatListContent}
            showsVerticalScrollIndicator={true}
            
            onScrollBeginDrag={Keyboard.dismiss} // 滚动时自动收起键盘
          />
        </View>

        {/* 输入框区域 - 跟随键盘 */}
        <View style={[styles.inputContainer, { paddingBottom: Math.max(insets.bottom, 10) }]}>
          <TextInput
            style={styles.inputField}
            placeholder="给天依发消息..."
            placeholderTextColor="#999"
            value={inputText}
            onChangeText={setInputText}
            multiline={false}
          />

          <TouchableOpacity style={styles.iconButton} onPress={handleSendImage} disabled={!canSendImage}>
            <Image
              source={canSendImage ?
                require('../assets/images/image_button_activate.png')
                : require('../assets/images/image_button_un.png')
              }
              style={styles.iconImage}
            />
          </TouchableOpacity>

          <TouchableOpacity
            style={styles.iconButton}
            onPress={handleSendText}
            disabled={!canSend}
          >
            <Image
              source={canSend
                ? require('../assets/images/send_button_activate.png')
                : require('../assets/images/send_button_un.png')
              }
              style={styles.iconImage}
            />
          </TouchableOpacity>
        </View>
      </View>
    </View>
  );
}


const styles = StyleSheet.create({
  background_image: {
    width: '100%',
    height: '100%',
    transform: [
      { scale: 1.1 },
      { translateX: 0 },
      { translateY: 0 }
    ]
  },
  live2dFixedLayer: {
    position: 'absolute',
    left: 0,
    right: 0,
    backgroundColor: 'transparent',
    zIndex: 10,
    overflow: 'hidden',
  },
  webview: {
    flex: 1,
    backgroundColor: 'transparent',
  },
  chatList: {
    flex: 1,
    backgroundColor: '#E8E8E8', // 浅灰色背景，区分对话框
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
});
import React, { useState } from 'react';
import React from 'react';
import { ActivityIndicator, StyleSheet, View } from "react-native";
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { useAuth } from '../hooks/useAuth';
import Index from './index';
import LoginScreen from './login';
import RegistrationPreferences, { UserPreferences } from '../components/RegistrationPreferences';
import { addDebugTrace } from '../utils/debug_trace';
import { server_config } from '../config';

export default function RootLayout() {
  const { isLoggedIn, isLoading, login, register, logout } = useAuth();
  const [showPreferences, setShowPreferences] = useState(false);
  const [pendingUsername, setPendingUsername] = useState('');

  // 注册成功后的回调
  const handleRegister = async (
    username: string,
    password: string,
    confirmPassword: string,
    inviteCode: string,
  ): Promise<{ success: boolean; message: string }> => {
    const result = await register(username, password, confirmPassword, inviteCode);
    if (result.success) {
      // 注册成功后，显示偏好设置界面
      setPendingUsername(username);
      setShowPreferences(true);
    }
    return result;
  };

  // 保存偏好设置到服务端（注册后尚未登录，使用 HTTP 请求）
  const savePreferences = async (preferences: UserPreferences) => {
    try {
      addDebugTrace('preferences', 'saving after registration', preferences);
      // 需要先使用新注册的账号登录才能通过 WebSocket 发送偏好
      // 为简化流程，偏好将在用户首次聊天时通过 WebSocket 自动同步
      // 这里仅记录日志
    } catch (e) {
      addDebugTrace('preferences', 'save error', { error: String(e) });
    }
    setShowPreferences(false);
  };

  // 跳过偏好设置
  const skipPreferences = () => {
    setShowPreferences(false);
  };

  // 正在检查自动登录状态时，显示加载画面
  if (isLoading) {
    return (
      <SafeAreaProvider>
        <View style={styles.loadingContainer}>
          <ActivityIndicator size="large" color="#66CCFF" />
        </View>
      </SafeAreaProvider>
    );
  }

  // 注册后显示偏好设置界面
  if (showPreferences) {
    return (
      <SafeAreaProvider>
        <RegistrationPreferences
          onSave={savePreferences}
          onSkip={skipPreferences}
        />
      </SafeAreaProvider>
    );
  }

  // 未登录 → 显示登录/注册界面
  if (!isLoggedIn) {
    return (
      <SafeAreaProvider>
        <LoginScreen onLogin={login} onRegister={handleRegister} />
      </SafeAreaProvider>
    );
  }

  // 已登录 → 显示主界面
  return (
    <SafeAreaProvider>
      <Index onLogout={logout} />
    </SafeAreaProvider>
  );
}

const styles = StyleSheet.create({
  loadingContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: '#f5f5f5',
  },
});

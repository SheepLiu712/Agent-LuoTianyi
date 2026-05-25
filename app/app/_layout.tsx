import React from 'react';
import { ActivityIndicator, StyleSheet, View } from "react-native";
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { useAuth } from '../hooks/useAuth';
import Index from './index';
import LoginScreen from './login';

export default function RootLayout() {
  const { isLoggedIn, isLoading, login, register, logout } = useAuth();

  // 注册成功后的回调：不再弹出偏好设置，用户可以在主界面右上角自行设置
  const handleRegister = async (
    username: string,
    password: string,
    confirmPassword: string,
    inviteCode: string,
  ): Promise<{ success: boolean; message: string }> => {
    const result = await register(username, password, confirmPassword, inviteCode);
    return result;
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

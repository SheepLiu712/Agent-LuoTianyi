import AsyncStorage from '@react-native-async-storage/async-storage';
import { useCallback, useEffect, useState } from 'react';
import { auth } from '../components/auth';
import { server_config } from '../config/index';
import { encryptPassword, getPublicKey } from '../utils/crypto';

const AUTO_LOGIN_KEY = 'auto_login';
const USERNAME_KEY = 'saved_username';
const AUTOLOGIN_TOKEN_KEY = 'auto_login_token';

export interface AuthState {
  isLoggedIn: boolean;
  isLoading: boolean;  // 正在向服务器请求
  publicKeyLoaded: boolean;  // 公钥是否已加载
}

export function useAuth() {
  const [authState, setAuthState] = useState<AuthState>({
    isLoggedIn: false,
    isLoading: true,
    publicKeyLoaded: false,
  });

  const checkAutoLogin = useCallback(async () => {
    try {
      const autoLogin = await AsyncStorage.getItem(AUTO_LOGIN_KEY);
      if (autoLogin === 'true') {
        const savedUsername = await AsyncStorage.getItem(USERNAME_KEY);
        const autoLoginToken = await AsyncStorage.getItem(AUTOLOGIN_TOKEN_KEY);
        if (savedUsername && autoLoginToken) { // 此时可以尝试自动登录
          const response = await fetch(`${server_config.BASE_URL}/auth/auto_login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              username: savedUsername,
              token: autoLoginToken,
            }),
          });

          if (response.ok) {
            console.log('自动登录成功');
            const result = await response.json();
            // 获取到新的token后可以更新存储的token
            await AsyncStorage.setItem(AUTOLOGIN_TOKEN_KEY, result.login_token);
            await AsyncStorage.setItem(USERNAME_KEY, result.user_id);
            setAuthState(prev => ({
              ...prev,
              isLoggedIn: true,
              isLoading: false,
            }));
            auth.username = savedUsername;
            auth.message_token = result.message_token;
            return;
          }
        }
      }
    } catch (e) {
      console.error('自动登录检查失败:', e);
    }
    setAuthState(prev => ({ ...prev, isLoading: false }));
  }, []);

  const initializeAuth = useCallback(async () => {
    // 首先尝试获取公钥
    try {
      console.log('正在获取服务器公钥...');
      const publicKey = await getPublicKey();
      if (publicKey) {
        console.log('公钥获取成功');
        setAuthState(prev => ({ ...prev, publicKeyLoaded: true }));
      } else {
        console.warn('公钥获取失败，登录功能可能受限');
      }
    } catch (error) {
      console.error('获取公钥时发生错误:', error);
    }

    // 然后检查自动登录
    await checkAutoLogin();
  }, [checkAutoLogin]);

  // 启动时检查是否有自动登录凭据，并获取公钥
  useEffect(() => {
    initializeAuth();
  }, [initializeAuth]);

  const login = useCallback(async (username: string, password: string, autoLogin: boolean): Promise<{ success: boolean; message: string }> => {
    try {
      // 验证输入
      if (!username.trim() || !password.trim()) {
        return { success: false, message: '用户名或密码不能为空' };
      }

      // 加密密码
      const encryptedPassword = await encryptPassword(password);
      if (!encryptedPassword) {
        console.warn('密码加密失败');
        return { success: false, message: '登录失败，无法加密密码' };
      }
      // 发送登录请求
      const response = await fetch(`${server_config.BASE_URL}/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          username,
          password: encryptedPassword,
        }),
      });
      const result = await response.json();
      if (!response.ok) {
        return { success: false, message: result.detail || '登录失败' };
      }

      // 保存自动登录设置
      if (autoLogin) {
        await AsyncStorage.setItem(AUTO_LOGIN_KEY, 'true');
        await AsyncStorage.setItem(USERNAME_KEY, username);
        await AsyncStorage.setItem(AUTOLOGIN_TOKEN_KEY, result.login_token); // 存储登录后从服务器获取的token
      } else {
        await AsyncStorage.removeItem(AUTO_LOGIN_KEY);
        await AsyncStorage.removeItem(USERNAME_KEY);
        await AsyncStorage.removeItem(AUTOLOGIN_TOKEN_KEY);
      }
      console.log('登录成功，用户:', username);
      setAuthState(prev => ({
        ...prev,
        isLoggedIn: true,
      }));
      auth.username = username;
      auth.message_token = result.message_token;

      return { success: true, message: '登录成功' };
    } catch (e) {
      console.error('登录失败:', e);
      return { success: false, message: '登录失败，请联系管理员' };
    }
  }, []);

  const register = useCallback(async (username: string, password: string, inviteCode: string): Promise<{ success: boolean; message: string }> => {
    try {
      // TODO: 替换为实际的服务器注册请求
      if (!username.trim()) return { success: false, message: '用户名不能为空' };
      if (!password.trim()) return { success: false, message: '密码不能为空' };
      if (!inviteCode.trim()) return { success: false, message: '邀请码不能为空' };

      // 加密密码
      const encryptedPassword = await encryptPassword(password);
      if (!encryptedPassword) {
        console.warn('密码加密失败，使用明文传输（不安全）');
        return { success: false, message: '注册失败，无法加密密码' };
      }

      // 发送注册请求
      const response = await fetch(`${server_config.BASE_URL}/auth/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          username,
          password: encryptedPassword,
          invite_code: inviteCode,
        }),
      });
      const result = await response.json();
      if (!response.ok) {
        return { success: false, message: result.detail || '注册失败' };
      }


      return { success: true, message: '注册成功，请登录' };
    } catch (e) {
      console.error('注册失败:', e);
      return { success: false, message: '注册失败，请联系管理员' };
    }
  }, []);

  const logout = useCallback(async () => {
    setAuthState(prev => ({
      ...prev,
      isLoggedIn: false,
    }));
    auth.username = "";
    auth.message_token = "";
  }, []);

  return {
    ...authState,
    login,
    register,
    logout,
  };
}

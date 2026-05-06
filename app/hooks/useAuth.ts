import AsyncStorage from '@react-native-async-storage/async-storage';
import { useCallback, useEffect, useState } from 'react';
import { auth } from '../components/auth';
import { server_config } from '../config/index';
import { encryptPassword, getPublicKey } from '../utils/crypto';
import { addDebugTrace } from '../utils/debug_trace';

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
            addDebugTrace('auth', 'auto login ok');
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
      addDebugTrace('auth', 'auto login check failed', { error: String(e) });
    }
    setAuthState(prev => ({ ...prev, isLoading: false }));
  }, []);

  const initializeAuth = useCallback(async () => {
    // 首先尝试获取公钥
    try {
      addDebugTrace('auth', 'fetching public key');
      const publicKey = await getPublicKey();
      if (publicKey) {
        addDebugTrace('auth', 'public key loaded');
        setAuthState(prev => ({ ...prev, publicKeyLoaded: true }));
      } else {
        addDebugTrace('auth', 'public key failed');
      }
    } catch (error) {
      addDebugTrace('auth', 'public key error', { error: String(error) });
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
        addDebugTrace('auth', 'password encrypt failed');
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
      addDebugTrace('auth', 'login ok', { username });
      setAuthState(prev => ({
        ...prev,
        isLoggedIn: true,
      }));
      auth.username = username;
      auth.message_token = result.message_token;

      return { success: true, message: '登录成功' };
    } catch (e) {
      addDebugTrace('auth', 'login error', { error: String(e) });
      return { success: false, message: '登录失败，请联系管理员' };
    }
  }, []);

  const register = useCallback(async (
    username: string,
    password: string,
    confirmPassword: string,
    inviteCode: string,
  ): Promise<{ success: boolean; message: string }> => {
    try {
      // TODO: 替换为实际的服务器注册请求
      if (!username.trim()) return { success: false, message: '用户名不能为空' };
      if (!password.trim()) return { success: false, message: '密码不能为空' };
      if (password !== confirmPassword) return { success: false, message: '两次密码不一致' };
      if (!inviteCode.trim()) return { success: false, message: '邀请码不能为空' };

      // 加密密码
      const encryptedPassword = await encryptPassword(password);
      if (!encryptedPassword) {
        addDebugTrace('auth', 'register: password encrypt failed');
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
      addDebugTrace('auth', 'register error', { error: String(e) });
      return { success: false, message: '注册失败，请联系管理员' };
    }
  }, []);

  const logout = useCallback(async () => {
    try {
      await AsyncStorage.removeItem(AUTO_LOGIN_KEY);
      await AsyncStorage.removeItem(USERNAME_KEY);
      await AsyncStorage.removeItem(AUTOLOGIN_TOKEN_KEY);
      auth.username = '';
      auth.message_token = '';
      setAuthState(prev => ({ ...prev, isLoggedIn: false }));
    } catch (e) {
      addDebugTrace('auth', 'logout error', { error: String(e) });
    }
  }, []);

  return {
    ...authState,
    login,
    register,
    logout,
  };
}

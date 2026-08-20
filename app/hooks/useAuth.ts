import AsyncStorage from '@react-native-async-storage/async-storage';
import * as SecureStore from 'expo-secure-store';
import { useCallback, useEffect, useState } from 'react';
import { auth } from '../components/auth';
import { loadSavedServerUrl, server_config } from '../config/index';
import { encryptPassword, getPublicKey, type PublicKeyFailureReason } from '../utils/crypto';
import { addDebugTrace } from '../utils/debug_trace';
import { classifyAutoLoginStatus, runAutoLoginWithRetry } from '../utils/auto_login';

const AUTO_LOGIN_KEY = 'auto_login';
const USERNAME_KEY = 'saved_username';
const AUTOLOGIN_TOKEN_KEY = 'auto_login_token';

/** 根据加密失败原因生成面向用户的明确提示 */
function describeEncryptFailure(scope: '登录' | '注册', reason: PublicKeyFailureReason | 'crypto'): string {
  switch (reason) {
    case 'network':
      return `${scope}失败，无法获取加密密钥，请检查网络后重试`;
    case 'server':
      return `${scope}失败，服务器返回异常，请稍后重试`;
    default:
      return `${scope}失败，无法加密密码`;
  }
}

// 自动登录进行中的标记，避免并发调用同时轮换 login_token 导致会话失效
let autoLoginInFlight: Promise<boolean> | null = null;

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

  /**
   * 尝试自动登录：瞬时故障（网络错误/5xx/429）按退避重试，
   * 只有 token 被明确拒绝（401/403）时才判定需要重新登录。
   * 返回是否登录成功。
   */
  const tryAutoLogin = useCallback(async (username: string, token: string): Promise<boolean> => {
    const outcome = await runAutoLoginWithRetry(async (attemptNumber) => {
      try {
        const response = await fetch(`${server_config.BASE_URL}/auth/auto_login`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ username, token }),
        });
        if (response.ok) {
          const result = await response.json();
          // 获取到新的token后可以更新存储的token
          await SecureStore.setItemAsync(AUTOLOGIN_TOKEN_KEY, result.login_token);
          await AsyncStorage.setItem(USERNAME_KEY, result.user_id);
          auth.username = username;
          auth.message_token = result.message_token;
          return 'ok';
        }
        const classified = classifyAutoLoginStatus(response.status);
        if (classified === 'invalid') {
          addDebugTrace('auth', 'auto login rejected', { status: response.status, attempt: attemptNumber });
        } else {
          addDebugTrace('auth', 'auto login transient failure', { status: response.status, attempt: attemptNumber });
        }
        return classified;
      } catch (e) {
        // 网络波动/超时视为瞬时故障，退避后重试
        addDebugTrace('auth', 'auto login network failure', { error: String(e), attempt: attemptNumber });
        return 'transient';
      }
    });

    if (outcome !== 'ok') {
      addDebugTrace('auth', 'auto login failed', { outcome });
      return false;
    }

    addDebugTrace('auth', 'auto login ok');
    setAuthState(prev => ({
      ...prev,
      isLoggedIn: true,
      isLoading: false,
    }));
    return true;
  }, []);

  const checkAutoLogin = useCallback(async () => {
    try {
      const autoLogin = await AsyncStorage.getItem(AUTO_LOGIN_KEY);
      if (autoLogin === 'true') {
        const savedUsername = await AsyncStorage.getItem(USERNAME_KEY);
        let autoLoginToken = await SecureStore.getItemAsync(AUTOLOGIN_TOKEN_KEY);
        if (!autoLoginToken) {
          const legacyToken = await AsyncStorage.getItem(AUTOLOGIN_TOKEN_KEY);
          if (legacyToken) {
            await SecureStore.setItemAsync(AUTOLOGIN_TOKEN_KEY, legacyToken);
            await AsyncStorage.removeItem(AUTOLOGIN_TOKEN_KEY);
            autoLoginToken = legacyToken;
          }
        }
        if (savedUsername && autoLoginToken) { // 此时可以尝试自动登录
          // 并发保护：重复进入时复用进行中的自动登录，避免重复请求竞争轮换 token
          if (!autoLoginInFlight) {
            autoLoginInFlight = tryAutoLogin(savedUsername, autoLoginToken);
            try {
              await autoLoginInFlight;
            } finally {
              autoLoginInFlight = null;
            }
          } else {
            await autoLoginInFlight;
          }
        }
      }
    } catch (e) {
      addDebugTrace('auth', 'auto login check failed', { error: String(e) });
    }
    // 自动登录成功路径已设置 isLoading=false；失败路径在这里兜底关闭 loading
    setAuthState(prev => (prev.isLoading ? { ...prev, isLoading: false } : prev));
  }, [tryAutoLogin]);

  const initializeAuth = useCallback(async () => {
    // 加载保存的自定义服务器地址
    await loadSavedServerUrl();

    // 然后尝试获取公钥
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
      const encrypted = await encryptPassword(password);
      if (!encrypted.ok) {
        addDebugTrace('auth', 'password encrypt failed', { reason: encrypted.reason });
        return { success: false, message: describeEncryptFailure('登录', encrypted.reason) };
      }
      // 发送登录请求
      const response = await fetch(`${server_config.BASE_URL}/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          username,
          password: encrypted.encrypted,
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
        await SecureStore.setItemAsync(AUTOLOGIN_TOKEN_KEY, result.login_token); // 存储登录后从服务器获取的token
        await AsyncStorage.removeItem(AUTOLOGIN_TOKEN_KEY);
      } else {
        await AsyncStorage.removeItem(AUTO_LOGIN_KEY);
        await AsyncStorage.removeItem(USERNAME_KEY);
        await SecureStore.deleteItemAsync(AUTOLOGIN_TOKEN_KEY);
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
      const encrypted = await encryptPassword(password);
      if (!encrypted.ok) {
        addDebugTrace('auth', 'register: password encrypt failed', { reason: encrypted.reason });
        return { success: false, message: describeEncryptFailure('注册', encrypted.reason) };
      }

      // 发送注册请求
      const response = await fetch(`${server_config.BASE_URL}/auth/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          username,
          password: encrypted.encrypted,
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
      // 清除公钥缓存，下次登录会重新从服务器获取
      const { clearCachedPublicKey } = await import('../utils/crypto');
      clearCachedPublicKey();
      await AsyncStorage.removeItem(AUTO_LOGIN_KEY);
      await AsyncStorage.removeItem(USERNAME_KEY);
      await SecureStore.deleteItemAsync(AUTOLOGIN_TOKEN_KEY);
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

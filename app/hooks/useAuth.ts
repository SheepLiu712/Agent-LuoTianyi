import AsyncStorage from '@react-native-async-storage/async-storage';
import * as SecureStore from 'expo-secure-store';
import { useCallback, useEffect, useRef, useState } from 'react';
import { auth } from '../components/auth';
import { loadSavedServerUrl, server_config } from '../config/index';
import { encryptPassword, getPublicKey, type PublicKeyFailureReason } from '../utils/crypto';
import { addDebugTrace } from '../utils/debug_trace';
import { classifyAutoLoginStatus, runAutoLoginWithRetry } from '../utils/auto_login';
import { voicePlaybackManager } from '../utils/voice_playback_manager';
import { AgreementPayload, parseAgreementPayload } from '../utils/agreement';
import { loadRegistrationResume, markRegistrationSameUserLogin, markRegistrationUnknown, saveRegistrationResume, clearRegistrationResume } from '../utils/registration_resume';
import { classifyAgreementSubmitFailure } from '../utils/agreement_failure';
import { authFetch, isUnknownRegistrationResult } from '../utils/auth_request';

const AUTO_LOGIN_KEY = 'auto_login';
const USERNAME_KEY = 'saved_username';
const AUTOLOGIN_TOKEN_KEY = 'auto_login_token';

/** 根据加密失败原因生成面向用户的明确提示 */
function describeEncryptFailure(scope: '登录' | '注册' | '协议提交', reason: PublicKeyFailureReason | 'crypto'): string {
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

async function clearStoredAutoLoginCredentials(): Promise<void> {
  await AsyncStorage.removeItem(AUTO_LOGIN_KEY);
  await AsyncStorage.removeItem(USERNAME_KEY);
  await SecureStore.deleteItemAsync(AUTOLOGIN_TOKEN_KEY);
  await AsyncStorage.removeItem(AUTOLOGIN_TOKEN_KEY);
}

export interface AuthState {
  isLoggedIn: boolean;
  isLoading: boolean;  // 正在向服务器请求
  publicKeyLoaded: boolean;  // 公钥是否已加载
}

export type AgreementCredential =
  | { kind: 'password'; username: string; password: string; autoLogin?: boolean }
  | { kind: 'auto_login'; username: string; token: string };
export interface PendingAgreement {
  agreement: AgreementPayload;
  credential: AgreementCredential;
  registration?: { username: string; password: string; confirmPassword: string; inviteCode: string; requestId: string };
  phase?: 'sign' | 'login';
}
export interface AuthResult { success: boolean; message: string; code?: string; agreement?: AgreementPayload; status?: number }

/** 失败响应里取一句可显示的文案。

    ``detail`` 可能是字符串，也可能是对象——例如运行时未就绪的 503 返回
    ``{detail: {ok, code, message, runtime}}``。直接插值对象会渲染成 ``[object Object]``。
    */
function agreementFailureMessage(detail: unknown): string {
  if (typeof detail === 'string' && detail) {
    return detail;
  }
  if (detail && typeof detail === 'object') {
    const message = (detail as { message?: unknown }).message;
    if (typeof message === 'string' && message) {
      return message;
    }
  }
  return '用户协议加载失败，请重试';
}

interface AgreementFetchOptions {
  signal?: AbortSignal;
  timeoutMs?: number;
}

async function getCurrentAgreementForAuth(): Promise<AgreementPayload | null> {
  const result = await fetchCurrentAgreement();
  return result.success ? result.data : null;
}

export async function fetchCurrentAgreement(
  options: AgreementFetchOptions = {},
): Promise<{ success: true; data: AgreementPayload } | { success: false; message: string }> {
  const controller = new AbortController();
  const abortFromCaller = () => controller.abort();
  if (options.signal?.aborted) {
    controller.abort();
  } else {
    options.signal?.addEventListener('abort', abortFromCaller, { once: true });
  }
  const timeout = setTimeout(
    () => controller.abort(),
    options.timeoutMs ?? server_config.API_TIMEOUT,
  );

  try {
    const response = await fetch(`${server_config.BASE_URL}/auth/agreement`, {
      signal: controller.signal,
    });
    const result: unknown = await response.json().catch(() => null);
    if (!response.ok) {
      addDebugTrace('auth', 'agreement fetch failed', { status: response.status });
      const detail = result && typeof result === 'object' ? (result as { detail?: unknown }).detail : null;
      return { success: false, message: agreementFailureMessage(detail) };
    }
    const data = parseAgreementPayload(result);
    if (!data) {
      addDebugTrace('auth', 'agreement fetch invalid payload');
      return { success: false, message: '用户协议加载失败，请重试' };
    }
    addDebugTrace('auth', 'agreement fetch ok');
    return { success: true, data };
  } catch (e) {
    addDebugTrace('auth', 'agreement fetch error', { error: String(e) });
    return { success: false, message: '用户协议加载失败，请重试' };
  } finally {
    clearTimeout(timeout);
    options.signal?.removeEventListener('abort', abortFromCaller);
  }
}

export function useAuth() {
  const [authState, setAuthState] = useState<AuthState>({
    isLoggedIn: false,
    isLoading: true,
    publicKeyLoaded: false,
  });
  const [pendingAgreement, setPendingAgreement] = useState<PendingAgreement | null>(null);
  const registrationIdentityLock = useRef<Record<string, string>>({});
  const autoLoginLastStatus = useRef<number | undefined>(undefined);
  const dismissAgreement = useCallback(() => setPendingAgreement(null), []);

  /**
   * 尝试自动登录：瞬时故障（网络错误/5xx/429）按退避重试，
   * 只有 token 被明确拒绝（401/403）时才判定需要重新登录。
   * 返回是否登录成功。
   */
  const tryAutoLogin = useCallback(async (username: string, token: string): Promise<boolean> => {
    const outcome = await runAutoLoginWithRetry(async (attemptNumber) => {
      try {
        const response = await authFetch(`${server_config.BASE_URL}/auth/auto_login`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ username, token }),
        });
        autoLoginLastStatus.current = response.status;
        if (response.ok) {
          const result = await response.json();
          // 获取到新的token后可以更新存储的token
          await SecureStore.setItemAsync(AUTOLOGIN_TOKEN_KEY, result.login_token);
          await AsyncStorage.setItem(USERNAME_KEY, result.user_id);
          auth.username = username;
          auth.message_token = result.message_token;
          return 'ok';
        }
        if (response.status === 403) {
          const body: any = await response.json().catch(() => ({}));
          if (body.code === 'AGREEMENT_REQUIRED') {
            const agreement = await getCurrentAgreementForAuth();
            if (agreement) setPendingAgreement({ agreement, credential: { kind: 'auto_login', username, token } });
            return 'invalid';
          }
        }
        const classified = classifyAutoLoginStatus(response.status);
        if (classified === 'invalid') {
          await clearStoredAutoLoginCredentials();
          addDebugTrace('auth', 'auto login rejected', { status: response.status, attempt: attemptNumber });
        } else {
          addDebugTrace('auth', 'auto login transient failure', { status: response.status, attempt: attemptNumber });
        }
        return classified;
      } catch (e) {
        autoLoginLastStatus.current = undefined;
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

  const login = useCallback(async (username: string, password: string, autoLogin: boolean): Promise<AuthResult> => {
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
      const response = await authFetch(`${server_config.BASE_URL}/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          username,
          password: encrypted.encrypted,
        }),
      });
      const result = await response.json();
      if (!response.ok) {
        const code = result.code || result.detail?.code;
        if (response.status === 403 && code === 'AGREEMENT_REQUIRED') {
          const agreement = await getCurrentAgreementForAuth();
          if (agreement) setPendingAgreement({ agreement, credential: { kind: 'password', username, password, autoLogin }, phase: 'sign' });
          return { success: false, message: '请阅读并同意用户协议', code, agreement: agreement || undefined };
        }
        return { success: false, message: typeof result.detail === 'string' ? result.detail : '登录失败', code, status: response.status };
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
      const resume = await loadRegistrationResume(server_config.BASE_URL);
      if (resume?.state === 'same_user_login' && resume.username === username) {
        await clearRegistrationResume(server_config.BASE_URL);
      }

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
    registrationRequestId?: string,
    agreementVersion?: string,
  ): Promise<AuthResult> => {
    try {
      if (!username.trim()) return { success: false, message: '用户名不能为空' };
      if (!password.trim()) return { success: false, message: '密码不能为空' };
      if (password !== confirmPassword) return { success: false, message: '两次密码不一致' };
      if (!inviteCode.trim()) return { success: false, message: '邀请码不能为空' };

      const existing = await loadRegistrationResume(server_config.BASE_URL);
      if (existing?.state === 'same_user_login') {
        return {
          success: false,
          code: 'LOGIN_CONFIRMATION_REQUIRED',
          message: '原注册结果无法核验，请先使用原账号登录确认；确认前不能创建新账号',
        };
      }

      // 加密密码
      const encrypted = await encryptPassword(password);
      if (!encrypted.ok) {
        addDebugTrace('auth', 'register: password encrypt failed', { reason: encrypted.reason });
        return { success: false, message: describeEncryptFailure('注册', encrypted.reason) };
      }

      // 发送注册请求
      const resumeKey = registrationRequestId ? `${server_config.BASE_URL}\u0000${registrationRequestId}` : '';
      const lockedIdentity = `${username}\u0000${password}\u0000${inviteCode}\u0000${agreementVersion || ''}`;
      if (resumeKey && registrationIdentityLock.current[resumeKey] && registrationIdentityLock.current[resumeKey] !== lockedIdentity) {
        return { success: false, message: '注册结果尚未确认，请先使用原用户名、密码和邀请码重试' };
      }
      if (resumeKey) registrationIdentityLock.current[resumeKey] = lockedIdentity;
      if (registrationRequestId && agreementVersion) {
        if (!existing || existing.requestId !== registrationRequestId) {
          await saveRegistrationResume({
            server: server_config.BASE_URL,
            requestId: registrationRequestId,
            username,
            agreementVersion,
            state: 'never_sent',
          });
        }
      }
      const response = await authFetch(`${server_config.BASE_URL}/auth/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          username,
          password: encrypted.encrypted,
          invite_code: inviteCode,
          ...(registrationRequestId ? { registration_request_id: registrationRequestId } : {}),
          ...(agreementVersion ? { agreement_version: agreementVersion, accepted: true } : {}),
        }),
      });
      let result: any;
      try {
        result = await response.json();
      } catch {
        if (registrationRequestId && agreementVersion) {
          await markRegistrationUnknown(server_config.BASE_URL, registrationRequestId, username, agreementVersion);
        }
        return { success: false, message: '注册结果未确认，请使用原信息重试' };
      }
      if (!response.ok) {
        if (isUnknownRegistrationResult(response.status)) {
          if (registrationRequestId && agreementVersion) {
            await markRegistrationUnknown(server_config.BASE_URL, registrationRequestId, username, agreementVersion);
          }
        }
        const code = result.code || result.detail?.code;
        if (code === 'AGREEMENT_CHANGED') {
          await clearRegistrationResume(server_config.BASE_URL);
          if (resumeKey) delete registrationIdentityLock.current[resumeKey];
        } else if (code === 'REGISTRATION_REQUEST_UNVERIFIABLE' && registrationRequestId && agreementVersion) {
          await markRegistrationSameUserLogin(server_config.BASE_URL, registrationRequestId, username, agreementVersion);
        }
        return { success: false, message: typeof result.detail === 'string' ? result.detail : '注册失败', code, agreement: code === 'AGREEMENT_CHANGED' ? await getCurrentAgreementForAuth() || undefined : undefined };
      }

      if (registrationRequestId && agreementVersion && result?.message) {
        await clearRegistrationResume(server_config.BASE_URL);
        if (resumeKey) delete registrationIdentityLock.current[resumeKey];
      }
      return { success: true, message: '注册成功，请登录' };
    } catch (e) {
      if (registrationRequestId && agreementVersion) {
        await markRegistrationUnknown(server_config.BASE_URL, registrationRequestId, username, agreementVersion);
      }
      addDebugTrace('auth', 'register error', { error: String(e) });
      return { success: false, message: '注册失败，请联系管理员' };
    }
  }, [getCurrentAgreementForAuth]);

  const acceptAgreement = useCallback(async (pending: PendingAgreement): Promise<AuthResult> => {
    try {
      if (pending.phase === 'login') {
        const resumed = pending.credential.kind === 'password'
          ? await login(pending.credential.username, pending.credential.password, Boolean(pending.credential.autoLogin))
          : await tryAutoLogin(pending.credential.username, pending.credential.token).then(success => ({ success, message: success ? '登录成功' : '登录失败', status: autoLoginLastStatus.current }));
        if (resumed.success) setPendingAgreement(null);
        if (resumed.status === 401) {
          dismissAgreement();
          if (pending.credential.kind === 'auto_login') await clearStoredAutoLoginCredentials();
        }
        return resumed;
      }
      let credential: AgreementCredential = pending.credential;
      if (pending.credential.kind === 'password') {
        const encrypted = await encryptPassword(pending.credential.password);
        if (!encrypted.ok) return { success: false, message: describeEncryptFailure('协议提交', encrypted.reason) };
        credential = { kind: 'password', username: pending.credential.username, password: encrypted.encrypted };
      }
      const response = await authFetch(`${server_config.BASE_URL}/auth/agreement/accept`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ agreement_version: pending.agreement.version, accepted: true, credential }),
      });
      const body: any = await response.json().catch(() => ({}));
      if (!response.ok) {
        const code = body.code || body.detail?.code;
        const failure = classifyAgreementSubmitFailure(response.status, code);
        if (failure === 'credential_invalid') {
          dismissAgreement();
          if (pending.credential.kind === 'auto_login') {
            await clearStoredAutoLoginCredentials();
          }
          return { success: false, message: '登录凭据已失效，请重新登录', code };
        }
        const agreement = failure === 'version_changed' ? await getCurrentAgreementForAuth() || undefined : undefined;
        if (agreement) setPendingAgreement({ ...pending, agreement, phase: 'sign' });
        return { success: false, message: typeof body.detail === 'string' ? body.detail : '协议提交失败，请重试', code, agreement };
      }
      const signedPending = { ...pending, phase: 'login' as const };
      setPendingAgreement(signedPending);
      const result = pending.credential.kind === 'password'
        ? await login(pending.credential.username, pending.credential.password, Boolean(pending.credential.autoLogin))
        : await tryAutoLogin(pending.credential.username, pending.credential.token).then(success => ({ success, message: success ? '登录成功' : '登录失败', status: autoLoginLastStatus.current }));
      if (result.success) setPendingAgreement(null);
      if (result.status === 401) {
        dismissAgreement();
        if (pending.credential.kind === 'auto_login') await clearStoredAutoLoginCredentials();
      }
      return result;
    } catch {
      return { success: false, message: '协议提交失败，请重试' };
    }
  }, [dismissAgreement, getCurrentAgreementForAuth, login, tryAutoLogin]);

  const logout = useCallback(async () => {
    try {
      // 清除公钥缓存，下次登录会重新从服务器获取
      const { clearCachedPublicKey } = await import('../utils/crypto');
      clearCachedPublicKey();
      await AsyncStorage.removeItem(AUTO_LOGIN_KEY);
      await AsyncStorage.removeItem(USERNAME_KEY);
      await SecureStore.deleteItemAsync(AUTOLOGIN_TOKEN_KEY);
      await AsyncStorage.removeItem(AUTOLOGIN_TOKEN_KEY);
      await voicePlaybackManager.clear();
      auth.username = '';
      auth.message_token = '';
      setAuthState(prev => ({ ...prev, isLoggedIn: false }));
    } catch (e) {
      addDebugTrace('auth', 'logout error', { error: String(e) });
    }
  }, [getCurrentAgreementForAuth]);

  return {
    ...authState,
    login,
    register,
    pendingAgreement,
    acceptAgreement,
    dismissAgreement,
    logout,
  };
}

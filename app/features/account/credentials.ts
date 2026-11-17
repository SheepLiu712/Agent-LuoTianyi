import AsyncStorage from '@react-native-async-storage/async-storage';
import * as SecureStore from 'expo-secure-store';
import { server_config } from '../../config';
import { clearCachedPublicKey, encryptPassword } from './crypto';

export interface AccountSession {
  readonly username: string;
  readonly token: string;
  readonly serverUrl: string;
}

export const AUTO_LOGIN_KEY = 'auto_login';
export const USERNAME_KEY = 'saved_username';
export const AUTOLOGIN_TOKEN_KEY = 'auto_login_token';

export async function clearSavedLogin() {
  await AsyncStorage.removeItem(AUTO_LOGIN_KEY);
  await AsyncStorage.removeItem(USERNAME_KEY);
  await SecureStore.deleteItemAsync(AUTOLOGIN_TOKEN_KEY);
  await AsyncStorage.removeItem(AUTOLOGIN_TOKEN_KEY);
}

export async function switchServer(url: string, verification?: { signal: AbortSignal; onCommit(): void }) {
  const response = await fetch(url + '/auth/public_key', { signal: verification?.signal });
  if (verification?.signal.aborted) return;
  if (!response.ok) throw new Error('服务器返回状态码 ' + response.status);
  verification?.onCommit();
  await clearSavedLogin();
  await AsyncStorage.setItem('custom_server_url', url);
  clearCachedPublicKey();
  server_config.BASE_URL = url;
}

export async function requestAccountReset(username: string, password: string, inviteCode: string) {
  const encrypted = await encryptPassword(password);
  if (!encrypted.ok) {
    if (encrypted.reason === 'network') throw new Error('无法获取加密密钥，请检查网络后重试');
    if (encrypted.reason === 'server') throw new Error('服务器返回异常，请稍后重试');
    throw new Error('密码加密失败');
  }
  const response = await fetch(server_config.BASE_URL + '/auth/reset_account', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ invite_code: inviteCode, new_username: username, new_password: encrypted.encrypted }),
  });
  if (!response.ok) throw new Error((await response.json()).detail || '未知错误');
}

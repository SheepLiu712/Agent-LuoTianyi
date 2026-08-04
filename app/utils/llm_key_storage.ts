/**
 * LLM API Key 安全存储封装。
 *
 * 与桌面 client 的 DPAPI 加密一致，APP 侧使用 expo-secure-store
 * （iOS Keychain / Android Keystore）保存，避免明文落在 AsyncStorage。
 */
import * as SecureStore from 'expo-secure-store';
import { LLM_API_KEY_STORAGE_KEY, VLM_API_KEY_STORAGE_KEY } from '../config';

export async function getLlmApiKey(): Promise<string | null> {
  return SecureStore.getItemAsync(LLM_API_KEY_STORAGE_KEY);
}

export async function setLlmApiKey(apiKey: string): Promise<void> {
  if (apiKey) {
    await SecureStore.setItemAsync(LLM_API_KEY_STORAGE_KEY, apiKey);
  } else {
    await SecureStore.deleteItemAsync(LLM_API_KEY_STORAGE_KEY);
  }
}

export async function getVlmApiKey(): Promise<string | null> {
  return SecureStore.getItemAsync(VLM_API_KEY_STORAGE_KEY);
}

export async function setVlmApiKey(apiKey: string): Promise<void> {
  if (apiKey) {
    await SecureStore.setItemAsync(VLM_API_KEY_STORAGE_KEY, apiKey);
  } else {
    await SecureStore.deleteItemAsync(VLM_API_KEY_STORAGE_KEY);
  }
}

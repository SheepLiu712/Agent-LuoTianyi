/**
 * LLM/VLM 配置安全存储封装。
 *
 * 每个模块的完整配置（apiKey/provider/model/baseUrl/params/开关）以单个 JSON
 * 存储在 expo-secure-store（iOS Keychain / Android Keystore）中，一次写入即
 * 原子生效，避免多键顺序写入产生撕裂配置；也避免明文落在 AsyncStorage。
 */
import * as SecureStore from 'expo-secure-store';
import {
  LLM_CONFIG_STORAGE_KEY,
  VLM_CONFIG_STORAGE_KEY,
} from '../config';

export interface LlmConfigSnapshot {
  apiKey: string;
  provider: string;
  model: string;
  baseUrl: string;
  paramsText: string;
  enableThinking: boolean;
  useJson: boolean;
}

async function readConfig(key: string): Promise<LlmConfigSnapshot | null> {
  const raw = await SecureStore.getItemAsync(key);
  if (!raw) {
    return null;
  }
  try {
    const parsed = JSON.parse(raw) as LlmConfigSnapshot;
    if (parsed && typeof parsed === 'object' && typeof parsed.apiKey === 'string') {
      return parsed;
    }
  } catch {
    // 忽略损坏的配置
  }
  return null;
}

export async function getLlmConfig(): Promise<LlmConfigSnapshot | null> {
  return readConfig(LLM_CONFIG_STORAGE_KEY);
}

export async function setLlmConfig(cfg: LlmConfigSnapshot): Promise<void> {
  await SecureStore.setItemAsync(LLM_CONFIG_STORAGE_KEY, JSON.stringify(cfg));
}

export async function clearLlmConfig(): Promise<void> {
  await SecureStore.deleteItemAsync(LLM_CONFIG_STORAGE_KEY);
}

export async function getVlmConfig(): Promise<LlmConfigSnapshot | null> {
  return readConfig(VLM_CONFIG_STORAGE_KEY);
}

export async function setVlmConfig(cfg: LlmConfigSnapshot): Promise<void> {
  await SecureStore.setItemAsync(VLM_CONFIG_STORAGE_KEY, JSON.stringify(cfg));
}

export async function clearVlmConfig(): Promise<void> {
  await SecureStore.deleteItemAsync(VLM_CONFIG_STORAGE_KEY);
}

/**
 * LLM 模块配置安全存储封装。
 *
 * 所有模块（按能力字段 key，如 llm_models / vlm_models）的完整配置以单个
 * JSON 存储在 expo-secure-store（iOS Keychain / Android Keystore）中，
 * 一次写入即原子生效，避免多键顺序写入产生撕裂配置；也避免明文落在
 * AsyncStorage。
 */
import * as SecureStore from 'expo-secure-store';

export const LLM_MODULES_CONFIG_STORAGE_KEY = 'llm_modules_config';

export interface LlmModuleConfig {
  enabled: boolean;
  provider: string;
  model: string;
  baseUrl: string;
  apiKey: string;
  paramsText: string;
}

export type LlmModulesConfig = Record<string, LlmModuleConfig>;

function sanitize(value: unknown): LlmModuleConfig {
  const raw = (value && typeof value === 'object' ? value : {}) as Partial<LlmModuleConfig>;
  return {
    enabled: Boolean(raw.enabled),
    provider: typeof raw.provider === 'string' ? raw.provider : '',
    model: typeof raw.model === 'string' ? raw.model : '',
    baseUrl: typeof raw.baseUrl === 'string' ? raw.baseUrl : '',
    apiKey: typeof raw.apiKey === 'string' ? raw.apiKey : '',
    paramsText: typeof raw.paramsText === 'string' ? raw.paramsText : '',
  };
}

export async function getLlmModulesConfig(): Promise<LlmModulesConfig> {
  const raw = await SecureStore.getItemAsync(LLM_MODULES_CONFIG_STORAGE_KEY);
  if (!raw) {
    return {};
  }
  try {
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed === 'object') {
      const result: LlmModulesConfig = {};
      for (const [key, value] of Object.entries(parsed as Record<string, unknown>)) {
        result[key] = sanitize(value);
      }
      return result;
    }
  } catch {
    // 忽略损坏的配置
  }
  return {};
}

export async function getModuleConfig(
  moduleKey: string,
): Promise<LlmModuleConfig | null> {
  const cfg = await getLlmModulesConfig();
  return cfg[moduleKey] ?? null;
}

export async function setLlmModulesConfig(cfg: LlmModulesConfig): Promise<void> {
  await SecureStore.setItemAsync(
    LLM_MODULES_CONFIG_STORAGE_KEY,
    JSON.stringify(cfg),
  );
}

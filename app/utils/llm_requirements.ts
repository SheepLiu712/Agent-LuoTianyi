import type { ClientModelType } from './llm_client';
import type { LlmModulesConfig } from './llm_key_storage';

export interface ModuleFormState {
  enabled: boolean;
  provider: string;
  baseUrl: string;
  model: string;
  apiKey: string;
  paramsText: string;
  supportsJson: boolean;
  supportsThinking: boolean;
}

export function emptyModuleForm(): ModuleFormState {
  return {
    enabled: false,
    provider: '',
    baseUrl: '',
    model: '',
    apiKey: '',
    paramsText: '',
    supportsJson: false,
    supportsThinking: false,
  };
}

export function validateLlmForms(
  types: ClientModelType[],
  forms: Record<string, ModuleFormState>,
): string | null {
  for (const requirement of types) {
    const form = forms[requirement.id];
    if (!form?.enabled) continue;
    const missing = [
      ['服务商名称', form.provider],
      ['Base URL', form.baseUrl],
      ['API Key', form.apiKey],
      ['模型名称', form.model],
    ].find(([, value]) => !value.trim());
    if (missing) return `类型「${requirement.name}」缺少 ${missing[0]}`;
    if (form.paramsText.trim()) {
      try {
        const parsed = JSON.parse(form.paramsText);
        if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
          return `类型「${requirement.name}」的高级参数必须是 JSON 对象`;
        }
      } catch {
        return `类型「${requirement.name}」的高级参数不是合法 JSON`;
      }
    }
  }
  return null;
}

export function buildLlmModulesConfig(
  types: ClientModelType[],
  forms: Record<string, ModuleFormState>,
): LlmModulesConfig {
  const config: LlmModulesConfig = {};
  for (const requirement of types) {
    const form = forms[requirement.id] ?? emptyModuleForm();
    config[requirement.id] = {
      enabled: form.enabled,
      provider: form.provider.trim(),
      baseUrl: form.baseUrl.trim().replace(/\/+$/, ''),
      model: form.model.trim(),
      apiKey: form.apiKey.trim(),
      paramsText: form.paramsText.trim(),
      modelKind: requirement.model_kind,
      modelCapabilities: {
        can_use_json: form.supportsJson,
        can_enable_thinking: form.supportsThinking,
      },
    };
  }
  return config;
}

export function validateClientModelRequirements(options: {
  requiredKind: string;
  configuredKind: string;
  requiresJson: boolean;
  requiresThinking: boolean;
  canUseJson: boolean;
  canEnableThinking: boolean;
}): string | null {
  const requiredKind = options.requiredKind.trim().toLowerCase();
  if (requiredKind !== 'llm' && requiredKind !== 'vlm') {
    return `服务端下发了未知模型类型：${requiredKind}`;
  }
  if (options.configuredKind !== requiredKind) {
    return `本地配置是 ${options.configuredKind || '未知'} 模型，当前调用要求 ${requiredKind.toUpperCase()} 模型`;
  }
  if (options.requiresJson && !options.canUseJson) {
    return '当前客户端模型未声明 JSON 输出能力';
  }
  if (options.requiresThinking && !options.canEnableThinking) {
    return '当前客户端模型未声明 thinking 能力';
  }
  return null;
}

export function validateJsonResponse(content: string, required: boolean): string | null {
  if (!required) return null;
  try {
    JSON.parse(content);
    return null;
  } catch {
    return '客户端模型未返回有效 JSON';
  }
}

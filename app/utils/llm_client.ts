/**
 * APP 侧 LLM 执行助手。
 * 服务端下发 llm_request 后，APP 使用用户自己的 api-key 直接调用
 * OpenAI 兼容的 chat/completions 接口，并把结果回传给服务端。
 */

interface LlmResult {
  content: string;
  usage: unknown;
}

export const CLIENT_JSON_UNSUPPORTED_MARKER = 'client_model_does_not_support_json';

export interface LlmProviderPreset {
  name: string;
  base_url: string;
  models: string[];
  vlm_models: string[];
}

export interface LlmModelCapability {
  can_enable_thinking: boolean;
  can_use_json: boolean;
}

export interface LlmProvidersResponse {
  providers: LlmProviderPreset[];
  llmModelCapabilities: Record<string, LlmModelCapability>;
  vlmModelCapabilities: Record<string, LlmModelCapability>;
}

let cachedProvidersResponse: LlmProvidersResponse | null = null;

export function getProviderPresets(): LlmProviderPreset[] {
  return cachedProvidersResponse?.providers ?? [];
}

export async function fetchProviderPresets(
  serverBaseUrl: string,
  timeoutMs = 15000,
): Promise<LlmProvidersResponse> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const resp = await fetch(`${serverBaseUrl.replace(/\/+$/, '')}/llm/providers`, {
      signal: controller.signal,
    });
    if (!resp.ok) {
      throw new Error(`HTTP ${resp.status}`);
    }
    const data = (await resp.json()) as Record<string, unknown>;
    const list = Array.isArray(data?.providers)
      ? (data.providers as LlmProviderPreset[]).filter(
          (p) => p && typeof p.name === 'string',
        )
      : [];
    const result: LlmProvidersResponse = {
      providers: list,
      llmModelCapabilities:
        (data.llm_model_capabilities as Record<string, LlmModelCapability>) ??
        {},
      vlmModelCapabilities:
        (data.vlm_model_capabilities as Record<string, LlmModelCapability>) ??
        {},
    };
    cachedProvidersResponse = result;
    return result;
  } finally {
    clearTimeout(timer);
  }
}

export async function ensureProviderPresets(
  serverBaseUrl: string,
): Promise<LlmProvidersResponse> {
  if (!cachedProvidersResponse) {
    return fetchProviderPresets(serverBaseUrl);
  }
  return cachedProvidersResponse;
}

export async function fetchJsonRequiredModules(
  serverBaseUrl: string,
  timeoutMs = 15000,
): Promise<{ llm: string[]; vlm: string[] }> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const resp = await fetch(`${serverBaseUrl.replace(/\/+$/, '')}/llm/providers`, {
      signal: controller.signal,
    });
    if (!resp.ok) {
      throw new Error(`HTTP ${resp.status}`);
    }
    const data = (await resp.json()) as {
      llm_json_required_modules?: unknown;
      vlm_json_required_modules?: unknown;
    };
    const toLabels = (value: unknown): string[] => {
      if (!Array.isArray(value)) {
        return [];
      }
      return value
        .map((item) => {
          if (item && typeof item === 'object') {
            const record = item as { label?: unknown; name?: unknown };
            return typeof record.label === 'string' && record.label
              ? record.label
              : typeof record.name === 'string'
                ? record.name
                : '';
          }
          return typeof item === 'string' ? item : '';
        })
        .filter((label) => label.length > 0);
    };
    return {
      llm: toLabels(data.llm_json_required_modules),
      vlm: toLabels(data.vlm_json_required_modules),
    };
  } finally {
    clearTimeout(timer);
  }
}

export function resolveProviderBaseUrl(
  providerName?: string | null,
  presets: LlmProviderPreset[] = cachedProvidersResponse?.providers ?? [],
): string {
  const name = providerName || '';
  for (const preset of presets) {
    if (preset.name === name) {
      return preset.base_url;
    }
  }
  return '';
}

export function resolveProviderModel(
  providerName?: string | null,
  presets: LlmProviderPreset[] = cachedProvidersResponse?.providers ?? [],
): string {
  // 返回默认文本模型（models 列表第一项）
  const name = providerName || '';
  for (const preset of presets) {
    if (preset.name === name) {
      return preset.models?.[0] ?? '';
    }
  }
  return '';
}

export function resolveProviderVlmModel(
  providerName?: string | null,
  presets: LlmProviderPreset[] = cachedProvidersResponse?.providers ?? [],
): string {
  // 返回默认图片理解模型（vlm_models 列表第一项）
  const name = providerName || '';
  for (const preset of presets) {
    if (preset.name === name) {
      return preset.vlm_models?.[0] ?? '';
    }
  }
  return '';
}

interface BuildPayloadOptions {
  prompt: string;
  model: string;
  params?: Record<string, unknown>;
  enableThinking?: boolean;
  useJson?: boolean;
  imageBase64?: string;
}

export function buildChatCompletionsPayload(options: BuildPayloadOptions): Record<string, unknown> {
  const {
    prompt,
    model,
    params = {},
    enableThinking = false,
    useJson = false,
    imageBase64,
  } = options;

  let messages: unknown[];
  if (imageBase64) {
    messages = [
      {
        role: 'user',
        content: [
          { type: 'text', text: prompt },
          { type: 'image_url', image_url: { url: imageBase64, detail: 'auto' } },
        ],
      },
    ];
  } else {
    messages = [{ role: 'system', content: prompt }];
  }

  const body: Record<string, unknown> = {
    model,
    messages,
    max_tokens: params.max_tokens ?? 4096,
    temperature: params.temperature ?? 0.7,
    top_p: params.top_p ?? 0.9,
  };
  // 其余用户参数全量透传（stop、presence_penalty 等），避免静默丢弃
  for (const [key, value] of Object.entries(params)) {
    if (!(key in body)) {
      body[key] = value;
    }
  }
  if (enableThinking) {
    body.enable_thinking = true;
  }
  if (useJson) {
    body.response_format = { type: 'json_object' };
  }
  return body;
}

interface CallProviderOptions {
  url: string;
  apiKey: string;
  body: Record<string, unknown>;
  timeoutMs?: number;
}

export async function callLlmProvider(options: CallProviderOptions): Promise<LlmResult> {
  const { url, apiKey, body, timeoutMs = 120000 } = options;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const resp = await fetch(url, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${apiKey}`,
        'Content-Type': 'application/json',
        Accept: 'application/json',
      },
      body: JSON.stringify(body),
      signal: controller.signal,
    });

    if (!resp.ok) {
      let detail = await resp.text();
      try {
        const data = (await resp.json()) as { error?: unknown };
        if (data && data.error !== undefined) {
          detail = JSON.stringify(data.error);
        }
      } catch {
        // 保留原始文本
      }
      throw new Error(`LLM provider returned HTTP ${resp.status}: ${detail}`);
    }

    const data = (await resp.json()) as {
      choices?: Array<{ message?: { content?: unknown } }>;
      usage?: unknown;
    };
    let content = '';
    if (data && Array.isArray(data.choices) && data.choices.length > 0) {
      const raw = data.choices[0]?.message?.content;
      content = typeof raw === 'string' ? raw : '';
    }
    return { content, usage: data?.usage ?? null };
  } finally {
    clearTimeout(timer);
  }
}

interface ProbeOptions {
  baseUrl: string;
  apiKey: string;
  model: string;
  flags?: { enableThinking?: boolean; useJson?: boolean };
  params?: Record<string, unknown>;
  timeoutMs?: number;
}

/**
 * 保存前探测：用所选模型/开关向服务商发一次最小请求，失败抛异常。
 * 仅验证文本链路（key/模型/开关），图片能力由服务端下发的 vlm_models 保证。
 */
export async function probeLlmConfig(options: ProbeOptions): Promise<void> {
  const {
    baseUrl,
    apiKey,
    model,
    flags = {},
    params = {},
    timeoutMs = 30000,
  } = options;
  const useJson = Boolean(flags.useJson);
  const probeParams: Record<string, unknown> = { ...params, max_tokens: 8, temperature: 0 };
  const body = buildChatCompletionsPayload({
    prompt: useJson ? '返回 JSON：{"ok": true}' : 'ping',
    model,
    params: probeParams,
    enableThinking: Boolean(flags.enableThinking),
    useJson,
  });
  await callLlmProvider({
    url: `${baseUrl.replace(/\/+$/, '')}/chat/completions`,
    apiKey,
    body,
    timeoutMs,
  });
}

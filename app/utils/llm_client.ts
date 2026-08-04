/**
 * APP 侧 LLM 执行助手。
 * 服务端下发 llm_request 后，APP 使用用户自己的 api-key 直接调用
 * OpenAI 兼容的 chat/completions 接口，并把结果回传给服务端。
 */

interface LlmResult {
  content: string;
  usage: unknown;
}

export interface LlmProviderPreset {
  name: string;
  base_url: string;
  model: string;
}

let cachedProviderPresets: LlmProviderPreset[] = [];

export function getProviderPresets(): LlmProviderPreset[] {
  return cachedProviderPresets;
}

export async function fetchProviderPresets(
  serverBaseUrl: string,
  timeoutMs = 15000,
): Promise<LlmProviderPreset[]> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const resp = await fetch(`${serverBaseUrl.replace(/\/+$/, '')}/llm/providers`, {
      signal: controller.signal,
    });
    if (!resp.ok) {
      throw new Error(`HTTP ${resp.status}`);
    }
    const data = (await resp.json()) as { providers?: unknown };
    const list = Array.isArray(data?.providers)
      ? (data.providers as LlmProviderPreset[]).filter(
          (p) => p && typeof p.name === 'string',
        )
      : [];
    cachedProviderPresets = list;
    return list;
  } finally {
    clearTimeout(timer);
  }
}

export async function ensureProviderPresets(
  serverBaseUrl: string,
): Promise<LlmProviderPreset[]> {
  if (cachedProviderPresets.length === 0) {
    return fetchProviderPresets(serverBaseUrl);
  }
  return cachedProviderPresets;
}

export function resolveProviderBaseUrl(
  providerName?: string | null,
  presets: LlmProviderPreset[] = cachedProviderPresets,
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
  presets: LlmProviderPreset[] = cachedProviderPresets,
): string {
  const name = providerName || '';
  for (const preset of presets) {
    if (preset.name === name) {
      return preset.model;
    }
  }
  return '';
}

export async function fetchProviderModels(
  baseUrl: string,
  apiKey: string,
  timeoutMs = 15000,
): Promise<string[]> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const resp = await fetch(`${baseUrl.replace(/\/+$/, '')}/models`, {
      headers: {
        Authorization: `Bearer ${apiKey}`,
        Accept: 'application/json',
      },
      signal: controller.signal,
    });
    if (!resp.ok) {
      throw new Error(`HTTP ${resp.status}`);
    }
    const data = (await resp.json()) as {
      data?: Array<{ id?: unknown }>;
    };
    const models: string[] = [];
    for (const item of data?.data ?? []) {
      if (typeof item?.id === 'string' && item.id) {
        models.push(item.id);
      }
    }
    return models;
  } finally {
    clearTimeout(timer);
  }
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

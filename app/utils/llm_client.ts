/**
 * APP 侧 LLM 执行助手。
 * 服务端下发 llm_request（按客户端模型类型）后，APP 使用用户自己的 api-key
 * 直接调用 OpenAI 兼容的 chat/completions 接口，并把结果回传给服务端。
 * 委托完全由 type 驱动，代码中不区分 llm/vlm。
 */

interface LlmResult {
  content: string;
  usage: unknown;
}

export interface ClientModelType {
  id: string;
  name: string;
  description: string;
  model_kind: 'llm' | 'vlm';
  requires_json: boolean;
  requires_thinking: boolean;
}

export interface ClientModelTypesResponse {
  types: ClientModelType[];
}

export async function fetchClientModelTypes(
  serverBaseUrl: string,
  timeoutMs = 15000,
): Promise<ClientModelTypesResponse> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const resp = await fetch(`${serverBaseUrl.replace(/\/+$/, '')}/llm/client-model-types`, {
      signal: controller.signal,
    });
    if (!resp.ok) {
      throw new Error(`HTTP ${resp.status}`);
    }
    const data = (await resp.json()) as Record<string, unknown>;
    const list = Array.isArray(data?.types)
      ? (data.types as ClientModelType[]).filter(
          (item) =>
            item &&
            typeof item.id === 'string' &&
            typeof item.name === 'string' &&
            (item.model_kind === 'llm' || item.model_kind === 'vlm'),
        )
      : [];
    return { types: list };
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

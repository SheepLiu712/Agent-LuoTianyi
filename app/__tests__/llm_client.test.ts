/**
 * APP 侧 LLM 客户端执行助手测试。
 */
import {
  buildChatCompletionsPayload,
  callLlmProvider,
  fetchJsonRequiredModules,
  fetchProviderPresets,
  probeLlmConfig,
  resolveProviderBaseUrl,
  resolveProviderModel,
  resolveProviderVlmModel,
} from '../utils/llm_client';
import type { LlmProviderPreset } from '../utils/llm_client';

const PRESETS: LlmProviderPreset[] = [
  {
    name: '阿里云百炼（DashScope）',
    base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    models: ['qwen3.5-plus', 'qwen3.6-flash'],
    vlm_models: ['qwen3-vl-plus'],
  },
  {
    name: 'DeepSeek',
    base_url: 'https://api.deepseek.com/v1',
    models: ['deepseek-v4-flash', 'deepseek-v4-pro'],
    vlm_models: [],
  },
];

describe('buildChatCompletionsPayload', () => {
  it('builds a text payload with params and flags', () => {
    const body = buildChatCompletionsPayload({
      prompt: '你是洛天依',
      model: 'test-model',
      params: { max_tokens: 1024, temperature: 0.3 },
      enableThinking: true,
      useJson: true,
    });
    expect(body.model).toBe('test-model');
    expect(body.messages).toEqual([{ role: 'system', content: '你是洛天依' }]);
    expect(body.max_tokens).toBe(1024);
    expect(body.temperature).toBe(0.3);
    expect(body.enable_thinking).toBe(true);
    expect(body.response_format).toEqual({ type: 'json_object' });
  });

  it('builds a multimodal payload for images', () => {
    const body = buildChatCompletionsPayload({
      prompt: '描述这张图',
      model: 'test-vlm',
      imageBase64: 'data:image/png;base64,AAA',
    });
    const content = (body.messages as Array<{ content: unknown[] }>)[0].content;
    expect((content[0] as { type: string }).type).toBe('text');
    expect((content[1] as { type: string }).type).toBe('image_url');
    expect(
      (content[1] as { image_url: { url: string } }).image_url.url,
    ).toBe('data:image/png;base64,AAA');
  });

  it('passes through extra params without dropping them', () => {
    const body = buildChatCompletionsPayload({
      prompt: 'hi',
      model: 'm',
      params: {
        max_tokens: 1024,
        stop: ['END'],
        presence_penalty: 0.5,
      },
    });
    expect(body.max_tokens).toBe(1024);
    expect(body.stop).toEqual(['END']);
    expect(body.presence_penalty).toBe(0.5);
  });
});

describe('resolveProviderBaseUrl', () => {
  it('resolves a preset name to its base url', () => {
    expect(resolveProviderBaseUrl('DeepSeek', PRESETS)).toBe('https://api.deepseek.com/v1');
  });

  it('returns empty string for unknown or empty names', () => {
    expect(resolveProviderBaseUrl(null, PRESETS)).toBe('');
    expect(resolveProviderBaseUrl('不存在的服务商', PRESETS)).toBe('');
  });
});

describe('resolveProviderModel', () => {
  it('resolves a preset name to its default model', () => {
    expect(resolveProviderModel('DeepSeek', PRESETS)).toBe('deepseek-v4-flash');
  });

  it('returns empty string for unknown or empty names', () => {
    expect(resolveProviderModel(null, PRESETS)).toBe('');
    expect(resolveProviderModel('不存在的服务商', PRESETS)).toBe('');
  });
});

describe('resolveProviderVlmModel', () => {
  it('resolves the default image model of a preset', () => {
    expect(resolveProviderVlmModel('阿里云百炼（DashScope）', PRESETS)).toBe('qwen3-vl-plus');
  });

  it('returns empty string when the provider has no image models', () => {
    expect(resolveProviderVlmModel('DeepSeek', PRESETS)).toBe('');
  });
});

describe('fetchProviderPresets', () => {
  it('fetches and caches provider presets from the server', async () => {
    const fetchMock = jest.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ providers: PRESETS }),
    } as unknown as Response);
    global.fetch = fetchMock as unknown as typeof fetch;

    const data = await fetchProviderPresets('https://server.example.com');
    expect(data.providers).toEqual(PRESETS);
    expect(data.llmModelCapabilities).toEqual({});
    expect(data.vlmModelCapabilities).toEqual({});
    const [url] = fetchMock.mock.calls[0] as [string];
    expect(url).toBe('https://server.example.com/llm/providers');
  });

  it('throws on http error', async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: false,
      status: 500,
      text: async () => 'error',
    } as unknown as Response) as unknown as typeof fetch;

    await expect(
      fetchProviderPresets('https://server.example.com'),
    ).rejects.toThrow('500');
  });
});

describe('fetchJsonRequiredModules', () => {
  it('returns llm and vlm modules that require json output', async () => {
    const fetchMock = jest.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        providers: [],
        llm_json_required_modules: [
          { name: 'topic_extractor', label: '话题抽取' },
          { name: 'memory_writer', label: '记忆写入' },
        ],
        vlm_json_required_modules: [],
      }),
    } as unknown as Response);
    global.fetch = fetchMock as unknown as typeof fetch;

    const result = await fetchJsonRequiredModules('https://server.example.com');
    expect(result.llm).toEqual(['话题抽取', '记忆写入']);
    expect(result.vlm).toEqual([]);
    const [url] = fetchMock.mock.calls[0] as [string];
    expect(url).toBe('https://server.example.com/llm/providers');
  });
});

describe('callLlmProvider', () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it('calls the provider with the bearer key and returns content', async () => {
    const fetchMock = jest.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        choices: [{ message: { content: 'hi' } }],
        usage: { total_tokens: 5 },
      }),
    } as unknown as Response);
    global.fetch = fetchMock as unknown as typeof fetch;

    const result = await callLlmProvider({
      url: 'https://example.com/v1/chat/completions',
      apiKey: 'sk-user',
      body: { model: 'm' },
    });

    expect(result.content).toBe('hi');
    expect(result.usage).toEqual({ total_tokens: 5 });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('https://example.com/v1/chat/completions');
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer sk-user');
  });

  it('throws on http error', async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: false,
      status: 401,
      text: async () => 'unauthorized',
      json: async () => ({ error: 'invalid key' }),
    } as unknown as Response) as unknown as typeof fetch;

    await expect(
      callLlmProvider({ url: 'https://example.com', apiKey: 'bad', body: {} }),
    ).rejects.toThrow('401');
  });
});

describe('probeLlmConfig', () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it('builds a probe request with flags and minimal params', async () => {
    const fetchMock = jest.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ choices: [{ message: { content: 'ok' } }], usage: null }),
    } as unknown as Response);
    global.fetch = fetchMock as unknown as typeof fetch;

    await probeLlmConfig({
      baseUrl: 'https://example.com/v1',
      apiKey: 'sk-user',
      model: 'test-model',
      flags: { enableThinking: true, useJson: true },
      params: { temperature: 0.9, max_tokens: 2048 },
      timeoutMs: 15000,
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('https://example.com/v1/chat/completions');
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer sk-user');
    const body = JSON.parse(String(init.body)) as Record<string, unknown>;
    expect(body.model).toBe('test-model');
    expect(body.max_tokens).toBe(8);
    expect(body.temperature).toBe(0);
    expect(body.enable_thinking).toBe(true);
    expect(body.response_format).toEqual({ type: 'json_object' });
    expect((body.messages as Array<{ content: string }>)[0].content).toContain('ok');
  });

  it('sends a plain ping when no flags are set', async () => {
    const fetchMock = jest.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ choices: [{ message: { content: 'ok' } }], usage: null }),
    } as unknown as Response);
    global.fetch = fetchMock as unknown as typeof fetch;

    await probeLlmConfig({
      baseUrl: 'https://example.com/v1',
      apiKey: 'sk-user',
      model: 'm',
      flags: { enableThinking: false, useJson: false },
    });

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('https://example.com/v1/chat/completions');
    const body = JSON.parse(String(init.body)) as Record<string, unknown>;
    expect((body.messages as Array<{ content: string }>)[0].content).toBe('ping');
    expect(body.enable_thinking).toBeUndefined();
    expect(body.response_format).toBeUndefined();
  });

  it('rejects when the provider returns an error', async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: false,
      status: 400,
      text: async () => 'unsupported switch',
      json: async () => ({ error: { message: 'unsupported switch' } }),
    } as unknown as Response) as unknown as typeof fetch;

    await expect(
      probeLlmConfig({
        baseUrl: 'https://example.com/v1',
        apiKey: 'sk',
        model: 'm',
        flags: { useJson: true },
      }),
    ).rejects.toThrow('400');
  });
});

/**
 * APP 侧 LLM 客户端执行助手测试。
 */
import {
  buildChatCompletionsPayload,
  callLlmProvider,
  fetchProviderModels,
  fetchProviderPresets,
  resolveProviderBaseUrl,
  resolveProviderModel,
} from '../utils/llm_client';
import type { LlmProviderPreset } from '../utils/llm_client';

const PRESETS: LlmProviderPreset[] = [
  {
    name: '阿里云百炼（DashScope）',
    base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    model: 'qwen3.5-plus',
  },
  {
    name: 'DeepSeek',
    base_url: 'https://api.deepseek.com/v1',
    model: 'deepseek-v4-flash',
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

describe('fetchProviderPresets', () => {
  it('fetches and caches provider presets from the server', async () => {
    const fetchMock = jest.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ providers: PRESETS }),
    } as unknown as Response);
    global.fetch = fetchMock as unknown as typeof fetch;

    const list = await fetchProviderPresets('https://server.example.com');
    expect(list).toEqual(PRESETS);
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

describe('fetchProviderModels', () => {
  it('fetches and parses model ids with the bearer key', async () => {
    const fetchMock = jest.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        object: 'list',
        data: [{ id: 'qwen3.5-plus' }, { id: 'deepseek-chat' }],
      }),
    } as unknown as Response);
    global.fetch = fetchMock as unknown as typeof fetch;

    const models = await fetchProviderModels(
      'https://dashscope.aliyuncs.com/compatible-mode/v1',
      'sk-test',
    );

    expect(models).toEqual(['qwen3.5-plus', 'deepseek-chat']);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('https://dashscope.aliyuncs.com/compatible-mode/v1/models');
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer sk-test');
  });

  it('throws on http error', async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: false,
      status: 401,
      text: async () => 'unauthorized',
    } as unknown as Response) as unknown as typeof fetch;

    await expect(
      fetchProviderModels('https://example.com/v1', 'bad'),
    ).rejects.toThrow('401');
  });
});

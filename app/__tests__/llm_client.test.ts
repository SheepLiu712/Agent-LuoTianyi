/**
 * APP 侧 LLM 客户端执行助手测试。
 */
import {
  buildChatCompletionsPayload,
  callLlmProvider,
  fetchClientModelTypes,
  fetchModelsList,
  probeLlmConfig,
} from '../utils/llm_client';
import type { ClientModelType } from '../utils/llm_client';

const TYPES: ClientModelType[] = [
  {
    type: '对话模型',
    description: '对话说明',
    providers: [
      {
        name: '阿里云百炼（DashScope）',
        base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
        models: [
          { id: 'qwen3.5-plus', can_enable_thinking: true, can_use_json: true },
          { id: 'qwen3.6-flash', can_enable_thinking: true, can_use_json: true },
          { id: 'qwen3-vl-plus', can_enable_thinking: false, can_use_json: false },
        ],
      },
    ],
  },
  {
    type: '图片理解模型',
    description: '图片说明',
    providers: [
      {
        name: 'DeepSeek',
        base_url: 'https://api.deepseek.com/v1',
        models: [
          { id: 'deepseek-v4-flash', can_enable_thinking: true, can_use_json: true },
          { id: 'deepseek-v4-pro', can_enable_thinking: true, can_use_json: true },
        ],
      },
    ],
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

describe('fetchClientModelTypes', () => {
  it('fetches client model types from the server', async () => {
    const fetchMock = jest.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ types: TYPES }),
    } as unknown as Response);
    global.fetch = fetchMock as unknown as typeof fetch;

    const data = await fetchClientModelTypes('https://server.example.com');
    expect(data.types).toEqual(TYPES);
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
      fetchClientModelTypes('https://server.example.com'),
    ).rejects.toThrow('500');
  });
});

describe('fetchModelsList', () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it('calls /models with the bearer key and returns model ids', async () => {
    const fetchMock = jest.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        data: [{ id: 'm1' }, { id: 'm2' }, {}],
      }),
    } as unknown as Response);
    global.fetch = fetchMock as unknown as typeof fetch;

    const ids = await fetchModelsList(
      'https://example.com/v1',
      'sk-user',
      5000,
    );
    expect(ids).toEqual(['m1', 'm2']);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('https://example.com/v1/models');
    expect((init.headers as Record<string, string>).Authorization).toBe(
      'Bearer sk-user',
    );
  });

  it('throws on http error', async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: false,
      status: 401,
      text: async () => 'unauthorized',
      json: async () => ({}),
    } as unknown as Response) as unknown as typeof fetch;

    await expect(
      fetchModelsList('https://example.com/v1', 'bad'),
    ).rejects.toThrow('401');
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

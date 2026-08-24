/**
 * APP 侧 LLM 客户端执行助手测试。
 */
import {
  buildChatCompletionsPayload,
  callLlmProvider,
  fetchClientModelTypes,
} from '../utils/llm_client';
import type { ClientModelType } from '../utils/llm_client';

const TYPES: ClientModelType[] = [
  {
    id: 'main_chat',
    name: '主对话模型',
    description: '对话说明',
    model_kind: 'llm',
    requires_json: false,
    requires_thinking: false,
  },
  {
    id: 'image_understanding',
    name: '图片理解模型',
    description: '图片说明',
    model_kind: 'vlm',
    requires_json: false,
    requires_thinking: false,
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
    expect(url).toBe('https://server.example.com/llm/client-model-types');
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

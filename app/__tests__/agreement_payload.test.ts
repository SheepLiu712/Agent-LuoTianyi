import { fetchCurrentAgreement } from '../hooks/useAuth';
import { parseAgreementPayload } from '../utils/agreement';

jest.mock('@react-native-async-storage/async-storage', () => ({
  __esModule: true,
  default: {
    getItem: jest.fn().mockResolvedValue(null),
    setItem: jest.fn().mockResolvedValue(undefined),
    removeItem: jest.fn().mockResolvedValue(undefined),
  },
}));

jest.mock('../utils/voice_playback_manager', () => ({
  voicePlaybackManager: {},
}));

const VALID_PAYLOAD = {
  version: 'terms-2026-10-v2',
  title: '用户协议',
  format: 'agreement.richtext.v1',
  blocks: [
    {
      font_size: 16,
      align: 'justify',
      runs: [{ text: '甲  乙\n丙', bold: true }],
    },
  ],
};

const mockFetch = jest.fn();
globalThis.fetch = mockFetch as unknown as typeof fetch;

function jsonResponse(body: unknown, ok = true, status = 200): Response {
  return {
    ok,
    status,
    json: async () => body,
  } as unknown as Response;
}

describe('协议响应校验', () => {
  beforeEach(() => {
    mockFetch.mockReset();
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  it('接受合法 payload 并保留空格、换行和粗体', () => {
    expect(parseAgreementPayload(VALID_PAYLOAD)).toEqual(VALID_PAYLOAD);
  });

  it.each([
    'not-an-object',
    [],
    { ...VALID_PAYLOAD, extra: true },
    { ...VALID_PAYLOAD, format: 'blocks-v1' },
    { ...VALID_PAYLOAD, blocks: [{ font_size: 16, align: 'left', runs: [{ text: '正文' }] }] },
    { ...VALID_PAYLOAD, blocks: [{ font_size: 33, align: 'justify', runs: [{ text: '正文' }] }] },
    { ...VALID_PAYLOAD, blocks: [{ font_size: 16, align: 'justify', runs: [] }] },
    {
      ...VALID_PAYLOAD,
      blocks: [{ font_size: 16, align: 'justify', runs: [{ text: '正文', bold: 'yes' }] }],
    },
  ])('拒绝畸形 payload %#', (payload) => {
    expect(parseAgreementPayload(payload)).toBeNull();
  });

  it('HTTP 200 畸形 JSON 返回统一失败而不是成功数据', async () => {
    mockFetch.mockResolvedValue(jsonResponse(['invalid']));

    await expect(fetchCurrentAgreement()).resolves.toEqual({
      success: false,
      message: '用户协议加载失败，请重试',
    });
  });

  it('HTTP 200 合法 JSON 返回已校验协议', async () => {
    mockFetch.mockResolvedValue(jsonResponse(VALID_PAYLOAD));

    await expect(fetchCurrentAgreement()).resolves.toEqual({ success: true, data: VALID_PAYLOAD });
  });

  it('超过有限超时时间会取消请求并返回可重试失败', async () => {
    jest.useFakeTimers();
    let requestSignal!: AbortSignal;
    mockFetch.mockImplementation((_url, init) => {
      requestSignal = init?.signal as AbortSignal;
      return new Promise((_resolve, reject) => {
        requestSignal.addEventListener('abort', () => reject(new Error('aborted')), { once: true });
      });
    });

    const result = fetchCurrentAgreement({ timeoutMs: 25 });
    await jest.advanceTimersByTimeAsync(25);

    await expect(result).resolves.toEqual({
      success: false,
      message: '用户协议加载失败，请重试',
    });
    expect(requestSignal.aborted).toBe(true);
  });

  it('调用方取消会传递到底层请求', async () => {
    const caller = new AbortController();
    let requestSignal!: AbortSignal;
    mockFetch.mockImplementation((_url, init) => {
      requestSignal = init?.signal as AbortSignal;
      return new Promise((_resolve, reject) => {
        requestSignal.addEventListener('abort', () => reject(new Error('aborted')), { once: true });
      });
    });

    const result = fetchCurrentAgreement({ signal: caller.signal, timeoutMs: 1000 });
    caller.abort();

    await expect(result).resolves.toEqual({
      success: false,
      message: '用户协议加载失败，请重试',
    });
    expect(requestSignal.aborted).toBe(true);
  });
});

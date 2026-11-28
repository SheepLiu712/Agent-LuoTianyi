import { authFetch, isUnknownRegistrationResult } from '../utils/auth_request';

describe('认证请求超时和注册结果分类', () => {
  const originalFetch = global.fetch;

  afterEach(() => {
    global.fetch = originalFetch;
    jest.useRealTimers();
  });

  it('超时、429 与 5xx 都保留原请求 ID 以确认注册结果', () => {
    expect(isUnknownRegistrationResult(undefined)).toBe(true);
    expect(isUnknownRegistrationResult(429)).toBe(true);
    expect(isUnknownRegistrationResult(500)).toBe(true);
    expect(isUnknownRegistrationResult(400)).toBe(false);
    expect(isUnknownRegistrationResult(409)).toBe(false);
  });

  it('为认证 fetch 传入可中止信号', async () => {
    global.fetch = jest.fn().mockResolvedValue(new Response('{}', { status: 200 }));

    await authFetch('https://example.test/auth/login');

    expect(global.fetch).toHaveBeenCalledWith('https://example.test/auth/login', expect.objectContaining({ signal: expect.any(AbortSignal) }));
  });

  it('到达配置超时时中止在途认证请求', async () => {
    jest.useFakeTimers();
    let signal!: AbortSignal;
    global.fetch = jest.fn((_url: RequestInfo | URL, init?: RequestInit) => {
      signal = (init as RequestInit).signal!;
      return new Promise<Response>(() => {});
    }) as typeof fetch;

    const request = authFetch('https://example.test/auth/register');
    jest.advanceTimersByTime(10_000);

    expect(signal.aborted).toBe(true);
    await expect(Promise.race([request, Promise.resolve('timeout')])).resolves.toBe('timeout');
  });
});

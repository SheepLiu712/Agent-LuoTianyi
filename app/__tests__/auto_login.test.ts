/**
 * auto_login.ts 单元测试
 * 覆盖自动登录结果分类与带退避的重试策略（Bug#2）。
 */
import {
  AUTO_LOGIN_MAX_ATTEMPTS,
  classifyAutoLoginStatus,
  runAutoLoginWithRetry,
} from '../utils/auto_login';

describe('classifyAutoLoginStatus', () => {
  it('2xx 视为成功', () => {
    expect(classifyAutoLoginStatus(200)).toBe('ok');
    expect(classifyAutoLoginStatus(204)).toBe('ok');
  });

  it('401/403 视为 token 被明确拒绝', () => {
    expect(classifyAutoLoginStatus(401)).toBe('invalid');
    expect(classifyAutoLoginStatus(403)).toBe('invalid');
  });

  it('5xx/429 视为瞬时故障', () => {
    expect(classifyAutoLoginStatus(500)).toBe('transient');
    expect(classifyAutoLoginStatus(503)).toBe('transient');
    expect(classifyAutoLoginStatus(429)).toBe('transient');
  });

  it('网络错误（null）视为瞬时故障', () => {
    expect(classifyAutoLoginStatus(null)).toBe('transient');
  });
});

describe('runAutoLoginWithRetry', () => {
  it('首次成功立即返回，不再尝试', async () => {
    const attempt = jest.fn().mockResolvedValue('ok');
    const delayFn = jest.fn().mockResolvedValue(undefined);

    const outcome = await runAutoLoginWithRetry(attempt, { delayFn });
    expect(outcome).toBe('ok');
    expect(attempt).toHaveBeenCalledTimes(1);
    expect(delayFn).not.toHaveBeenCalled();
  });

  it('token 被拒绝（invalid）立即返回，不重试', async () => {
    const attempt = jest.fn().mockResolvedValue('invalid');
    const delayFn = jest.fn().mockResolvedValue(undefined);

    const outcome = await runAutoLoginWithRetry(attempt, { delayFn });
    expect(outcome).toBe('invalid');
    expect(attempt).toHaveBeenCalledTimes(1);
    expect(delayFn).not.toHaveBeenCalled();
  });

  it('瞬时故障按指数退避重试，随后成功', async () => {
    const attempt = jest.fn()
      .mockResolvedValueOnce('transient')
      .mockResolvedValueOnce('transient')
      .mockResolvedValueOnce('ok');
    const delayFn = jest.fn().mockResolvedValue(undefined);

    const outcome = await runAutoLoginWithRetry(attempt, { retryBaseMs: 100, delayFn });
    expect(outcome).toBe('ok');
    expect(attempt).toHaveBeenCalledTimes(3);
    expect(delayFn.mock.calls).toEqual([[100], [200]]);
  });

  it('持续瞬时故障时重试达到最大次数后放弃', async () => {
    const attempt = jest.fn().mockResolvedValue('transient');
    const delayFn = jest.fn().mockResolvedValue(undefined);

    const outcome = await runAutoLoginWithRetry(attempt, {
      maxAttempts: AUTO_LOGIN_MAX_ATTEMPTS,
      retryBaseMs: 100,
      delayFn,
    });
    expect(outcome).toBe('transient');
    expect(attempt).toHaveBeenCalledTimes(AUTO_LOGIN_MAX_ATTEMPTS);
    expect(delayFn).toHaveBeenCalledTimes(AUTO_LOGIN_MAX_ATTEMPTS - 1);
  });
});

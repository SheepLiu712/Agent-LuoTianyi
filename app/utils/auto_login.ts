/**
 * 自动登录相关工具：结果分类与带退避的重试策略（可独立单元测试）
 */

export const AUTO_LOGIN_MAX_ATTEMPTS = 3;
/** 自动登录重试退避基数（毫秒） */
export const AUTO_LOGIN_RETRY_BASE_MS = 1000;

/** 单次自动登录尝试的结果：ok=成功，invalid=token 被明确拒绝，transient=瞬时故障（可重试） */
export type AutoLoginAttemptOutcome = 'ok' | 'invalid' | 'transient';

/**
 * 根据 HTTP 状态码判断自动登录结果；status=null 表示网络错误。
 * - 2xx：成功
 * - 401/403：token 被明确拒绝（如已在其他设备登录），需要用户重新登录
 * - 其余（5xx/429/网络错误）：瞬时故障，可退避重试
 */
export function classifyAutoLoginStatus(status: number | null): AutoLoginAttemptOutcome {
  if (status === null) return 'transient';
  if (status >= 200 && status < 300) return 'ok';
  if (status === 401 || status === 403) return 'invalid';
  return 'transient';
}

function defaultDelay(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}

export interface AutoLoginRetryOptions {
  maxAttempts?: number;
  retryBaseMs?: number;
  /** 可注入的延时函数（测试用） */
  delayFn?: (ms: number) => Promise<void>;
}

/**
 * 带退避重试地执行自动登录尝试：
 * - 成功或 token 被明确拒绝（invalid）立即返回，不重试；
 * - 瞬时故障（网络错误/5xx/429）按指数退避重试，最多 maxAttempts 次。
 */
export async function runAutoLoginWithRetry(
  attempt: (attemptNumber: number) => Promise<AutoLoginAttemptOutcome>,
  options: AutoLoginRetryOptions = {},
): Promise<AutoLoginAttemptOutcome> {
  const {
    maxAttempts = AUTO_LOGIN_MAX_ATTEMPTS,
    retryBaseMs = AUTO_LOGIN_RETRY_BASE_MS,
    delayFn = defaultDelay,
  } = options;

  let lastOutcome: AutoLoginAttemptOutcome = 'transient';
  for (let i = 1; i <= maxAttempts; i++) {
    const outcome = await attempt(i);
    if (outcome !== 'transient') return outcome;
    lastOutcome = outcome;
    if (i < maxAttempts) {
      await delayFn(retryBaseMs * 2 ** (i - 1));
    }
  }
  return lastOutcome;
}

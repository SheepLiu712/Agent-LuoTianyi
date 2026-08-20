import forge from 'node-forge';
import { server_config } from '../config';
import { addDebugTrace } from './debug_trace';

// 缓存公钥对象（forge 格式）
let cachedForgeKey: forge.pki.rsa.PublicKey | null = null;

// 公钥获取失败的类型：network = 网络错误/超时，server = 服务器返回异常或数据无效
export type PublicKeyFailureReason = 'network' | 'server';

/** 公钥获取最多尝试次数 */
const PUBLIC_KEY_MAX_ATTEMPTS = 3;
/** 两次尝试之间的退避间隔（毫秒） */
const PUBLIC_KEY_RETRY_DELAY_MS = 800;

type PublicKeyFetchOutcome =
  | { ok: true; publicKey: forge.pki.rsa.PublicKey }
  | { ok: false; reason: PublicKeyFailureReason };

function delay(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}

/**
 * 带超时的 fetch，避免网络波动时请求无限挂起
 */
async function fetchWithTimeout(url: string, timeoutMs: number): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}

/**
 * 获取并解析公钥，失败时自动重试。
 * 网络错误（fetch 抛异常、超时）与 HTTP 非 2xx 均视为可重试的临时故障；
 * 全部重试失败后返回失败原因，供上层给出明确提示。
 */
async function fetchPublicKeyWithRetry(): Promise<PublicKeyFetchOutcome> {
  let lastFailure: PublicKeyFailureReason = 'network';
  for (let attempt = 1; attempt <= PUBLIC_KEY_MAX_ATTEMPTS; attempt++) {
    try {
      const response = await fetchWithTimeout(
        `${server_config.BASE_URL}/auth/public_key`,
        server_config.API_TIMEOUT,
      );
      if (!response.ok) {
        addDebugTrace('crypto', 'public key http error', { status: response.status, attempt });
        lastFailure = 'server';
      } else {
        const data = await response.json();
        const pem = data?.public_key;
        if (typeof pem !== 'string' || pem.length === 0) {
          addDebugTrace('crypto', 'public key payload invalid', { attempt });
          lastFailure = 'server';
        } else {
          const publicKey = forge.pki.publicKeyFromPem(pem);
          return { ok: true, publicKey };
        }
      }
    } catch (error) {
      addDebugTrace('crypto', 'public key fetch failed', { error: String(error), attempt });
      lastFailure = 'network';
    }
    if (attempt < PUBLIC_KEY_MAX_ATTEMPTS) {
      await delay(PUBLIC_KEY_RETRY_DELAY_MS);
    }
  }
  return { ok: false, reason: lastFailure };
}

/**
 * 获取并转换公钥（失败时自动重试，全部失败返回 null）
 */
export async function getPublicKey(): Promise<forge.pki.rsa.PublicKey | null> {
  if (cachedForgeKey) return cachedForgeKey;

  const outcome = await fetchPublicKeyWithRetry();
  if (outcome.ok) {
    cachedForgeKey = outcome.publicKey;
    return outcome.publicKey;
  }
  return null;
}

export type EncryptPasswordResult =
  | { ok: true; encrypted: string }
  | { ok: false; reason: PublicKeyFailureReason | 'crypto' };

/**
 * 核心加密函数：对接 Python 后端的 RSA-OAEP + SHA-256
 * 公钥获取失败时自动重试；返回结构化结果以便上层区分失败原因并给出明确提示。
 */
export async function encryptPassword(password: string): Promise<EncryptPasswordResult> {
  // 优先使用已缓存的公钥，未缓存时才发起网络请求
  let publicKey = cachedForgeKey;
  if (!publicKey) {
    const outcome = await fetchPublicKeyWithRetry();
    if (!outcome.ok) {
      addDebugTrace('crypto', 'encrypt failed: public key unavailable', { reason: outcome.reason });
      return { ok: false, reason: outcome.reason };
    }
    publicKey = outcome.publicKey;
    cachedForgeKey = publicKey;
  }

  try {
    // 1. 将字符串转为 UTF-8 字节编码
    const bytes = forge.util.encodeUtf8(password);

    // 2. 执行 RSA-OAEP 加密
    // 注意：这里的配置必须严格匹配 Python 的 padding.OAEP
    const encrypted = publicKey.encrypt(bytes, 'RSA-OAEP', {
      md: forge.md.sha256.create(),      // 主哈希使用 SHA-256
      mgf1: {
        md: forge.md.sha256.create()    // MGF1 也必须使用 SHA-256
      }
    });

    // 3. 将加密后的二进制转为 Base64 字符串
    return { ok: true, encrypted: forge.util.encode64(encrypted) };
  } catch (error) {
    addDebugTrace('crypto', 'encrypt failed', { error: String(error) });
    return { ok: false, reason: 'crypto' };
  }
}

/** 清除缓存的公钥，服务器地址变更后需要调用 */
export function clearCachedPublicKey(): void {
  cachedForgeKey = null;
}

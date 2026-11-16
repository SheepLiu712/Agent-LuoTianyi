/**
 * crypto.ts 单元测试
 * 覆盖公钥获取的重试、超时、缓存，以及密码加密失败原因区分（Bug#1）。
 */
import forge from 'node-forge';
import { clearCachedPublicKey, encryptPassword, getPublicKey } from '../utils/crypto';
import { server_config } from '../config';

jest.mock('@react-native-async-storage/async-storage', () => ({
  __esModule: true,
  default: {
    getItem: jest.fn().mockResolvedValue(null),
    setItem: jest.fn().mockResolvedValue(undefined),
    removeItem: jest.fn().mockResolvedValue(undefined),
  },
}));

// 生成一个真实可用的 RSA 公钥 PEM（测试专用，非敏感信息）
const { publicKey: testKeyPair } = forge.pki.rsa.generateKeyPair(1024);
const TEST_PUBLIC_KEY_PEM = forge.pki.publicKeyToPem(testKeyPair);

const mockFetch = jest.fn();
globalThis.fetch = mockFetch as unknown as typeof fetch;

function jsonResponse(body: unknown, ok = true, status = 200): Response {
  return {
    ok,
    status,
    json: async () => body,
  } as unknown as Response;
}

const PUBLIC_KEY_URL = `${server_config.BASE_URL}/auth/public_key`;

describe('getPublicKey', () => {
  beforeEach(() => {
    mockFetch.mockReset();
    clearCachedPublicKey();
  });

  it('获取成功时返回公钥并缓存（第二次调用不再请求网络）', async () => {
    mockFetch.mockResolvedValue(jsonResponse({ public_key: TEST_PUBLIC_KEY_PEM }));

    const key1 = await getPublicKey();
    expect(key1).not.toBeNull();
    expect(mockFetch).toHaveBeenCalledTimes(1);

    const key2 = await getPublicKey();
    expect(key2).toBe(key1);
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  it('网络波动时自动重试，最终成功返回公钥', async () => {
    mockFetch
      .mockRejectedValueOnce(new TypeError('Network request failed'))
      .mockRejectedValueOnce(new TypeError('Network request failed'))
      .mockResolvedValueOnce(jsonResponse({ public_key: TEST_PUBLIC_KEY_PEM }));

    const key = await getPublicKey();
    expect(key).not.toBeNull();
    expect(mockFetch).toHaveBeenCalledTimes(3);
  });

  it('网络持续失败时返回 null，且重试达到最大次数', async () => {
    mockFetch.mockRejectedValue(new TypeError('Network request failed'));

    const key = await getPublicKey();
    expect(key).toBeNull();
    expect(mockFetch).toHaveBeenCalledTimes(3);
  });

  it('HTTP 非 2xx 时重试后返回 null', async () => {
    mockFetch.mockResolvedValue(jsonResponse({ detail: 'error' }, false, 500));

    const key = await getPublicKey();
    expect(key).toBeNull();
    expect(mockFetch).toHaveBeenCalledTimes(3);
  });

  it('返回数据缺少 public_key 字段时重试后返回 null', async () => {
    mockFetch.mockResolvedValue(jsonResponse({ foo: 'bar' }));

    const key = await getPublicKey();
    expect(key).toBeNull();
    expect(mockFetch).toHaveBeenCalledTimes(3);
  });

  it('请求带有超时信号（AbortController）', async () => {
    mockFetch.mockResolvedValue(jsonResponse({ public_key: TEST_PUBLIC_KEY_PEM }));

    await getPublicKey();
    const [, init] = mockFetch.mock.calls[0];
    expect(init).toHaveProperty('signal');
    expect(init.signal.aborted).toBe(false);
  });
});

describe('encryptPassword', () => {
  beforeEach(() => {
    mockFetch.mockReset();
    clearCachedPublicKey();
  });

  it('公钥获取成功时返回加密后的 Base64 字符串', async () => {
    mockFetch.mockResolvedValue(jsonResponse({ public_key: TEST_PUBLIC_KEY_PEM }));

    const result = await encryptPassword('secret123');
    expect(result.ok).toBe(true);
    if (result.ok) {
      // Base64 编码的非空字符串
      expect(typeof result.encrypted).toBe('string');
      expect(result.encrypted.length).toBeGreaterThan(0);
    }
  });

  it('公钥获取失败（网络）时返回原因 network，不抛出异常', async () => {
    mockFetch.mockRejectedValue(new TypeError('Network request failed'));

    const result = await encryptPassword('secret123');
    expect(result).toEqual({ ok: false, reason: 'network' });
    expect(mockFetch).toHaveBeenCalledTimes(3);
  });

  it('公钥获取失败（服务器异常）时返回原因 server', async () => {
    mockFetch.mockResolvedValue(jsonResponse({ detail: 'error' }, false, 500));

    const result = await encryptPassword('secret123');
    expect(result).toEqual({ ok: false, reason: 'server' });
  });

  it('服务重启后用新公钥加密，当前服务可以解密密码', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ public_key: TEST_PUBLIC_KEY_PEM }));
    await getPublicKey();
    const current = forge.pki.rsa.generateKeyPair(1024);
    mockFetch.mockResolvedValue(jsonResponse({ public_key: forge.pki.publicKeyToPem(current.publicKey) }));

    const result = await encryptPassword('secret456');
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(current.privateKey.decrypt(forge.util.decode64(result.encrypted), 'RSA-OAEP', {
        md: forge.md.sha256.create(), mgf1: { md: forge.md.sha256.create() },
      })).toBe('secret456');
    }
  });

  it('旧公钥仍在缓存但无法取得当前公钥时不发送旧密钥密文', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ public_key: TEST_PUBLIC_KEY_PEM }));
    await getPublicKey();
    mockFetch.mockResolvedValue(jsonResponse({}, false, 503));
    expect(await encryptPassword('secret456')).toEqual({ ok: false, reason: 'server' });
  });
});

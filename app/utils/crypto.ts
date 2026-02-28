import forge from 'node-forge';
import { server_config } from '../config';

// 缓存公钥对象（forge 格式）
let cachedForgeKey: forge.pki.rsa.PublicKey | null = null;

/**
 * 获取并转换公钥
 */
export async function getPublicKey(): Promise<forge.pki.rsa.PublicKey | null> {
  if (cachedForgeKey) return cachedForgeKey;

  try {
    const response = await fetch(`${server_config.BASE_URL}/auth/public_key`);
    const data = await response.json();
    const pem = data.public_key;

    // 使用 forge 直接从 PEM 字符串导入
    cachedForgeKey = forge.pki.publicKeyFromPem(pem);
    return cachedForgeKey;
  } catch (error) {
    console.error('获取公钥失败:', error);
    return null;
  }
}

/**
 * 核心加密函数：对接 Python 后端的 RSA-OAEP + SHA-256
 */
export async function encryptPassword(
  password: string,
): Promise<string | null> {
  try {
    const publicKey = await getPublicKey();
    if (!publicKey) return null;

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
    return forge.util.encode64(encrypted);
  } catch (error) {
    console.error('Forge 加密失败:', error);
    return null;
  }
}
import forge from 'node-forge';

/**
 * 生成 RFC 4122 v4 UUID。
 *
 * 服务端 `user_voice` 协议对 `upload_id` 强制执行 `UUID(value)` 校验
 * （`server/src/adapter/websocket/voice_upload.py`），因此协议 id 不能沿用
 * `recording-<时间戳>-<随机>` 这类本地展示 id。
 */
export function randomUuid(): string {
  const bytes = forge.random.getBytesSync(16);
  let hex = '';
  for (let index = 0; index < 16; index += 1) {
    hex += bytes.charCodeAt(index).toString(16).padStart(2, '0');
  }
  const version = `4${hex.slice(13, 16)}`;
  const variant = ((parseInt(hex[16], 16) & 0x3) | 0x8).toString(16);
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${version}-${variant}${hex.slice(17, 20)}-${hex.slice(20, 32)}`;
}

/** 判断字符串是否为规范 UUID（与服务端值域契约一致）。 */
export function isUuid(value: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);
}

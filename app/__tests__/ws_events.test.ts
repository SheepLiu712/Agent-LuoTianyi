/**
 * WSEventType 常量测试
 * 验证常量值与服务端 Python enum 一致，且没有重复值。
 */
import { WSEventType } from '../types/ws_events';

describe('WSEventType constants', () => {
  it('should have all required keys', () => {
    // 服务端 WSEventType 包含的键
    const expectedKeys = [
      'SYSTEM_READY',
      'AUTH_SUCCESS',
      'AUTH_FAILURE',
      'SERVER_ERROR',
      'SERVER_ACK',
      'AUTH_ERROR',
      'AUTH_OK',
      'AGENT_STATE_CHANGED',
      'AGENT_MESSAGE',
      'USER_MESSAGE',
      'USER_IMAGE',
      'USER_TEXT',
      'USER_TYPING',
      'USER_AUTH',
      'USER_TOUCH',
      'USER_PREFERENCE_SYNC',
      'HB_PING',
      'HB_PONG',
      'DATE_DETECTED',
    ];

    for (const key of expectedKeys) {
      expect(WSEventType).toHaveProperty(key);
    }
  });

  it('should have correct values matching server enum', () => {
    expect(WSEventType.SYSTEM_READY).toBe('system_ready');
    expect(WSEventType.AUTH_OK).toBe('auth_ok');
    expect(WSEventType.AUTH_ERROR).toBe('auth_error');
    expect(WSEventType.SERVER_ACK).toBe('server_ack');
    expect(WSEventType.SERVER_ERROR).toBe('error');
    expect(WSEventType.AGENT_STATE_CHANGED).toBe('agent_state_changed');
    expect(WSEventType.AGENT_MESSAGE).toBe('agent_message');
    expect(WSEventType.USER_TEXT).toBe('user_text');
    expect(WSEventType.USER_IMAGE).toBe('user_image');
    expect(WSEventType.USER_TYPING).toBe('user_typing');
    expect(WSEventType.USER_AUTH).toBe('user_auth');
    expect(WSEventType.USER_TOUCH).toBe('user_touch');
    expect(WSEventType.USER_PREFERENCE_SYNC).toBe('user_preference_sync');
    expect(WSEventType.HB_PING).toBe('hb_ping');
    expect(WSEventType.HB_PONG).toBe('hb_pong');
  });

  it('should have no duplicate values', () => {
    const values = Object.values(WSEventType);
    const uniqueValues = new Set(values);
    expect(uniqueValues.size).toBe(values.length);
  });

  it('should have no duplicate keys (by definition, but worth checking)', () => {
    const keys = Object.keys(WSEventType);
    const uniqueKeys = new Set(keys);
    expect(uniqueKeys.size).toBe(keys.length);
  });
});

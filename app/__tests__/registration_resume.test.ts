import AsyncStorage from '@react-native-async-storage/async-storage';
import {
  clearRegistrationResume,
  isRecoverable,
  loadRegistrationResume,
  markRegistrationSameUserLogin,
  markRegistrationUnknown,
  normalizeRegistrationServer,
  saveRegistrationResume,
} from '../utils/registration_resume';

jest.mock('@react-native-async-storage/async-storage', () => ({
  __esModule: true,
  default: { getItem: jest.fn(), setItem: jest.fn(), removeItem: jest.fn() },
}));

const storage = AsyncStorage as jest.Mocked<typeof AsyncStorage>;

describe('注册请求恢复记录', () => {
  beforeEach(() => jest.clearAllMocks());

  it('绑定规范化服务器且只持久化非秘密元数据', async () => {
    storage.setItem.mockResolvedValue(undefined);
    await saveRegistrationResume({ server: 'HTTPS://Example.test///', requestId: 'r1', username: 'u', agreementVersion: 'v1', state: 'never_sent' });
    expect(storage.setItem).toHaveBeenCalledWith(expect.stringContaining('https%3A%2F%2Fexample.test'), expect.not.stringContaining('password'));
    expect(storage.setItem.mock.calls[0][1]).not.toContain('invite');
    expect(normalizeRegistrationServer('HTTPS://Example.test///')).toBe('https://example.test');
  });

  it('未知结果可恢复但不能被误当成成功', async () => {
    storage.setItem.mockResolvedValue(undefined);
    const record = await markRegistrationUnknown('https://example.test', 'r1', 'u', 'v1');
    expect(isRecoverable(record)).toBe(true);
    storage.getItem.mockResolvedValue(JSON.stringify(record));
    expect(await loadRegistrationResume('HTTPS://EXAMPLE.TEST/')).toEqual(record);
  });

  it('清理只删除绑定服务器的记录', async () => {
    storage.removeItem.mockResolvedValue(undefined);
    await clearRegistrationResume('https://example.test/');
    expect(storage.removeItem).toHaveBeenCalledWith(expect.stringContaining('example.test'));
  });

  it('成功不持久化，无法核验时仅保存同用户名登录确认状态', async () => {
    storage.setItem.mockResolvedValue(undefined);
    const record = await markRegistrationSameUserLogin('https://example.test', 'r2', 'u', 'v1');
    expect(record.state).toBe('same_user_login');
    expect(isRecoverable(record)).toBe(true);
    expect(storage.setItem.mock.calls[0][1]).not.toContain('password');
    expect(storage.setItem.mock.calls[0][1]).not.toContain('invite');
  });
});

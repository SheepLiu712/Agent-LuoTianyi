import React from 'react';
import { act, create, type ReactTestRenderer } from 'react-test-renderer';
import AsyncStorage from '@react-native-async-storage/async-storage';
import * as SecureStore from 'expo-secure-store';
import { switchServer } from '../features/account/credentials';
import { useAuth } from '../features/account/useAuth';
import { server_config } from '../config';

jest.mock('@react-native-async-storage/async-storage', () =>
  require('@react-native-async-storage/async-storage/jest/async-storage-mock'));
jest.mock('../features/account/crypto', () => ({ getPublicKey: jest.fn(async () => 'key'), clearCachedPublicKey: jest.fn() }));

it('旧版凭据在原服务器恢复登录，换服失败保留登录，成功换服后重启停在登录页', async () => {
  const original = server_config.BASE_URL;
  const saved = new Map<string, string>();
  jest.mocked(SecureStore.getItemAsync).mockImplementation(async key => saved.get(key) ?? null);
  jest.mocked(SecureStore.setItemAsync).mockImplementation(async (key, value) => { saved.set(key, value); });
  jest.mocked(SecureStore.deleteItemAsync).mockImplementation(async key => { saved.delete(key); });
  await AsyncStorage.setItem('auto_login', 'true');
  await AsyncStorage.setItem('saved_username', 'alice');
  await AsyncStorage.setItem('auto_login_token', 'old-token');
  const requests = jest.spyOn(globalThis, 'fetch').mockResolvedValueOnce({
    ok: true, json: async () => ({ user_id: 'alice', message_token: 'session', login_token: 'rotated' }),
  } as Response);
  let account!: ReturnType<typeof useAuth>;
  let root!: ReactTestRenderer;
  function Probe() { account = useAuth(); return null; }
  try {
    await act(async () => { root = create(<Probe />); });
    expect(account.session?.username).toBe('alice');
    expect(saved.get('auto_login_token')).toBe('rotated');
    expect(await AsyncStorage.getItem('auto_login_token')).toBeNull();
    act(() => root.unmount());
    requests.mockResolvedValueOnce({ ok: false, status: 503 } as Response);
    await expect(switchServer('https://new.test')).rejects.toThrow('503');
    expect(server_config.BASE_URL).toBe(original);
    expect(saved.get('auto_login_token')).toBe('rotated');
    requests.mockResolvedValueOnce({ ok: true } as Response);
    await switchServer('https://new.test');
    server_config.BASE_URL = original;
    await act(async () => { root = create(<Probe />); });
    expect(server_config.BASE_URL).toBe('https://new.test');
    expect(account.isLoading).toBe(false);
    expect(account.session).toBeNull();
    expect(requests.mock.calls.filter(([url]) => String(url).endsWith('/auth/auto_login'))).toHaveLength(1);
    expect(saved.size).toBe(0);
    act(() => root.unmount());
  } finally {
    server_config.BASE_URL = original;
    requests.mockRestore();
    await AsyncStorage.clear();
  }
});

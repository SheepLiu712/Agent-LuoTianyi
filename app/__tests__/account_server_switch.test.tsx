import React from 'react';
import { act, create, type ReactTestRenderer } from 'react-test-renderer';
import AsyncStorage from '@react-native-async-storage/async-storage';
import * as SecureStore from 'expo-secure-store';
import LoginScreen from '../features/account/LoginScreen';
import { AppNotices } from '../shell/notices/AppNotices';
import { Alert, Text, TextInput, TouchableOpacity } from 'react-native';
import { getHistory } from '../features/chat/getHistory';
import { switchServer } from '../features/account/credentials';
import { useAuth } from '../features/account/useAuth';
import { server_config } from '../config';

jest.mock('@react-native-async-storage/async-storage', () =>
  require('@react-native-async-storage/async-storage/jest/async-storage-mock'));
jest.mock('../features/account/crypto', () => ({ getPublicKey: jest.fn(async () => 'key'), clearCachedPublicKey: jest.fn(), encryptPassword: async () => ({ ok: true, encrypted: 'encrypted' }) }));

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

jest.mock('react-native', () => ({
  Alert: { alert: jest.fn() }, Keyboard: { dismiss: jest.fn() }, Platform: { OS: 'android' },
  KeyboardAvoidingView: 'KeyboardAvoidingView', Modal: 'Modal', View: 'View', ScrollView: 'ScrollView',
  StyleSheet: { create: (styles: unknown) => styles }, Text: 'Text', TextInput: 'TextInput',
  TouchableOpacity: 'TouchableOpacity', Pressable: 'Pressable', useColorScheme: () => 'light',
  useWindowDimensions: () => ({ width: 390, fontScale: 1 }),
}));
jest.mock('react-native-safe-area-context', () => ({ useSafeAreaInsets: () => ({ top: 0, bottom: 0 }) }));
jest.mock('expo-file-system/legacy', () => ({}));

it('登录失败保留表单，修改密码和重提时分别保留、撤下旧提示，随后显示新的失败原因', async () => {
  let finishRetry!: (result: { success: boolean; message: string }) => void;
  const login = jest.fn().mockResolvedValueOnce({ success: false, message: '密码错误' })
    .mockImplementationOnce(() => new Promise(resolve => { finishRetry = resolve; }));
  let tree!: ReactTestRenderer;
  await act(async () => {
    tree = create(<AppNotices><LoginScreen onLogin={login} onRegister={jest.fn()} resetAccount={jest.fn()} /></AppNotices>);
  });
  const field = (name: string) => tree.root.findAllByType(TextInput).find(n => n.props.placeholder === name)!;
  const submit = () => tree.root.findAllByType(TouchableOpacity).filter(button =>
    button.findAllByType(Text).some(text => text.props.children === '登录')).pop()!.props.onPress();
  const messages = () => tree.root.findAllByType(Text).map(n => n.props.children);
  try {
    act(() => { field('请输入用户名').props.onChangeText('alice'); field('请输入密码').props.onChangeText('first'); });
    await act(async () => { await submit(); });
    expect(messages()).toContain('密码错误');
    expect(field('请输入用户名').props.value).toBe('alice');
    expect(field('请输入密码').props.value).toBe('first');
    act(() => field('请输入密码').props.onChangeText('second'));
    expect(messages()).toContain('密码错误');
    act(() => { void submit(); });
    expect(messages()).not.toContain('密码错误');
    expect(login).toHaveBeenLastCalledWith('alice', 'second', false);
    await act(async () => { finishRetry({ success: false, message: '服务暂不可用' }); });
    expect(messages()).toContain('服务暂不可用');
    expect(messages()).not.toContain('密码错误');
  } finally { act(() => tree.unmount()); }
});

it.each(['验证先返回', '登录先返回'])('取消验证后仍登录原服并在原服恢复会话：%s', async order => {
  const original = server_config.BASE_URL;
  jest.mocked(Alert.alert).mockClear();
  const candidate = 'https://candidate.test';
  const saved = new Map<string, string>();
  jest.mocked(SecureStore.getItemAsync).mockImplementation(async key => saved.get(key) ?? null);
  jest.mocked(SecureStore.setItemAsync).mockImplementation(async (key, value) => { saved.set(key, value); });
  jest.mocked(SecureStore.deleteItemAsync).mockImplementation(async key => { saved.delete(key); });
  let finishProbe!: () => void;
  let finishLogin!: () => void;
  const ok = (body: unknown) => ({ ok: true, json: async () => body } as Response);
  const tokens = { user_id: 'alice', message_token: 'message-a', login_token: 'login-a' };
  const requests = jest.spyOn(globalThis, 'fetch').mockImplementation(async url => {
    if (url === candidate + '/auth/public_key') return new Promise(resolve => { finishProbe = () => resolve(ok({})); });
    if (url === original + '/auth/login') return new Promise(resolve => { finishLogin = () => resolve(ok(tokens)); });
    if (url === original + '/auth/auto_login') return ok(tokens);
    if (String(url).startsWith(original + '/history?')) return ok({ history: [], start_index: 0 });
    throw new Error('意外的请求地址');
  });
  let account!: ReturnType<typeof useAuth>;
  let root!: ReactTestRenderer;
  function Host() {
    account = useAuth();
    return account.isLoading || account.session ? null :
      <AppNotices><LoginScreen onLogin={account.login} onRegister={account.register} resetAccount={jest.fn()} /></AppNotices>;
  }
  function press(label: string) {
    const buttons = root.root.findAllByType(TouchableOpacity).filter(node =>
      node.findAllByType(Text).some(text => text.props.children === label));
    return buttons[buttons.length - 1].props.onPress();
  }
  const type = (placeholder: string, value: string) =>
    root.root.findAllByType(TextInput).find(node => node.props.placeholder === placeholder)!.props.onChangeText(value);
  try {
    await act(async () => { root = create(<Host />); });
    act(() => press('服务器地址'));
    act(() => type('https://your-server.com:60030', candidate));
    act(() => { void press('验证并保存'); });
    act(() => press('取消'));
    act(() => { type('请输入用户名', 'alice'); type('请输入密码', 'password'); press('自动登录'); });
    await act(async () => { void press('登录'); });
    for (const finish of order === '验证先返回' ? [finishProbe, finishLogin] : [finishLogin, finishProbe]) {
      await act(async () => { finish(); });
    }
    expect(account.session).toEqual({ username: 'alice', token: 'message-a', serverUrl: original });
    expect(Alert.alert).not.toHaveBeenCalledWith('成功', expect.anything());
    await getHistory(account.session!.username, account.session!.token, 10, -1);
    expect(requests).toHaveBeenLastCalledWith(expect.stringContaining(original + '/history?'),
      expect.objectContaining({ headers: expect.objectContaining({ Authorization: 'Bearer message-a' }) }));
    act(() => root.unmount());
    await act(async () => { root = create(<Host />); });
    expect(requests).toHaveBeenCalledWith(original + '/auth/auto_login',
      expect.objectContaining({ body: JSON.stringify({ username: 'alice', token: 'login-a' }) }));
    expect(account.session?.serverUrl).toBe(original);
  } finally {
    act(() => root?.unmount());
    requests.mockRestore();
    server_config.BASE_URL = original;
    await AsyncStorage.clear();
  }
});

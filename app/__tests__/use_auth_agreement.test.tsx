import AsyncStorage from '@react-native-async-storage/async-storage';
import * as SecureStore from 'expo-secure-store';
import React, { useEffect } from 'react';
import { act, create } from 'react-test-renderer';

import { useAuth } from '../hooks/useAuth';
import { server_config } from '../config';
import { loadRegistrationResume } from '../utils/registration_resume';
import { markRegistrationSameUserLogin } from '../utils/registration_resume';
import { encryptPassword } from '../utils/crypto';

jest.mock('@react-native-async-storage/async-storage', () => ({
  __esModule: true,
  default: { getItem: jest.fn(), setItem: jest.fn(), removeItem: jest.fn() },
}));
jest.mock('../utils/crypto', () => ({
  encryptPassword: jest.fn(async (value: string) => ({ ok: true, encrypted: `encrypted:${value}` })),
  getPublicKey: jest.fn(async () => 'key'),
}));
jest.mock('../utils/voice_playback_manager', () => ({ voicePlaybackManager: { clear: jest.fn() } }));

const storage = AsyncStorage as jest.Mocked<typeof AsyncStorage>;
const secureStore = SecureStore as jest.Mocked<typeof SecureStore>;
const agreement = { version: 'v2', title: '协议', format: 'agreement.richtext.v1', blocks: [{ runs: [{ text: '正文' }] }] };

function HookHarness({ onValue }: { onValue: (value: ReturnType<typeof useAuth>) => void }) {
  const value = useAuth();
  useEffect(() => onValue(value), [onValue, value]);
  return null;
}

async function renderHook() {
  let current!: ReturnType<typeof useAuth>;
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<HookHarness onValue={value => { current = value; }} />); });
  await act(async () => Promise.resolve());
  const getCurrent = () => current;
  getCurrent.unmount = () => tree.unmount();
  return getCurrent;
}

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

describe('useAuth 协议签署消费者', () => {
  const originalFetch = global.fetch;
  let storageValues: Map<string, string>;

  beforeEach(() => {
    jest.clearAllMocks();
    storageValues = new Map();
    storage.getItem.mockImplementation(async key => storageValues.get(key) ?? null);
    storage.setItem.mockImplementation(async (key, value) => { storageValues.set(key, value); });
    storage.removeItem.mockImplementation(async key => { storageValues.delete(key); });
    secureStore.getItemAsync.mockResolvedValue(null);
    secureStore.setItemAsync.mockResolvedValue(undefined);
    secureStore.deleteItemAsync.mockResolvedValue(undefined);
    server_config.BASE_URL = 'https://one.test';
  });

  afterEach(() => { global.fetch = originalFetch; });

  it('密码登录门禁创建真实 pending，签署后 401 关闭 pending', async () => {
    global.fetch = jest.fn()
      .mockResolvedValueOnce(json(403, { code: 'AGREEMENT_REQUIRED', detail: 'upgrade' }))
      .mockResolvedValueOnce(json(200, agreement))
      .mockResolvedValueOnce(json(200, { agreement_version: 'v2', accepted_at: 'time' }))
      .mockResolvedValueOnce(json(401, { detail: 'bad credential' }));
    const current = await renderHook();

    await act(async () => { await current().login('alice', 'pw', false); });
    expect(current().pendingAgreement?.phase).toBe('sign');
    await act(async () => { await current().acceptAgreement(current().pendingAgreement!); });

    expect(current().pendingAgreement).toBeNull();
  });

  it('签署成功后 429 进入 login 阶段，重试不会再次提交签署', async () => {
    global.fetch = jest.fn()
      .mockResolvedValueOnce(json(403, { code: 'AGREEMENT_REQUIRED', detail: 'upgrade' }))
      .mockResolvedValueOnce(json(200, agreement))
      .mockResolvedValueOnce(json(200, { agreement_version: 'v2', accepted_at: 'time' }))
      .mockResolvedValueOnce(json(429, { detail: 'slow' }))
      .mockResolvedValueOnce(json(200, { login_token: 'new', message_token: 'message', user_id: 'alice' }));
    const current = await renderHook();

    await act(async () => { await current().login('alice', 'pw', false); });
    await act(async () => { await current().acceptAgreement(current().pendingAgreement!); });
    expect(current().pendingAgreement?.phase).toBe('login');
    await act(async () => { await current().acceptAgreement(current().pendingAgreement!); });

    const calls = (global.fetch as jest.Mock).mock.calls.map(call => call[0]);
    expect(calls.filter(url => String(url).endsWith('/auth/agreement/accept'))).toHaveLength(1);
    expect(current().pendingAgreement).toBeNull();
  });

  it('签署后新版门禁回到 sign 阶段而不是错误地复用已签状态', async () => {
    const newer = { ...agreement, version: 'v3' };
    global.fetch = jest.fn()
      .mockResolvedValueOnce(json(403, { code: 'AGREEMENT_REQUIRED', detail: 'upgrade' }))
      .mockResolvedValueOnce(json(200, agreement))
      .mockResolvedValueOnce(json(200, { agreement_version: 'v2', accepted_at: 'time' }))
      .mockResolvedValueOnce(json(403, { code: 'AGREEMENT_REQUIRED', detail: 'upgrade' }))
      .mockResolvedValueOnce(json(200, newer));
    const current = await renderHook();

    await act(async () => { await current().login('alice', 'pw', false); });
    await act(async () => { await current().acceptAgreement(current().pendingAgreement!); });

    expect(current().pendingAgreement?.phase).toBe('sign');
    expect(current().pendingAgreement?.agreement.version).toBe('v3');
  });

  it('自动登录协议门禁保留 token，明确 401 才清除凭据', async () => {
    storage.getItem.mockImplementation(async key => key === 'auto_login' ? 'true' : key === 'saved_username' ? 'alice' : null);
    secureStore.getItemAsync.mockResolvedValue('token');
    global.fetch = jest.fn()
      .mockResolvedValueOnce(json(403, { code: 'AGREEMENT_REQUIRED', detail: 'upgrade' }))
      .mockResolvedValueOnce(json(200, agreement));
    const current = await renderHook();

    await act(async () => Promise.resolve());

    expect(current().pendingAgreement?.credential.kind).toBe('auto_login');
    expect(secureStore.deleteItemAsync).not.toHaveBeenCalled();
  });

  it('自动登录签署后的 401 关闭 pending 并清除失效 token', async () => {
    storage.getItem.mockImplementation(async key => key === 'auto_login' ? 'true' : key === 'saved_username' ? 'alice' : null);
    secureStore.getItemAsync.mockResolvedValue('token');
    global.fetch = jest.fn()
      .mockResolvedValueOnce(json(403, { code: 'AGREEMENT_REQUIRED', detail: 'upgrade' }))
      .mockResolvedValueOnce(json(200, agreement))
      .mockResolvedValueOnce(json(200, { agreement_version: 'v2', accepted_at: 'time' }))
      .mockResolvedValueOnce(json(401, { detail: 'invalid' }));
    const current = await renderHook();
    await act(async () => Promise.resolve());

    await act(async () => { await current().acceptAgreement(current().pendingAgreement!); });

    expect(current().pendingAgreement).toBeNull();
    expect(secureStore.deleteItemAsync).toHaveBeenCalled();
  });

  it('注册网络未知后用原 ID 和版本重放，改密码或邀请码不会发送请求', async () => {
    global.fetch = jest.fn()
      .mockRejectedValueOnce(new Error('network'))
      .mockResolvedValueOnce(json(200, { message: '注册成功' }));
    const current = await renderHook();

    await act(async () => { await current().register('alice', 'pw', 'pw', 'invite', 'r1', 'v1'); });
    const unknown = await loadRegistrationResume('https://one.test');
    expect(unknown).toMatchObject({ requestId: 'r1', agreementVersion: 'v1', state: 'unknown' });
    await act(async () => { await current().register('alice', 'changed', 'changed', 'invite', 'r1', 'v1'); });
    await act(async () => { await current().register('alice', 'pw', 'pw', 'changed-invite', 'r1', 'v1'); });
    expect(global.fetch).toHaveBeenCalledTimes(1);
    await act(async () => { await current().register('alice', 'pw', 'pw', 'invite', 'r1', 'v1'); });

    const sent = JSON.parse((global.fetch as jest.Mock).mock.calls[1][1].body);
    expect(sent.registration_request_id).toBe('r1');
    expect(sent.agreement_version).toBe('v1');
    expect(await loadRegistrationResume('https://one.test')).toBeNull();
  });

  it('注册 CONFLICT 和其他确定但未知的 4xx 不会静默清除恢复记录', async () => {
    global.fetch = jest.fn()
      .mockRejectedValueOnce(new Error('network'))
      .mockResolvedValueOnce(json(409, { code: 'REGISTRATION_REQUEST_CONFLICT', detail: 'conflict' }))
      .mockResolvedValueOnce(json(422, { detail: 'invalid' }));
    const current = await renderHook();

    await act(async () => { await current().register('alice', 'pw', 'pw', 'invite', 'r1', 'v1'); });
    await act(async () => { await current().register('alice', 'pw', 'pw', 'invite', 'r1', 'v1'); });
    await act(async () => { await current().register('alice', 'pw', 'pw', 'invite', 'r1', 'v1'); });

    expect(await loadRegistrationResume('https://one.test')).toMatchObject({ requestId: 'r1', state: 'unknown' });
  });

  it('无法核验记录仅在同服务器同用户名成功登录后跨 hook 清除', async () => {
    global.fetch = jest.fn().mockResolvedValueOnce(json(409, { code: 'REGISTRATION_REQUEST_UNVERIFIABLE', detail: 'verify' }));
    const first = await renderHook();
    await act(async () => { await first().register('alice', 'pw', 'pw', 'invite', 'r1', 'v1'); });
    expect(await loadRegistrationResume('https://one.test')).toMatchObject({ state: 'same_user_login' });
    first.unmount();

    global.fetch = jest.fn()
      .mockResolvedValueOnce(json(200, { login_token: 'token', message_token: 'message', user_id: 'bob' }))
      .mockResolvedValueOnce(json(200, { login_token: 'token2', message_token: 'message2', user_id: 'alice' }));
    const second = await renderHook();
    await act(async () => { await second().login('bob', 'pw', false); });
    expect(await loadRegistrationResume('https://one.test')).not.toBeNull();
    await act(async () => { await second().login('alice', 'pw', false); });
    expect(await loadRegistrationResume('https://one.test')).toBeNull();
  });

  it('same_user_login 阻止任何当前服务器注册，确认登录后才放行', async () => {
    await markRegistrationSameUserLogin('https://one.test', 'r1', 'alice', 'v1');
    const current = await renderHook();
    (encryptPassword as jest.Mock).mockRejectedValue(new Error('must not encrypt'));
    global.fetch = jest.fn();

    const otherUser = await current().register('bob', 'pw', 'pw', 'invite', 'r2', 'v2');
    const originalUser = await current().register('alice', 'pw', 'pw', 'invite', 'r1', 'v1');
    expect(otherUser.code).toBe('LOGIN_CONFIRMATION_REQUIRED');
    expect(originalUser.code).toBe('LOGIN_CONFIRMATION_REQUIRED');
    expect(encryptPassword).not.toHaveBeenCalled();
    expect(global.fetch).not.toHaveBeenCalled();
    expect(await loadRegistrationResume('https://one.test')).toMatchObject({ requestId: 'r1', username: 'alice', state: 'same_user_login' });

    (encryptPassword as jest.Mock).mockResolvedValue({ ok: true, encrypted: 'encrypted' });
    global.fetch = jest.fn()
      .mockResolvedValueOnce(json(401, { detail: 'bad' }))
      .mockResolvedValueOnce(json(200, { login_token: 'token', message_token: 'message', user_id: 'alice' }))
      .mockResolvedValueOnce(json(200, { message: '注册成功' }));
    await act(async () => { await current().login('alice', 'wrong', false); });
    expect(await loadRegistrationResume('https://one.test')).not.toBeNull();
    await act(async () => { await current().login('alice', 'pw', false); });
    expect(await loadRegistrationResume('https://one.test')).toBeNull();
    await act(async () => { await current().register('bob', 'pw', 'pw', 'invite', 'r2', 'v2'); });
    expect(global.fetch).toHaveBeenCalledTimes(3);
  });

  it('other server same_user_login does not block the current server', async () => {
    await markRegistrationSameUserLogin('https://one.test', 'r1', 'alice', 'v1');
    server_config.BASE_URL = 'https://two.test';
    global.fetch = jest.fn().mockResolvedValue(json(200, { message: '注册成功' }));
    const current = await renderHook();

    await act(async () => { await current().register('bob', 'pw', 'pw', 'invite', 'r2', 'v2'); });

    expect(global.fetch).toHaveBeenCalledTimes(1);
    expect(await loadRegistrationResume('https://one.test')).toMatchObject({ state: 'same_user_login' });
    server_config.BASE_URL = 'https://one.test';
  });

  it('注册超时把结果标为 unknown，切换服务器不会发旧服务器请求 ID', async () => {
    const originalTimeout = server_config.API_TIMEOUT;
    server_config.API_TIMEOUT = 1;
    global.fetch = jest.fn((_url: RequestInfo | URL, init?: RequestInit) => new Promise<Response>((_, reject) => {
      init?.signal?.addEventListener('abort', () => reject(new Error('aborted')));
    })) as typeof fetch;
    const current = await renderHook();
    await act(async () => { await current().register('alice', 'pw', 'pw', 'invite', 'old-id', 'v1'); });
    expect(await loadRegistrationResume('https://one.test')).toMatchObject({ requestId: 'old-id', state: 'unknown' });

    server_config.BASE_URL = 'https://two.test';
    global.fetch = jest.fn().mockResolvedValue(json(200, { message: '注册成功' }));
    await act(async () => { await current().register('alice', 'pw', 'pw', 'invite', 'new-id', 'v2'); });
    const body = JSON.parse((global.fetch as jest.Mock).mock.calls[0][1].body);
    expect(body.registration_request_id).toBe('new-id');
    expect(await loadRegistrationResume('https://one.test')).toMatchObject({ requestId: 'old-id' });
    server_config.BASE_URL = 'https://one.test';
    server_config.API_TIMEOUT = originalTimeout;
  });
});

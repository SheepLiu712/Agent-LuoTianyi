import AsyncStorage from '@react-native-async-storage/async-storage';
import * as SecureStore from 'expo-secure-store';
import React, { useEffect } from 'react';
import { act, create } from 'react-test-renderer';

import { useAuth } from '../features/account/useAuth';
import { server_config } from '../config';
import { loadRegistrationResume } from '../utils/registration_resume';
import { markRegistrationSameUserLogin } from '../utils/registration_resume';
import { encryptPassword } from '../features/account/crypto';

jest.mock('@react-native-async-storage/async-storage', () => ({
  __esModule: true,
  default: { getItem: jest.fn(), setItem: jest.fn(), removeItem: jest.fn() },
}));
jest.mock('../features/account/crypto', () => ({
  encryptPassword: jest.fn(async (value: string) => ({ ok: true, encrypted: `encrypted:${value}` })),
  getPublicKey: jest.fn(async () => 'key'),
}));
jest.mock('../features/chat/voice_playback_manager', () => ({ voicePlaybackManager: { clear: jest.fn() } }));

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
    (encryptPassword as jest.Mock).mockImplementation(async (value: string) => ({ ok: true, encrypted: `encrypted:${value}` }));
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

  it.each(['password', 'auto_login'])('正文下载失败保留 %s 身份，重试恢复签署入口', async kind => {
    if (kind === 'auto_login') {
      storage.getItem.mockImplementation(async key => key === 'auto_login' ? 'true' : key === 'saved_username' ? 'alice' : null);
      secureStore.getItemAsync.mockResolvedValue('token');
    }
    global.fetch = jest.fn()
      .mockResolvedValueOnce(json(403, { code: 'AGREEMENT_REQUIRED' }))
      .mockResolvedValueOnce(json(503, { detail: 'offline' }))
      .mockResolvedValueOnce(json(200, agreement));
    const current = await renderHook();
    if (kind === 'password') await act(async () => { await current().login('alice', 'pw', false); });
    expect(current().pendingAgreement?.agreement).toBeNull();
    expect(current().pendingAgreement?.credential.kind).toBe(kind);
    expect(secureStore.deleteItemAsync).not.toHaveBeenCalled();
    await act(async () => { await current().retryAgreement(); });
    expect(current().pendingAgreement?.agreement?.version).toBe('v2');
    expect(current().pendingAgreement?.credential.username).toBe('alice');
    expect((global.fetch as jest.Mock).mock.calls.filter(call => String(call[0]).endsWith('/auth/agreement/accept'))).toHaveLength(0);
    act(() => current.unmount());
  });

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
    expect(current().pendingAgreement?.agreement?.version).toBe('v3');
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

  it.each(['unknown', 'never_sent'])('跨 hook 恢复 %s 时拒绝另一身份、新 ID、新版本及无协议字段覆盖', async state => {
    const key = 'registration_resume:v1:https%3A%2F%2Fone.test';
    const record = JSON.stringify({ server: 'https://one.test', requestId: 'r1', username: 'alice', agreementVersion: 'v1', state, createdAt: 1 });
    storageValues.set(key, record);
    global.fetch = jest.fn();
    const current = await renderHook();
    for (const [username, requestId, version] of [
      ['bob', 'r2', 'v1'], ['alice', 'r2', 'v1'], ['alice', 'r1', 'v2'], ['bob', undefined, undefined],
    ]) {
      const result = await current().register(username!, 'pw', 'pw', 'invite', requestId, version);
      expect(result.code).toBe('REGISTRATION_RESULT_PENDING');
    }
    expect(encryptPassword).not.toHaveBeenCalled();
    expect(global.fetch).not.toHaveBeenCalled();
    expect(storageValues.get(key)).toBe(record);
    act(() => current.unmount());
  });

  it('请求发出且尚无响应时已持久化未决记录，重建 hook 仍能确认原提交', async () => {
    let finish!: (response: Response) => void;
    global.fetch = jest.fn().mockImplementationOnce(() => new Promise<Response>(resolve => { finish = resolve; }))
      .mockResolvedValueOnce(json(200, { message: '注册成功', user_id: 'alice' }));
    const first = await renderHook();
    let submitting!: Promise<unknown>;
    await act(async () => {
      submitting = first().register('alice', 'pw', 'pw', 'invite', 'r1', 'v1');
      await Promise.resolve();
    });
    expect(global.fetch).toHaveBeenCalledTimes(1);
    expect(await loadRegistrationResume('https://one.test')).toMatchObject({ requestId: 'r1', username: 'alice', agreementVersion: 'v1', state: 'unknown' });
    const persisted = storageValues.get('registration_resume:v1:https%3A%2F%2Fone.test')!;
    expect(persisted).not.toContain('password');
    expect(persisted).not.toContain('invite');
    act(() => first.unmount());

    // 用全新 hook 模拟进程重建：原内存身份锁已经丢失，仅持久化记录仍存在。
    const restarted = await renderHook();
    const blocked = await restarted().register('alice', 'pw', 'pw', 'invite', 'r2', 'v2');
    expect(blocked.code).toBe('REGISTRATION_RESULT_PENDING');
    let restored!: { success: boolean };
    await act(async () => { restored = await restarted().register('alice', 'pw', 'pw', 'invite', 'r1', 'v1'); });
    expect(restored.success).toBe(true);
    const body = JSON.parse((global.fetch as jest.Mock).mock.calls[1][1].body);
    expect(body).toMatchObject({ registration_request_id: 'r1', agreement_version: 'v1', username: 'alice' });
    expect(await loadRegistrationResume('https://one.test')).toBeNull();
    // 收束被丢弃客户端的请求，不把它的迟到失败重新写成恢复记录。
    await act(async () => { finish(json(503, { detail: 'offline' })); await submitting; });
    expect(await loadRegistrationResume('https://one.test')).toBeNull();
    act(() => restarted.unmount());
  });

  it.each([400, 422])('初次注册明确收到 %s 拒绝后允许更正表单重新提交', async status => {
    global.fetch = jest.fn().mockResolvedValueOnce(json(status, { detail: 'invalid input' }))
      .mockResolvedValueOnce(json(200, { message: '注册成功' }));
    const current = await renderHook();
    await act(async () => { await current().register('alice', 'pw', 'pw', 'invalid', 'r1', 'v1'); });
    expect(await loadRegistrationResume('https://one.test')).toBeNull();
    await act(async () => { await current().register('alice', 'pw', 'pw', 'corrected', 'r2', 'v1'); });
    expect(global.fetch).toHaveBeenCalledTimes(2);
    expect(await loadRegistrationResume('https://one.test')).toBeNull();
    act(() => current.unmount());
  });

  it('注册返回换版但正文下载失败时仍返回换版错误码并结束原请求恢复', async () => {
    global.fetch = jest.fn()
      .mockResolvedValueOnce(json(409, { code: 'AGREEMENT_CHANGED', detail: '用户协议已更新，请重新阅读' }))
      .mockResolvedValueOnce(json(503, { detail: 'offline' }));
    const current = await renderHook();
    const result = await current().register('alice', 'pw', 'pw', 'invite', 'r1', 'v1');
    expect(result).toMatchObject({ success: false, code: 'AGREEMENT_CHANGED' });
    expect(result.agreement).toBeUndefined();
    expect(await loadRegistrationResume('https://one.test')).toBeNull();
    expect((global.fetch as jest.Mock).mock.calls.map(call => call[0])).toEqual([
      'https://one.test/auth/register', 'https://one.test/auth/agreement',
    ]);
    act(() => current.unmount());
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

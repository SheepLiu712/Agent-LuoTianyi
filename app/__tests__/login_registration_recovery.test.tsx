import React, { ElementType } from 'react';
import { act, create, ReactTestInstance, ReactTestRenderer } from 'react-test-renderer';
import LoginScreen from '../app/login';
import { THEMES } from '../utils/theme';
import { server_config } from '../config';

const storage = new Map<string, string>();
const agreement = { version: 'v2', title: '用户协议', format: 'agreement.richtext.v1' as const, blocks: [{ runs: [{ text: '正文' }] }] };
let agreementSubmit: ((result: { success: boolean; code?: string; agreement?: typeof agreement }) => void) | undefined;
let latestModal: ReactTestInstance | undefined;

jest.mock('@react-native-async-storage/async-storage', () => ({
  __esModule: true,
  default: {
    getItem: jest.fn(async (key: string) => storage.get(key) ?? null),
    setItem: jest.fn(async (key: string, value: string) => { storage.set(key, value); }),
    removeItem: jest.fn(async (key: string) => { storage.delete(key); }),
  },
}));
jest.mock('expo-secure-store', () => ({ getItemAsync: jest.fn(), setItemAsync: jest.fn(), deleteItemAsync: jest.fn() }));
jest.mock('../hooks/useAuth', () => ({ fetchCurrentAgreement: jest.fn(async () => ({ success: true, data: agreement })) }));
jest.mock('../components/AgreementModal', () => ({
  AgreementModal: (props: any) => {
    latestModal = { props } as ReactTestInstance;
    return 'AgreementModalHost';
  },
}));
jest.mock('react-native-safe-area-context', () => ({ useSafeAreaInsets: () => ({ top: 1, bottom: 2, left: 0, right: 0 }) }));
jest.mock('react-native', () => ({
  Alert: { alert: jest.fn((_title: string, _message: string, buttons?: Array<{ text: string; onPress?: () => void }>) => {
    if (buttons) (globalThis as any).__lastAlertButtons = buttons;
  }) },
  BackHandler: { exitApp: jest.fn() }, Keyboard: { dismiss: jest.fn() }, KeyboardAvoidingView: 'KeyboardAvoidingView', Modal: (props: any) => props.visible ? 'ModalHost' : null,
  Platform: { OS: 'android' }, ScrollView: 'ScrollView', StyleSheet: { create: (value: unknown) => value }, Text: 'Text', TextInput: 'TextInput', TouchableOpacity: 'TouchableOpacity', useColorScheme: () => 'light', View: 'View',
}));
jest.mock('../utils/voice_playback_manager', () => ({ voicePlaybackManager: { clear: jest.fn() } }));
jest.mock('../utils/crypto', () => ({ encryptPassword: jest.fn(), clearCachedPublicKey: jest.fn() }));
jest.mock('../utils/auth_request', () => ({ authFetch: jest.fn() }));

const TEXT = 'Text' as unknown as ElementType;
const INPUT = 'TextInput' as unknown as ElementType;
const BUTTON = 'TouchableOpacity' as unknown as ElementType;

function renderPage(onRegister: jest.Mock, onLogin = jest.fn().mockResolvedValue({ success: true, message: 'ok' })) {
  let tree!: ReactTestRenderer;
  act(() => { tree = create(<LoginScreen onLogin={onLogin} onRegister={onRegister} />); });
  return tree;
}
function text(tree: ReactTestRenderer, value: string) { return tree.root.findAllByType(TEXT).find((node) => node.props.children === value); }
function button(tree: ReactTestRenderer, value: string): ReactTestInstance {
  const result = tree.root.findAllByType(BUTTON).find((node) => node.findAll((child) => child.props.children === value).length > 0);
  if (!result) throw new Error(`button ${value} not found`);
  return result;
}
function registerSubmitButton(tree: ReactTestRenderer): ReactTestInstance {
  const matches = tree.root.findAllByType(BUTTON).filter((node) => node.findAll((child) => child.props.children === '注册').length > 0);
  const result = matches[matches.length - 1];
  if (!result) throw new Error('register submit button not found');
  return result;
}
function input(tree: ReactTestRenderer, placeholder: string) { const result = tree.root.findAllByType(INPUT).find((node) => node.props.placeholder === placeholder); if (!result) throw new Error(`input ${placeholder} not found`); return result; }
async function enterRegistration(tree: ReactTestRenderer) {
  await act(async () => button(tree, '注册').props.onPress());
  // The tab and submit button share the label; after selecting the tab, the form inputs are present.
}
async function fillAndOpen(tree: ReactTestRenderer, username: string) {
  await act(async () => button(tree, '注册').props.onPress());
  const fields = [['请输入用户名', username], ['请输入密码', 'pw'], ['请再次输入密码', 'pw'], ['请输入邀请码', 'invite']];
  for (const [placeholder, value] of fields) act(() => input(tree, placeholder).props.onChangeText(value));
  await act(async () => registerSubmitButton(tree).props.onPress());
}

describe('LoginScreen 注册恢复真实消费者', () => {
  beforeEach(() => {
    storage.clear();
    agreementSubmit = undefined;
    latestModal = undefined;
    (globalThis as any).__lastAlertButtons = undefined;
    server_config.BASE_URL = 'https://server.example';
  });

  it('unknown V1 + 当前正文 V2 仍把原 R1/V1 传给 onRegister', async () => {
    storage.set('registration_resume:v1:https%3A%2F%2Fserver.example', JSON.stringify({ server: 'https://server.example', requestId: 'R1', username: 'alice', agreementVersion: 'v1', state: 'unknown', createdAt: 1 }));
    const register = jest.fn().mockResolvedValue({ success: false, message: 'retry' });
    const tree = renderPage(register);
    await fillAndOpen(tree, 'alice');
    await act(async () => latestModal?.props.onSubmit());
    expect(register).toHaveBeenCalledWith('alice', 'pw', 'pw', 'invite', 'R1', 'v1');
  });

  it('never_sent V1 遇当前 V2 创建新 ID 并提交 V2', async () => {
    storage.set('registration_resume:v1:https%3A%2F%2Fserver.example', JSON.stringify({ server: 'https://server.example', requestId: 'OLD', username: 'alice', agreementVersion: 'v1', state: 'never_sent', createdAt: 1 }));
    const register = jest.fn().mockResolvedValue({ success: false, message: 'retry' });
    const tree = renderPage(register);
    await fillAndOpen(tree, 'alice');
    await act(async () => latestModal?.props.onSubmit());
    expect(register.mock.calls[0][5]).toBe('v2');
    expect(register.mock.calls[0][4]).not.toBe('OLD');
  });

  it('AGREEMENT_CHANGED 后更新协议、生成新 ID，并在下一次确认提交 V2', async () => {
    const register = jest.fn().mockResolvedValueOnce({ success: false, code: 'AGREEMENT_CHANGED', message: 'changed', agreement: { ...agreement, version: 'v3' } }).mockResolvedValue({ success: false, message: 'retry' });
    const tree = renderPage(register);
    await fillAndOpen(tree, 'alice');
    await act(async () => latestModal?.props.onSubmit());
    expect(latestModal?.props.agreement.version).toBe('v3');
    const firstId = register.mock.calls[0][4];
    await act(async () => latestModal?.props.onSubmit());
    expect(register.mock.calls[1][5]).toBe('v3');
    expect(register.mock.calls[1][4]).not.toBe(firstId);
  });

  it('冲突取消保留表单；确认仅清相同 pending ID，过期 confirmation 不清新 ID', async () => {
    const register = jest.fn().mockResolvedValue({ success: false, code: 'REGISTRATION_REQUEST_CONFLICT', message: 'conflict' });
    const tree = renderPage(register);
    await fillAndOpen(tree, 'alice');
    await act(async () => latestModal?.props.onSubmit());
    const oldId = register.mock.calls[0][4];
    const buttons = (globalThis as any).__lastAlertButtons as Array<{ text: string; onPress?: () => void }>;
    buttons[0].onPress?.();
    expect(input(tree, '请输入用户名').props.value).toBe('alice');
    storage.set('registration_resume:v1:https%3A%2F%2Fserver.example', JSON.stringify({ server: 'https://server.example', requestId: oldId, username: 'alice', agreementVersion: 'v2', state: 'unknown', createdAt: 1 }));
    act(() => input(tree, '请输入用户名').props.onChangeText('bob'));
    await act(async () => registerSubmitButton(tree).props.onPress());
    storage.set('registration_resume:v1:https%3A%2F%2Fserver.example', JSON.stringify({ server: 'https://server.example', requestId: 'NEW', username: 'bob', agreementVersion: 'v2', state: 'unknown', createdAt: 2 }));
    await act(async () => { buttons[1].onPress?.(); await Promise.resolve(); });
    expect(storage.has('registration_resume:v1:https%3A%2F%2Fserver.example')).toBe(true);
    expect(register).toHaveBeenCalledTimes(1);
  });

  it('服务器不一致或缺少恢复记录时不调用 onRegister，取消只保留 UA2 表单', async () => {
    storage.set('registration_resume:v1:https%3A%2F%2Fother.example', JSON.stringify({ server: 'https://other.example', requestId: 'R', username: 'alice', agreementVersion: 'v1', state: 'unknown', createdAt: 1 }));
    const register = jest.fn().mockResolvedValue({ success: true, message: 'ok' });
    const tree = renderPage(register);
    await fillAndOpen(tree, 'alice');
    await act(async () => latestModal?.props.onCancel());
    expect(register).not.toHaveBeenCalled();
    expect(input(tree, '请输入用户名').props.value).toBe('alice');
  });

  it('same_user_login 阻止注册，切登录页预填原用户名并保留记录', async () => {
    storage.set('registration_resume:v1:https%3A%2F%2Fserver.example', JSON.stringify({ server: 'https://server.example', requestId: 'R1', username: 'alice', agreementVersion: 'v1', state: 'same_user_login', createdAt: 1 }));
    const register = jest.fn();
    const tree = renderPage(register);
    await fillAndOpen(tree, 'bob');
    expect(register).not.toHaveBeenCalled();
    expect(input(tree, '请输入用户名').props.value).toBe('alice');
    expect(storage.has('registration_resume:v1:https%3A%2F%2Fserver.example')).toBe(true);
  });
});

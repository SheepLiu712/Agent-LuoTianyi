jest.mock('expo-image-manipulator', () => ({}));
jest.mock('expo-av', () => ({}));
jest.mock('expo-file-system/legacy', () => ({}));
jest.mock('react-native', () => ({ AppState: { currentState: 'active' } }));

import * as SecureStore from 'expo-secure-store';
import * as modelClient from '../shared/client-model/llm_client';
import { setLlmModulesConfig } from '../shared/client-model/llm_key_storage';
import { MessageProcessor } from '../features/chat/message_processor';
import { NetworkClient } from '../features/chat/connection/network_client';

import {
  buildLlmModulesConfig,
  validateLlmForms,
} from '../features/settings/modelForm';
import type { ModuleFormState } from '../features/settings/modelForm';
import type { ClientModelType } from '../shared/client-model/llm_client';

const types: ClientModelType[] = [
  {
    id: 'main_chat',
    name: '主对话模型',
    description: '',
    model_kind: 'llm',
    requires_json: false,
    requires_thinking: false,
  },
  {
    id: 'image_understanding',
    name: '图片理解模型',
    description: '',
    model_kind: 'vlm',
    requires_json: false,
    requires_thinking: false,
  },
];

const configured: ModuleFormState = {
  enabled: true,
  provider: ' Custom ',
  baseUrl: 'https://custom.example/v1/',
  model: ' model-x ',
  apiKey: ' sk-x ',
  paramsText: '{"temperature": 0.2}',
  supportsJson: true,
  supportsThinking: false,
};

describe('LLM settings configuration', () => {
  it('accepts arbitrary provider, url and model and stores the server model kind', () => {
    const config = buildLlmModulesConfig(types, {
      main_chat: configured,
      image_understanding: { ...configured, enabled: false },
    });
    expect(config.main_chat).toMatchObject({
      provider: 'Custom',
      baseUrl: 'https://custom.example/v1',
      model: 'model-x',
      apiKey: 'sk-x',
      modelKind: 'llm',
      modelCapabilities: {
        can_use_json: true,
        can_enable_thinking: false,
      },
    });
    expect(config.image_understanding.modelKind).toBe('vlm');
  });

  it('does not validate against a server provider or model catalog', () => {
    expect(validateLlmForms(types, { main_chat: configured })).toBeNull();
  });

  it('rejects missing base url and malformed params', () => {
    expect(
      validateLlmForms(types, {
        main_chat: { ...configured, baseUrl: '' },
      }),
    ).toContain('Base URL');
    expect(
      validateLlmForms(types, {
        main_chat: { ...configured, paramsText: '[]' },
      }),
    ).toContain('JSON 对象');
  });
});

it('保存新模型后，当前聊天的下一次请求立即使用新配置', async () => {
  const storage = new Map<string, string>();
  jest.mocked(SecureStore.setItemAsync).mockImplementation(async (key, value) => { storage.set(key, value); });
  jest.mocked(SecureStore.getItemAsync).mockImplementation(async key => storage.get(key) ?? null);
  const provider = jest.spyOn(modelClient, 'callLlmProvider').mockResolvedValue({ content: '回复', usage: null });
  const feedback = {
    emitAgentMessage: jest.fn(), emitMessageStatus: jest.fn(), emitAgentThinking: jest.fn(),
    emitLocalTtsState: jest.fn(), emitErrorText: jest.fn(),
  };
  const chat = new MessageProcessor(new NetworkClient(), feedback, jest.fn());
  for (const model of ['old-model', 'new-model']) {
    await setLlmModulesConfig(buildLlmModulesConfig(types, { main_chat: { ...configured, model } }));
    await expect(chat.processLlmRequest({ type: 'main_chat', request_id: model, prompt: '你好' }))
      .resolves.toMatchObject({ content: '回复' });
    expect(provider).toHaveBeenLastCalledWith(expect.objectContaining({
      url: 'https://custom.example/v1/chat/completions',
      body: expect.objectContaining({ model, temperature: 0.2 }),
    }));
  }
  provider.mockRestore();
});

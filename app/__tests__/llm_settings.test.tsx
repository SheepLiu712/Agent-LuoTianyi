import {
  buildLlmModulesConfig,
  validateLlmForms,
} from '../utils/llm_requirements';
import type { ModuleFormState } from '../utils/llm_requirements';
import type { ClientModelType } from '../utils/llm_client';

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

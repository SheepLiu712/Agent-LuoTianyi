/**
 * LlmSettingsScreen 保存→重载测试
 *
 * 验证设置页保存 API Key 后写入 SecureStore（mock），组件重载后回填到输入框。
 */
import React from 'react';
import renderer, { act, ReactTestRenderer } from 'react-test-renderer';

const secureStoreBacking: Record<string, string> =
  ((globalThis as { __testSecureStoreBacking?: Record<string, string> })
    .__testSecureStoreBacking ??= {});

const mockSecureStore: {
  getItemAsync: jest.Mock;
  setItemAsync: jest.Mock;
  deleteItemAsync: jest.Mock;
  __reset: () => void;
} = {
  getItemAsync: jest.fn(async (key: string) => secureStoreBacking[key] ?? null),
  setItemAsync: jest.fn(async (key: string, value: string) => {
    secureStoreBacking[key] = value;
  }),
  deleteItemAsync: jest.fn(async (key: string) => {
    delete secureStoreBacking[key];
  }),
  __reset: () => {
    for (const key of Object.keys(secureStoreBacking)) {
      delete secureStoreBacking[key];
    }
  },
};

const mockAsyncStorage: {
  getItem: jest.Mock;
  setItem: jest.Mock;
  removeItem: jest.Mock;
  clear: jest.Mock;
  __reset: () => void;
} = (() => {
  const store: Record<string, string> = {};
  return {
    getItem: jest.fn(async (key: string) => store[key] ?? null),
    setItem: jest.fn(async (key: string, value: string) => {
      store[key] = value;
    }),
    removeItem: jest.fn(async (key: string) => {
      delete store[key];
    }),
    clear: jest.fn(async () => {
      for (const key of Object.keys(store)) {
        delete store[key];
      }
    }),
    __reset: () => {
      for (const key of Object.keys(store)) {
        delete store[key];
      }
    },
  };
})();

jest.mock('expo-secure-store', () => mockSecureStore);
jest.mock('expo-clipboard', () => ({
  getStringAsync: jest.fn(async () => 'sk-clipboard'),
}));
jest.mock('@react-native-async-storage/async-storage', () => mockAsyncStorage);
jest.mock('react-native-safe-area-context', () => ({
  useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }),
}));
jest.mock('react-native', () => {
  const React = require('react');
  const stub = (name: string) => {
    const Comp = (props: Record<string, unknown>) => React.createElement('View', props);
    (Comp as { displayName?: string }).displayName = name;
    return Comp;
  };
  return {
    Platform: { OS: 'ios' },
    StyleSheet: { create: (styles: unknown) => styles, hairlineWidth: 1 },
    Keyboard: { addListener: jest.fn(() => ({ remove: jest.fn() })) },
    Alert: { alert: jest.fn() },
    View: stub('View'),
    Text: stub('Text'),
    TextInput: stub('TextInput'),
    TouchableOpacity: stub('TouchableOpacity'),
    ScrollView: stub('ScrollView'),
    Modal: stub('Modal'),
    KeyboardAvoidingView: stub('KeyboardAvoidingView'),
  };
});
jest.mock('../config', () => ({
  LLM_API_KEY_STORAGE_KEY: 'llm_api_key',
  LLM_PROVIDER_STORAGE_KEY: 'llm_provider',
  LLM_MODEL_STORAGE_KEY: 'llm_model',
  LLM_PROVIDER_BASE_URL_STORAGE_KEY: 'llm_provider_base_url',
  LLM_PARAMS_STORAGE_KEY: 'llm_params',
  LLM_ENABLE_THINKING_STORAGE_KEY: 'llm_enable_thinking',
  LLM_USE_JSON_STORAGE_KEY: 'llm_use_json',
  VLM_API_KEY_STORAGE_KEY: 'vlm_api_key',
  VLM_PROVIDER_STORAGE_KEY: 'vlm_provider',
  VLM_MODEL_STORAGE_KEY: 'vlm_model',
  VLM_PROVIDER_BASE_URL_STORAGE_KEY: 'vlm_provider_base_url',
  VLM_PARAMS_STORAGE_KEY: 'vlm_params',
  VLM_ENABLE_THINKING_STORAGE_KEY: 'vlm_enable_thinking',
  VLM_USE_JSON_STORAGE_KEY: 'vlm_use_json',
  server_config: { BASE_URL: 'https://server.example.com' },
}));

const mockPresets = [
  {
    name: 'DeepSeek',
    base_url: 'https://api.deepseek.com/v1',
    models: ['deepseek-v4-flash'],
    vlm_models: [],
  },
];

jest.mock('../utils/llm_client', () => ({
  fetchProviderPresets: jest.fn(async () => mockPresets),
  fetchJsonRequiredModules: jest.fn(async () => ({ llm: [], vlm: [] })),
  probeLlmConfig: jest.fn(async () => undefined),
  resolveProviderBaseUrl: jest.fn(
    (name: string, presets: Array<{ name: string; base_url: string }>) =>
      presets?.find((p) => p.name === name)?.base_url ?? '',
  ),
}));

import LlmSettingsScreen from '../app/llm_settings';

describe('LlmSettingsScreen 保存→重载', () => {
  beforeEach(() => {
    mockSecureStore.__reset();
    mockAsyncStorage.__reset();
    jest.clearAllMocks();
  });

  it('保存 API Key 后 SecureStore 持久化，重载后回填', async () => {
    const onClose = jest.fn();
    let tree: ReactTestRenderer | undefined;

    await act(async () => {
      tree = renderer.create(<LlmSettingsScreen onClose={onClose} />);
    });
    // 等待加载 effect（读取本地配置 / 拉取服务商与 JSON 功能列表）完成
    await act(async () => {
      await Promise.resolve();
    });

    const apiKeyInput = tree!.root.findAllByProps({
      placeholder: '粘贴对话服务商的 API Key',
    })[0];
    expect(apiKeyInput).toBeTruthy();

    await act(async () => {
      apiKeyInput.props.onChangeText('sk-test-key');
    });

    const saveText = tree!.root.findAll(
      (node) => node.props.children === '保存设置',
    )[0];
    expect(saveText).toBeTruthy();
    const saveButton = saveText.parent!;
    await act(async () => {
      await saveButton.props.onPress();
    });
    // 等待保存链路的剩余状态更新（setSaving(false) 等）
    await act(async () => {
      await Promise.resolve();
    });

    // 保存后 key 已写入 SecureStore（llm_api_key）
    await expect(mockSecureStore.getItemAsync('llm_api_key')).resolves.toBe(
      'sk-test-key',
    );
    expect(onClose).toHaveBeenCalled();

    // 重载：卸载后重新渲染，设置页应回填已保存的 key
    await act(async () => {
      tree!.unmount();
    });
    let tree2: ReactTestRenderer | undefined;
    await act(async () => {
      tree2 = renderer.create(<LlmSettingsScreen onClose={onClose} />);
    });
    await act(async () => {
      await Promise.resolve();
    });

    const apiKeyInput2 = tree2!.root.findAllByProps({
      placeholder: '粘贴对话服务商的 API Key',
    })[0];
    expect(apiKeyInput2.props.value).toBe('sk-test-key');
  });

  it('vlm 未配置时不提示图片理解模型 JSON 未勾选', async () => {
    const llmClient = jest.requireMock('../utils/llm_client') as {
      fetchJsonRequiredModules: jest.Mock;
    };
    llmClient.fetchJsonRequiredModules.mockResolvedValueOnce({
      llm: [],
      vlm: ['B站动态解析'],
    });
    const Alert = (jest.requireMock('react-native') as {
      Alert: { alert: jest.Mock };
    }).Alert;
    const onClose = jest.fn();
    let tree: ReactTestRenderer | undefined;

    await act(async () => {
      tree = renderer.create(<LlmSettingsScreen onClose={onClose} />);
    });
    await act(async () => {
      await Promise.resolve();
    });

    // 只填对话 key，不配置图片理解模型
    const apiKeyInput = tree!.root.findAllByProps({
      placeholder: '粘贴对话服务商的 API Key',
    })[0];
    await act(async () => {
      apiKeyInput.props.onChangeText('sk-text');
    });

    const saveText = tree!.root.findAll(
      (node) => node.props.children === '保存设置',
    )[0];
    const saveButton = saveText.parent!;
    await act(async () => {
      await saveButton.props.onPress();
    });
    await act(async () => {
      await Promise.resolve();
    });

    expect(onClose).toHaveBeenCalled();
    const alertTitles = Alert.alert.mock.calls.map((call) => String(call[0]));
    expect(alertTitles).not.toContain('提示');
  });
});

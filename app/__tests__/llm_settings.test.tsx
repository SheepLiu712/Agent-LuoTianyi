/**
 * LlmSettingsScreen 单页模块列表测试：
 * 模块派生/标题、加载回填、开关保留值、预检、统一校验（batchId）与整体写入。
 */
import React from 'react';
import renderer, { act, ReactTestRenderer } from 'react-test-renderer';

const secureStoreBacking: Record<string, string> =
  ((globalThis as { __testSecureStoreBacking?: Record<string, string> })
    .__testSecureStoreBacking ??= {});

const mockSecureStore = {
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

const mockPresets = [
  {
    name: 'DeepSeek',
    base_url: 'https://api.deepseek.com/v1',
    llm_models: ['deepseek-v4-flash'],
    vlm_models: ['deepseek-vl'],
  },
  {
    name: 'AudioOnly',
    base_url: 'https://audio.example.com/v1',
    llm_models: [],
    vlm_models: [],
    audio_models: ['audio-1'],
  },
];

const mockCapabilities = {
  llmModelCapabilities: {
    'deepseek-v4-flash': { can_enable_thinking: false, can_use_json: false },
  },
  vlmModelCapabilities: {
    'deepseek-vl': { can_enable_thinking: false, can_use_json: true },
  },
};

const mockFetchModelsList = jest.fn(async () => ['deepseek-v4-flash']);

jest.mock('expo-secure-store', () => mockSecureStore);
jest.mock('expo-clipboard', () => ({
  getStringAsync: jest.fn(async () => 'sk-clipboard'),
}));
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
    Keyboard: {
      addListener: jest.fn(() => ({ remove: jest.fn() })),
      dismiss: jest.fn(),
    },
    ActivityIndicator: stub('ActivityIndicator'),
    Alert: { alert: jest.fn() },
    View: stub('View'),
    Text: stub('Text'),
    TextInput: stub('TextInput'),
    TouchableOpacity: stub('TouchableOpacity'),
    ScrollView: stub('ScrollView'),
    Modal: stub('Modal'),
    KeyboardAvoidingView: stub('KeyboardAvoidingView'),
    Switch: stub('Switch'),
  };
});
jest.mock('../config', () => ({
  server_config: { BASE_URL: 'https://server.example.com' },
}));
jest.mock('../utils/llm_client', () => ({
  fetchProviderPresets: jest.fn(async () => ({
    providers: mockPresets,
    ...mockCapabilities,
  })),
  fetchJsonRequiredModules: jest.fn(async () => ({ llm: ['记忆写入'], vlm: [] })),
  fetchModelsList: mockFetchModelsList,
}));

import LlmSettingsScreen from '../app/llm_settings';

const seedConfig = async (cfg: Record<string, unknown>) => {
  await mockSecureStore.setItemAsync(
    'llm_modules_config',
    JSON.stringify(cfg),
  );
};

async function renderScreen(): Promise<ReactTestRenderer> {
  let tree!: ReactTestRenderer;
  await act(async () => {
    tree = renderer.create(<LlmSettingsScreen onClose={jest.fn()} />);
  });
  for (let i = 0; i < 6; i += 1) {
    await act(async () => {
      await Promise.resolve();
    });
  }
  return tree;
}

function pressLabel(tree: ReactTestRenderer, label: string) {
  const textNode = tree.root.findAll((node) => node.props?.children === label)[0];
  expect(textNode).toBeTruthy();
  let node = textNode.parent;
  while (node && !node.props?.onPress) {
    node = node.parent;
  }
  expect(node).toBeTruthy();
  if (!node) {
    throw new Error(`no pressable found for label: ${label}`);
  }
  act(() => {
    node.props.onPress();
  });
}

function switches(tree: ReactTestRenderer) {
  const RN = jest.requireMock('react-native') as { Switch: unknown };
  return tree.root.findAllByType(RN.Switch as never);
}

function textInputs(tree: ReactTestRenderer) {
  const RN = jest.requireMock('react-native') as { TextInput: unknown };
  return tree.root.findAllByType(RN.TextInput as never);
}

function moduleConfigWrites(): number {
  return mockSecureStore.setItemAsync.mock.calls.filter(
    (call) => call[0] === 'llm_modules_config',
  ).length;
}

describe('LlmSettingsScreen 单页模块列表', () => {
  const Alert = (jest.requireMock('react-native') as {
    Alert: { alert: jest.Mock };
  }).Alert;

  beforeEach(() => {
    mockSecureStore.__reset();
    jest.clearAllMocks();
    mockFetchModelsList.mockImplementation(async () => ['deepseek-v4-flash']);
  });

  it('模块由 providers 字段派生，标题取映射或字段名', async () => {
    const tree = await renderScreen();
    expect(
      tree.root.findAllByProps({ children: '对话模型' }).length,
    ).toBeGreaterThanOrEqual(1);
    expect(
      tree.root.findAllByProps({ children: '图片理解模型' }).length,
    ).toBeGreaterThanOrEqual(1);
    // 未映射新字段回退显示字段名
    expect(
      tree.root.findAllByProps({ children: 'audio_models' }).length,
    ).toBeGreaterThanOrEqual(1);
  });

  it('空存储：开关全关、无自动选择', async () => {
    const tree = await renderScreen();
    for (const node of switches(tree)) {
      expect(node.props.value).toBe(false);
    }
    // 开关关闭时字段整体隐藏，无“选择服务商”占位
    expect(tree.root.findAllByProps({ children: '选择服务商' }).length).toBe(0);
  });

  it('加载回填保存值（开关/服务商/模型/Key），不清空', async () => {
    await seedConfig({
      llm_models: {
        enabled: true,
        provider: 'DeepSeek',
        model: 'deepseek-v4-flash',
        baseUrl: 'https://api.deepseek.com/v1',
        apiKey: 'sk-saved',
        paramsText: '{"temperature": 0.7}',
      },
    });
    const tree = await renderScreen();
    expect(switches(tree)[0].props.value).toBe(true);
    expect(tree.root.findAllByProps({ children: 'DeepSeek' }).length).toBeGreaterThan(0);
    expect(tree.root.findAllByProps({ children: 'deepseek-v4-flash' }).length).toBeGreaterThan(0);
    const keyInput = tree.root.findAllByProps({ placeholder: '粘贴 API Key' })[0];
    expect(keyInput.props.value).toBe('sk-saved');
  });

  it('关闭开关隐藏字段但保留值，重新开启恢复', async () => {
    const tree = await renderScreen();
    act(() => {
      switches(tree)[0].props.onValueChange(true);
    });
    const keyInput = tree.root.findAllByProps({ placeholder: '粘贴 API Key' })[0];
    act(() => {
      keyInput.props.onChangeText('sk-test');
    });
    expect(
      tree.root.findAllByProps({ placeholder: '粘贴 API Key' }).length,
    ).toBeGreaterThanOrEqual(1);
    act(() => {
      switches(tree)[0].props.onValueChange(false);
    });
    expect(tree.root.findAllByProps({ placeholder: '粘贴 API Key' }).length).toBe(0);
    act(() => {
      switches(tree)[0].props.onValueChange(true);
    });
    expect(
      tree.root.findAllByProps({ placeholder: '粘贴 API Key' })[0].props.value,
    ).toBe('sk-test');
  });

  it('预检：缺少 API Key 弹窗提示且不写入', async () => {
    await seedConfig({
      llm_models: {
        enabled: true,
        provider: 'DeepSeek',
        model: 'deepseek-v4-flash',
        baseUrl: 'https://api.deepseek.com/v1',
        apiKey: '',
        paramsText: '',
      },
    });
    const tree = await renderScreen();
    pressLabel(tree, '保存');
    await act(async () => {
      await Promise.resolve();
    });
    expect(Alert.alert).toHaveBeenCalledWith(
      '配置不完整',
      expect.stringContaining('缺少 API Key'),
    );
    expect(moduleConfigWrites()).toBe(1); // 仅种子写入，预检未写
  });

  it('预检：高级参数非法 JSON 弹窗提示', async () => {
    await seedConfig({
      llm_models: {
        enabled: true,
        provider: 'DeepSeek',
        model: 'deepseek-v4-flash',
        baseUrl: 'https://api.deepseek.com/v1',
        apiKey: 'sk-test',
        paramsText: '',
      },
    });
    const tree = await renderScreen();
    const inputs = textInputs(tree);
    const params = inputs[inputs.length - 1];
    act(() => {
      params.props.onChangeText('{bad json');
    });
    pressLabel(tree, '保存');
    await act(async () => {
      await Promise.resolve();
    });
    expect(Alert.alert).toHaveBeenCalledWith(
      '配置不完整',
      expect.stringContaining('JSON'),
    );
  });

  it('校验通过后整体写入（含关闭模块），显示成功提示', async () => {
    await seedConfig({
      llm_models: {
        enabled: true,
        provider: 'DeepSeek',
        model: 'deepseek-v4-flash',
        baseUrl: 'https://api.deepseek.com/v1',
        apiKey: 'sk-test',
        paramsText: '',
      },
    });
    const tree = await renderScreen();
    pressLabel(tree, '保存');
    await act(async () => {
      await Promise.resolve();
    });
    expect(mockFetchModelsList).toHaveBeenCalled();
    expect(secureStoreBacking['llm_modules_config']).toBeTruthy();
    const saved = JSON.parse(secureStoreBacking['llm_modules_config']) as Record<
      string,
      { enabled: boolean; provider: string; apiKey: string }
    >;
    expect(saved.llm_models.enabled).toBe(true);
    expect(saved.llm_models.apiKey).toBe('sk-test');
    // 未开启模块也一并写入
    expect(saved.audio_models.enabled).toBe(false);
    expect(tree.root.findAllByProps({ children: '配置已保存' }).length).toBeGreaterThanOrEqual(1);
  });

  it('校验失败（Key 无效）不写入并提示模块', async () => {
    await seedConfig({
      llm_models: {
        enabled: true,
        provider: 'DeepSeek',
        model: 'deepseek-v4-flash',
        baseUrl: 'https://api.deepseek.com/v1',
        apiKey: 'bad-key',
        paramsText: '',
      },
    });
    mockFetchModelsList.mockRejectedValue(new Error('HTTP 401'));
    const tree = await renderScreen();
    pressLabel(tree, '保存');
    await act(async () => {
      await Promise.resolve();
    });
    expect(Alert.alert).toHaveBeenCalledWith(
      '配置校验失败',
      expect.stringContaining('对话模型'),
    );
    expect(moduleConfigWrites()).toBe(1); // 仅种子写入，校验失败未写
  });

  it('模型不在服务商列表时判定不可用', async () => {
    await seedConfig({
      llm_models: {
        enabled: true,
        provider: 'DeepSeek',
        model: 'ghost-model',
        baseUrl: 'https://api.deepseek.com/v1',
        apiKey: 'sk-test',
        paramsText: '',
      },
    });
    const tree = await renderScreen();
    pressLabel(tree, '保存');
    await act(async () => {
      await Promise.resolve();
    });
    expect(Alert.alert).toHaveBeenCalledWith(
      '配置校验失败',
      expect.stringContaining('模型不可用'),
    );
    expect(moduleConfigWrites()).toBe(1);
  });

  it('取消校验使过期批次丢弃，不写入', async () => {
    await seedConfig({
      llm_models: {
        enabled: true,
        provider: 'DeepSeek',
        model: 'deepseek-v4-flash',
        baseUrl: 'https://api.deepseek.com/v1',
        apiKey: 'sk-test',
        paramsText: '',
      },
    });
    let resolveModels!: (value: string[]) => void;
    mockFetchModelsList.mockImplementation(
      () =>
        new Promise<string[]>((resolve) => {
          resolveModels = resolve;
        }),
    );
    const tree = await renderScreen();
    pressLabel(tree, '保存');
    await act(async () => {
      await Promise.resolve();
    });
    pressLabel(tree, '取消');
    await act(async () => {
      resolveModels(['deepseek-v4-flash']);
    });
    expect(moduleConfigWrites()).toBe(1);
  });
});

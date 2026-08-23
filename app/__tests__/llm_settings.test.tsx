/**
 * LlmSettingsScreen 按类型卡片测试：
 * 类型渲染/描述、加载回填、开关保留值、预检、统一校验（batchId）与整体写入。
 */
import React from 'react';
import renderer, { act, ReactTestRenderer, ReactTestInstance } from 'react-test-renderer';

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

const mockTypes = [
  {
    type: '对话模型',
    description: '对话说明',
    providers: [
      {
        name: 'DeepSeek',
        base_url: 'https://api.deepseek.com/v1',
        models: [
          {
            id: 'deepseek-v4-flash',
            can_enable_thinking: false,
            can_use_json: true,
          },
        ],
      },
    ],
  },
  {
    type: '图片理解模型',
    description: '图片说明',
    providers: [
      {
        name: 'VlmOnly',
        base_url: 'https://v.example.com/v1',
        models: [
          {
            id: 'deepseek-vl',
            can_enable_thinking: false,
            can_use_json: false,
          },
        ],
      },
    ],
  },
];

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
    const Comp = (props: Record<string, unknown>) =>
      React.createElement('View', props);
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
  fetchClientModelTypes: jest.fn(async () => ({ types: mockTypes })),
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
  const textNode = tree.root.findAll((node: ReactTestInstance) => node.props?.children === label)[0];
  expect(textNode).toBeTruthy();
  let node: ReactTestInstance | null = textNode.parent;
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

describe('LlmSettingsScreen 按类型卡片', () => {
  const Alert = (jest.requireMock('react-native') as {
    Alert: { alert: jest.Mock };
  }).Alert;

  beforeEach(() => {
    mockSecureStore.__reset();
    jest.clearAllMocks();
    mockFetchModelsList.mockImplementation(async () => ['deepseek-v4-flash']);
  });

  it('按服务端类型渲染卡片与填写说明', async () => {
    const tree = await renderScreen();
    expect(
      tree.root.findAllByProps({ children: '对话模型' }).length,
    ).toBeGreaterThanOrEqual(1);
    expect(
      tree.root.findAllByProps({ children: '图片理解模型' }).length,
    ).toBeGreaterThanOrEqual(1);
    expect(
      tree.root.findAllByProps({ children: '对话说明' }).length,
    ).toBeGreaterThanOrEqual(1);
  });

  it('空存储：开关全关、无自动选择', async () => {
    const tree = await renderScreen();
    for (const node of switches(tree)) {
      expect(node.props.value).toBe(false);
    }
    expect(tree.root.findAllByProps({ children: '选择服务商' }).length).toBe(0);
  });

  it('加载回填保存值（开关/服务商/模型/Key），不清空', async () => {
    await seedConfig({
      对话模型: {
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
    expect(
      tree.root.findAllByProps({ children: 'DeepSeek' }).length,
    ).toBeGreaterThan(0);
    expect(
      tree.root.findAllByProps({ children: 'deepseek-v4-flash' }).length,
    ).toBeGreaterThan(0);
    const keyInput = tree.root.findAllByProps({ placeholder: '粘贴 API Key' })[0];
    expect(keyInput.props.value).toBe('sk-saved');
  });

  it('已选服务商显示服务商地址提示', async () => {
    await seedConfig({
      对话模型: {
        enabled: true,
        provider: 'DeepSeek',
        model: 'deepseek-v4-flash',
        baseUrl: 'https://api.deepseek.com/v1',
        apiKey: '',
        paramsText: '',
      },
    });
    const tree = await renderScreen();
    const hintNodes = tree.root.findAll(
      (n: ReactTestInstance) =>
        Array.isArray(n.props?.children) &&
        n.props.children[0] === '服务商地址：',
    );
    expect(hintNodes.length).toBeGreaterThanOrEqual(1);
    expect(hintNodes[0].props.children.join('')).toBe(
      '服务商地址：https://api.deepseek.com/v1',
    );
  });

  it('点击返回按钮关闭设置页', async () => {
    const onClose = jest.fn();
    let tree!: ReactTestRenderer;
    await act(async () => {
      tree = renderer.create(<LlmSettingsScreen onClose={onClose} />);
    });
    for (let i = 0; i < 6; i += 1) {
      await act(async () => {
        await Promise.resolve();
      });
    }
    pressLabel(tree, '‹ 返回');
    expect(onClose).toHaveBeenCalled();
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
      对话模型: {
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
      对话模型: {
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

  it('校验通过后整体写入（含未开启类型），能力勾选随模型保存', async () => {
    await seedConfig({
      对话模型: {
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
      {
        enabled: boolean;
        provider: string;
        apiKey: string;
        modelCapabilities: { can_enable_thinking: boolean; can_use_json: boolean };
      }
    >;
    expect(saved['对话模型'].enabled).toBe(true);
    expect(saved['对话模型'].apiKey).toBe('sk-test');
    expect(saved['对话模型'].modelCapabilities).toEqual({
      can_enable_thinking: false,
      can_use_json: true,
    });
    // 未开启类型也一并写入
    expect(saved['图片理解模型'].enabled).toBe(false);
    expect(Alert.alert).toHaveBeenCalledWith('保存成功', '配置已保存');
  });

  it('保存时服务商在列表则自动更新 baseUrl', async () => {
    await seedConfig({
      对话模型: {
        enabled: true,
        provider: 'DeepSeek',
        model: 'deepseek-v4-flash',
        baseUrl: 'https://stale.example.com/v1',
        apiKey: 'sk-test',
        paramsText: '',
      },
    });
    const tree = await renderScreen();
    pressLabel(tree, '保存');
    await act(async () => {
      await Promise.resolve();
    });
    const saved = JSON.parse(
      secureStoreBacking['llm_modules_config'],
    ) as Record<string, { baseUrl: string }>;
    expect(saved['对话模型'].baseUrl).toBe('https://api.deepseek.com/v1');
  });

  it('校验失败（Key 无效）不写入并提示类型', async () => {
    await seedConfig({
      对话模型: {
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
      对话模型: {
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
      对话模型: {
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

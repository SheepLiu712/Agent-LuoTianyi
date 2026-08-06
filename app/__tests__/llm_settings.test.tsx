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
  };
});
jest.mock('../config', () => ({
  LLM_CONFIG_STORAGE_KEY: 'llm_config',
  VLM_CONFIG_STORAGE_KEY: 'vlm_config',
  server_config: { BASE_URL: 'https://server.example.com' },
}));

const mockPresets = [
  {
    name: 'DeepSeek',
    base_url: 'https://api.deepseek.com/v1',
    models: ['deepseek-v4-flash'],
    vlm_models: ['deepseek-vl'],
  },
];

// 预置对话模块整份配置（单次 SecureStore 写入）
const seedLlmConfig = async (
  cfg: Partial<{
    apiKey: string;
    provider: string;
    model: string;
    baseUrl: string;
  }> = {},
) => {
  await mockSecureStore.setItemAsync(
    'llm_config',
    JSON.stringify({
      apiKey: cfg.apiKey ?? '',
      provider: cfg.provider ?? 'DeepSeek',
      model: cfg.model ?? 'deepseek-v4-flash',
      baseUrl: cfg.baseUrl ?? 'https://api.deepseek.com/v1',
      paramsText: '',
      enableThinking: false,
      useJson: false,
    }),
  );
};

const getSavedLlmConfig = async (): Promise<Record<string, unknown>> => {
  const raw = await mockSecureStore.getItemAsync('llm_config');
  return raw ? JSON.parse(raw) : {};
};

jest.mock('../utils/llm_client', () => ({
  fetchProviderPresets: jest.fn(async () => ({
    providers: mockPresets,
    llmModelCapabilities: {},
    vlmModelCapabilities: {},
  })),
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
    const Alert = (jest.requireMock('react-native') as {
      Alert: { alert: jest.Mock };
    }).Alert;
    const onClose = jest.fn();
    let tree: ReactTestRenderer | undefined;

    // 预置已保存的服务商与模型，使对话页三个必填项齐全（直接走校验+保存）
    await seedLlmConfig({});

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

    // 点击“下一步”：配置完整，探测校验通过后保存并进入第 2 页
    const nextText = tree!.root.findAll(
      (node) => node.props.children === '下一步',
    )[0];
    expect(nextText).toBeTruthy();
    await act(async () => {
      await nextText.parent!.props.onPress();
    });
    // 等待保存链路的剩余状态更新（setSaving(false) 等）
    await act(async () => {
      await Promise.resolve();
    });

    // 保存后整份配置已写入 SecureStore（llm_config）
    await expect(getSavedLlmConfig()).resolves.toHaveProperty('apiKey', 'sk-test-key');
    // 保存后进入图片理解页，不关闭设置页
    expect(onClose).not.toHaveBeenCalled();
    expect(Alert.alert).toHaveBeenCalledWith('成功', '对话模型设置已保存');

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

    await seedLlmConfig({});

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

    const nextText = tree!.root.findAll(
      (node) => node.props.children === '下一步',
    )[0];
    await act(async () => {
      await nextText.parent!.props.onPress();
    });
    await act(async () => {
      await Promise.resolve();
    });

    expect(onClose).not.toHaveBeenCalled();
    const alertTitles = Alert.alert.mock.calls.map((call) => String(call[0]));
    expect(alertTitles).not.toContain('提示');
  });

  it('未填 API Key 时弹窗提示将使用服务端 Key，继续后进入下一页', async () => {
    const Alert = (jest.requireMock('react-native') as {
      Alert: { alert: jest.Mock };
    }).Alert;
    const onClose = jest.fn();
    let tree: ReactTestRenderer | undefined;

    // 预置已保存的服务商与模型（网络数据只提供下拉选项，不再自动选中）
    await seedLlmConfig({});

    await act(async () => {
      tree = renderer.create(<LlmSettingsScreen onClose={onClose} />);
    });
    await act(async () => {
      await Promise.resolve();
    });

    // 服务商/模型已回填，仅 key 未填 → 页面常驻提示
    const note = tree!.root.findAll(
      (node) =>
        node.props.children ===
        '未配置 API Key，相关调用将使用服务端 Key。',
    )[0];
    expect(note).toBeTruthy();

    // 点击“下一步”弹窗确认
    const nextText = tree!.root.findAll(
      (node) => node.props.children === '下一步',
    )[0];
    await act(async () => {
      await nextText.parent!.props.onPress();
    });
    await act(async () => {
      await Promise.resolve();
    });

    const promptCall = Alert.alert.mock.calls.find(
      (call) => call[0] === '提示',
    );
    expect(promptCall).toBeTruthy();
    expect(String(promptCall![1])).toContain('服务端 Key');
    await expect(getSavedLlmConfig()).resolves.toHaveProperty('apiKey', '');
    // 不点“继续”即相当于取消：仍留在第 1 页，不保存
    expect(
      tree!.root.findAll((node) => node.props.children === '完成')[0],
    ).toBeFalsy();

    // 再次“下一步”并选择“继续”：进入第 2 页
    const nextText2 = tree!.root.findAll(
      (node) => node.props.children === '下一步',
    )[0];
    await act(async () => {
      await nextText2.parent!.props.onPress();
    });
    await act(async () => {
      await Promise.resolve();
    });
    const promptCall2 =
      Alert.alert.mock.calls[Alert.alert.mock.calls.length - 1];
    const continueBtn = promptCall2[2].find(
      (button: { text: string }) => button.text === '继续',
    );
    await act(async () => {
      continueBtn.onPress();
    });
    await act(async () => {
      await Promise.resolve();
    });

    await expect(getSavedLlmConfig()).resolves.toHaveProperty('apiKey', '');
    expect(
      tree!.root.findAll((node) => node.props.children === '完成')[0],
    ).toBeTruthy();
    expect(onClose).not.toHaveBeenCalled();
  });

  it('列表已加载且旧配置未修改时，直接下一步且不执行保存', async () => {
    const llmClient = jest.requireMock('../utils/llm_client') as {
      probeLlmConfig: jest.Mock;
    };
    const Alert = (jest.requireMock('react-native') as {
      Alert: { alert: jest.Mock };
    }).Alert;
    const onClose = jest.fn();
    let tree: ReactTestRenderer | undefined;

    // 预置完整旧配置（与默认服务商预设一致）
    await seedLlmConfig({ apiKey: 'sk-saved' });

    await act(async () => {
      tree = renderer.create(<LlmSettingsScreen onClose={onClose} />);
    });
    await act(async () => {
      await Promise.resolve();
    });

    const nextText = tree!.root.findAll(
      (node) => node.props.children === '下一步',
    )[0];
    expect(nextText.parent!.props.disabled).toBe(false);

    await act(async () => {
      await nextText.parent!.props.onPress();
    });
    await act(async () => {
      await Promise.resolve();
    });

    // 直接翻页：未探测、未弹窗、key 未动
    expect(
      tree!.root.findAll((node) => node.props.children === '完成')[0],
    ).toBeTruthy();
    expect(llmClient.probeLlmConfig).not.toHaveBeenCalled();
    expect(Alert.alert).not.toHaveBeenCalled();
    await expect(getSavedLlmConfig()).resolves.toHaveProperty('apiKey', 'sk-saved');
    expect(onClose).not.toHaveBeenCalled();
  });

  it('清除失败时不继续导航，可取消重试且不破坏现有配置', async () => {
    const Alert = (jest.requireMock('react-native') as {
      Alert: { alert: jest.Mock };
    }).Alert;
    const onClose = jest.fn();
    let tree: ReactTestRenderer | undefined;

    await seedLlmConfig({});

    await act(async () => {
      tree = renderer.create(<LlmSettingsScreen onClose={onClose} />);
    });
    await act(async () => {
      await Promise.resolve();
    });

    // key 为空 → 下一步 → 弹窗 → 继续（触发清除）
    const nextText = tree!.root.findAll(
      (node) => node.props.children === '下一步',
    )[0];
    await act(async () => {
      await nextText.parent!.props.onPress();
    });
    await act(async () => {
      await Promise.resolve();
    });
    const promptCall = Alert.alert.mock.calls.find(
      (call) => call[0] === '提示',
    );
    const continueBtn = promptCall![2].find(
      (button: { text: string }) => button.text === '继续',
    );

    // 清除失败
    mockSecureStore.setItemAsync.mockRejectedValueOnce(new Error('disk full'));
    await act(async () => {
      continueBtn.onPress();
    });
    await act(async () => {
      await Promise.resolve();
    });

    // 弹清除失败提示，未导航
    const failCall = Alert.alert.mock.calls.find(
      (call) => call[0] === '清除失败',
    );
    expect(failCall).toBeTruthy();
    expect(
      tree!.root.findAll((node) => node.props.children === '完成')[0],
    ).toBeFalsy();
    expect(onClose).not.toHaveBeenCalled();
    // 不点“重试”即放弃：留在本页；失败写入未生效，现有配置保持原样
    await expect(getSavedLlmConfig()).resolves.toHaveProperty('provider', 'DeepSeek');
  });

  it('粘贴按钮随输入值切换为清空/粘贴', async () => {
    const onClose = jest.fn();
    let tree: ReactTestRenderer | undefined;

    await act(async () => {
      tree = renderer.create(<LlmSettingsScreen onClose={onClose} />);
    });
    await act(async () => {
      await Promise.resolve();
    });

    // 初始无值：显示“粘贴”
    expect(
      tree!.root.findAll((node) => node.props.children === '粘贴')[0],
    ).toBeTruthy();

    const apiKeyInput = tree!.root.findAllByProps({
      placeholder: '粘贴对话服务商的 API Key',
    })[0];
    await act(async () => {
      apiKeyInput.props.onChangeText('sk-x');
    });
    await act(async () => {
      await Promise.resolve();
    });
    expect(
      tree!.root.findAll((node) => node.props.children === '清空')[0],
    ).toBeTruthy();

    // 点击“清空”后输入框清空，按钮恢复“粘贴”
    const clearText = tree!.root.findAll(
      (node) => node.props.children === '清空',
    )[0];
    await act(async () => {
      await clearText.parent!.props.onPress();
    });
    await act(async () => {
      await Promise.resolve();
    });
    expect(apiKeyInput.props.value).toBe('');
    expect(
      tree!.root.findAll((node) => node.props.children === '粘贴')[0],
    ).toBeTruthy();
  });

  it('点击刷新会重新拉取服务商与 JSON 功能列表', async () => {
    const llmClient = jest.requireMock('../utils/llm_client') as {
      fetchProviderPresets: jest.Mock;
      fetchJsonRequiredModules: jest.Mock;
    };
    const onClose = jest.fn();
    let tree: ReactTestRenderer | undefined;

    await act(async () => {
      tree = renderer.create(<LlmSettingsScreen onClose={onClose} />);
    });
    await act(async () => {
      await Promise.resolve();
    });
    expect(llmClient.fetchProviderPresets).toHaveBeenCalledTimes(1);

    const refreshText = tree!.root.findAll(
      (node) => node.props.children === '刷新',
    )[0];
    expect(refreshText).toBeTruthy();
    await act(async () => {
      await refreshText.parent!.props.onPress();
    });
    await act(async () => {
      await Promise.resolve();
    });

    expect(llmClient.fetchProviderPresets).toHaveBeenCalledTimes(2);
    expect(llmClient.fetchJsonRequiredModules).toHaveBeenCalledTimes(2);
  });

  it('纯 VLM 服务商不被全量过滤，图片理解页可渲染', async () => {
    const llmClient = jest.requireMock('../utils/llm_client') as {
      fetchProviderPresets: jest.Mock;
    };
    llmClient.fetchProviderPresets.mockResolvedValueOnce({
      providers: [
        {
          name: 'DeepSeek',
          base_url: 'https://api.deepseek.com/v1',
          models: ['deepseek-v4-flash'],
          vlm_models: [],
        },
        {
          name: 'VlmOnly',
          base_url: 'https://vlm.example.com/v1',
          models: [],
          vlm_models: ['vlm-model'],
        },
      ],
      llmModelCapabilities: {},
      vlmModelCapabilities: {},
    });
    const onClose = jest.fn();
    let tree: ReactTestRenderer | undefined;

    await seedLlmConfig({ apiKey: 'sk-saved' });
    await act(async () => {
      tree = renderer.create(<LlmSettingsScreen onClose={onClose} />);
    });
    await act(async () => {
      await Promise.resolve();
    });

    // 对话页：纯 VLM 服务商不出现，普通对话服务商出现
    expect(
      tree!.root.findAll((node) => node.props.children === 'VlmOnly')[0],
    ).toBeFalsy();
    expect(
      tree!.root.findAll((node) => node.props.children === 'DeepSeek')[0],
    ).toBeTruthy();

    // 下一步（配置未修改 → 直接翻页）进入图片理解页：纯 VLM 服务商出现
    const nextText = tree!.root.findAll(
      (node) => node.props.children === '下一步',
    )[0];
    await act(async () => {
      await nextText.parent!.props.onPress();
    });
    await act(async () => {
      await Promise.resolve();
    });
    expect(
      tree!.root.findAll((node) => node.props.children === 'VlmOnly')[0],
    ).toBeTruthy();
  });

  it('探测失败时显示友好错误提示且不保存', async () => {
    const llmClient = jest.requireMock('../utils/llm_client') as {
      probeLlmConfig: jest.Mock;
    };
    llmClient.probeLlmConfig.mockRejectedValueOnce(new Error('401 Unauthorized'));
    const Alert = (jest.requireMock('react-native') as {
      Alert: { alert: jest.Mock };
    }).Alert;
    const onClose = jest.fn();
    let tree: ReactTestRenderer | undefined;

    await seedLlmConfig({});
    await act(async () => {
      tree = renderer.create(<LlmSettingsScreen onClose={onClose} />);
    });
    await act(async () => {
      await Promise.resolve();
    });

    const apiKeyInput = tree!.root.findAllByProps({
      placeholder: '粘贴对话服务商的 API Key',
    })[0];
    await act(async () => {
      apiKeyInput.props.onChangeText('sk-bad');
    });

    const nextText = tree!.root.findAll(
      (node) => node.props.children === '下一步',
    )[0];
    await act(async () => {
      await nextText.parent!.props.onPress();
    });
    await act(async () => {
      await Promise.resolve();
    });

    const failCall = Alert.alert.mock.calls.find(
      (call) => call[0] === '配置校验失败',
    );
    expect(failCall).toBeTruthy();
    expect(String(failCall![1])).toContain('API Key 无效');
    await expect(getSavedLlmConfig()).resolves.toHaveProperty('apiKey', '');
    // 校验失败仍停留在第 1 页
    const doneText = tree!.root.findAll(
      (node) => node.props.children === '完成',
    )[0];
    expect(doneText).toBeFalsy();
  });

  it('校验期间整页遮罩冻结并显示校验中，完成后恢复', async () => {
    const llmClient = jest.requireMock('../utils/llm_client') as {
      probeLlmConfig: jest.Mock;
    };
    const onClose = jest.fn();
    let tree: ReactTestRenderer | undefined;
    let rejectProbe!: (reason?: unknown) => void;

    await seedLlmConfig({});

    await act(async () => {
      tree = renderer.create(<LlmSettingsScreen onClose={onClose} />);
    });
    await act(async () => {
      await Promise.resolve();
    });

    // 探测挂起，模拟校验进行中
    llmClient.probeLlmConfig.mockImplementationOnce(
      () =>
        new Promise<void>((_resolve, reject) => {
          rejectProbe = reject;
        }),
    );

    const apiKeyInput = tree!.root.findAllByProps({
      placeholder: '粘贴对话服务商的 API Key',
    })[0];
    await act(async () => {
      apiKeyInput.props.onChangeText('sk-test');
    });
    await act(async () => {
      await Promise.resolve();
    });

    const nextText = tree!.root.findAll(
      (node) => node.props.children === '下一步',
    )[0];
    await act(async () => {
      await nextText.parent!.props.onPress();
    });
    await act(async () => {
      await Promise.resolve();
    });

    // 校验中：整页遮罩覆盖（含头部返回），并显示“校验中…”
    const overlayText = tree!.root.findAll(
      (node) => node.props.children === '校验中…',
    )[0];
    expect(overlayText).toBeTruthy();

    // 校验结束（失败路径）：遮罩消失，控件未单独冻结
    await act(async () => {
      rejectProbe(new Error('401 Unauthorized'));
    });
    await act(async () => {
      await Promise.resolve();
    });
    expect(
      tree!.root.findAll((node) => node.props.children === '校验中…')[0],
    ).toBeFalsy();
    expect(apiKeyInput.props.editable).not.toBe(false);
  });
});

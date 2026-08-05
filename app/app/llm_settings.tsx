import * as Clipboard from 'expo-clipboard';
import React, { useEffect, useRef, useState } from 'react';
import {
  Alert,
  Keyboard,
  KeyboardAvoidingView,
  Modal,
  Platform,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import AsyncStorage from '@react-native-async-storage/async-storage';
import {
  LLM_PROVIDER_STORAGE_KEY,
  LLM_MODEL_STORAGE_KEY,
  LLM_PROVIDER_BASE_URL_STORAGE_KEY,
  LLM_PARAMS_STORAGE_KEY,
  LLM_ENABLE_THINKING_STORAGE_KEY,
  LLM_USE_JSON_STORAGE_KEY,
  VLM_PROVIDER_STORAGE_KEY,
  VLM_MODEL_STORAGE_KEY,
  VLM_PROVIDER_BASE_URL_STORAGE_KEY,
  VLM_PARAMS_STORAGE_KEY,
  VLM_ENABLE_THINKING_STORAGE_KEY,
  VLM_USE_JSON_STORAGE_KEY,
  server_config,
} from '../config';
import { addDebugTrace } from '../utils/debug_trace';
import {
  fetchJsonRequiredModules,
  fetchProviderPresets,
  probeLlmConfig,
  resolveProviderBaseUrl,
} from '../utils/llm_client';
import type { LlmProviderPreset } from '../utils/llm_client';
import {
  getLlmApiKey,
  setLlmApiKey,
  getVlmApiKey,
  setVlmApiKey,
} from '../utils/llm_key_storage';
import { AppTheme, THEMES } from '../utils/theme';

interface LlmSettingsScreenProps {
  onClose: () => void;
  theme?: AppTheme;
}

type TabKind = 'text' | 'vlm';
type PickerKind = TabKind;

interface LoadedConfigSnapshot {
  llmProvider: string;
  llmModel: string;
  llmApiKey: string;
  llmParams: string;
  llmThinking: boolean;
  llmJson: boolean;
  vlmProvider: string;
  vlmModel: string;
  vlmApiKey: string;
  vlmParams: string;
  vlmThinking: boolean;
  vlmJson: boolean;
}

function friendlyProbeError(name: string, error: unknown): string {
  const text = String(error instanceof Error ? error.message : error).toLowerCase();
  if (/(401|403|unauthorized|invalid api key|api key|authentication|access denied|arrearage)/.test(text)) {
    return `${name}：API Key 无效或没有权限，请检查后重试。`;
  }
  if (/(400|unsupported|invalidparameter)/.test(text)) {
    return `${name}：模型或所选开关不受支持，请更换模型或取消不支持的选项后重试。`;
  }
  if (/(connection|timed out|timeout|network|request failed|resolve)/.test(text)) {
    return `${name}：无法连接服务商，请检查网络后重试。`;
  }
  return `${name}：${error instanceof Error ? error.message : String(error)}`;
}

export default function LlmSettingsScreen({ onClose, theme = THEMES.light }: LlmSettingsScreenProps) {
  const insets = useSafeAreaInsets();
  const scrollRef = useRef<ScrollView>(null);
  const loadedRef = useRef<LoadedConfigSnapshot | null>(null);

  const [providers, setProviders] = useState<LlmProviderPreset[]>([]);
  const [providersError, setProvidersError] = useState('');
  const [llmJsonModules, setLlmJsonModules] = useState<string[]>([]);
  const [vlmJsonModules, setVlmJsonModules] = useState<string[]>([]);
  const [stepIndex, setStepIndex] = useState(0);

  const [llmProvider, setLlmProvider] = useState('');
  const [llmApiKey, setLlmApiKeyState] = useState('');
  const [llmModel, setLlmModel] = useState('');
  const [llmParamsText, setLlmParamsText] = useState('');
  const [llmEnableThinking, setLlmEnableThinking] = useState(false);
  const [llmUseJson, setLlmUseJson] = useState(false);

  const [vlmProvider, setVlmProvider] = useState('');
  const [vlmApiKey, setVlmApiKeyState] = useState('');
  const [vlmModel, setVlmModel] = useState('');
  const [vlmParamsText, setVlmParamsText] = useState('');
  const [vlmEnableThinking, setVlmEnableThinking] = useState(false);
  const [vlmUseJson, setVlmUseJson] = useState(false);

  const [showLlmAdvanced, setShowLlmAdvanced] = useState(false);
  const [showVlmAdvanced, setShowVlmAdvanced] = useState(false);
  const [pickerKind, setPickerKind] = useState<PickerKind | null>(null);
  const [pickerText, setPickerText] = useState('');
  const [keyboardHeight, setKeyboardHeight] = useState(0);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    const showSub = Keyboard.addListener(
      Platform.OS === 'ios' ? 'keyboardWillShow' : 'keyboardDidShow',
      (e) => setKeyboardHeight(e.endCoordinates.height),
    );
    const hideSub = Keyboard.addListener(
      Platform.OS === 'ios' ? 'keyboardWillHide' : 'keyboardDidHide',
      () => setKeyboardHeight(0),
    );
    return () => {
      showSub.remove();
      hideSub.remove();
    };
  }, []);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const [
          provider, model, params,
          vlmProv, vlmMod, vlmParams,
          key, vlmKey,
          llmThinking, llmJson, vlmThinking, vlmJson,
        ] = await Promise.all([
          AsyncStorage.getItem(LLM_PROVIDER_STORAGE_KEY),
          AsyncStorage.getItem(LLM_MODEL_STORAGE_KEY),
          AsyncStorage.getItem(LLM_PARAMS_STORAGE_KEY),
          AsyncStorage.getItem(VLM_PROVIDER_STORAGE_KEY),
          AsyncStorage.getItem(VLM_MODEL_STORAGE_KEY),
          AsyncStorage.getItem(VLM_PARAMS_STORAGE_KEY),
          getLlmApiKey(),
          getVlmApiKey(),
          AsyncStorage.getItem(LLM_ENABLE_THINKING_STORAGE_KEY),
          AsyncStorage.getItem(LLM_USE_JSON_STORAGE_KEY),
          AsyncStorage.getItem(VLM_ENABLE_THINKING_STORAGE_KEY),
          AsyncStorage.getItem(VLM_USE_JSON_STORAGE_KEY),
        ]);
        if (!active) {
          return;
        }
        if (provider) setLlmProvider(provider);
        if (model) setLlmModel(model);
        if (params) setLlmParamsText(params);
        if (vlmProv) setVlmProvider(vlmProv);
        if (vlmMod) setVlmModel(vlmMod);
        if (vlmParams) setVlmParamsText(vlmParams);
        if (key) setLlmApiKeyState(key);
        if (vlmKey) setVlmApiKeyState(vlmKey);
        setLlmEnableThinking(llmThinking === '1' || llmThinking === 'true');
        setLlmUseJson(llmJson === '1' || llmJson === 'true');
        setVlmEnableThinking(vlmThinking === '1' || vlmThinking === 'true');
        setVlmUseJson(vlmJson === '1' || vlmJson === 'true');
        loadedRef.current = {
          llmProvider: provider ?? '',
          llmModel: model ?? '',
          llmApiKey: key ?? '',
          llmParams: params ?? '',
          llmThinking: llmThinking === '1' || llmThinking === 'true',
          llmJson: llmJson === '1' || llmJson === 'true',
          vlmProvider: vlmProv ?? '',
          vlmModel: vlmMod ?? '',
          vlmApiKey: vlmKey ?? '',
          vlmParams: vlmParams ?? '',
          vlmThinking: vlmThinking === '1' || vlmThinking === 'true',
          vlmJson: vlmJson === '1' || vlmJson === 'true',
        };
      } catch (e) {
        addDebugTrace('llm_settings', 'load saved config failed', { error: String(e) });
      }
      try {
        const list = await fetchProviderPresets(server_config.BASE_URL);
        if (!active) {
          return;
        }
        setProvidersError('');
        setProviders(list);
        // 仅 key 为空（未配置）时默认展示首项，方便用户直接填入 key；
        // 已配置则保留已保存选择，网络数据只提供下拉选项
        const snapshot = loadedRef.current;
        if (snapshot && !snapshot.llmApiKey) {
          const first = list[0];
          const nextProvider = snapshot.llmProvider || first?.name || '';
          setLlmProvider(nextProvider);
          const preset = list.find((p) => p.name === nextProvider) ?? null;
          setLlmModel(
            snapshot.llmModel && preset?.models?.includes(snapshot.llmModel)
              ? snapshot.llmModel
              : preset?.models?.[0] || '',
          );
        }
        if (snapshot && !snapshot.vlmApiKey) {
          const firstVlm = list.find((p) => (p.vlm_models?.length ?? 0) > 0);
          const nextProvider = snapshot.vlmProvider || firstVlm?.name || '';
          setVlmProvider(nextProvider);
          const preset = list.find((p) => p.name === nextProvider) ?? null;
          setVlmModel(
            snapshot.vlmModel && preset?.vlm_models?.includes(snapshot.vlmModel)
              ? snapshot.vlmModel
              : preset?.vlm_models?.[0] || '',
          );
        }
      } catch (e) {
        if (!active) {
          return;
        }
        addDebugTrace('llm_settings', 'fetch providers failed', { error: String(e) });
        setProvidersError(
          `获取服务商列表失败：${e instanceof Error ? e.message : String(e)}`,
        );
      }
      try {
        const jsonModules = await fetchJsonRequiredModules(server_config.BASE_URL);
        if (!active) {
          return;
        }
        setLlmJsonModules(jsonModules.llm);
        setVlmJsonModules(jsonModules.vlm);
      } catch (e) {
        if (!active) {
          return;
        }
        addDebugTrace('llm_settings', 'fetch json modules failed', { error: String(e) });
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  const currentPreset = providers.find((p) => p.name === llmProvider) ?? null;
  const currentVlmPreset = providers.find((p) => p.name === vlmProvider) ?? null;
  const vlmProviders = providers.filter((p) => (p.vlm_models?.length ?? 0) > 0);

  const isVlmTab = stepIndex === 1;
  const paramsText = isVlmTab ? vlmParamsText : llmParamsText;
  const setParamsText = isVlmTab ? setVlmParamsText : setLlmParamsText;
  const enableThinking = isVlmTab ? vlmEnableThinking : llmEnableThinking;
  const useJson = isVlmTab ? vlmUseJson : llmUseJson;
  const setEnableThinking = isVlmTab ? setVlmEnableThinking : setLlmEnableThinking;
  const setUseJson = isVlmTab ? setVlmUseJson : setLlmUseJson;
  const pickerProvider = isVlmTab ? currentVlmPreset : currentPreset;
  const pickerList = isVlmTab
    ? (currentVlmPreset?.vlm_models ?? [])
    : (currentPreset?.models ?? []);
  const pickerTitle = isVlmTab ? '选择图片理解模型' : '选择对话模型';
  const advancedVisible = isVlmTab ? showVlmAdvanced : showLlmAdvanced;
  const pageApiKey = (isVlmTab ? vlmApiKey : llmApiKey).trim();
  // 当前页已选中服务商且其模型列表可用时才能继续（未选择或列表未加载则禁用）
  const modelReady = isVlmTab
    ? (currentVlmPreset?.vlm_models?.length ?? 0) > 0
    : (currentPreset?.models?.length ?? 0) > 0;

  const hasUnchangedSaved = (forVlm: boolean): boolean => {
    const saved = loadedRef.current;
    if (!saved) {
      return false;
    }
    if (forVlm) {
      return Boolean(saved.vlmProvider && saved.vlmModel && saved.vlmApiKey)
        && vlmProvider === saved.vlmProvider
        && vlmModel === saved.vlmModel
        && vlmApiKey.trim() === saved.vlmApiKey
        && vlmParamsText.trim() === saved.vlmParams
        && vlmEnableThinking === saved.vlmThinking
        && vlmUseJson === saved.vlmJson;
    }
    return Boolean(saved.llmProvider && saved.llmModel && saved.llmApiKey)
      && llmProvider === saved.llmProvider
      && llmModel === saved.llmModel
      && llmApiKey.trim() === saved.llmApiKey
      && llmParamsText.trim() === saved.llmParams
      && llmEnableThinking === saved.llmThinking
      && llmUseJson === saved.llmJson;
  };

  const canNext = modelReady || hasUnchangedSaved(isVlmTab);

  const scrollToBottom = () => {
    requestAnimationFrame(() => {
      scrollRef.current?.scrollToEnd?.({ animated: true });
    });
  };

  const goStep = (index: number) => {
    setStepIndex(index);
    Keyboard.dismiss();
    requestAnimationFrame(() => {
      scrollRef.current?.scrollTo?.({ y: 0, animated: true });
    });
  };

  const pasteKey = async (setter: (value: string) => void) => {
    try {
      const text = await Clipboard.getStringAsync();
      if (text) {
        setter(text);
      }
    } catch (e) {
      addDebugTrace('llm_settings', 'paste key failed', { error: String(e) });
    }
  };

  const parseParams = (text: string): Record<string, unknown> | null => {
    const trimmed = text.trim();
    if (!trimmed) {
      return {};
    }
    try {
      const parsed = JSON.parse(trimmed);
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
        Alert.alert('提示', '高级参数必须是 JSON 对象');
        return null;
      }
      return parsed as Record<string, unknown>;
    } catch (e) {
      Alert.alert(
        '提示',
        `高级参数不是合法 JSON：${e instanceof Error ? e.message : String(e)}`,
      );
      return null;
    }
  };

  const refreshProviders = async () => {
    try {
      const list = await fetchProviderPresets(server_config.BASE_URL);
      setProvidersError('');
      setProviders(list);
      // 刷新同样只在 key 为空（未配置）时补默认首项，保留已有选择
      const snapshot = loadedRef.current;
      if (snapshot && !snapshot.llmApiKey) {
        const nextProvider = llmProvider || list[0]?.name || '';
        setLlmProvider(nextProvider);
        const preset = list.find((p) => p.name === nextProvider) ?? null;
        setLlmModel(
          llmModel && preset?.models?.includes(llmModel)
            ? llmModel
            : preset?.models?.[0] || '',
        );
      }
      if (snapshot && !snapshot.vlmApiKey) {
        const firstVlm = list.find((p) => (p.vlm_models?.length ?? 0) > 0);
        const nextProvider = vlmProvider || firstVlm?.name || '';
        setVlmProvider(nextProvider);
        const preset = list.find((p) => p.name === nextProvider) ?? null;
        setVlmModel(
          vlmModel && preset?.vlm_models?.includes(vlmModel)
            ? vlmModel
            : preset?.vlm_models?.[0] || '',
        );
      }
      const jsonModules = await fetchJsonRequiredModules(server_config.BASE_URL);
      setLlmJsonModules(jsonModules.llm);
      setVlmJsonModules(jsonModules.vlm);
    } catch (e) {
      addDebugTrace('llm_settings', 'refresh providers failed', {
        error: String(e),
      });
      setProvidersError(
        `获取服务商列表失败：${e instanceof Error ? e.message : String(e)}`,
      );
    }
  };

  const writeModuleConfig = async (
    forVlm: boolean,
    cfg: {
      apiKey: string;
      provider: string;
      model: string;
      baseUrl: string;
      paramsText: string;
      enableThinking: boolean;
      useJson: boolean;
    },
  ) => {
    if (forVlm) {
      await setVlmApiKey(cfg.apiKey);
      await AsyncStorage.setItem(VLM_PROVIDER_STORAGE_KEY, cfg.provider);
      await AsyncStorage.setItem(VLM_MODEL_STORAGE_KEY, cfg.model);
      await AsyncStorage.setItem(VLM_PROVIDER_BASE_URL_STORAGE_KEY, cfg.baseUrl);
      await AsyncStorage.setItem(VLM_PARAMS_STORAGE_KEY, cfg.paramsText);
      await AsyncStorage.setItem(
        VLM_ENABLE_THINKING_STORAGE_KEY,
        cfg.enableThinking ? '1' : '0',
      );
      await AsyncStorage.setItem(VLM_USE_JSON_STORAGE_KEY, cfg.useJson ? '1' : '0');
    } else {
      await setLlmApiKey(cfg.apiKey);
      await AsyncStorage.setItem(LLM_PROVIDER_STORAGE_KEY, cfg.provider);
      await AsyncStorage.setItem(LLM_MODEL_STORAGE_KEY, cfg.model);
      await AsyncStorage.setItem(LLM_PROVIDER_BASE_URL_STORAGE_KEY, cfg.baseUrl);
      await AsyncStorage.setItem(LLM_PARAMS_STORAGE_KEY, cfg.paramsText);
      await AsyncStorage.setItem(
        LLM_ENABLE_THINKING_STORAGE_KEY,
        cfg.enableThinking ? '1' : '0',
      );
      await AsyncStorage.setItem(LLM_USE_JSON_STORAGE_KEY, cfg.useJson ? '1' : '0');
    }
    // 保存后同步快照为存储值，保证“未修改”判断对比的是当前存储而非进入时的值
    loadedRef.current = {
      ...(loadedRef.current ?? {
        llmProvider: '',
        llmModel: '',
        llmApiKey: '',
        llmParams: '',
        llmThinking: false,
        llmJson: false,
        vlmProvider: '',
        vlmModel: '',
        vlmApiKey: '',
        vlmParams: '',
        vlmThinking: false,
        vlmJson: false,
      }),
      ...(forVlm
        ? {
            vlmProvider: cfg.provider,
            vlmModel: cfg.model,
            vlmApiKey: cfg.apiKey,
            vlmParams: cfg.paramsText,
            vlmThinking: cfg.enableThinking,
            vlmJson: cfg.useJson,
          }
        : {
            llmProvider: cfg.provider,
            llmModel: cfg.model,
            llmApiKey: cfg.apiKey,
            llmParams: cfg.paramsText,
            llmThinking: cfg.enableThinking,
            llmJson: cfg.useJson,
          }),
    };
  };

  const clearAndAdvance = async (forVlm: boolean) => {
    try {
      await writeModuleConfig(forVlm, {
        apiKey: '',
        provider: '',
        model: '',
        baseUrl: '',
        paramsText: '',
        enableThinking: false,
        useJson: false,
      });
      // 清除成功才导航
      if (forVlm) {
        onClose();
      } else {
        goStep(1);
      }
    } catch (e) {
      addDebugTrace('llm_settings', 'clear config failed', { error: String(e) });
      Alert.alert('清除失败', '清除配置失败，是否重试？', [
        { text: '取消', style: 'cancel' },
        { text: '重试', onPress: () => { void clearAndAdvance(forVlm); } },
      ]);
    }
  };

  const toggleKeyInput = (forVlm: boolean) => {
    const setter = forVlm ? setVlmApiKeyState : setLlmApiKeyState;
    const hasValue = forVlm
      ? vlmApiKey.trim().length > 0
      : llmApiKey.trim().length > 0;
    if (hasValue) {
      setter('');
    } else {
      void pasteKey(setter);
    }
  };

  const toggleAdvanced = () => {
    if (isVlmTab) {
      setShowVlmAdvanced((v) => !v);
    } else {
      setShowLlmAdvanced((v) => !v);
    }
  };

  const handleNext = () => {
    const forVlm = isVlmTab;
    // 旧配置完整且未修改：任意情况下直接翻页/关闭，不执行保存
    if (hasUnchangedSaved(forVlm)) {
      if (forVlm) {
        onClose();
      } else {
        goStep(1);
      }
      return;
    }
    if (!modelReady) {
      // 服务商未选择或列表未加载：无法保存，保持禁用
      return;
    }
    if (parseParams(forVlm ? vlmParamsText : llmParamsText) === null) {
      return;
    }
    const apiKey = (forVlm ? vlmApiKey : llmApiKey).trim();
    if (apiKey) {
      void handleSave(forVlm);
      return;
    }
    Alert.alert('提示', '未配置 API Key，相关调用将使用服务端 Key。是否继续？', [
      { text: '取消', style: 'cancel' },
      { text: '继续', onPress: () => { void clearAndAdvance(forVlm); } },
    ]);
  };

  const handleSave = async (forVlm: boolean) => {
    const params = parseParams(forVlm ? vlmParamsText : llmParamsText);
    if (params === null) return;

    const name = forVlm ? '图片理解模型' : '对话模型';
    const apiKey = (forVlm ? vlmApiKey : llmApiKey).trim();
    const provider = forVlm ? vlmProvider : llmProvider;
    const model = (forVlm ? vlmModel : llmModel).trim();
    const enableThinking = forVlm ? vlmEnableThinking : llmEnableThinking;
    const useJson = forVlm ? vlmUseJson : llmUseJson;
    const jsonModules = forVlm ? vlmJsonModules : llmJsonModules;
    setSaving(true);
    try {
      const baseUrl = resolveProviderBaseUrl(provider, providers);
      if (apiKey && model && baseUrl) {
        try {
          await probeLlmConfig({
            baseUrl,
            apiKey,
            model,
            flags: { enableThinking, useJson },
            params,
          });
        } catch (e) {
          Alert.alert('配置校验失败', friendlyProbeError(name, e));
          return;
        }
      }
      await writeModuleConfig(forVlm, {
        apiKey,
        provider,
        model,
        baseUrl,
        paramsText: (forVlm ? vlmParamsText : llmParamsText).trim(),
        enableThinking,
        useJson,
      });

      const configured = Boolean(apiKey && provider && model);
      if (configured && !useJson && jsonModules.length > 0) {
        Alert.alert(
          '提示',
          `${name}未勾选“支持 JSON 输出”，以下功能将改用服务端 API 执行：\n${[
            ...new Set(jsonModules),
          ].join('、')}`,
        );
      }

      if (forVlm) {
        onClose();
      } else {
        goStep(1);
      }
    } catch (e) {
      addDebugTrace('llm_settings', 'save failed', { error: String(e) });
      Alert.alert('保存失败', e instanceof Error ? e.message : '网络错误');
    } finally {
      setSaving(false);
    }
  };

  return (
    <View style={[styles.overlayRoot, { backgroundColor: theme.root }]}>
      <KeyboardAvoidingView style={styles.kavFill} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <View style={[styles.container, { paddingTop: insets.top, paddingBottom: insets.bottom, backgroundColor: theme.root }]}>
          <View style={[styles.header, { backgroundColor: theme.surface, borderBottomColor: theme.border }]}>
            <TouchableOpacity style={styles.backButton} onPress={onClose} activeOpacity={0.7}>
              <Text style={[styles.backButtonText, { color: theme.accentText }]}>返回</Text>
            </TouchableOpacity>
            <Text style={[styles.headerTitle, { color: theme.text }]}>LLM 模型设置</Text>
            <View style={styles.headerPlaceholder} />
          </View>

          <View style={styles.stepBar}>
            <Text style={[styles.stepText, { color: theme.text }]}>
              {isVlmTab ? '2 / 2 · 图片理解模型' : '1 / 2 · 对话模型'}
            </Text>
          </View>

          <ScrollView
            ref={scrollRef}
            style={styles.scrollArea}
            contentContainerStyle={[
              styles.scrollContent,
              {
                paddingBottom:
                  Platform.OS === 'android' && keyboardHeight > 0
                    ? keyboardHeight + 16
                    : styles.scrollContent.paddingBottom,
              },
            ]}
            keyboardShouldPersistTaps="handled"
            keyboardDismissMode="on-drag"
          >
            <Text style={[styles.description, { color: theme.textMuted }]}>
              {isVlmTab
                ? '配置图片理解使用的服务商、API Key 与模型；该服务商必须支持图片理解。'
                : '配置对话使用的服务商、API Key 与模型。key 只保存在本机，不会上传服务器。'}
            </Text>
            {!pageApiKey ? (
              <Text style={[styles.configNote, { color: theme.textMuted }]}>
                未配置 API Key，相关调用将使用服务端 Key。
              </Text>
            ) : null}

            <View style={styles.labelRow}>
              <Text style={[styles.label, styles.labelInRow, { color: theme.text }]}>
                服务商
              </Text>
              <TouchableOpacity
                style={styles.refreshButton}
                onPress={() => { void refreshProviders(); }}
                activeOpacity={0.7}
              >
                <Text style={[styles.refreshText, { color: theme.accentText }]}>
                  刷新
                </Text>
              </TouchableOpacity>
            </View>
            <View style={styles.optionRow}>
              {(isVlmTab ? vlmProviders : providers).map((preset) => (
                <TouchableOpacity
                  key={preset.name}
                  style={[
                    styles.chip,
                    { backgroundColor: theme.surface, borderColor: theme.border },
                    (isVlmTab ? vlmProvider : llmProvider) === preset.name && { backgroundColor: theme.accent, borderColor: theme.accent },
                  ]}
                  onPress={() => {
                    if (isVlmTab) {
                      setVlmProvider(preset.name);
                      setVlmModel((prev) =>
                        preset.vlm_models?.includes(prev) ? prev : preset.vlm_models?.[0] || '',
                      );
                    } else {
                      setLlmProvider(preset.name);
                      setLlmModel((prev) =>
                        preset.models?.includes(prev) ? prev : preset.models?.[0] || '',
                      );
                    }
                  }}
                  activeOpacity={0.75}
                >
                  <Text
                    style={[
                      styles.chipText,
                      { color: theme.textSoft },
                      (isVlmTab ? vlmProvider : llmProvider) === preset.name && { color: theme.name === 'dark' ? '#0F1419' : '#ffffff', fontWeight: '700' },
                    ]}
                  >
                    {preset.name}
                  </Text>
                </TouchableOpacity>
              ))}
            </View>
            {providersError ? (
              <Text style={[styles.emptyText, { color: theme.textMuted }]}>
                {providersError}
              </Text>
            ) : providers.length === 0 ? (
              <Text style={[styles.emptyText, { color: theme.textMuted }]}>
                暂无可用的服务商（请确认服务端已配置）
              </Text>
            ) : isVlmTab && vlmProviders.length === 0 ? (
              <Text style={[styles.emptyText, { color: theme.textMuted }]}>
                当前服务端没有支持图片理解的模型
              </Text>
            ) : null}

            <Text style={[styles.label, { color: theme.text }]}>API Key</Text>
            <View style={styles.keyRow}>
              <TextInput
                style={[styles.input, styles.keyInput, { backgroundColor: theme.inputBackground, borderColor: theme.border, color: theme.inputText }]}
                placeholder={isVlmTab ? '粘贴图片理解服务商的 API Key' : '粘贴对话服务商的 API Key'}
                placeholderTextColor={theme.placeholder}
                value={isVlmTab ? vlmApiKey : llmApiKey}
                onChangeText={isVlmTab ? setVlmApiKeyState : setLlmApiKeyState}
                secureTextEntry
                autoCapitalize="none"
                autoCorrect={false}
              />
              <TouchableOpacity
                style={[styles.pasteButton, { backgroundColor: theme.surfaceAlt }]}
                onPress={() => toggleKeyInput(isVlmTab)}
                activeOpacity={0.8}
              >
                <Text style={[styles.pasteButtonText, { color: theme.textSoft }]}>
                  {pageApiKey ? '清空' : '粘贴'}
                </Text>
              </TouchableOpacity>
            </View>

            <Text style={[styles.label, { color: theme.text }]}>模型</Text>
            <TouchableOpacity
              style={[styles.input, { backgroundColor: theme.inputBackground, borderColor: theme.border }]}
              onPress={() => {
                setPickerText('');
                setPickerKind(isVlmTab ? 'vlm' : 'text');
              }}
              activeOpacity={0.7}
            >
              <Text style={{ color: theme.inputText, fontSize: 15 }} numberOfLines={1}>
                {isVlmTab ? vlmModel || '请选择图片理解模型' : llmModel || '请选择对话模型'}
              </Text>
            </TouchableOpacity>

            {pickerProvider ? (
              <Text style={[styles.hintText, { color: theme.textMuted }]}>
                服务商地址：{pickerProvider.base_url}
              </Text>
            ) : null}

            <Text style={[styles.hintText, { color: theme.textMuted }]}>
              思考：仅模型支持思考参数时勾选；JSON：未勾选时相关功能改用服务端 API。
            </Text>
            <TouchableOpacity
              style={styles.checkboxRow}
              onPress={() => setEnableThinking(!enableThinking)}
              activeOpacity={0.7}
            >
              <View
                style={[
                  styles.checkbox,
                  { borderColor: theme.border },
                  enableThinking && { backgroundColor: theme.accent, borderColor: theme.accent },
                ]}
              >
                {enableThinking && (
                  <Text
                    style={[
                      styles.checkmark,
                      { color: theme.name === 'dark' ? '#0F1419' : '#ffffff' },
                    ]}
                  >
                    ✓
                  </Text>
                )}
              </View>
              <Text style={[styles.checkboxLabel, { color: theme.textSoft }]}>
                支持思考模式
              </Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={styles.checkboxRow}
              onPress={() => setUseJson(!useJson)}
              activeOpacity={0.7}
            >
              <View
                style={[
                  styles.checkbox,
                  { borderColor: theme.border },
                  useJson && { backgroundColor: theme.accent, borderColor: theme.accent },
                ]}
              >
                {useJson && (
                  <Text
                    style={[
                      styles.checkmark,
                      { color: theme.name === 'dark' ? '#0F1419' : '#ffffff' },
                    ]}
                  >
                    ✓
                  </Text>
                )}
              </View>
              <Text style={[styles.checkboxLabel, { color: theme.textSoft }]}>
                支持 JSON 输出
              </Text>
            </TouchableOpacity>

            <TouchableOpacity
              style={[styles.advancedToggle, { backgroundColor: theme.surfaceAlt }]}
              onPress={toggleAdvanced}
              activeOpacity={0.8}
            >
              <Text style={[styles.advancedToggleText, { color: theme.text }]}>
                高级设置{advancedVisible ? '（收起）' : ''}
              </Text>
            </TouchableOpacity>

            {advancedVisible ? (
              <View>
                <Text style={[styles.hintText, { color: theme.textMuted }]}>
                  可选，以 JSON 覆盖请求参数（不同模型参数不同，请按服务商文档填写）
                </Text>
                <TextInput
                  style={[styles.input, styles.paramsInput, { backgroundColor: theme.inputBackground, borderColor: theme.border, color: theme.inputText }]}
                  placeholder='{"temperature": 0.7, "max_tokens": 4096, "top_p": 0.9}'
                  placeholderTextColor={theme.placeholder}
                  value={paramsText}
                  onChangeText={setParamsText}
                  multiline
                  autoCapitalize="none"
                  autoCorrect={false}
                  onFocus={scrollToBottom}
                />
              </View>
            ) : null}

            <View style={styles.buttonRow}>
              {isVlmTab ? (
                <TouchableOpacity
                  style={[
                    styles.prevButton,
                    { backgroundColor: theme.surfaceAlt },
                    saving && styles.buttonDisabled,
                  ]}
                  onPress={() => goStep(0)}
                  disabled={saving}
                  activeOpacity={0.8}
                >
                  <Text style={[styles.prevButtonText, { color: theme.textSoft }]}>
                    上一步
                  </Text>
                </TouchableOpacity>
              ) : null}
              <TouchableOpacity
                style={[
                  styles.saveButton,
                  { backgroundColor: theme.accent },
                  (saving || !canNext) && styles.saveButtonDisabled,
                ]}
                onPress={handleNext}
                disabled={saving || !canNext}
                activeOpacity={0.8}
              >
                <Text style={[styles.saveButtonText, { color: theme.name === 'dark' ? '#0F1419' : '#ffffff' }]}>
                  {saving ? '校验中...' : isVlmTab ? '完成' : '下一步'}
                </Text>
              </TouchableOpacity>
            </View>
          </ScrollView>
        </View>
      </KeyboardAvoidingView>

      <Modal
        visible={pickerKind !== null}
        transparent
        animationType="slide"
        onRequestClose={() => setPickerKind(null)}
      >
        <View style={styles.modalOverlay}>
          <View style={[styles.modalCard, { backgroundColor: theme.surface }]}>
            <View style={styles.modalHeader}>
              <Text style={[styles.modalTitle, { color: theme.text }]}>{pickerTitle}</Text>
              <TouchableOpacity onPress={() => setPickerKind(null)} activeOpacity={0.7}>
                <Text style={[styles.modalCloseText, { color: theme.accentText }]}>关闭</Text>
              </TouchableOpacity>
            </View>
            <TextInput
              style={[styles.modalInput, { backgroundColor: theme.inputBackground, borderColor: theme.border, color: theme.inputText }]}
              placeholder="搜索模型"
              placeholderTextColor={theme.placeholder}
              value={pickerText}
              onChangeText={setPickerText}
              autoCapitalize="none"
              autoCorrect={false}
            />
            <ScrollView style={styles.modalList} keyboardShouldPersistTaps="handled">
              {pickerList.length === 0 ? (
                <Text style={[styles.modalEmptyText, { color: theme.textMuted }]}>
                  {pickerProvider
                    ? `该服务商未提供${pickerKind === 'vlm' ? '图片理解' : '对话'}模型`
                    : '请先选择服务商'}
                </Text>
              ) : (
                pickerList
                  .filter((m) => m.toLowerCase().includes(pickerText.trim().toLowerCase()))
                  .map((m) => (
                    <TouchableOpacity
                      key={m}
                      style={styles.modelOption}
                      onPress={() => {
                        if (pickerKind === 'vlm') {
                          setVlmModel(m);
                        } else {
                          setLlmModel(m);
                        }
                        setPickerKind(null);
                      }}
                      activeOpacity={0.7}
                    >
                      <Text style={[styles.modelOptionText, { color: theme.text }]} numberOfLines={1}>
                        {m}
                      </Text>
                    </TouchableOpacity>
                  ))
              )}
            </ScrollView>
          </View>
        </View>
      </Modal>
    </View>
  );
}

const styles = StyleSheet.create({
  overlayRoot: {
    ...StyleSheet.absoluteFillObject,
    zIndex: 120,
    backgroundColor: '#f5f7fa',
  },
  kavFill: {
    flex: 1,
  },
  container: {
    flex: 1,
    backgroundColor: '#f5f7fa',
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    paddingVertical: 12,
    backgroundColor: '#ffffff',
    borderBottomWidth: 1,
    borderBottomColor: '#e3e8ee',
  },
  backButton: {
    minWidth: 56,
    paddingVertical: 6,
    paddingRight: 8,
  },
  backButtonText: {
    fontSize: 16,
    color: '#1686b9',
    fontWeight: '600',
  },
  headerTitle: {
    flex: 1,
    textAlign: 'center',
    fontSize: 17,
    fontWeight: '700',
    color: '#243447',
  },
  headerPlaceholder: {
    width: 56,
  },
  stepBar: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 16,
    paddingVertical: 10,
  },
  stepText: {
    fontSize: 14,
    fontWeight: '700',
  },
  scrollArea: {
    flex: 1,
  },
  scrollContent: {
    padding: 20,
    paddingTop: 4,
    paddingBottom: 40,
  },
  description: {
    color: '#65717f',
    fontSize: 13,
    lineHeight: 20,
    marginBottom: 12,
  },
  configNote: {
    fontSize: 12,
    marginBottom: 8,
  },
  label: {
    fontSize: 15,
    fontWeight: '700',
    color: '#344252',
    marginBottom: 10,
    marginTop: 8,
  },
  labelRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginTop: 8,
    marginBottom: 10,
  },
  labelInRow: {
    marginTop: 0,
    marginBottom: 0,
  },
  refreshButton: {
    paddingVertical: 4,
    paddingHorizontal: 8,
  },
  refreshText: {
    fontSize: 14,
    fontWeight: '600',
  },
  optionRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
    marginTop: -4,
    marginBottom: 12,
  },
  chip: {
    backgroundColor: '#ffffff',
    borderRadius: 15,
    paddingHorizontal: 11,
    paddingVertical: 6,
    borderWidth: 1,
    borderColor: '#dfe6ee',
  },
  chipText: {
    fontSize: 13,
    color: '#4b5967',
  },
  emptyText: {
    fontSize: 13,
    marginBottom: 12,
  },
  hintText: {
    fontSize: 12,
    marginTop: 2,
    marginBottom: 8,
  },
  input: {
    backgroundColor: '#ffffff',
    borderRadius: 10,
    paddingHorizontal: 14,
    paddingVertical: 11,
    fontSize: 15,
    color: '#243447',
    marginBottom: 14,
    borderWidth: 1,
    borderColor: '#dfe6ee',
  },
  keyRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginBottom: 14,
  },
  keyInput: {
    flex: 1,
    marginBottom: 0,
  },
  pasteButton: {
    borderRadius: 10,
    paddingHorizontal: 14,
    paddingVertical: 11,
  },
  pasteButtonText: {
    fontSize: 14,
    fontWeight: '600',
  },
  paramsInput: {
    minHeight: 100,
    textAlignVertical: 'top',
  },
  checkboxRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 10,
  },
  checkbox: {
    width: 20,
    height: 20,
    borderRadius: 4,
    borderWidth: 2,
    marginRight: 8,
    justifyContent: 'center',
    alignItems: 'center',
  },
  checkmark: {
    fontSize: 13,
    fontWeight: 'bold',
    lineHeight: 16,
  },
  checkboxLabel: {
    fontSize: 14,
  },
  advancedToggle: {
    borderRadius: 10,
    paddingVertical: 10,
    paddingHorizontal: 14,
    marginBottom: 10,
  },
  advancedToggleText: {
    fontSize: 14,
    fontWeight: '600',
  },
  buttonRow: {
    flexDirection: 'row',
    marginTop: 14,
    gap: 12,
  },
  prevButton: {
    flex: 1,
    backgroundColor: '#e8edf2',
    borderRadius: 10,
    paddingVertical: 14,
    alignItems: 'center',
  },
  prevButtonText: {
    color: '#4b5967',
    fontSize: 15,
    fontWeight: '700',
  },
  saveButton: {
    flex: 1,
    backgroundColor: '#43a65b',
    borderRadius: 10,
    paddingVertical: 14,
    alignItems: 'center',
  },
  saveButtonText: {
    color: '#ffffff',
    fontSize: 15,
    fontWeight: '700',
  },
  buttonDisabled: {
    opacity: 0.5,
  },
  saveButtonDisabled: {
    backgroundColor: '#b8bec6',
    opacity: 0.9,
  },
  modalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.45)',
    justifyContent: 'center',
    paddingHorizontal: 24,
  },
  modalCard: {
    borderRadius: 16,
    padding: 16,
    maxHeight: '75%',
  },
  modalHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 12,
  },
  modalTitle: {
    fontSize: 17,
    fontWeight: '700',
  },
  modalCloseText: {
    fontSize: 15,
    fontWeight: '600',
  },
  modalInput: {
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 9,
    fontSize: 15,
    borderWidth: 1,
    marginBottom: 10,
  },
  modalList: {
    maxHeight: 320,
  },
  modalEmptyText: {
    fontSize: 13,
    paddingVertical: 16,
    textAlign: 'center',
  },
  modelOption: {
    paddingVertical: 11,
    paddingHorizontal: 6,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: '#dfe6ee',
  },
  modelOptionText: {
    fontSize: 14,
  },
});

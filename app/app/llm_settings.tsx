/**
 * LLM 模型设置页：单页垂直模块列表 + 全局保存。
 *
 * 模块列表由 /llm/providers 返回的 provider 能力字段（值为非空列表的字段，
 * 如 llm_models / vlm_models）动态生成，模块 key 即字段名，标题取极简映射
 * 表，未映射字段回退字段名。每个模块用开关控制“使用自己的 API Key”；
 * 保存时先做客户端预检（必填 + 高级参数 JSON），再对开启模块并行
 * GET /v1/models 校验（batchId 防过期），全部通过后一次性写入 SecureStore。
 */

import * as Clipboard from 'expo-clipboard';
import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Keyboard,
  KeyboardAvoidingView,
  Modal,
  Platform,
  ScrollView,
  StyleSheet,
  Switch,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { server_config } from '../config';
import { addDebugTrace } from '../utils/debug_trace';
import {
  fetchJsonRequiredModules,
  fetchModelsList,
  fetchProviderPresets,
} from '../utils/llm_client';
import type { LlmModelCapability, LlmProviderPreset } from '../utils/llm_client';
import {
  getLlmModulesConfig,
  setLlmModulesConfig,
} from '../utils/llm_key_storage';
import type { LlmModulesConfig } from '../utils/llm_key_storage';
import { AppTheme, THEMES } from '../utils/theme';

const MODULE_TITLES: Record<string, string> = {
  llm_models: '对话模型',
  vlm_models: '图片理解模型',
};

const VALIDATION_TIMEOUT_MS = 30000;

/** 模块 key -> 服务端能力/JSON 任务数据来源（数据驱动，非运行时分支判断）。 */
const MODULE_SERVER_SOURCES: Record<
  string,
  { caps: 'llmModelCapabilities' | 'vlmModelCapabilities'; json: 'llm' | 'vlm' }
> = {
  llm_models: { caps: 'llmModelCapabilities', json: 'llm' },
  vlm_models: { caps: 'vlmModelCapabilities', json: 'vlm' },
};

type FieldKey = 'provider' | 'apiKey' | 'model' | 'paramsText';

interface ModuleFormState {
  enabled: boolean;
  provider: string;
  storedProvider: string;
  model: string;
  storedModel: string;
  apiKey: string;
  paramsText: string;
  baseUrl: string;
  notice: string;
  highlight: FieldKey | null;
  showJsonTasks: boolean;
}

interface LlmSettingsScreenProps {
  onClose: () => void;
  theme?: AppTheme;
}

interface PickerTarget {
  moduleKey: string;
  field: 'provider' | 'model';
}

function deriveModuleKeys(providers: LlmProviderPreset[]): string[] {
  const keys: string[] = [];
  for (const provider of providers) {
    for (const [key, value] of Object.entries(provider)) {
      if (Array.isArray(value) && value.length > 0 && !keys.includes(key)) {
        keys.push(key);
      }
    }
  }
  return keys;
}

function moduleTitle(key: string): string {
  return MODULE_TITLES[key] ?? key;
}

function providerField(provider: LlmProviderPreset, key: string): unknown {
  return (provider as unknown as Record<string, unknown>)[key];
}

function friendlyFieldName(field: FieldKey): string {
  switch (field) {
    case 'provider':
      return '服务商';
    case 'apiKey':
      return 'API Key';
    case 'model':
      return '模型';
    case 'paramsText':
      return '高级参数';
  }
}

function OptionPicker({
  visible,
  title,
  options,
  selected,
  onSelect,
  onClose,
}: {
  visible: boolean;
  title: string;
  options: string[];
  selected: string;
  onSelect: (value: string) => void;
  onClose: () => void;
}) {
  return (
    <Modal transparent visible={visible} animationType="fade" onRequestClose={onClose}>
      <View style={styles.pickerMask}>
        <View style={styles.pickerBox}>
          <Text style={styles.pickerTitle}>{title}</Text>
          <ScrollView style={{ maxHeight: 320 }}>
            {options.map((option) => (
              <TouchableOpacity
                key={option}
                onPress={() => onSelect(option)}
                style={[
                  styles.pickerItem,
                  option === selected && styles.pickerItemSelected,
                ]}
              >
                <Text style={styles.pickerItemText}>{option}</Text>
              </TouchableOpacity>
            ))}
          </ScrollView>
          <TouchableOpacity onPress={onClose} style={styles.pickerCancel}>
            <Text style={styles.pickerCancelText}>取消</Text>
          </TouchableOpacity>
        </View>
      </View>
    </Modal>
  );
}

export default function LlmSettingsScreen({
  onClose,
  theme = THEMES.light,
}: LlmSettingsScreenProps) {
  const insets = useSafeAreaInsets();
  const scrollRef = useRef<ScrollView>(null);
  const cardYRef = useRef<Record<string, number>>({});
  const batchRef = useRef(0);

  const [providers, setProviders] = useState<LlmProviderPreset[]>([]);
  const [moduleKeys, setModuleKeys] = useState<string[]>([]);
  const [forms, setForms] = useState<Record<string, ModuleFormState>>({});
  const [moduleCaps, setModuleCaps] = useState<
    Record<string, Record<string, LlmModelCapability>>
  >({});
  const [moduleJsonLabels, setModuleJsonLabels] = useState<Record<string, string[]>>(
    {},
  );
  const [providersLoaded, setProvidersLoaded] = useState(false);
  const [providersError, setProvidersError] = useState('');
  const [saving, setSaving] = useState(false);
  const [successMsg, setSuccessMsg] = useState('');
  const [picker, setPicker] = useState<PickerTarget | null>(null);

  const capsFor = useCallback(
    (key: string): Record<string, LlmModelCapability> =>
      moduleCaps[key] ?? {},
    [moduleCaps],
  );

  const jsonLabelsFor = useCallback(
    (key: string): string[] => moduleJsonLabels[key] ?? [],
    [moduleJsonLabels],
  );

  const presetsFor = useCallback(
    (key: string): LlmProviderPreset[] =>
      providers.filter(
        (p) =>
          Array.isArray(providerField(p, key)) &&
          (providerField(p, key) as string[]).length > 0,
      ),
    [providers],
  );

  const loadForms = useCallback(
    async (providerList: LlmProviderPreset[], keys: string[]) => {
      const stored = await getLlmModulesConfig();
      const next: Record<string, ModuleFormState> = {};
      for (const key of keys) {
        const saved = stored[key];
        const presets = providerList.filter(
          (p) =>
            Array.isArray(providerField(p, key)) &&
            (providerField(p, key) as string[]).length > 0,
        );
        let provider = saved?.provider ?? '';
        let storedProvider = '';
        let notice = '';
        if (provider && !presets.some((p) => p.name === provider)) {
          storedProvider = provider;
          notice = `注意：服务商 '${provider}' 已不在列表中`;
        }
        const preset = presets.find((p) => p.name === provider) ?? null;
        let model = saved?.model ?? '';
        let storedModel = '';
        if (
          model &&
          !(preset && (providerField(preset, key) as string[]).includes(model))
        ) {
          storedModel = model;
          model = '';
        }
        next[key] = {
          enabled: Boolean(saved?.enabled),
          provider,
          storedProvider,
          model,
          storedModel,
          apiKey: saved?.apiKey ?? '',
          paramsText: saved?.paramsText ?? '',
          baseUrl: saved?.baseUrl ?? preset?.base_url ?? '',
          notice,
          highlight: null,
          showJsonTasks: false,
        };
      }
      setForms(next);
    },
    [],
  );

  const refreshProviders = useCallback(async () => {
    try {
      const data = await fetchProviderPresets(server_config.BASE_URL);
      const jsonModules = await fetchJsonRequiredModules(server_config.BASE_URL);
      setProviders(data.providers);
      const keys = deriveModuleKeys(data.providers);
      const capsMap: Record<string, Record<string, LlmModelCapability>> = {};
      const labelsMap: Record<string, string[]> = {};
      for (const key of keys) {
        const source = MODULE_SERVER_SOURCES[key];
        if (source) {
          capsMap[key] = data[source.caps];
          labelsMap[key] = jsonModules[source.json];
        }
      }
      setModuleCaps(capsMap);
      setModuleJsonLabels(labelsMap);
      setModuleKeys(keys);
      setProvidersLoaded(true);
      setProvidersError('');
      await loadForms(data.providers, keys);
    } catch (e) {
      addDebugTrace('llm_settings', 'fetch providers failed', {
        error: String(e),
      });
      setProvidersError(
        `获取服务商列表失败：${e instanceof Error ? e.message : String(e)}`,
      );
    }
  }, [loadForms]);

  useEffect(() => {
    void refreshProviders();
  }, [refreshProviders]);

  const updateForm = useCallback(
    (moduleKey: string, patch: Partial<ModuleFormState>) => {
      setForms((prev) => ({
        ...prev,
        [moduleKey]: { ...prev[moduleKey], ...patch },
      }));
    },
    [],
  );

  const clearHighlight = useCallback(
    (moduleKey: string, field: FieldKey) => {
      const current = forms[moduleKey];
      if (current && current.highlight === field) {
        updateForm(moduleKey, { highlight: null });
      }
    },
    [forms, updateForm],
  );

  const selectProvider = (moduleKey: string, value: string) => {
    const preset = presetsFor(moduleKey).find((p) => p.name === value);
    updateForm(moduleKey, {
      provider: value,
      baseUrl: preset?.base_url ?? '',
      storedProvider: '',
      storedModel: '',
      model: '',
      notice: '',
      highlight: null,
    });
  };

  const selectModel = (moduleKey: string, value: string) => {
    updateForm(moduleKey, {
      model: value,
      storedModel: '',
      highlight: null,
    });
  };

  const pasteKey = async (moduleKey: string) => {
    try {
      const text = await Clipboard.getStringAsync();
      if (text) {
        updateForm(moduleKey, { apiKey: text.trim(), highlight: null });
      }
    } catch (e) {
      addDebugTrace('llm_settings', 'paste key failed', { error: String(e) });
    }
  };

  const scrollToModule = (moduleKey: string) => {
    const y = cardYRef.current[moduleKey] ?? 0;
    requestAnimationFrame(() => {
      scrollRef.current?.scrollTo({ y: Math.max(0, y - 12), animated: true });
    });
  };

  const parseParams = (text: string): Record<string, unknown> | null => {
    const trimmed = text.trim();
    if (!trimmed) {
      return {};
    }
    try {
      const parsed = JSON.parse(trimmed);
      return parsed && typeof parsed === 'object' && !Array.isArray(parsed)
        ? (parsed as Record<string, unknown>)
        : null;
    } catch {
      return null;
    }
  };

  const precheck = (): { moduleKey: string; field: FieldKey } | null => {
    for (const key of moduleKeys) {
      const form = forms[key];
      if (!form || !form.enabled) {
        continue;
      }
      if (!form.provider && !form.storedProvider) {
        return { moduleKey: key, field: 'provider' };
      }
      if (!form.apiKey) {
        return { moduleKey: key, field: 'apiKey' };
      }
      if (!form.model && !form.storedModel) {
        return { moduleKey: key, field: 'model' };
      }
      if (form.paramsText.trim() && parseParams(form.paramsText) === null) {
        return { moduleKey: key, field: 'paramsText' };
      }
    }
    return null;
  };

  const onSave = async () => {
    if (saving) {
      return;
    }
    const missing = precheck();
    if (missing) {
      updateForm(missing.moduleKey, { highlight: missing.field });
      scrollToModule(missing.moduleKey);
      const title = moduleTitle(missing.moduleKey);
      const field = friendlyFieldName(missing.field);
      Alert.alert(
        '配置不完整',
        missing.field === 'paramsText'
          ? `模块「${title}」的高级参数不是合法 JSON，请修正后重试。`
          : `模块「${title}」缺少 ${field}，请补全后重试。`,
      );
      return;
    }
    const batch = ++batchRef.current;
    setSaving(true);
    setSuccessMsg('');
    Keyboard.dismiss();

    const effectiveBaseUrl = (key: string): string => {
      const form = forms[key];
      const provider = form.provider || form.storedProvider;
      const preset = presetsFor(key).find((p) => p.name === provider);
      // 服务商在列表中：保存时自动同步预设地址；不在则保持原值
      return preset ? preset.base_url : form.baseUrl;
    };

    const targets = moduleKeys.filter(
      (key) => forms[key]?.enabled && effectiveBaseUrl(key),
    );
    const results = await Promise.all(
      targets.map(async (key): Promise<{ key: string; error: string | null }> => {
        const form = forms[key];
        const model = form.model || form.storedModel;
        try {
          const ids = await fetchModelsList(
            effectiveBaseUrl(key),
            form.apiKey,
            VALIDATION_TIMEOUT_MS,
          );
          if (!model || !ids.includes(model)) {
            return { key, error: '模型不可用（不在服务商模型列表中），请更换模型后重试。' };
          }
          return { key, error: null };
        } catch (e) {
          const message = String(e instanceof Error ? e.message : e);
          if (/(401|403|unauthorized|invalid api key)/i.test(message)) {
            return { key, error: 'API Key 无效或没有权限，请检查后重试。' };
          }
          if (/(timeout|timed out)/i.test(message)) {
            return { key, error: '请求超时（30 秒无响应），请检查网络后重试。' };
          }
          return { key, error: '无法连接服务商（URL 不可达），请检查网络后重试。' };
        }
      }),
    );
    if (batch !== batchRef.current) {
      return; // 过期批次：静默丢弃
    }
    setSaving(false);
    const failed = results.filter((r): r is { key: string; error: string } => !!r.error);
    if (failed.length > 0) {
      Alert.alert(
        '配置校验失败',
        failed
          .map((r) => `模块「${moduleTitle(r.key)}」：${r.error}`)
          .join('\n'),
      );
      return;
    }

    const cfg: LlmModulesConfig = {};
    for (const key of moduleKeys) {
      const form = forms[key];
      const provider = form.provider || form.storedProvider;
      cfg[key] = {
        enabled: form.enabled,
        provider,
        model: form.model || form.storedModel,
        baseUrl: effectiveBaseUrl(key),
        apiKey: form.apiKey,
        paramsText: form.paramsText,
      };
    }
    try {
      await setLlmModulesConfig(cfg);
      setSuccessMsg('配置已保存');
    } catch (e) {
      Alert.alert('保存失败', String(e instanceof Error ? e.message : e));
    }
  };

  const onCancel = () => {
    batchRef.current += 1;
    setSaving(false);
  };

  const badgeFor = (key: string): { show: boolean; labels: string[] } => {
    const form = forms[key];
    if (!form) {
      return { show: false, labels: [] };
    }
    const model = form.model || form.storedModel;
    const cap = model ? capsFor(key)[model] : undefined;
    const labels = jsonLabelsFor(key);
    return { show: !!model && !!cap && !cap.can_use_json && labels.length > 0, labels };
  };

  const renderCard = (key: string) => {
    const form = forms[key];
    if (!form) {
      return null;
    }
    const title = moduleTitle(key);
    const presets = presetsFor(key);
    const models = (
      presets.find((p) => p.name === form.provider) as
        | (LlmProviderPreset & Record<string, unknown>)
        | undefined
    )?.[key] as string[] | undefined;
    const badge = badgeFor(key);
    const fieldStyle = (field: FieldKey) =>
      form.highlight === field ? styles.inputError : undefined;

    return (
      <View
        key={key}
        style={styles.card}
        onLayout={(e) => {
          cardYRef.current[key] = e.nativeEvent.layout.y;
        }}
      >
        <View style={styles.cardHeader}>
          <Text style={styles.cardTitle}>{title}</Text>
          <View style={styles.switchRow}>
            <Text style={styles.switchLabel}>使用自己的 API Key</Text>
            <Switch
              value={form.enabled}
              disabled={saving}
              onValueChange={(value) => updateForm(key, { enabled: value })}
            />
          </View>
        </View>
        {form.notice ? (
          <Text style={styles.notice}>{form.notice}</Text>
        ) : null}
        {form.enabled ? (
          <View>
            <Text style={styles.fieldLabel}>服务商</Text>
            <TouchableOpacity
              disabled={saving}
              onPress={() => setPicker({ moduleKey: key, field: 'provider' })}
              style={[styles.pickerInput, fieldStyle('provider')]}
            >
              <Text
                style={form.provider ? styles.pickerInputText : styles.pickerPlaceholder}
              >
                {form.provider || (form.storedProvider ? form.storedProvider : '选择服务商')}
              </Text>
            </TouchableOpacity>

            <Text style={styles.fieldLabel}>API Key</Text>
            <View style={styles.keyRow}>
              <TextInput
                value={form.apiKey}
                onChangeText={(text) => {
                  updateForm(key, { apiKey: text });
                  clearHighlight(key, 'apiKey');
                }}
                placeholder="粘贴 API Key"
                placeholderTextColor="#aaa"
                secureTextEntry
                style={[styles.input, fieldStyle('apiKey')]}
              />
              <TouchableOpacity
                disabled={saving}
                onPress={() => (form.apiKey ? updateForm(key, { apiKey: '' }) : void pasteKey(key))}
                style={styles.smallButton}
              >
                <Text style={styles.smallButtonText}>
                  {form.apiKey ? '清空' : '粘贴'}
                </Text>
              </TouchableOpacity>
            </View>

            <Text style={styles.fieldLabel}>模型</Text>
            <TouchableOpacity
              disabled={saving}
              onPress={() => setPicker({ moduleKey: key, field: 'model' })}
              style={[styles.pickerInput, fieldStyle('model')]}
            >
              <Text
                style={form.model ? styles.pickerInputText : styles.pickerPlaceholder}
              >
                {form.model || (form.storedModel ? form.storedModel : '选择模型')}
              </Text>
            </TouchableOpacity>

            {badge.show ? (
              <View style={styles.badgeRow}>
                <Text style={styles.badge}>部分高级功能将使用服务端 Key</Text>
                <TouchableOpacity
                  onPress={() => updateForm(key, { showJsonTasks: !form.showJsonTasks })}
                  style={styles.infoButton}
                >
                  <Text style={styles.infoButtonText}>?</Text>
                </TouchableOpacity>
              </View>
            ) : null}
            {badge.show && form.showJsonTasks ? (
              <Text style={styles.badgeDetail}>
                以下功能将使用服务端 Key：{badge.labels.join('、')}
              </Text>
            ) : null}

            <Text style={styles.fieldLabel}>高级参数（JSON，可选）</Text>
            <TextInput
              value={form.paramsText}
              onChangeText={(text) => {
                updateForm(key, { paramsText: text });
                clearHighlight(key, 'paramsText');
              }}
              placeholder={'{"temperature": 0.7}'}
              placeholderTextColor="#aaa"
              multiline
              style={[styles.input, styles.paramsInput, fieldStyle('paramsText')]}
            />
          </View>
        ) : null}
      </View>
    );
  };

  const pickerTarget = picker ? forms[picker.moduleKey] : null;
  const pickerOptions: string[] = (() => {
    if (!picker || !pickerTarget) {
      return [];
    }
    if (picker.field === 'provider') {
      return presetsFor(picker.moduleKey).map((p) => p.name);
    }
    const preset = presetsFor(picker.moduleKey).find(
      (p) => p.name === pickerTarget.provider,
    );
    const field = preset ? providerField(preset, picker.moduleKey) : undefined;
    return Array.isArray(field) ? (field as string[]) : [];
  })();

  return (
    <KeyboardAvoidingView
      style={[styles.screen, { paddingTop: insets.top }]}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <View style={styles.header}>
        <Text style={styles.title}>LLM 模型设置</Text>
        <TouchableOpacity onPress={refreshProviders} disabled={saving}>
          <Text style={styles.refreshText}>刷新服务商列表</Text>
        </TouchableOpacity>
      </View>
      {providersError ? <Text style={styles.errorText}>{providersError}</Text> : null}
      {successMsg ? <Text style={styles.successText}>{successMsg}</Text> : null}

      <ScrollView ref={scrollRef} contentContainerStyle={styles.listContent}>
        {!providersLoaded ? (
          <ActivityIndicator style={styles.loading} />
        ) : (
          moduleKeys.map(renderCard)
        )}
      </ScrollView>

      <View style={styles.footer}>
        {saving ? (
          <TouchableOpacity onPress={onCancel} style={styles.cancelButton}>
            <Text style={styles.cancelButtonText}>取消</Text>
          </TouchableOpacity>
        ) : null}
        <TouchableOpacity
          disabled={!providersLoaded || saving}
          onPress={() => void onSave()}
          style={[styles.saveButton, (!providersLoaded || saving) && styles.saveButtonDisabled]}
        >
          <Text style={styles.saveButtonText}>保存</Text>
        </TouchableOpacity>
      </View>

      <OptionPicker
        visible={!!picker}
        title={picker ? `${moduleTitle(picker.moduleKey)} - ${picker.field === 'provider' ? '选择服务商' : '选择模型'}` : ''}
        options={pickerOptions}
        selected={picker && pickerTarget ? (picker.field === 'provider' ? pickerTarget.provider : pickerTarget.model) : ''}
        onSelect={(value) => {
          if (picker) {
            if (picker.field === 'provider') {
              selectProvider(picker.moduleKey, value);
            } else {
              selectModel(picker.moduleKey, value);
            }
          }
          setPicker(null);
        }}
        onClose={() => setPicker(null)}
      />
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: '#F5F7FA',
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    paddingVertical: 12,
  },
  title: {
    fontSize: 20,
    fontWeight: '700',
    color: '#333',
  },
  refreshText: {
    fontSize: 14,
    color: '#2F80ED',
  },
  errorText: {
    fontSize: 13,
    color: '#C0392B',
    paddingHorizontal: 16,
    paddingBottom: 4,
  },
  successText: {
    fontSize: 13,
    color: '#1E8E3E',
    paddingHorizontal: 16,
    paddingBottom: 4,
  },
  listContent: {
    padding: 12,
    paddingBottom: 24,
  },
  loading: {
    marginTop: 48,
  },
  card: {
    backgroundColor: '#FFFFFF',
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#E0E6EC',
    padding: 14,
    marginBottom: 12,
  },
  cardHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 4,
  },
  cardTitle: {
    fontSize: 16,
    fontWeight: '600',
    color: '#333',
  },
  switchRow: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  switchLabel: {
    fontSize: 13,
    color: '#555',
    marginRight: 6,
  },
  notice: {
    fontSize: 12,
    color: '#C77700',
    marginBottom: 6,
  },
  fieldLabel: {
    fontSize: 13,
    color: '#555',
    marginTop: 8,
    marginBottom: 4,
  },
  pickerInput: {
    borderWidth: 1,
    borderColor: '#D5DAE0',
    borderRadius: 8,
    paddingHorizontal: 10,
    paddingVertical: 10,
    backgroundColor: '#FBFCFD',
  },
  pickerInputText: {
    fontSize: 14,
    color: '#333',
  },
  pickerPlaceholder: {
    fontSize: 14,
    color: '#aaa',
  },
  keyRow: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  input: {
    flex: 1,
    borderWidth: 1,
    borderColor: '#D5DAE0',
    borderRadius: 8,
    paddingHorizontal: 10,
    paddingVertical: 10,
    fontSize: 14,
    color: '#333',
    backgroundColor: '#FBFCFD',
  },
  paramsInput: {
    minHeight: 72,
    textAlignVertical: 'top',
  },
  inputError: {
    borderColor: '#E53935',
    borderWidth: 2,
  },
  smallButton: {
    marginLeft: 8,
    paddingHorizontal: 14,
    paddingVertical: 10,
    borderRadius: 8,
    backgroundColor: '#EEF3F8',
  },
  smallButtonText: {
    fontSize: 13,
    color: '#2F80ED',
  },
  badgeRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginTop: 8,
  },
  badge: {
    fontSize: 12,
    color: '#B7791F',
    backgroundColor: '#FDF3DC',
    borderRadius: 4,
    paddingHorizontal: 8,
    paddingVertical: 3,
    overflow: 'hidden',
  },
  infoButton: {
    marginLeft: 6,
    width: 22,
    height: 22,
    borderRadius: 11,
    backgroundColor: '#E5E7EB',
    alignItems: 'center',
    justifyContent: 'center',
  },
  infoButtonText: {
    fontSize: 13,
    color: '#555',
    fontWeight: '700',
  },
  badgeDetail: {
    fontSize: 12,
    color: '#8A6D1A',
    marginTop: 4,
  },
  footer: {
    flexDirection: 'row',
    justifyContent: 'flex-end',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderTopWidth: 1,
    borderTopColor: '#E5E9EF',
    backgroundColor: '#FFFFFF',
  },
  cancelButton: {
    marginRight: 10,
    paddingHorizontal: 20,
    paddingVertical: 10,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#CCC',
  },
  cancelButtonText: {
    fontSize: 14,
    color: '#555',
  },
  saveButton: {
    backgroundColor: '#5BB8E8',
    paddingHorizontal: 32,
    paddingVertical: 10,
    borderRadius: 8,
  },
  saveButtonDisabled: {
    backgroundColor: '#C8CDD3',
  },
  saveButtonText: {
    fontSize: 15,
    color: '#FFFFFF',
    fontWeight: '600',
  },
  pickerMask: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.35)',
    justifyContent: 'center',
    padding: 24,
  },
  pickerBox: {
    backgroundColor: '#FFFFFF',
    borderRadius: 12,
    padding: 16,
  },
  pickerTitle: {
    fontSize: 16,
    fontWeight: '600',
    color: '#333',
    marginBottom: 10,
  },
  pickerItem: {
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: '#F0F2F5',
  },
  pickerItemSelected: {
    backgroundColor: '#F0F7FD',
  },
  pickerItemText: {
    fontSize: 15,
    color: '#333',
  },
  pickerCancel: {
    marginTop: 12,
    alignItems: 'center',
    paddingVertical: 10,
  },
  pickerCancelText: {
    fontSize: 15,
    color: '#2F80ED',
  },
});

/**
 * LLM 模型设置页：按服务端下发的客户端模型类型渲染卡片 + 全局保存。
 *
 * 类型字典由 /llm/providers 生成（type -> providers[base_url, models[勾选]]），
 * 每个类型一张卡片：服务商/模型下拉由类型数据驱动，保存时对开启的类型并行
 * GET /models 校验（batchId 防过期），全部通过后一次性写入 SecureStore，
 * 键为类型名；并把所选模型的 thinking/json 勾选复制为本地能力快照，
 * 供运行时按服务端门控逻辑附加 enable_thinking / response_format。
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
import { fetchClientModelTypes, fetchModelsList } from '../utils/llm_client';
import type { ClientModelType } from '../utils/llm_client';
import {
  getLlmModulesConfig,
  setLlmModulesConfig,
} from '../utils/llm_key_storage';
import type { LlmModulesConfig } from '../utils/llm_key_storage';
import { AppTheme, THEMES } from '../utils/theme';

const VALIDATION_TIMEOUT_MS = 30000;

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
}

interface LlmSettingsScreenProps {
  onClose: () => void;
  theme?: AppTheme;
}

interface PickerTarget {
  typeName: string;
  field: 'provider' | 'model';
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

  const [types, setTypes] = useState<ClientModelType[]>([]);
  const [forms, setForms] = useState<Record<string, ModuleFormState>>({});
  const [typesLoaded, setTypesLoaded] = useState(false);
  const [typesError, setTypesError] = useState('');
  const [saving, setSaving] = useState(false);
  const [picker, setPicker] = useState<PickerTarget | null>(null);

  const providersFor = useCallback(
    (typeName: string): ClientModelType['providers'] =>
      types.find((item) => item.type === typeName)?.providers ?? [],
    [types],
  );

  const effectiveBaseUrl = useCallback(
    (typeName: string): string => {
      const form = forms[typeName];
      if (!form) {
        return '';
      }
      const provider = form.provider || form.storedProvider;
      const preset = providersFor(typeName).find((p) => p.name === provider);
      return preset ? preset.base_url : form.baseUrl;
    },
    [forms, providersFor],
  );

  const loadForms = useCallback(
    async (typeList: ClientModelType[]) => {
      const stored = await getLlmModulesConfig();
      const next: Record<string, ModuleFormState> = {};
      for (const typeItem of typeList) {
        const saved = stored[typeItem.type];
        const presets = typeItem.providers;
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
          !(preset && preset.models.some((m) => m.id === model))
        ) {
          storedModel = model;
          model = '';
        }
        next[typeItem.type] = {
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
        };
      }
      setForms(next);
    },
    [],
  );

  const refreshTypes = useCallback(async () => {
    try {
      const data = await fetchClientModelTypes(server_config.BASE_URL);
      setTypes(data.types);
      setTypesLoaded(true);
      setTypesError('');
      await loadForms(data.types);
    } catch (e) {
      addDebugTrace('llm_settings', 'fetch types failed', {
        error: String(e),
      });
      setTypesError(
        `获取类型列表失败：${e instanceof Error ? e.message : String(e)}`,
      );
    }
  }, [loadForms]);

  useEffect(() => {
    void refreshTypes();
  }, [refreshTypes]);

  const updateForm = useCallback(
    (typeName: string, patch: Partial<ModuleFormState>) => {
      setForms((prev) => ({
        ...prev,
        [typeName]: { ...prev[typeName], ...patch },
      }));
    },
    [],
  );

  const clearHighlight = useCallback(
    (typeName: string, field: FieldKey) => {
      const current = forms[typeName];
      if (current && current.highlight === field) {
        updateForm(typeName, { highlight: null });
      }
    },
    [forms, updateForm],
  );

  const selectProvider = (typeName: string, value: string) => {
    const preset = providersFor(typeName).find((p) => p.name === value);
    updateForm(typeName, {
      provider: value,
      baseUrl: preset?.base_url ?? '',
      storedProvider: '',
      storedModel: '',
      model: '',
      notice: '',
      highlight: null,
    });
  };

  const selectModel = (typeName: string, value: string) => {
    updateForm(typeName, {
      model: value,
      storedModel: '',
      highlight: null,
    });
  };

  const pasteKey = async (typeName: string) => {
    try {
      const text = await Clipboard.getStringAsync();
      if (text) {
        updateForm(typeName, { apiKey: text.trim(), highlight: null });
      }
    } catch (e) {
      addDebugTrace('llm_settings', 'paste key failed', { error: String(e) });
    }
  };

  const scrollToType = (typeName: string) => {
    const y = cardYRef.current[typeName] ?? 0;
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

  const precheck = (): { typeName: string; field: FieldKey } | null => {
    for (const typeItem of types) {
      const form = forms[typeItem.type];
      if (!form || !form.enabled) {
        continue;
      }
      if (!form.provider && !form.storedProvider) {
        return { typeName: typeItem.type, field: 'provider' };
      }
      if (!form.apiKey) {
        return { typeName: typeItem.type, field: 'apiKey' };
      }
      if (!form.model && !form.storedModel) {
        return { typeName: typeItem.type, field: 'model' };
      }
      if (form.paramsText.trim() && parseParams(form.paramsText) === null) {
        return { typeName: typeItem.type, field: 'paramsText' };
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
      updateForm(missing.typeName, { highlight: missing.field });
      scrollToType(missing.typeName);
      const field = friendlyFieldName(missing.field);
      Alert.alert(
        '配置不完整',
        missing.field === 'paramsText'
          ? `类型「${missing.typeName}」的高级参数不是合法 JSON，请修正后重试。`
          : `类型「${missing.typeName}」缺少 ${field}，请补全后重试。`,
      );
      return;
    }
    const batch = ++batchRef.current;
    setSaving(true);
    Keyboard.dismiss();

    const targets = types.filter(
      (typeItem) =>
        forms[typeItem.type]?.enabled && effectiveBaseUrl(typeItem.type),
    );
    const results = await Promise.all(
      targets.map(
        async (typeItem): Promise<{ typeName: string; error: string | null }> => {
          const form = forms[typeItem.type];
          const model = form.model || form.storedModel;
          try {
            const ids = await fetchModelsList(
              effectiveBaseUrl(typeItem.type),
              form.apiKey,
              VALIDATION_TIMEOUT_MS,
            );
            if (!model || !ids.includes(model)) {
              return {
                typeName: typeItem.type,
                error: '模型不可用（不在服务商模型列表中），请更换模型后重试。',
              };
            }
            return { typeName: typeItem.type, error: null };
          } catch (e) {
            const message = String(e instanceof Error ? e.message : e);
            if (/(401|403|unauthorized|invalid api key)/i.test(message)) {
              return {
                typeName: typeItem.type,
                error: 'API Key 无效或没有权限，请检查后重试。',
              };
            }
            if (/(timeout|timed out)/i.test(message)) {
              return {
                typeName: typeItem.type,
                error: '请求超时（30 秒无响应），请检查网络后重试。',
              };
            }
            return {
              typeName: typeItem.type,
              error: '无法连接服务商（URL 不可达），请检查网络后重试。',
            };
          }
        },
      ),
    );
    if (batch !== batchRef.current) {
      return; // 过期批次：静默丢弃
    }
    setSaving(false);
    const failed = results.filter(
      (r): r is { typeName: string; error: string } => !!r.error,
    );
    if (failed.length > 0) {
      Alert.alert(
        '配置校验失败',
        failed.map((r) => `类型「${r.typeName}」：${r.error}`).join('\n'),
      );
      return;
    }

    const cfg: LlmModulesConfig = {};
    for (const typeItem of types) {
      const form = forms[typeItem.type];
      const provider = form.provider || form.storedProvider;
      const model = form.model || form.storedModel;
      const preset = providersFor(typeItem.type).find((p) => p.name === provider);
      const modelEntry = preset?.models.find((m) => m.id === model);
      cfg[typeItem.type] = {
        enabled: form.enabled,
        provider,
        model,
        baseUrl: effectiveBaseUrl(typeItem.type),
        apiKey: form.apiKey,
        paramsText: form.paramsText,
        modelCapabilities: {
          can_enable_thinking: Boolean(modelEntry?.can_enable_thinking),
          can_use_json: Boolean(modelEntry?.can_use_json),
        },
      };
    }
    try {
      await setLlmModulesConfig(cfg);
      Alert.alert('保存成功', '配置已保存');
    } catch (e) {
      Alert.alert('保存失败', String(e instanceof Error ? e.message : e));
    }
  };

  const onCancel = () => {
    batchRef.current += 1;
    setSaving(false);
  };

  const renderCard = (typeItem: ClientModelType) => {
    const typeName = typeItem.type;
    const form = forms[typeName];
    if (!form) {
      return null;
    }
    const fieldStyle = (field: FieldKey) =>
      form.highlight === field ? styles.inputError : undefined;

    return (
      <View
        key={typeName}
        style={styles.card}
        onLayout={(e) => {
          cardYRef.current[typeName] = e.nativeEvent.layout.y;
        }}
      >
        <View style={styles.cardHeader}>
          <Text style={styles.cardTitle}>{typeName}</Text>
          <View style={styles.switchRow}>
            <Text style={styles.switchLabel}>使用自己的 API Key</Text>
            <Switch
              value={form.enabled}
              disabled={saving}
              onValueChange={(value) => updateForm(typeName, { enabled: value })}
            />
          </View>
        </View>
        {typeItem.description ? (
          <Text style={styles.description}>{typeItem.description}</Text>
        ) : null}
        {form.notice ? <Text style={styles.notice}>{form.notice}</Text> : null}
        {form.enabled ? (
          <View>
            <Text style={styles.fieldLabel}>服务商</Text>
            <TouchableOpacity
              disabled={saving}
              onPress={() => setPicker({ typeName, field: 'provider' })}
              style={[styles.pickerInput, fieldStyle('provider')]}
            >
              <Text
                style={form.provider ? styles.pickerInputText : styles.pickerPlaceholder}
              >
                {form.provider || (form.storedProvider ? form.storedProvider : '选择服务商')}
              </Text>
            </TouchableOpacity>
            {form.provider || form.storedProvider ? (
              <Text style={styles.urlHint}>
                服务商地址：{effectiveBaseUrl(typeName)}
              </Text>
            ) : null}

            <Text style={styles.fieldLabel}>API Key</Text>
            <View style={styles.keyRow}>
              <TextInput
                value={form.apiKey}
                onChangeText={(text) => {
                  updateForm(typeName, { apiKey: text });
                  clearHighlight(typeName, 'apiKey');
                }}
                placeholder="粘贴 API Key"
                placeholderTextColor="#aaa"
                secureTextEntry
                style={[styles.input, fieldStyle('apiKey')]}
              />
              <TouchableOpacity
                disabled={saving}
                onPress={() =>
                  form.apiKey
                    ? updateForm(typeName, { apiKey: '' })
                    : void pasteKey(typeName)
                }
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
              onPress={() => setPicker({ typeName, field: 'model' })}
              style={[styles.pickerInput, fieldStyle('model')]}
            >
              <Text
                style={form.model ? styles.pickerInputText : styles.pickerPlaceholder}
              >
                {form.model || (form.storedModel ? form.storedModel : '选择模型')}
              </Text>
            </TouchableOpacity>

            <Text style={styles.fieldLabel}>高级参数（JSON，可选）</Text>
            <TextInput
              value={form.paramsText}
              onChangeText={(text) => {
                updateForm(typeName, { paramsText: text });
                clearHighlight(typeName, 'paramsText');
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

  const pickerTarget = picker ? forms[picker.typeName] : null;
  const pickerOptions: string[] = (() => {
    if (!picker || !pickerTarget) {
      return [];
    }
    if (picker.field === 'provider') {
      return providersFor(picker.typeName).map((p) => p.name);
    }
    const preset = providersFor(picker.typeName).find(
      (p) => p.name === pickerTarget.provider,
    );
    return preset ? preset.models.map((m) => m.id) : [];
  })();

  return (
    <KeyboardAvoidingView
      style={[styles.screen, { paddingTop: insets.top }]}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <View style={styles.header}>
        <TouchableOpacity onPress={onClose} disabled={saving} style={styles.backButton}>
          <Text style={styles.backText}>‹ 返回</Text>
        </TouchableOpacity>
        <Text style={styles.title}>LLM 模型设置</Text>
        <TouchableOpacity onPress={refreshTypes} disabled={saving}>
          <Text style={styles.refreshText}>刷新类型列表</Text>
        </TouchableOpacity>
      </View>
      {typesError ? <Text style={styles.errorText}>{typesError}</Text> : null}

      <ScrollView ref={scrollRef} contentContainerStyle={styles.listContent}>
        {!typesLoaded ? (
          <ActivityIndicator style={styles.loading} />
        ) : (
          types.map(renderCard)
        )}
      </ScrollView>

      <View style={styles.footer}>
        {saving ? (
          <TouchableOpacity onPress={onCancel} style={styles.cancelButton}>
            <Text style={styles.cancelButtonText}>取消</Text>
          </TouchableOpacity>
        ) : null}
        <TouchableOpacity
          disabled={!typesLoaded || saving}
          onPress={() => void onSave()}
          style={[styles.saveButton, (!typesLoaded || saving) && styles.saveButtonDisabled]}
        >
          <Text style={styles.saveButtonText}>保存</Text>
        </TouchableOpacity>
      </View>

      <OptionPicker
        visible={!!picker}
        title={
          picker
            ? `${picker.typeName} - ${picker.field === 'provider' ? '选择服务商' : '选择模型'}`
            : ''
        }
        options={pickerOptions}
        selected={
          picker && pickerTarget
            ? picker.field === 'provider'
              ? pickerTarget.provider
              : pickerTarget.model
            : ''
        }
        onSelect={(value) => {
          if (picker) {
            if (picker.field === 'provider') {
              selectProvider(picker.typeName, value);
            } else {
              selectModel(picker.typeName, value);
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
    ...StyleSheet.absoluteFillObject,
    zIndex: 120,
    backgroundColor: '#f5f7fa',
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
  backButton: {
    minWidth: 72,
    paddingVertical: 4,
  },
  backText: {
    fontSize: 15,
    color: '#2F80ED',
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
  description: {
    fontSize: 12,
    color: '#888',
    marginBottom: 6,
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
  urlHint: {
    fontSize: 12,
    color: '#888',
    marginTop: 2,
    marginBottom: 4,
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

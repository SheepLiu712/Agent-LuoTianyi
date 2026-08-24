/** 客户端自定义 LLM/VLM 配置页。服务端只下发调用需求，不下发模型目录。 */

import React, { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  KeyboardAvoidingView,
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
import { fetchClientModelTypes } from '../utils/llm_client';
import type { ClientModelType } from '../utils/llm_client';
import {
  getLlmModulesConfig,
  setLlmModulesConfig,
} from '../utils/llm_key_storage';
import {
  buildLlmModulesConfig,
  emptyModuleForm,
  validateLlmForms,
} from '../utils/llm_requirements';
import type { ModuleFormState } from '../utils/llm_requirements';
import { AppTheme, THEMES } from '../utils/theme';

interface LlmSettingsScreenProps {
  onClose: () => void;
  theme?: AppTheme;
}


export default function LlmSettingsScreen({
  onClose,
  theme = THEMES.light,
}: LlmSettingsScreenProps) {
  const insets = useSafeAreaInsets();
  const [types, setTypes] = useState<ClientModelType[]>([]);
  const [forms, setForms] = useState<Record<string, ModuleFormState>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [response, stored] = await Promise.all([
        fetchClientModelTypes(server_config.BASE_URL),
        getLlmModulesConfig(),
      ]);
      const next: Record<string, ModuleFormState> = {};
      for (const requirement of response.types) {
        // 兼容旧版以中文显示名为键的配置。
        const saved = stored[requirement.id] ?? stored[requirement.name];
        next[requirement.id] = saved
          ? {
              enabled: saved.enabled,
              provider: saved.provider,
              baseUrl: saved.baseUrl,
              model: saved.model,
              apiKey: saved.apiKey,
              paramsText: saved.paramsText,
              supportsJson: Boolean(saved.modelCapabilities?.can_use_json),
              supportsThinking: Boolean(saved.modelCapabilities?.can_enable_thinking),
            }
          : emptyModuleForm();
      }
      setTypes(response.types);
      setForms(next);
      setError('');
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      addDebugTrace('llm_settings', 'fetch requirements failed', { error: message });
      setError(`获取模型需求失败：${message}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const updateForm = (typeId: string, patch: Partial<ModuleFormState>) => {
    setForms((previous) => ({
      ...previous,
      [typeId]: { ...(previous[typeId] ?? emptyModuleForm()), ...patch },
    }));
  };

  const save = async () => {
    if (saving) {
      return;
    }
    const validationError = validateLlmForms(types, forms);
    if (validationError) {
      Alert.alert('配置不完整', validationError);
      return;
    }
    setSaving(true);
    try {
      const config = buildLlmModulesConfig(types, forms);
      await setLlmModulesConfig(config);
      Alert.alert('保存成功', '实际调用失败时会提示错误并回退服务端模型。');
    } catch (e) {
      Alert.alert('保存失败', e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <KeyboardAvoidingView
      style={[styles.overlayRoot, { backgroundColor: theme.root }]}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <View
        style={[
          styles.container,
          {
            paddingTop: insets.top,
            paddingBottom: insets.bottom,
            backgroundColor: theme.root,
          },
        ]}
      >
        <View
          style={[
            styles.header,
            { backgroundColor: theme.surface, borderBottomColor: theme.border },
          ]}
        >
          <TouchableOpacity onPress={onClose} style={styles.headerButton} activeOpacity={0.72}>
            <Text style={[styles.headerButtonText, { color: theme.accentText }]}>返回</Text>
          </TouchableOpacity>
          <Text style={[styles.title, { color: theme.text }]}>LLM 模型设置</Text>
          <TouchableOpacity
            onPress={() => void load()}
            style={[styles.headerButton, styles.headerButtonRight]}
            activeOpacity={0.72}
          >
            <Text style={[styles.headerButtonText, { color: theme.accentText }]}>刷新</Text>
          </TouchableOpacity>
        </View>

        <ScrollView
          style={styles.scrollView}
          contentContainerStyle={styles.content}
          keyboardShouldPersistTaps="handled"
        >
          <Text style={[styles.explanation, { color: theme.textMuted }]}>
            服务端只规定调用所需的 LLM/VLM、JSON 和 thinking 能力。服务商、Base URL、模型和
            Key 完全由你配置，Key 只保存在本机。
          </Text>

        {loading && <ActivityIndicator size="large" color={theme.accent} />}
        {!!error && (
          <View style={styles.errorBox}>
            <Text style={styles.errorText}>{error}</Text>
          </View>
        )}

        {types.map((requirement) => {
          const form = forms[requirement.id] ?? emptyModuleForm();
          const requirementLabels = [requirement.model_kind.toUpperCase()];
          if (requirement.requires_json) requirementLabels.push('需要 JSON');
          if (requirement.requires_thinking) requirementLabels.push('需要 thinking');
          return (
            <View key={requirement.id} style={[styles.card, { borderColor: theme.border }]}>
              <View style={styles.cardHeader}>
                <View style={styles.cardTitleWrap}>
                  <Text style={[styles.cardTitle, { color: theme.text }]}>{requirement.name}</Text>
                  <Text style={[styles.requirement, { color: theme.accent }]}>
                    调用要求：{requirementLabels.join(' / ')}
                  </Text>
                </View>
                <Switch
                  value={form.enabled}
                  onValueChange={(enabled) => updateForm(requirement.id, { enabled })}
                />
              </View>
              {!!requirement.description && (
                <Text style={[styles.description, { color: theme.textMuted }]}>
                  {requirement.description}
                </Text>
              )}
              {form.enabled && (
                <View style={styles.fields}>
                  <TextInput
                    value={form.provider}
                    onChangeText={(provider) => updateForm(requirement.id, { provider })}
                    placeholder="服务商名称（自定义）"
                    placeholderTextColor={theme.textMuted}
                    style={[styles.input, { color: theme.text, borderColor: theme.border }]}
                  />
                  <TextInput
                    value={form.baseUrl}
                    onChangeText={(baseUrl) => updateForm(requirement.id, { baseUrl })}
                    placeholder="OpenAI-compatible Base URL，例如 https://example.com/v1"
                    placeholderTextColor={theme.textMuted}
                    autoCapitalize="none"
                    style={[styles.input, { color: theme.text, borderColor: theme.border }]}
                  />
                  <TextInput
                    value={form.apiKey}
                    onChangeText={(apiKey) => updateForm(requirement.id, { apiKey })}
                    placeholder="API Key"
                    placeholderTextColor={theme.textMuted}
                    secureTextEntry
                    autoCapitalize="none"
                    style={[styles.input, { color: theme.text, borderColor: theme.border }]}
                  />
                  <TextInput
                    value={form.model}
                    onChangeText={(model) => updateForm(requirement.id, { model })}
                    placeholder="模型名称（自定义）"
                    placeholderTextColor={theme.textMuted}
                    autoCapitalize="none"
                    style={[styles.input, { color: theme.text, borderColor: theme.border }]}
                  />
                  <View style={styles.capabilityRow}>
                    <Text style={{ color: theme.text }}>此模型支持 JSON 输出</Text>
                    <Switch
                      value={form.supportsJson}
                      onValueChange={(supportsJson) => updateForm(requirement.id, { supportsJson })}
                    />
                  </View>
                  <View style={styles.capabilityRow}>
                    <Text style={{ color: theme.text }}>此模型支持 thinking</Text>
                    <Switch
                      value={form.supportsThinking}
                      onValueChange={(supportsThinking) =>
                        updateForm(requirement.id, { supportsThinking })
                      }
                    />
                  </View>
                  <TextInput
                    value={form.paramsText}
                    onChangeText={(paramsText) => updateForm(requirement.id, { paramsText })}
                    placeholder={'高级参数（JSON，可选），例如 {"temperature": 0.7}'}
                    placeholderTextColor={theme.textMuted}
                    multiline
                    style={[styles.input, styles.paramsInput, { color: theme.text, borderColor: theme.border }]}
                  />
                </View>
              )}
            </View>
          );
        })}

          <TouchableOpacity
            disabled={loading || saving || types.length === 0}
            onPress={() => void save()}
            style={[styles.saveButton, { backgroundColor: theme.accent }, (loading || saving) && styles.disabled]}
          >
            {saving ? <ActivityIndicator color="#fff" /> : <Text style={styles.saveText}>保存</Text>}
          </TouchableOpacity>
        </ScrollView>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  overlayRoot: {
    ...StyleSheet.absoluteFillObject,
    zIndex: 130,
  },
  container: { flex: 1 },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderBottomWidth: 1,
  },
  headerButton: { minWidth: 58, paddingVertical: 6 },
  headerButtonRight: { alignItems: 'flex-end' },
  headerButtonText: { fontSize: 16, fontWeight: '600' },
  title: { flex: 1, textAlign: 'center', fontSize: 18, fontWeight: '600' },
  scrollView: { flex: 1 },
  content: { paddingHorizontal: 16, paddingTop: 16, paddingBottom: 24, gap: 14 },
  explanation: { fontSize: 13, lineHeight: 19 },
  errorBox: { backgroundColor: '#FFECEC', borderRadius: 8, padding: 12 },
  errorText: { color: '#C62828' },
  card: { borderWidth: 1, borderRadius: 10, padding: 14, gap: 8 },
  cardHeader: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  cardTitleWrap: { flex: 1 },
  cardTitle: { fontSize: 16, fontWeight: '600' },
  requirement: { marginTop: 3, fontSize: 12 },
  description: { fontSize: 12, lineHeight: 18 },
  fields: { gap: 10, marginTop: 4 },
  input: { borderWidth: 1, borderRadius: 8, paddingHorizontal: 11, paddingVertical: 9, fontSize: 14 },
  capabilityRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  paramsInput: { minHeight: 72, textAlignVertical: 'top' },
  saveButton: { minHeight: 46, borderRadius: 9, alignItems: 'center', justifyContent: 'center', marginTop: 4 },
  saveText: { color: '#fff', fontSize: 16, fontWeight: '600' },
  disabled: { opacity: 0.5 },
});

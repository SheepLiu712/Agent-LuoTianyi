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
  VLM_PROVIDER_STORAGE_KEY,
  VLM_MODEL_STORAGE_KEY,
  VLM_PROVIDER_BASE_URL_STORAGE_KEY,
  VLM_PARAMS_STORAGE_KEY,
  server_config,
} from '../config';
import { addDebugTrace } from '../utils/debug_trace';
import { fetchProviderPresets, resolveProviderBaseUrl } from '../utils/llm_client';
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

export default function LlmSettingsScreen({ onClose, theme = THEMES.light }: LlmSettingsScreenProps) {
  const insets = useSafeAreaInsets();
  const scrollRef = useRef<ScrollView>(null);

  const [providers, setProviders] = useState<LlmProviderPreset[]>([]);
  const [activeTab, setActiveTab] = useState<TabKind>('text');

  const [llmProvider, setLlmProvider] = useState('');
  const [llmApiKey, setLlmApiKey] = useState('');
  const [llmModel, setLlmModel] = useState('');
  const [llmParamsText, setLlmParamsText] = useState('');

  const [vlmProvider, setVlmProvider] = useState('');
  const [vlmApiKey, setVlmApiKey] = useState('');
  const [vlmModel, setVlmModel] = useState('');
  const [vlmParamsText, setVlmParamsText] = useState('');

  const [showAdvanced, setShowAdvanced] = useState(false);
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
        ] = await Promise.all([
          AsyncStorage.getItem(LLM_PROVIDER_STORAGE_KEY),
          AsyncStorage.getItem(LLM_MODEL_STORAGE_KEY),
          AsyncStorage.getItem(LLM_PARAMS_STORAGE_KEY),
          AsyncStorage.getItem(VLM_PROVIDER_STORAGE_KEY),
          AsyncStorage.getItem(VLM_MODEL_STORAGE_KEY),
          AsyncStorage.getItem(VLM_PARAMS_STORAGE_KEY),
          getLlmApiKey(),
          getVlmApiKey(),
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
        if (key) setLlmApiKey(key);
        if (vlmKey) setVlmApiKey(vlmKey);
      } catch (e) {
        addDebugTrace('llm_settings', 'load saved config failed', { error: String(e) });
      }
      try {
        const list = await fetchProviderPresets(server_config.BASE_URL);
        if (!active) {
          return;
        }
        setProviders(list);
        setLlmProvider((prev) => prev || list[0]?.name || '');
        const firstVlmProvider = list.find((p) => (p.vlm_models?.length ?? 0) > 0)?.name || '';
        setVlmProvider((prev) => prev || firstVlmProvider);
      } catch (e) {
        if (!active) {
          return;
        }
        addDebugTrace('llm_settings', 'fetch providers failed', { error: String(e) });
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  const currentPreset = providers.find((p) => p.name === llmProvider) ?? null;
  const currentVlmPreset = providers.find((p) => p.name === vlmProvider) ?? null;
  const vlmProviders = providers.filter((p) => (p.vlm_models?.length ?? 0) > 0);

  const isVlmTab = activeTab === 'vlm';
  const paramsText = isVlmTab ? vlmParamsText : llmParamsText;
  const setParamsText = isVlmTab ? setVlmParamsText : setLlmParamsText;
  const pickerProvider = isVlmTab ? currentVlmPreset : currentPreset;
  const pickerList = isVlmTab
    ? (currentVlmPreset?.vlm_models ?? [])
    : (currentPreset?.models ?? []);
  const pickerTitle = isVlmTab ? '选择图片理解模型' : '选择对话模型';

  const scrollToBottom = () => {
    requestAnimationFrame(() => {
      scrollRef.current?.scrollToEnd({ animated: true });
    });
  };

  const handleSave = async () => {
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
        Alert.alert('提示', `高级参数不是合法 JSON：${e instanceof Error ? e.message : String(e)}`);
        return null;
      }
    };
    const textParams = parseParams(llmParamsText);
    if (textParams === null) return;
    const vlmParams = parseParams(vlmParamsText);
    if (vlmParams === null) return;

    setSaving(true);
    try {
      await setLlmApiKey(llmApiKey.trim());
      await AsyncStorage.setItem(LLM_PROVIDER_STORAGE_KEY, llmProvider);
      await AsyncStorage.setItem(LLM_MODEL_STORAGE_KEY, llmModel.trim());
      await AsyncStorage.setItem(
        LLM_PROVIDER_BASE_URL_STORAGE_KEY,
        resolveProviderBaseUrl(llmProvider, providers),
      );
      await AsyncStorage.setItem(LLM_PARAMS_STORAGE_KEY, llmParamsText.trim());

      await setVlmApiKey(vlmApiKey.trim());
      await AsyncStorage.setItem(VLM_PROVIDER_STORAGE_KEY, vlmProvider);
      await AsyncStorage.setItem(VLM_MODEL_STORAGE_KEY, vlmModel.trim());
      await AsyncStorage.setItem(
        VLM_PROVIDER_BASE_URL_STORAGE_KEY,
        resolveProviderBaseUrl(vlmProvider, providers),
      );
      await AsyncStorage.setItem(VLM_PARAMS_STORAGE_KEY, vlmParamsText.trim());

      Alert.alert('成功', 'LLM 模型设置已保存');
      onClose();
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

          <View style={styles.tabBar}>
            <TouchableOpacity
              style={[styles.tabItem, activeTab === 'text' && { backgroundColor: theme.accent }]}
              onPress={() => setActiveTab('text')}
              activeOpacity={0.75}
            >
              <Text style={[styles.tabItemText, { color: activeTab === 'text' ? (theme.name === 'dark' ? '#0F1419' : '#ffffff') : theme.text }]}>
                对话模型
              </Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[styles.tabItem, activeTab === 'vlm' && { backgroundColor: theme.accent }]}
              onPress={() => setActiveTab('vlm')}
              activeOpacity={0.75}
            >
              <Text style={[styles.tabItemText, { color: activeTab === 'vlm' ? (theme.name === 'dark' ? '#0F1419' : '#ffffff') : theme.text }]}>
                图片理解模型
              </Text>
            </TouchableOpacity>
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

            <Text style={[styles.label, { color: theme.text }]}>服务商</Text>
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
            {providers.length === 0 ? (
              <Text style={[styles.emptyText, { color: theme.textMuted }]}>
                暂无可用的服务商（请确认服务端已配置）
              </Text>
            ) : isVlmTab && vlmProviders.length === 0 ? (
              <Text style={[styles.emptyText, { color: theme.textMuted }]}>
                当前服务端没有支持图片理解的模型
              </Text>
            ) : null}

            <Text style={[styles.label, { color: theme.text }]}>API Key</Text>
            <TextInput
              style={[styles.input, { backgroundColor: theme.inputBackground, borderColor: theme.border, color: theme.inputText }]}
              placeholder={isVlmTab ? '粘贴图片理解服务商的 API Key' : '粘贴对话服务商的 API Key'}
              placeholderTextColor={theme.placeholder}
              value={isVlmTab ? vlmApiKey : llmApiKey}
              onChangeText={isVlmTab ? setVlmApiKey : setLlmApiKey}
              secureTextEntry
              autoCapitalize="none"
              autoCorrect={false}
              onFocus={scrollToBottom}
            />

            <Text style={[styles.label, { color: theme.text }]}>模型</Text>
            <TouchableOpacity
              style={[styles.input, { backgroundColor: theme.inputBackground, borderColor: theme.border }]}
              onPress={() => {
                setPickerText('');
                setPickerKind(activeTab);
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

            <TouchableOpacity
              style={[styles.advancedToggle, { backgroundColor: theme.surfaceAlt }]}
              onPress={() => setShowAdvanced((prev) => !prev)}
              activeOpacity={0.8}
            >
              <Text style={[styles.advancedToggleText, { color: theme.text }]}>
                高级设置{showAdvanced ? '（收起）' : ''}
              </Text>
            </TouchableOpacity>

            {showAdvanced ? (
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
              <TouchableOpacity style={[styles.cancelButton, { backgroundColor: theme.surfaceAlt }]} onPress={onClose} activeOpacity={0.8}>
                <Text style={[styles.cancelButtonText, { color: theme.textSoft }]}>取消</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[styles.saveButton, { backgroundColor: theme.accent }, saving && styles.buttonDisabled]}
                onPress={handleSave}
                disabled={saving}
                activeOpacity={0.8}
              >
                <Text style={[styles.saveButtonText, { color: theme.name === 'dark' ? '#0F1419' : '#ffffff' }]}>
                  {saving ? '保存中...' : '保存设置'}
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
                  该服务商未提供{pickerKind === 'vlm' ? '图片理解' : '对话'}模型
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
  tabBar: {
    flexDirection: 'row',
    paddingHorizontal: 16,
    paddingVertical: 10,
    gap: 10,
  },
  tabItem: {
    flex: 1,
    borderRadius: 10,
    paddingVertical: 9,
    alignItems: 'center',
    backgroundColor: '#e8edf2',
  },
  tabItemText: {
    fontSize: 14,
    fontWeight: '600',
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
  label: {
    fontSize: 15,
    fontWeight: '700',
    color: '#344252',
    marginBottom: 10,
    marginTop: 8,
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
  paramsInput: {
    minHeight: 100,
    textAlignVertical: 'top',
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
  cancelButton: {
    flex: 1,
    backgroundColor: '#e8edf2',
    borderRadius: 10,
    paddingVertical: 14,
    alignItems: 'center',
  },
  cancelButtonText: {
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
    opacity: 0.6,
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

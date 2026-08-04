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
  server_config,
} from '../config';
import { addDebugTrace } from '../utils/debug_trace';
import {
  fetchProviderModels,
  fetchProviderPresets,
  resolveProviderBaseUrl,
  resolveProviderModel,
} from '../utils/llm_client';
import type { LlmProviderPreset } from '../utils/llm_client';
import { getLlmApiKey, setLlmApiKey } from '../utils/llm_key_storage';
import { AppTheme, THEMES } from '../utils/theme';

interface LlmSettingsScreenProps {
  onClose: () => void;
  theme?: AppTheme;
}

export default function LlmSettingsScreen({ onClose, theme = THEMES.light }: LlmSettingsScreenProps) {
  const insets = useSafeAreaInsets();
  const scrollRef = useRef<ScrollView>(null);

  const [providers, setProviders] = useState<LlmProviderPreset[]>([]);
  const [llmProvider, setLlmProvider] = useState('');
  const [llmApiKey, setLlmApiKey] = useState('');
  const [llmModel, setLlmModel] = useState('');
  const [llmModels, setLlmModels] = useState<string[]>([]);
  const [modelsLoading, setModelsLoading] = useState(false);
  const [modelsError, setModelsError] = useState('');
  const [showModelPicker, setShowModelPicker] = useState(false);
  const [modelPickerText, setModelPickerText] = useState('');
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
        const [savedProvider, savedModel, savedKey] = await Promise.all([
          AsyncStorage.getItem(LLM_PROVIDER_STORAGE_KEY),
          AsyncStorage.getItem(LLM_MODEL_STORAGE_KEY),
          getLlmApiKey(),
        ]);
        if (!active) {
          return;
        }
        if (savedProvider) {
          setLlmProvider(savedProvider);
        }
        if (savedModel) {
          setLlmModel(savedModel);
        }
        if (savedKey) {
          setLlmApiKey(savedKey);
        }
      } catch (e) {
        addDebugTrace('llm_settings', 'load saved config failed', { error: String(e) });
      }
      try {
        const list = await fetchProviderPresets(server_config.BASE_URL);
        if (!active) {
          return;
        }
        setProviders(list);
        setLlmProvider((prev) => prev || (list[0]?.name ?? ''));
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

  useEffect(() => {
    const key = llmApiKey.trim();
    if (!key || !llmProvider) {
      setLlmModels([]);
      setModelsError('');
      return;
    }
    let active = true;
    const timer = setTimeout(async () => {
      setModelsLoading(true);
      setModelsError('');
      try {
        let baseUrl = resolveProviderBaseUrl(llmProvider, providers);
        if (!baseUrl) {
          baseUrl =
            (await AsyncStorage.getItem(LLM_PROVIDER_BASE_URL_STORAGE_KEY)) ?? '';
        }
        if (!baseUrl) {
          throw new Error('unknown provider');
        }
        const models = await fetchProviderModels(baseUrl, key);
        if (!active) {
          return;
        }
        setLlmModels(models);
        setLlmModel((prev) => (models.length > 0 && !models.includes(prev) ? models[0] : prev));
        setModelPickerText('');
      } catch (e) {
        if (!active) {
          return;
        }
        setModelsError(e instanceof Error ? e.message : String(e));
      } finally {
        if (active) {
          setModelsLoading(false);
        }
      }
    }, 600);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [llmProvider, llmApiKey, providers]);

  const scrollToBottom = () => {
    requestAnimationFrame(() => {
      scrollRef.current?.scrollToEnd({ animated: true });
    });
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      await setLlmApiKey(llmApiKey.trim());
      await AsyncStorage.setItem(LLM_PROVIDER_STORAGE_KEY, llmProvider);
      await AsyncStorage.setItem(LLM_MODEL_STORAGE_KEY, llmModel.trim());
      await AsyncStorage.setItem(
        LLM_PROVIDER_BASE_URL_STORAGE_KEY,
        resolveProviderBaseUrl(llmProvider, providers),
      );
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
              填写自己的 LLM API Key 后，聊天会由客户端直接调用大模型；key 只保存在本机，不会上传服务器。
            </Text>

            <Text style={[styles.label, { color: theme.text }]}>LLM 服务商</Text>
            <View style={styles.optionRow}>
              {providers.map((preset) => (
                <TouchableOpacity
                  key={preset.name}
                  style={[
                    styles.chip,
                    { backgroundColor: theme.surface, borderColor: theme.border },
                    llmProvider === preset.name && { backgroundColor: theme.accent, borderColor: theme.accent },
                  ]}
                  onPress={() => {
                    setLlmProvider(preset.name);
                    setLlmModel(resolveProviderModel(preset.name, providers));
                  }}
                  activeOpacity={0.75}
                >
                  <Text
                    style={[
                      styles.chipText,
                      { color: theme.textSoft },
                      llmProvider === preset.name && { color: theme.name === 'dark' ? '#0F1419' : '#ffffff', fontWeight: '700' },
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
            ) : null}

            <Text style={[styles.label, { color: theme.text }]}>LLM API Key</Text>
            <TextInput
              style={[styles.input, { backgroundColor: theme.inputBackground, borderColor: theme.border, color: theme.inputText }]}
              placeholder="填入后自动获取可用模型列表"
              placeholderTextColor={theme.placeholder}
              value={llmApiKey}
              onChangeText={setLlmApiKey}
              secureTextEntry
              autoCapitalize="none"
              autoCorrect={false}
              onFocus={scrollToBottom}
            />

            <Text style={[styles.label, { color: theme.text }]}>模型</Text>
            <TouchableOpacity
              style={[styles.input, { backgroundColor: theme.inputBackground, borderColor: theme.border }]}
              onPress={() => setShowModelPicker(true)}
              activeOpacity={0.7}
            >
              <Text style={{ color: theme.inputText, fontSize: 15 }} numberOfLines={1}>
                {llmModel || '请选择模型'}
              </Text>
              <Text style={{ color: theme.textMuted, fontSize: 12, marginTop: 2 }}>
                {modelsLoading
                  ? '正在获取模型列表…'
                  : modelsError
                    ? '获取失败，点击重试'
                    : `点击选择（${llmModels.length} 个可用模型）`}
              </Text>
            </TouchableOpacity>

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
        visible={showModelPicker}
        transparent
        animationType="slide"
        onRequestClose={() => setShowModelPicker(false)}
      >
        <View style={styles.modalOverlay}>
          <View style={[styles.modalCard, { backgroundColor: theme.surface }]}>
            <View style={styles.modalHeader}>
              <Text style={[styles.modalTitle, { color: theme.text }]}>选择模型</Text>
              <TouchableOpacity onPress={() => setShowModelPicker(false)} activeOpacity={0.7}>
                <Text style={[styles.modalCloseText, { color: theme.accentText }]}>关闭</Text>
              </TouchableOpacity>
            </View>
            <TextInput
              style={[styles.modalInput, { backgroundColor: theme.inputBackground, borderColor: theme.border, color: theme.inputText }]}
              placeholder="搜索模型"
              placeholderTextColor={theme.placeholder}
              value={modelPickerText}
              onChangeText={setModelPickerText}
              autoCapitalize="none"
              autoCorrect={false}
            />
            <ScrollView style={styles.modalList} keyboardShouldPersistTaps="handled">
              {modelsLoading ? (
                <Text style={[styles.modalEmptyText, { color: theme.textMuted }]}>正在获取模型列表…</Text>
              ) : modelsError ? (
                <Text style={[styles.modalEmptyText, { color: theme.textMuted }]}>获取失败：请检查api-key是否正确</Text>
              ) : llmModels.length === 0 ? (
                <Text style={[styles.modalEmptyText, { color: theme.textMuted }]}>暂无可用模型</Text>
              ) : (
                llmModels
                  .filter((m) => m.toLowerCase().includes(modelPickerText.trim().toLowerCase()))
                  .map((m) => (
                    <TouchableOpacity
                      key={m}
                      style={styles.modelOption}
                      onPress={() => {
                        setLlmModel(m);
                        setShowModelPicker(false);
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
  scrollArea: {
    flex: 1,
  },
  scrollContent: {
    padding: 20,
    paddingBottom: 40,
  },
  description: {
    color: '#65717f',
    fontSize: 13,
    lineHeight: 20,
    marginBottom: 16,
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

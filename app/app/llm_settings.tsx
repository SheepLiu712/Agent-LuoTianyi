import React, { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  Keyboard,
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
import AsyncStorage from '@react-native-async-storage/async-storage';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

const STORAGE_KEY = 'llm_endpoint_config';

interface LlmEndpointConfig {
  api_type: string;
  base_url: string;
  api_key: string;
  model: string;
  temperature: string;
  max_tokens: string;
  timeout: string;
  enable_thinking: boolean;
  default_headers: string;
}

const API_TYPES = [
  { value: 'custom', label: '自定义 (custom)' },
  { value: 'openai', label: 'OpenAI 兼容' },
  { value: 'requests', label: '直接请求 (requests)' },
];

const DEFAULT_CONFIG: LlmEndpointConfig = {
  api_type: 'custom',
  base_url: '',
  api_key: '',
  model: '',
  temperature: '0.7',
  max_tokens: '4096',
  timeout: '30',
  enable_thinking: false,
  default_headers: '',
};

interface LlmSettingsProps {
  onClose: () => void;
  onSave: (config: Record<string, unknown>) => void;
}

export default function LlmSettingsScreen({ onClose, onSave }: LlmSettingsProps) {
  const insets = useSafeAreaInsets();
  const [config, setConfig] = useState<LlmEndpointConfig>(DEFAULT_CONFIG);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const stored = await AsyncStorage.getItem(STORAGE_KEY);
        if (stored) {
          const parsed = JSON.parse(stored);
          setConfig({ ...DEFAULT_CONFIG, ...parsed });
        }
      } catch {
        // ignore
      } finally {
        setLoaded(true);
      }
    })();
  }, []);

  const updateField = useCallback(<K extends keyof LlmEndpointConfig>(
    key: K,
    value: LlmEndpointConfig[K],
  ) => {
    setConfig((prev) => ({ ...prev, [key]: value }));
  }, []);

  const handleSave = useCallback(async () => {
    Keyboard.dismiss();

    // 构建发送到服务端的配置对象
    const endpointConfig: Record<string, unknown> = {
      api_type: config.api_type,
      base_url: config.base_url.trim(),
    };

    if (config.api_key.trim()) {
      endpointConfig.api_key = config.api_key.trim();
    }
    if (config.model.trim()) {
      endpointConfig.model = config.model.trim();
    }

    const temperature = parseFloat(config.temperature);
    if (!isNaN(temperature)) {
      endpointConfig.temperature = Math.min(2, Math.max(0, temperature));
    }

    const maxTokens = parseInt(config.max_tokens, 10);
    if (!isNaN(maxTokens)) {
      endpointConfig.max_tokens = Math.min(65536, Math.max(256, maxTokens));
    }

    const timeout = parseInt(config.timeout, 10);
    if (!isNaN(timeout)) {
      endpointConfig.timeout = Math.min(300, Math.max(1, timeout));
    }

    endpointConfig.enable_thinking = config.enable_thinking;

    if (config.default_headers.trim()) {
      try {
        endpointConfig.default_headers = JSON.parse(config.default_headers.trim());
      } catch {
        Alert.alert('格式错误', '自定义请求头不是合法的 JSON 格式');
        return;
      }
    }

    // 持久化到本地
    try {
      await AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(config));
    } catch {
      // ignore
    }

    onSave({ llm_endpoint: endpointConfig });
    onClose();
  }, [config, onSave, onClose]);

  if (!loaded) {
    return (
      <View style={[styles.container, { paddingTop: insets.top }]}>
        <Text style={styles.loadingText}>加载中...</Text>
      </View>
    );
  }

  return (
    <KeyboardAvoidingView
      style={{ flex: 1 }}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <View style={[styles.container, { paddingTop: insets.top, paddingBottom: insets.bottom }]}>
        {/* 标题栏 */}
        <View style={styles.header}>
          <TouchableOpacity onPress={onClose} style={styles.headerButton}>
            <Text style={styles.headerButtonText}>取消</Text>
          </TouchableOpacity>
          <Text style={styles.headerTitle}>LLM 端点配置</Text>
          <TouchableOpacity onPress={handleSave} style={styles.headerButton}>
            <Text style={[styles.headerButtonText, styles.saveButtonText]}>保存</Text>
          </TouchableOpacity>
        </View>

        <ScrollView
          style={styles.scroll}
          contentContainerStyle={styles.scrollContent}
          keyboardShouldPersistTaps="handled"
        >
          {/* API 类型 */}
          <Text style={styles.label}>API 类型</Text>
          <View style={styles.apiTypeRow}>
            {API_TYPES.map((t) => (
              <TouchableOpacity
                key={t.value}
                style={[styles.apiTypeChip, config.api_type === t.value && styles.apiTypeChipActive]}
                onPress={() => updateField('api_type', t.value)}
              >
                <Text style={[styles.apiTypeChipText, config.api_type === t.value && styles.apiTypeChipTextActive]}>
                  {t.label}
                </Text>
              </TouchableOpacity>
            ))}
          </View>

          {/* 端点地址 */}
          <Text style={styles.label}>端点地址 (base_url)</Text>
          <TextInput
            style={styles.input}
            placeholder="https://your-api.com/v1"
            placeholderTextColor="#aaa"
            value={config.base_url}
            onChangeText={(v) => updateField('base_url', v)}
            autoCapitalize="none"
            autoCorrect={false}
            keyboardType="url"
          />

          {/* API 密钥 */}
          <Text style={styles.label}>API 密钥</Text>
          <TextInput
            style={styles.input}
            placeholder="sk-..."
            placeholderTextColor="#aaa"
            value={config.api_key}
            onChangeText={(v) => updateField('api_key', v)}
            autoCapitalize="none"
            autoCorrect={false}
            secureTextEntry
          />

          {/* 模型名称 */}
          <Text style={styles.label}>模型名称</Text>
          <TextInput
            style={styles.input}
            placeholder='gpt-4, deepseek-chat, ...'
            placeholderTextColor="#aaa"
            value={config.model}
            onChangeText={(v) => updateField('model', v)}
            autoCapitalize="none"
            autoCorrect={false}
          />

          {/* 温度 */}
          <Text style={styles.label}>温度 (temperature): {config.temperature}</Text>
          <TextInput
            style={styles.input}
            placeholder="0.0 ~ 2.0"
            placeholderTextColor="#aaa"
            value={config.temperature}
            onChangeText={(v) => updateField('temperature', v)}
            keyboardType="decimal-pad"
          />

          {/* 最大输出 tokens */}
          <Text style={styles.label}>最大输出 tokens</Text>
          <TextInput
            style={styles.input}
            placeholder="256 ~ 65536"
            placeholderTextColor="#aaa"
            value={config.max_tokens}
            onChangeText={(v) => updateField('max_tokens', v)}
            keyboardType="number-pad"
          />

          {/* 超时时间 */}
          <Text style={styles.label}>请求超时 (秒)</Text>
          <TextInput
            style={styles.input}
            placeholder="1 ~ 300"
            placeholderTextColor="#aaa"
            value={config.timeout}
            onChangeText={(v) => updateField('timeout', v)}
            keyboardType="number-pad"
          />

          {/* 启用思考 */}
          <View style={styles.switchRow}>
            <Text style={styles.label}>启用思考 (enable_thinking)</Text>
            <Switch
              value={config.enable_thinking}
              onValueChange={(v) => updateField('enable_thinking', v)}
              trackColor={{ false: '#ddd', true: '#66CCFF' }}
              thumbColor={config.enable_thinking ? '#fff' : '#f4f3f4'}
            />
          </View>

          {/* 自定义请求头 */}
          <Text style={styles.label}>自定义请求头 (JSON, 可选)</Text>
          <TextInput
            style={[styles.input, styles.multilineInput]}
            placeholder='{"X-Custom-Header": "value"}'
            placeholderTextColor="#aaa"
            value={config.default_headers}
            onChangeText={(v) => updateField('default_headers', v)}
            autoCapitalize="none"
            autoCorrect={false}
            multiline
            numberOfLines={3}
            textAlignVertical="top"
          />

          <View style={{ height: 40 }} />
        </ScrollView>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#f5f5f5',
  },
  loadingText: {
    textAlign: 'center',
    marginTop: 40,
    color: '#999',
    fontSize: 16,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    paddingVertical: 12,
    backgroundColor: '#fff',
    borderBottomWidth: 1,
    borderBottomColor: '#e0e0e0',
  },
  headerButton: {
    paddingHorizontal: 4,
    paddingVertical: 8,
    minWidth: 50,
  },
  headerButtonText: {
    fontSize: 16,
    color: '#666',
  },
  saveButtonText: {
    color: '#66CCFF',
    fontWeight: '600',
  },
  headerTitle: {
    fontSize: 17,
    fontWeight: '600',
    color: '#333',
  },
  scroll: {
    flex: 1,
  },
  scrollContent: {
    paddingHorizontal: 20,
    paddingTop: 20,
  },
  label: {
    fontSize: 14,
    color: '#555',
    marginBottom: 6,
    marginLeft: 4,
  },
  input: {
    backgroundColor: '#ffffff',
    borderRadius: 12,
    paddingHorizontal: 16,
    paddingVertical: 12,
    fontSize: 15,
    color: '#333',
    marginBottom: 16,
    borderWidth: 1,
    borderColor: '#e0e0e0',
  },
  multilineInput: {
    minHeight: 72,
    paddingTop: 12,
  },
  apiTypeRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    marginBottom: 16,
    gap: 8,
  },
  apiTypeChip: {
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: '#ddd',
    backgroundColor: '#fff',
  },
  apiTypeChipActive: {
    borderColor: '#66CCFF',
    backgroundColor: '#E8F7FF',
  },
  apiTypeChipText: {
    fontSize: 13,
    color: '#666',
  },
  apiTypeChipTextActive: {
    color: '#66CCFF',
    fontWeight: '600',
  },
  switchRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 16,
    paddingRight: 4,
  },
});

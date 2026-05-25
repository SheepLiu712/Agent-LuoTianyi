import React, { useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { auth } from '../components/auth';
import { getPreferences, overwritePreferences, UserPreferences } from '../utils/getPreferences';
import { addDebugTrace } from '../utils/debug_trace';

interface PreferencesScreenProps {
  onClose: () => void;
}

const RELATIONSHIP_OPTIONS = ['朋友', '知己', '粉丝', '搭档', '家人', '其他'];
const STYLE_OPTIONS = ['活泼可爱', '温柔可人', '俏皮调皮', '诗意文艺', '热情洋溢', '文静恬淡', '随意自然'];

export default function PreferencesScreen({ onClose }: PreferencesScreenProps) {
  const insets = useSafeAreaInsets();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const [relationship, setRelationship] = useState('');
  const [speakingStyle, setSpeakingStyle] = useState('');
  const [personalityText, setPersonalityText] = useState('');
  const [customContext, setCustomContext] = useState('');

  // 从服务端拉取偏好设置
  useEffect(() => {
    const fetchPrefs = async () => {
      if (!auth.username || !auth.message_token) {
        setLoading(false);
        return;
      }
      setLoading(true);
      try {
        const prefs = await getPreferences(auth.username, auth.message_token);
        if (prefs) {
          setRelationship(prefs.relationship || '');
          setSpeakingStyle(prefs.speaking_style || '');
          setPersonalityText(Array.isArray(prefs.personality_traits) ? prefs.personality_traits.join('、') : '');
          setCustomContext(prefs.custom_context || '');
        }
      } catch (e) {
        addDebugTrace('preferences', 'fetch error on screen', { error: String(e) });
      } finally {
        setLoading(false);
      }
    };
    fetchPrefs();
  }, []);

  const handleSave = async () => {
    if (!auth.username || !auth.message_token) {
      Alert.alert('错误', '用户未登录，无法保存偏好设置');
      return;
    }

    const personality_traits = personalityText
      .split(/[，,、]/)
      .map(s => s.trim())
      .filter(s => s.length > 0);

    const preferences: UserPreferences = {
      relationship: relationship && relationship !== '朋友' ? relationship : '',
      speaking_style: speakingStyle && speakingStyle !== '活泼可爱' ? speakingStyle : '',
      personality_traits,
      custom_context: customContext,
    };

    setSaving(true);
    try {
      const ok = await overwritePreferences(auth.username, auth.message_token, preferences);
      if (ok) {
        Alert.alert('成功', '偏好设置已保存');
        onClose();
      } else {
        Alert.alert('保存失败', '请检查网络连接后重试');
      }
    } catch (e: any) {
      Alert.alert('保存失败', e.message || '网络错误');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <View style={[styles.container, { paddingTop: insets.top }]}>
        <View style={styles.loadingContainer}>
          <ActivityIndicator size="large" color="#66CCFF" />
        </View>
      </View>
    );
  }

  return (
    <KeyboardAvoidingView
      style={{ flex: 1 }}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <View style={[styles.container, { paddingTop: insets.top, paddingBottom: insets.bottom }]}>
        {/* 顶部导航栏 */}
        <View style={styles.header}>
          <TouchableOpacity
            style={styles.backButton}
            onPress={onClose}
            activeOpacity={0.7}
          >
            <Text style={styles.backButtonText}>← 返回</Text>
          </TouchableOpacity>
          <Text style={styles.headerTitle}>相处模式</Text>
          <View style={styles.headerPlaceholder} />
        </View>

        <ScrollView
          style={styles.scrollArea}
          contentContainerStyle={styles.scrollContent}
          keyboardShouldPersistTaps="handled"
        >
          {/* 关系类型 */}
          <Text style={styles.label}>你希望和天依的关系是：</Text>
          <View style={styles.optionRow}>
            {RELATIONSHIP_OPTIONS.map(opt => (
              <TouchableOpacity
                key={opt}
                style={[styles.chip, relationship === opt && styles.chipSelected]}
                onPress={() => setRelationship(opt)}
                activeOpacity={0.7}
              >
                <Text style={[styles.chipText, relationship === opt && styles.chipTextSelected]}>
                  {opt}
                </Text>
              </TouchableOpacity>
            ))}
          </View>

          {/* 表达风格 */}
          <Text style={styles.label}>你希望天依的表达风格偏向：</Text>
          <View style={styles.optionRow}>
            {STYLE_OPTIONS.map(opt => (
              <TouchableOpacity
                key={opt}
                style={[styles.chip, speakingStyle === opt && styles.chipSelected]}
                onPress={() => setSpeakingStyle(opt)}
                activeOpacity={0.7}
              >
                <Text style={[styles.chipText, speakingStyle === opt && styles.chipTextSelected]}>
                  {opt}
                </Text>
              </TouchableOpacity>
            ))}
          </View>

          {/* 性格特点 */}
          <Text style={styles.label}>你希望天依的性格特点（用逗号分隔，可选）：</Text>
          <TextInput
            style={styles.input}
            placeholder="例如：温柔、耐心、善解人意"
            placeholderTextColor="#aaa"
            value={personalityText}
            onChangeText={setPersonalityText}
          />

          {/* 自定义上下文 */}
          <Text style={styles.label}>其他你想让天依知道的（可选）：</Text>
          <TextInput
            style={[styles.input, styles.textArea]}
            placeholder="在这里添加任何你想让天依知道的关于你们关系的信息..."
            placeholderTextColor="#aaa"
            value={customContext}
            onChangeText={setCustomContext}
            multiline
            numberOfLines={3}
          />

          {/* 按钮 */}
          <View style={styles.buttonRow}>
            <TouchableOpacity
              style={styles.cancelButton}
              onPress={onClose}
              activeOpacity={0.8}
            >
              <Text style={styles.cancelButtonText}>取消</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[styles.saveButton, saving && styles.buttonDisabled]}
              onPress={handleSave}
              disabled={saving}
              activeOpacity={0.8}
            >
              <Text style={styles.saveButtonText}>
                {saving ? '保存中...' : '保存设置'}
              </Text>
            </TouchableOpacity>
          </View>
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
  loadingContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    paddingVertical: 12,
    backgroundColor: '#ffffff',
    borderBottomWidth: 1,
    borderBottomColor: '#e0e0e0',
  },
  backButton: {
    paddingVertical: 4,
    paddingHorizontal: 8,
  },
  backButtonText: {
    fontSize: 16,
    color: '#66CCFF',
    fontWeight: '600',
  },
  headerTitle: {
    fontSize: 17,
    fontWeight: 'bold',
    color: '#333',
  },
  headerPlaceholder: {
    width: 60,
  },
  scrollArea: {
    flex: 1,
  },
  scrollContent: {
    padding: 20,
    paddingBottom: 40,
  },
  label: {
    fontSize: 15,
    fontWeight: '600',
    color: '#444',
    marginBottom: 10,
    marginTop: 8,
  },
  optionRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
    marginBottom: 12,
  },
  chip: {
    backgroundColor: '#ffffff',
    borderRadius: 20,
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderWidth: 1,
    borderColor: '#e0e0e0',
  },
  chipSelected: {
    backgroundColor: '#66CCFF',
    borderColor: '#66CCFF',
  },
  chipText: {
    fontSize: 14,
    color: '#666',
  },
  chipTextSelected: {
    color: '#ffffff',
    fontWeight: '600',
  },
  input: {
    backgroundColor: '#ffffff',
    borderRadius: 12,
    paddingHorizontal: 16,
    paddingVertical: 12,
    fontSize: 15,
    color: '#333',
    marginBottom: 12,
    borderWidth: 1,
    borderColor: '#e0e0e0',
  },
  textArea: {
    minHeight: 80,
    textAlignVertical: 'top',
  },
  buttonRow: {
    flexDirection: 'row',
    marginTop: 16,
    gap: 12,
  },
  cancelButton: {
    flex: 1,
    backgroundColor: '#e0e0e0',
    borderRadius: 12,
    paddingVertical: 14,
    alignItems: 'center',
  },
  cancelButtonText: {
    color: '#666',
    fontSize: 15,
    fontWeight: '600',
  },
  saveButton: {
    flex: 1,
    backgroundColor: '#4CAF50',
    borderRadius: 12,
    paddingVertical: 14,
    alignItems: 'center',
  },
  saveButtonText: {
    color: '#ffffff',
    fontSize: 15,
    fontWeight: '600',
  },
  buttonDisabled: {
    opacity: 0.6,
  },
});

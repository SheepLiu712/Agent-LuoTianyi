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
import { addDebugTrace } from '../utils/debug_trace';
import { getPreferences, overwritePreferences, UserPreferences } from '../utils/getPreferences';
import { AppTheme, THEMES } from '../utils/theme';

interface PreferencesScreenProps {
  onClose: () => void;
  theme?: AppTheme;
}

const RELATIONSHIP_OPTIONS = ['朋友', '知己', '偶像', '搭档', '家人'];
const STYLE_OPTIONS = ['活泼可爱', '温柔可人', '文静恬淡'];

function pickPersonalityText(prefs: UserPreferences) {
  if (typeof prefs['#sym:personality_text'] === 'string') {
    return prefs['#sym:personality_text'];
  }
  if (Array.isArray(prefs.personality_traits)) {
    return prefs.personality_traits.join('、');
  }
  return '';
}

export default function PreferencesScreen({ onClose, theme = THEMES.light }: PreferencesScreenProps) {
  const insets = useSafeAreaInsets();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const [relationship, setRelationship] = useState('');
  const [speakingStyle, setSpeakingStyle] = useState('');
  const [personalityText, setPersonalityText] = useState('');
  const [customContext, setCustomContext] = useState('');

  useEffect(() => {
    const fetchPrefs = async () => {
      if (!auth.username || !auth.message_token) {
        setLoading(false);
        return;
      }

      setLoading(true);
      try {
        const prefs = await getPreferences(auth.username, auth.message_token);
        if (!prefs) {
          return;
        }

        setRelationship(prefs.relationship || '');
        setSpeakingStyle(prefs.speaking_style || '');
        setPersonalityText(pickPersonalityText(prefs));
        setCustomContext(prefs.custom_context || '');
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

    const finalRelationship = relationship.trim();
    const finalSpeakingStyle = speakingStyle.trim();

    const preferences: UserPreferences = {
      relationship: finalRelationship,
      speaking_style: finalSpeakingStyle,
      '#sym:personality_text': personalityText.trim(),
      custom_context: customContext.trim(),
    };

    setSaving(true);
    try {
      addDebugTrace('preferences', 'saving preferences', preferences);
      const ok = await overwritePreferences(auth.username, auth.message_token, preferences);
      if (ok) {
        Alert.alert('成功', '偏好设置已保存');
        onClose();
      } else {
        Alert.alert('保存失败', '请检查网络连接后重试');
      }
    } catch (e: any) {
      Alert.alert('保存失败', e?.message || '网络错误');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <View style={[styles.overlayRoot, styles.container, { paddingTop: insets.top, paddingBottom: insets.bottom, backgroundColor: theme.root }]}>
        <View style={styles.loadingContainer}>
          <ActivityIndicator size="large" color={theme.accent} />
          <Text style={[styles.loadingText, { color: theme.textMuted }]}>正在加载偏好设置...</Text>
        </View>
      </View>
    );
  }

  return (
    <KeyboardAvoidingView style={[styles.overlayRoot, { backgroundColor: theme.root }]} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <View style={[styles.container, { paddingTop: insets.top, paddingBottom: insets.bottom, backgroundColor: theme.root }]}>
        <View style={[styles.header, { backgroundColor: theme.surface, borderBottomColor: theme.border }]}>
          <TouchableOpacity style={styles.backButton} onPress={onClose} activeOpacity={0.7}>
            <Text style={[styles.backButtonText, { color: theme.accentText }]}>返回</Text>
          </TouchableOpacity>
          <Text style={[styles.headerTitle, { color: theme.text }]}>和天依的相处模式</Text>
          <View style={styles.headerPlaceholder} />
        </View>

        <ScrollView style={styles.scrollArea} contentContainerStyle={styles.scrollContent} keyboardShouldPersistTaps="handled">
          <Text style={[styles.description, { color: theme.textMuted }]}>告诉天依你们之间的关系和相处方式，她会更好地理解你。</Text>

          <Text style={[styles.label, { color: theme.text }]}>你希望天依是你的：</Text>
          <TextInput
            style={[styles.input, { backgroundColor: theme.inputBackground, borderColor: theme.border, color: theme.inputText }]}
            placeholder="例如：朋友"
            placeholderTextColor={theme.placeholder}
            value={relationship}
            onChangeText={setRelationship}
          />
          <View style={styles.optionRow}>
            {RELATIONSHIP_OPTIONS.map((opt) => (
              <TouchableOpacity
                key={opt}
                style={[
                  styles.chip,
                  { backgroundColor: theme.surface, borderColor: theme.border },
                  relationship === opt && { backgroundColor: theme.accent, borderColor: theme.accent },
                ]}
                onPress={() => setRelationship(opt)}
                activeOpacity={0.75}
              >
                <Text style={[styles.chipText, { color: theme.textSoft }, relationship === opt && { color: theme.name === 'dark' ? '#0F1419' : '#ffffff', fontWeight: '700' }]}>{opt}</Text>
              </TouchableOpacity>
            ))}
          </View>

          <Text style={[styles.label, { color: theme.text }]}>你希望天依的表达风格偏向：</Text>
          <TextInput
            style={[styles.input, { backgroundColor: theme.inputBackground, borderColor: theme.border, color: theme.inputText }]}
            placeholder="例如：活泼可爱"
            placeholderTextColor={theme.placeholder}
            value={speakingStyle}
            onChangeText={setSpeakingStyle}
          />
          <View style={styles.optionRow}>
            {STYLE_OPTIONS.map((opt) => (
              <TouchableOpacity
                key={opt}
                style={[
                  styles.chip,
                  { backgroundColor: theme.surface, borderColor: theme.border },
                  speakingStyle === opt && { backgroundColor: theme.accent, borderColor: theme.accent },
                ]}
                onPress={() => setSpeakingStyle(opt)}
                activeOpacity={0.75}
              >
                <Text style={[styles.chipText, { color: theme.textSoft }, speakingStyle === opt && { color: theme.name === 'dark' ? '#0F1419' : '#ffffff', fontWeight: '700' }]}>{opt}</Text>
              </TouchableOpacity>
            ))}
          </View>

          <Text style={[styles.label, { color: theme.text }]}>你希望天依的性格特点（可选）：</Text>
          <TextInput
            style={[styles.input, { backgroundColor: theme.inputBackground, borderColor: theme.border, color: theme.inputText }]}
            placeholder="例如：温柔、耐心、善解人意"
            placeholderTextColor={theme.placeholder}
            value={personalityText}
            onChangeText={setPersonalityText}
          />

          <Text style={[styles.label, { color: theme.text }]}>其他你想让天依知道的（可选）：</Text>
          <TextInput
            style={[styles.input, styles.textArea, { backgroundColor: theme.inputBackground, borderColor: theme.border, color: theme.inputText }]}
            placeholder="在这里添加任何你想让天依知道的关于你们关系的信息..."
            placeholderTextColor={theme.placeholder}
            value={customContext}
            onChangeText={setCustomContext}
            multiline
            numberOfLines={4}
          />

          <View style={styles.buttonRow}>
            <TouchableOpacity style={[styles.cancelButton, { backgroundColor: theme.surfaceAlt }]} onPress={onClose} activeOpacity={0.8}>
              <Text style={[styles.cancelButtonText, { color: theme.textSoft }]}>取消</Text>
            </TouchableOpacity>
            <TouchableOpacity style={[styles.saveButton, { backgroundColor: theme.accent }, saving && styles.buttonDisabled]} onPress={handleSave} disabled={saving} activeOpacity={0.8}>
              <Text style={[styles.saveButtonText, { color: theme.name === 'dark' ? '#0F1419' : '#ffffff' }]}>{saving ? '保存中...' : '保存设置'}</Text>
            </TouchableOpacity>
          </View>
        </ScrollView>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  overlayRoot: {
    ...StyleSheet.absoluteFillObject,
    zIndex: 120,
    backgroundColor: '#f5f7fa',
  },
  container: {
    flex: 1,
    backgroundColor: '#f5f7fa',
  },
  loadingContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  loadingText: {
    marginTop: 12,
    color: '#65717f',
    fontSize: 14,
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
  chipSelected: {
    backgroundColor: '#66CCFF',
    borderColor: '#66CCFF',
  },
  chipText: {
    fontSize: 13,
    color: '#4b5967',
  },
  chipTextSelected: {
    color: '#ffffff',
    fontWeight: '700',
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
  textArea: {
    minHeight: 96,
    textAlignVertical: 'top',
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
});

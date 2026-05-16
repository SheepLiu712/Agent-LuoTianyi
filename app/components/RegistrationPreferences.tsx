import React, { useState } from 'react';
import {
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';

export interface UserPreferences {
  relationship: string;
  speaking_style: string;
  personality_traits: string[];
  custom_context: string;
}

interface RegistrationPreferencesProps {
  onSave: (preferences: UserPreferences) => void;
  onSkip: () => void;
}

const RELATIONSHIP_OPTIONS = ['朋友', '知己', '粉丝', '搭档', '家人', '其他'];
const STYLE_OPTIONS = ['活泼可爱', '温柔可人', '俏皮调皮', '诗意文艺', '热情洋溢', '文静恬淡', '随意自然'];

export default function RegistrationPreferences({ onSave, onSkip }: RegistrationPreferencesProps) {
  const [relationship, setRelationship] = useState('');
  const [speakingStyle, setSpeakingStyle] = useState('');
  const [personalityText, setPersonalityText] = useState('');
  const [customContext, setCustomContext] = useState('');

  const handleSave = () => {
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
    onSave(preferences);
  };

  return (
    <KeyboardAvoidingView
      style={{ flex: 1 }}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <ScrollView
        style={styles.container}
        contentContainerStyle={styles.content}
        keyboardShouldPersistTaps="handled"
      >
        {/* 标题 */}
        <Text style={styles.title}>💬 和天依的相处模式</Text>
        <Text style={styles.description}>
          你可以在这里告诉天依你们之间的关系和相处方式，这样天依会更好地了解你！
          当然，你也可以跳过这些设置直接开始聊天~
        </Text>

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

        <View style={styles.buttonRow}>
          {/* 先试试看按钮（高亮） */}
          <TouchableOpacity
            style={styles.skipButton}
            onPress={onSkip}
            activeOpacity={0.8}
          >
            <Text style={styles.skipButtonText}>✨ 先试试看！</Text>
          </TouchableOpacity>

          {/* 保存按钮 */}
          <TouchableOpacity
            style={styles.saveButton}
            onPress={handleSave}
            activeOpacity={0.8}
          >
            <Text style={styles.saveButtonText}>保存设置</Text>
          </TouchableOpacity>
        </View>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#f5f5f5',
  },
  content: {
    padding: 24,
    paddingBottom: 40,
  },
  title: {
    fontSize: 24,
    fontWeight: 'bold',
    color: '#66CCFF',
    textAlign: 'center',
    marginBottom: 12,
  },
  description: {
    fontSize: 14,
    color: '#666',
    textAlign: 'center',
    marginBottom: 24,
    lineHeight: 20,
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
  skipButton: {
    flex: 1,
    backgroundColor: '#66CCFF',
    borderRadius: 12,
    paddingVertical: 14,
    alignItems: 'center',
    shadowColor: '#66CCFF',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.3,
    shadowRadius: 4,
    elevation: 4,
  },
  skipButtonText: {
    color: '#ffffff',
    fontSize: 16,
    fontWeight: '700',
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
});

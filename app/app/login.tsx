import { useState } from 'react';
import {
  Alert,
  Keyboard,
  KeyboardAvoidingView, Platform, ScrollView,
  StyleSheet,
  Text, TextInput, TouchableOpacity,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

interface LoginScreenProps {
  onLogin: (username: string, password: string, autoLogin: boolean) => Promise<{ success: boolean; message: string }>;
  onRegister: (username: string, password: string, inviteCode: string) => Promise<{ success: boolean; message: string }>;
}

type TabType = 'login' | 'register';

export default function LoginScreen({ onLogin, onRegister }: LoginScreenProps) {
  const insets = useSafeAreaInsets();
  const [activeTab, setActiveTab] = useState<TabType>('login');
  const [loading, setLoading] = useState(false);

  // 登录表单
  const [loginUsername, setLoginUsername] = useState('');
  const [loginPassword, setLoginPassword] = useState('');
  const [autoLogin, setAutoLogin] = useState(false);

  // 注册表单
  const [regUsername, setRegUsername] = useState('');
  const [regPassword, setRegPassword] = useState('');
  const [inviteCode, setInviteCode] = useState('');

  const handleLogin = async () => {
    Keyboard.dismiss();
    setLoading(true);
    const result = await onLogin(loginUsername, loginPassword, autoLogin);
    setLoading(false);
    if (!result.success) {
      Alert.alert('登录失败', result.message);
    }
  };

  const handleRegister = async () => {
    Keyboard.dismiss();
    setLoading(true);
    const result = await onRegister(regUsername, regPassword, inviteCode);
    setLoading(false);
    if (result.success) {
      Alert.alert('注册成功', result.message, [
        {
          text: '去登录',
          onPress: () => {
            setActiveTab('login');
            setLoginUsername(regUsername);
          },
        },
      ]);
    } else {
      Alert.alert('注册失败', result.message);
    }
  };

  return (
    <KeyboardAvoidingView
      style={{ flex: 1 }}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <View style={[styles.container, { paddingTop: insets.top + 40, paddingBottom: insets.bottom }]}>
        {/* 标题 */}
        <Text style={styles.title}>小洛聊天室</Text>
        <Text style={styles.subtitle}>Chat with LuoTianyi</Text>

        {/* Tab 切换 */}
        <View style={styles.tabContainer}>
          <TouchableOpacity
            style={[styles.tab, activeTab === 'login' && styles.activeTab]}
            onPress={() => setActiveTab('login')}
          >
            <Text style={[styles.tabText, activeTab === 'login' && styles.activeTabText]}>
              登录
            </Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[styles.tab, activeTab === 'register' && styles.activeTab]}
            onPress={() => setActiveTab('register')}
          >
            <Text style={[styles.tabText, activeTab === 'register' && styles.activeTabText]}>
              注册
            </Text>
          </TouchableOpacity>
        </View>

        {/* 表单区域 */}
        <ScrollView
          style={styles.formScrollView}
          contentContainerStyle={styles.formContainer}
          keyboardShouldPersistTaps="handled"
        >
          {activeTab === 'login' ? (
            /* ========== 登录表单 ========== */
            <View>
              <Text style={styles.label}>用户名</Text>
              <TextInput
                style={styles.input}
                placeholder="请输入用户名"
                placeholderTextColor="#aaa"
                value={loginUsername}
                onChangeText={setLoginUsername}
                autoCapitalize="none"
              />

              <Text style={styles.label}>密码</Text>
              <TextInput
                style={styles.input}
                placeholder="请输入密码"
                placeholderTextColor="#aaa"
                value={loginPassword}
                onChangeText={setLoginPassword}
                secureTextEntry
              />

              {/* 自动登录勾选 */}
              <TouchableOpacity
                style={styles.checkboxRow}
                onPress={() => setAutoLogin(!autoLogin)}
                activeOpacity={0.7}
              >
                <View style={[styles.checkbox, autoLogin && styles.checkboxChecked]}>
                  {autoLogin && <Text style={styles.checkmark}>✓</Text>}
                </View>
                <Text style={styles.checkboxLabel}>自动登录</Text>
              </TouchableOpacity>

              {/* 登录按钮 */}
              <TouchableOpacity
                style={[styles.button, loading && styles.buttonDisabled]}
                onPress={handleLogin}
                disabled={loading}
                activeOpacity={0.8}
              >
                <Text style={styles.buttonText}>{loading ? '登录中...' : '登录'}</Text>
              </TouchableOpacity>
            </View>
          ) : (
            /* ========== 注册表单 ========== */
            <View>
              <Text style={styles.label}>用户名</Text>
              <TextInput
                style={styles.input}
                placeholder="请输入用户名"
                placeholderTextColor="#aaa"
                value={regUsername}
                onChangeText={setRegUsername}
                autoCapitalize="none"
              />

              <Text style={styles.label}>密码</Text>
              <TextInput
                style={styles.input}
                placeholder="请输入密码"
                placeholderTextColor="#aaa"
                value={regPassword}
                onChangeText={setRegPassword}
                secureTextEntry
              />

              <Text style={styles.label}>邀请码</Text>
              <TextInput
                style={styles.input}
                placeholder="请输入邀请码"
                placeholderTextColor="#aaa"
                value={inviteCode}
                onChangeText={setInviteCode}
                autoCapitalize="none"
              />

              {/* 注册按钮 */}
              <TouchableOpacity
                style={[styles.button, styles.registerButton, loading && styles.buttonDisabled]}
                onPress={handleRegister}
                disabled={loading}
                activeOpacity={0.8}
              >
                <Text style={styles.buttonText}>{loading ? '注册中...' : '注册'}</Text>
              </TouchableOpacity>
            </View>
          )}
        </ScrollView>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#f5f5f5',
    paddingHorizontal: 30,
  },
  title: {
    fontSize: 32,
    fontWeight: 'bold',
    color: '#66CCFF',
    textAlign: 'center',
    marginBottom: 4,
  },
  subtitle: {
    fontSize: 14,
    color: '#999',
    textAlign: 'center',
    marginBottom: 30,
  },
  tabContainer: {
    flexDirection: 'row',
    backgroundColor: '#e0e0e0',
    borderRadius: 12,
    padding: 3,
    marginBottom: 25,
  },
  tab: {
    flex: 1,
    paddingVertical: 10,
    borderRadius: 10,
    alignItems: 'center',
  },
  activeTab: {
    backgroundColor: '#ffffff',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.1,
    shadowRadius: 2,
    elevation: 2,
  },
  tabText: {
    fontSize: 15,
    color: '#999',
    fontWeight: '500',
  },
  activeTabText: {
    color: '#66CCFF',
    fontWeight: '600',
  },
  formScrollView: {
    flex: 1,
  },
  formContainer: {
    paddingBottom: 30,
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
  checkboxRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 24,
    marginLeft: 4,
  },
  checkbox: {
    width: 20,
    height: 20,
    borderRadius: 4,
    borderWidth: 2,
    borderColor: '#ccc',
    marginRight: 8,
    justifyContent: 'center',
    alignItems: 'center',
  },
  checkboxChecked: {
    backgroundColor: '#66CCFF',
    borderColor: '#66CCFF',
  },
  checkmark: {
    color: '#fff',
    fontSize: 13,
    fontWeight: 'bold',
    lineHeight: 16,
  },
  checkboxLabel: {
    fontSize: 14,
    color: '#666',
  },
  button: {
    backgroundColor: '#66CCFF',
    borderRadius: 12,
    paddingVertical: 14,
    alignItems: 'center',
    marginTop: 8,
    shadowColor: '#66CCFF',
    shadowOffset: { width: 0, height: 3 },
    shadowOpacity: 0.3,
    shadowRadius: 5,
    elevation: 4,
  },
  registerButton: {
    backgroundColor: '#88EDFF',
  },
  buttonDisabled: {
    opacity: 0.6,
  },
  buttonText: {
    color: '#ffffff',
    fontSize: 16,
    fontWeight: '600',
  },
});

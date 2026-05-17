import React, { useState } from 'react';
import {
  Alert,
  Keyboard,
  KeyboardAvoidingView, Modal, Platform, ScrollView,
  StyleSheet,
  Text, TextInput, TouchableOpacity,
  View,
} from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { server_config } from '../config';

const PREFERENCE_KEY = 'user_preferences';

function PreferenceGuideModal({ visible, onComplete }: { visible: boolean; onComplete: (prefs: Record<string, string>) => void }) {
  const [relationship, setRelationship] = useState('朋友');
  const [speakingStyle, setSpeakingStyle] = useState('');

  const relationships = ['朋友', '知己', '粉丝', '搭档', '家人', '其他'];
  const styles = ['', '活泼可爱', '温柔可人', '俏皮调皮', '诗意文艺', '热情洋溢', '文静恬淡'];

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={() => onComplete({})}>
      <View style={modalStyles.overlay}>
        <View style={modalStyles.container}>
          <Text style={modalStyles.title}>欢迎~</Text>
          <Text style={modalStyles.subtitle}>在开始聊天前，可以先告诉天依你想和她怎么相处~</Text>

          <Text style={modalStyles.label}>你和天依的关系：</Text>
          <View style={modalStyles.optionsRow}>
            {relationships.map((r) => (
              <TouchableOpacity
                key={r}
                style={[modalStyles.chip, relationship === r && modalStyles.chipActive]}
                onPress={() => setRelationship(r)}
              >
                <Text style={[modalStyles.chipText, relationship === r && modalStyles.chipTextActive]}>{r}</Text>
              </TouchableOpacity>
            ))}
          </View>

          <Text style={modalStyles.label}>希望天依的表达风格：（可不选）</Text>
          <View style={modalStyles.optionsRow}>
            {styles.map((s) => (
              <TouchableOpacity
                key={s || '默认'}
                style={[modalStyles.chip, speakingStyle === s && modalStyles.chipActive]}
                onPress={() => setSpeakingStyle(s)}
              >
                <Text style={[modalStyles.chipText, speakingStyle === s && modalStyles.chipTextActive]}>{s || '默认'}</Text>
              </TouchableOpacity>
            ))}
          </View>

          <View style={modalStyles.btnRow}>
            <TouchableOpacity
              style={modalStyles.skipBtn}
              onPress={() => onComplete({})}
            >
              <Text style={modalStyles.skipBtnText}>先试试看</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={modalStyles.confirmBtn}
              onPress={() => onComplete({ relationship, speaking_style: speakingStyle })}
            >
              <Text style={modalStyles.confirmBtnText}>确认</Text>
            </TouchableOpacity>
          </View>

          <Text style={modalStyles.hint}>后续可在设置中随时修改~</Text>
        </View>
      </View>
    </Modal>
  );
}

const modalStyles = StyleSheet.create({
  overlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.5)',
    justifyContent: 'center',
    alignItems: 'center',
    padding: 30,
  },
  container: {
    backgroundColor: '#fff',
    borderRadius: 16,
    padding: 24,
    width: '100%',
    maxWidth: 360,
  },
  title: {
    fontSize: 22,
    fontWeight: '700',
    color: '#66CCFF',
    textAlign: 'center',
  },
  subtitle: {
    fontSize: 13,
    color: '#888',
    textAlign: 'center',
    marginTop: 6,
    marginBottom: 20,
  },
  label: {
    fontSize: 14,
    color: '#555',
    fontWeight: '600',
    marginTop: 12,
    marginBottom: 8,
  },
  optionsRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  chip: {
    paddingHorizontal: 14,
    paddingVertical: 7,
    borderRadius: 16,
    backgroundColor: '#f0f0f0',
    borderWidth: 1,
    borderColor: '#e0e0e0',
  },
  chipActive: {
    backgroundColor: '#E6F7FF',
    borderColor: '#66CCFF',
  },
  chipText: {
    fontSize: 13,
    color: '#666',
  },
  chipTextActive: {
    color: '#66CCFF',
    fontWeight: '600',
  },
  btnRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginTop: 24,
  },
  skipBtn: {
    flex: 1,
    paddingVertical: 12,
    borderRadius: 10,
    backgroundColor: '#f0f0f0',
    alignItems: 'center',
    marginRight: 8,
  },
  skipBtnText: {
    fontSize: 14,
    color: '#888',
  },
  confirmBtn: {
    flex: 1,
    paddingVertical: 12,
    borderRadius: 10,
    backgroundColor: '#66CCFF',
    alignItems: 'center',
    marginLeft: 8,
  },
  confirmBtnText: {
    fontSize: 14,
    color: '#fff',
    fontWeight: '600',
  },
  hint: {
    fontSize: 11,
    color: '#bbb',
    textAlign: 'center',
    marginTop: 12,
  },
});

interface LoginScreenProps {
  onLogin: (username: string, password: string, autoLogin: boolean) => Promise<{ success: boolean; message: string }>;
  onRegister: (username: string, password: string, confirmPassword: string, inviteCode: string) => Promise<{ success: boolean; message: string }>;
}

type TabType = 'login' | 'register';

export default function LoginScreen({ onLogin, onRegister }: LoginScreenProps) {
  const insets = useSafeAreaInsets();
  const [activeTab, setActiveTab] = useState<TabType>('login');
  const [loading, setLoading] = useState(false);
  const [showGuide, setShowGuide] = useState(false);
  // 暂存刚注册的用户名，供 guide 完成后自动填入登录表单
  const [justRegisteredUser, setJustRegisteredUser] = useState('');

  // 登录表单
  const [loginUsername, setLoginUsername] = useState('');
  const [loginPassword, setLoginPassword] = useState('');
  const [autoLogin, setAutoLogin] = useState(false);

  // 注册表单
  const [regUsername, setRegUsername] = useState('');
  const [regPassword, setRegPassword] = useState('');
  const [regConfirmPassword, setRegConfirmPassword] = useState('');
  const [inviteCode, setInviteCode] = useState('');

  // 重置账号弹窗
  const [showReset, setShowReset] = useState(false);
  const [resetInvite, setResetInvite] = useState('');
  const [resetUsername, setResetUsername] = useState('');
  const [resetPassword, setResetPassword] = useState('');
  const [resetConfirm, setResetConfirm] = useState('');
  const [resetting, setResetting] = useState(false);

  // 服务器地址弹窗
  const [showServer, setShowServer] = useState(false);
  const [serverUrl, setServerUrl] = useState(server_config.BASE_URL);
  const [verifying, setVerifying] = useState(false);

  const handleLogin = async () => {
    Keyboard.dismiss();
    setLoading(true);
    const result = await onLogin(loginUsername, loginPassword, autoLogin);
    setLoading(false);
    if (!result.success) {
      Alert.alert('登录失败', result.message);
    }
  };

  const handleGuideComplete = async (prefs: Record<string, string>) => {
    setShowGuide(false);
    // 保存偏好到 AsyncStorage
    if (prefs && prefs.relationship) {
      try {
        await AsyncStorage.setItem(PREFERENCE_KEY, JSON.stringify(prefs));
      } catch (e) {
        // ignore
      }
    }
    // 跳转到登录页
    Alert.alert('注册成功', '注册成功，请登录', [
      {
        text: '去登录',
        onPress: () => {
          setActiveTab('login');
          setLoginUsername(justRegisteredUser);
        },
      },
    ]);
  };

  const handleRegister = async () => {
    Keyboard.dismiss();
    if (regPassword !== regConfirmPassword) {
      Alert.alert('注册失败', '两次输入的密码不一致');
      return;
    }
    setLoading(true);
    const result = await onRegister(regUsername, regPassword, regConfirmPassword, inviteCode);
    setLoading(false);
    if (result.success) {
      // 偏好设置在 _layout 中处理
      Alert.alert('注册成功', '注册成功！接下来可以设置你与天依的相处模式~');
      // 自动切换到登录页
      setActiveTab('login');
      setLoginUsername(regUsername);
      setJustRegisteredUser(regUsername);
      setShowGuide(true);  // 先显示引导，登录放在 guide 完成之后
    } else {
      Alert.alert('注册失败', result.message);
    }
  };

  const handleResetAccount = async () => {
    Keyboard.dismiss();
    if (!resetInvite || !resetUsername || !resetPassword || !resetConfirm) {
      Alert.alert('错误', '请填写所有信息');
      return;
    }
    if (resetPassword !== resetConfirm) {
      Alert.alert('错误', '两次输入的密码不一致');
      return;
    }
    setResetting(true);
    try {
      // 加密密码（复用已有的加密方法）
      const { encryptPassword } = await import('../utils/crypto');
      const encryptedPassword = await encryptPassword(resetPassword);
      if (!encryptedPassword) {
        Alert.alert('错误', '密码加密失败');
        setResetting(false);
        return;
      }
      const response = await fetch(`${server_config.BASE_URL}/auth/reset_account`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          invite_code: resetInvite,
          new_username: resetUsername,
          new_password: encryptedPassword,
        }),
      });
      const result = await response.json();
      if (response.ok) {
        Alert.alert('成功', '账号重置成功，请使用新账号登录');
        setShowReset(false);
        setLoginUsername(resetUsername);
        setActiveTab('login');
      } else {
        Alert.alert('重置失败', result.detail || '未知错误');
      }
    } catch (e: any) {
      Alert.alert('重置失败', e.message || '网络错误');
    }
    setResetting(false);
  };

  const handleVerifyServer = async () => {
    const url = serverUrl.trim().replace(/\/+$/, '');
    if (!url) {
      Alert.alert('错误', '请输入服务器地址');
      return;
    }
    setVerifying(true);
    try {
      const response = await fetch(`${url}/auth/public_key`, { method: 'GET' });
      if (response.ok) {
        // 保存到 AsyncStorage 以便持久化
        const AsyncStorage = (await import('@react-native-async-storage/async-storage')).default;
        await AsyncStorage.setItem('custom_server_url', url);
        // 更新全局配置
        server_config.BASE_URL = url;
        Alert.alert('成功', '服务器地址验证成功，地址已保存');
        setShowServer(false);
      } else {
        Alert.alert('验证失败', `服务器返回状态码: ${response.status}`);
      }
    } catch (e: any) {
      Alert.alert('验证失败', `无法连接到服务器: ${e.message}`);
    }
    setVerifying(false);
  };

  return (
    <KeyboardAvoidingView
      style={{ flex: 1 }}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <View style={[styles.container, { paddingTop: insets.top + 40, paddingBottom: insets.bottom }]}>
        {/* 标题 */}
        <Text style={styles.title}>AI小洛</Text>
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

              {/* 底部操作区 */}
              <View style={styles.bottomActions}>
                <TouchableOpacity
                  style={styles.actionLink}
                  onPress={() => setShowReset(true)}
                >
                  <Text style={styles.actionLinkText}>🔄 重置账号</Text>
                </TouchableOpacity>
                <TouchableOpacity
                  style={styles.actionLink}
                  onPress={() => setShowServer(true)}
                >
                  <Text style={styles.actionLinkText}>⚙ 服务器地址</Text>
                </TouchableOpacity>
              </View>
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

              <Text style={styles.label}>确认密码</Text>
              <TextInput
                style={styles.input}
                placeholder="请再次输入密码"
                placeholderTextColor="#aaa"
                value={regConfirmPassword}
                onChangeText={setRegConfirmPassword}
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

        {/* ========== 重置账号弹窗 ========== */}
        <Modal visible={showReset} transparent animationType="fade">
          <View style={styles.modalOverlay}>
            <View style={styles.modalContent}>
              <Text style={styles.modalTitle}>🔄 重置账号</Text>
              <Text style={styles.modalDesc}>输入已使用的邀请码和新账号信息：</Text>

              <TextInput
                style={styles.modalInput}
                placeholder="已使用的邀请码"
                placeholderTextColor="#aaa"
                value={resetInvite}
                onChangeText={setResetInvite}
              />
              <TextInput
                style={styles.modalInput}
                placeholder="新用户名"
                placeholderTextColor="#aaa"
                value={resetUsername}
                onChangeText={setResetUsername}
                autoCapitalize="none"
              />
              <TextInput
                style={styles.modalInput}
                placeholder="新密码"
                placeholderTextColor="#aaa"
                value={resetPassword}
                onChangeText={setResetPassword}
                secureTextEntry
              />
              <TextInput
                style={styles.modalInput}
                placeholder="确认新密码"
                placeholderTextColor="#aaa"
                value={resetConfirm}
                onChangeText={setResetConfirm}
                secureTextEntry
              />

              <View style={styles.modalButtons}>
                <TouchableOpacity
                  style={[styles.modalBtn, styles.modalBtnCancel]}
                  onPress={() => { setShowReset(false); setResetting(false); }}
                >
                  <Text style={styles.modalBtnText}>取消</Text>
                </TouchableOpacity>
                <TouchableOpacity
                  style={[styles.modalBtn, styles.modalBtnDanger, resetting && styles.buttonDisabled]}
                  onPress={handleResetAccount}
                  disabled={resetting}
                >
                  <Text style={[styles.modalBtnText, { color: '#fff' }]}>
                    {resetting ? '重置中...' : '确认重置'}
                  </Text>
                </TouchableOpacity>
              </View>
            </View>
          </View>
        </Modal>

        {/* ========== 服务器地址弹窗 ========== */}
        <Modal visible={showServer} transparent animationType="fade">
          <View style={styles.modalOverlay}>
            <View style={styles.modalContent}>
              <Text style={styles.modalTitle}>⚙ 服务器地址</Text>
              <Text style={styles.modalDesc}>输入自定义服务器地址（URL），输入后会自动验证连接：</Text>

              <TextInput
                style={styles.modalInput}
                placeholder="https://your-server.com:60030"
                placeholderTextColor="#aaa"
                value={serverUrl}
                onChangeText={setServerUrl}
                autoCapitalize="none"
                autoCorrect={false}
              />

              <View style={styles.modalButtons}>
                <TouchableOpacity
                  style={[styles.modalBtn, styles.modalBtnCancel]}
                  onPress={() => setShowServer(false)}
                >
                  <Text style={styles.modalBtnText}>取消</Text>
                </TouchableOpacity>
                <TouchableOpacity
                  style={[styles.modalBtn, styles.modalBtnPrimary, verifying && styles.buttonDisabled]}
                  onPress={handleVerifyServer}
                  disabled={verifying}
                >
                  <Text style={[styles.modalBtnText, { color: '#fff' }]}>
                    {verifying ? '验证中...' : '验证并保存'}
                  </Text>
                </TouchableOpacity>
              </View>
            </View>
          </View>
        </Modal>
        <PreferenceGuideModal visible={showGuide} onComplete={handleGuideComplete} />
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
  bottomActions: {
    flexDirection: 'row',
    justifyContent: 'space-around',
    marginTop: 20,
  },
  actionLink: {
    paddingVertical: 8,
    paddingHorizontal: 12,
  },
  actionLinkText: {
    fontSize: 14,
    color: '#888',
    fontWeight: '500',
  },
  modalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.5)',
    justifyContent: 'center',
    alignItems: 'center',
  },
  modalContent: {
    backgroundColor: '#fff',
    borderRadius: 16,
    padding: 24,
    width: '85%',
    maxWidth: 400,
  },
  modalTitle: {
    fontSize: 20,
    fontWeight: 'bold',
    color: '#333',
    marginBottom: 8,
    textAlign: 'center',
  },
  modalDesc: {
    fontSize: 13,
    color: '#666',
    marginBottom: 16,
    textAlign: 'center',
  },
  modalInput: {
    backgroundColor: '#f5f5f5',
    borderRadius: 10,
    paddingHorizontal: 14,
    paddingVertical: 10,
    fontSize: 14,
    color: '#333',
    marginBottom: 10,
    borderWidth: 1,
    borderColor: '#e0e0e0',
  },
  modalButtons: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginTop: 12,
    gap: 12,
  },
  modalBtn: {
    flex: 1,
    paddingVertical: 12,
    borderRadius: 10,
    alignItems: 'center',
  },
  modalBtnCancel: {
    backgroundColor: '#f0f0f0',
  },
  modalBtnDanger: {
    backgroundColor: '#FF6B6B',
  },
  modalBtnPrimary: {
    backgroundColor: '#66CCFF',
  },
  modalBtnText: {
    fontSize: 15,
    fontWeight: '600',
    color: '#333',
  },
});

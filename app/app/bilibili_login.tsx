/**
 * Bilibili Cookie 登录页（手机端）
 * 支持：手机号+验证码登录、账号密码登录
 */
import React, { useState } from 'react';
import {
  Alert,
  Keyboard,
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
import { server_config } from '../config';
import * as forge from 'node-forge';

type LoginMode = 'sms' | 'password';

interface Props {
  onClose: () => void;
}

async function apiPost(path: string, body: Record<string, string>): Promise<any> {
  const resp = await fetch(`${server_config.BASE_URL}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return resp.json();
}

export default function BilibiliLoginScreen({ onClose }: Props) {
  const insets = useSafeAreaInsets();
  const [mode, setMode] = useState<LoginMode>('sms');
  const [loading, setLoading] = useState(false);

  // 短信登录
  const [phone, setPhone] = useState('');
  const [smsCode, setSmsCode] = useState('');
  const [codeSent, setCodeSent] = useState(false);
  const [countdown, setCountdown] = useState(0);

  // 密码登录
  const [biliUsername, setBiliUsername] = useState('');
  const [biliPassword, setBiliPassword] = useState('');

  const sendSms = async () => {
    Keyboard.dismiss();
    if (!phone.trim()) {
      Alert.alert('提示', '请输入手机号');
      return;
    }
    setLoading(true);
    try {
      const result = await apiPost('/api/bilibili/cookie/login/sms/send', {
        phone: phone.trim(),
        country_code: '86',
      });
      if (result.success) {
        setCodeSent(true);
        setCountdown(60);
        const timer = setInterval(() => {
          setCountdown((c) => {
            if (c <= 1) {
              clearInterval(timer);
              return 0;
            }
            return c - 1;
          });
        }, 1000);
        Alert.alert('已发送', '验证码已发送到您的手机');
      } else {
        Alert.alert('发送失败', result.message || '未知错误');
      }
    } catch (e: any) {
      Alert.alert('错误', e.message);
    }
    setLoading(false);
  };

  const doSmsLogin = async () => {
    Keyboard.dismiss();
    if (!phone.trim() || !smsCode.trim()) {
      Alert.alert('提示', '请填写手机号和验证码');
      return;
    }
    setLoading(true);
    try {
      const result = await apiPost('/api/bilibili/cookie/login/sms', {
        phone: phone.trim(),
        code: smsCode.trim(),
        country_code: '86',
      });
      if (result.success) {
        Alert.alert('成功', 'Bilibili 登录成功！Cookie 已保存到本地');
        onClose();
      } else {
        Alert.alert('登录失败', result.message || '未知错误');
      }
    } catch (e: any) {
      Alert.alert('错误', e.message);
    }
    setLoading(false);
  };

  const doPasswordLogin = async () => {
    Keyboard.dismiss();
    if (!biliUsername.trim() || !biliPassword.trim()) {
      Alert.alert('提示', '请填写账号和密码');
      return;
    }
    setLoading(true);
    try {
      // 1. 获取 RSA 公钥（服务端不接触密码明文）
      const keyResp = await fetch(`${server_config.BASE_URL}/api/bilibili/cookie/login/key`);
      const keyData = await keyResp.json();
      if (!keyData.key || !keyData.hash) {
        Alert.alert('错误', '获取加密密钥失败');
        setLoading(false);
        return;
      }

      // 2. 客户端本地 RSA 加密密码（PKCS1 v1.5）
      const publicKey = forge.pki.publicKeyFromPem(keyData.key);
      const encrypted = publicKey.encrypt(keyData.hash + biliPassword, 'RSAES-PKCS1-V1_5');
      const encryptedPassword = forge.util.encode64(encrypted);

      // 3. 发送加密后的密码到服务端
      const result = await apiPost('/api/bilibili/cookie/login/password', {
        username: biliUsername.trim(),
        encrypted_password: encryptedPassword,
      });
      if (result.success) {
        Alert.alert('成功', 'Bilibili 登录成功！Cookie 已保存到本地');
        onClose();
      } else {
        Alert.alert('登录失败', result.message || '账号或密码错误');
      }
    } catch (e: any) {
      Alert.alert('错误', e.message);
    }
    setLoading(false);
  };

  const checkStatus = async () => {
    try {
      const result = await apiPost('/api/bilibili/cookie/qrcode/generate', {});
      if (result.url) {
        Alert.alert(
          '需要 PC 端扫码',
          '手机端不支持二维码显示，请使用 PC 客户端进行 QR 码登录，或使用下方的短信/密码登录。',
        );
      }
    } catch {
      Alert.alert('无法连接服务端', '请检查服务器地址配置');
    }
  };

  return (
    <View style={[styles.container, { paddingTop: insets.top }]}>
      {/* 标题栏 */}
      <View style={styles.header}>
        <TouchableOpacity onPress={onClose}>
          <Text style={styles.backBtn}>{'< 返回'}</Text>
        </TouchableOpacity>
        <Text style={styles.title}>Bilibili 登录</Text>
        <View style={{ width: 60 }} />
      </View>

      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
        style={{ flex: 1 }}
      >
        <ScrollView contentContainerStyle={styles.scrollContent}>
          {/* 模式切换 */}
          <View style={styles.tabRow}>
            <TouchableOpacity
              style={[styles.tab, mode === 'sms' && styles.tabActive]}
              onPress={() => setMode('sms')}
            >
              <Text style={[styles.tabText, mode === 'sms' && styles.tabTextActive]}>
                手机验证码
              </Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[styles.tab, mode === 'password' && styles.tabActive]}
              onPress={() => setMode('password')}
            >
              <Text style={[styles.tabText, mode === 'password' && styles.tabTextActive]}>
                账号密码
              </Text>
            </TouchableOpacity>
          </View>

          {mode === 'sms' ? (
            <View style={styles.form}>
              <Text style={styles.label}>手机号</Text>
              <TextInput
                style={styles.input}
                placeholder="输入 B站 绑定手机号"
                keyboardType="phone-pad"
                value={phone}
                onChangeText={setPhone}
              />

              <View style={styles.codeRow}>
                <TextInput
                  style={[styles.input, { flex: 1, marginRight: 8 }]}
                  placeholder="验证码"
                  keyboardType="number-pad"
                  value={smsCode}
                  onChangeText={setSmsCode}
                />
                <TouchableOpacity
                  style={[styles.smallBtn, countdown > 0 && { opacity: 0.5 }]}
                  onPress={sendSms}
                  disabled={countdown > 0 || loading}
                >
                  <Text style={styles.smallBtnText}>
                    {countdown > 0 ? `${countdown}s` : '获取验证码'}
                  </Text>
                </TouchableOpacity>
              </View>

              <TouchableOpacity
                style={[styles.primaryBtn, loading && { opacity: 0.6 }]}
                onPress={doSmsLogin}
                disabled={loading}
              >
                <Text style={styles.primaryBtnText}>
                  {loading ? '登录中...' : '登录'}
                </Text>
              </TouchableOpacity>
            </View>
          ) : (
            <View style={styles.form}>
              <Text style={styles.label}>B站账号（手机号/邮箱）</Text>
              <TextInput
                style={styles.input}
                placeholder="输入 B站 账号"
                value={biliUsername}
                onChangeText={setBiliUsername}
                autoCapitalize="none"
              />

              <Text style={styles.label}>密码</Text>
              <TextInput
                style={styles.input}
                placeholder="输入密码"
                secureTextEntry
                value={biliPassword}
                onChangeText={setBiliPassword}
              />

              <TouchableOpacity
                style={[styles.primaryBtn, loading && { opacity: 0.6 }]}
                onPress={doPasswordLogin}
                disabled={loading}
              >
                <Text style={styles.primaryBtnText}>
                  {loading ? '登录中...' : '登录'}
                </Text>
              </TouchableOpacity>
            </View>
          )}

          {/* 安全提示 */}
          <View style={styles.tips}>
            <Text style={styles.tipTitle}>安全说明</Text>
            <Text style={styles.tipText}>
              • 密码经 B站 RSA 公钥加密传输，服务端无法获取明文
            </Text>
            <Text style={styles.tipText}>
              • Cookie 保存在本地，使用时才同步到服务端内存，不落盘
            </Text>
            <Text style={styles.tipText}>
              • refresh_token 仅用于续期 SESSDATA，无法操作用户账号
            </Text>
            <Text style={styles.tipText}>
              • 服务端重启后 Cookie 不会丢失，从本地重新同步即可
            </Text>
            <Text style={styles.tipText}>
              • 可随时在 B站「设置-安全设置-登录设备管理」中撤销授权
            </Text>
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#f5f5f5' },
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
  backBtn: { fontSize: 16, color: '#66CCFF' },
  title: { fontSize: 18, fontWeight: '600', color: '#333' },
  scrollContent: { padding: 16 },
  tabRow: {
    flexDirection: 'row',
    marginBottom: 20,
    backgroundColor: '#e0e0e0',
    borderRadius: 8,
    padding: 2,
  },
  tab: {
    flex: 1,
    paddingVertical: 10,
    alignItems: 'center',
    borderRadius: 6,
  },
  tabActive: { backgroundColor: '#fff' },
  tabText: { fontSize: 14, color: '#666' },
  tabTextActive: { color: '#66CCFF', fontWeight: '600' },
  form: { marginBottom: 20 },
  label: { fontSize: 14, color: '#333', marginBottom: 6, marginTop: 12 },
  input: {
    height: 44,
    backgroundColor: '#fff',
    borderRadius: 8,
    paddingHorizontal: 12,
    fontSize: 15,
    borderWidth: 1,
    borderColor: '#ddd',
  },
  codeRow: { flexDirection: 'row', alignItems: 'center', marginTop: 12 },
  smallBtn: {
    height: 44,
    paddingHorizontal: 16,
    backgroundColor: '#66CCFF',
    borderRadius: 8,
    justifyContent: 'center',
    alignItems: 'center',
  },
  smallBtnText: { color: '#fff', fontSize: 14, fontWeight: '600' },
  primaryBtn: {
    height: 48,
    backgroundColor: '#FB7299',
    borderRadius: 24,
    justifyContent: 'center',
    alignItems: 'center',
    marginTop: 24,
  },
  primaryBtnText: { color: '#fff', fontSize: 17, fontWeight: '600' },
  tips: {
    backgroundColor: '#fff',
    borderRadius: 8,
    padding: 14,
    marginTop: 10,
  },
  tipTitle: { fontSize: 14, fontWeight: '600', color: '#999', marginBottom: 8 },
  tipText: { fontSize: 13, color: '#999', lineHeight: 20, marginBottom: 4 },
});

import { Alert, Linking } from 'react-native';
import {
  MICROPHONE_AMBIGUOUS_MESSAGE,
  MICROPHONE_PENDING_MESSAGE,
  showMicrophoneSettings,
} from '../utils/voice_permission';

jest.mock('react-native', () => ({
  Alert: { alert: jest.fn() }, Linking: { openSettings: jest.fn() },
}));

beforeEach(() => { jest.clearAllMocks(); });

it('gives feedback without claiming the permission is closed', () => {
  showMicrophoneSettings(jest.fn());
  const [title, message] = (Alert.alert as jest.Mock).mock.calls[0];

  // 只要求"确实给出了反馈"：具体文案由文案评审决定，不用单元测试锁死措辞。
  expect(typeof title).toBe('string');
  expect(title.trim()).not.toBe('');
  expect(typeof message).toBe('string');
  expect(message.trim()).not.toBe('');
  // 唯一保留的契约：不得把原因不明的未授权表述成"权限已关闭 / 永久拒绝"。
  expect(`${title}${message}`).not.toMatch(/已关闭|永久/);
});

it('renders the settings dialog with a title that matches its body', () => {
  showMicrophoneSettings(jest.fn());
  const [title, message] = (Alert.alert as jest.Mock).mock.calls[0];

  // 这个弹窗只在"请求长时间没有返回"时出现：标题与正文都必须说明这一点，不能预告授权失败。
  expect(title).toContain('未返回');
  expect(message).toContain('没有返回');
  expect(title).not.toContain('失败');
  expect(`${title}${message}`).not.toMatch(/已关闭|永久/);
});

it('keeps the non-modal messages free of permanent-denial wording', () => {
  // 已返回的模糊未授权 → 强调可重试；在途 → 只说明处理中。
  expect(MICROPHONE_AMBIGUOUS_MESSAGE).toContain('重试');
  expect(MICROPHONE_PENDING_MESSAGE).toContain('处理中');
  for (const text of [MICROPHONE_AMBIGUOUS_MESSAGE, MICROPHONE_PENDING_MESSAGE]) {
    expect(text).not.toMatch(/已关闭|永久/);
    expect(text).not.toContain('授权失败');
  }
});

it('offers cancel and opens app settings only on explicit selection', async () => {
  const notice = jest.fn();
  (Linking.openSettings as jest.Mock).mockResolvedValue(undefined);
  showMicrophoneSettings(notice);
  const buttons = (Alert.alert as jest.Mock).mock.calls[0][2];
  expect(buttons[0]).toEqual({ text: '取消', style: 'cancel' });
  expect(Linking.openSettings).not.toHaveBeenCalled();
  expect(buttons[1].text).toBe('去设置');
  buttons[1].onPress();
  await Promise.resolve();
  expect(Linking.openSettings).toHaveBeenCalledTimes(1);
  expect(notice).not.toHaveBeenCalled();
  (Linking.openSettings as jest.Mock).mockRejectedValue(new Error('unavailable'));
  buttons[1].onPress();
  await Promise.resolve();
  expect(notice).toHaveBeenCalledWith(expect.stringContaining('无法打开系统设置'));
});

import { Alert, Linking } from 'react-native';
import { showMicrophonePendingSettings, showMicrophoneSettings } from '../utils/voice_permission';

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
  // 已经返回的未授权结果不是 pending：不应出现"处理中"。
  expect(`${title}${message}`).not.toContain('处理中');
});

it('renders the pending notice with a title that matches its body', () => {
  showMicrophonePendingSettings(jest.fn());
  const [title, message] = (Alert.alert as jest.Mock).mock.calls[0];

  // 请求尚未返回时不能出现"失败"结论：标题与正文必须一致地只说明"处理中"。
  expect(title).toContain('处理中');
  expect(title).not.toContain('失败');
  expect(message).toContain('处理中');
  expect(message).not.toContain('失败');
  expect(`${title}${message}`).not.toMatch(/已关闭|永久/);
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

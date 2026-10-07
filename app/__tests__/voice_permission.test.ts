import { Alert, Linking } from 'react-native';
import { showMicrophoneSettings } from '../utils/voice_permission';

jest.mock('react-native', () => ({
  Alert: { alert: jest.fn() }, Linking: { openSettings: jest.fn() },
}));

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

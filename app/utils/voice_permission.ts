import { Alert, Linking } from 'react-native';

export function showMicrophoneSettings(onError: (message: string) => void) {
  Alert.alert('麦克风权限已关闭', '请在系统设置中允许使用麦克风，然后返回重新按住说话。', [
    { text: '取消', style: 'cancel' },
    { text: '去设置', onPress: () => {
      void Linking.openSettings().catch(() => onError('无法打开系统设置，请手动为本应用开启麦克风权限'));
    } },
  ]);
}

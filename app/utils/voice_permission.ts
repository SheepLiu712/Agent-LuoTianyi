import { Alert, Linking } from 'react-native';

/**
 * 未获得麦克风权限时的提示。
 *
 * Expo 在 Android 上无法可靠区分"本次取消""普通拒绝"和"永久拒绝"，所以文案只陈述
 * "这次授权失败"，不声称权限已关闭或用户已永久拒绝；用户可以直接重试，也可以去系统设置。
 */
export function showMicrophoneSettings(
  onError: (message: string) => void,
  message = '未能获得麦克风权限。你可以重新按住说话重试；也可以在系统设置中允许使用麦克风。',
) {
  Alert.alert('麦克风授权失败', message, [
    { text: '取消', style: 'cancel' },
    { text: '去设置', onPress: () => {
      void Linking.openSettings().catch(() => onError('无法打开系统设置，请手动为本应用开启麦克风权限'));
    } },
  ]);
}

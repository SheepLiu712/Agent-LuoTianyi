import { Alert, Linking } from 'react-native';

/** 一条麦克风权限提示：标题与正文必须成对给出，避免标题与正文互相矛盾。 */
export interface MicrophoneNotice {
  title: string;
  message: string;
}

/**
 * 未获得授权。
 *
 * Expo 在 Android 上无法可靠区分"本次取消""普通拒绝"和"永久拒绝"，所以只陈述"这次授权失败"，
 * 不声称权限已关闭或用户已永久拒绝；用户可以重试，也可以去系统设置。
 */
export const MICROPHONE_FAILURE_NOTICE: MicrophoneNotice = {
  title: '麦克风授权失败',
  message: '未能获得麦克风权限。你可以重新按住说话重试；也可以在系统设置中允许使用麦克风。',
};

/** 请求仍在途：结果尚未返回，不能提前断言授权失败，只说明状态并给出出口。 */
export const MICROPHONE_PENDING_NOTICE: MicrophoneNotice = {
  title: '麦克风权限请求处理中',
  message: '权限请求仍在处理中。请稍候重试；也可以在系统设置中查看麦克风权限。',
};

export function showMicrophoneSettings(
  onError: (message: string) => void,
  notice: MicrophoneNotice = MICROPHONE_FAILURE_NOTICE,
) {
  Alert.alert(notice.title, notice.message, [
    { text: '取消', style: 'cancel' },
    { text: '去设置', onPress: () => {
      void Linking.openSettings().catch(() => onError('无法打开系统设置，请手动为本应用开启麦克风权限'));
    } },
  ]);
}

/**
 * 请求仍在途时的提示。
 *
 * 单独成一个入口，避免调用方只替换正文却留着"授权失败"的标题，造成同一弹窗自相矛盾。
 */
export function showMicrophonePendingSettings(onError: (message: string) => void) {
  showMicrophoneSettings(onError, MICROPHONE_PENDING_NOTICE);
}

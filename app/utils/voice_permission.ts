import { Alert, Linking } from 'react-native';

/** 一条麦克风权限提示：标题与正文必须成对给出，避免标题与正文互相矛盾。 */
export interface MicrophoneNotice {
  title: string;
  message: string;
}

/**
 * 请求已返回、但原因不明的未授权结果。
 *
 * Expo 在 Android 上无法可靠区分"本次取消""普通拒绝"和"永久拒绝"，所以只陈述"这次没拿到权限"，
 * 用非模态提示让用户可重试，也告知设置入口；不自动弹出设置对话框，避免把可重试结果升级成永久拒绝。
 */
export const MICROPHONE_AMBIGUOUS_MESSAGE =
  '没拿到麦克风权限。可以再按住试一次；如果一直不弹系统询问，请到系统设置里打开麦克风。';

/** 请求仍在途：只陈述当前事实，不预告结果。 */
export const MICROPHONE_PENDING_MESSAGE = '上一次权限请求还没有返回。';

/** 请求长时间没有返回：此时才提供设置出口。 */
export const MICROPHONE_STUCK_NOTICE: MicrophoneNotice = {
  title: '麦克风权限请求未返回',
  message: '系统权限请求长时间没有返回，可以重试或到系统设置检查麦克风权限。',
};

/**
 * 在途多久算"卡住"。
 *
 * 这里量的是**请求在途时长**，不是"系统框是否出现过"，也不用于推断用户意图（取消 / 拒绝 / 永久拒绝）。
 * 正常系统框由用户操作，返回时间远大于该值；只有请求异常挂起时才会触发设置出口。
 */
export const PERMISSION_STUCK_AFTER_MS = 8000;

/**
 * 弹出带设置入口的提示。
 *
 * 只应在"请求长时间未返回"这类需要用户去系统设置排查时调用；已返回的模糊未授权结果走非模态文案。
 */
export function showMicrophoneSettings(
  onError: (message: string) => void,
  notice: MicrophoneNotice = MICROPHONE_STUCK_NOTICE,
) {
  Alert.alert(notice.title, notice.message, [
    { text: '取消', style: 'cancel' },
    { text: '去设置', onPress: () => {
      void Linking.openSettings().catch(() => onError('无法打开系统设置，请手动为本应用开启麦克风权限'));
    } },
  ]);
}

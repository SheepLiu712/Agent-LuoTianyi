import type { CallEndReason } from './call_protocol/control_types';

export interface CallFailureNotice {
  title: string;
  message: string;
}

const FAILURE_NOTICES: Record<string, CallFailureNotice> = {
  SERVER_CALL_UNAVAILABLE: { title: '通话暂不可用', message: '服务暂未准备好，请稍后再试。' },
  NATIVE_CALL_UNAVAILABLE: { title: '无法使用麦克风', message: '请检查设备音频权限和通话能力后重试。' },
  CALL_AUTH_REQUIRED: { title: '通话需要重新登录', message: '登录状态已失效，请重新登录后再试。' },
  AUTH_REJECTED: { title: '通话需要重新登录', message: '登录状态已失效，请重新登录后再试。' },
  CALL_CONNECTION_LOST: { title: '通话连接失败', message: '未能建立通话连接，请检查网络后重试。' },
  SOCKET_NOT_OPEN: { title: '通话连接失败', message: '通话连接未建立，请检查网络后重试。' },
  RECOVERY_TIMEOUT: { title: '通话连接中断', message: '恢复连接超时，通话已结束，请检查网络后重试。' },
  CALL_SETUP_TIMEOUT: { title: '呼叫超时', message: '未能及时接通，请稍后重试。' },
  CALL_PROVIDER_FAILED: { title: '通话服务异常', message: '语音服务暂时不可用，请稍后重试。' },
  CALL_SYSTEM_FAILURE: { title: '通话异常结束', message: '通话服务发生异常，请稍后重试。' },
  AUDIO_FOCUS_LOST: { title: '通话音频已中断', message: '设备音频被其他应用占用，请重试通话。' },
  AUDIO_FOCUS_CLOSE_FAILED: { title: '通话音频异常', message: '设备音频未能正常切换，请重试通话。' },
  CONTROL_OUTBOX_FULL: { title: '通话暂时繁忙', message: '通话请求未能及时送达，请稍后再试。' },
};

const FALLBACK_NOTICE: CallFailureNotice = {
  title: '通话失败',
  message: '通话未能建立，请检查网络和设备权限后重试。',
};

// Outcome records whether the call connected; only the end reason identifies a failure.
const END_FAILURE_CODES: Record<CallEndReason, string | undefined> = {
  user_hangup: undefined,
  agent_hangup: undefined,
  declined: undefined,
  time_limit: undefined,
  setup_timeout: 'CALL_SETUP_TIMEOUT',
  provider_failed: 'CALL_PROVIDER_FAILED',
  recovery_timeout: 'RECOVERY_TIMEOUT',
  system_failure: 'CALL_SYSTEM_FAILURE',
};

export function getCallEndFailureCode(reason?: CallEndReason): string | undefined {
  return reason ? END_FAILURE_CODES[reason] : undefined;
}

/** Maps internal transport codes to safe, actionable user copy. Raw errors never reach the UI. */
export function getCallFailureNotice(code?: string): CallFailureNotice {
  return (code ? FAILURE_NOTICES[code] : undefined) ?? FALLBACK_NOTICE;
}

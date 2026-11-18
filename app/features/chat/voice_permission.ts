export interface PermissionNotice {
  message: string;
  settings: boolean;
}

export const permissionMessages = {
  waiting: '上一次麦克风权限申请尚未结束，请稍后再试。',
  denied: '未获得麦克风权限，可重新按住再试',
  settings: '仍未获得麦克风权限，可前往系统设置为本应用开启麦克风权限。',
  error: '无法获取麦克风权限状态，请重新按住再试。',
  settingsError: '无法打开系统设置，请手动前往系统设置，为本应用开启麦克风权限。',
};

import { useEffect } from 'react';
import type { Notice } from '../../shell/notices/AppNotices';
import type { AppTheme } from '../../shared/ui/theme';
import type { PermissionNotice } from './voice_permission';

interface Props {
  notice: PermissionNotice;
  theme: AppTheme;
  show(notice: Notice): () => void;
  onDismiss(notice: PermissionNotice): void;
  onOpenSettings(notice: PermissionNotice): void;
}

export function VoicePermissionNotice({ show, notice, theme, onDismiss, onOpenSettings }: Props) {
  useEffect(() => {
    const dismiss = () => onDismiss(notice);
    return show({
      message: notice.message, theme,
      primary: notice.settings ? { label: '去设置', action: () => onOpenSettings(notice) }
        : { label: '知道了', accessibilityLabel: '关闭麦克风提示', action: dismiss },
      cancel: notice.settings ? { label: '取消', action: dismiss } : undefined,
    });
  }, [notice, onDismiss, onOpenSettings, show, theme]);
  return null;
}

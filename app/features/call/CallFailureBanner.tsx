import { useEffect } from 'react';
import type { Notice } from '../../shell/notices/AppNotices';
import type { AppTheme } from '../../shared/ui/theme';
import type { CallFailureNotice } from './call_failure';

interface Props {
  notice: CallFailureNotice;
  theme: AppTheme;
  show(notice: Notice): () => void;
  onDismiss(): void;
}

export function CallFailureBanner({ notice, theme, show, onDismiss }: Props) {
  useEffect(() => show({
    ...notice, theme, primary: { label: '知道了', accessibilityLabel: '关闭通话提示', action: onDismiss },
  }), [notice, theme, show, onDismiss]);
  return null;
}

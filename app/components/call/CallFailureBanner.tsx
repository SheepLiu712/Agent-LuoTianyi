import React from 'react';
import type { AppTheme } from '../../utils/theme';
import type { CallFailureNotice } from '../../utils/call_failure';
import { NoticeBanner } from '../NoticeBanner';

interface Props {
  notice: CallFailureNotice;
  theme: AppTheme;
  onDismiss: () => void;
}

export function CallFailureBanner({ notice, theme, onDismiss }: Props) {
  return <NoticeBanner {...notice} theme={theme} dismissLabel="关闭通话提示" onDismiss={onDismiss} />;
}

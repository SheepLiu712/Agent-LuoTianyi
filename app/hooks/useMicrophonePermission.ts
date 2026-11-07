import { useCallback, useLayoutEffect, useRef, useState } from 'react';
import { AppState, Linking } from 'react-native';
import type { VoiceRecorderApi } from '../utils/voice_recorder';
import { type PermissionNotice, permissionMessages } from '../utils/voice_permission';

export function useMicrophonePermission(recorder: VoiceRecorderApi) {
  const [permissionNotice, setNotice] = useState<PermissionNotice | null>(null);
  const shown = useRef<PermissionNotice | null>(null);
  const generation = useRef(0);
  const retryAfterDenial = useRef(false);
  const pending = useRef<{ waiting: PermissionNotice | null } | null>(null);
  const foreground = useRef(AppState.currentState !== 'background' && AppState.currentState !== 'inactive');
  const onResume = useRef<(() => void) | null>(null);

  const display = useCallback((message: string, settings = false) => {
    const notice = { message, settings };
    shown.current = notice;
    setNotice(notice);
    return notice;
  }, []);
  const dismissPermissionNotice = useCallback((notice: PermissionNotice | null) => {
    if (notice && shown.current === notice) {
      shown.current = null;
      setNotice(null);
    }
  }, []);
  const leavePermissionPage = useCallback(() => {
    generation.current += 1;
    onResume.current = null;
    dismissPermissionNotice(shown.current);
  }, [dismissPermissionNotice]);

  useLayoutEffect(() => () => {
    generation.current += 1;
    shown.current = null;
    onResume.current = null;
  }, []);

  const setPermissionForeground = useCallback((active: boolean) => {
    foreground.current = active;
    if (active && onResume.current) {
      const deliver = onResume.current;
      onResume.current = null;
      deliver();
    }
  }, []);

  const checkPermission = useCallback(async (validPress: () => boolean, onPermissionPrompt?: () => void) => {
    const beforeQuery = generation.current;
    const existing = pending.current;
    let permission;
    try {
      permission = await recorder.getPermission();
    } catch {
      if (generation.current === beforeQuery && validPress()) display(permissionMessages.error);
      return false;
    }
    if (generation.current !== beforeQuery || !validPress()) return false;
    if (permission === 'granted') {
      generation.current += 1;
      onResume.current = null;
      retryAfterDenial.current = false;
      dismissPermissionNotice(shown.current);
      return true;
    }
    onPermissionPrompt?.();
    if (existing) {
      // 本次按住发生在原请求返回之前，不能因权限查询较慢而追加一次申请。
      if (pending.current === existing && (!existing.waiting || shown.current !== existing.waiting)) {
        existing.waiting = display(permissionMessages.waiting);
      }
      return false;
    }

    const attempt = ++generation.current;
    onResume.current = null;
    dismissPermissionNotice(shown.current);
    const request = { waiting: null as PermissionNotice | null };
    pending.current = request;
    const isRetry = retryAfterDenial.current;
    const finish = (action: () => void) => {
      if (pending.current === request) pending.current = null;
      dismissPermissionNotice(request.waiting);
      if (generation.current !== attempt) return;
      if (foreground.current) action();
      else onResume.current = action;
    };
    const requestFromSystem = async () => {
      let result;
      try {
        result = await recorder.requestPermission();
      } catch {
        finish(() => display(permissionMessages.error));
        return;
      }
      finish(() => {
        if (result === 'granted') {
          retryAfterDenial.current = false;
          return;
        }
        retryAfterDenial.current = true;
        if (isRetry && result === 'blocked') display(permissionMessages.settings, true);
        else display(permissionMessages.denied);
      });
    };
    void requestFromSystem();
    return false;
  }, [recorder, display, dismissPermissionNotice]);

  const openPermissionSettings = useCallback(async (notice: PermissionNotice) => {
    if (!notice.settings || shown.current !== notice) return;
    dismissPermissionNotice(notice);
    const attempt = generation.current;
    try {
      await Linking.openSettings();
    } catch {
      if (generation.current === attempt) display(permissionMessages.settingsError);
    }
  }, [dismissPermissionNotice, display]);

  return { checkPermission, permissionNotice, dismissPermissionNotice, openPermissionSettings,
    leavePermissionPage, setPermissionForeground };
}

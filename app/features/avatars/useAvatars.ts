import AsyncStorage from '@react-native-async-storage/async-storage';
import * as SecureStore from 'expo-secure-store';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { AppState } from 'react-native';
import type { AccountSession } from '../account/credentials';
import { AvatarSync, emptyAvatars, type AvatarImage, type AvatarSide, type AvatarState } from './avatar_sync';

// SecureStore accepts only alphanumeric characters, dots, underscores and hyphens.
const tokenKey = (key: string) => `avatar_token_${key.split('').map(char => char.charCodeAt(0).toString(16).padStart(4, '0')).join('')}`;
const tokens = {
  getItem: (key: string) => SecureStore.getItemAsync(tokenKey(key)),
  setItem: (key: string, value: string) => value
    ? SecureStore.setItemAsync(tokenKey(key), value) : SecureStore.deleteItemAsync(tokenKey(key)),
};

export function useAvatars(session: AccountSession) {
  const { username, token, serverUrl } = session;
  const controller = useMemo(() => new AvatarSync({ username, token, serverUrl }, AsyncStorage, fetch, tokens),
    [username, token, serverUrl]);
  const [value, setValue] = useState<{ owner: AvatarSync; state: AvatarState }>();
  useEffect(() => {
    const unsubscribe = controller.subscribe(state => setValue({ owner: controller, state }));
    void controller.setForeground(AppState.currentState === 'active');
    void controller.start();
    const foreground = AppState.addEventListener('change', next => controller.setForeground(next === 'active'));
    return () => { unsubscribe(); controller.dispose(); foreground.remove(); };
  }, [controller]);
  const save = useCallback((side: AvatarSide, image: AvatarImage) => controller.save(side, image), [controller]);
  const retry = useCallback(() => controller.retry(), [controller]);
  const check = useCallback(() => controller.check(), [controller]);
  return { ...(value?.owner === controller ? value.state : emptyAvatars), save, retry, check };
}
export type Avatars = ReturnType<typeof useAvatars>;

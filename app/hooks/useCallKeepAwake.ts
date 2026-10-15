import { useEffect, useRef } from 'react';
import { activateKeepAwakeAsync, deactivateKeepAwake } from 'expo-keep-awake';

const activePhases = new Set([
  'SWITCH_PREPARING',
  'CONNECTING',
  'PREPARING',
  'RINGING',
  'ACTIVE',
  'RECONNECTING',
]);
let nextOwnerId = 0;

/** Owns one tagged screen-awake lock for the mounted CallScreen owner. */
export function useCallKeepAwake(phase: string): void {
  const tagRef = useRef<string | undefined>(undefined);
  const heldRef = useRef(false);
  const pendingRef = useRef<Promise<void> | null>(null);
  const mountedRef = useRef(false);
  const desiredRef = useRef(false);
  if (!tagRef.current) tagRef.current = `call-screen-${++nextOwnerId}`;
  desiredRef.current = activePhases.has(phase);

  useEffect(() => {
    const tag = tagRef.current!;

    if (!desiredRef.current) {
      if (heldRef.current) {
        heldRef.current = false;
        void deactivateKeepAwake(tag).catch((error) => {
          console.warn('Call keep-awake release failed', error);
        });
      }
      return undefined;
    }

    if (heldRef.current || pendingRef.current) return undefined;
    const activation = activateKeepAwakeAsync(tag)
      .then(() => {
        if (!mountedRef.current || !desiredRef.current) {
          return deactivateKeepAwake(tag);
        }
        heldRef.current = true;
        return undefined;
      })
      .catch((error) => {
        console.warn('Call keep-awake activation failed', error);
      })
      .finally(() => {
        if (pendingRef.current === activation) pendingRef.current = null;
      });
    pendingRef.current = activation;
    return undefined;
  }, [phase]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      const tag = tagRef.current!;
      if (heldRef.current) {
        heldRef.current = false;
        void deactivateKeepAwake(tag).catch((error) => {
          console.warn('Call keep-awake release failed', error);
        });
      }
      // A pending activation observes mountedRef/desiredRef and releases its tag
      // after the native promise resolves if this owner is no longer active.
    };
  }, []);
}

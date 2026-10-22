import { AppState, BackHandler, Platform } from 'react-native';
import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react';
import type { CallSession } from '../utils/call_session/call_session';
import type { CallCapabilities, CallTransportSnapshot } from '../types/call_transport';
import type { CallEvent, CallState } from '../types/call';
import { initialCallState, reduceCallState } from '../utils/call_state';
import { callMonotonicNowMs } from '../utils/call_clock';
import type { CallFailureNotice } from '../utils/call_failure';
import { getCallEndFailureCode, getCallFailureNotice } from '../utils/call_failure';
import { localCallHistory } from '../utils/call_history';
import type { ChatMessage } from '../types/chat';

type SessionPort = Pick<CallSession, 'prepare' | 'start' | 'hangup' | 'subscribe' | 'onError' | 'close'>;
interface SessionOwner {
  generation: number;
  session: SessionPort;
  unsubscribe?: () => void;
  unsubscribeError?: () => void;
  cleaned: boolean;
  failureReported?: boolean;
}

export interface CallSessionOptions {
  /** Kept for compatibility with the frozen CallSession API; one instance can serve one attempt. */
  session?: SessionPort;
  /** Preferred for production: every attempt receives a fresh, owned session. */
  createSession?: () => SessionPort;
  capabilities?: CallCapabilities;
  requestPermission?: () => Promise<'granted' | 'denied' | 'permanently_denied'>;
  now?: () => number;
  onReturnToChat?: () => void;
  onCallRecord?: (record: ChatMessage) => void;
  onBackConfirmation?: () => void;
  onPermissionSettings?: () => void;
  onCleanupError?: (error: unknown) => void;
  onFailure?: (notice: CallFailureNotice) => void;
  ringtone?: { playLoop: () => void; stop: () => void };
  initializeAttempt?: (session: SessionPort) => Promise<boolean>;
}

const unavailable: CallCapabilities = { serverAvailable: false, nativeAvailable: false };
const EXIT_PHASES: CallState['phase'][] = ['ACTIVE', 'RECONNECTING', 'PREPARING', 'RINGING', 'CONNECTING', 'SWITCH_PREPARING', 'REQUESTING_PERMISSION'];

export function useCallSession(options: CallSessionOptions = {}) {
  const {
    session: compatibilitySession,
    createSession,
    capabilities = unavailable,
    now: suppliedNow,
    ringtone,
  } = options;
  const optionsRef = useRef(options);
  optionsRef.current = options;
  const [state, dispatch] = useReducer((current: CallState, event: CallEvent) => reduceCallState(current, event).state, initialCallState);
  const [failureNotice, setFailureNotice] = useState<CallFailureNotice | null>(null);
  const stateRef = useRef(state);
  const mountedRef = useRef(true);
  const generationRef = useRef(0);
  const connectedRef = useRef(false);
  const ownerRef = useRef<SessionOwner | null>(null);
  const snapshotRef = useRef<Readonly<CallTransportSnapshot> | null>(null);
  const requestedAtRef = useRef(0);
  const compatibilityConsumedRef = useRef(false);
  stateRef.current = state;
  const now = suppliedNow ?? callMonotonicNowMs;
  const ringing = state.phase === 'PREPARING' || state.phase === 'RINGING';
  const canStart = Platform.OS === 'android' && capabilities.serverAvailable && capabilities.nativeAvailable && Boolean(createSession || (compatibilitySession && !compatibilityConsumedRef.current));

  const reportCleanupError = useCallback((error: unknown) => {
    try { optionsRef.current.onCleanupError?.(error); } catch { /* diagnostics must not block cleanup */ }
  }, []);

  const cleanupOwner = useCallback((owner: SessionOwner | null) => {
    if (!owner || owner.cleaned) return;
    owner.cleaned = true;
    for (const cleanup of [owner.unsubscribe, owner.unsubscribeError]) {
      try {
        cleanup?.();
      } catch (error) { reportCleanupError(error); }
    }
    try {
      void Promise.resolve(owner.session.close()).catch(reportCleanupError);
    } catch (error) { reportCleanupError(error); }
  }, [reportCleanupError]);

  const releaseOwnedSession = useCallback((generation: number) => {
    const owner = ownerRef.current;
    if (!owner || owner.generation !== generation) return;
    ownerRef.current = null;
    cleanupOwner(owner);
  }, [cleanupOwner]);

  const scheduleReturnToChat = useCallback((oldOwnerGeneration: number) => {
    releaseOwnedSession(oldOwnerGeneration);
    const returnGeneration = oldOwnerGeneration + 1;
    generationRef.current = returnGeneration;
    queueMicrotask(() => {
      if (mountedRef.current && returnGeneration === generationRef.current) optionsRef.current.onReturnToChat?.();
    });
  }, [releaseOwnedSession]);

  const reportAttemptFailure = useCallback((owner: SessionOwner | null, generation: number, code?: string) => {
    if (generation !== generationRef.current || owner?.failureReported) return false;
    if (owner) owner.failureReported = true;
    const notice = getCallFailureNotice(code);
    setFailureNotice(notice);
    try { optionsRef.current.onFailure?.(notice); } catch (error) { reportCleanupError(error); }
    return true;
  }, [reportCleanupError]);

  const invokePromise = useCallback((operation: () => void | Promise<void>, onError?: (error: unknown) => void) => {
    try {
      const result = operation();
      void Promise.resolve(result).catch((error) => { onError?.(error); });
    } catch (error) {
      onError?.(error);
    }
  }, []);

  const retireAttempt = useCallback((reason: 'user_hangup' | 'backgrounded') => {
    generationRef.current += 1;
    const owner = ownerRef.current;
    ownerRef.current = null;
    if (owner?.session) invokePromise(() => owner.session.hangup(reason), reportCleanupError);
    cleanupOwner(owner);
  }, [cleanupOwner, invokePromise, reportCleanupError]);

  const executeEffects = useCallback((effects: readonly { type: string }[]) => {
    for (const effect of effects) {
      if (effect.type === 'return_to_chat') {
        const record = localCallHistory(stateRef.current, snapshotRef.current, requestedAtRef.current);
        if (record) {
          try { optionsRef.current.onCallRecord?.(record); } catch (error) { reportCleanupError(error); }
        }
        snapshotRef.current = null;
        scheduleReturnToChat(generationRef.current);
        stateRef.current = initialCallState;
        dispatch({ type: 'reset_to_idle' });
      }
      if (effect.type === 'show_back_confirmation') optionsRef.current.onBackConfirmation?.();
    }
  }, [reportCleanupError, scheduleReturnToChat]);

  const dispatchEvent = useCallback((event: CallEvent) => {
    if (!mountedRef.current) return;
    const transition = reduceCallState(stateRef.current, event);
    stateRef.current = transition.state;
    dispatch(event);
    executeEffects(transition.effects);
  }, [executeEffects]);

  const installSession = useCallback((owned: SessionPort, generation: number) => {
    const owner: SessionOwner = { generation, session: owned, cleaned: false };
    ownerRef.current = owner;
    connectedRef.current = false;
    snapshotRef.current = null;
    try {
      owner.unsubscribe = owned.subscribe((snapshot: Readonly<CallTransportSnapshot>) => {
        if (!mountedRef.current || generation !== generationRef.current) return;
        snapshotRef.current = snapshot;
        if (snapshot.status === 'starting') dispatchEvent({ type: 'server_state', state: 'PREPARING', callId: snapshot.callId });
        if (snapshot.status === 'connected' && snapshot.callId) {
          if (connectedRef.current) dispatchEvent({ type: 'transport_resumed', nowMs: now() });
          else {
            connectedRef.current = true;
            dispatchEvent({
              type: 'call_active',
              callId: snapshot.callId,
              connectedAtMs: snapshot.connectedAtMonotonicMs ?? now(),
              connectedAtServerMs: snapshot.connectedAtServerMs,
            });
          }
        }
        if (snapshot.status === 'recovering') dispatchEvent({ type: 'transport_lost', nowMs: now() });
        if (snapshot.status === 'failed') {
          reportAttemptFailure(owner, generation, snapshot.errorCode);
          dispatchEvent({ type: 'call_ended', nowMs: now(), errorCode: snapshot.errorCode });
        }
        if (snapshot.status === 'closed') {
          const code = getCallEndFailureCode(snapshot.endReason);
          if (code) reportAttemptFailure(owner, generation, code);
          dispatchEvent({ type: 'call_ended', nowMs: now(), errorCode: code });
        }
      });
      owner.unsubscribeError = owned.onError((error) => {
        if (generation === generationRef.current) {
          const code = typeof error === 'string' ? error : undefined;
          reportAttemptFailure(owner, generation, code);
          dispatchEvent({ type: 'call_ended', nowMs: now(), errorCode: code });
        }
        reportCleanupError(error);
      });
    } catch (error) {
      ownerRef.current = null;
      reportCleanupError(error);
      cleanupOwner(owner);
      throw error;
    }
  }, [cleanupOwner, dispatchEvent, now, reportAttemptFailure, reportCleanupError]);

  const start = useCallback(async (requiresChatSwitch = true) => {
    if (!canStart || stateRef.current.phase !== 'IDLE') return false;
    setFailureNotice(null);
    requestedAtRef.current = Date.now();
    const attemptGeneration = generationRef.current + 1;
    generationRef.current = attemptGeneration;
    let owned: SessionPort | null;
    try { owned = createSession ? createSession() : compatibilityConsumedRef.current ? null : compatibilitySession ?? null; }
    catch (error) {
      reportCleanupError(error);
      const code = error instanceof Error ? error.message : undefined;
      reportAttemptFailure(null, attemptGeneration, code);
      scheduleReturnToChat(attemptGeneration);
      return false;
    }
    if (!owned) {
      reportAttemptFailure(null, attemptGeneration, 'CALL_RESOLVER_UNAVAILABLE');
      scheduleReturnToChat(attemptGeneration);
      return false;
    }
    compatibilityConsumedRef.current = true;
    const generation = attemptGeneration;
    connectedRef.current = false;
    try { installSession(owned, generation); } catch (error) {
      reportAttemptFailure(null, generation, error instanceof Error ? error.message : undefined);
      scheduleReturnToChat(generation);
      return false;
    }
    const clientRequestId = `ui-${now()}-${Math.random().toString(36).slice(2, 8)}`;
    dispatchEvent({ type: 'audio_capability', capability: 'available' });
    dispatchEvent({ type: 'request_call', requiresChatSwitch, clientRequestId });
    return true;
  }, [canStart, compatibilitySession, createSession, dispatchEvent, installSession, now, reportAttemptFailure, reportCleanupError, scheduleReturnToChat]);

  const hangup = useCallback(() => {
    if (!EXIT_PHASES.includes(stateRef.current.phase)) return;
    retireAttempt('user_hangup');
    dispatchEvent({ type: 'user_hangup', nowMs: now() });
  }, [dispatchEvent, now, retireAttempt]);

  useEffect(() => {
    const subscription = AppState.addEventListener('change', (next) => {
      if (next !== 'active' && EXIT_PHASES.includes(stateRef.current.phase)) {
        retireAttempt('backgrounded');
        dispatchEvent({ type: 'app_backgrounded', nowMs: now() });
      }
    });
    const back = BackHandler.addEventListener('hardwareBackPress', () => {
      if (!EXIT_PHASES.includes(stateRef.current.phase)) return false;
      dispatchEvent({ type: 'back_requested' });
      return true;
    });
    return () => { subscription.remove(); back.remove(); };
  }, [dispatchEvent, now, retireAttempt]);

  useEffect(() => {
    if (state.phase !== 'REQUESTING_PERMISSION') return undefined;
    let cancelled = false;
    const generation = generationRef.current;
    const { requestPermission, initializeAttempt, onPermissionSettings } = optionsRef.current;
    const pending = Promise.resolve().then(() => requestPermission?.() ?? 'denied' as const);
    pending.then((result) => {
      if (cancelled || generation !== generationRef.current) return;
      if (result === 'permanently_denied') onPermissionSettings?.();
      if (result !== 'granted') {
        dispatchEvent({ type: result === 'permanently_denied' ? 'permission_permanently_denied' : 'permission_denied' });
        return;
      }
      const owner = ownerRef.current;
      const initialize = initializeAttempt ? initializeAttempt(owner!.session) : Promise.resolve(true);
      initialize.then((available) => {
        if (cancelled || generation !== generationRef.current) return;
        if (available) dispatchEvent({ type: 'permission_granted' });
        else {
          reportAttemptFailure(ownerRef.current, generation, 'NATIVE_CALL_UNAVAILABLE');
          releaseOwnedSession(generation);
          dispatchEvent({ type: 'call_ended', nowMs: now(), errorCode: 'NATIVE_CALL_UNAVAILABLE' });
        }
      }).catch((error) => {
        if (cancelled || generation !== generationRef.current) return;
        reportCleanupError(error);
        releaseOwnedSession(generation);
        reportAttemptFailure(ownerRef.current, generation, error instanceof Error ? error.message : 'NATIVE_CALL_UNAVAILABLE');
        dispatchEvent({ type: 'call_ended', nowMs: now(), errorCode: error instanceof Error ? error.message : 'NATIVE_CALL_UNAVAILABLE' });
      });
    }).catch((error) => {
      if (!cancelled && generation === generationRef.current) { reportCleanupError(error); dispatchEvent({ type: 'permission_denied' }); }
    });
    return () => { cancelled = true; };
  }, [dispatchEvent, now, releaseOwnedSession, reportAttemptFailure, reportCleanupError, state.phase]);

  useEffect(() => {
    if (!ownerRef.current || !state.clientRequestId) return undefined;
    const generation = generationRef.current;
    if (state.phase === 'SWITCH_PREPARING') {
      const owned = ownerRef.current.session;
      void Promise.resolve(owned.prepare(state.clientRequestId)).then(() => {
        if (generation === generationRef.current) dispatchEvent({ type: 'switch_ready' });
      }).catch((error) => {
        if (generation === generationRef.current) {
          reportCleanupError(error);
          const code = error instanceof Error ? error.message : undefined;
          reportAttemptFailure(ownerRef.current, generation, code);
          dispatchEvent({ type: 'switch_failed', errorCode: code });
        }
      });
    }
    if (state.phase === 'CONNECTING') dispatchEvent({ type: 'transport_authenticated' });
    if (state.phase === 'PREPARING') {
      const owned = ownerRef.current.session;
      void Promise.resolve(owned.start(state.clientRequestId, state.requiresChatSwitch ? 'prepared_switch' : 'direct_no_chat')).catch((error) => {
        if (generation === generationRef.current) {
          reportCleanupError(error);
          const code = error instanceof Error ? error.message : undefined;
          reportAttemptFailure(ownerRef.current, generation, code);
          dispatchEvent({ type: 'call_ended', nowMs: now(), errorCode: code });
        }
      });
    }
    return undefined;
  }, [dispatchEvent, now, reportAttemptFailure, reportCleanupError, state.clientRequestId, state.phase, state.requiresChatSwitch]);

  useEffect(() => {
    if (ringing) ringtone?.playLoop(); else ringtone?.stop();
    return () => ringtone?.stop();
  }, [ringing, ringtone]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      generationRef.current += 1;
      const owner = ownerRef.current;
      ownerRef.current = null;
      cleanupOwner(owner);
    };
  }, [cleanupOwner]);

  const dismissFailure = useCallback(() => setFailureNotice(null), []);
  return useMemo(() => ({ state, canStart, start, hangup, dispatch: dispatchEvent, failureNotice, dismissFailure }), [canStart, dismissFailure, dispatchEvent, failureNotice, hangup, start, state]);
}

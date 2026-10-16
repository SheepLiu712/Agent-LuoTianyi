import React from 'react';
import { act, create } from 'react-test-renderer';
import { CallFailureBanner } from '../components/call/CallFailureBanner';
import { useCallSession } from '../hooks/useCallSession';
import { getCallFailureNotice } from '../utils/call_failure';
import { THEMES } from '../utils/theme';
import type { CallSession } from '../utils/call_session/call_session';

jest.mock('react-native', () => ({
  __esModule: true,
  Platform: { OS: 'android' },
  AppState: { addEventListener: () => ({ remove: jest.fn() }) },
  BackHandler: { addEventListener: () => ({ remove: jest.fn() }) },
  Pressable: 'Pressable', Text: 'Text', View: 'View',
  StyleSheet: { absoluteFillObject: {}, create: (styles: any) => styles },
}));

function textOf(node: any): string {
  return React.Children.toArray(node?.props?.children).map((child: any) => typeof child === 'string' ? child : textOf(child)).join('');
}

function Probe({ session, createSession, onResult, onFailure, onReturnToChat, requestPermission, initializeAttempt }: { session?: CallSession; createSession?: () => CallSession; onResult: (result: any) => void; onFailure?: (notice: unknown) => void; onReturnToChat?: () => void; requestPermission?: () => Promise<'granted' | 'denied' | 'permanently_denied'>; initializeAttempt?: (session: unknown) => Promise<boolean> }) {
  const result = useCallSession({
    session,
    createSession,
    capabilities: { serverAvailable: true, nativeAvailable: true },
    requestPermission: requestPermission ?? (async () => 'granted'),
    initializeAttempt,
    onFailure,
    onReturnToChat,
  });
  onResult(result);
  return null;
}

function sessionPort() {
  let snapshotListener!: (snapshot: any) => void;
  let errorListener!: (error: unknown) => void;
  return {
    session: {
      prepare: jest.fn(async () => undefined),
      start: jest.fn(async () => undefined),
      hangup: jest.fn(async () => undefined),
      close: jest.fn(),
      subscribe: jest.fn((listener: (snapshot: any) => void) => { snapshotListener = listener; return () => undefined; }),
      onError: jest.fn((listener: (error: unknown) => void) => { errorListener = listener; return () => undefined; }),
    } as unknown as CallSession,
    emitSnapshot: (snapshot: any) => snapshotListener(snapshot),
    emitError: (error: unknown) => errorListener(error),
  };
}

describe('call failure user-visible feedback', () => {
  it('maps known and unknown codes to safe actionable copy without raw details', () => {
    expect(getCallFailureNotice('CALL_CONNECTION_LOST')).toEqual({ title: '通话连接失败', message: '未能建立通话连接，请检查网络后重试。' });
    const notice = getCallFailureNotice('provider=https://secret.example/token=abc stack Error: leaked');
    expect(notice.message).toContain('检查网络');
    expect(notice.message).not.toContain('secret.example');
    expect(notice.message).not.toContain('abc');
  });

  it('renders a dismissible banner using the normal app theme affordance', () => {
    const onDismiss = jest.fn();
    let tree!: ReturnType<typeof create>;
    act(() => { tree = create(<CallFailureBanner notice={getCallFailureNotice('CALL_CONNECTION_LOST')} theme={THEMES.dark} onDismiss={onDismiss} />); });
    const renderedText = tree.root.findAllByType('Text' as any).map(textOf).join('');
    expect(renderedText).toContain('通话连接失败');
    expect(renderedText).toContain('检查网络后重试');
    tree.root.findByProps({ accessibilityLabel: '关闭通话提示' }).props.onPress();
    expect(onDismiss).toHaveBeenCalledTimes(1);
    act(() => tree.unmount());
  });

  it('keeps one failure notice after return-to-chat, deduplicates callback and snapshot, and clears it for the next attempt', async () => {
    const port = sessionPort();
    let result: any;
    let root!: ReturnType<typeof create>;
    const onFailure = jest.fn();
    act(() => { root = create(<Probe session={port.session} onResult={(value) => { result = value; }} onFailure={onFailure} />); });
    await act(async () => { expect(await result.start(false)).toBe(true); });
    act(() => { result.dispatch({ type: 'permission_granted' }); });
    act(() => { result.dispatch({ type: 'transport_authenticated' }); });
    act(() => { port.emitSnapshot({ status: 'starting', callId: 'call-1', activeDurationMs: 0 }); });
    act(() => { port.emitError('CALL_CONNECTION_LOST'); });
    expect(result.state.phase).toBe('IDLE');
    expect(result.failureNotice).toEqual(getCallFailureNotice('CALL_CONNECTION_LOST'));

    act(() => { port.emitSnapshot({ status: 'failed', callId: 'call-1', errorCode: 'provider-secret', activeDurationMs: 0 }); });
    expect(result.failureNotice).toEqual(getCallFailureNotice('CALL_CONNECTION_LOST'));
    expect(onFailure).toHaveBeenCalledTimes(1);
    expect(onFailure).toHaveBeenCalledWith(getCallFailureNotice('CALL_CONNECTION_LOST'));
    act(() => result.dismissFailure());
    expect(result.failureNotice).toBeNull();
    act(() => root.unmount());
    expect(port.session.close).toHaveBeenCalled();
  });

  it('does not create a failure notice for a user hangup', async () => {
    const port = sessionPort();
    let result: any;
    let root!: ReturnType<typeof create>;
    act(() => { root = create(<Probe session={port.session} onResult={(value) => { result = value; }} />); });
    await act(async () => { expect(await result.start(false)).toBe(true); });
    act(() => result.hangup());
    expect(result.failureNotice).toBeNull();
    act(() => root.unmount());
  });

  it('maps AUTH_REJECTED to the safe re-login message', () => {
    expect(getCallFailureNotice('AUTH_REJECTED')).toEqual(getCallFailureNotice('CALL_AUTH_REQUIRED'));
  });

  it('clears the previous notice at a new attempt and ignores a retired attempt failure', async () => {
    const ports = [sessionPort(), sessionPort()];
    let nextPort = 0;
    let result: any;
    let root!: ReturnType<typeof create>;
    act(() => {
      root = create(<Probe createSession={() => ports[nextPort++].session} onResult={(value) => { result = value; }} />);
    });
    await act(async () => { expect(await result.start(false)).toBe(true); });
    act(() => { ports[0].emitError('CALL_CONNECTION_LOST'); });
    expect(result.failureNotice).not.toBeNull();
    act(() => result.dismissFailure());
    expect(result.failureNotice).toBeNull();
    // A late event from the retired owner cannot recreate a dismissed notice.
    act(() => { ports[0].emitError('provider-secret'); });
    expect(result.failureNotice).toBeNull();
    await act(async () => { expect(await result.start(false)).toBe(true); });
    expect(result.failureNotice).toBeNull();
    act(() => { ports[1].emitError('CALL_CONNECTION_LOST'); });
    expect(result.failureNotice).toEqual(getCallFailureNotice('CALL_CONNECTION_LOST'));
    act(() => root.unmount());
  });

  it('calls onReturnToChat exactly once after failure and suppresses a queued return when a new attempt starts', async () => {
    const ports = [sessionPort(), sessionPort()];
    let nextPort = 0;
    const onReturnToChat = jest.fn();
    let result: any;
    let root!: ReturnType<typeof create>;
    act(() => { root = create(<Probe createSession={() => ports[nextPort++].session} onResult={(value) => { result = value; }} onReturnToChat={onReturnToChat} />); });
    await act(async () => { expect(await result.start(false)).toBe(true); });
    act(() => { ports[0].emitError('CALL_CONNECTION_LOST'); });
    await act(async () => { expect(await result.start(false)).toBe(true); });
    await act(async () => { await Promise.resolve(); });
    expect(onReturnToChat).not.toHaveBeenCalled();
    act(() => root.unmount());
  });

  it('calls onReturnToChat exactly once when the failed attempt remains retired', async () => {
    const port = sessionPort();
    const onReturnToChat = jest.fn();
    let result: any;
    let root!: ReturnType<typeof create>;
    act(() => { root = create(<Probe session={port.session} onResult={(value) => { result = value; }} onReturnToChat={onReturnToChat} />); });
    await act(async () => { expect(await result.start(false)).toBe(true); });
    act(() => { port.emitError('CALL_CONNECTION_LOST'); });
    await act(async () => { await Promise.resolve(); });
    expect(onReturnToChat).toHaveBeenCalledTimes(1);
    act(() => root.unmount());
  });

  it('shows a safe notice for synchronous create and initialization failures, while permission denial stays non-failure', async () => {
    const onReturnToChat = jest.fn();
    let result: any;
    let root!: ReturnType<typeof create>;
    act(() => {
      root = create(<Probe createSession={() => { throw new Error('provider=https://secret/token=abc'); }} onResult={(value) => { result = value; }} />);
    });
    await act(async () => { expect(await result.start(false)).toBe(false); });
    expect(result.failureNotice?.message).not.toContain('secret');
    act(() => root.unmount());

    const initialized = sessionPort();
    act(() => {
      root = create(<Probe session={initialized.session} initializeAttempt={async () => false} onResult={(value) => { result = value; }} />);
    });
    await act(async () => { expect(await result.start(false)).toBe(true); });
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(result.failureNotice).toEqual(getCallFailureNotice('NATIVE_CALL_UNAVAILABLE'));
    act(() => root.unmount());

    const port = sessionPort();
    act(() => {
      root = create(<Probe session={port.session} requestPermission={async () => 'denied'} onResult={(value) => { result = value; }} />);
    });
    await act(async () => { expect(await result.start(false)).toBe(true); });
    expect(result.failureNotice).toBeNull();
    act(() => root.unmount());
    expect(onReturnToChat).not.toHaveBeenCalled();
  });

  it('returns normally when transport closes after an active call and does not show a failure notice', async () => {
    const port = sessionPort();
    let result: any;
    let root!: ReturnType<typeof create>;
    act(() => { root = create(<Probe session={port.session} onResult={(value) => { result = value; }} />); });
    await act(async () => { expect(await result.start(false)).toBe(true); });
    act(() => { result.dispatch({ type: 'permission_granted' }); });
    act(() => { result.dispatch({ type: 'transport_authenticated' }); });
    act(() => { port.emitSnapshot({ status: 'starting', callId: 'call-1', activeDurationMs: 0 }); });
    act(() => { port.emitSnapshot({ status: 'connected', callId: 'call-1', connectedAtMonotonicMs: 100, activeDurationMs: 0 }); });
    act(() => { port.emitSnapshot({ status: 'closed', callId: 'call-1', activeDurationMs: 500 }); });
    await act(async () => { await Promise.resolve(); });
    expect(result.state.phase).toBe('IDLE');
    expect(result.failureNotice).toBeNull();
    act(() => root.unmount());
  });

  it.each(['snapshot', 'callback'] as const)('keeps terminal cleanup when onFailure throws for a %s failure', async (source) => {
    const port = sessionPort();
    const onFailure = jest.fn(() => { throw new Error('observer failed'); });
    const onReturnToChat = jest.fn();
    let result: any;
    let root!: ReturnType<typeof create>;
    act(() => { root = create(<Probe session={port.session} onResult={(value) => { result = value; }} onFailure={onFailure} onReturnToChat={onReturnToChat} />); });
    await act(async () => { expect(await result.start(false)).toBe(true); });
    act(() => { result.dispatch({ type: 'permission_granted' }); });
    act(() => { result.dispatch({ type: 'transport_authenticated' }); });
    act(() => { port.emitSnapshot({ status: 'starting', callId: 'call-1', activeDurationMs: 0 }); });
    if (source === 'snapshot') {
      expect(() => act(() => { port.emitSnapshot({ status: 'failed', callId: 'call-1', errorCode: 'CALL_CONNECTION_LOST', activeDurationMs: 0 }); })).not.toThrow();
    } else {
      expect(() => act(() => { port.emitError('CALL_CONNECTION_LOST'); })).not.toThrow();
    }
    await act(async () => { await Promise.resolve(); });
    expect(result.state.phase).toBe('IDLE');
    expect(result.failureNotice).toEqual(getCallFailureNotice('CALL_CONNECTION_LOST'));
    expect(onFailure).toHaveBeenCalledTimes(1);
    expect(onReturnToChat).toHaveBeenCalledTimes(1);
    expect(port.session.close).toHaveBeenCalledTimes(1);
    act(() => root.unmount());
  });

  it('does not reject or leak when synchronous creation fails and the failure observer throws', async () => {
    const onFailure = jest.fn(() => { throw new Error('observer failed'); });
    let result: any;
    let root!: ReturnType<typeof create>;
    act(() => { root = create(<Probe createSession={() => { throw new Error('CALL_AUTH_REQUIRED'); }} onResult={(value) => { result = value; }} onFailure={onFailure} />); });
    await act(async () => { await expect(result.start(false)).resolves.toBe(false); });
    expect(result.failureNotice).toEqual(getCallFailureNotice('CALL_AUTH_REQUIRED'));
    expect(onFailure).toHaveBeenCalledTimes(1);
    act(() => root.unmount());
  });

  it('covers subscribe installation, initialize rejection, prepare rejection, and start rejection as safe failures', async () => {
    const makeSession = (mode: 'subscribe' | 'initialize' | 'prepare' | 'start') => {
      const port = sessionPort();
      if (mode === 'subscribe') port.session.subscribe = jest.fn(() => { throw new Error('CALL_CONNECTION_LOST'); });
      if (mode === 'prepare') port.session.prepare = jest.fn(async () => { throw new Error('CALL_CONNECTION_LOST'); });
      if (mode === 'start') port.session.start = jest.fn(async () => { throw new Error('CALL_CONNECTION_LOST'); });
      return port;
    };
    for (const mode of ['subscribe', 'initialize', 'prepare', 'start'] as const) {
      const port = makeSession(mode);
      let result: any;
      let root!: ReturnType<typeof create>;
      act(() => { root = create(<Probe session={port.session} initializeAttempt={mode === 'initialize' ? async () => { throw new Error('CALL_CONNECTION_LOST'); } : undefined} onResult={(value) => { result = value; }} />); });
      await act(async () => { expect(await result.start(mode === 'prepare')).toBe(mode !== 'subscribe'); });
      await act(async () => { for (let i = 0; i < 8; i += 1) await Promise.resolve(); });
      if (!result.failureNotice) throw new Error(`missing failure notice for ${mode}, state=${result.state.phase}`);
      expect(result.failureNotice).toEqual(getCallFailureNotice('CALL_CONNECTION_LOST'));
      act(() => root.unmount());
    }
  });
});

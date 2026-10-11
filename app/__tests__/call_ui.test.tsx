import React from 'react';
import { act, create } from 'react-test-renderer';
import { CallScreen } from '../components/call/CallScreen';
import { CallHistoryBubble } from '../components/call/CallHistoryBubble';
import { useCallSession } from '../hooks/useCallSession';
import { initialCallState } from '../utils/call_state';
import { THEMES } from '../utils/theme';
import type { CallSession } from '../utils/call_session/call_session';

jest.mock('react-native-safe-area-context', () => ({ useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }) }));
jest.mock('react-native', () => {
  const listeners = new Set<(state: string) => void>();
  (globalThis as any).__emitAppState = (state: string) => listeners.forEach((listener) => listener(state));
  return {
    __esModule: true,
    Platform: { OS: 'android' },
    AppState: { addEventListener: (_type: string, listener: (state: string) => void) => { listeners.add(listener); return { remove: () => listeners.delete(listener) }; } },
    BackHandler: { addEventListener: (_type: string, listener: () => boolean) => { (globalThis as any).__back = listener; return { remove: () => { (globalThis as any).__back = undefined; } }; } },
    Image: 'Image', Pressable: 'Pressable', Text: 'Text', View: 'View',
    StyleSheet: { absoluteFillObject: { position: 'absolute' }, create: (styles: any) => styles },
  };
});

function textOf(node: any): string {
  return React.Children.toArray(node?.props?.children).map((child: any) => typeof child === 'string' ? child : textOf(child)).join('');
}

function Probe({ options, onState }: { options: Parameters<typeof useCallSession>[0]; onState: (state: any) => void }) {
  const result = useCallSession(options);
  onState(result);
  return null;
}

const theme = THEMES.dark;

describe('call UI', () => {
  beforeEach(() => {
    jest.useFakeTimers();
    jest.setSystemTime(5_000);
  });

  afterEach(() => {
    jest.runOnlyPendingTimers();
    jest.useRealTimers();
    (globalThis as any).__back = undefined;
  });

  it('shows ACTIVE duration and keeps the same timer/scene while reconnecting', () => {
    const onHangup = jest.fn();
    const reconnecting = { ...initialCallState, phase: 'RECONNECTING' as const, callId: 'c1', activeStartedAtMs: 0, activeDurationAtDisconnectMs: 5000 };
    let tree!: ReturnType<typeof create>;
    act(() => { tree = create(<CallScreen state={reconnecting} theme={theme} onHangup={onHangup} onBack={jest.fn()} />); });
    expect(textOf(tree.root.findByProps({ accessibilityLabel: '挂断通话' }))).toBe('挂断');
    const texts = tree.root.findAllByType('Text' as any).map(textOf).join('');
    expect(texts).toContain('正在重新连接');
    expect(texts).toContain('连接中断，正在恢复');
    expect(jest.getTimerCount()).toBe(1);
    act(() => { jest.advanceTimersByTime(1000); });
    tree.root.findByProps({ accessibilityLabel: '挂断通话' }).props.onPress();
    expect(onHangup).toHaveBeenCalledTimes(1);
    act(() => tree.unmount());
    expect(jest.getTimerCount()).toBe(0);
  });

  it.each([
    ['cancelled', '[语音通话] 已取消'],
    ['declined', '[语音通话] 未接听'],
    ['failed', '[语音通话] 通话失败'],
  ] as const)('renders %s history without a playback control', (outcome, label) => {
    const tree = CallHistoryBubble({ message: { uuid: outcome, type: 'call', content: '', isUser: true, callOutcome: outcome }, theme });
    expect(textOf(tree)).toContain(label);
    expect(textOf(tree)).not.toContain('播放');
    expect((tree as any).props.style).toEqual(expect.arrayContaining([expect.objectContaining({ justifyContent: 'flex-end' })]));
  });

  it('renders a connected history duration in the requested right-aligned compact format', () => {
    const tree = CallHistoryBubble({ message: { uuid: 'connected', type: 'call', content: '', isUser: true, callOutcome: 'connected', durationMs: 323000 }, theme });
    expect(textOf(tree)).toContain('[语音通话] 05:23');
  });

  it('does not start on unavailable Android capabilities and closes owned resources on unmount', async () => {
    const unavailableSession = { prepare: jest.fn(), start: jest.fn(), hangup: jest.fn(), subscribe: jest.fn(() => jest.fn()), onError: jest.fn(() => jest.fn()), close: jest.fn() } as unknown as CallSession;
    let unavailable: any;
    let root!: ReturnType<typeof create>;
    act(() => { root = create(<Probe options={{ session: unavailableSession, capabilities: { serverAvailable: false, nativeAvailable: false }, now: () => 100 }} onState={(value) => { unavailable = value; }} />); });
    await act(async () => { expect(await unavailable.start()).toBe(false); });
    expect(unavailableSession.prepare).not.toHaveBeenCalled();
    expect(unavailableSession.start).not.toHaveBeenCalled();
    act(() => root.unmount());
    expect(unavailableSession.close).not.toHaveBeenCalled();
  });

  it('asks permission before prepare/start and carries one client request id through both ports', async () => {
    const prepare = jest.fn(async (_id: string) => undefined);
    const startCall = jest.fn(async (_id: string, _mode: 'prepared_switch' | 'direct_no_chat') => undefined);
    const session = { prepare, start: startCall, hangup: jest.fn(), subscribe: jest.fn(() => jest.fn()), onError: jest.fn(() => jest.fn()), close: jest.fn() } as unknown as CallSession;
    let result: any;
    const permission = jest.fn(async () => 'granted' as const);
    let root!: ReturnType<typeof create>;
    act(() => { root = create(<Probe options={{ session, capabilities: { serverAvailable: true, nativeAvailable: true }, requestPermission: permission, now: () => 100 }} onState={(value) => { result = value; }} />); });
    await act(async () => { expect(await result.start(true)).toBe(true); });
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(permission).toHaveBeenCalledTimes(1);
    expect(prepare).toHaveBeenCalledTimes(1);
    expect(startCall).toHaveBeenCalledTimes(1);
    expect(startCall.mock.calls[0][0]).toBe(prepare.mock.calls[0][0]);
    expect(startCall.mock.calls[0][1]).toBe('prepared_switch');
    act(() => root.unmount());
  });

  it('ends on background, confirms hardware back, and removes lifecycle listeners on unmount', async () => {
    const session = { prepare: jest.fn(async () => undefined), start: jest.fn(async () => undefined), hangup: jest.fn(async () => undefined), subscribe: jest.fn(() => jest.fn()), onError: jest.fn(() => jest.fn()), close: jest.fn() } as unknown as CallSession;
    let result: any;
    let root!: ReturnType<typeof create>;
    act(() => { root = create(<Probe options={{ session, capabilities: { serverAvailable: true, nativeAvailable: true }, requestPermission: () => new Promise(() => {}), now: () => 100 }} onState={(value) => { result = value; }} />); });
    await act(async () => { expect(await result.start(false)).toBe(true); });
    expect(result.state.phase).toBe('REQUESTING_PERMISSION');
    act(() => { result.dispatch({ type: 'permission_granted' }); });
    act(() => { result.dispatch({ type: 'transport_authenticated' }); });
    act(() => { result.dispatch({ type: 'call_active', callId: 'c1', connectedAtMs: 100 }); });
    expect(result.state.phase).toBe('ACTIVE');
    expect((globalThis as any).__back()).toBe(true);
    act(() => { (globalThis as any).__emitAppState('background'); });
    expect(session.hangup).toHaveBeenCalledWith('backgrounded');
    expect(result.state.phase).toBe('IDLE');
    act(() => root.unmount());
    expect((globalThis as any).__back).toBeUndefined();
  });

  it('drives ACTIVE and reconnect recovery from real transport snapshots and owns ringtone cleanup', async () => {
    let listener!: (snapshot: any) => void;
    const ringtone = { playLoop: jest.fn(), stop: jest.fn() };
    const session = {
      prepare: jest.fn(async () => undefined), start: jest.fn(async () => undefined), hangup: jest.fn(async () => undefined), close: jest.fn(),
      subscribe: jest.fn((next: (snapshot: any) => void) => { listener = next; return jest.fn(); }),
      onError: jest.fn(() => jest.fn()),
    } as unknown as CallSession;
    let result: any;
    let root!: ReturnType<typeof create>;
    act(() => { root = create(<Probe options={{ session, capabilities: { serverAvailable: true, nativeAvailable: true }, ringtone, requestPermission: () => new Promise(() => {}), now: () => 100 }} onState={(value) => { result = value; }} />); });
    await act(async () => { expect(await result.start(false)).toBe(true); });
    act(() => { result.dispatch({ type: 'permission_granted' }); });
    act(() => { result.dispatch({ type: 'transport_authenticated' }); });
    act(() => { listener({ status: 'starting', callId: 'c1', activeDurationMs: 0 }); });
    expect(result.state.phase).toBe('PREPARING');
    act(() => { listener({ status: 'connected', callId: 'c1', activeDurationMs: 0 }); });
    expect(result.state.phase).toBe('ACTIVE');
    act(() => { listener({ status: 'recovering', callId: 'c1', activeDurationMs: 100 }); });
    expect(result.state.phase).toBe('RECONNECTING');
    act(() => { listener({ status: 'connected', callId: 'c1', activeDurationMs: 100 }); });
    expect(result.state.phase).toBe('ACTIVE');
    expect(ringtone.playLoop).toHaveBeenCalled();
    act(() => root.unmount());
    expect(ringtone.stop).toHaveBeenCalled();
  });

  it('invalidates generation on synchronous hangup failure, closes once, and ignores late connected snapshots', async () => {
    let listener!: (snapshot: any) => void;
    const cleanupError = jest.fn();
    const session = {
      prepare: jest.fn(async () => undefined), start: jest.fn(async () => undefined),
      hangup: jest.fn(() => { throw new Error('hangup-failed'); }), close: jest.fn(),
      subscribe: jest.fn((next: (snapshot: any) => void) => { listener = next; return jest.fn(); }),
      onError: jest.fn(() => jest.fn()),
    } as unknown as CallSession;
    let result: any; let root!: ReturnType<typeof create>;
    act(() => { root = create(<Probe options={{ session, capabilities: { serverAvailable: true, nativeAvailable: true }, requestPermission: () => new Promise(() => {}), onCleanupError: cleanupError }} onState={(value) => { result = value; }} />); });
    await act(async () => { await result.start(false); });
    act(() => { result.dispatch({ type: 'permission_granted' }); });
    act(() => { result.hangup(); });
    expect(result.state.phase).toBe('IDLE');
    expect(session.close).toHaveBeenCalledTimes(1);
    expect(cleanupError).toHaveBeenCalled();
    act(() => { listener?.({ status: 'connected', callId: 'late', activeDurationMs: 0 }); });
    expect(result.state.phase).toBe('IDLE');
    act(() => root.unmount());
    expect(session.close).toHaveBeenCalledTimes(1);
  });

  it('attempts both unsubscribe callbacks and close when either cleanup callback throws', async () => {
    const first = jest.fn(() => { throw new Error('unsubscribe'); });
    const second = jest.fn(() => { throw new Error('error-unsubscribe'); });
    const session = {
      prepare: jest.fn(async () => undefined), start: jest.fn(async () => undefined), hangup: jest.fn(), close: jest.fn(),
      subscribe: jest.fn(() => first), onError: jest.fn(() => second),
    } as unknown as CallSession;
    let result: any; let root!: ReturnType<typeof create>;
    act(() => { root = create(<Probe options={{ session, capabilities: { serverAvailable: true, nativeAvailable: true }, requestPermission: () => new Promise(() => {}), onCleanupError: jest.fn() }} onState={(value) => { result = value; }} />); });
    await act(async () => { await result.start(false); });
    act(() => { result.hangup(); });
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(first).toHaveBeenCalledTimes(1); expect(second).toHaveBeenCalledTimes(1); expect(session.close).toHaveBeenCalledTimes(1);
    act(() => root.unmount());
  });

  it('uses a fresh factory session after the first attempt and rolls back subscribe setup failure', async () => {
    const created: any[] = [];
    const makeSession = (broken = false) => ({
      prepare: jest.fn(async () => undefined), start: jest.fn(async () => undefined), hangup: jest.fn(), close: jest.fn(),
      subscribe: jest.fn(() => { if (broken) throw new Error('subscribe-failed'); return jest.fn(); }), onError: jest.fn(() => jest.fn()),
    });
    const factory = jest.fn(() => { const session = makeSession(created.length === 0); created.push(session); return session; });
    let result: any; let root!: ReturnType<typeof create>;
    act(() => { root = create(<Probe options={{ createSession: factory, capabilities: { serverAvailable: true, nativeAvailable: true }, requestPermission: () => new Promise(() => {}), onCleanupError: jest.fn() }} onState={(value) => { result = value; }} />); });
    await act(async () => { expect(await result.start(false)).toBe(false); });
    expect(created[0].close).toHaveBeenCalledTimes(1);
    await act(async () => { expect(await result.start(false)).toBe(true); });
    expect(factory).toHaveBeenCalledTimes(2);
    expect(created[1]).not.toBe(created[0]);
    act(() => root.unmount());
  });

  it('closes a pending native init attempt and ignores its late available result', async () => {
    let resolveInitialize!: (available: boolean) => void;
    const close = jest.fn(async () => undefined);
    const session = {
      prepare: jest.fn(), start: jest.fn(), hangup: jest.fn(), close,
      subscribe: jest.fn(() => jest.fn()), onError: jest.fn(() => jest.fn()),
    } as unknown as CallSession;
    let result: any; let root!: ReturnType<typeof create>;
    act(() => {
      root = create(<Probe options={{
        createSession: () => session,
        capabilities: { serverAvailable: true, nativeAvailable: true },
        requestPermission: async () => 'granted',
        initializeAttempt: () => new Promise((resolve) => { resolveInitialize = resolve; }),
      }} onState={(value) => { result = value; }} />);
    });
    await act(async () => { expect(await result.start(false)).toBe(true); await Promise.resolve(); });
    act(() => result.hangup());
    resolveInitialize(true);
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(close).toHaveBeenCalledTimes(1);
    expect(result.state.phase).toBe('IDLE');
    act(() => root.unmount());
  });
});

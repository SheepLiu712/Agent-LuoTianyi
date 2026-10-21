import React from 'react';
import { act, create } from 'react-test-renderer';
import { CallScreen } from '../components/call/CallScreen';
import { useCallSession } from '../hooks/useCallSession';
import type { CallState } from '../types/call';
import { THEMES } from '../utils/theme';

import { activateKeepAwakeAsync as activate, deactivateKeepAwake as deactivate } from 'expo-keep-awake';
jest.mock('react-native-safe-area-context', () => ({
  useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }),
}));
jest.mock('react-native', () => ({
  __esModule: true,
  Platform: { OS: 'android' },
  BackHandler: { addEventListener: () => ({ remove: jest.fn() }) },
  AppState: { addEventListener: (_type: string, listener: (state: string) => void) => {
    (globalThis as any).__callKeepAwakeAppState = listener;
    return { remove: () => { (globalThis as any).__callKeepAwakeAppState = undefined; } };
  } },
  Image: 'Image', Pressable: 'Pressable', Text: 'Text', View: 'View',
  StyleSheet: { absoluteFillObject: {}, create: (styles: any) => styles },
}));

const state = (phase: CallState['phase']): CallState => ({
  phase, callId: phase === 'IDLE' ? undefined : 'call-1', endReason: undefined,
  audioCapability: phase === 'IDLE' ? 'unresolved' : 'available', requiresChatSwitch: false,
  activeStartedAtMs: phase === 'ACTIVE' || phase === 'RECONNECTING' ? 0 : undefined,
  activeDurationAtDisconnectMs: undefined, endedActiveDurationMs: undefined,
});

const activateMock = activate as jest.MockedFunction<typeof activate>;
const deactivateMock = deactivate as jest.MockedFunction<typeof deactivate>;

describe('CallScreen keep-awake lifecycle', () => {
  beforeEach(() => {
    jest.useFakeTimers();
    activateMock.mockReset();
    activateMock.mockResolvedValue(undefined);
    deactivateMock.mockClear();
    deactivateMock.mockResolvedValue(undefined);
  });

  afterEach(() => {
    jest.runOnlyPendingTimers();
    jest.useRealTimers();
  });

  it('requests one tagged lock for the production call screen and releases it on terminal state', async () => {
    let resolveActivation!: () => void;
    activateMock.mockImplementation(() => new Promise<void>((resolve) => { resolveActivation = resolve; }));
    let tree!: ReturnType<typeof create>;
    act(() => { tree = create(<CallScreen state={state('PREPARING')} theme={THEMES.dark} onHangup={jest.fn()} onBack={jest.fn()} />); });
    expect(activateMock).toHaveBeenCalledTimes(1);
    const tag = activateMock.mock.calls[0][0];
    expect(tag).not.toBe('ExpoKeepAwakeDefaultTag');

    act(() => { tree.update(<CallScreen state={state('ACTIVE')} theme={THEMES.dark} onHangup={jest.fn()} onBack={jest.fn()} />); });
    expect(activateMock).toHaveBeenCalledTimes(1);
    resolveActivation();
    await act(async () => { await Promise.resolve(); });
    act(() => { tree.update(<CallScreen state={state('ENDED')} theme={THEMES.dark} onHangup={jest.fn()} onBack={jest.fn()} />); });
    expect(deactivateMock).toHaveBeenCalledWith(tag);
    act(() => tree.unmount());
  });

  it('releases a late activation after unmount without touching the other owner', async () => {
    let resolveFirst!: () => void;
    activateMock
      .mockImplementationOnce(() => new Promise<void>((resolve) => { resolveFirst = resolve; }))
      .mockResolvedValueOnce(undefined);
    let first!: ReturnType<typeof create>;
    let second!: ReturnType<typeof create>;
    act(() => {
      first = create(<CallScreen state={state('ACTIVE')} theme={THEMES.dark} onHangup={jest.fn()} onBack={jest.fn()} />);
      second = create(<CallScreen state={state('ACTIVE')} theme={THEMES.dark} onHangup={jest.fn()} onBack={jest.fn()} />);
    });
    expect(activateMock).toHaveBeenCalledTimes(2);
    const firstTag = activateMock.mock.calls[0][0];
    const secondTag = activateMock.mock.calls[1][0];
    expect(firstTag).not.toBe(secondTag);
    act(() => first.unmount());
    resolveFirst();
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(deactivateMock).toHaveBeenCalledWith(firstTag);
    expect(deactivateMock).not.toHaveBeenCalledWith(secondTag);
    act(() => second.unmount());
  });

  it.each(['SWITCH_PREPARING', 'CONNECTING', 'PREPARING', 'RINGING', 'ACTIVE', 'RECONNECTING'] as const)(
    'activates once for %s', (phase) => {
      let tree!: ReturnType<typeof create>;
      act(() => { tree = create(<CallScreen state={state(phase)} theme={THEMES.dark} onHangup={jest.fn()} onBack={jest.fn()} />); });
      expect(activateMock).toHaveBeenCalledTimes(1);
      act(() => tree.unmount());
    },
  );

  it.each(['ENDING', 'ENDED', 'FAILED', 'DECLINED', 'IDLE'] as const)(
    'does not activate for terminal/inactive %s', (phase) => {
      let tree!: ReturnType<typeof create>;
      act(() => { tree = create(<CallScreen state={state(phase)} theme={THEMES.dark} onHangup={jest.fn()} onBack={jest.fn()} />); });
      expect(activateMock).toHaveBeenCalledTimes(0);
      act(() => tree.unmount());
    },
  );

  it('does not release a pending owner on rerender, but releases exactly once after activation', async () => {
    let resolveActivation!: () => void;
    activateMock.mockImplementation(() => new Promise<void>((resolve) => { resolveActivation = resolve; }));
    let tree!: ReturnType<typeof create>;
    act(() => { tree = create(<CallScreen state={state('ACTIVE')} theme={THEMES.dark} onHangup={jest.fn()} onBack={jest.fn()} />); });
    const tag = activateMock.mock.calls[0][0];
    act(() => { tree.update(<CallScreen state={state('RECONNECTING')} theme={THEMES.dark} onHangup={jest.fn()} onBack={jest.fn()} />); });
    expect(deactivateMock).not.toHaveBeenCalled();
    resolveActivation();
    await act(async () => { await Promise.resolve(); });
    act(() => { tree.update(<CallScreen state={state('ENDED')} theme={THEMES.dark} onHangup={jest.fn()} onBack={jest.fn()} />); });
    expect(deactivateMock.mock.calls.filter(([value]) => value === tag)).toHaveLength(1);
    act(() => tree.unmount());
  });

  it('contains activation and release rejection without unhandled cleanup failure', async () => {
    const warn = jest.spyOn(console, 'warn').mockImplementation(() => undefined);
    activateMock.mockRejectedValueOnce(new Error('activate-failed'));
    let tree!: ReturnType<typeof create>;
    act(() => { tree = create(<CallScreen state={state('ACTIVE')} theme={THEMES.dark} onHangup={jest.fn()} onBack={jest.fn()} />); });
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    deactivateMock.mockRejectedValueOnce(new Error('deactivate-failed'));
    act(() => tree.unmount());
    await act(async () => { await Promise.resolve(); });
    expect(warn).toHaveBeenCalled();
    warn.mockRestore();
  });

  it('releases a held tag when deactivation rejects, without touching another owner', async () => {
    const warn = jest.spyOn(console, 'warn').mockImplementation(() => undefined);
    let first!: ReturnType<typeof create>;
    let second!: ReturnType<typeof create>;
    act(() => {
      first = create(<CallScreen state={state('ACTIVE')} theme={THEMES.dark} onHangup={jest.fn()} onBack={jest.fn()} />);
      second = create(<CallScreen state={state('ACTIVE')} theme={THEMES.dark} onHangup={jest.fn()} onBack={jest.fn()} />);
    });
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    const firstTag = activateMock.mock.calls[0][0];
    const secondTag = activateMock.mock.calls[1][0];
    deactivateMock.mockRejectedValueOnce(new Error('deactivate-failed'));
    act(() => first.unmount());
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(deactivateMock).toHaveBeenCalledWith(firstTag);
    expect(deactivateMock).not.toHaveBeenCalledWith(secondTag);
    expect(warn).toHaveBeenCalledWith('Call keep-awake release failed', expect.any(Error));
    act(() => second.unmount());
    warn.mockRestore();
  });

  it('keeps a stable tagged owner through StrictMode effect replay', async () => {
    const StrictMode = React.StrictMode;
    let resolveActivation!: () => void;
    activateMock.mockImplementation(() => new Promise<void>((resolve) => { resolveActivation = resolve; }));
    let tree!: ReturnType<typeof create>;
    act(() => {
      tree = create(<StrictMode><CallScreen state={state('ACTIVE')} theme={THEMES.dark} onHangup={jest.fn()} onBack={jest.fn()} /></StrictMode>);
    });
    expect(activateMock).toHaveBeenCalledTimes(1);
    expect(new Set(activateMock.mock.calls.map(([tag]) => tag)).size).toBe(1);
    resolveActivation();
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    act(() => tree.unmount());
  });

  it('releases through the real useCallSession plus CallScreen background policy', async () => {
    const session = {
      prepare: jest.fn(async () => undefined),
      start: jest.fn(async () => undefined),
      hangup: jest.fn(async () => undefined),
      close: jest.fn(async () => undefined),
      subscribe: jest.fn(() => jest.fn()),
      onError: jest.fn(() => jest.fn()),
    } as any;
    let result: any;
    function Harness() {
      result = useCallSession({
        session,
        capabilities: { serverAvailable: true, nativeAvailable: true },
        requestPermission: async () => 'granted',
      });
      return <CallScreen state={result.state} theme={THEMES.dark} onHangup={result.hangup} onBack={jest.fn()} />;
    }
    let tree!: ReturnType<typeof create>;
    await act(async () => { tree = create(<Harness />); });
    await act(async () => { await result.start(false); });
    act(() => {
      result.dispatch({ type: 'permission_granted' });
      result.dispatch({ type: 'transport_authenticated' });
      result.dispatch({ type: 'call_active', callId: 'call-1', connectedAtMs: 0 });
    });
    expect(result.state.phase).toBe('ACTIVE');
    expect(activateMock).toHaveBeenCalledTimes(1);
    act(() => { (globalThis as any).__callKeepAwakeAppState('background'); });
    expect(session.hangup).toHaveBeenCalledWith('backgrounded');
    expect(result.state.phase).toBe('IDLE');
    expect(deactivateMock).toHaveBeenCalledTimes(1);
    act(() => tree.unmount());
  });

});

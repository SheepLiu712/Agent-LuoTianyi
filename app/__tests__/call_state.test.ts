import { initialCallState, getCallActiveDurationMs, reduceCallState } from '../utils/call_state';
import type { CallEvent, CallTransition } from '../types/call';

function reduce(events: CallEvent[]): CallTransition {
  return events.reduce<CallTransition>((current, event) => reduceCallState(current.state, event), {
    state: initialCallState,
    effects: [],
  });
}

describe('call lifecycle state skeleton', () => {
  it('does not start a real-time call before audio capability is confirmed', () => {
    expect(
      reduceCallState(initialCallState, {
        type: 'request_call',
        requiresChatSwitch: true,
        clientRequestId: 'request-1',
      }),
    ).toEqual({ state: initialCallState, effects: [] });
  });

  it('waits for switch_ready before closing chat or opening the call transport', () => {
    const permission = reduce([
      { type: 'audio_capability', capability: 'available' },
      { type: 'request_call', requiresChatSwitch: true, clientRequestId: 'request-1' },
      { type: 'permission_granted' },
    ]);
    expect(permission.state.phase).toBe('SWITCH_PREPARING');
    expect(permission.effects).toEqual([{ type: 'prepare_switch', clientRequestId: 'request-1' }]);

    const ready = reduceCallState(permission.state, { type: 'switch_ready' });
    expect(ready.effects).toEqual([{ type: 'close_chat' }, { type: 'open_call' }]);
  });

  it('returns to chat on permission denial without creating a call', () => {
    const requested = reduce([
      { type: 'audio_capability', capability: 'available' },
      { type: 'request_call', requiresChatSwitch: false, clientRequestId: 'request-1' },
    ]);
    expect(reduceCallState(requested.state, { type: 'permission_permanently_denied' })).toMatchObject({
      state: { phase: 'IDLE' },
      effects: [{ type: 'return_to_chat' }],
    });
  });

  it('starts timing at ACTIVE and excludes a reconnect that does not recover', () => {
    const active = reduce([
      { type: 'audio_capability', capability: 'available' },
      { type: 'request_call', requiresChatSwitch: false, clientRequestId: 'request-1' },
      { type: 'permission_granted' },
      { type: 'transport_authenticated' },
      { type: 'call_active', callId: 'call-1', connectedAtMs: 100 },
    ]).state;
    const reconnecting = reduceCallState(active, { type: 'transport_lost', nowMs: 1_100 }).state;
    expect(getCallActiveDurationMs(reconnecting, 2_000)).toBe(1_900);
    expect(reduceCallState(reconnecting, { type: 'recovery_timeout' }).state.endedActiveDurationMs).toBe(1_000);
  });

  it('keeps a recovered fluctuation within the same displayed duration', () => {
    const active = {
      ...initialCallState,
      phase: 'ACTIVE' as const,
      audioCapability: 'available' as const,
      callId: 'call-1',
      activeStartedAtMs: 100,
    };
    const reconnecting = reduceCallState(active, { type: 'transport_lost', nowMs: 1_100 }).state;
    const resumed = reduceCallState(reconnecting, { type: 'transport_resumed', nowMs: 2_100 }).state;
    expect(getCallActiveDurationMs(resumed, 3_100)).toBe(3_000);
  });

  it('uses the same client request identity for prepare and start', () => {
    const requested = reduce([
      { type: 'audio_capability', capability: 'available' },
      { type: 'request_call', requiresChatSwitch: true, clientRequestId: 'request-1' },
      { type: 'permission_granted' },
    ]);
    expect(requested.state.clientRequestId).toBe('request-1');
    expect(requested.effects).toEqual([{ type: 'prepare_switch', clientRequestId: 'request-1' }]);

    const ready = reduceCallState(requested.state, { type: 'switch_ready' });
    const authenticated = reduceCallState(ready.state, { type: 'transport_authenticated' });
    expect(authenticated.effects).toEqual([{ type: 'start', clientRequestId: 'request-1' }]);
  });

  it('shows confirmation for back, but backgrounding ends once and stops audio', () => {
    const active = { ...initialCallState, phase: 'ACTIVE' as const, activeStartedAtMs: 100 };
    expect(reduceCallState(active, { type: 'back_requested' }).effects).toEqual([{ type: 'show_back_confirmation' }]);
    const ending = reduceCallState(active, { type: 'app_backgrounded', nowMs: 200 });
    expect(ending.effects).toEqual([
      { type: 'stop_capture' },
      { type: 'stop_playback' },
      { type: 'return_to_chat' },
    ]);
    expect(reduceCallState(ending.state, { type: 'user_hangup', nowMs: 300 }).effects).toEqual([]);
  });
});

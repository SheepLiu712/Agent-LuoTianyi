import { initialCallState, reduceCallState } from '../utils/call_state';

describe('call failure lifecycle classification', () => {
  it('retains a safe internal code for a failed establishment and returns once', () => {
    const state = { ...initialCallState, phase: 'PREPARING' as const, callId: 'call-1' };
    const transition = reduceCallState(state, { type: 'call_ended', nowMs: 100, errorCode: 'CALL_CONNECTION_LOST' });
    expect(transition.state).toMatchObject({ phase: 'FAILED', endReason: 'failed', failureCode: 'CALL_CONNECTION_LOST' });
    expect(transition.effects).toEqual([
      { type: 'stop_capture' }, { type: 'stop_playback' }, { type: 'return_to_chat' },
    ]);
  });

  it('does not classify intentional hangup as a failure', () => {
    const state = { ...initialCallState, phase: 'CONNECTING' as const };
    const transition = reduceCallState(state, { type: 'user_hangup', nowMs: 100 });
    expect(transition.state.endReason).toBe('user_hangup');
    expect(transition.state.failureCode).toBeUndefined();
  });
});

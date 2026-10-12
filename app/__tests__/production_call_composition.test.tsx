import React, { StrictMode } from 'react';
import { act, create, ReactTestRenderer } from 'react-test-renderer';

import { useProductionCallComposition } from '../hooks/useProductionCallComposition';
import { ProductionCallResolver } from '../utils/call_session/production_resolver';

jest.mock('../utils/call_session/production_resolver', () => ({
  ProductionCallResolver: jest.fn(),
}));

type Composition = ReturnType<typeof useProductionCallComposition>;

function Harness(props: { username: string; token: string; onValue(value: Composition): void }) {
  const value = useProductionCallComposition({
    username: props.username,
    token: props.token,
    characterId: 'current-character',
    switchPort: { prepare: jest.fn() },
    onAuthRequired: jest.fn(),
    onError: jest.fn(),
  });
  props.onValue(value);
  return null;
}

describe('production call composition lifecycle', () => {
  let resolvers: any[];

  beforeEach(() => {
    resolvers = [];
    (ProductionCallResolver as jest.Mock).mockImplementation((options) => {
      let resolveProbe!: () => void;
      const resolver = {
        options,
        refreshCapability: jest.fn(() => new Promise<void>((resolve) => { resolveProbe = resolve; })),
        resolveProbe: () => resolveProbe(),
        currentCapabilities: jest.fn(() => ({ serverAvailable: true, nativeAvailable: true })),
        technicalNativeAvailable: jest.fn(() => true),
        createAttempt: jest.fn(() => ({ session: { owner: options.credentials.username } })),
        initializeSession: jest.fn(async () => true),
        close: jest.fn(async () => undefined),
      };
      resolvers.push(resolver);
      return resolver;
    });
  });

  it('uses a fresh credential-owned resolver and ignores a stale probe', async () => {
    let composition!: Composition;
    let root!: ReactTestRenderer;
    await act(async () => {
      root = create(<Harness username="alice" token="token-a" onValue={(value) => { composition = value; }} />);
    });
    const first = resolvers[0];
    await act(async () => {
      root.update(<Harness username="bob" token="token-b" onValue={(value) => { composition = value; }} />);
    });
    const second = resolvers[1];
    expect(first.close).toHaveBeenCalledTimes(1);
    expect(second.options.credentials).toEqual({ username: 'bob', token: 'token-b' });

    await act(async () => { first.resolveProbe(); await Promise.resolve(); });
    expect(composition.capabilities.serverAvailable).toBe(false);
    await act(async () => { second.resolveProbe(); await Promise.resolve(); });
    expect(composition.capabilities.serverAvailable).toBe(true);
    expect(composition.createSession()).toEqual({ owner: 'bob' });
    await act(async () => root.unmount());
    expect(second.close).toHaveBeenCalledTimes(1);
  });

  it('survives StrictMode setup-cleanup-setup with a callable fresh resolver', async () => {
    let composition!: Composition;
    let root!: ReactTestRenderer;
    await act(async () => {
      root = create(<StrictMode><Harness username="alice" token="token" onValue={(value) => { composition = value; }} /></StrictMode>);
    });
    expect(resolvers.length).toBeGreaterThanOrEqual(2);
    const current = resolvers.at(-1);
    await act(async () => { current.resolveProbe(); await Promise.resolve(); });
    expect(composition.createSession()).toEqual({ owner: 'alice' });
    expect(resolvers.slice(0, -1).every((resolver) => resolver.close.mock.calls.length === 1)).toBe(true);
    await act(async () => root.unmount());
    expect(current.close).toHaveBeenCalledTimes(1);
  });
});

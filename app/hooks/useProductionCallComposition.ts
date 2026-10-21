import { useCallback, useEffect, useRef, useState } from 'react';

import type { CallCapabilities, CallSwitchPort } from '../types/call_transport';
import type { CallSession } from '../utils/call_session/call_session';
import { ProductionCallResolver } from '../utils/call_session/production_resolver';
import type { CallMouthBridge } from '../utils/call_audio/playback_progress';

const unavailable: CallCapabilities = { serverAvailable: false, nativeAvailable: false };

export function useProductionCallComposition(options: {
  username: string;
  token: string;
  characterId: string;
  switchPort: CallSwitchPort;
  onAuthRequired(): void;
  onError(error: unknown): void;
  mouthBridge?: CallMouthBridge;
}) {
  const [capabilities, setCapabilities] = useState<CallCapabilities>(unavailable);
  const resolverRef = useRef<ProductionCallResolver | null>(null);
  const generationRef = useRef(0);
  const switchPortRef = useRef(options.switchPort);
  const onAuthRequiredRef = useRef(options.onAuthRequired);
  const onErrorRef = useRef(options.onError);
  switchPortRef.current = options.switchPort;
  onAuthRequiredRef.current = options.onAuthRequired;
  onErrorRef.current = options.onError;

  useEffect(() => {
    const generation = ++generationRef.current;
    const resolver = new ProductionCallResolver({
      characterId: options.characterId,
      credentials: { username: options.username, token: options.token },
      switchPort: {
        prepare: (clientRequestId, characterId) => switchPortRef.current.prepare(clientRequestId, characterId),
      },
      mouthBridge: options.mouthBridge,
    });
    resolverRef.current = resolver;
    setCapabilities(unavailable);
    void resolver.refreshCapability().then(() => {
      if (generation === generationRef.current && resolverRef.current === resolver) {
        setCapabilities(resolver.currentCapabilities());
      }
    }).catch((error) => {
      if (generation !== generationRef.current || resolverRef.current !== resolver) return;
      setCapabilities({ serverAvailable: false, nativeAvailable: resolver.technicalNativeAvailable() });
      if (error instanceof Error && error.message === 'CALL_AUTH_REQUIRED') onAuthRequiredRef.current();
      else onErrorRef.current(error);
    });
    return () => {
      if (resolverRef.current === resolver) resolverRef.current = null;
      generationRef.current += 1;
      void resolver.close();
    };
  }, [options.characterId, options.mouthBridge, options.token, options.username]);

  const createSession = useCallback(() => {
    const resolver = resolverRef.current;
    if (!resolver) throw new Error('CALL_RESOLVER_UNAVAILABLE');
    return resolver.createAttempt().session;
  }, []);

  const initializeSession = useCallback(async (session: CallSession) => {
    return resolverRef.current?.initializeSession(session) ?? false;
  }, []);

  const closeCurrent = useCallback(async () => {
    const resolver = resolverRef.current;
    if (!resolver) return;
    resolverRef.current = null;
    generationRef.current += 1;
    await resolver.close();
  }, []);

  return { capabilities, createSession, initializeSession, closeCurrent };
}

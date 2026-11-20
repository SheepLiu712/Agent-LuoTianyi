import { useMemo } from 'react';
import { Linking } from 'react-native';
import { useCallSession, type CallSessionOptions } from './useCallSession';
import { useProductionCallComposition } from './useProductionCallComposition';
import { requestCallMicrophonePermission } from './call_session/production_resolver';
import { NativeCallRingtone } from './call_session/ringtone';
import { addDebugTrace } from '../../utils/debug_trace';

type CallFeatureOptions = Omit<Parameters<typeof useProductionCallComposition>[0], 'onError'>
  & Pick<CallSessionOptions, 'onReturnToChat' | 'onCallRecord' | 'onBackConfirmation'>;

export function useCallFeature(options: CallFeatureOptions) {
  const ringtone = useMemo(() => new NativeCallRingtone(), []);
  const composition = useProductionCallComposition({
    ...options,
    onError: (error) => addDebugTrace('call', 'capability probe failed', { error: String(error) }),
  });
  const call = useCallSession({
    capabilities: composition.capabilities,
    createAttempt: composition.createAttempt,
    ringtone,
    requestPermission: requestCallMicrophonePermission,
    onReturnToChat: options.onReturnToChat,
    onCallRecord: options.onCallRecord,
    onBackConfirmation: options.onBackConfirmation,
    onPermissionSettings: () => { void Linking.openSettings(); },
    onCleanupError: (error) => addDebugTrace('call', 'call resource cleanup failed', { error: String(error) }),
  });
  return { ...call, close: composition.closeCurrent };
}

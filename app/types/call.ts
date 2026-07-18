export type CallStatus = 'idle' | 'connecting' | 'requesting' | 'active' | 'reconnecting' | 'ending' | 'ended';

export interface CallEventEnvelope {
  type?: string;
  payload?: Record<string, unknown>;
  reply_to?: string;
}

export interface CallCallbacks {
  onEvent: (type: string, payload: Record<string, unknown>) => void;
  onStatus: (status: CallStatus) => void;
  onError: (message: string) => void;
  onConnectedAt?: (timestamp: string) => void;
}

export interface CallAckResult {
  ok: boolean;
  request_id: string;
  code?: string;
  message?: string;
  error?: string;
}

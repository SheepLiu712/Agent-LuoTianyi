export interface AckResult {
  ok: boolean;
  request_id: string;
  error?: string;
  drop?: boolean;
  code?: string;
  retryable?: boolean;
  message_uuid?: string;
  duration_ms?: number;
}

export function normalizeServerAck(payload: Record<string, unknown>, requestId: string): AckResult {
  // Older servers did not send `ok`; preserve their positive-ACK behavior.
  if (payload.ok !== false) {
    return {
      ok: true,
      request_id: requestId,
      ...(typeof payload.message_uuid === 'string' ? { message_uuid: payload.message_uuid } : {}),
      ...(typeof payload.duration_ms === 'number' ? { duration_ms: payload.duration_ms } : {}),
    };
  }

  const code = typeof payload.code === 'string' ? payload.code : 'REJECTED';
  const retryable = payload.retryable === true;
  const message = typeof payload.message === 'string' ? payload.message : code;
  return {
    ok: false,
    request_id: requestId,
    error: `[${code}] ${message}`,
    code,
    retryable,
    drop: !retryable,
    ...(typeof payload.message_uuid === 'string' ? { message_uuid: payload.message_uuid } : {}),
    ...(typeof payload.duration_ms === 'number' ? { duration_ms: payload.duration_ms } : {}),
  };
}

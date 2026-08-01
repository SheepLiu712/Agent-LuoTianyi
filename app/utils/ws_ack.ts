export interface AckResult {
  ok: boolean;
  request_id: string;
  error?: string;
  drop?: boolean;
  code?: string;
  retryable?: boolean;
}

export function normalizeServerAck(payload: Record<string, unknown>, requestId: string): AckResult {
  // Older servers did not send `ok`; preserve their positive-ACK behavior.
  if (payload.ok !== false) {
    return { ok: true, request_id: requestId };
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
  };
}

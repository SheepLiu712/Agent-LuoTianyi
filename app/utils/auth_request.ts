import { server_config } from '../config';

export async function authFetch(url: string, init: RequestInit = {}): Promise<Response> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), server_config.API_TIMEOUT);
  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } finally {
    clearTimeout(timeout);
  }
}

export function isUnknownRegistrationResult(status?: number): boolean {
  return status === undefined || status === 408 || status === 429 || status >= 500;
}

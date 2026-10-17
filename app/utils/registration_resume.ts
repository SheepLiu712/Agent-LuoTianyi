import AsyncStorage from '@react-native-async-storage/async-storage';

export type RegistrationAttemptState = 'never_sent' | 'unknown' | 'same_user_login';

export interface RegistrationResumeRecord {
  server: string;
  requestId: string;
  username: string;
  agreementVersion: string;
  state: RegistrationAttemptState;
  createdAt: number;
}

const PREFIX = 'registration_resume:v1:';

export function normalizeRegistrationServer(url: string): string {
  return url.trim().replace(/\/+$/, '').toLowerCase();
}

function key(server: string): string {
  return `${PREFIX}${encodeURIComponent(normalizeRegistrationServer(server))}`;
}

export function isRecoverable(record: RegistrationResumeRecord | null): boolean {
  return Boolean(record);
}

export function isUnknown(record: RegistrationResumeRecord | null): boolean {
  return record?.state === 'unknown';
}

export function isSameRegistrationIdentity(
  record: RegistrationResumeRecord | null,
  server: string,
  requestId: string,
  username: string,
): boolean {
  return Boolean(
    record && record.server === normalizeRegistrationServer(server) &&
      record.requestId === requestId && record.username === username,
  );
}

export async function loadRegistrationResume(server: string): Promise<RegistrationResumeRecord | null> {
  const raw = await AsyncStorage.getItem(key(server));
  if (!raw) return null;
  try {
    const value = JSON.parse(raw) as Partial<RegistrationResumeRecord>;
    if (
      value.server !== normalizeRegistrationServer(server) ||
      typeof value.requestId !== 'string' || !value.requestId ||
      typeof value.username !== 'string' ||
      typeof value.agreementVersion !== 'string' ||
      !['never_sent', 'unknown', 'same_user_login'].includes(value.state || '')
    ) return null;
    return value as RegistrationResumeRecord;
  } catch {
    return null;
  }
}

export async function saveRegistrationResume(record: Omit<RegistrationResumeRecord, 'server' | 'createdAt'> & { server: string; createdAt?: number }): Promise<RegistrationResumeRecord> {
  const normalized: RegistrationResumeRecord = {
    ...record,
    server: normalizeRegistrationServer(record.server),
    createdAt: record.createdAt ?? Date.now(),
  };
  await AsyncStorage.setItem(key(normalized.server), JSON.stringify(normalized));
  return normalized;
}

export async function markRegistrationUnknown(server: string, requestId: string, username: string, agreementVersion: string) {
  return saveRegistrationResume({ server, requestId, username, agreementVersion, state: 'unknown' });
}

export async function markRegistrationSameUserLogin(server: string, requestId: string, username: string, agreementVersion: string) {
  return saveRegistrationResume({ server, requestId, username, agreementVersion, state: 'same_user_login' });
}

export async function clearRegistrationResume(server: string): Promise<void> {
  await AsyncStorage.removeItem(key(server));
}

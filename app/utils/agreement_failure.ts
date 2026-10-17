export type AgreementSubmitFailure = 'credential_invalid' | 'version_changed' | 'retryable';

export function classifyAgreementSubmitFailure(status: number, code?: string): AgreementSubmitFailure {
  if (status === 401) return 'credential_invalid';
  if (status === 409 && code === 'AGREEMENT_CHANGED') return 'version_changed';
  return 'retryable';
}

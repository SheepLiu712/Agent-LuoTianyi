import { AgreementPayload } from './agreement';

export interface AgreementReaderState {
  elapsed: number;
  reachedBottom: boolean;
  submitting: boolean;
}

export function agreementReady(state: AgreementReaderState, shortDocument: boolean): boolean {
  return state.elapsed >= 5 && (state.reachedBottom || shortDocument) && !state.submitting;
}

export function resetAgreementReader(): AgreementReaderState {
  return { elapsed: 0, reachedBottom: false, submitting: false };
}

export function agreementAfterVersionChange(_agreement: AgreementPayload): AgreementReaderState {
  return resetAgreementReader();
}

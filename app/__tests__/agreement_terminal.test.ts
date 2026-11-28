import { classifyAgreementSubmitFailure } from '../utils/agreement_failure';

describe('老用户协议终态契约', () => {
  it('401 是凭据失效终态；429 和网络失败保留阅读状态重试', () => {
    expect(classifyAgreementSubmitFailure(401)).toBe('credential_invalid');
    expect(classifyAgreementSubmitFailure(429)).toBe('retryable');
    expect(classifyAgreementSubmitFailure(0)).toBe('retryable');
  });

  it('只有协议版本变更触发重读', () => {
    expect(classifyAgreementSubmitFailure(409, 'AGREEMENT_CHANGED')).toBe('version_changed');
    expect(classifyAgreementSubmitFailure(409, 'OTHER')).toBe('retryable');
  });
});

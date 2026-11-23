import { agreementAfterVersionChange, agreementReady, resetAgreementReader } from '../utils/agreement_flow';

describe('协议阅读状态', () => {
  it('五秒和到底均满足才可提交，短文可视为到底', () => {
    expect(agreementReady({ elapsed: 4.99, reachedBottom: true, submitting: false }, false)).toBe(false);
    expect(agreementReady({ elapsed: 5, reachedBottom: false, submitting: false }, false)).toBe(false);
    expect(agreementReady({ elapsed: 5, reachedBottom: false, submitting: false }, true)).toBe(true);
  });

  it('提交中不可重复，换版与重开清除状态', () => {
    expect(agreementReady({ elapsed: 5, reachedBottom: true, submitting: true }, false)).toBe(false);
    expect(resetAgreementReader()).toEqual({ elapsed: 0, reachedBottom: false, submitting: false });
    expect(agreementAfterVersionChange({} as any)).toEqual(resetAgreementReader());
  });
});

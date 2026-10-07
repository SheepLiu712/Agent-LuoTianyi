import {
  validateClientModelRequirements,
  validateJsonResponse,
} from '../utils/llm_requirements';

const base = {
  requiredKind: 'llm',
  configuredKind: 'llm',
  requiresJson: false,
  requiresThinking: false,
  canUseJson: false,
  canEnableThinking: false,
};

describe('client model runtime requirements', () => {
  it('accepts a matching model', () => {
    expect(validateClientModelRequirements(base)).toBeNull();
  });

  it('reports model kind mismatch', () => {
    expect(
      validateClientModelRequirements({ ...base, requiredKind: 'vlm' }),
    ).toContain('VLM');
  });

  it('reports missing json and thinking capabilities', () => {
    expect(
      validateClientModelRequirements({ ...base, requiresJson: true }),
    ).toContain('JSON');
    expect(
      validateClientModelRequirements({ ...base, requiresThinking: true }),
    ).toContain('thinking');
  });

  it('reports invalid json returned by a model that claimed support', () => {
    expect(validateJsonResponse('{"ok": true}', true)).toBeNull();
    expect(validateJsonResponse('not-json', true)).toContain('有效 JSON');
    expect(validateJsonResponse('not-json', false)).toBeNull();
  });
});

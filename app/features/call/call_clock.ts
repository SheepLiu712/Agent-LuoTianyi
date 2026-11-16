/**
 * Clock used by every call duration consumer.
 *
 * Call anchors and subsequent samples must share one time domain. `Date.now`
 * is only the fallback because some React Native runtimes do not expose the
 * Performance API; all call consumers use this same fallback decision.
 */
export function callMonotonicNowMs(): number {
  return globalThis.performance?.now?.() ?? Date.now();
}

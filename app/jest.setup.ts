// Jest setup: define React Native globals
(globalThis as any).__DEV__ = false;
(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;
(globalThis as any).requestAnimationFrame = (cb: FrameRequestCallback) =>
  setTimeout(cb, 0);

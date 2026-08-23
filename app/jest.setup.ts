// Jest setup: define React Native globals
(globalThis as any).__DEV__ = false;
(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;
(globalThis as any).requestAnimationFrame = (cb: FrameRequestCallback) =>
  setTimeout(cb, 0);

// 全局 mock expo-secure-store（原生模块为 ESM，Jest 无法直接解析）。
// 测试文件内的 jest.mock 优先级更高，会覆盖此默认实现（如 llm_settings.test.tsx）。
jest.mock('expo-secure-store', () => ({
  getItemAsync: jest.fn(async () => null),
  setItemAsync: jest.fn(async () => {}),
  deleteItemAsync: jest.fn(async () => {}),
}));

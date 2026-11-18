import React from 'react';
import { act, create, ReactTestRenderer } from 'react-test-renderer';
import RootLayout from '../app/_layout';
import LoginScreen from '../app/login';

const register = jest.fn().mockResolvedValue({ success: true });
jest.mock('../hooks/useAuth', () => ({
  useAuth: () => ({ isLoggedIn: false, isLoading: false, register }),
}));
jest.mock('../app/index', () => ({ __esModule: true, default: () => null }));
jest.mock('../app/login', () => ({ __esModule: true, default: () => null }));
jest.mock('react-native-safe-area-context', () => ({
  SafeAreaProvider: ({ children }: React.PropsWithChildren) => children,
}));
jest.mock('react-native', () => ({
  ActivityIndicator: 'ActivityIndicator', View: 'View', StyleSheet: { create: (value: unknown) => value },
}));

it('注册入口保留本次请求身份和用户阅读的协议版本', async () => {
  let tree!: ReactTestRenderer;
  act(() => { tree = create(<RootLayout />); });
  await act(async () => {
    await tree.root.findByType(LoginScreen).props.onRegister(
      'user', 'pass', 'pass', 'invite', 'app-request-123', 'terms-v3',
    );
  });
  expect(register).toHaveBeenCalledWith('user', 'pass', 'pass', 'invite', 'app-request-123', 'terms-v3');
  act(() => tree.unmount());
});

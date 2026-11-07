import { createElement } from 'react';
import { act, create, type ReactTestRenderer } from 'react-test-renderer';
import { Linking } from 'react-native';
import { useMicrophonePermission } from '../hooks/useMicrophonePermission';
import type { VoiceRecorderApi } from '../utils/voice_recorder';

jest.mock('react-native', () => ({
  AppState: { currentState: 'active' },
  Linking: { openSettings: jest.fn() },
}));

const recorder: VoiceRecorderApi = {
  getPermission: jest.fn(), requestPermission: jest.fn(), start: jest.fn(), stop: jest.fn(),
  cancel: jest.fn(), dispose: jest.fn(),
};
let tree: ReactTestRenderer;
let permission: ReturnType<typeof useMicrophonePermission>;

function PermissionHarness() {
  permission = useMicrophonePermission(recorder);
  return null;
}

beforeEach(async () => {
  jest.resetAllMocks();
  (recorder.getPermission as jest.Mock).mockResolvedValue('denied');
  (recorder.requestPermission as jest.Mock).mockResolvedValue('blocked');
  await act(async () => { tree = create(createElement(PermissionHarness)); });
});
afterEach(async () => { await act(async () => { tree.unmount(); }); });

async function showSettingsChoice() {
  await act(async () => { await permission.checkPermission(); });
  await act(async () => { await permission.checkPermission(); });
  const choice = permission.permissionNotice;
  if (!choice?.settings) throw new Error('重试后应展示去设置选择框');
  expect(Linking.openSettings).not.toHaveBeenCalled();
  return choice;
}

it('取消后不打开设置，过期的选择也不能再次打开设置', async () => {
  const choice = await showSettingsChoice();
  await act(async () => { permission.dismissPermissionNotice(choice); });
  expect(permission.permissionNotice).toBeNull();
  await act(async () => { await permission.openPermissionSettings(choice); });
  expect(Linking.openSettings).not.toHaveBeenCalled();
});

it.each(['成功', '失败'])('用户选择“去设置”，系统设置打开%s', async (result) => {
  const choice = await showSettingsChoice();
  const openSettings = Linking.openSettings as jest.Mock;
  if (result === '成功') openSettings.mockResolvedValue(undefined);
  else openSettings.mockRejectedValue(new Error('unavailable'));
  await act(async () => { await permission.openPermissionSettings(choice); });
  expect(openSettings).toHaveBeenCalledTimes(1);
  if (result === '成功') expect(permission.permissionNotice).toBeNull();
  else expect(permission.permissionNotice).toMatchObject({
    message: '无法打开系统设置，请手动前往系统设置，为本应用开启麦克风权限。', settings: false,
  });
});

it('离开原界面后，打开设置失败不会补弹提示', async () => {
  const choice = await showSettingsChoice();
  let fail!: (reason: Error) => void;
  (Linking.openSettings as jest.Mock).mockReturnValue(new Promise((_resolve, reject) => { fail = reject; }));
  let opening!: Promise<void>;
  await act(async () => { opening = permission.openPermissionSettings(choice); });
  expect(permission.permissionNotice).toBeNull();
  await act(async () => { permission.leavePermissionPage(); });
  await act(async () => { fail(new Error('unavailable')); await opening; });
  expect(permission.permissionNotice).toBeNull();
});

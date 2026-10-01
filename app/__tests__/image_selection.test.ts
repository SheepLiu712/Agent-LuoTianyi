import type { ImagePickerResult, MediaLibraryPermissionResponse } from 'expo-image-picker';
import type { PermissionStatus } from 'expo-modules-core';
import {
  IMAGE_PICKER_ERROR_MESSAGE,
  IMAGE_PICKER_PERMISSION_DENIED_MESSAGE,
  runImageSelection,
} from '../utils/image_selection';

const canceledResult: ImagePickerResult = { canceled: true, assets: null };

function grantedPermission(): MediaLibraryPermissionResponse {
  return {
    status: 'granted' as PermissionStatus,
    granted: true,
    expires: 'never',
    canAskAgain: true,
    accessPrivileges: 'all',
  };
}

describe('runImageSelection', () => {
  it('shows a visible error and resets selection state when Android permission is denied', async () => {
    const emitError = jest.fn();
    const cancelSelecting = jest.fn(async () => undefined);

    await expect(
      runImageSelection({
        isAndroid: true,
        sendSelecting: jest.fn(async () => undefined),
        cancelSelecting,
        launchPicker: jest.fn(async () => {
          throw new Error('permission failure');
        }),
        requestMediaLibraryPermission: jest.fn(async (): Promise<MediaLibraryPermissionResponse> => ({
          ...grantedPermission(),
          status: 'denied' as PermissionStatus,
          granted: false,
          canAskAgain: false,
          accessPrivileges: 'none',
        })),
        onSelected: jest.fn(async () => undefined),
        emitError,
      }),
    ).resolves.toBeUndefined();

    expect(emitError).toHaveBeenCalledWith(IMAGE_PICKER_PERMISSION_DENIED_MESSAGE);
    expect(cancelSelecting).toHaveBeenCalledTimes(1);
  });

  it('requests permission only after an Android launch failure and retries once', async () => {
    const launchPicker = jest
      .fn<Promise<ImagePickerResult>, []>()
      .mockRejectedValueOnce(new Error('picker unavailable'))
      .mockResolvedValueOnce(canceledResult);
    const requestMediaLibraryPermission = jest.fn(async () => grantedPermission());
    const cancelSelecting = jest.fn(async () => undefined);

    await runImageSelection({
      isAndroid: true,
      sendSelecting: jest.fn(async () => undefined),
      cancelSelecting,
      launchPicker,
      requestMediaLibraryPermission,
      onSelected: jest.fn(async () => undefined),
      emitError: jest.fn(),
    });

    expect(launchPicker).toHaveBeenCalledTimes(2);
    expect(requestMediaLibraryPermission).toHaveBeenCalledTimes(1);
    expect(cancelSelecting).toHaveBeenCalledTimes(1);
  });

  it('does not request permission before a successful picker launch', async () => {
    const requestMediaLibraryPermission = jest.fn(async () => grantedPermission());

    await runImageSelection({
      isAndroid: true,
      sendSelecting: jest.fn(async () => undefined),
      cancelSelecting: jest.fn(async () => undefined),
      launchPicker: jest.fn(async () => canceledResult),
      requestMediaLibraryPermission,
      onSelected: jest.fn(async () => undefined),
      emitError: jest.fn(),
    });

    expect(requestMediaLibraryPermission).not.toHaveBeenCalled();
  });

  it('catches non-Android picker errors without an unhandled rejection', async () => {
    const emitError = jest.fn();

    await expect(
      runImageSelection({
        isAndroid: false,
        sendSelecting: jest.fn(async () => undefined),
        cancelSelecting: jest.fn(async () => undefined),
        launchPicker: jest.fn(async () => {
          throw new Error('native picker failure');
        }),
        requestMediaLibraryPermission: jest.fn(async () => grantedPermission()),
        onSelected: jest.fn(async () => undefined),
        emitError,
      }),
    ).resolves.toBeUndefined();

    expect(emitError).toHaveBeenCalledWith(IMAGE_PICKER_ERROR_MESSAGE);
  });
});

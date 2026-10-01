import type { ImagePickerAsset, ImagePickerResult, MediaLibraryPermissionResponse } from 'expo-image-picker';

export const IMAGE_PICKER_ERROR_MESSAGE =
  '无法打开图片选择器，请重试；若被系统拦截，请在设置中授予相册权限';
export const IMAGE_PICKER_PERMISSION_DENIED_MESSAGE = '相册权限未授予，请在系统设置中允许访问照片后重试';

interface ImageSelectionOptions {
  isAndroid: boolean;
  sendSelecting: () => Promise<void>;
  cancelSelecting: () => Promise<void>;
  launchPicker: () => Promise<ImagePickerResult>;
  requestMediaLibraryPermission: () => Promise<MediaLibraryPermissionResponse>;
  onSelected: (asset: ImagePickerAsset) => Promise<void>;
  emitError: (message: string) => void;
  logError?: (error: unknown) => void;
}

class MediaLibraryPermissionDeniedError extends Error {}

async function launchPickerWithPermissionFallback(
  options: Pick<
    ImageSelectionOptions,
    'isAndroid' | 'launchPicker' | 'requestMediaLibraryPermission'
  >,
): Promise<ImagePickerResult> {
  try {
    return await options.launchPicker();
  } catch (error) {
    if (!options.isAndroid) {
      throw error;
    }

    const permission = await options.requestMediaLibraryPermission();
    if (!permission.granted) {
      throw new MediaLibraryPermissionDeniedError();
    }

    return await options.launchPicker();
  }
}

export async function runImageSelection(options: ImageSelectionOptions): Promise<void> {
  try {
    await options.sendSelecting();
    const result = await launchPickerWithPermissionFallback(options);

    if (result.canceled || !result.assets || result.assets.length === 0) {
      await options.cancelSelecting();
      return;
    }

    await options.onSelected(result.assets[0]);
  } catch (error) {
    options.logError?.(error);
    options.emitError(
      error instanceof MediaLibraryPermissionDeniedError
        ? IMAGE_PICKER_PERMISSION_DENIED_MESSAGE
        : IMAGE_PICKER_ERROR_MESSAGE,
    );

    try {
      await options.cancelSelecting();
    } catch (cancelError) {
      options.logError?.(cancelError);
    }
  }
}

import type { ImagePickerAsset, ImagePickerResult } from 'expo-image-picker';
import { addDebugTrace } from './debug_trace';

export const IMAGE_PICKER_ERROR_MESSAGE = '无法打开图片选择器，请重试；可在调试日志中查看详情';
export const IMAGE_SELECTION_ERROR_MESSAGE = '图片选择或发送失败，请重试；可在调试日志中查看详情';
export const IMAGE_SELECTION_RESET_ERROR_MESSAGE = '选图状态复位失败，请重试；可在调试日志中查看详情';

interface ImageSelectionOptions {
  sendSelecting: () => Promise<void>;
  cancelSelecting: () => Promise<void>;
  launchPicker: () => Promise<ImagePickerResult>;
  onSelected: (asset: ImagePickerAsset) => Promise<void>;
  emitError: (message: string) => void;
}

type SelectionStage = 'notify_selecting' | 'launch_picker' | 'send_selected' | 'cancel_selecting';

function logSelectionError(stage: SelectionStage, error: unknown) {
  const detail = error !== null && typeof error === 'object' ? error : undefined;
  addDebugTrace('image-selection', 'failed', {
    stage,
    name: detail && 'name' in detail ? String(detail.name) : undefined,
    code: detail && 'code' in detail ? String(detail.code) : undefined,
    message: detail && 'message' in detail ? String(detail.message) : String(error),
    stack: detail && 'stack' in detail ? String(detail.stack) : undefined,
  });
}

async function cancelSelection(options: ImageSelectionOptions) {
  try {
    await options.cancelSelecting();
    addDebugTrace('image-selection', 'reset completed');
  } catch (error) {
    logSelectionError('cancel_selecting', error);
    options.emitError(IMAGE_SELECTION_RESET_ERROR_MESSAGE);
  }
}

export async function runImageSelection(options: ImageSelectionOptions): Promise<void> {
  let stage: SelectionStage = 'notify_selecting';
  addDebugTrace('image-selection', 'started');
  try {
    await options.sendSelecting();
    stage = 'launch_picker';
    addDebugTrace('image-selection', 'launching picker');
    const result = await options.launchPicker();

    if (result.canceled || !result.assets || result.assets.length === 0) {
      addDebugTrace('image-selection', 'canceled');
      await cancelSelection(options);
      return;
    }

    stage = 'send_selected';
    addDebugTrace('image-selection', 'asset selected');
    await options.onSelected(result.assets[0]);
    addDebugTrace('image-selection', 'selection handed to sender');
  } catch (error) {
    logSelectionError(stage, error);
    options.emitError(stage === 'launch_picker' ? IMAGE_PICKER_ERROR_MESSAGE : IMAGE_SELECTION_ERROR_MESSAGE);
    await cancelSelection(options);
  }
}

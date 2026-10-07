import type { ImagePickerAsset, ImagePickerResult } from 'expo-image-picker';
import { clearDebugTrace, getDebugTraceSnapshot } from '../utils/debug_trace';
import {
  IMAGE_PICKER_ERROR_MESSAGE,
  IMAGE_SELECTION_ERROR_MESSAGE,
  IMAGE_SELECTION_RESET_ERROR_MESSAGE,
  runImageSelection,
} from '../utils/image_selection';

const asset: ImagePickerAsset = { uri: 'file://image.jpg', width: 100, height: 100 };
const canceledResult: ImagePickerResult = { canceled: true, assets: null };

function createOptions() {
  return {
    sendSelecting: jest.fn(async () => undefined),
    cancelSelecting: jest.fn(async () => undefined),
    launchPicker: jest.fn(async (): Promise<ImagePickerResult> => ({ canceled: false, assets: [asset] })),
    onSelected: jest.fn(async (_asset: ImagePickerAsset) => undefined),
    emitError: jest.fn(),
  };
}

function failures() {
  return getDebugTraceSnapshot().filter((entry) => entry.message === 'failed')
    .map((entry) => JSON.parse(entry.detail!));
}

describe('runImageSelection', () => {
  beforeEach(clearDebugTrace);

  it('hands a selected asset to the sender once and records progress in release mode', async () => {
    const options = createOptions();
    await runImageSelection(options);
    expect(__DEV__).toBe(false);
    expect(options.launchPicker).toHaveBeenCalledTimes(1);
    expect(options.onSelected).toHaveBeenCalledWith(asset);
    expect(options.cancelSelecting).not.toHaveBeenCalled();
    expect(options.emitError).not.toHaveBeenCalled();
    expect(getDebugTraceSnapshot().map((entry) => entry.message)).toEqual([
      'started', 'launching picker', 'asset selected', 'selection handed to sender',
    ]);
  });

  it.each([
    canceledResult,
    { canceled: false, assets: [] } as ImagePickerResult,
  ])('resets after cancellation or an empty selection without showing an error', async (result) => {
    const options = createOptions();
    options.launchPicker.mockResolvedValue(result);
    await runImageSelection(options);
    expect(options.cancelSelecting).toHaveBeenCalledTimes(1);
    expect(options.onSelected).not.toHaveBeenCalled();
    expect(options.emitError).not.toHaveBeenCalled();
    expect(getDebugTraceSnapshot().map((entry) => entry.message)).toContain('reset completed');
  });

  it('catches native launch failure, logs diagnostic fields and resets without retrying the picker', async () => {
    const options = createOptions();
    const error = Object.assign(new Error('native launch failed'), { code: 'E_PICKER' });
    options.launchPicker.mockRejectedValue(error);
    await expect(runImageSelection(options)).resolves.toBeUndefined();
    expect(options.launchPicker).toHaveBeenCalledTimes(1);
    expect(options.emitError).toHaveBeenCalledWith(IMAGE_PICKER_ERROR_MESSAGE);
    expect(options.cancelSelecting).toHaveBeenCalledTimes(1);
    expect(options.onSelected).not.toHaveBeenCalled();
    expect(failures()).toEqual([{
      stage: 'launch_picker', name: 'Error', code: 'E_PICKER',
      message: error.message, stack: error.stack,
    }]);
  });

  it('records non-Error native rejection details', async () => {
    const options = createOptions();
    options.launchPicker.mockRejectedValue({ code: 'E_ACTIVITY', message: 'no activity' });
    await runImageSelection(options);
    expect(failures()).toEqual([{ stage: 'launch_picker', code: 'E_ACTIVITY', message: 'no activity' }]);
  });

  it('handles a selecting notification failure before launching the picker', async () => {
    const options = createOptions();
    options.sendSelecting.mockRejectedValue('notification failed');
    await runImageSelection(options);
    expect(options.launchPicker).not.toHaveBeenCalled();
    expect(options.cancelSelecting).toHaveBeenCalledTimes(1);
    expect(options.emitError).toHaveBeenCalledWith(IMAGE_SELECTION_ERROR_MESSAGE);
    expect(failures()).toEqual([{ stage: 'notify_selecting', message: 'notification failed' }]);
  });

  it('does not mislabel a selected-image callback failure as a picker launch failure', async () => {
    const options = createOptions();
    options.onSelected.mockRejectedValue(new Error('enqueue failed'));
    await runImageSelection(options);
    expect(options.emitError).toHaveBeenCalledWith(IMAGE_SELECTION_ERROR_MESSAGE);
    expect(options.cancelSelecting).toHaveBeenCalledTimes(1);
    expect(failures()[0]).toMatchObject({ stage: 'send_selected', message: 'enqueue failed' });
  });

  it('preserves the original error when recovery also fails', async () => {
    const options = createOptions();
    options.launchPicker.mockRejectedValue(new Error('launch failed'));
    options.cancelSelecting.mockRejectedValue(new Error('reset failed'));
    await expect(runImageSelection(options)).resolves.toBeUndefined();
    expect(options.cancelSelecting).toHaveBeenCalledTimes(1);
    expect(options.emitError.mock.calls).toEqual([
      [IMAGE_PICKER_ERROR_MESSAGE], [IMAGE_SELECTION_RESET_ERROR_MESSAGE],
    ]);
    expect(failures().map((error) => error.stage)).toEqual(['launch_picker', 'cancel_selecting']);
  });

  it('catches a reset failure after user cancellation without retrying reset', async () => {
    const options = createOptions();
    options.launchPicker.mockResolvedValue(canceledResult);
    options.cancelSelecting.mockRejectedValue(new Error('reset failed'));
    await expect(runImageSelection(options)).resolves.toBeUndefined();
    expect(options.cancelSelecting).toHaveBeenCalledTimes(1);
    expect(options.emitError).toHaveBeenCalledTimes(1);
    expect(options.emitError).toHaveBeenCalledWith(IMAGE_SELECTION_RESET_ERROR_MESSAGE);
    expect(failures()[0]).toMatchObject({ stage: 'cancel_selecting', message: 'reset failed' });
  });
});

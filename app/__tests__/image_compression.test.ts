jest.mock('expo-file-system/legacy', () => ({
  getInfoAsync: jest.fn(),
}));

jest.mock('expo-image-manipulator', () => ({
  ImageManipulator: { manipulate: jest.fn() },
  SaveFormat: { JPEG: 'jpeg', PNG: 'png' },
}));

import * as FileSystem from 'expo-file-system/legacy';
import { ImageManipulator } from 'expo-image-manipulator';
import {
  compressImageForUpload,
  IMAGE_COMPRESSION_TARGET_BYTES,
  MAX_IMAGE_FILE_SIZE_BYTES,
} from '../utils/image_compression';

const getInfoAsync = FileSystem.getInfoAsync as jest.Mock;
const manipulate = ImageManipulator.manipulate as jest.Mock;

function mockManipulator(outputUris: string[]) {
  const sourceImage = { width: 4000, height: 3000 };
  const saveAsync = jest.fn();
  outputUris.forEach((uri) => saveAsync.mockResolvedValueOnce({ uri, width: 1, height: 1 }));
  const resize = jest.fn();
  const renderAsync = jest
    .fn()
    .mockResolvedValueOnce(sourceImage)
    .mockImplementation(async () => ({ ...sourceImage, saveAsync }));
  manipulate.mockImplementation(() => ({ resize, renderAsync }));
  return { resize, saveAsync };
}

describe('compressImageForUpload', () => {
  beforeEach(() => jest.clearAllMocks());

  it('returns an image below the upload limit without recompressing it', async () => {
    getInfoAsync.mockResolvedValue({ exists: true, size: MAX_IMAGE_FILE_SIZE_BYTES });

    await expect(compressImageForUpload('file://small.jpg', 'image/jpeg')).resolves.toEqual({
      ok: true,
      uri: 'file://small.jpg',
      mimeType: 'image/jpeg',
      size: MAX_IMAGE_FILE_SIZE_BYTES,
    });
    expect(manipulate).not.toHaveBeenCalled();
  });

  it('returns the first JPEG stage when it reaches the target size', async () => {
    const { resize, saveAsync } = mockManipulator(['file://stage-1.jpg']);
    getInfoAsync
      .mockResolvedValueOnce({ exists: true, size: MAX_IMAGE_FILE_SIZE_BYTES + 1 })
      .mockResolvedValueOnce({ exists: true, size: IMAGE_COMPRESSION_TARGET_BYTES });

    await expect(compressImageForUpload('file://large.jpg', 'image/jpeg')).resolves.toEqual({
      ok: true,
      uri: 'file://stage-1.jpg',
      mimeType: 'image/jpeg',
      size: IMAGE_COMPRESSION_TARGET_BYTES,
    });
    expect(resize).toHaveBeenCalledWith({ width: 2560 });
    expect(saveAsync).toHaveBeenCalledWith({ format: 'jpeg', compress: 0.8 });
  });

  it('uses the second PNG stage without converting transparent images to JPEG', async () => {
    const { resize, saveAsync } = mockManipulator(['file://stage-1.png', 'file://stage-2.png']);
    getInfoAsync
      .mockResolvedValueOnce({ exists: true, size: MAX_IMAGE_FILE_SIZE_BYTES + 1 })
      .mockResolvedValueOnce({ exists: true, size: IMAGE_COMPRESSION_TARGET_BYTES + 1 })
      .mockResolvedValueOnce({ exists: true, size: IMAGE_COMPRESSION_TARGET_BYTES - 1 });

    await expect(compressImageForUpload('file://large.png', 'image/png')).resolves.toMatchObject({
      ok: true,
      uri: 'file://stage-2.png',
      mimeType: 'image/png',
    });
    expect(resize).toHaveBeenNthCalledWith(1, { width: 2560 });
    expect(resize).toHaveBeenNthCalledWith(2, { width: 2048 });
    expect(saveAsync).toHaveBeenCalledWith({ format: 'png' });
  });

  it('fails when every compression stage remains over the target', async () => {
    mockManipulator(['file://stage-1.jpg', 'file://stage-2.jpg']);
    getInfoAsync
      .mockResolvedValueOnce({ exists: true, size: MAX_IMAGE_FILE_SIZE_BYTES + 1 })
      .mockResolvedValue({ exists: true, size: IMAGE_COMPRESSION_TARGET_BYTES + 1 });

    await expect(compressImageForUpload('file://large.jpg', 'image/jpeg')).resolves.toEqual({
      ok: false,
      reason: 'compressed image remains too large',
    });
  });

  it('returns a failure when image manipulation throws', async () => {
    getInfoAsync.mockResolvedValue({ exists: true, size: MAX_IMAGE_FILE_SIZE_BYTES + 1 });
    manipulate.mockImplementation(() => {
      throw new Error('native error');
    });

    await expect(compressImageForUpload('file://large.jpg', 'image/jpeg')).resolves.toEqual({
      ok: false,
      reason: 'image compression failed: native error',
    });
  });

  it('skips compression when the source size is unavailable', async () => {
    getInfoAsync.mockResolvedValue({ exists: true });

    await expect(compressImageForUpload('file://unknown.jpg', 'image/jpeg')).resolves.toEqual({
      ok: true,
      uri: 'file://unknown.jpg',
      mimeType: 'image/jpeg',
      size: undefined,
    });
    expect(manipulate).not.toHaveBeenCalled();
  });
});

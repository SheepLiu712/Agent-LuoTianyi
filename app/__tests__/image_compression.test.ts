import * as FileSystem from 'expo-file-system/legacy';
import { ImageManipulator } from 'expo-image-manipulator';
import {
  compressImageForUpload,
  IMAGE_COMPRESSION_TARGET_BYTES,
  MAX_IMAGE_FILE_SIZE_BYTES,
} from '../utils/image_compression';

jest.mock('expo-file-system/legacy', () => ({
  getInfoAsync: jest.fn(),
}));

jest.mock('expo-image-manipulator', () => ({
  ImageManipulator: { manipulate: jest.fn() },
  SaveFormat: { JPEG: 'jpeg', PNG: 'png' },
}));

const getInfoAsync = FileSystem.getInfoAsync as jest.Mock;
const manipulate = ImageManipulator.manipulate as jest.Mock;

function mockManipulator(outputUris: string[]) {
  const saveAsync = jest.fn();
  const sourceImage = { width: 4000, height: 3000, saveAsync };
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
  beforeEach(() => jest.resetAllMocks());

  it.each(['image/jpeg', 'image/mpo', 'image/tiff'])('renders the primary bitmap even for a small %s', async (mime) => {
    const { saveAsync } = mockManipulator(['file://primary.jpg']);
    getInfoAsync.mockResolvedValue({ exists: true, size: 1024 });
    await expect(compressImageForUpload('file://small.jpg', mime)).resolves.toEqual({
      ok: true, uri: 'file://primary.jpg', mimeType: 'image/jpeg', size: 1024,
    });
    expect(saveAsync).toHaveBeenCalledWith({ format: 'jpeg', compress: 1 });
  });

  it.each(['image/gif', 'image/apng', 'image/webp'])('saves a single transparent bitmap for %s', async (mime) => {
    const { saveAsync } = mockManipulator(['file://primary.png']);
    getInfoAsync.mockResolvedValue({ exists: true, size: 1024 });
    await expect(compressImageForUpload('file://animated', mime)).resolves.toMatchObject({
      ok: true, uri: 'file://primary.png', mimeType: 'image/png',
    });
    expect(saveAsync).toHaveBeenCalledWith({ format: 'png' });
  });

  it('returns the first JPEG stage when it reaches the target size', async () => {
    const { resize, saveAsync } = mockManipulator(['file://primary.jpg', 'file://stage-1.jpg']);
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
    const { resize, saveAsync } = mockManipulator(['file://primary.png', 'file://stage-1.png', 'file://stage-2.png']);
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
    mockManipulator(['file://primary.jpg', 'file://stage-1.jpg', 'file://stage-2.jpg']);
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

  it('normalizes when original size is unavailable', async () => {
    mockManipulator(['file://primary.jpg']);
    getInfoAsync.mockImplementation(async (uri) => uri === 'file://unknown.jpg'
      ? { exists: true } : { exists: true, size: 1024 });
    await expect(compressImageForUpload('file://unknown.jpg', 'image/jpeg')).resolves.toMatchObject({
      ok: true, uri: 'file://primary.jpg', size: 1024,
    });
  });

  it('compresses again if primary extraction grows above the size limit', async () => {
    mockManipulator(['file://primary.jpg', 'file://compressed.jpg']);
    getInfoAsync.mockResolvedValueOnce({ exists: true, size: MAX_IMAGE_FILE_SIZE_BYTES + 1 })
      .mockResolvedValueOnce({ exists: true, size: 1024 });
    await expect(compressImageForUpload('file://small.mpo', 'image/jpeg')).resolves.toMatchObject({
      ok: true, uri: 'file://compressed.jpg', size: 1024,
    });
  });
  it('does not resize an oversized container when its primary fits the limit', async () => {
    const { resize, saveAsync } = mockManipulator(['file://primary.jpg']);
    getInfoAsync.mockImplementation(async (uri) => ({
      exists: true,
      size: uri === 'file://large.mpo' ? MAX_IMAGE_FILE_SIZE_BYTES * 2 : MAX_IMAGE_FILE_SIZE_BYTES,
    }));
    await expect(compressImageForUpload('file://large.mpo', 'image/jpeg')).resolves.toMatchObject({
      ok: true, uri: 'file://primary.jpg', size: MAX_IMAGE_FILE_SIZE_BYTES,
    });
    expect(getInfoAsync).toHaveBeenCalledTimes(1);
    expect(getInfoAsync).toHaveBeenCalledWith('file://primary.jpg');
    expect(resize).not.toHaveBeenCalled();
    expect(saveAsync).toHaveBeenCalledTimes(1);
    expect(saveAsync).toHaveBeenCalledWith({ format: 'jpeg', compress: 1 });
  });

  it('fails without guessing compression needs when primary size is unavailable', async () => {
    const { resize } = mockManipulator(['file://primary.jpg']);
    getInfoAsync.mockResolvedValue({ exists: true });
    await expect(compressImageForUpload('file://multi.mpo', 'image/jpeg')).resolves.toEqual({
      ok: false, reason: 'primary image size unavailable',
    });
    expect(resize).not.toHaveBeenCalled();
  });

});

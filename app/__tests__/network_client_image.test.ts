import * as FileSystem from 'expo-file-system/legacy';
import { compressImageForUpload, MAX_IMAGE_FILE_SIZE_BYTES } from '../utils/image_compression';
import { NetworkClient } from '../utils/network_client';

jest.mock('expo-file-system/legacy', () => ({
  EncodingType: { Base64: 'base64' },
  getInfoAsync: jest.fn(),
  readAsStringAsync: jest.fn(),
}));

jest.mock('../utils/debug_trace', () => ({ addDebugTrace: jest.fn() }));
jest.mock('../utils/image_compression', () => ({
  MAX_IMAGE_FILE_SIZE_BYTES: 6 * 1024 * 1024,
  compressImageForUpload: jest.fn(),
}));
jest.mock('../utils/ws_transport', () => ({ WebSocketTransport: jest.fn() }));

const getInfoAsync = FileSystem.getInfoAsync as jest.Mock;
const readAsStringAsync = FileSystem.readAsStringAsync as jest.Mock;
const compress = compressImageForUpload as jest.Mock;

function createClient() {
  const client = new NetworkClient();
  const submitUserImage = jest.fn().mockResolvedValue({ ok: true, request_id: 'image-1' });
  (client as any).transport = { submitUserImage };
  return { client, submitUserImage };
}

describe('NetworkClient.sendImage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    readAsStringAsync.mockResolvedValue('data:image/jpeg;base64,encoded-image');
    compress.mockImplementation(async (uri, mimeType) => ({ ok: true, uri, mimeType, size: 1024 }));
  });

  it('uploads only the normalized primary of a small JPEG-declared MPO', async () => {
    const { client, submitUserImage } = createClient();
    getInfoAsync.mockResolvedValue({ exists: true, size: 1024 });
    compress.mockResolvedValue({ ok: true, uri: 'file://primary.jpg', mimeType: 'image/jpeg', size: 900 });
    await client.sendImage('file://multi.jpg', 'image/jpeg', 'multi');
    expect(readAsStringAsync).toHaveBeenCalledWith('file://primary.jpg', { encoding: 'base64' });
    expect(submitUserImage).toHaveBeenCalledWith('encoded-image', 'image/jpeg', 'file://primary.jpg', 10000, 'multi');
  });

  it('does not upload original frames when native decoding fails', async () => {
    const { client, submitUserImage } = createClient();
    compress.mockResolvedValue({ ok: false, reason: 'image compression failed: unsupported decoder' });
    await expect(client.sendImage('file://multi.tiff', 'image/tiff', 'multi')).resolves.toMatchObject({
      ok: false, drop: true, error: '无法处理图片，请转换为普通 JPEG 或 PNG 后重试',
    });
    expect(readAsStringAsync).not.toHaveBeenCalled();
    expect(submitUserImage).not.toHaveBeenCalled();
  });

  it('compresses an oversized image and submits the resulting URI and MIME type', async () => {
    const { client, submitUserImage } = createClient();
    getInfoAsync.mockResolvedValue({ exists: true, size: MAX_IMAGE_FILE_SIZE_BYTES + 1 });
    compress.mockResolvedValue({
      ok: true,
      uri: 'file://compressed.jpg',
      mimeType: 'image/jpeg',
      size: 5 * 1024 * 1024,
    });

    await expect(client.sendImage('file://large.png', 'image/png', 'image-1')).resolves.toEqual({
      ok: true,
      request_id: 'image-1',
    });
    expect(readAsStringAsync).toHaveBeenCalledWith('file://compressed.jpg', { encoding: 'base64' });
    expect(submitUserImage).toHaveBeenCalledWith(
      'encoded-image',
      'image/jpeg',
      'file://compressed.jpg',
      10000,
      'image-1',
    );
  });

  it('returns a terminal size error when compression fails', async () => {
    const { client, submitUserImage } = createClient();
    getInfoAsync.mockResolvedValue({ exists: true, size: MAX_IMAGE_FILE_SIZE_BYTES + 1 });
    compress.mockResolvedValue({ ok: false, reason: 'compressed image remains too large' });

    await expect(client.sendImage('file://large.jpg', 'image/jpeg', 'image-2')).resolves.toEqual({
      ok: false,
      request_id: 'image-2',
      error: '图片过大（上限约 6 MB），请选择更小的图片',
      drop: true,
    });
    expect(readAsStringAsync).not.toHaveBeenCalled();
    expect(submitUserImage).not.toHaveBeenCalled();
  });

  it('submits an image below the limit after primary normalization', async () => {
    const { client, submitUserImage } = createClient();
    getInfoAsync.mockResolvedValue({ exists: true, size: MAX_IMAGE_FILE_SIZE_BYTES });

    await client.sendImage('file://small.png', 'image/png', 'image-3');

    expect(compress).toHaveBeenCalledTimes(1);
    expect(readAsStringAsync).toHaveBeenCalledWith('file://small.png', { encoding: 'base64' });
    expect(submitUserImage).toHaveBeenCalledWith(
      'encoded-image',
      'image/png',
      'file://small.png',
      10000,
      'image-3',
    );
  });

  it('uses the original send path when the source size is unavailable', async () => {
    const { client, submitUserImage } = createClient();
    getInfoAsync.mockResolvedValue({ exists: true });

    await client.sendImage('file://unknown.jpg', 'image/jpeg', 'image-4');

    expect(compress).toHaveBeenCalledTimes(1);
    expect(submitUserImage).toHaveBeenCalledWith(
      'encoded-image',
      'image/jpeg',
      'file://unknown.jpg',
      10000,
      'image-4',
    );
  });
});

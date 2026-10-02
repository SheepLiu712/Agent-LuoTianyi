const mockGetInfoAsync = jest.fn();
const mockReadAsStringAsync = jest.fn();

jest.mock('expo-file-system/legacy', () => ({
  EncodingType: { Base64: 'base64' },
  getInfoAsync: mockGetInfoAsync,
  readAsStringAsync: mockReadAsStringAsync,
}));
jest.mock('../utils/ws_transport', () => ({ WebSocketTransport: jest.fn() }));
jest.mock('../utils/image_compression', () => ({
  MAX_IMAGE_FILE_SIZE_BYTES: 6 * 1024 * 1024,
  compressImageForUpload: jest.fn().mockResolvedValue({ ok: false, reason: 'still too large' }),
}));

import { compressImageForUpload } from '../utils/image_compression';
import { NetworkClient } from '../utils/network_client';

const MAX_IMAGE_FILE_SIZE_BYTES = 6 * 1024 * 1024;

function createConnectedClient() {
  const client = new NetworkClient();
  const transport = {
    submitUserImage: jest.fn().mockResolvedValue({ ok: true, request_id: 'request-1' }),
  };
  (client as unknown as { transport: typeof transport }).transport = transport;
  return { client, transport };
}

describe('NetworkClient image size preflight', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockReadAsStringAsync.mockResolvedValue('aW1hZ2U=');
  });

  it('rejects an oversized image when compression cannot bring it under the limit', async () => {
    mockGetInfoAsync.mockResolvedValue({ exists: true, size: MAX_IMAGE_FILE_SIZE_BYTES + 1 });
    const { client, transport } = createConnectedClient();

    const result = await client.sendImage('file://large.jpg', 'image/jpeg', 'client-1');

    expect(result).toEqual({
      ok: false,
      request_id: 'client-1',
      error: '图片过大（上限约 6 MB），请选择更小的图片',
      drop: true,
    });
    expect(mockReadAsStringAsync).not.toHaveBeenCalled();
    expect(transport.submitUserImage).not.toHaveBeenCalled();
    expect(compressImageForUpload).toHaveBeenCalledWith('file://large.jpg', 'image/jpeg');
  });

  it('allows an image at the size boundary', async () => {
    mockGetInfoAsync.mockResolvedValue({ exists: true, size: MAX_IMAGE_FILE_SIZE_BYTES });
    const { client, transport } = createConnectedClient();

    const result = await client.sendImage('file://boundary.jpg', 'image/jpeg', 'client-2');

    expect(result.ok).toBe(true);
    expect(mockReadAsStringAsync).toHaveBeenCalledWith('file://boundary.jpg', { encoding: 'base64' });
    expect(transport.submitUserImage).toHaveBeenCalledWith(
      'aW1hZ2U=',
      'image/jpeg',
      'file://boundary.jpg',
      10000,
      'client-2',
    );
  });

  it('allows an image when its size is unavailable', async () => {
    mockGetInfoAsync.mockRejectedValue(new Error('unsupported URI'));
    const { client, transport } = createConnectedClient();

    const result = await client.sendImage('content://unknown.jpg', 'image/jpeg', 'client-3');

    expect(result.ok).toBe(true);
    expect(compressImageForUpload).not.toHaveBeenCalled();
    expect(mockReadAsStringAsync).toHaveBeenCalledWith('content://unknown.jpg', { encoding: 'base64' });
    expect(transport.submitUserImage).toHaveBeenCalledWith(
      'aW1hZ2U=', 'image/jpeg', 'content://unknown.jpg', 10000, 'client-3',
    );
  });

  it('returns a terminal read error when both metadata and content are unavailable', async () => {
    mockGetInfoAsync.mockRejectedValue(new Error('unsupported URI'));
    mockReadAsStringAsync.mockRejectedValue(new Error('file missing'));
    const { client, transport } = createConnectedClient();

    await expect(client.sendImage('content://missing.jpg', 'image/jpeg', 'client-4')).resolves.toEqual({
      ok: false,
      request_id: 'client-4',
      error: 'failed to read image file',
      drop: true,
    });
    expect(mockReadAsStringAsync).toHaveBeenCalled();
    expect(transport.submitUserImage).not.toHaveBeenCalled();
  });
});

import * as FileSystem from 'expo-file-system/legacy';
import { ImageManipulator, SaveFormat } from 'expo-image-manipulator';

export const MAX_IMAGE_FILE_SIZE_BYTES = 6 * 1024 * 1024;
export const IMAGE_COMPRESSION_TARGET_BYTES = Math.floor(5.5 * 1024 * 1024);

type CompressionSuccess = {
  ok: true;
  uri: string;
  mimeType: string;
  size?: number;
};

type CompressionFailure = {
  ok: false;
  reason: string;
};

export type ImageCompressionResult = CompressionSuccess | CompressionFailure;

type CompressionStage = {
  maxDimension: number;
  jpegQuality: number;
};

const COMPRESSION_STAGES: CompressionStage[] = [
  { maxDimension: 2560, jpegQuality: 0.8 },
  { maxDimension: 2048, jpegQuality: 0.6 },
];

async function getFileSize(uri: string): Promise<number | undefined> {
  const info = await FileSystem.getInfoAsync(uri);
  return info.exists && typeof info.size === 'number' ? info.size : undefined;
}

function getResizeDimensions(width: number, height: number, maxDimension: number) {
  if (Math.max(width, height) <= maxDimension) {
    return null;
  }
  return width >= height ? { width: maxDimension } : { height: maxDimension };
}

export async function compressImageForUpload(
  uri: string,
  mimeType: string,
): Promise<ImageCompressionResult> {
  try {
    const originalSize = await getFileSize(uri);
    if (originalSize === undefined || originalSize <= MAX_IMAGE_FILE_SIZE_BYTES) {
      return { ok: true, uri, mimeType, size: originalSize };
    }

    const sourceImage = await ImageManipulator.manipulate(uri).renderAsync();
    const isPng = mimeType.toLowerCase() === 'image/png';

    for (const stage of COMPRESSION_STAGES) {
      const context = ImageManipulator.manipulate(sourceImage);
      const resize = getResizeDimensions(sourceImage.width, sourceImage.height, stage.maxDimension);
      if (resize) {
        context.resize(resize);
      }

      const renderedImage = await context.renderAsync();
      const result = await renderedImage.saveAsync({
        format: isPng ? SaveFormat.PNG : SaveFormat.JPEG,
        ...(isPng ? {} : { compress: stage.jpegQuality }),
      });
      const compressedSize = await getFileSize(result.uri);
      if (compressedSize !== undefined && compressedSize <= IMAGE_COMPRESSION_TARGET_BYTES) {
        return {
          ok: true,
          uri: result.uri,
          mimeType: isPng ? 'image/png' : 'image/jpeg',
          size: compressedSize,
        };
      }
    }

    return { ok: false, reason: 'compressed image remains too large' };
  } catch (error) {
    const reason = error instanceof Error ? error.message : String(error);
    return { ok: false, reason: `image compression failed: ${reason}` };
  }
}

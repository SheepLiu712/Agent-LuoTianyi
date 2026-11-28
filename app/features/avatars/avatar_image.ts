import { ImageManipulator, SaveFormat } from 'expo-image-manipulator';
import type { ImagePickerAsset } from 'expo-image-picker';
import type { CropSource } from './avatar_crop';

type CropRegion = { originX: number; originY: number; width: number; height: number };

export async function loadAvatarSource(asset: ImagePickerAsset): Promise<CropSource> {
  const mime = asset.mimeType?.toLowerCase() || (/\.png$/i.test(asset.fileName || asset.uri) ? 'image/png'
    : /\.jpe?g$/i.test(asset.fileName || asset.uri) ? 'image/jpeg' : '');
  if (mime !== 'image/png' && mime !== 'image/jpeg') throw new Error('头像仅支持 PNG 或 JPEG 图片。');
  const source = await ImageManipulator.manipulate(asset.uri).renderAsync();
  const context = ImageManipulator.manipulate(source);
  if (Math.max(source.width, source.height) > 2048) context.resize(source.width >= source.height ? { width: 2048 } : { height: 2048 });
  return (await context.renderAsync()).saveAsync({ format: SaveFormat.PNG });
}

export async function prepareAvatar(source: CropSource, crop: CropRegion): Promise<string> {
  const context = ImageManipulator.manipulate(source.uri);
  context.crop(crop).resize({ width: 256, height: 256 });
  const image = await context.renderAsync();
  const result = await image.saveAsync({ format: SaveFormat.PNG, base64: true });
  if (!result.base64) throw new Error('无法处理头像图片，请重试。');
  return `data:image/png;base64,${result.base64}`;
}

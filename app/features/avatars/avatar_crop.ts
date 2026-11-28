export interface CropSource { uri: string; width: number; height: number }
export interface CropView { zoom: number; x: number; y: number }
export const initialCrop: CropView = { zoom: 1, x: 0, y: 0 };

export function cropTransform(source: CropSource, size: number, view: CropView) {
  const scale = Math.max(size / source.width, size / source.height) * Math.max(1, Math.min(8, view.zoom));
  const width = source.width * scale;
  const height = source.height * scale;
  const x = Math.max(-(width - size) / 2, Math.min((width - size) / 2, view.x));
  const y = Math.max(-(height - size) / 2, Math.min((height - size) / 2, view.y));
  return { scale, width, height, x, y };
}

export function cropRegion(source: CropSource, size: number, view: CropView) {
  const { scale, x, y } = cropTransform(source, size, view);
  const side = Math.max(1, Math.min(source.width, source.height, Math.round(size / scale)));
  return {
    originX: Math.max(0, Math.min(source.width - side, Math.round((source.width - size / scale) / 2 - x / scale))),
    originY: Math.max(0, Math.min(source.height - side, Math.round((source.height - size / scale) / 2 - y / scale))),
    width: side, height: side,
  };
}

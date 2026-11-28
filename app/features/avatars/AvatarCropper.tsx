import React, { useMemo, useRef } from 'react';
import { Image, PanResponder, StyleSheet, View, type GestureResponderEvent } from 'react-native';
import { cropTransform, type CropSource, type CropView } from './avatar_crop';

function touchPosition(event: GestureResponderEvent) {
  const touches = event.nativeEvent.touches;
  const first = touches[0];
  const second = touches[1] || first;
  return { count: touches.length, x: (first.pageX + second.pageX) / 2, y: (first.pageY + second.pageY) / 2,
    distance: Math.hypot(second.pageX - first.pageX, second.pageY - first.pageY) };
}

export function AvatarCropper({ source, size, value, onChange }: {
  source: CropSource; size: number; value: CropView; onChange(value: CropView): void;
}) {
  const frameRef = useRef<View>(null);
  const center = useRef({ x: size / 2, y: size / 2 });
  const measureFrame = () => frameRef.current?.measureInWindow((x, y, width, height) => {
    center.current = { x: x + width / 2, y: y + height / 2 };
  });
  const current = useRef({ source, size, value, onChange });
  current.current = { source, size, value, onChange };
  const gesture = useRef<(ReturnType<typeof touchPosition> & { view: CropView }) | undefined>(undefined);
  const responder = useMemo(() => {
    const begin = (event: GestureResponderEvent) => {
      gesture.current = { ...touchPosition(event), view: current.current.value };
    };
    return PanResponder.create({
      onStartShouldSetPanResponder: () => true,
      onMoveShouldSetPanResponder: () => true,
      onPanResponderTerminationRequest: () => false,
      onPanResponderGrant: event => { measureFrame(); begin(event); },
      onPanResponderMove: event => {
        const position = touchPosition(event);
        const start = gesture.current;
        if (!start || start.count !== position.count) { begin(event); return; }
        const { source, size, onChange } = current.current;
        const zoom = Math.max(1, Math.min(8, start.view.zoom * (start.distance ? position.distance / start.distance : 1)));
        const ratio = zoom / start.view.zoom;
        const transform = cropTransform(source, size, { zoom,
          x: start.view.x * ratio + position.x - start.x + (1 - ratio) * (start.x - center.current.x),
          y: start.view.y * ratio + position.y - start.y + (1 - ratio) * (start.y - center.current.y) });
        const next = { zoom, x: transform.x, y: transform.y };
        current.current.value = next;
        onChange(next);
      },
      onPanResponderRelease: () => { gesture.current = undefined; },
      onPanResponderTerminate: () => { gesture.current = undefined; },
    });
  }, []);
  const frame = cropTransform(source, size, value);
  return <View ref={frameRef} onLayout={measureFrame} accessibilityLabel="拖动照片或双指缩放以裁剪头像" {...responder.panHandlers}
    style={{ width: size, height: size, overflow: 'hidden', backgroundColor: '#111' }}>
    <Image source={{ uri: source.uri }} resizeMode="stretch" style={{ position: 'absolute',
      width: frame.width, height: frame.height, left: (size - frame.width) / 2 + frame.x, top: (size - frame.height) / 2 + frame.y }} />
    <View pointerEvents="none" style={{ position: 'absolute', left: -size, top: -size,
      width: size * 3, height: size * 3, borderRadius: size * 1.5, borderWidth: size,
      borderColor: 'rgba(0, 0, 0, 0.6)' }} />
    <View pointerEvents="none" style={[StyleSheet.absoluteFillObject, { borderWidth: 1, borderColor: '#fff', borderRadius: size / 2 }]} />
  </View>;
}

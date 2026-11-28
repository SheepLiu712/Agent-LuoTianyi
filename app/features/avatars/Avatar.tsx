import React from 'react';
import { Image, TouchableOpacity, View } from 'react-native';
import type { AvatarImage, AvatarSide } from './avatar_sync';

export function AvatarRow({ side, image, onEdit, children }: React.PropsWithChildren<{
  side: AvatarSide | null; image: AvatarImage; onEdit?(side: AvatarSide): void;
}>) {
  if (!side) return <>{children}</>;
  const avatar = <View style={{ paddingTop: 5 }}><TouchableOpacity accessibilityRole="button"
    accessibilityLabel={side === 'user' ? '更换我的头像' : '更换天依头像'} hitSlop={4}
    disabled={!onEdit} onPress={() => onEdit?.(side)}><Avatar side={side} image={image} /></TouchableOpacity></View>;
  return <View style={{ flexDirection: 'row', alignItems: 'flex-start', paddingHorizontal: 8 }}>
    {side === 'agent' && avatar}
    <View style={{ flex: 1 }}>{children}</View>
    {side === 'user' && avatar}
  </View>;
}

export function Avatar({ side, image, size = 36 }: { side: AvatarSide; image: AvatarImage; size?: number }) {
  return <Image accessibilityLabel={side === 'user' ? '我的头像' : '天依头像'}
    source={image ? { uri: image } : side === 'user'
      ? require('../../assets/images/user_icon.png') : require('../../assets/images/icon.png')}
    style={{ width: size, height: size, borderRadius: size / 2 }} resizeMode="contain" />;
}

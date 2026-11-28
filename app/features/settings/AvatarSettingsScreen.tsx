import React, { useEffect, useRef, useState } from 'react';
import { BackHandler, ScrollView, StyleSheet, Text, TouchableOpacity, View, useWindowDimensions } from 'react-native';
import * as ImagePicker from 'expo-image-picker';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { usePageNotices } from '../../shell/notices/AppNotices';
import type { AppTheme } from '../../shared/ui/theme';
import { runImageSelection } from '../chat/image_selection';
import { Avatar } from '../avatars/Avatar';
import { AvatarCropper } from '../avatars/AvatarCropper';
import { cropRegion, cropTransform, initialCrop, type CropSource } from '../avatars/avatar_crop';
import { loadAvatarSource, prepareAvatar } from '../avatars/avatar_image';
import type { AvatarImage, AvatarSide } from '../avatars/avatar_sync';
import type { Avatars } from '../avatars/useAvatars';

export default function AvatarSettingsScreen({ avatars, side, theme, onClose }: {
  avatars: Avatars; side: AvatarSide; theme: AppTheme; onClose(): void;
}) {
  const insets = useSafeAreaInsets();
  const { width } = useWindowDimensions();
  const size = Math.min(280, width - 48);
  const showNotice = usePageNotices('avatars');
  const [draft, setDraft] = useState<AvatarImage>();
  const [source, setSource] = useState<CropSource>();
  const [crop, setCrop] = useState(initialCrop);
  const [busy, setBusy] = useState(false);
  const active = useRef(true);
  const checkAvatars = avatars.check;
  useEffect(() => { void checkAvatars(); }, [checkAvatars]);
  useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);
  useEffect(() => {
    const subscription = BackHandler.addEventListener('hardwareBackPress', () => { onClose(); return true; });
    return () => subscription.remove();
  }, [onClose]);
  const showError = (error: unknown) => {
    if (active.current) showNotice({ message: error instanceof Error ? error.message : '头像处理失败，请重试。', theme });
  };
  const choose = async () => {
    setBusy(true);
    await runImageSelection({
      sendSelecting: async () => {}, cancelSelecting: async () => {},
      launchPicker: (legacy = false) => ImagePicker.launchImageLibraryAsync({ mediaTypes: ['images'], quality: 1, allowsEditing: false, legacy }),
      emitError: message => { if (active.current) showNotice({ message, theme }); },
      onSelected: async asset => {
        try {
          const image = await loadAvatarSource(asset);
          if (active.current) { setSource(image); setCrop(initialCrop); setDraft(undefined); }
        } catch (error) { showError(error); }
      },
    });
    if (active.current) setBusy(false);
  };
  const save = async () => {
    setBusy(true);
    try {
      const image = source ? await prepareAvatar(source, cropRegion(source, size, crop)) : draft!;
      if (active.current) { void avatars.save(side, image); onClose(); }
    } catch (error) { showError(error); }
    if (active.current) setBusy(false);
  };
  const zoom = (factor: number) => {
    if (!source) return;
    const next = { ...crop, zoom: Math.max(1, Math.min(8, crop.zoom * factor)) };
    const transform = cropTransform(source, size, next);
    setCrop({ zoom: next.zoom, x: transform.x, y: transform.y });
  };
  const name = side === 'user' ? '我的头像' : '天依头像';
  const dirty = Boolean(source) || draft !== undefined;
  return <View style={[styles.root, { backgroundColor: theme.root, paddingTop: insets.top, paddingBottom: insets.bottom }]}>
    <View style={[styles.header, { borderBottomColor: theme.border }]}>
      <TouchableOpacity accessibilityRole="button" onPress={onClose}><Text style={{ color: theme.accentText }}>返回</Text></TouchableOpacity>
      <Text style={[styles.title, { color: theme.text }]}>{name}</Text>
      <TouchableOpacity accessibilityRole="button" accessibilityLabel={`保存${name}`} disabled={!dirty || !avatars.ready || busy} onPress={() => { void save(); }}>
        <Text style={{ color: dirty && !busy ? theme.accentText : theme.textMuted }}>保存</Text>
      </TouchableOpacity>
    </View>
    <ScrollView contentContainerStyle={styles.content} scrollEnabled={!busy}>
      {source ? <AvatarCropper key={source.uri} source={source} size={size} value={crop} onChange={setCrop} /> :
        <TouchableOpacity accessibilityRole="button" accessibilityLabel={`选择${name}`} disabled={!avatars.ready || busy} onPress={() => { void choose(); }}>
          <Avatar side={side} image={draft !== undefined ? draft : avatars[side]} size={192} />
        </TouchableOpacity>}
      {source && <Text style={{ color: theme.textMuted }}>拖动照片、双指缩放调整位置，圆框内为头像预览，保存后生效。</Text>}
      {source && <View style={styles.zoom}>
        <TouchableOpacity accessibilityRole="button" accessibilityLabel="缩小照片" disabled={busy} onPress={() => zoom(1 / 1.2)} style={styles.button}><Text style={{ color: theme.accentText }}>缩小</Text></TouchableOpacity>
        <TouchableOpacity accessibilityRole="button" accessibilityLabel="放大照片" disabled={busy} onPress={() => zoom(1.2)} style={styles.button}><Text style={{ color: theme.accentText }}>放大</Text></TouchableOpacity>
      </View>}
      <TouchableOpacity accessibilityRole="button" accessibilityLabel={`从相册选择${name}`} disabled={!avatars.ready || busy} onPress={() => { void choose(); }} style={styles.button}>
        <Text style={{ color: theme.accentText }}>{busy ? '处理中…' : '从相册选择'}</Text>
      </TouchableOpacity>
      <TouchableOpacity accessibilityRole="button" accessibilityLabel={`恢复默认${name}`} disabled={!avatars.ready || busy} onPress={() => { setSource(undefined); setDraft(null); }} style={styles.button}>
        <Text style={{ color: theme.accentText }}>恢复默认</Text>
      </TouchableOpacity>
      {avatars.error && <Text accessibilityRole="alert" style={{ color: theme.dangerText }}>{avatars.error}</Text>}
      {avatars.error && <TouchableOpacity accessibilityRole="button" onPress={() => { void avatars.retry(); }} style={styles.button}>
        <Text style={{ color: theme.accentText }}>立即重试</Text>
      </TouchableOpacity>}
    </ScrollView>
  </View>;
}
const styles = StyleSheet.create({
  root: { ...StyleSheet.absoluteFillObject, zIndex: 120 },
  header: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', padding: 18, borderBottomWidth: 1 },
  title: { fontSize: 17, fontWeight: '700' },
  content: { padding: 24, gap: 16, alignItems: 'center' },
  zoom: { flexDirection: 'row', gap: 24 },
  button: { padding: 12, minHeight: 44, justifyContent: 'center' },
});

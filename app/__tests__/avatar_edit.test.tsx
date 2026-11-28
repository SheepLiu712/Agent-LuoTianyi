import React from 'react';
import { act, create, type ReactTestRenderer } from 'react-test-renderer';
import * as ImagePicker from 'expo-image-picker';
import { AvatarRow } from '../features/avatars/Avatar';
import { AvatarCropper } from '../features/avatars/AvatarCropper';
import { cropRegion, initialCrop, type CropView } from '../features/avatars/avatar_crop';
import AvatarSettingsScreen from '../features/settings/AvatarSettingsScreen';
import { emptyAvatars } from '../features/avatars/avatar_sync';
import { loadAvatarSource, prepareAvatar } from '../features/avatars/avatar_image';
import { THEMES } from '../shared/ui/theme';

jest.mock('react-native', () => ({
  BackHandler: { addEventListener: jest.fn(() => ({ remove: jest.fn() })) },
  Image: 'Image', View: 'View', Text: 'Text', TouchableOpacity: 'Button', ScrollView: 'ScrollView',
  PanResponder: { create: (handlers: unknown) => ({ panHandlers: handlers }) },
  useWindowDimensions: () => ({ width: 400 }),
  StyleSheet: { create: (styles: unknown) => styles, absoluteFillObject: {} },
}));
jest.mock('react-native-safe-area-context', () => ({ useSafeAreaInsets: () => ({ top: 0, bottom: 0 }) }));
jest.mock('expo-image-picker', () => ({ launchImageLibraryAsync: jest.fn() }));
jest.mock('../shell/notices/AppNotices', () => ({ usePageNotices: () => jest.fn() }));
jest.mock('../features/avatars/avatar_image', () => ({ prepareAvatar: jest.fn(), loadAvatarSource: jest.fn() }));

it('点击聊天双方头像各自打开对应编辑入口，系统消息没有头像入口', () => {
  const edit = jest.fn();
  let tree!: ReactTestRenderer;
  act(() => { tree = create(<><AvatarRow side="user" image={null} onEdit={edit} /><AvatarRow side="agent" image={null} onEdit={edit} /><AvatarRow side={null} image={null} onEdit={edit} /></>); });
  const buttons = tree.root.findAllByType('Button' as React.ElementType);
  expect(buttons).toHaveLength(2);
  act(() => buttons[0].props.onPress());
  expect(edit).toHaveBeenLastCalledWith('user');
  act(() => buttons[1].props.onPress());
  expect(edit).toHaveBeenLastCalledWith('agent');
  act(() => tree.unmount());
});

it('取消不改头像，选择后只预览，保存时按裁剪区域仅修改点击的一侧', async () => {
  const save = jest.fn(async () => {});
  const close = jest.fn();
  const avatars = { ...emptyAvatars, ready: true, save, check: jest.fn(async () => {}), retry: jest.fn(async () => {}) };
  const picker = jest.mocked(ImagePicker.launchImageLibraryAsync);
  picker.mockResolvedValueOnce({ canceled: true, assets: null });
  picker.mockResolvedValueOnce({ canceled: false, assets: [{ uri: 'file:///source.png', width: 800, height: 400 }] });
  const source = { uri: 'file:///normalized.png', width: 800, height: 400 };
  jest.mocked(loadAvatarSource).mockResolvedValue(source);
  jest.mocked(prepareAvatar).mockResolvedValue('data:image/png;base64,cropped');
  let tree!: ReactTestRenderer;
  act(() => { tree = create(<AvatarSettingsScreen avatars={avatars} side="agent" theme={THEMES.light} onClose={close} />); });
  const button = (label: string) => tree.root.findByProps({ accessibilityLabel: label });
  expect(avatars.check).toHaveBeenCalledTimes(1);
  await act(async () => { button('从相册选择天依头像').props.onPress(); });
  expect(save).not.toHaveBeenCalled();
  expect(loadAvatarSource).not.toHaveBeenCalled();
  await act(async () => { button('从相册选择天依头像').props.onPress(); });
  expect(tree.root.findByType(AvatarCropper).props.source).toEqual(source);
  expect(save).not.toHaveBeenCalled();
  await act(async () => { button('保存天依头像').props.onPress(); });
  expect(prepareAvatar).toHaveBeenCalledWith(source, { originX: 200, originY: 0, width: 400, height: 400 });
  expect(save).toHaveBeenCalledWith('agent', 'data:image/png;base64,cropped');
  expect(close).toHaveBeenCalledTimes(1);
  act(() => tree.unmount());
});

it('双指放大并拖图得到对应裁剪区域，拖到边界不会裁出空白', () => {
  const source = { uri: 'photo', width: 800, height: 400 };
  let view: CropView = initialCrop;
  let tree!: ReactTestRenderer;
  act(() => { tree = create(<AvatarCropper source={source} size={200} value={view} onChange={next => { view = next; }} />); });
  const frame = tree.root.findByProps({ accessibilityLabel: '拖动照片或双指缩放以裁剪头像' });
  const event = (...points: number[]) => ({ nativeEvent: { touches: points.map(x => ({ pageX: x, pageY: 100 })) } });
  act(() => frame.props.onPanResponderGrant(event(50, 150)));
  act(() => frame.props.onPanResponderMove(event(0, 200)));
  expect(view.zoom).toBe(2);
  expect(cropRegion(source, 200, view)).toEqual({ originX: 300, originY: 100, width: 200, height: 200 });
  act(() => frame.props.onPanResponderMove(event(100)));
  act(() => frame.props.onPanResponderMove(event(9999)));
  expect(cropRegion(source, 200, view)).toEqual({ originX: 0, originY: 100, width: 200, height: 200 });
  expect(cropRegion({ uri: 'tiny', width: 1, height: 1 }, 200, { zoom: 8, x: 500, y: -500 }))
    .toEqual({ originX: 0, originY: 0, width: 1, height: 1 });
  act(() => tree.unmount());
});

it('偏心双指缩放时保持两指中点下的照片位置', () => {
  const source = { uri: 'photo', width: 800, height: 400 };
  let view: CropView = initialCrop;
  let tree!: ReactTestRenderer;
  act(() => { tree = create(<AvatarCropper source={source} size={200} value={view} onChange={next => { view = next; }} />); });
  const frame = tree.root.findByProps({ accessibilityLabel: '拖动照片或双指缩放以裁剪头像' });
  const event = (...points: number[]) => ({ nativeEvent: { touches: points.map(x => ({ pageX: x, pageY: 100 })) } });
  act(() => frame.props.onPanResponderGrant(event(125, 175)));
  act(() => frame.props.onPanResponderMove(event(100, 200)));
  expect(view).toEqual({ zoom: 2, x: -50, y: 0 });
  expect(cropRegion(source, 200, view)).toEqual({ originX: 350, originY: 100, width: 200, height: 200 });
  act(() => tree.unmount());
});

import React from 'react';
import { act, create, ReactTestRenderer } from 'react-test-renderer';
import { VoiceRecordingOverlay } from '../components/VoiceRecordingOverlay';
import { THEMES } from '../utils/theme';

jest.mock('react-native', () => ({
  View: 'View', Text: 'Text',
  StyleSheet: { create: (styles: unknown) => styles, absoluteFillObject: { position: 'absolute', top: 0, bottom: 0, left: 0, right: 0 } },
  useWindowDimensions: () => ({ width: 390, height: 844, fontScale: 1 }),
}));
jest.mock('@expo/vector-icons/MaterialIcons', () => 'MaterialIcons');
const flatten = (style: any): any => Array.isArray(style) ? Object.assign({}, ...style.map(flatten)) : style;
let tree: ReactTestRenderer;
afterEach(() => act(() => tree?.unmount()));

it.each(['light', 'dark'] as const)('同步切换%s主题的两块颜色、文案，并恢复累计时间', (mode) => {
  const render = (cancelZone: boolean, elapsedMs: number, meter: number) => (
    <VoiceRecordingOverlay cancelZone={cancelZone} elapsedMs={elapsedMs} meter={meter} theme={THEMES[mode]} bottomInset={24} topInset={24} />
  );
  act(() => { tree = create(render(false, 0, 0)); });
  const texts = () => tree.root.findAllByType('Text' as any).filter((node) => flatten(node.props.style).opacity !== 0).map((node) => node.props.children);
  const card = () => flatten(tree.root.findByProps({ testID: 'voice-recording-card' }).props.style);
  const bottomColors = () => tree.root.findByProps({ testID: 'voice-recording-bottom' }).findAllByType('View' as any)
    .map((node) => flatten(node.props.style)?.backgroundColor).filter(Boolean);
  expect(texts()).toEqual(['0″ / 30″', '松手发送']);
  expect(card().backgroundColor).toBe(THEMES[mode].accent);
  expect(bottomColors()).toEqual([THEMES[mode].accent, THEMES[mode].accent]);
  expect(flatten(tree.root.findByProps({ testID: 'voice-recording-overlay' }).props.style).backgroundColor).toBe('rgba(0, 0, 0, 0.75)');
  const initialCard = card();
  act(() => tree.update(render(true, 8000, 0.5)));
  expect(texts()).toEqual(['松手取消发送']);
  expect(card()).toEqual({ ...initialCard, backgroundColor: '#F04464' });
  expect(bottomColors()).toEqual(['#F04464', '#F04464']);
  expect(tree.root.findByType('MaterialIcons' as any).props).toMatchObject({ name: 'mic', size: 32, color: '#FFFFFF' });
  act(() => tree.update(render(false, 9900, 0.5)));
  expect(texts()).toEqual(['9″ / 30″', '松手发送']);
  expect(card()).toEqual(initialCard);
  expect(tree.root.findByProps({ testID: 'voice-recording-overlay' }).props.pointerEvents).toBe('none');
});

it('静音最低、音量增大单调增高，取消期间继续响应且滑回不重置', () => {
  const render = (meter: number, cancelZone = false) => <VoiceRecordingOverlay meter={meter} cancelZone={cancelZone} elapsedMs={1000} />;
  act(() => { tree = create(render(0)); });
  const heights = () => tree.root.findAllByProps({ testID: 'voice-meter-bar' }).map((bar) => flatten(bar.props.style).height);
  expect(heights()).toEqual(Array(25).fill(3));
  act(() => tree.update(render(0.4)));
  const quiet = heights();
  act(() => tree.update(render(1, true)));
  const loud = heights();
  expect(loud.every((height, index) => height > quiet[index] && height <= 28)).toBe(true);
  act(() => tree.update(render(1)));
  expect(heights()).toEqual(loud);
  act(() => tree.update(render(0)));
  expect(heights()).toEqual(Array(25).fill(3));
});

it.each([320, 390])('宽度%d下卡片保留边距，弧形和麦克风避开底部安全区', (width) => {
  act(() => { tree = create(<VoiceRecordingOverlay meter={0} cancelZone={false} elapsedMs={31000} bottomInset={34} />); });
  act(() => tree.root.findByProps({ testID: 'voice-recording-overlay' }).props.onLayout({ nativeEvent: { layout: { width } } }));
  const card = tree.root.findByProps({ testID: 'voice-recording-card' });
  expect(flatten(card.props.style)).toMatchObject({ width: 240, maxWidth: '100%', minHeight: 120 });
  expect(flatten(card.parent!.props.style)).toMatchObject({ left: 24, right: 24, bottom: 34 });
  const bottom = tree.root.findByProps({ testID: 'voice-recording-bottom' });
  expect(flatten(bottom.props.style).height).toBe(194);
  const ellipse = bottom.findAllByType('View' as any)[1];
  const style = flatten(ellipse.props.style);
  expect(style.width).toBe(width);
  expect(style.top + style.height / 2 - style.height * style.transform[0].scaleY / 2).toBeCloseTo(0);
  expect(flatten(tree.root.findByType('MaterialIcons' as any).parent!.props.style).bottom).toBe(74);
  expect(tree.root.findAllByType('Text' as any).map((node) => node.props.children)).toContain('30″ / 30″');
});

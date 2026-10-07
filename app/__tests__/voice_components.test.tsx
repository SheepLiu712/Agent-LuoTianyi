import React from 'react';
import { act, create, ReactTestRenderer } from 'react-test-renderer';

import { MessageItem } from '../components/ChatBubbles';
import { VoiceBubble } from '../components/VoiceBubble';
import { VoiceInputBar } from '../components/VoiceInputBar';

jest.mock('react-native', () => ({
  Image: 'Image', Text: 'Text', TextInput: 'TextInput', TouchableOpacity: 'TouchableOpacity', View: 'View',
  StyleSheet: { create: (styles: any) => styles },
  Keyboard: { dismiss: jest.fn() },
}));

jest.mock('../components/CachedImage', () => ({ CachedImage: 'CachedImage' }));

jest.mock('@expo/vector-icons/MaterialIcons', () => 'MaterialIcons');

function childrenOf(element: any): any[] {
  return React.Children.toArray(element?.props?.children);
}

function collect(element: any, type: string): any[] {
  if (!element || typeof element !== 'object') return [];
  const own = element.type === type ? [element] : [];
  return own.concat(childrenOf(element).flatMap((child) => collect(child, type)));
}

const inputProps = { inputHeight: 44, onInputHeightChange: jest.fn(), onInputChange: jest.fn(), pressIn: jest.fn(), pressMove: jest.fn(), pressOut: jest.fn() };

const message = { uuid: 'v', type: 'audio' as const, content: '[语音消息]', isUser: true, durationMs: 15000, sendStatus: 'waiting' as const };

describe('voice components', () => {
  it('routes the failed voice retry control to sending instead of playback and removes it after success', () => {
    const retry = jest.fn();
    const play = jest.fn();
    const item = MessageItem({ message: { ...message, sendStatus: 'failed' }, onRetryVoice: retry, onToggleVoicePlayback: play }) as React.ReactElement<Parameters<typeof VoiceBubble>[0]>;
    const failed = VoiceBubble(item.props);
    const button = collect(failed, 'TouchableOpacity').find((node) => node.props.accessibilityLabel === '重试发送语音');
    button.props.onPress();
    expect(retry).toHaveBeenCalledWith('v');
    expect(play).not.toHaveBeenCalled();
    for (const sendStatus of ['waiting', 'submitted'] as const) {
      const tree = VoiceBubble({ ...item.props, message: { ...message, sendStatus } });
      expect(collect(tree, 'TouchableOpacity').filter((node) => node.props.accessibilityLabel === '重试发送语音')).toHaveLength(0);
    }
  });
  it('renders a right-aligned waiting voice bubble with a disabled playback bubble', () => {
    const tree = VoiceBubble({ message, onPlay: jest.fn(), onRetry: jest.fn() }) as any;
    expect(tree.props.style).toEqual(expect.objectContaining({ justifyContent: 'flex-end' }));
    expect(tree.props.accessibilityLabel).toBe(`用户语音消息，15''，发送中`);
    expect(collect(tree, 'Text').map((node) => React.Children.toArray(node.props.children).join(''))).toContain(`15''`);
    expect(collect(tree, 'TouchableOpacity')).toHaveLength(1);
  });

  it('renders failed and playing placeholders', () => {
    const failed = VoiceBubble({ message: { ...message, sendStatus: 'failed' } }) as any;
    expect(collect(failed, 'Image')).toHaveLength(0);
    expect(collect(failed, 'MaterialIcons')[0].props).toMatchObject({ name: 'refresh', color: '#ffffff' });
    expect(collect(failed, 'TouchableOpacity')[0].props.style).toMatchObject({ borderRadius: 14, backgroundColor: '#D9363E' });
  });

  it.each(['idle', 'playing', 'loading', 'failed', 'unavailable'] as const)('uses the bubble itself for playback in %s state', (state) => {
    const play = jest.fn();
    const tree = VoiceBubble({ message: { ...message, sendStatus: 'submitted', audioPlayState: state === 'playing' ? 'playing' : 'idle', audioDownloadState: state === 'loading' ? 'loading' : state === 'failed' ? 'failed' : 'ready', audioAvailable: state !== 'unavailable' }, onPlay: play }) as any;
    const buttons = collect(tree, 'TouchableOpacity');
    expect(buttons).toHaveLength(1);
    expect(buttons[0].props.disabled).toBe(state === 'unavailable');
    expect(collect(buttons[0], 'Text')).toHaveLength(1);
    if (state !== 'unavailable') { buttons[0].props.onPress(); expect(play).toHaveBeenCalledTimes(1); }
    if (state === 'playing') expect(buttons[0].props.accessibilityLabel).toBe('停止播放语音');
  });

  it('switches between text and voice controls and hides text send in voice mode', () => {
    const text = VoiceInputBar({ ...inputProps, mode: 'text', inputText: 'hi', canSend: true, canSendImage: true, captureState: 'TextMode', onToggleMode: jest.fn(), onSendText: jest.fn(), onSendImage: jest.fn() }) as any;
    expect(collect(text, 'TextInput')).toHaveLength(1);
    const voice = VoiceInputBar({ ...inputProps, mode: 'voice', inputText: '', canSend: false, canSendImage: false, captureState: 'VoiceReady', onToggleMode: jest.fn(), onSendText: jest.fn(), onSendImage: jest.fn() }) as any;
    expect(collect(voice, 'TextInput')).toHaveLength(0);
    expect(collect(voice, 'Text').map((node) => React.Children.toArray(node.props.children).join(''))).toContain('按住说话');
  });
});


it('cycles the playback icon every 300ms, resets on stop and cleans up its timer', () => {
  jest.useFakeTimers();
  let root!: ReactTestRenderer;
  const render = (playing: boolean) => <VoiceBubble message={{ ...message, sendStatus: 'submitted', audioPlayState: playing ? 'playing' : 'idle' }} onPlay={jest.fn()} />;
  try {
    act(() => { root = create(render(false)); });
    const parts = () => root.root.findByProps({ testID: 'voice-audio-icon' }).children.length;
    expect(parts()).toBe(3);
    expect(jest.getTimerCount()).toBe(0);
    act(() => { root.update(render(true)); });
    expect(parts()).toBe(1);
    act(() => jest.advanceTimersByTime(299));
    expect(parts()).toBe(1);
    act(() => jest.advanceTimersByTime(1));
    expect(parts()).toBe(2);
    act(() => jest.advanceTimersByTime(300));
    expect(parts()).toBe(3);
    act(() => jest.advanceTimersByTime(300));
    expect(parts()).toBe(1);
    act(() => { root.update(render(false)); });
    expect(parts()).toBe(3);
    expect(jest.getTimerCount()).toBe(0);
    act(() => { root.update(render(true)); });
    expect(parts()).toBe(1);
  } finally {
    act(() => root?.unmount());
    expect(jest.getTimerCount()).toBe(0);
    jest.useRealTimers();
  }
});

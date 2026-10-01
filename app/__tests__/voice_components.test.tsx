import React from 'react';

jest.mock('react-native', () => ({
  Image: 'Image', Text: 'Text', TextInput: 'TextInput', TouchableOpacity: 'TouchableOpacity', View: 'View',
  StyleSheet: { create: (styles: any) => styles },
}));

import { VoiceBubble } from '../components/VoiceBubble';
import { VoiceInputBar } from '../components/VoiceInputBar';

function childrenOf(element: any): any[] {
  return React.Children.toArray(element?.props?.children);
}

function collect(element: any, type: string): any[] {
  if (!element || typeof element !== 'object') return [];
  const own = element.type === type ? [element] : [];
  return own.concat(childrenOf(element).flatMap((child) => collect(child, type)));
}

const message = { uuid: 'v', type: 'audio' as const, content: '[语音消息]', isUser: true, durationMs: 15000, sendStatus: 'waiting' as const };

describe('voice components', () => {
  it('renders a right-aligned waiting voice bubble with status, playback, and bubble order', () => {
    const tree = VoiceBubble({ message, onPlay: jest.fn(), onRetry: jest.fn() }) as any;
    expect(tree.props.style).toEqual(expect.objectContaining({ justifyContent: 'flex-end' }));
    expect(tree.props.accessibilityLabel).toBe(`用户语音消息，15''，播放`);
    expect(collect(tree, 'Text').map((node) => React.Children.toArray(node.props.children).join(''))).toContain(`15''`);
    expect(collect(tree, 'TouchableOpacity')).toHaveLength(2);
  });

  it('renders failed and playing placeholders', () => {
    const failed = VoiceBubble({ message: { ...message, sendStatus: 'failed' } }) as any;
    expect(collect(failed, 'Image')).toHaveLength(1);
    const playing = VoiceBubble({ message: { ...message, sendStatus: 'submitted', audioPlayState: 'playing' } }) as any;
    expect(collect(playing, 'Text').map((node) => React.Children.toArray(node.props.children).join(''))).toContain('■');
  });

  it('renders loading, retryable failure, and unavailable failure states', () => {
    const loading = VoiceBubble({ message: { ...message, sendStatus: 'submitted', audioDownloadState: 'loading' } }) as any;
    expect(collect(loading, 'Text').map((node) => React.Children.toArray(node.props.children).join(''))).toContain('…');

    const failed = VoiceBubble({ message: { ...message, sendStatus: 'submitted', audioDownloadState: 'failed' } }) as any;
    const failedControls = collect(failed, 'TouchableOpacity');
    expect(collect(failed, 'Text').map((node) => React.Children.toArray(node.props.children).join(''))).toContain('!');
    expect(failedControls[1].props.accessibilityLabel).toBe('语音加载失败，点击重试');

    const unavailable = VoiceBubble({ message: { ...message, sendStatus: 'submitted', audioAvailable: false } }) as any;
    const unavailableControls = collect(unavailable, 'TouchableOpacity');
    expect(collect(unavailable, 'Text').map((node) => React.Children.toArray(node.props.children).join(''))).toContain('!');
    expect(unavailableControls[1].props.disabled).toBe(false);
    expect(unavailableControls[1].props.accessibilityLabel).toBe('语音不可用，无法重试');
    expect(unavailable.props.accessibilityLabel).toContain('语音不可用，无法重试');
  });

  it('switches between text and voice controls and hides text send in voice mode', () => {
    const text = VoiceInputBar({ mode: 'text', inputText: 'hi', canSend: true, canSendImage: true, captureState: 'TextMode', onToggleMode: jest.fn(), onSendText: jest.fn(), onSendImage: jest.fn() }) as any;
    expect(collect(text, 'TextInput')).toHaveLength(1);
    const voice = VoiceInputBar({ mode: 'voice', inputText: '', canSend: false, canSendImage: false, captureState: 'VoiceReady', onToggleMode: jest.fn(), onSendText: jest.fn(), onSendImage: jest.fn() }) as any;
    expect(collect(voice, 'TextInput')).toHaveLength(0);
    expect(collect(voice, 'Text').map((node) => React.Children.toArray(node.props.children).join(''))).toContain('按住说话');
  });
});

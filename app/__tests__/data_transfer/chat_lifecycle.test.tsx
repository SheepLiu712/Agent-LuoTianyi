import React from 'react';
import { act, create, type ReactTestRenderer } from 'react-test-renderer';
import { useChatLogic } from '../../features/chat/useChatLogic';
import { NetworkClient } from '../../features/chat/connection/network_client';
import { MessageProcessor } from '../../features/chat/message_processor';

jest.mock('react-native', () => ({}));
jest.mock('expo-image-picker', () => ({}));
jest.mock('expo-file-system/legacy', () => ({}));
jest.mock('../../shared/character/live2d_helper', () => ({ setExpression: jest.fn() }));
jest.mock('../../features/chat/useVoiceInput', () => {
  const voiceInput = { onUploadStatus: jest.fn() };
  return { useVoiceInput: jest.fn(() => voiceInput) };
});
jest.mock('../../features/chat/connection/network_client', () => ({ NetworkClient: jest.fn() }));
jest.mock('../../features/chat/message_processor', () => ({ MessageProcessor: jest.fn() }));
jest.mock('../../features/chat/voice_playback_manager', () => ({ voicePlaybackManager: {
  initialize: jest.fn().mockResolvedValue(undefined), stop: jest.fn().mockResolvedValue(undefined),
} }));

let root: ReactTestRenderer;
let chat: ReturnType<typeof useChatLogic>;
const network = { connectWs: jest.fn(), disconnectWs: jest.fn(), reconnectWs: jest.fn() };
const processor = { queueLength: jest.fn(), onServerAudioFinished: jest.fn(), stopLocalTts: jest.fn(), stop: jest.fn() };
const webview = { current: { injectJavaScript: jest.fn() } } as any;
function Harness() { chat = useChatLogic(webview, 'current', 'token', 'luotianyi'); return null; }
beforeEach(async () => {
  jest.clearAllMocks();
  network.reconnectWs.mockResolvedValue(true);
  processor.queueLength.mockReturnValue(0);
  processor.stopLocalTts.mockResolvedValue(undefined);
  jest.mocked(NetworkClient).mockImplementation(() => network as any);
  jest.mocked(MessageProcessor).mockImplementation(() => processor as any);
  await act(async () => { root = create(<Harness />); });
});
afterEach(async () => { await act(async () => root.unmount()); });

it('受控暂停停止物理连接和自动重连，迁移结束才可resume', async () => {
  expect(network.connectWs).toHaveBeenCalledTimes(1);
  await act(async () => { expect(chat.pauseChatForDataTransfer()).toBe(true); });
  expect(network.disconnectWs).toHaveBeenCalledTimes(1);
  expect(await chat.resumeChat()).toBe(false);
  expect(network.reconnectWs).not.toHaveBeenCalled();
  await act(async () => {
    chat.setInputText('late input');
    await chat.handleSendImage();
    chat.handleWebViewMessage({ nativeEvent: { data: JSON.stringify({ type: 'touch' }) } });
  });
  expect(chat.inputText).toBe('');
  await expect(chat.callSwitch.prepare('call-1', 'luotianyi')).rejects.toThrow('CHAT_PAUSED_FOR_DATA_TRANSFER');
  await act(async () => { expect(await chat.resumeChatAfterDataTransfer(false)).toBe(true); });
  expect(network.reconnectWs).toHaveBeenCalledWith('current', 'token', 'luotianyi', expect.any(Object));
  expect(chat.historyRevision).toBe(0);
});

it('重置历史分页版本并拒收迁移前请求晚到的数据', async () => {
  const staleHistory = chat.addHistoryMessage;
  await act(async () => { staleHistory([{ uuid: 'old', isUser: true, type: 'text', content: 'previous' }]); });
  expect(chat.messages).toHaveLength(1);
  await act(async () => {
    expect(chat.pauseChatForDataTransfer()).toBe(true);
    await chat.resumeChatAfterDataTransfer(true);
  });
  expect(chat.historyRevision).toBe(1);
  expect(chat.messages).toEqual([]);
  await act(async () => { staleHistory([{ uuid: 'old', isUser: true, type: 'text', content: 'stale' }]); });
  expect(chat.messages).toEqual([]);
  await act(async () => { chat.addHistoryMessage([{ uuid: 'new', isUser: true, type: 'text', content: 'imported' }]); });
  expect(chat.messages.map(message => message.uuid)).toEqual(['new']);
});

it('发送队列未结束时不暂停连接，重连失败返回false供页面重试', async () => {
  processor.queueLength.mockReturnValue(1);
  expect(chat.pauseChatForDataTransfer()).toBe(false);
  expect(network.disconnectWs).not.toHaveBeenCalled();
  processor.queueLength.mockReturnValue(0);
  network.reconnectWs.mockResolvedValueOnce(false);
  await act(async () => {
    expect(chat.pauseChatForDataTransfer()).toBe(true);
    expect(await chat.resumeChatAfterDataTransfer(false)).toBe(false);
  });
});

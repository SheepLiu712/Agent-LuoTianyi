import { createSystemChatMessage } from '../types/chat';


test('system messages are distinct from user and agent bubbles', () => {
  expect(createSystemChatMessage('WebSocket 错误', 'system-1', 123)).toEqual({
    uuid: 'system-1',
    type: 'system',
    content: 'WebSocket 错误',
    isUser: false,
    timestamp: 123,
  });
});

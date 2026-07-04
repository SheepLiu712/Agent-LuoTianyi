/**
 * AgentBinder 单元测试
 * 测试中介者模式是否正确转发 send/emit 调用。
 */
import { AgentBinder, BinderSendCallbacks, BinderUiCallbacks } from '../utils/binder';
import { AgentMessagePayload, SendStatus } from '../types/chat';

describe('AgentBinder', () => {
  let sendCallbacks: jest.Mocked<BinderSendCallbacks>;
  let uiCallbacks: jest.Mocked<BinderUiCallbacks>;
  let binder: AgentBinder;

  beforeEach(() => {
    sendCallbacks = {
      sendText: jest.fn(),
      sendImage: jest.fn(),
      sendProactiveText: jest.fn(),
      sendTouch: jest.fn(),
      sendTyping: jest.fn(),
      sendImageSelecting: jest.fn(),
      sendImageSelectingCancel: jest.fn(),
      playLocalTts: jest.fn().mockResolvedValue(true),
      stopLocalTts: jest.fn().mockResolvedValue(undefined),
    };

    uiCallbacks = {
      onAgentMessage: jest.fn(),
      onMessageStatus: jest.fn(),
      onAgentThinking: jest.fn(),
      onLocalTtsState: jest.fn(),
      onErrorText: jest.fn(),
    };

    binder = new AgentBinder(sendCallbacks, uiCallbacks);
  });

  describe('send methods', () => {
    it('sendText should delegate', async () => {
      await binder.sendText('uuid-1', 'hello');
      expect(sendCallbacks.sendText).toHaveBeenCalledWith('uuid-1', 'hello');
    });

    it('sendImage should delegate', async () => {
      await binder.sendImage('uuid-2', '/path/img.jpg', 'image/jpeg');
      expect(sendCallbacks.sendImage).toHaveBeenCalledWith('uuid-2', '/path/img.jpg', 'image/jpeg');
    });

    it('sendTyping should delegate', async () => {
      await binder.sendTyping(42);
      expect(sendCallbacks.sendTyping).toHaveBeenCalledWith(42);
    });

    it('playLocalTts should delegate', async () => {
      const result = await binder.playLocalTts('uuid-3');
      expect(sendCallbacks.playLocalTts).toHaveBeenCalledWith('uuid-3');
      expect(result).toBe(true);
    });

    it('stopLocalTts should delegate', async () => {
      await binder.stopLocalTts();
      expect(sendCallbacks.stopLocalTts).toHaveBeenCalled();
    });

    it('sendProactiveText should delegate', async () => {
      await binder.sendProactiveText('uuid-p', 'proactive hello');
      expect(sendCallbacks.sendProactiveText).toHaveBeenCalledWith('uuid-p', 'proactive hello');
    });

    it('sendTouch should delegate', async () => {
      await binder.sendTouch('头', { count_10s: 3, count_30s: 10 });
      expect(sendCallbacks.sendTouch).toHaveBeenCalledWith('头', { count_10s: 3, count_30s: 10 });
    });

    it('sendTouch should work without clickFrequency', async () => {
      await binder.sendTouch('辫子');
      expect(sendCallbacks.sendTouch).toHaveBeenCalledWith('辫子', undefined);
    });

  });

  describe('emit methods', () => {
    it('emitAgentMessage should delegate', () => {
      const payload: AgentMessagePayload = { uuid: 'a1', text: 'hi' };
      binder.emitAgentMessage(payload);
      expect(uiCallbacks.onAgentMessage).toHaveBeenCalledWith(payload);
    });

    it('emitMessageStatus should delegate', () => {
      binder.emitMessageStatus('uuid-4', 'submitted');
      expect(uiCallbacks.onMessageStatus).toHaveBeenCalledWith('uuid-4', 'submitted');
    });

    it('emitAgentThinking should delegate', () => {
      binder.emitAgentThinking(true);
      expect(uiCallbacks.onAgentThinking).toHaveBeenCalledWith(true);
    });

    it('emitLocalTtsState should delegate', () => {
      binder.emitLocalTtsState('finished', 'uuid-5');
      expect(uiCallbacks.onLocalTtsState).toHaveBeenCalledWith('finished', 'uuid-5');
    });

    it('emitErrorText should delegate', () => {
      binder.emitErrorText('something went wrong');
      expect(uiCallbacks.onErrorText).toHaveBeenCalledWith('something went wrong');
    });
  });
});

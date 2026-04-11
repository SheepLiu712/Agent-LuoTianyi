import { AgentMessagePayload, SendStatus } from '../types/chat';

export interface BinderSendCallbacks {
  sendText: (uuid: string, text: string) => Promise<void>;
  sendImage: (uuid: string, imageUri: string, mimeType: string) => Promise<void>;
  sendTyping: (textLength: number) => Promise<void>;
  playLocalTts: (convUuid: string) => Promise<boolean>;
  stopLocalTts: () => Promise<void>;
}

export interface BinderUiCallbacks {
  onAgentMessage: (payload: AgentMessagePayload) => void;
  onMessageStatus: (uuid: string, status: SendStatus) => void;
  onAgentThinking: (thinking: boolean) => void;
  onLocalTtsState: (event: 'finished' | 'stopped', convUuid: string) => void;
  onErrorText: (text: string) => void;
}

export class AgentBinder {
  private readonly sendCallbacks: BinderSendCallbacks;
  private readonly uiCallbacks: BinderUiCallbacks;

  constructor(sendCallbacks: BinderSendCallbacks, uiCallbacks: BinderUiCallbacks) {
    this.sendCallbacks = sendCallbacks;
    this.uiCallbacks = uiCallbacks;
  }

  sendText(uuid: string, text: string) {
    return this.sendCallbacks.sendText(uuid, text);
  }

  sendImage(uuid: string, imageUri: string, mimeType: string) {
    return this.sendCallbacks.sendImage(uuid, imageUri, mimeType);
  }

  sendTyping(textLength: number) {
    return this.sendCallbacks.sendTyping(textLength);
  }

  playLocalTts(convUuid: string) {
    return this.sendCallbacks.playLocalTts(convUuid);
  }

  stopLocalTts() {
    return this.sendCallbacks.stopLocalTts();
  }

  emitAgentMessage(payload: AgentMessagePayload) {
    this.uiCallbacks.onAgentMessage(payload);
  }

  emitMessageStatus(uuid: string, status: SendStatus) {
    this.uiCallbacks.onMessageStatus(uuid, status);
  }

  emitAgentThinking(thinking: boolean) {
    this.uiCallbacks.onAgentThinking(thinking);
  }

  emitLocalTtsState(event: 'finished' | 'stopped', convUuid: string) {
    this.uiCallbacks.onLocalTtsState(event, convUuid);
  }

  emitErrorText(text: string) {
    this.uiCallbacks.onErrorText(text);
  }
}

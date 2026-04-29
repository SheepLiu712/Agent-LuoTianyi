export type MessageType = 'text' | 'image';
export type SendStatus = 'waiting' | 'submitted' | 'failed';
export type AudioPlayState = 'idle' | 'playing';

export interface ChatMessage {
  uuid: string;
  type: MessageType;
  content: string;
  isUser: boolean;
  timestamp?: number;
  sendStatus?: SendStatus;
  audioAvailable?: boolean;
  audioLocalUri?: string;
  audioPlayState?: AudioPlayState;
}

export interface AgentMessagePayload {
  uuid?: string;
  text?: string;
  audio?: string | null;
  expression?: string | null;
  is_final_package?: boolean;
}

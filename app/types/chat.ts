export type MessageType = 'text' | 'image' | 'audio' | 'sing' | 'system';
export type SendStatus = 'waiting' | 'submitted' | 'failed';
export type AudioPlayState = 'idle' | 'playing';
export type AudioDownloadState = 'idle' | 'loading' | 'ready' | 'failed';
export type VoiceCaptureState = 'TextMode' | 'VoiceReady' | 'PermissionPrompt' | 'Starting' | 'Recording' | 'CancelZone' | 'Uploading' | 'Sent' | 'Failed';

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
  durationMs?: number;
  audioDownloadState?: AudioDownloadState;
}

export interface AgentMessagePayload {
  packet_sequence?: number | null;
  uuid?: string;
  text?: string;
  audio?: string | null;
  expression?: string | null;
  is_final_package?: boolean;
  audio_error?: boolean;
  error_code?: string | null;
  display_in_chat?: boolean;
  is_ephemeral?: boolean;
}

export function createSystemChatMessage(
  text: string,
  uuid: string,
  timestamp = Date.now(),
): ChatMessage {
  return {
    uuid,
    type: 'system',
    content: text,
    isUser: false,
    timestamp,
  };
}

export const AudioStreamType = {
  CHAT: 'chat',
  CALL: 'call',
} as const;

export type AudioStreamType = (typeof AudioStreamType)[keyof typeof AudioStreamType];

export interface Live2DAudioPacket {
  stream_type: AudioStreamType;
  audio_id: string;
  audio: string;
  is_final: boolean;
  response_id?: string;
}

export interface Live2DAudioStopCommand {
  stream_type: AudioStreamType;
  audio_ids?: string[];
  response_id?: string;
  reason: string;
}

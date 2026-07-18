export interface PcmChunk {
  audio: string;
  seq: number;
}

export interface PcmRecordingError {
  code: string;
  message: string;
}

export type PcmRecorderModuleEvents = {
  pcmChunk: (chunk: PcmChunk) => void;
  recordingError: (error: PcmRecordingError) => void;
};

/** Adapter-wire representation of one call.v1 PCM16 mono audio frame. */
export interface WireAudioFrame {
  version: number;
  route: number;
  flags: number;
  streamId: number;
  seq: number;
  payload: Uint8Array;
}

/** A replaceable encoding for one call.v1 audio frame. */
export interface AudioFrameCodec<Encoded> {
  encode(frame: WireAudioFrame): Encoded;
  decode(encoded: Encoded): WireAudioFrame;
}

export type AudioFrameCodecErrorCode =
  | 'HEADER_TRUNCATED'
  | 'UNSUPPORTED_VERSION'
  | 'INVALID_ROUTE'
  | 'UNSUPPORTED_FLAGS'
  | 'INVALID_SEQ'
  | 'FIELD_OUT_OF_RANGE'
  | 'INVALID_FIELD_TYPE'
  | 'PAYLOAD_LENGTH_MISMATCH'
  | 'PAYLOAD_TOO_LARGE'
  | 'EMPTY_PAYLOAD'
  | 'PCM_ALIGNMENT_ERROR';

/** A codec validation failure with a stable cross-client error code. */
export class AudioFrameCodecError extends Error {
  readonly code: AudioFrameCodecErrorCode;

  constructor(code: AudioFrameCodecErrorCode) {
    super(code);
    this.name = 'AudioFrameCodecError';
    this.code = code;
  }
}

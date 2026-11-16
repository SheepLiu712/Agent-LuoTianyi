import {
  AudioFrameCodecError,
  type AudioFrameCodec,
  type AudioFrameCodecErrorCode,
  type WireAudioFrame,
} from './types';

const HEADER_SIZE = 15;
const VERSION = 1;
const CHAT_ROUTE = 1;
const CALL_ROUTE = 2;
const FINAL_FLAG = 1;
const ALLOWED_FLAGS_MASK = FINAL_FLAG;
const UINT8_MAX = 0xff;
const UINT32_MAX = 0xffffffff;
const MAX_PAYLOAD_BYTES = 16_384;

/** Strict codec for the fixed-layout call.v1 binary audio frame. */
export class BinaryAudioFrameCodec implements AudioFrameCodec<Uint8Array> {
  encode(frame: WireAudioFrame): Uint8Array {
    this.validateFrame(frame);

    const encoded = new Uint8Array(HEADER_SIZE + frame.payload.length);
    const header = new DataView(encoded.buffer, encoded.byteOffset, HEADER_SIZE);
    header.setUint8(0, frame.version);
    header.setUint8(1, frame.route);
    header.setUint8(2, frame.flags);
    header.setUint32(3, frame.streamId, false);
    header.setUint32(7, frame.seq, false);
    header.setUint32(11, frame.payload.length, false);
    encoded.set(frame.payload, HEADER_SIZE);
    return encoded;
  }

  decode(encoded: Uint8Array): WireAudioFrame {
    if (!(encoded instanceof Uint8Array)) {
      throwCodecError('INVALID_FIELD_TYPE');
    }
    if (encoded.length < HEADER_SIZE) {
      throwCodecError('HEADER_TRUNCATED');
    }

    const header = new DataView(encoded.buffer, encoded.byteOffset, HEADER_SIZE);
    const version = header.getUint8(0);
    const route = header.getUint8(1);
    const flags = header.getUint8(2);
    const streamId = header.getUint32(3, false);
    const seq = header.getUint32(7, false);
    const payloadLength = header.getUint32(11, false);
    const actualPayloadLength = encoded.length - HEADER_SIZE;

    if (version !== VERSION) {
      throwCodecError('UNSUPPORTED_VERSION');
    }
    if (route !== CHAT_ROUTE && route !== CALL_ROUTE) {
      throwCodecError('INVALID_ROUTE');
    }
    if ((flags & ~ALLOWED_FLAGS_MASK) !== 0) {
      throwCodecError('UNSUPPORTED_FLAGS');
    }
    if (seq === 0) {
      throwCodecError('INVALID_SEQ');
    }
    if (payloadLength !== actualPayloadLength) {
      throwCodecError('PAYLOAD_LENGTH_MISMATCH');
    }
    this.validatePayloadLength(actualPayloadLength);
    const payload = encoded.slice(HEADER_SIZE);

    return { version, route, flags, streamId, seq, payload };
  }

  private validateFrame(frame: WireAudioFrame): void {
    if (frame === null || typeof frame !== 'object') {
      throwCodecError('INVALID_FIELD_TYPE');
    }

    const fields = [frame.version, frame.route, frame.flags, frame.streamId, frame.seq];
    if (!fields.every((field) => typeof field === 'number' && Number.isInteger(field))) {
      throwCodecError('INVALID_FIELD_TYPE');
    }
    if (!(frame.payload instanceof Uint8Array)) {
      throwCodecError('INVALID_FIELD_TYPE');
    }
    if (
      frame.version < 0 ||
      frame.version > UINT8_MAX ||
      frame.route < 0 ||
      frame.route > UINT8_MAX ||
      frame.flags < 0 ||
      frame.flags > UINT8_MAX ||
      frame.streamId < 0 ||
      frame.streamId > UINT32_MAX ||
      frame.seq < 0 ||
      frame.seq > UINT32_MAX
    ) {
      throwCodecError('FIELD_OUT_OF_RANGE');
    }
    if (frame.version !== VERSION) {
      throwCodecError('UNSUPPORTED_VERSION');
    }
    if (frame.route !== CHAT_ROUTE && frame.route !== CALL_ROUTE) {
      throwCodecError('INVALID_ROUTE');
    }
    if ((frame.flags & ~ALLOWED_FLAGS_MASK) !== 0) {
      throwCodecError('UNSUPPORTED_FLAGS');
    }
    if (frame.seq === 0) {
      throwCodecError('INVALID_SEQ');
    }
    this.validatePayload(frame.payload);
  }

  private validatePayload(payload: Uint8Array): void {
    this.validatePayloadLength(payload.length);
  }

  private validatePayloadLength(payloadLength: number): void {
    if (payloadLength > MAX_PAYLOAD_BYTES) {
      throwCodecError('PAYLOAD_TOO_LARGE');
    }
    if (payloadLength === 0) {
      throwCodecError('EMPTY_PAYLOAD');
    }
    if (payloadLength % 2 !== 0) {
      throwCodecError('PCM_ALIGNMENT_ERROR');
    }
  }
}

function throwCodecError(code: AudioFrameCodecErrorCode): never {
  throw new AudioFrameCodecError(code);
}

export { AudioFrameCodecError, type AudioFrameCodec, type WireAudioFrame } from './types';

import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import {
  AudioFrameCodecError,
  BinaryAudioFrameCodec,
  type AudioFrameCodec,
  type WireAudioFrame,
} from '../utils/call_protocol/audio_codec';

type ContractFrame = {
  version: number;
  route: 'CHAT' | 'CALL';
  flags: readonly ('FINAL')[];
  stream_id: number;
  seq: number;
  payload_hex?: string;
  payload_pattern?: { repeat_hex: string; count: number };
};

type FixtureCase = {
  id: string;
  operation?: 'encode' | 'decode';
  frame?: ContractFrame;
  encoded_hex?: string;
  encoded_hex_pattern?: { prefix: string; repeat_hex: string; count: number };
  error?: string;
};

type AudioFrameContract = {
  constants: {
    routes: Record<ContractFrame['route'], number>;
    flags: { FINAL: number };
  };
  valid: FixtureCase[];
  invalid: FixtureCase[];
};

const fixturePath = resolve(__dirname, '../../contracts/call_v1/fixtures/audio_frames.json');
const contract = JSON.parse(readFileSync(fixturePath, 'utf8')) as AudioFrameContract;

function bytesFromHex(hex: string): Uint8Array {
  if (hex.length % 2 !== 0) {
    throw new Error('Expected an even-length fixture hex string');
  }
  const bytes = new Uint8Array(hex.length / 2);
  for (let index = 0; index < bytes.length; index += 1) {
    bytes[index] = Number.parseInt(hex.slice(index * 2, index * 2 + 2), 16);
  }
  return bytes;
}

function hexFromPattern(pattern: NonNullable<FixtureCase['encoded_hex_pattern']>): string {
  return pattern.prefix + pattern.repeat_hex.repeat(pattern.count);
}

function encodedHex(caseData: FixtureCase): string {
  return caseData.encoded_hex ?? hexFromPattern(caseData.encoded_hex_pattern!);
}

function payload(frame: ContractFrame): Uint8Array {
  return bytesFromHex(frame.payload_hex ?? frame.payload_pattern!.repeat_hex.repeat(frame.payload_pattern!.count));
}

function frameFromFixture(frame: ContractFrame): WireAudioFrame {
  return {
    version: frame.version,
    route: contract.constants.routes[frame.route],
    flags: frame.flags.reduce((value, flag) => value | contract.constants.flags[flag], 0),
    streamId: frame.stream_id,
    seq: frame.seq,
    payload: payload(frame),
  };
}

function expectCodecError(action: () => unknown, code: string): void {
  try {
    action();
    throw new Error(`Expected ${code}`);
  } catch (error) {
    expect(error).toBeInstanceOf(AudioFrameCodecError);
    expect((error as AudioFrameCodecError).code).toBe(code);
    expect((error as Error).message).toBe(code);
  }
}

describe('call.v1 binary audio codec', () => {
  it.each(contract.valid)('encodes $id to its exact golden bytes and round-trips', (caseData) => {
    const codec = new BinaryAudioFrameCodec();
    const frame = frameFromFixture(caseData.frame!);
    const expected = bytesFromHex(encodedHex(caseData));

    expect(codec.encode(frame)).toEqual(expected);
    expect(codec.decode(expected)).toEqual(frame);
  });

  it.each(contract.invalid.filter((caseData) => caseData.operation === 'decode'))(
    'rejects invalid decode fixture $id with its stable code',
    (caseData) => {
      expectCodecError(() => new BinaryAudioFrameCodec().decode(bytesFromHex(encodedHex(caseData))), caseData.error!);
    },
  );

  it.each(contract.invalid.filter((caseData) => caseData.operation === 'encode'))(
    'rejects invalid encode fixture $id with its stable code',
    (caseData) => {
      expectCodecError(() => new BinaryAudioFrameCodec().encode(frameFromFixture(caseData.frame!)), caseData.error!);
    },
  );

  it.each([true, '1', 1.5, Number.NaN, Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY])(
    'rejects non-integer scalar field value %p',
    (value) => {
      const frame = {
        version: 1,
        route: 2,
        flags: 0,
        streamId: 1,
        seq: 1,
        payload: new Uint8Array([0, 1]),
      } as WireAudioFrame;

      for (const field of ['version', 'route', 'flags', 'streamId', 'seq'] as const) {
        expectCodecError(
          () => new BinaryAudioFrameCodec().encode({ ...frame, [field]: value } as WireAudioFrame),
          'INVALID_FIELD_TYPE',
        );
      }
    },
  );

  it.each([-1, 256])('rejects out-of-range uint8 header values', (value) => {
    expectCodecError(
      () => new BinaryAudioFrameCodec().encode({ ...validFrame(), version: value }),
      'FIELD_OUT_OF_RANGE',
    );
  });

  it.each([-1, 4_294_967_296])('rejects out-of-range uint32 values', (value) => {
    for (const field of ['streamId', 'seq'] as const) {
      expectCodecError(
        () => new BinaryAudioFrameCodec().encode({ ...validFrame(), [field]: value }),
        'FIELD_OUT_OF_RANGE',
      );
    }
  });

  it('rejects non-byte payloads and non-byte encoded input', () => {
    expectCodecError(
      () => new BinaryAudioFrameCodec().encode({ ...validFrame(), payload: '0001' } as unknown as WireAudioFrame),
      'INVALID_FIELD_TYPE',
    );
    expectCodecError(() => new BinaryAudioFrameCodec().decode('not bytes' as unknown as Uint8Array), 'INVALID_FIELD_TYPE');
  });

  it('rejects trailing bytes because the declared payload length must match exactly', () => {
    const trailing = bytesFromHex('01020000000001000000010000000200010000');
    expectCodecError(() => new BinaryAudioFrameCodec().decode(trailing), 'PAYLOAD_LENGTH_MISMATCH');
  });

  it.each([
    {
      name: 'unsupported version',
      header: '020200000000010000000100000002',
      error: 'UNSUPPORTED_VERSION',
    },
    {
      name: 'payload over limit',
      header: '010200000000010000000100010000',
      error: 'PAYLOAD_TOO_LARGE',
    },
  ])('rejects a large $name input before copying its payload', ({ header, error }) => {
    const encoded = new Uint8Array(15 + 65_536);
    encoded.set(bytesFromHex(header));
    const sliceSpy = jest.spyOn(encoded, 'slice');

    expectCodecError(() => new BinaryAudioFrameCodec().decode(encoded), error);
    expect(sliceSpy).not.toHaveBeenCalled();
  });

  it('honors a Uint8Array view offset and gives decoded payload independent ownership', () => {
    const golden = bytesFromHex('0102000000000100000001000000020001');
    const backing = new Uint8Array(golden.length + 8);
    backing.set(golden, 4);
    const offsetView = backing.subarray(4, 4 + golden.length);

    const decoded = new BinaryAudioFrameCodec().decode(offsetView);
    offsetView[offsetView.length - 1] = 0xff;

    expect(decoded.payload).toEqual(new Uint8Array([0, 1]));
  });

  it('gives encoded bytes independent ownership from the source payload', () => {
    const frame = validFrame();
    const encoded = new BinaryAudioFrameCodec().encode(frame);

    frame.payload[0] = 0xff;

    expect(encoded).toEqual(bytesFromHex('0102000000000100000001000000020001'));
  });

  it('keeps the future alternate-encoding seam narrow and locally replaceable', () => {
    class FakeCodec implements AudioFrameCodec<string> {
      encode(frame: WireAudioFrame): string {
        return frame.payload.join(',');
      }

      decode(encoded: string): WireAudioFrame {
        return { ...validFrame(), payload: new Uint8Array(encoded.split(',').map(Number)) };
      }
    }

    const codec: AudioFrameCodec<string> = new FakeCodec();
    expect(codec.decode(codec.encode(validFrame())).payload).toEqual(new Uint8Array([0, 1]));
  });
});

function validFrame(): WireAudioFrame {
  return { version: 1, route: 2, flags: 0, streamId: 1, seq: 1, payload: new Uint8Array([0, 1]) };
}

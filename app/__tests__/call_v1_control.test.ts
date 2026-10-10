import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import {
  ControlMessageError,
  decodeControlBytes,
  decodeControlText,
  encodeControlMessage,
  type ControlContext,
  type ControlMessage,
} from '../utils/call_protocol/control';

type ValidCase = ControlContext & { id: string; raw: string; message: ControlMessage };
type InvalidCase = ControlContext & {
  id: string;
  raw?: string;
  raw_hex?: string;
  raw_pattern?: { prefix: string; repeat: string; count: number; suffix: string };
  expected: { error: string; path: string };
};
type Contract = { valid: ValidCase[]; invalid: InvalidCase[] };

const fixturePath = resolve(__dirname, '../../contracts/call_v1/fixtures/control_messages.json');
const contract = JSON.parse(readFileSync(fixturePath, 'utf8')) as Contract;

function context(caseData: ControlContext): ControlContext {
  return { transport: caseData.transport, direction: caseData.direction };
}

function rawText(caseData: InvalidCase): string {
  if (caseData.raw !== undefined) return caseData.raw;
  const pattern = caseData.raw_pattern!;
  return pattern.prefix + pattern.repeat.repeat(pattern.count) + pattern.suffix;
}

function bytesFromHex(hex: string): Uint8Array {
  return new Uint8Array(hex.match(/../g)!.map((byte) => Number.parseInt(byte, 16)));
}

function expectControlError(action: () => unknown, code: string, path: string): void {
  try {
    action();
    throw new Error(`Expected ${code} at ${path}`);
  } catch (error) {
    expect(error).toBeInstanceOf(ControlMessageError);
    expect((error as ControlMessageError).code).toBe(code);
    expect((error as ControlMessageError).path).toBe(path);
  }
}

describe('call.v1 control protocol', () => {
  it.each(contract.valid)('decodes and canonically encodes valid fixture $id', (caseData) => {
    const decoded = decodeControlText(caseData.raw, context(caseData));

    expect(decoded).toEqual(caseData.message);
    expect(encodeControlMessage(decoded, context(caseData))).toBe(caseData.raw);
  });

  it.each(contract.invalid.filter((caseData) => caseData.raw_hex === undefined))(
    'rejects invalid text fixture $id with its stable error and path',
    (caseData) => {
      expectControlError(
        () => decodeControlText(rawText(caseData), context(caseData)),
        caseData.expected.error,
        caseData.expected.path,
      );
    },
  );

  it.each(contract.invalid.filter((caseData) => caseData.raw_hex !== undefined))(
    'rejects invalid byte fixture $id with its stable error and path',
    (caseData) => {
      expectControlError(
        () => decodeControlBytes(bytesFromHex(caseData.raw_hex!), context(caseData)),
        caseData.expected.error,
        caseData.expected.path,
      );
    },
  );

  it('rejects duplicate nested keys after Unicode escape decoding', () => {
    const raw =
      '{"protocol":"call.v1","type":"call.start","seq":1,"client_request_id":"request","character_id":"luotianyi","audio":{"encoding":"pcm_s16le","sample_rate":16000,"\\u0073ample_rate":16000,"channels":1}}';

    expectControlError(
      () => decodeControlText(raw, { transport: 'call_ws', direction: 'client_to_server' }),
      'DUPLICATE_FIELD',
      '$.audio.sample_rate',
    );
  });

  it('does not mutate Object.prototype for hostile field names', () => {
    const raw =
      '{"protocol":"call.v1","type":"ack","call_id":"606ec5e6-a330-4e6c-b07a-8432a5716c8f","ack_seq":0,"__proto__":{"polluted":true}}';

    expectControlError(
      () => decodeControlText(raw, { transport: 'call_ws', direction: 'client_to_server' }),
      'UNKNOWN_FIELD',
      '$.__proto__',
    );
    expect(({} as { polluted?: boolean }).polluted).toBeUndefined();
  });

  it('rejects malformed input without leaking native range or syntax errors', () => {
    const deep = '['.repeat(2000) + ']'.repeat(2000);
    expectControlError(
      () => decodeControlText(deep, { transport: 'call_ws', direction: 'client_to_server' }),
      'TOP_LEVEL_NOT_OBJECT',
      '$',
    );
  });

  it('canonicalizes top-level and nested encoder field order', () => {
    const message = {
      audio: { channels: 1, sample_rate: 16000, encoding: 'pcm_s16le' },
      character_id: 'luotianyi',
      client_request_id: 'request',
      seq: 1,
      type: 'call.start',
      protocol: 'call.v1',
    } as ControlMessage;

    expect(encodeControlMessage(message, { transport: 'call_ws', direction: 'client_to_server' })).toBe(
      '{"protocol":"call.v1","type":"call.start","seq":1,"client_request_id":"request","character_id":"luotianyi","audio":{"encoding":"pcm_s16le","sample_rate":16000,"channels":1}}',
    );
  });

  it.each([
    ['NUL', '\u0000', 'INVALID_FIELD_VALUE'],
    ['replacement character', '\ufffd', 'INVALID_FIELD_VALUE'],
    ['lone surrogate', '\ud800', 'BAD_JSON'],
  ])('rejects encoder %s strings with a stable error', (_name, value, code) => {
    const message = {
      protocol: 'call.v1',
      type: 'error',
      code: 'BAD_VALUE',
      message: value,
      retryable: false,
    } as ControlMessage;

    expectControlError(
      () => encodeControlMessage(message, { transport: 'call_ws', direction: 'client_to_server' }),
      code,
      '$.message',
    );
  });

  it.each([
    ['NaN', Number.NaN, 'INVALID_FIELD_TYPE'],
    ['positive infinity', Number.POSITIVE_INFINITY, 'INVALID_FIELD_TYPE'],
    ['negative infinity', Number.NEGATIVE_INFINITY, 'INVALID_FIELD_TYPE'],
    ['negative zero', -0, 'INVALID_FIELD_VALUE'],
  ])('rejects encoder numeric value %s with a stable error', (_name, seq, code) => {
    const message = {
      protocol: 'call.v1',
      type: 'call.start',
      seq,
      client_request_id: 'request',
      character_id: 'luotianyi',
      audio: { encoding: 'pcm_s16le', sample_rate: 16000, channels: 1 },
    } as ControlMessage;

    expectControlError(
      () => encodeControlMessage(message, { transport: 'call_ws', direction: 'client_to_server' }),
      code,
      '$.seq',
    );
  });

  it('measures strict UTF-8 bytes at the 16384-byte boundary', () => {
    const base = '{"protocol":"call.v1","type":"error","code":"OK","message":"界","retryable":false}';
    const exact = base + ' '.repeat(16_384 - Buffer.byteLength(base, 'utf8'));

    expect(decodeControlText(exact, { transport: 'call_ws', direction: 'server_to_client' }).type).toBe('error');
    expectControlError(
      () => decodeControlText(`${exact} `, { transport: 'call_ws', direction: 'server_to_client' }),
      'CONTROL_TOO_LARGE',
      '$',
    );
  });
});

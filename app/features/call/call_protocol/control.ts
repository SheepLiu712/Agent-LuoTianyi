import {
  ControlMessageError,
  type ControlContext,
  type ControlDirection,
  type ControlErrorCode,
  type ControlMessage,
  type ControlTransport,
} from './control_types';

const MAX_RAW_BYTES = 16_384;
const UINT32_MAX = 0xffff_ffff;
const SAFE_INTEGER_MAX = Number.MAX_SAFE_INTEGER;
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const ERROR_CODE_PATTERN = /^[A-Z][A-Z0-9_]{0,63}$/;

type JsonValue = null | boolean | string | JsonNumber | JsonObject | JsonValue[];
type JsonObject = Map<string, JsonValue>;
type JsonNumber = number;

type MessageSpec = {
  readonly fields: readonly string[];
  readonly required: readonly string[];
  readonly transports: readonly ControlTransport[];
  readonly directions: readonly ControlDirection[];
};

const SPECS: Record<ControlMessage['type'], MessageSpec> = {
  'call.switch_prepare': spec(['protocol', 'type', 'client_request_id', 'character_id'], ['chat_ws'], ['client_to_server']),
  'call.switch_ready': spec(['protocol', 'type', 'client_request_id', 'character_id'], ['chat_ws'], ['server_to_client']),
  'call.start': spec(['protocol', 'type', 'seq', 'client_request_id', 'character_id', 'audio'], ['call_ws'], ['client_to_server']),
  'call.state': spec(['protocol', 'type', 'seq', 'call_id', 'client_request_id', 'state'], ['call_ws'], ['server_to_client']),
  'call.active': spec(['protocol', 'type', 'seq', 'call_id', 'connected_at_ms'], ['call_ws'], ['server_to_client']),
  'call.hangup': spec(['protocol', 'type', 'seq', 'call_id', 'reason'], ['call_ws'], ['client_to_server']),
  'call.ended': spec(['protocol', 'type', 'seq', 'call_id', 'outcome', 'end_reason', 'active_duration_ms'], ['call_ws'], ['server_to_client']),
  'call.resume': spec(['protocol', 'type', 'call_id', 'character_id', 'last_contiguous_server_seq'], ['call_ws'], ['client_to_server']),
  'call.resumed': spec(['protocol', 'type', 'call_id', 'character_id', 'last_contiguous_client_seq', 'last_contiguous_server_seq'], ['call_ws'], ['server_to_client']),
  ack: spec(['protocol', 'type', 'call_id', 'ack_seq'], ['call_ws'], ['client_to_server', 'server_to_client']),
  nack: spec(['protocol', 'type', 'call_id', 'missing_seq'], ['call_ws'], ['client_to_server', 'server_to_client']),
  'audio.stream_started': spec(['protocol', 'type', 'seq', 'call_id', 'audio_route', 'stream_id', 'response_id', 'encoding', 'sample_rate', 'channels'], ['call_ws'], ['server_to_client']),
  'playback.completed': spec(['protocol', 'type', 'seq', 'call_id', 'response_id', 'stream_id'], ['call_ws'], ['client_to_server']),
  'playback.stop': spec(['protocol', 'type', 'seq', 'call_id', 'response_id', 'stream_id', 'retire_server_seq', 'reason'], ['call_ws'], ['server_to_client']),
  'playback.stopped': spec(['protocol', 'type', 'seq', 'call_id', 'response_id', 'stop_seq'], ['call_ws'], ['client_to_server']),
  error: {
    fields: ['protocol', 'type', 'code', 'message', 'retryable', 'request_type', 'request_seq', 'client_request_id', 'call_id'],
    required: ['protocol', 'type', 'code', 'message', 'retryable'],
    transports: ['chat_ws', 'call_ws'],
    directions: ['client_to_server', 'server_to_client'],
  },
};

function spec(
  fields: readonly string[],
  transports: readonly ControlTransport[],
  directions: readonly ControlDirection[],
): MessageSpec {
  return { fields, required: fields, transports, directions };
}

/** Decode and validate a control message from its sole trusted text boundary. */
export function decodeControlText(raw: string, context: ControlContext): ControlMessage {
  if (typeof raw !== 'string') {
    fail('INVALID_FIELD_TYPE', '$');
  }
  const byteLength = strictUtf8Length(raw);
  if (byteLength > MAX_RAW_BYTES) {
    fail('CONTROL_TOO_LARGE', '$');
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    fail('BAD_JSON', '$');
  }
  return validateMessage(parsed, context);
}

/** Strict byte entry point for transports that have not decoded their text frame yet. */
export function decodeControlBytes(raw: Uint8Array, context: ControlContext): ControlMessage {
  if (!(raw instanceof Uint8Array)) {
    fail('INVALID_FIELD_TYPE', '$');
  }
  if (raw.byteLength > MAX_RAW_BYTES) {
    fail('CONTROL_TOO_LARGE', '$');
  }
  return decodeControlText(decodeUtf8Strict(raw), context);
}

/** Validate known fields and encode JSON without a wire field-order contract. */
export function encodeControlMessage(message: ControlMessage, context: ControlContext): string {
  const validated = validateMessage(message, context);
  const encoded = JSON.stringify(validated);
  if (strictUtf8Length(encoded) > MAX_RAW_BYTES) {
    fail('CONTROL_TOO_LARGE', '$');
  }
  return encoded;
}

function validateMessage(message: unknown, context: ControlContext): ControlMessage {
  if (message === null || typeof message !== 'object' || Array.isArray(message)) {
    fail('TOP_LEVEL_NOT_OBJECT', '$');
  }
  try {
    return validateParsed(valueToParsed(knownFields(message), '$'), context);
  } catch (error) {
    if (error instanceof RangeError) fail('BAD_JSON', '$');
    throw error;
  }
}

function validateParsed(value: JsonValue, context: ControlContext): ControlMessage {
  if (!(value instanceof Map)) {
    fail('TOP_LEVEL_NOT_OBJECT', '$');
  }
  const object = value as JsonObject;
  const protocol = object.get('protocol');
  if (protocol === undefined) {
    fail('MISSING_FIELD', '$.protocol');
  }
  if (typeof protocol !== 'string') {
    fail('INVALID_FIELD_TYPE', '$.protocol');
  }
  if (protocol !== 'call.v1') {
    fail('UNSUPPORTED_PROTOCOL', '$.protocol');
  }
  const typeValue = object.get('type');
  if (typeValue === undefined) {
    fail('MISSING_FIELD', '$.type');
  }
  if (typeof typeValue !== 'string') {
    fail('INVALID_FIELD_TYPE', '$.type');
  }
  if (!hasOwn(SPECS, typeValue)) {
    fail('UNKNOWN_TYPE', '$.type');
  }
  const type = typeValue as ControlMessage['type'];
  const messageSpec = SPECS[type];
  if (!messageSpec.transports.includes(context.transport)) {
    fail('INVALID_TRANSPORT', '$');
  }
  if (!messageSpec.directions.includes(context.direction)) {
    fail('INVALID_DIRECTION', '$');
  }
  for (const field of messageSpec.required) {
    if (!object.has(field)) {
      fail('MISSING_FIELD', `$.${field}`);
    }
  }
  validateFieldTypes(type, object);
  validateFieldRanges(type, object);
  validateEnums(type, object);
  validateCrossFields(type, object);
  return materializeObject(object) as unknown as ControlMessage;
}

function validateFieldTypes(type: ControlMessage['type'], object: JsonObject): void {
  for (const field of stringFields(type)) {
    if (object.has(field)) requireString(object, field);
  }
  for (const field of integerFields(type)) {
    if (object.has(field)) requireInteger(object, field);
  }
  if (type === 'error' && typeof object.get('retryable') !== 'boolean') {
    fail('INVALID_FIELD_TYPE', '$.retryable');
  }
  if (type === 'call.start') {
    requireNestedObject(object, 'audio', ['encoding', 'sample_rate', 'channels']);
    const audio = object.get('audio') as JsonObject;
    requireString(audio, 'encoding', '$.audio');
    requireInteger(audio, 'sample_rate', '$.audio');
    requireInteger(audio, 'channels', '$.audio');
  }
  if (type === 'playback.stop') {
    requireNestedObject(object, 'retire_server_seq', ['from', 'through']);
    const range = object.get('retire_server_seq') as JsonObject;
    requireInteger(range, 'from', '$.retire_server_seq');
    requireInteger(range, 'through', '$.retire_server_seq');
  }
}

function validateFieldRanges(type: ControlMessage['type'], object: JsonObject): void {
  for (const field of seqFields(type)) {
    if (object.has(field)) requireRange(object, field, 1, UINT32_MAX);
  }
  for (const field of cursorFields(type)) {
    if (object.has(field)) requireRange(object, field, 0, UINT32_MAX);
  }
  if (type === 'call.active') requireRange(object, 'connected_at_ms', 0, SAFE_INTEGER_MAX);
  if (type === 'call.ended') requireRange(object, 'active_duration_ms', 0, SAFE_INTEGER_MAX);
  for (const field of opaqueFields(type)) {
    if (object.has(field)) requireStringRange(object, field, 1, 128);
  }
  for (const field of characterFields(type)) requireStringRange(object, field, 1, 64);
  if (hasField(type, 'call_id') && object.has('call_id')) validateUuid(object, 'call_id');
  if (type === 'error') {
    requireStringRange(object, 'code', 1, 64);
    requireStringRange(object, 'message', 1, 512);
    if (object.has('request_type')) requireStringRange(object, 'request_type', 1, 64);
  }
  if (type === 'playback.stop') {
    const range = object.get('retire_server_seq') as JsonObject;
    requireRange(range, 'from', 1, UINT32_MAX, '$.retire_server_seq');
    requireRange(range, 'through', 1, UINT32_MAX, '$.retire_server_seq');
  }
}

function validateEnums(type: ControlMessage['type'], object: JsonObject): void {
  const enumRules: Partial<Record<ControlMessage['type'], readonly [string, readonly unknown[]][]>> = {
    'call.state': [['state', ['preparing', 'ringing']]],
    'call.hangup': [['reason', ['user_hangup', 'backgrounded']]],
    'call.ended': [
      ['outcome', ['connected', 'cancelled_before_answer', 'declined']],
      ['end_reason', ['user_hangup', 'agent_hangup', 'declined', 'setup_timeout', 'time_limit', 'provider_failed', 'recovery_timeout', 'system_failure']],
    ],
    'audio.stream_started': [
      ['audio_route', ['CALL']],
      ['encoding', ['pcm_s16le']],
      ['sample_rate', [24000]],
      ['channels', [1]],
    ],
    'playback.stop': [['reason', ['user_interrupted']]],
  };
  for (const [field, allowed] of enumRules[type] ?? []) {
    if (!allowed.includes(materialize(object.get(field)!))) fail('INVALID_ENUM', `$.${field}`);
  }
  if (type === 'call.start') {
    const audio = object.get('audio') as JsonObject;
    for (const [field, allowed] of [
      ['encoding', ['pcm_s16le']],
      ['sample_rate', [16000]],
      ['channels', [1]],
    ] as const) {
      if (!allowed.includes(materialize(audio.get(field)!) as never)) fail('INVALID_ENUM', `$.audio.${field}`);
    }
  }
  if (type === 'error' && !ERROR_CODE_PATTERN.test(object.get('code') as string)) {
    fail('INVALID_FIELD_VALUE', '$.code');
  }
}

function validateCrossFields(type: ControlMessage['type'], object: JsonObject): void {
  if (type !== 'playback.stop') return;
  const range = object.get('retire_server_seq') as JsonObject;
  const from = numberValue(range.get('from')!);
  const through = numberValue(range.get('through')!);
  const stopSeq = numberValue(object.get('seq')!);
  if (from > through) fail('INVALID_FIELD_VALUE', '$.retire_server_seq');
  if (through >= stopSeq) fail('INVALID_FIELD_VALUE', '$.retire_server_seq.through');
}

function requireNestedObject(object: JsonObject, field: string, fields: readonly string[]): void {
  const value = object.get(field);
  if (!(value instanceof Map)) fail('INVALID_FIELD_TYPE', `$.${field}`);
  for (const required of fields) {
    if (!value.has(required)) fail('MISSING_FIELD', `$.${field}.${required}`);
  }
}

function requireString(object: JsonObject, field: string, base = '$'): string {
  const value = object.get(field);
  if (typeof value !== 'string') fail('INVALID_FIELD_TYPE', `${base}.${field}`);
  validateUnicodeValue(value, `${base}.${field}`);
  return value;
}

function requireInteger(object: JsonObject, field: string, base = '$'): JsonNumber {
  const value = object.get(field);
  if (!isJsonNumber(value)) fail('INVALID_FIELD_TYPE', `${base}.${field}`);
  if (!Number.isFinite(value)) fail('FIELD_OUT_OF_RANGE', `${base}.${field}`);
  if (!Number.isInteger(value)) fail('INVALID_FIELD_TYPE', `${base}.${field}`);
  return value;
}

function requireRange(object: JsonObject, field: string, minimum: number, maximum: number, base = '$'): void {
  const value = numberValue(object.get(field)!);
  if (!Number.isSafeInteger(value) || value < minimum || value > maximum) {
    fail('FIELD_OUT_OF_RANGE', `${base}.${field}`);
  }
}

function requireStringRange(object: JsonObject, field: string, minimum: number, maximum: number): void {
  const value = object.get(field) as string;
  const length = [...value].length;
  if (length < minimum || length > maximum) fail('FIELD_OUT_OF_RANGE', `$.${field}`);
}

function validateUuid(object: JsonObject, field: string): void {
  if (!UUID_PATTERN.test(object.get(field) as string)) fail('INVALID_FIELD_VALUE', `$.${field}`);
}

function validateUnicodeValue(value: string, path: string): void {
  for (let index = 0; index < value.length; index += 1) {
    const code = value.charCodeAt(index);
    if (code === 0 || code === 0xfffd) fail('INVALID_FIELD_VALUE', path);
    if (code >= 0xd800 && code <= 0xdbff) {
      const next = value.charCodeAt(index + 1);
      if (!Number.isInteger(next) || next < 0xdc00 || next > 0xdfff) fail('INVALID_FIELD_VALUE', path);
      index += 1;
    } else if (code >= 0xdc00 && code <= 0xdfff) {
      fail('INVALID_FIELD_VALUE', path);
    }
  }
}

function strictUtf8Length(value: string): number {
  let bytes = 0;
  for (let index = 0; index < value.length; index += 1) {
    const code = value.charCodeAt(index);
    if (code <= 0x7f) bytes += 1;
    else if (code <= 0x7ff) bytes += 2;
    else if (code >= 0xd800 && code <= 0xdbff) {
      const next = value.charCodeAt(index + 1);
      if (!Number.isInteger(next) || next < 0xdc00 || next > 0xdfff) fail('BAD_JSON', '$');
      bytes += 4;
      index += 1;
    } else if (code >= 0xdc00 && code <= 0xdfff) fail('BAD_JSON', '$');
    else bytes += 3;
  }
  return bytes;
}

function decodeUtf8Strict(bytes: Uint8Array): string {
  let result = '';
  for (let index = 0; index < bytes.length; ) {
    const first = bytes[index++];
    if (first <= 0x7f) {
      result += String.fromCharCode(first);
      continue;
    }
    let remaining: number;
    let codePoint: number;
    let minimum: number;
    if (first >= 0xc2 && first <= 0xdf) {
      remaining = 1;
      codePoint = first & 0x1f;
      minimum = 0x80;
    } else if (first >= 0xe0 && first <= 0xef) {
      remaining = 2;
      codePoint = first & 0x0f;
      minimum = 0x800;
    } else if (first >= 0xf0 && first <= 0xf4) {
      remaining = 3;
      codePoint = first & 0x07;
      minimum = 0x1_0000;
    } else {
      fail('BAD_JSON', '$');
    }
    if (index + remaining > bytes.length) fail('BAD_JSON', '$');
    for (let offset = 0; offset < remaining; offset += 1) {
      const continuation = bytes[index++];
      if ((continuation & 0xc0) !== 0x80) fail('BAD_JSON', '$');
      codePoint = (codePoint << 6) | (continuation & 0x3f);
    }
    if (
      codePoint < minimum ||
      codePoint > 0x10_ffff ||
      (codePoint >= 0xd800 && codePoint <= 0xdfff)
    ) {
      fail('BAD_JSON', '$');
    }
    result += String.fromCodePoint(codePoint);
  }
  return result;
}

function knownFields(value: unknown): unknown {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return value;
  const object = value as Record<string, unknown>;
  const type = object.type;
  const fields = typeof type === 'string' && hasOwn(SPECS, type)
    ? SPECS[type as ControlMessage['type']].fields : ['protocol', 'type'];
  const result: Record<string, unknown> = {};
  for (const key of Object.keys(object)) {
    if (!fields.includes(key)) continue;
    const item = object[key];
    const nested = key === 'audio' ? ['encoding', 'sample_rate', 'channels']
      : key === 'retire_server_seq' ? ['from', 'through'] : undefined;
    result[key] = nested && item !== null && typeof item === 'object' && !Array.isArray(item)
      ? Object.fromEntries(Object.entries(item).filter(([name]) => nested.includes(name))) : item;
  }
  return result;
}

function valueToParsed(value: unknown, path: string): JsonValue {
  if (typeof value === 'string') {
    rejectLoneSurrogate(value, path);
    return value;
  }
  if (value === null || typeof value === 'boolean') return value;
  if (typeof value === 'number') {
    return value === 0 ? 0 : value;
  }
  if (Array.isArray(value)) return value.map((item, index) => valueToParsed(item, `${path}[${index}]`));
  if (typeof value !== 'object') fail('INVALID_FIELD_TYPE', path);
  const result = new Map<string, JsonValue>();
  for (const [key, item] of Object.entries(value as Record<string, unknown>)) {
    if (item !== undefined) result.set(key, valueToParsed(item, `${path}.${key}`));
  }
  return result;
}

function rejectLoneSurrogate(value: string, path: string): void {
  for (let index = 0; index < value.length; index += 1) {
    const code = value.charCodeAt(index);
    if (code >= 0xd800 && code <= 0xdbff) {
      const next = value.charCodeAt(index + 1);
      if (!Number.isInteger(next) || next < 0xdc00 || next > 0xdfff) fail('BAD_JSON', path);
      index += 1;
    } else if (code >= 0xdc00 && code <= 0xdfff) {
      fail('BAD_JSON', path);
    }
  }
}

function materializeObject(object: JsonObject): Record<string, unknown> {
  const result: Record<string, unknown> = {};
  for (const [key, value] of object) result[key] = materialize(value);
  return result;
}

function materialize(value: JsonValue): unknown {
  if (isJsonNumber(value)) return value;
  if (value instanceof Map) return materializeObject(value);
  if (Array.isArray(value)) return value.map(materialize);
  return value;
}

function numberValue(value: JsonValue): number {
  return value as number;
}

function isJsonNumber(value: JsonValue | undefined): value is JsonNumber {
  return typeof value === 'number';
}

function hasOwn(object: object, key: PropertyKey): boolean {
  return Object.prototype.hasOwnProperty.call(object, key);
}

function hasField(type: ControlMessage['type'], field: string): boolean {
  return SPECS[type].fields.includes(field);
}

function stringFields(type: ControlMessage['type']): readonly string[] {
  const numeric = new Set([
    ...integerFields(type),
    ...(type === 'audio.stream_started' ? ['sample_rate', 'channels'] : []),
  ]);
  return SPECS[type].fields.filter(
    (field) => !numeric.has(field) && !['protocol', 'type', 'audio', 'retire_server_seq', 'retryable'].includes(field),
  );
}

function integerFields(type: ControlMessage['type']): readonly string[] {
  return [
    ...seqFields(type),
    ...cursorFields(type),
    ...(type === 'call.active' ? ['connected_at_ms'] : []),
    ...(type === 'call.ended' ? ['active_duration_ms'] : []),
    ...(type === 'audio.stream_started' ? ['sample_rate', 'channels'] : []),
  ];
}

function seqFields(type: ControlMessage['type']): readonly string[] {
  const fields = SPECS[type].fields;
  return ['seq', 'stream_id', 'stop_seq', 'request_seq', 'missing_seq'].filter((field) => fields.includes(field));
}

function cursorFields(type: ControlMessage['type']): readonly string[] {
  const fields = SPECS[type].fields;
  return ['ack_seq', 'last_contiguous_client_seq', 'last_contiguous_server_seq'].filter((field) => fields.includes(field));
}

function opaqueFields(type: ControlMessage['type']): readonly string[] {
  const fields = SPECS[type].fields;
  return ['client_request_id', 'response_id'].filter((field) => fields.includes(field));
}

function characterFields(type: ControlMessage['type']): readonly string[] {
  return SPECS[type].fields.includes('character_id') ? ['character_id'] : [];
}

function fail(code: ControlErrorCode, path: string): never {
  throw new ControlMessageError(code, path);
}


export { ControlMessageError } from './control_types';
export type { ControlContext, ControlDirection, ControlErrorCode, ControlMessage, ControlTransport } from './control_types';

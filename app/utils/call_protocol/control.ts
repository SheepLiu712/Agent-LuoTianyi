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
type JsonNumber = { readonly kind: 'number'; readonly token: string; readonly value: number };

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
  const parsed = new JsonScanner(raw).parse();
  return validateParsed(parsed, context);
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

/** Validate and encode a canonical compact control JSON string. */
export function encodeControlMessage(message: ControlMessage, context: ControlContext): string {
  const parsed = valueToParsed(message, '$');
  const validated = validateParsed(parsed, context);
  const ordered = orderMessage(validated);
  const encoded = JSON.stringify(ordered);
  if (strictUtf8Length(encoded) > MAX_RAW_BYTES) {
    fail('CONTROL_TOO_LARGE', '$');
  }
  return encoded;
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
  const allowed = new Set(messageSpec.fields);
  for (const field of object.keys()) {
    if (!allowed.has(field)) {
      fail('UNKNOWN_FIELD', `$.${field}`);
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
    if (object.has(field)) requireCanonicalInteger(object, field);
  }
  if (type === 'error' && typeof object.get('retryable') !== 'boolean') {
    fail('INVALID_FIELD_TYPE', '$.retryable');
  }
  if (type === 'call.start') {
    requireNestedObject(object, 'audio', ['encoding', 'sample_rate', 'channels']);
    const audio = object.get('audio') as JsonObject;
    requireString(audio, 'encoding', '$.audio');
    requireCanonicalInteger(audio, 'sample_rate', '$.audio');
    requireCanonicalInteger(audio, 'channels', '$.audio');
  }
  if (type === 'playback.stop') {
    requireNestedObject(object, 'retire_server_seq', ['from', 'through']);
    const range = object.get('retire_server_seq') as JsonObject;
    requireCanonicalInteger(range, 'from', '$.retire_server_seq');
    requireCanonicalInteger(range, 'through', '$.retire_server_seq');
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
  const allowed = new Set(fields);
  for (const nested of value.keys()) {
    if (!allowed.has(nested)) fail('UNKNOWN_FIELD', `$.${field}.${nested}`);
  }
}

function requireString(object: JsonObject, field: string, base = '$'): string {
  const value = object.get(field);
  if (typeof value !== 'string') fail('INVALID_FIELD_TYPE', `${base}.${field}`);
  validateUnicodeValue(value, `${base}.${field}`);
  return value;
}

function requireCanonicalInteger(object: JsonObject, field: string, base = '$'): JsonNumber {
  const value = object.get(field);
  if (!isJsonNumber(value)) fail('INVALID_FIELD_TYPE', `${base}.${field}`);
  if (value.token === '-0') fail('INVALID_FIELD_VALUE', `${base}.${field}`);
  if (!/^-?(0|[1-9][0-9]*)$/.test(value.token)) fail('INVALID_FIELD_TYPE', `${base}.${field}`);
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

function orderMessage(message: ControlMessage): Record<string, unknown> {
  const ordered: Record<string, unknown> = {};
  for (const field of SPECS[message.type].fields) {
    const value = (message as unknown as Record<string, unknown>)[field];
    if (value === undefined) continue;
    if (field === 'audio') {
      const audio = value as Record<string, unknown>;
      ordered[field] = { encoding: audio.encoding, sample_rate: audio.sample_rate, channels: audio.channels };
    } else if (field === 'retire_server_seq') {
      const range = value as Record<string, unknown>;
      ordered[field] = { from: range.from, through: range.through };
    } else ordered[field] = value;
  }
  return ordered;
}

function valueToParsed(value: unknown, path: string): JsonValue {
  if (typeof value === 'string') {
    rejectLoneSurrogate(value, path);
    return value;
  }
  if (value === null || typeof value === 'boolean') return value;
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) fail('INVALID_FIELD_TYPE', path);
    return { kind: 'number', token: Object.is(value, -0) ? '-0' : String(value), value };
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
  if (isJsonNumber(value)) return value.value;
  if (value instanceof Map) return materializeObject(value);
  if (Array.isArray(value)) return value.map(materialize);
  return value;
}

function numberValue(value: JsonValue): number {
  return (value as JsonNumber).value;
}

function isJsonNumber(value: JsonValue | undefined): value is JsonNumber {
  return typeof value === 'object' && value !== null && !Array.isArray(value) && !(value instanceof Map) && value.kind === 'number';
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

class JsonScanner {
  private index = 0;

  constructor(private readonly source: string) {}

  parse(): JsonValue {
    try {
      this.skipWhitespace();
      const value = this.parseValue('$');
      this.skipWhitespace();
      if (this.index !== this.source.length) fail('BAD_JSON', '$');
      return value;
    } catch (error) {
      if (error instanceof ControlMessageError) throw error;
      fail('BAD_JSON', '$');
    }
  }

  private parseValue(path: string): JsonValue {
    const char = this.source[this.index];
    if (char === '{') return this.parseObject(path);
    if (char === '[') return this.parseArray(path);
    if (char === '"') return this.parseString(path);
    if (char === 't') return this.parseLiteral('true', true, path);
    if (char === 'f') return this.parseLiteral('false', false, path);
    if (char === 'n') return this.parseLiteral('null', null, path);
    if (char === '-' || (char >= '0' && char <= '9')) return this.parseNumber(path);
    fail('BAD_JSON', path);
  }

  private parseObject(path: string): JsonObject {
    this.index += 1;
    const object = new Map<string, JsonValue>();
    this.skipWhitespace();
    if (this.consume('}')) return object;
    while (true) {
      if (this.source[this.index] !== '"') fail('BAD_JSON', path);
      const key = this.parseString(path);
      const fieldPath = `${path}.${key}`;
      if (object.has(key)) fail('DUPLICATE_FIELD', fieldPath);
      this.skipWhitespace();
      if (!this.consume(':')) fail('BAD_JSON', fieldPath);
      this.skipWhitespace();
      object.set(key, this.parseValue(fieldPath));
      this.skipWhitespace();
      if (this.consume('}')) return object;
      if (!this.consume(',')) fail('BAD_JSON', path);
      this.skipWhitespace();
    }
  }

  private parseArray(path: string): JsonValue[] {
    this.index += 1;
    const values: JsonValue[] = [];
    this.skipWhitespace();
    if (this.consume(']')) return values;
    while (true) {
      values.push(this.parseValue(`${path}[${values.length}]`));
      this.skipWhitespace();
      if (this.consume(']')) return values;
      if (!this.consume(',')) fail('BAD_JSON', path);
      this.skipWhitespace();
    }
  }

  private parseString(path: string): string {
    this.index += 1;
    let result = '';
    while (this.index < this.source.length) {
      const char = this.source[this.index++];
      if (char === '"') return result;
      if (char === '\\') {
        const escape = this.source[this.index++];
        const simple: Record<string, string> = { '"': '"', '\\': '\\', '/': '/', b: '\b', f: '\f', n: '\n', r: '\r', t: '\t' };
        if (hasOwn(simple, escape)) result += simple[escape];
        else if (escape === 'u') result += this.parseUnicodeEscape(path);
        else fail('BAD_JSON', path);
      } else {
        const code = char.charCodeAt(0);
        if (code < 0x20) fail('BAD_JSON', path);
        if (code >= 0xd800 && code <= 0xdfff) {
          if (code > 0xdbff || this.index >= this.source.length) fail('BAD_JSON', path);
          const next = this.source.charCodeAt(this.index);
          if (next < 0xdc00 || next > 0xdfff) fail('BAD_JSON', path);
          result += char + this.source[this.index++];
        } else result += char;
      }
    }
    fail('BAD_JSON', path);
  }

  private parseUnicodeEscape(path: string): string {
    const first = this.parseHexCodeUnit(path);
    if (first >= 0xdc00 && first <= 0xdfff) fail('BAD_JSON', path);
    if (first < 0xd800 || first > 0xdbff) return String.fromCharCode(first);
    if (this.source.slice(this.index, this.index + 2) !== '\\u') fail('BAD_JSON', path);
    this.index += 2;
    const second = this.parseHexCodeUnit(path);
    if (second < 0xdc00 || second > 0xdfff) fail('BAD_JSON', path);
    return String.fromCharCode(first, second);
  }

  private parseHexCodeUnit(path: string): number {
    const hex = this.source.slice(this.index, this.index + 4);
    if (!/^[0-9a-fA-F]{4}$/.test(hex)) fail('BAD_JSON', path);
    this.index += 4;
    return Number.parseInt(hex, 16);
  }

  private parseNumber(path: string): JsonNumber {
    const start = this.index;
    if (this.consume('-') && this.index >= this.source.length) fail('BAD_JSON', path);
    if (this.consume('0')) {
      if (/[0-9]/.test(this.source[this.index] ?? '')) fail('BAD_JSON', path);
    } else {
      if (!/[1-9]/.test(this.source[this.index] ?? '')) fail('BAD_JSON', path);
      while (/[0-9]/.test(this.source[this.index] ?? '')) this.index += 1;
    }
    if (this.consume('.')) {
      if (!/[0-9]/.test(this.source[this.index] ?? '')) fail('BAD_JSON', path);
      while (/[0-9]/.test(this.source[this.index] ?? '')) this.index += 1;
    }
    if (this.source[this.index] === 'e' || this.source[this.index] === 'E') {
      this.index += 1;
      if (this.source[this.index] === '+' || this.source[this.index] === '-') this.index += 1;
      if (!/[0-9]/.test(this.source[this.index] ?? '')) fail('BAD_JSON', path);
      while (/[0-9]/.test(this.source[this.index] ?? '')) this.index += 1;
    }
    const token = this.source.slice(start, this.index);
    const value = Number(token);
    if (!Number.isFinite(value)) fail('BAD_JSON', path);
    return { kind: 'number', token, value };
  }

  private parseLiteral<T extends boolean | null>(literal: string, value: T, path: string): T {
    if (this.source.slice(this.index, this.index + literal.length) !== literal) fail('BAD_JSON', path);
    this.index += literal.length;
    return value;
  }

  private skipWhitespace(): void {
    while (' \n\r\t'.includes(this.source[this.index] ?? '\0')) this.index += 1;
  }

  private consume(char: string): boolean {
    if (this.source[this.index] !== char) return false;
    this.index += 1;
    return true;
  }
}

export { ControlMessageError } from './control_types';
export type { ControlContext, ControlDirection, ControlErrorCode, ControlMessage, ControlTransport } from './control_types';

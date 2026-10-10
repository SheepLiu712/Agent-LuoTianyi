export type ControlTransport = 'chat_ws' | 'call_ws';
export type ControlDirection = 'client_to_server' | 'server_to_client';

export type ControlErrorCode =
  | 'BAD_JSON'
  | 'CONTROL_TOO_LARGE'
  | 'TOP_LEVEL_NOT_OBJECT'
  | 'DUPLICATE_FIELD'
  | 'MISSING_FIELD'
  | 'UNKNOWN_FIELD'
  | 'UNKNOWN_TYPE'
  | 'UNSUPPORTED_PROTOCOL'
  | 'INVALID_TRANSPORT'
  | 'INVALID_DIRECTION'
  | 'INVALID_FIELD_TYPE'
  | 'FIELD_OUT_OF_RANGE'
  | 'INVALID_FIELD_VALUE'
  | 'INVALID_ENUM';

export interface ControlContext {
  transport: ControlTransport;
  direction: ControlDirection;
}

interface ControlBase<Type extends string> {
  protocol: 'call.v1';
  type: Type;
}

interface SequencedControl<Type extends string> extends ControlBase<Type> {
  seq: number;
}

export interface CallSwitchPrepare extends ControlBase<'call.switch_prepare'> {
  client_request_id: string;
  character_id: string;
}

export interface CallSwitchReady extends ControlBase<'call.switch_ready'> {
  client_request_id: string;
  character_id: string;
}

export interface CallStart extends SequencedControl<'call.start'> {
  client_request_id: string;
  character_id: string;
  audio: { encoding: 'pcm_s16le'; sample_rate: 16000; channels: 1 };
}

export interface CallStateMessage extends SequencedControl<'call.state'> {
  call_id: string;
  client_request_id: string;
  state: 'preparing' | 'ringing';
}

export interface CallActive extends SequencedControl<'call.active'> {
  call_id: string;
  connected_at_ms: number;
}

export interface CallHangup extends SequencedControl<'call.hangup'> {
  call_id: string;
  reason: 'user_hangup' | 'backgrounded';
}

export type CallEndReason =
  | 'user_hangup'
  | 'agent_hangup'
  | 'declined'
  | 'setup_timeout'
  | 'time_limit'
  | 'provider_failed'
  | 'recovery_timeout'
  | 'system_failure';

export interface CallEnded extends SequencedControl<'call.ended'> {
  call_id: string;
  outcome: 'connected' | 'cancelled_before_answer' | 'declined';
  end_reason: CallEndReason;
  active_duration_ms: number;
}

export interface CallResume extends ControlBase<'call.resume'> {
  call_id: string;
  character_id: string;
  last_contiguous_server_seq: number;
}

export interface CallResumed extends ControlBase<'call.resumed'> {
  call_id: string;
  character_id: string;
  last_contiguous_client_seq: number;
  last_contiguous_server_seq: number;
}

export interface Ack extends ControlBase<'ack'> {
  call_id: string;
  ack_seq: number;
}

export interface Nack extends ControlBase<'nack'> {
  call_id: string;
  missing_seq: number;
}

export interface AudioStreamStarted extends SequencedControl<'audio.stream_started'> {
  call_id: string;
  audio_route: 'CALL';
  stream_id: number;
  response_id: string;
  encoding: 'pcm_s16le';
  sample_rate: 24000;
  channels: 1;
}

export interface PlaybackCompleted extends SequencedControl<'playback.completed'> {
  call_id: string;
  response_id: string;
  stream_id: number;
}

export interface PlaybackStop extends SequencedControl<'playback.stop'> {
  call_id: string;
  response_id: string;
  stream_id: number;
  retire_server_seq: { from: number; through: number };
  reason: 'user_interrupted';
}

export interface PlaybackStopped extends SequencedControl<'playback.stopped'> {
  call_id: string;
  response_id: string;
  stop_seq: number;
}

export interface CallProtocolError extends ControlBase<'error'> {
  code: string;
  message: string;
  retryable: boolean;
  request_type?: string;
  request_seq?: number;
  client_request_id?: string;
  call_id?: string;
}

export type ControlMessage =
  | CallSwitchPrepare
  | CallSwitchReady
  | CallStart
  | CallStateMessage
  | CallActive
  | CallHangup
  | CallEnded
  | CallResume
  | CallResumed
  | Ack
  | Nack
  | AudioStreamStarted
  | PlaybackCompleted
  | PlaybackStop
  | PlaybackStopped
  | CallProtocolError;

export class ControlMessageError extends Error {
  readonly code: ControlErrorCode;
  readonly path: string;

  constructor(code: ControlErrorCode, path: string) {
    super(`${code} at ${path}`);
    this.name = 'ControlMessageError';
    this.code = code;
    this.path = path;
  }
}

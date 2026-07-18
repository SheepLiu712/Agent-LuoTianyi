/** 服务端 WebSocket 事件类型常量，与 server/src/interface/types.py WSEventType 一一对应 */
export const WSEventType = {
  // 系统
  SYSTEM_READY: "system_ready",
  AUTH_SUCCESS: "auth_success",
  AUTH_FAILURE: "auth_failure",
  SERVER_ERROR: "error",
  SERVER_ACK: "server_ack",
  AUTH_ERROR: "auth_error",
  AUTH_OK: "auth_ok",

  // 代理状态
  AGENT_STATE_CHANGED: "agent_state_changed",
  AGENT_MESSAGE: "agent_message",

  // 用户事件（客户端发送）
  USER_MESSAGE: "user_message",
  USER_IMAGE: "user_image",
  USER_TEXT: "user_text",
  USER_TYPING: "user_typing",
  USER_AUTH: "user_auth",
  USER_TOUCH: "user_touch",
  USER_IMAGE_SELECTING: "user_image_selecting",
  USER_IMAGE_SELECTING_CANCEL: "user_image_selecting_cancel",
  // 心跳
  HB_PING: "hb_ping",
  HB_PONG: "hb_pong",

  // 其他
  DATE_DETECTED: "date_detected",

  // 语音通话专用事件
  CALL_START: "call.start",
  CALL_RESUME: "call.resume",
  CALL_AUDIO_APPEND: "call.audio.append",
  CALL_HANGUP: "call.hangup",
  CALL_PLAYBACK_COMPLETED: "call.playback_completed",
  CALL_PLAYBACK_STOPPED: "call.playback_stopped",
  CALL_REQUESTED: "call.requested",
  CALL_CONNECTED: "call.connected",
  CALL_AUDIO_CHUNK: "call.audio.chunk",
  CALL_STOP_PLAYBACK: "call.stop_playback",
  CALL_RECONNECTING: "call.reconnecting",
  CALL_RESUMED: "call.resumed",
  CALL_REJECTED: "call.rejected",
  CALL_ENDED: "call.ended",
  CALL_ERROR: "call.error",
} as const;

export type WSEventType = (typeof WSEventType)[keyof typeof WSEventType];

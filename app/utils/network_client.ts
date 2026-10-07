import * as FileSystem from 'expo-file-system/legacy';
import { AgentMessagePayload } from '../types/chat';
import { addDebugTrace } from './debug_trace';
import { compressImageForUpload, MAX_IMAGE_FILE_SIZE_BYTES } from './image_compression';
import { WebSocketTransport } from './ws_transport';

interface SendResult {
  ok: boolean;
  request_id: string;
  error?: string;
  drop?: boolean;
  message_uuid?: string;
  duration_ms?: number;
}

interface ConnectCallbacks {
  onAgentMessage: (payload: AgentMessagePayload) => void;
  onAgentStateChanged: (state: string) => void;
  onError: (errorText: string) => void;

  onLlmRequest?: (payload: Record<string, unknown>) => Promise<Record<string, unknown> | null>;
  getLlmMode?: () => Promise<{ types: string[] }>;
}

function sanitizeBase64(input: string) {
  const idx = input.indexOf(',');
  return idx >= 0 ? input.slice(idx + 1) : input;
}

export class NetworkClient {
  private transport: WebSocketTransport | null = null;

  connectWs(username: string, token: string, callbacks: ConnectCallbacks) {
    this.disconnectWs();
    addDebugTrace('network', 'connectWs', { username });
    this.transport = new WebSocketTransport(username, token, callbacks);
    this.transport.start();
  }

  disconnectWs() {
    if (this.transport) {
      addDebugTrace('network', 'disconnectWs');
      this.transport.stop();
      this.transport = null;
    }
  }

  sendChat(text: string, isProactive = false, clientMsgId?: string): Promise<SendResult> {
    if (!this.transport) {
      addDebugTrace('network', 'sendChat blocked: no transport');
      return Promise.resolve({
        ok: false,
        request_id: clientMsgId || `local-${Date.now()}`,
        error: 'not logged in',
        drop: true,
      });
    }
    addDebugTrace('network', 'sendChat', { textLength: text.length });
    return this.transport.submitUserText(text, isProactive, 10000, clientMsgId);
  }

  async sendImage(imageUri: string, mimeType: string, clientMsgId?: string): Promise<SendResult> {
    if (!this.transport) {
      addDebugTrace('network', 'sendImage blocked: no transport');
      return {
        ok: false,
        request_id: clientMsgId || `local-${Date.now()}`,
        error: 'not logged in',
        drop: true,
      };
    }

    try {
      let uploadUri = imageUri;
      let uploadMimeType = mimeType;
      let originalSize: number | undefined;
      try {
        const imageInfo = await FileSystem.getInfoAsync(imageUri);
        originalSize = imageInfo.exists && typeof imageInfo.size === 'number' ? imageInfo.size : undefined;
      } catch {
        // Metadata can be unavailable even when the URI remains readable.
        addDebugTrace('network', 'sendImage file size unavailable', { imageUri });
      }

      if (originalSize !== undefined && originalSize > MAX_IMAGE_FILE_SIZE_BYTES) {
        addDebugTrace('network', 'sendImage compression started', { imageUri, mimeType, originalSize });
        const compressedImage = await compressImageForUpload(imageUri, mimeType);
        if (!compressedImage.ok || compressedImage.size === undefined || compressedImage.size > MAX_IMAGE_FILE_SIZE_BYTES) {
          addDebugTrace('network', 'sendImage compression failed', {
            imageUri,
            originalSize,
            reason: compressedImage.ok ? 'compressed size unavailable or over limit' : compressedImage.reason,
          });
          return {
            ok: false,
            request_id: clientMsgId || `local-${Date.now()}`,
            error: '图片过大（上限约 6 MB），请选择更小的图片',
            drop: true,
          };
        }
        uploadUri = compressedImage.uri;
        uploadMimeType = compressedImage.mimeType;
        addDebugTrace('network', 'sendImage compression completed', {
          originalSize,
          compressedSize: compressedImage.size,
          uploadUri,
          uploadMimeType,
        });
      }

      addDebugTrace('network', 'sendImage read file', {
        imageUri: uploadUri,
        mimeType: uploadMimeType,
        originalSize,
      });
      const imageBase64 = await FileSystem.readAsStringAsync(uploadUri, {
        encoding: FileSystem.EncodingType.Base64,
      });

      return this.transport.submitUserImage(
        sanitizeBase64(imageBase64),
        uploadMimeType,
        uploadUri,
        10000,
        clientMsgId,
      );
    } catch {
      addDebugTrace('network', 'sendImage failed: read file error', { imageUri });
      return {
        ok: false,
        request_id: clientMsgId || `local-${Date.now()}`,
        error: 'failed to read image file',
        drop: true,
      };
    }
  }

  sendTouch(
    touchArea: string | string[],
    clickFrequency?: Record<string, number>,
    touchMeta?: Record<string, unknown>,
    clientMsgId?: string,
  ): Promise<SendResult> {
    if (!this.transport) {
      addDebugTrace('network', 'sendTouch blocked: no transport');
      return Promise.resolve({
        ok: false,
        request_id: clientMsgId || `local-${Date.now()}`,
        error: 'not logged in',
        drop: true,
      });
    }
    addDebugTrace('network', 'sendTouch', { touchArea });
    return this.transport.submitUserTouch(touchArea, clickFrequency, touchMeta, 10000, clientMsgId);
  }

  sendTypingEvent(textLength: number, clientMsgId?: string): Promise<SendResult> {
    if (!this.transport) {
      addDebugTrace('network', 'sendTyping blocked: no transport');
      return Promise.resolve({
        ok: false,
        request_id: clientMsgId || `local-${Date.now()}`,
        error: 'not logged in',
        drop: true,
      });
    }
    addDebugTrace('network', 'sendTyping', { textLength });
    return this.transport.submitUserTyping(textLength, 10000, clientMsgId);
  }

  sendImageSelecting(clientMsgId?: string): Promise<SendResult> {
    if (!this.transport) {
      addDebugTrace('network', 'sendImageSelecting blocked: no transport');
      return Promise.resolve({
        ok: false,
        request_id: clientMsgId || `local-${Date.now()}`,
        error: 'not logged in',
        drop: true,
      });
    }
    addDebugTrace('network', 'sendImageSelecting');
    return this.transport.submitUserImageSelecting(5000, clientMsgId);
  }

  sendImageSelectingCancel(clientMsgId?: string): Promise<SendResult> {
    if (!this.transport) {
      addDebugTrace('network', 'sendImageSelectingCancel blocked: no transport');
      return Promise.resolve({
        ok: false,
        request_id: clientMsgId || `local-${Date.now()}`,
        error: 'not logged in',
        drop: true,
      });
    }
    addDebugTrace('network', 'sendImageSelectingCancel');
    return this.transport.submitUserImageSelectingCancel(5000, clientMsgId);
  }

  sendVoiceRecordingStarted(recordingId: string, clientMsgId?: string) {
    if (!this.transport) return Promise.resolve({ ok: false, request_id: clientMsgId || `local-${Date.now()}`, error: 'not logged in', drop: true });
    return this.transport.submitVoiceRecordingStarted(recordingId, 5000, clientMsgId);
  }

  sendVoiceRecordingCancelled(recordingId: string, clientMsgId?: string) {
    if (!this.transport) return Promise.resolve({ ok: false, request_id: clientMsgId || `local-${Date.now()}`, error: 'not logged in', drop: true });
    return this.transport.submitVoiceRecordingCancelled(recordingId, 5000, clientMsgId);
  }

  sendVoicePhase(payload: Record<string, unknown>, clientMsgId?: string) {
    if (!this.transport) return Promise.resolve({ ok: false, request_id: clientMsgId || `local-${Date.now()}`, error: 'not logged in', drop: true });
    return this.transport.submitVoicePhase(payload, 5000, clientMsgId);
  }


}

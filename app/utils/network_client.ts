import * as FileSystem from 'expo-file-system/legacy';
import { AgentMessagePayload } from '../types/chat';
import { addDebugTrace } from './debug_trace';
import { WebSocketTransport } from './ws_transport';

interface SendResult {
  ok: boolean;
  request_id: string;
  error?: string;
  drop?: boolean;
}

interface ConnectCallbacks {
  onAgentMessage: (payload: AgentMessagePayload) => void;
  onAgentStateChanged: (state: string) => void;
  onError: (errorText: string) => void;
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

  sendChat(text: string): Promise<SendResult> {
    if (!this.transport) {
      addDebugTrace('network', 'sendChat blocked: no transport');
      return Promise.resolve({
        ok: false,
        request_id: `local-${Date.now()}`,
        error: 'not logged in',
        drop: true,
      });
    }
    addDebugTrace('network', 'sendChat', { textLength: text.length });
    return this.transport.submitUserText(text, 10000);
  }

  async sendImage(imageUri: string, mimeType: string): Promise<SendResult> {
    if (!this.transport) {
      addDebugTrace('network', 'sendImage blocked: no transport');
      return {
        ok: false,
        request_id: `local-${Date.now()}`,
        error: 'not logged in',
        drop: true,
      };
    }

    try {
      addDebugTrace('network', 'sendImage read file', { imageUri, mimeType });
      const imageBase64 = await FileSystem.readAsStringAsync(imageUri, {
        encoding: FileSystem.EncodingType.Base64,
      });

      return this.transport.submitUserImage(
        sanitizeBase64(imageBase64),
        mimeType,
        imageUri,
        10000,
      );
    } catch {
      addDebugTrace('network', 'sendImage failed: read file error', { imageUri });
      return {
        ok: false,
        request_id: `local-${Date.now()}`,
        error: 'failed to read image file',
        drop: true,
      };
    }
  }

  sendTypingEvent(textLength: number): Promise<SendResult> {
    if (!this.transport) {
      addDebugTrace('network', 'sendTyping blocked: no transport');
      return Promise.resolve({
        ok: false,
        request_id: `local-${Date.now()}`,
        error: 'not logged in',
        drop: true,
      });
    }
    addDebugTrace('network', 'sendTyping', { textLength });
    return this.transport.submitUserTyping(textLength, 10000);
  }
}

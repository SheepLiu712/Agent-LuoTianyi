import type { CallSocket, CallSocketEventMap, CallSocketFactory } from '../../types/call_transport';

interface PlatformMessageEvent { data: string | ArrayBuffer | Uint8Array | Blob }
interface PlatformWebSocket {
  readyState: number;
  binaryType: string;
  send(data: string | Uint8Array): void;
  close(code?: number, reason?: string): void;
  addEventListener(type: string, listener: (event: unknown) => void): void;
  removeEventListener(type: string, listener: (event: unknown) => void): void;
}

export function createPlatformCallSocketFactory(
  create: (url: string) => PlatformWebSocket = (url) => new WebSocket(url) as unknown as PlatformWebSocket,
): CallSocketFactory {
  return { create: (url) => new PlatformCallSocket(create(url)) };
}

class PlatformCallSocket implements CallSocket {
  private readonly listeners = new Map<keyof CallSocketEventMap, Map<Function, (event: unknown) => void>>();

  constructor(private readonly socket: PlatformWebSocket) { socket.binaryType = 'arraybuffer'; }
  get readyState(): number { return this.socket.readyState; }
  send(data: string | Uint8Array): void { this.socket.send(data); }
  close(code?: number, reason?: string): void { this.socket.close(code, reason); }

  addEventListener<Type extends keyof CallSocketEventMap>(type: Type, listener: (event: CallSocketEventMap[Type]) => void): void {
    const wrapped = type === 'message'
      ? (event: unknown) => { this.dispatchMessage(event as PlatformMessageEvent, listener); }
      : (event: unknown) => listener(event as CallSocketEventMap[Type]);
    const byListener = this.listeners.get(type) ?? new Map();
    byListener.set(listener, wrapped);
    this.listeners.set(type, byListener);
    this.socket.addEventListener(type, wrapped);
  }

  removeEventListener<Type extends keyof CallSocketEventMap>(type: Type, listener: (event: CallSocketEventMap[Type]) => void): void {
    const wrapped = this.listeners.get(type)?.get(listener);
    if (!wrapped) return;
    this.socket.removeEventListener(type, wrapped);
    this.listeners.get(type)?.delete(listener);
  }

  private dispatchError(message: string): void {
    for (const listener of this.listeners.get('error')?.values() ?? []) listener({ message });
  }

  private dispatchMessage<Type extends keyof CallSocketEventMap>(
    event: PlatformMessageEvent,
    listener: (event: CallSocketEventMap[Type]) => void,
  ): void {
    const data = event.data;
    if (typeof data === 'string' || data instanceof Uint8Array) {
      listener({ data } as CallSocketEventMap[Type]);
      return;
    }
    if (data instanceof ArrayBuffer) {
      listener({ data: new Uint8Array(data) } as CallSocketEventMap[Type]);
      return;
    }
    if (typeof Blob !== 'undefined' && data instanceof Blob && typeof data.arrayBuffer === 'function') {
      const deferred = { resolve: async () => new Uint8Array(await data.arrayBuffer()) };
      listener({ data: deferred } as CallSocketEventMap[Type]);
      return;
    }
    this.dispatchError('UNSUPPORTED_SOCKET_PAYLOAD');
  }
}

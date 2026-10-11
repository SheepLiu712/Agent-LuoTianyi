import type {
  CallSwitchPort,
  CallStartMode,
  CallTransportErrorListener,
  CallTransportListener,
  CallTransportSnapshot,
  StartCallRequest,
} from '../../types/call_transport';
import { CallTransportSession } from '../call_transport/call_transport';

/** Frozen coordinator API consumed by the later UI lane. */
export class CallSession {
  private preparedRequestId: string | null = null;
  constructor(
    private readonly transport: CallTransportSession,
    private readonly switchPort: CallSwitchPort,
    private readonly characterId: string,
    private readonly release?: () => void | Promise<void>,
  ) {}

  get state(): Readonly<CallTransportSnapshot> {
    return this.transport.state;
  }

  async prepare(clientRequestId: string): Promise<void> {
    await this.switchPort.prepare(clientRequestId, this.characterId);
    this.preparedRequestId = clientRequestId;
  }

  async start(clientRequestId: string, mode: CallStartMode): Promise<void> {
    if (mode === 'prepared_switch' && this.preparedRequestId !== clientRequestId) {
      throw new Error('CALL_PREPARE_IDENTITY_MISMATCH');
    }
    if (mode === 'direct_no_chat' && this.preparedRequestId !== null) {
      throw new Error('DIRECT_START_AFTER_PREPARE');
    }
    const request: StartCallRequest = { clientRequestId, characterId: this.characterId };
    await this.transport.start(request);
  }

  hangup(reason: 'user_hangup' | 'backgrounded' = 'user_hangup'): Promise<void> {
    return this.transport.hangup(reason);
  }

  subscribe(listener: CallTransportListener): () => void {
    return this.transport.subscribe(listener);
  }

  onError(listener: CallTransportErrorListener): () => void {
    return this.transport.onError(listener);
  }

  close(): void | Promise<void> {
    this.transport.close();
    return this.release?.();
  }
}

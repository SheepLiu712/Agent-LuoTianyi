jest.mock('react-native', () => ({ AppState: { currentState: 'active' } }));
jest.mock('expo-av', () => ({ Audio: { Sound: jest.fn() } }));
jest.mock('expo-file-system/legacy', () => ({
  EncodingType: { Base64: 'base64' },
  getInfoAsync: jest.fn().mockResolvedValue({ exists: true, size: 49152 }),
  readAsStringAsync: jest.fn(),
}));

import * as FileSystem from 'expo-file-system/legacy';
import { AgentBinder } from '../utils/binder';
import { MessageProcessor } from '../utils/message_processor';
import { NetworkClient } from '../utils/network_client';

function binder() {
  return { emitMessageStatus: jest.fn(), emitErrorText: jest.fn(), emitAgentMessage: jest.fn(), emitLocalTtsState: jest.fn() } as unknown as jest.Mocked<AgentBinder>;
}

function processor(networkClient: NetworkClient, messageBinder = binder()) {
  return { processor: new MessageProcessor(networkClient, messageBinder, jest.fn()), binder: messageBinder };
}

describe('voice upload phases', () => {
  beforeEach(() => jest.clearAllMocks());

  it('sends begin, chunks, and finalize with stable upload and client IDs', async () => {
    const raw = 'A'.repeat(65536 + 8);
    (FileSystem.readAsStringAsync as jest.Mock).mockResolvedValue(raw);
    const phases: Array<{ payload: Record<string, unknown>; id?: string }> = [];
    const network = { sendVoicePhase: jest.fn(async (payload, id) => { phases.push({ payload, id }); return { ok: true }; }) } as unknown as NetworkClient;
    const { processor: subject, binder: messageBinder } = processor(network);

    await subject.sendVoice('voice-1', 'file://voice.m4a', 15000);
    await new Promise((resolve) => setImmediate(resolve));
    await new Promise((resolve) => setImmediate(resolve));

    expect(phases.map((entry) => entry.payload.phase)).toEqual(['begin', 'chunk', 'chunk', 'finalize']);
    expect(phases.map((entry) => entry.id)).toEqual(['voice-1:begin', 'voice-1:chunk:0', 'voice-1:chunk:1', 'voice-1:finalize']);
    expect(phases.every(({ payload }) => payload.upload_id === 'voice-1')).toBe(true);
    expect((phases[1].payload.audio_base64 as string).length).toBeLessThanOrEqual(65536);
    expect(messageBinder.emitMessageStatus).toHaveBeenLastCalledWith('voice-1', 'submitted');
  });

  it('drops when the 15 second budget is exceeded', async () => {
    (FileSystem.readAsStringAsync as jest.Mock).mockResolvedValue('AAAA');
    const network = { sendVoicePhase: jest.fn(async () => ({ ok: true })) } as unknown as NetworkClient;
    const { processor: subject, binder: messageBinder } = processor(network);
    const now = jest.spyOn(Date, 'now').mockReturnValueOnce(0).mockReturnValue(15000);
    const result = await (subject as any).sendVoiceItem({ kind: 'voice', uuid: 'late', localUri: 'file://voice.m4a', durationMs: 1000, clientMsgId: 'late', retryAttempt: 0, enqueuedAtMs: 0 });
    expect(result).toMatchObject({ ok: false, drop: true });
    expect((network.sendVoicePhase as jest.Mock).mock.calls.map((call) => call[1])).toEqual(['late:begin']);
    now.mockRestore();
    expect(messageBinder.emitMessageStatus).not.toHaveBeenCalled();
  });

  it('retries a failed upload with the same phase IDs', async () => {
    (FileSystem.readAsStringAsync as jest.Mock).mockResolvedValue('AAAA');
    const ids: string[] = [];
    let attempt = 0;
    const network = { sendVoicePhase: jest.fn(async (_payload, id) => { ids.push(id); attempt += 1; return attempt === 1 ? { ok: false, error: 'temporary' } : { ok: true }; }) } as unknown as NetworkClient;
    const { processor: subject } = processor(network);
    const item = { kind: 'voice', uuid: 'retry', localUri: 'file://voice.m4a', durationMs: 1000, clientMsgId: 'retry', retryAttempt: 0, enqueuedAtMs: Date.now() };
    await expect((subject as any).sendVoiceItem(item)).resolves.toMatchObject({ ok: false });
    await expect((subject as any).sendVoiceItem(item)).resolves.toMatchObject({ ok: true });
    expect(ids).toEqual(['retry:begin', 'retry:begin', 'retry:chunk:0', 'retry:finalize']);
  });
});

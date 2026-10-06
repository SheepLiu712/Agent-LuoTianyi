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

  it('drops when the 15 second budget is exceeded and releases the server slot with abort', async () => {
    (FileSystem.readAsStringAsync as jest.Mock).mockResolvedValue('AAAA');
    const network = { sendVoicePhase: jest.fn(async () => ({ ok: true })) } as unknown as NetworkClient;
    const { processor: subject, binder: messageBinder } = processor(network);
    const now = jest.spyOn(Date, 'now').mockReturnValueOnce(0).mockReturnValue(15000);
    const result = await (subject as any).sendVoiceItem({ kind: 'voice', uuid: 'late', localUri: 'file://voice.m4a', durationMs: 1000, clientMsgId: 'late', retryAttempt: 0, enqueuedAtMs: 0 });
    expect(result).toMatchObject({ ok: false, drop: true });
    // 放弃上传时必须补发 abort，否则服务端每用户唯一的未完成槽位会被占满到 TTL。
    expect((network.sendVoicePhase as jest.Mock).mock.calls.map((call) => call[1])).toEqual(['late:abort']);
    expect((network.sendVoicePhase as jest.Mock).mock.calls[0][0]).toEqual({ phase: 'abort', upload_id: 'late' });
    now.mockRestore();
    expect(messageBinder.emitMessageStatus).not.toHaveBeenCalled();
  });

  it('keeps the 15 second budget across retries instead of restarting it', async () => {
    (FileSystem.readAsStringAsync as jest.Mock).mockResolvedValue('AAAA');
    const ids: string[] = [];
    let attempt = 0;
    // 第一次 begin 可重试失败；第二次 begin 成功，但总预算必须已经耗尽。
    const network = { sendVoicePhase: jest.fn(async (_payload, id) => { ids.push(id); attempt += 1; return attempt === 1 ? { ok: false, error: 'temporary' } : { ok: true }; }) } as unknown as NetworkClient;
    const { processor: subject } = processor(network);
    const item = { kind: 'voice', uuid: 'budget', localUri: 'file://voice.m4a', durationMs: 1000, clientMsgId: 'budget', retryAttempt: 0, enqueuedAtMs: 0 };
    const now = jest.spyOn(Date, 'now').mockReturnValue(0);
    await expect((subject as any).sendVoiceItem(item)).resolves.toMatchObject({ ok: false });
    now.mockReturnValue(16000);
    const second = await (subject as any).sendVoiceItem(item);
    now.mockRestore();

    expect(second).toMatchObject({ ok: false, drop: true, error: 'voice upload budget exceeded' });
    // 第二次 invocation 进入时预算已耗尽，begin 前就直接放弃（不再重复发帧）。
    expect(ids).toEqual(['budget:begin', 'budget:abort']);
  });

  it('releases the server slot when a phase is permanently rejected', async () => {
    (FileSystem.readAsStringAsync as jest.Mock).mockResolvedValue('AAAA');
    const calls: Array<[Record<string, unknown>, string]> = [];
    const network = {
      sendVoicePhase: jest.fn(async (payload: Record<string, unknown>, id: string) => {
        calls.push([payload, id]);
        return id.endsWith(':begin') ? { ok: false, error: 'conflict', drop: true } : { ok: true };
      }),
    } as unknown as NetworkClient;
    const { processor: subject } = processor(network);

    const result = await (subject as any).sendVoiceItem({ kind: 'voice', uuid: 'conflict', localUri: 'file://voice.m4a', durationMs: 1000, clientMsgId: 'conflict', retryAttempt: 0, enqueuedAtMs: 0 });

    expect(result).toMatchObject({ ok: false, drop: true, error: 'conflict' });
    expect(calls.map(([, id]) => id)).toEqual(['conflict:begin', 'conflict:abort']);
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

  it('aborts when a retryable begin failure exhausts the 15 second budget', async () => {
    (FileSystem.readAsStringAsync as jest.Mock).mockResolvedValue('AAAA');
    const ids: string[] = [];
    const network = { sendVoicePhase: jest.fn(async (_payload, id) => { ids.push(id); return { ok: false, error: 'offline' }; }) } as unknown as NetworkClient;
    const { processor: subject } = processor(network);
    // 进入时未超预算（0）；begin 失败后预算已耗尽（16000）。
    const now = jest.spyOn(Date, 'now').mockReturnValueOnce(0).mockReturnValue(16000);
    const item = { kind: 'voice', uuid: 'offline', localUri: 'file://voice.m4a', durationMs: 1000, clientMsgId: 'offline', retryAttempt: 0, enqueuedAtMs: 0, voiceStartedAtMs: 0 };

    const result = await (subject as any).sendVoiceItem(item);
    now.mockRestore();

    // 离线时 begin 返回可重试失败；旧实现会原样返回由 durable 循环继续重试，失败图标要 2~3.5 分钟才出现。
    expect(result).toMatchObject({ ok: false, drop: true, error: 'offline' });
    expect(ids).toEqual(['offline:begin', 'offline:abort']);
  });

  it('still returns a retryable failure (without abort) when the budget has time left', async () => {
    (FileSystem.readAsStringAsync as jest.Mock).mockResolvedValue('AAAA');
    const ids: string[] = [];
    const network = { sendVoicePhase: jest.fn(async (_payload, id) => { ids.push(id); return { ok: false, error: 'temporary' }; }) } as unknown as NetworkClient;
    const { processor: subject } = processor(network);
    const now = jest.spyOn(Date, 'now').mockReturnValue(1000);
    const item = { kind: 'voice', uuid: 'retryable', localUri: 'file://voice.m4a', durationMs: 1000, clientMsgId: 'retryable', retryAttempt: 0, enqueuedAtMs: 1000, voiceStartedAtMs: 1000 };

    const result = await (subject as any).sendVoiceItem(item);
    now.mockRestore();

    expect(result).toMatchObject({ ok: false });
    expect((result as any).drop).not.toBe(true);
    expect(ids).toEqual(['retryable:begin']);
  });
});

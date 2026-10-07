import * as FileSystem from 'expo-file-system/legacy';
import { AgentBinder } from '../utils/binder';
import { MessageProcessor } from '../utils/message_processor';
import { NetworkClient } from '../utils/network_client';

jest.mock('react-native', () => ({ AppState: { currentState: 'active' } }));
jest.mock('expo-av', () => ({ Audio: { Sound: jest.fn() } }));
jest.mock('expo-file-system/legacy', () => ({
  EncodingType: { Base64: 'base64' },
  getInfoAsync: jest.fn(), readAsStringAsync: jest.fn(),
}));

function setup(sendVoicePhase: jest.Mock) {
  const binder = { emitMessageStatus: jest.fn(), emitErrorText: jest.fn() };
  const network = { sendVoicePhase, sendVoiceRecordingCancelled: jest.fn().mockResolvedValue({ ok: true }), sendChat: jest.fn().mockResolvedValue({ ok: true }) };
  const processor = new MessageProcessor(network as unknown as NetworkClient, binder as unknown as AgentBinder, jest.fn());
  return { processor, binder, network };
}

beforeEach(() => {
  jest.useFakeTimers();
  jest.clearAllMocks();
  (FileSystem.getInfoAsync as jest.Mock).mockResolvedValue({ exists: true, size: 49158 });
  (FileSystem.readAsStringAsync as jest.Mock).mockResolvedValue('A'.repeat(65536 + 8));
});
afterEach(() => jest.useRealTimers());

it('sends stable phase IDs, waits for finalize and does not interleave queued text', async () => {
  let finish!: (result: object) => void;
  const send = jest.fn(async (payload, _id?: string) => payload.phase === 'finalize' ? new Promise((resolve) => { finish = resolve; }) : { ok: true });
  const { processor, binder, network } = setup(send);
  await processor.sendVoice('voice', 'file://voice.m4a', 1000);
  await processor.sendText('text', 'hello');
  await jest.advanceTimersByTimeAsync(0);
  expect(send.mock.calls.map((call) => call[1])).toEqual(['voice:begin', 'voice:chunk:0', 'voice:chunk:1', 'voice:finalize']);
  expect(network.sendChat).not.toHaveBeenCalled();
  expect(binder.emitMessageStatus).not.toHaveBeenCalledWith('voice', 'submitted');
  finish({ ok: true });
  await jest.advanceTimersByTimeAsync(0);
  expect(binder.emitMessageStatus).toHaveBeenCalledWith('voice', 'submitted');
  expect(network.sendChat).toHaveBeenCalledTimes(1);
});

it.each(['begin', 'chunk:1', 'finalize'])('retries only the failed %s operation with the same ID', async (failedPhase) => {
  let failed = false;
  const send = jest.fn(async (_payload, id) => {
    if (id === `voice:${failedPhase}` && !failed) { failed = true; return { ok: false, error: 'disconnected', drop: false }; }
    return { ok: true };
  });
  const { processor, binder } = setup(send);
  await processor.sendVoice('voice', 'file://voice.m4a', 1000);
  await jest.advanceTimersByTimeAsync(1000);
  const expected = ['begin', 'chunk:0', 'chunk:1', 'finalize'].flatMap((phase) => phase === failedPhase ? [phase, phase] : [phase]);
  expect(send.mock.calls.map((call) => call[1])).toEqual(expected.map((phase) => `voice:${phase}`));
  expect(binder.emitMessageStatus).toHaveBeenLastCalledWith('voice', 'submitted');
});

it('fails at the shared 15s deadline, caps the final ACK wait and aborts once without more retries', async () => {
  const send = jest.fn((payload, _id, budgetMs) => payload.phase === 'abort'
    ? Promise.resolve({ ok: true })
    : new Promise((resolve) => setTimeout(() => resolve({ ok: false, error: 'ack lost' }), budgetMs)));
  const { processor, binder } = setup(send);
  await processor.sendVoice('voice', 'file://voice.m4a', 1000);
  await jest.advanceTimersByTimeAsync(14999);
  expect(binder.emitMessageStatus).not.toHaveBeenCalledWith('voice', 'failed');
  await jest.advanceTimersByTimeAsync(1);
  expect(binder.emitMessageStatus).toHaveBeenLastCalledWith('voice', 'failed');
  expect(send.mock.calls.map((call) => [call[1], call[2]])).toEqual([
    ['voice:begin', 5000], ['voice:begin', 5000], ['voice:begin', 2000], ['voice:abort', 1000],
  ]);
  await jest.advanceTimersByTimeAsync(60000);
  expect(send).toHaveBeenCalledTimes(4);
  expect(processor.queueLength()).toBe(0);
  // 手工重试得到新预算，但逻辑消息和阶段 ID 不变。
  send.mockImplementation(async () => ({ ok: true }));
  await processor.sendVoice('voice', 'file://voice.m4a', 1000);
  await jest.advanceTimersByTimeAsync(0);
  expect(send.mock.calls[4][1]).toBe('voice:begin');
  expect(send.mock.calls[4][2]).toBe(5000);
  expect(binder.emitMessageStatus).toHaveBeenLastCalledWith('voice', 'submitted');
});

it('caps backoff at the deadline rather than waiting for the next retry window', async () => {
  const send = jest.fn(async (payload, _id?: string) => payload.phase === 'abort' ? { ok: true } : { ok: false, error: 'offline' });
  const { processor, binder } = setup(send);
  await processor.sendVoice('voice', 'file://voice.m4a', 1000);
  await jest.advanceTimersByTimeAsync(15000);
  expect(binder.emitMessageStatus).toHaveBeenLastCalledWith('voice', 'failed');
  expect(send.mock.calls.map((call) => call[1])).toEqual(['voice:begin', 'voice:begin', 'voice:begin', 'voice:begin', 'voice:abort']);
});

it('permanent rejection aborts immediately and allows the next queued message', async () => {
  const send = jest.fn(async (payload, _id?: string) => payload.phase === 'abort' ? { ok: true } : { ok: false, drop: true, error: 'BAD_MESSAGE' });
  const { processor, binder, network } = setup(send);
  await processor.sendVoice('voice', 'file://voice.m4a', 1000);
  await processor.sendText('text', 'hello');
  await jest.advanceTimersByTimeAsync(0);
  expect(send.mock.calls.map((call) => call[1])).toEqual(['voice:begin', 'voice:abort']);
  expect(binder.emitMessageStatus).toHaveBeenCalledWith('voice', 'failed');
  expect(network.sendChat).toHaveBeenCalledTimes(1);
});

it('file read errors settle as failed rather than leaving the queue and UI locked', async () => {
  (FileSystem.readAsStringAsync as jest.Mock).mockRejectedValue(new Error('file unreadable'));
  const send = jest.fn().mockResolvedValue({ ok: true });
  const { processor, binder, network } = setup(send);
  await processor.sendVoice('voice', 'file://voice.m4a', 1000);
  await jest.advanceTimersByTimeAsync(0);
  expect(binder.emitMessageStatus).toHaveBeenLastCalledWith('voice', 'failed');
  expect(processor.queueLength()).toBe(0);
  expect(send).not.toHaveBeenCalled();
  expect(network.sendVoiceRecordingCancelled).toHaveBeenCalledWith('voice');
});

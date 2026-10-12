import { ExpoCallRingtone } from '../utils/call_session/ringtone';

const createAsync = jest.fn();
jest.mock('expo-av', () => ({ Audio: { Sound: { createAsync: (...args: unknown[]) => createAsync(...args) } } }));

describe('ExpoCallRingtone', () => {
  beforeEach(() => createAsync.mockReset());

  it('does not retry a failed audio backend until a new play request', async () => {
    createAsync.mockRejectedValue(new Error('audio backend unavailable'));
    const ringtone = new ExpoCallRingtone();
    ringtone.playLoop();
    // Bounded microtask flushing also catches the old self-scheduling retry loop.
    for (let index = 0; index < 20; index += 1) await Promise.resolve();
    const attempts = createAsync.mock.calls.length;
    ringtone.stop();
    expect(attempts).toBe(1);
  });

  it('unloads a sound whose initial playback fails', async () => {
    const sound = {
      playAsync: jest.fn(async () => { throw new Error('play failed'); }),
      stopAsync: jest.fn(), unloadAsync: jest.fn(async () => undefined),
    };
    createAsync.mockResolvedValue({ sound });
    const ringtone = new ExpoCallRingtone();
    ringtone.playLoop();
    for (let index = 0; index < 20; index += 1) await Promise.resolve();
    expect(createAsync).toHaveBeenCalledTimes(1);
    expect(sound.unloadAsync).toHaveBeenCalledTimes(1);
    ringtone.stop();
  });

  it('unloads a late create after stop and never starts playback', async () => {
    let resolveCreate!: (value: any) => void;
    const sound = { playAsync: jest.fn(), stopAsync: jest.fn(), unloadAsync: jest.fn(async () => undefined) };
    createAsync.mockReturnValueOnce(new Promise((resolve) => { resolveCreate = resolve; }));
    const ringtone = new ExpoCallRingtone();
    ringtone.playLoop();
    ringtone.stop();
    resolveCreate({ sound });
    await Promise.resolve(); await Promise.resolve();
    expect(sound.playAsync).not.toHaveBeenCalled();
    expect(sound.unloadAsync).toHaveBeenCalledTimes(1);
  });

  it('starts only current desired generation and stop owns stop plus unload', async () => {
    const sound = {
      playAsync: jest.fn(async () => undefined), stopAsync: jest.fn(async () => undefined),
      unloadAsync: jest.fn(async () => undefined),
    };
    createAsync.mockResolvedValueOnce({ sound });
    const ringtone = new ExpoCallRingtone();
    ringtone.playLoop();
    await Promise.resolve(); await Promise.resolve();
    expect(sound.playAsync).toHaveBeenCalledTimes(1);
    ringtone.stop();
    await Promise.resolve(); await Promise.resolve();
    expect(sound.stopAsync).toHaveBeenCalledTimes(1);
    expect(sound.unloadAsync).toHaveBeenCalledTimes(1);
  });

  it('replaces a stopped pending generation when play is requested again', async () => {
    let resolveFirst!: (value: any) => void;
    const first = { playAsync: jest.fn(), stopAsync: jest.fn(), unloadAsync: jest.fn(async () => undefined) };
    const second = {
      playAsync: jest.fn(async () => undefined), stopAsync: jest.fn(async () => undefined),
      unloadAsync: jest.fn(async () => undefined),
    };
    createAsync
      .mockReturnValueOnce(new Promise((resolve) => { resolveFirst = resolve; }))
      .mockResolvedValueOnce({ sound: second });
    const ringtone = new ExpoCallRingtone();
    ringtone.playLoop();
    ringtone.stop();
    ringtone.playLoop();
    resolveFirst({ sound: first });
    await new Promise((resolve) => setImmediate(resolve));
    await new Promise((resolve) => setImmediate(resolve));
    expect(first.playAsync).not.toHaveBeenCalled();
    expect(first.unloadAsync).toHaveBeenCalledTimes(1);
    expect(second.playAsync).toHaveBeenCalledTimes(1);
    ringtone.stop();
  });
});

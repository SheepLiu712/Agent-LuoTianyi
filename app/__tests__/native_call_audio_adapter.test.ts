import type { CallAudioNativeModule } from '../modules/call-audio/src/CallAudioModule';
import type {
  NativeCapability,
  NativeCapturedFrame,
  NativePlaybackCompleted,
  NativePlaybackStopped,
} from '../modules/call-audio/src/CallAudio.types';
import { AndroidCallAudio, CAPTURE_FORMAT, PLAYBACK_FORMAT } from '../utils/call_audio/native_call_audio';

jest.mock('expo-modules-core', () => ({
  requireOptionalNativeModule: jest.fn(() => null),
}));
jest.mock('react-native', () => ({
  Platform: { OS: 'android' },
}));

type Listener = (event: any) => void;

class FakeNativeCallAudio implements CallAudioNativeModule {
  private readonly listeners = new Map<string, Set<Listener>>();
  generation = 0;
  replyFailureToneCount = 0;
  capability: NativeCapability = {
    available: true,
    captureFormat: CAPTURE_FORMAT as NativeCapability['captureFormat'],
    playbackFormat: PLAYBACK_FORMAT as NativeCapability['playbackFormat'],
    aec: { available: true, enabled: true },
    noiseSuppressor: { available: true, enabled: true },
    audioFocus: { granted: true },
    sessionGeneration: 1,
  };

  async getCapability() { return this.capability; }
  async startSession() { return this.capability; }
  async stopSession() {}
  async startCapture() { return this.capability; }
  async stopCapture() {}
  async reacquireAudioFocus() { return this.capability; }
  async acknowledgeCapturedAudio() {}
  async enqueuePlayback() { return ++this.generation; }
  async stopPlayback() {}
  async tombstone() {}
  async playReplyFailureTone() { this.replyFailureToneCount += 1; }
  addListener(eventName: string, listener: Listener) {
    const listeners = this.listeners.get(eventName) ?? new Set();
    listeners.add(listener);
    this.listeners.set(eventName, listeners);
    return { remove: () => listeners.delete(listener) };
  }
  emit(eventName: string, event: unknown) {
    this.listeners.get(eventName)?.forEach((listener) => listener(event));
  }
}

describe('AndroidCallAudio adapter', () => {
  it('stays unavailable until native initialization reports exact formats', async () => {
    const native = new FakeNativeCallAudio();
    native.capability = {
      ...native.capability,
      playbackFormat: { encoding: 'pcm_s16le', sampleRateHz: 16_000, channels: 1 },
    };
    const audio = new AndroidCallAudio({}, native, 'android');

    await expect(audio.initialize()).resolves.toBe('unavailable');
  });

  it.each([
    ['aec', { aec: { available: false, enabled: false, error: 'aec_unavailable' } }],
    ['noise suppression', {
      noiseSuppressor: { available: false, enabled: false, error: 'noise_suppressor_unavailable' },
    }],
    ['audio focus', { audioFocus: { granted: false, error: 'audio_focus_denied' } }],
  ])('fails closed when %s is not initialized', async (_name, override) => {
    const native = new FakeNativeCallAudio();
    native.capability = { ...native.capability, ...override };
    const audio = new AndroidCallAudio({}, native, 'android');

    await expect(audio.initialize()).resolves.toBe('unavailable');
  });

  it('emits completion only for actual current-generation native consumption', async () => {
    const native = new FakeNativeCallAudio();
    const audio = new AndroidCallAudio({}, native, 'android');
    const completed = jest.fn();
    const stream = { callId: 'call', responseId: 'response', streamId: 1 };
    audio.setConsumptionListener(completed);
    await audio.initialize();
    await audio.enqueue({ stream, format: PLAYBACK_FORMAT, payload: new Uint8Array([0, 0]), isFinal: true });

    native.emit('onPlaybackCompleted', {
      responseId: 'response', streamId: 1, generation: 0,
      sessionGeneration: 1,
    } satisfies NativePlaybackCompleted);
    expect(completed).not.toHaveBeenCalled();

    native.emit('onPlaybackCompleted', {
      responseId: 'response', streamId: 1, generation: 1,
      sessionGeneration: 1,
    } satisfies NativePlaybackCompleted);
    native.emit('onPlaybackCompleted', {
      responseId: 'response', streamId: 1, generation: 1,
      sessionGeneration: 1,
    } satisfies NativePlaybackCompleted);
    expect(completed).toHaveBeenCalledTimes(1);
  });

  it('commits a native completion that arrives before enqueue resolves exactly once', async () => {
    const native = new FakeNativeCallAudio();
    const audio = new AndroidCallAudio({}, native, 'android');
    const completed = jest.fn();
    const stream = { callId: 'call', responseId: 'response', streamId: 1 };
    let resolveEnqueue!: (generation: number) => void;
    native.enqueuePlayback = async () => new Promise<number>((resolve) => { resolveEnqueue = resolve; });
    audio.setConsumptionListener(completed);
    await audio.initialize();

    const enqueue = audio.enqueue({ stream, format: PLAYBACK_FORMAT, payload: new Uint8Array([0, 0]), isFinal: true });
    native.emit('onPlaybackCompleted', {
      responseId: 'response', streamId: 1, generation: 7, sessionGeneration: 1,
    } satisfies NativePlaybackCompleted);
    expect(completed).not.toHaveBeenCalled();
    resolveEnqueue(7);
    await enqueue;
    expect(completed).toHaveBeenCalledTimes(1);
    native.emit('onPlaybackCompleted', {
      responseId: 'response', streamId: 1, generation: 7, sessionGeneration: 1,
    } satisfies NativePlaybackCompleted);
    expect(completed).toHaveBeenCalledTimes(1);
  });

  it('drops an early completion when native enqueue rejects', async () => {
    const native = new FakeNativeCallAudio();
    const audio = new AndroidCallAudio({}, native, 'android');
    const completed = jest.fn();
    const stream = { callId: 'call', responseId: 'response', streamId: 1 };
    let rejectEnqueue!: (error: Error) => void;
    native.enqueuePlayback = async () => new Promise<number>((_resolve, reject) => { rejectEnqueue = reject; });
    audio.setConsumptionListener(completed);
    await audio.initialize();

    const enqueue = audio.enqueue({ stream, format: PLAYBACK_FORMAT, payload: new Uint8Array([0, 0]), isFinal: true });
    native.emit('onPlaybackCompleted', {
      responseId: 'response', streamId: 1, generation: 7, sessionGeneration: 1,
    } satisfies NativePlaybackCompleted);
    rejectEnqueue(new Error('native_enqueue_failed'));

    await expect(enqueue).rejects.toThrow('native_enqueue_failed');
    expect(completed).not.toHaveBeenCalled();
  });

  it('drops an early completion after stop wins the pending enqueue race', async () => {
    const native = new FakeNativeCallAudio();
    const audio = new AndroidCallAudio({}, native, 'android');
    const completed = jest.fn();
    const stream = { callId: 'call', responseId: 'response', streamId: 1 };
    let resolveEnqueue!: (generation: number) => void;
    native.enqueuePlayback = async () => new Promise<number>((resolve) => { resolveEnqueue = resolve; });
    audio.setConsumptionListener(completed);
    await audio.initialize();

    const enqueue = audio.enqueue({ stream, format: PLAYBACK_FORMAT, payload: new Uint8Array([0, 0]), isFinal: true });
    native.emit('onPlaybackCompleted', {
      responseId: 'response', streamId: 1, generation: 7, sessionGeneration: 1,
    } satisfies NativePlaybackCompleted);
    await audio.tombstone(stream);
    resolveEnqueue(7);
    await expect(enqueue).rejects.toThrow('stale_playback_session');

    expect(completed).not.toHaveBeenCalled();
  });

  it('does not carry an early completion across adapter sessions', async () => {
    const native = new FakeNativeCallAudio();
    const audio = new AndroidCallAudio({}, native, 'android');
    const completed = jest.fn();
    const stream = { callId: 'call', responseId: 'response', streamId: 1 };
    let resolveEnqueue!: (generation: number) => void;
    native.enqueuePlayback = async () => new Promise<number>((resolve) => { resolveEnqueue = resolve; });
    audio.setConsumptionListener(completed);
    await audio.initialize();

    const enqueue = audio.enqueue({ stream, format: PLAYBACK_FORMAT, payload: new Uint8Array([0, 0]), isFinal: true });
    native.emit('onPlaybackCompleted', {
      responseId: 'response', streamId: 1, generation: 7, sessionGeneration: 1,
    } satisfies NativePlaybackCompleted);
    await audio.close();
    resolveEnqueue(7);
    await expect(enqueue).rejects.toThrow('stale_playback_session');
    native.capability = { ...native.capability, sessionGeneration: 2 };
    await audio.initialize();

    expect(completed).not.toHaveBeenCalled();
  });

  it('does not let a stale enqueue cleanup erase the new session reservation for the same stream key', async () => {
    const native = new FakeNativeCallAudio();
    const audio = new AndroidCallAudio({}, native, 'android');
    const completed = jest.fn();
    const stream = { callId: 'call', responseId: 'response', streamId: 1 };
    const pending: { resolve(generation: number): void; reject(error: Error): void }[] = [];
    native.enqueuePlayback = async () => new Promise<number>((resolve, reject) => {
      pending.push({ resolve, reject });
    });
    audio.setConsumptionListener(completed);
    await audio.initialize();

    const oldEnqueue = audio.enqueue({
      stream, format: PLAYBACK_FORMAT, payload: new Uint8Array([0, 0]), isFinal: true,
    });
    await audio.close();
    native.capability = { ...native.capability, sessionGeneration: 2 };
    await audio.initialize();
    const newEnqueue = audio.enqueue({
      stream, format: PLAYBACK_FORMAT, payload: new Uint8Array([0, 0]), isFinal: true,
    });
    native.emit('onPlaybackCompleted', {
      responseId: 'response', streamId: 1, generation: 9, sessionGeneration: 2,
    } satisfies NativePlaybackCompleted);

    pending[0].resolve(7);
    await expect(oldEnqueue).rejects.toThrow('stale_playback_session');
    expect(completed).not.toHaveBeenCalled();
    pending[1].resolve(9);
    await newEnqueue;
    expect(completed).toHaveBeenCalledTimes(1);
    native.emit('onPlaybackCompleted', {
      responseId: 'response', streamId: 1, generation: 9, sessionGeneration: 2,
    } satisfies NativePlaybackCompleted);
    expect(completed).toHaveBeenCalledTimes(1);
  });

  it('does not let a stale enqueue rejection erase the new session reservation for the same stream key', async () => {
    const native = new FakeNativeCallAudio();
    const audio = new AndroidCallAudio({}, native, 'android');
    const completed = jest.fn();
    const stream = { callId: 'call', responseId: 'response', streamId: 1 };
    const pending: { resolve(generation: number): void; reject(error: Error): void }[] = [];
    native.enqueuePlayback = async () => new Promise<number>((resolve, reject) => {
      pending.push({ resolve, reject });
    });
    audio.setConsumptionListener(completed);
    await audio.initialize();

    const oldEnqueue = audio.enqueue({
      stream, format: PLAYBACK_FORMAT, payload: new Uint8Array([0, 0]), isFinal: true,
    });
    await audio.close();
    native.capability = { ...native.capability, sessionGeneration: 2 };
    await audio.initialize();
    const newEnqueue = audio.enqueue({
      stream, format: PLAYBACK_FORMAT, payload: new Uint8Array([0, 0]), isFinal: true,
    });
    native.emit('onPlaybackCompleted', {
      responseId: 'response', streamId: 1, generation: 9, sessionGeneration: 2,
    } satisfies NativePlaybackCompleted);

    pending[0].reject(new Error('old_enqueue_failed'));
    await expect(oldEnqueue).rejects.toThrow('old_enqueue_failed');
    pending[1].resolve(9);
    await newEnqueue;

    expect(completed).toHaveBeenCalledTimes(1);
  });

  it('routes the built-in reply failure tone through the initialized native call audio module', async () => {
    const native = new FakeNativeCallAudio();
    const audio = new AndroidCallAudio({}, native, 'android');
    await audio.initialize();

    await audio.playReplyFailureTone();

    expect(native.replyFailureToneCount).toBe(1);
  });

  it('recreates capture effects after reacquiring focus during resume', async () => {
    const native = new FakeNativeCallAudio();
    const audio = new AndroidCallAudio({}, native, 'android');
    const initialized = native.capability;
    native.stopCapture = async () => {
      native.capability = {
        ...initialized,
        aec: { available: true, enabled: false, error: 'aec_not_initialized' },
        noiseSuppressor: { available: true, enabled: false, error: 'noise_suppressor_not_initialized' },
      };
    };
    const start = jest.spyOn(native, 'startCapture').mockImplementation(async () => {
      native.capability = initialized;
      return native.capability;
    });
    await audio.initialize();
    await audio.startCapture(CAPTURE_FORMAT, jest.fn());
    await audio.pauseCapture();

    await expect(audio.resumeCapture()).resolves.toBeUndefined();
    expect(start).toHaveBeenCalledTimes(2);
  });

  it('does not restart capture when focus is denied and still checks recreated effects', async () => {
    const native = new FakeNativeCallAudio();
    const audio = new AndroidCallAudio({}, native, 'android');
    await audio.initialize();
    await audio.pauseCapture();
    const start = jest.spyOn(native, 'startCapture');
    native.capability = {
      ...native.capability,
      available: false,
      reason: 'audio_focus_denied',
      audioFocus: { granted: false },
    };

    await expect(audio.resumeCapture()).rejects.toThrow('audio_focus_denied');
    expect(start).not.toHaveBeenCalled();

    native.capability = {
      ...native.capability,
      available: true,
      reason: 'aec_unavailable',
      audioFocus: { granted: true },
      aec: { available: false, enabled: false },
    };
    await expect(audio.resumeCapture()).rejects.toThrow('aec_unavailable');
    expect(start).toHaveBeenCalledTimes(1);
  });

  it('rejects a late completion after the native stopped receipt tombstones it', async () => {
    const native = new FakeNativeCallAudio();
    const audio = new AndroidCallAudio({}, native, 'android');
    const completed = jest.fn();
    const stream = { callId: 'call', responseId: 'response', streamId: 1 };
    audio.setConsumptionListener(completed);
    await audio.initialize();
    await audio.enqueue({ stream, format: PLAYBACK_FORMAT, payload: new Uint8Array([0, 0]), isFinal: true });

    native.emit('onPlaybackStopped', {
      responseId: 'response', streamId: 1, generation: 2,
      sessionGeneration: 1,
    } satisfies NativePlaybackStopped);
    native.emit('onPlaybackCompleted', {
      responseId: 'response', streamId: 1, generation: 1,
      sessionGeneration: 1,
    } satisfies NativePlaybackCompleted);

    expect(completed).not.toHaveBeenCalled();
  });

  it('tombstones synchronously before awaiting native stop', async () => {
    const native = new FakeNativeCallAudio();
    let releaseStop!: () => void;
    native.stopPlayback = async () => new Promise<void>((resolve) => { releaseStop = resolve; });
    const audio = new AndroidCallAudio({}, native, 'android');
    const completed = jest.fn();
    const stream = { callId: 'call', responseId: 'response', streamId: 1 };
    audio.setConsumptionListener(completed);
    await audio.initialize();
    await audio.enqueue({ stream, format: PLAYBACK_FORMAT, payload: new Uint8Array([0, 0]), isFinal: true });

    const stopping = audio.stop(stream);
    native.emit('onPlaybackCompleted', {
      responseId: 'response', streamId: 1, generation: 1,
      sessionGeneration: 1,
    } satisfies NativePlaybackCompleted);
    expect(completed).not.toHaveBeenCalled();
    releaseStop();
    await stopping;
  });

  it('does not resolve duplicate stop promises before shared native completion', async () => {
    const native = new FakeNativeCallAudio();
    let releaseStop!: () => void;
    const sharedStop = new Promise<void>((resolve) => { releaseStop = resolve; });
    native.stopPlayback = async () => sharedStop;
    const audio = new AndroidCallAudio({}, native, 'android');
    const stream = { callId: 'call', responseId: 'response', streamId: 1 };
    await audio.initialize();
    await audio.enqueue({ stream, format: PLAYBACK_FORMAT, payload: new Uint8Array([0, 0]), isFinal: true });
    const first = audio.stop(stream);
    const duplicate = audio.stop(stream);
    const firstSettled = jest.fn();
    const duplicateSettled = jest.fn();
    void first.then(firstSettled);
    void duplicate.then(duplicateSettled);

    await Promise.resolve();
    expect(firstSettled).not.toHaveBeenCalled();
    expect(duplicateSettled).not.toHaveBeenCalled();

    releaseStop();
    await Promise.all([first, duplicate]);
    expect(firstSettled).toHaveBeenCalledTimes(1);
    expect(duplicateSettled).toHaveBeenCalledTimes(1);
  });

  it('decodes capture bridge Base64 without treating device sequence as wire sequence', async () => {
    const native = new FakeNativeCallAudio();
    const audio = new AndroidCallAudio({}, native, 'android');
    const frames: Pick<NativeCapturedFrame, 'deviceSequence' | 'payloadBase64' | 'format'>[] = [];
    await audio.initialize();
    await audio.startCapture(CAPTURE_FORMAT, (frame) => frames.push({
      deviceSequence: frame.deviceSequence,
      payloadBase64: Buffer.from(frame.payload).toString('base64'),
      format: frame.format as NativeCapturedFrame['format'],
    }));

    native.emit('onCapturedAudio', {
      deviceSequence: 42,
      sessionGeneration: 1,
      payloadBase64: 'AQI=',
      format: CAPTURE_FORMAT as NativeCapturedFrame['format'],
    } satisfies NativeCapturedFrame);

    expect(frames).toEqual([{
      deviceSequence: 42,
      payloadBase64: 'AQI=',
      format: CAPTURE_FORMAT,
    }]);
  });

  it('isolates late events and ledgers across reused adapter sessions', async () => {
    const native = new FakeNativeCallAudio();
    const audio = new AndroidCallAudio({}, native, 'android');
    const completed = jest.fn();
    const stream = { callId: 'new-call', responseId: 'same-response', streamId: 1 };
    audio.setConsumptionListener(completed);
    await audio.initialize();
    await audio.close();
    native.capability = { ...native.capability, sessionGeneration: 2 };
    await audio.initialize();
    await audio.enqueue({ stream, format: PLAYBACK_FORMAT, payload: new Uint8Array([0, 0]), isFinal: true });

    native.emit('onPlaybackCompleted', {
      responseId: 'same-response', streamId: 1, generation: 1, sessionGeneration: 1,
    } satisfies NativePlaybackCompleted);
    expect(completed).not.toHaveBeenCalled();

    native.emit('onPlaybackCompleted', {
      responseId: 'same-response', streamId: 1, generation: 1, sessionGeneration: 2,
    } satisfies NativePlaybackCompleted);
    expect(completed).toHaveBeenCalledTimes(1);
  });

  it('stores only transport-assigned wire sequence values for recovery', async () => {
    const native = new FakeNativeCallAudio();
    const audio = new AndroidCallAudio({}, native, 'android');
    let captured!: Parameters<AndroidCallAudio['recordTransportFrame']>[0];
    await audio.initialize();
    await audio.startCapture(CAPTURE_FORMAT, (frame) => { captured = frame; });
    native.emit('onCapturedAudio', {
      deviceSequence: 77,
      sessionGeneration: 1,
      payloadBase64: 'AQI=',
      format: CAPTURE_FORMAT as NativeCapturedFrame['format'],
    } satisfies NativeCapturedFrame);

    audio.recordTransportFrame(captured, 9001);

    expect(audio.recoveryBuffer.unacknowledgedAfter(0)[0]).toMatchObject({
      deviceSequence: 77,
      wireSequence: 9001,
    });
  });

  it('stays unavailable after native close rejects and refuses new ownership', async () => {
    const native = new FakeNativeCallAudio();
    native.stopSession = async () => { throw new Error('session_termination_failed'); };
    const audio = new AndroidCallAudio({}, native, 'android');
    await audio.initialize();

    await expect(audio.close()).rejects.toThrow('session_termination_failed');
    await expect(audio.initialize()).resolves.toBe('unavailable');
    await expect(audio.startCapture(CAPTURE_FORMAT, jest.fn())).rejects.toThrow('session_termination_failed');
    await expect(audio.enqueue({
      stream: { callId: 'new-call', responseId: 'new-response', streamId: 1 },
      format: PLAYBACK_FORMAT,
      payload: new Uint8Array([0, 0]),
      isFinal: true,
    })).rejects.toThrow('session_termination_failed');
  });

  it('does not leave an in-flight stop pending when native close fails', async () => {
    const native = new FakeNativeCallAudio();
    let rejectStop!: (error: Error) => void;
    native.stopPlayback = async () => new Promise<void>((_resolve, reject) => { rejectStop = reject; });
    native.stopSession = async () => {
      const error = new Error('session_termination_failed');
      rejectStop(error);
      throw error;
    };
    const audio = new AndroidCallAudio({}, native, 'android');
    const stream = { callId: 'call', responseId: 'response', streamId: 1 };
    await audio.initialize();
    await audio.enqueue({ stream, format: PLAYBACK_FORMAT, payload: new Uint8Array([0, 0]), isFinal: true });
    const stopping = audio.stop(stream);

    await expect(audio.close()).rejects.toThrow('session_termination_failed');
    await expect(stopping).rejects.toThrow('session_termination_failed');
  });
});

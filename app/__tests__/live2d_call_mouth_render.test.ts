import fs from 'fs';
import path from 'path';
import vm from 'vm';

describe('production Live2D call mouth bridge', () => {
  it('loads live2d.html and drives ParamMouthOpenY from setCallMouthRms through the real render loop', async () => {
    const html = fs.readFileSync(path.join(process.cwd(), 'public/live2d/live2d.html'), 'utf8');
    const script = html.match(/<script>\s*([\s\S]*?)\s*<\/script>\s*<\/body>/)?.[1];
    expect(script).toBeTruthy();

    const parameterWrites: number[] = [];
    let frame: (() => void) | undefined;
    const canvas = {
      addEventListener: jest.fn(),
      getBoundingClientRect: () => ({ left: 0, top: 0 }),
    };
    const model = {
      width: 100,
      height: 100,
      scale: { set: jest.fn() },
      x: 0,
      y: 0,
      expression: jest.fn(),
      focus: jest.fn(),
      hitTest: jest.fn(() => []),
      eventMode: 'none',
      interactive: false,
      interactiveChildren: false,
      internalModel: {
        eyeBlink: {},
        focusController: { focus: jest.fn() },
        coreModel: { setParameterValueById: jest.fn((_id: string, value: number, weight = 1) => {
          parameterWrites.push((parameterWrites.at(-1) ?? -1) * (1 - weight) + value * weight);
        }) },
      },
    };
    let modelScale = 1;
    Object.defineProperties(model, {
      width: { get: () => 100 * modelScale },
      height: { get: () => 100 * modelScale },
    });
    model.scale.set.mockImplementation((value: number) => { modelScale = value; });
    const sample = new Int16Array(128).fill(1536);
    const lastSources: { onended?: () => void }[] = [];
    const context: any = {
      innerWidth: 360,
      innerHeight: 400,
      console,
      setTimeout,
      clearTimeout,
      Promise,
      Uint8Array,
      Int16Array,
      DataView,
      Math,
      Number,
      JSON,
      performance: { now: () => 0 },
      atob: (value: string) => Buffer.from(value, 'base64').toString('binary'),
      fetch: jest.fn(async () => { throw new Error('asset fixture omitted'); }),
      document: { getElementById: jest.fn(() => canvas) },
      requestAnimationFrame: jest.fn((callback: () => void) => { frame = callback; return 1; }),
      AudioContext: class {
        sampleRate = 48_000;
        state = 'running';
        destination = {};
        currentTime = 0;
        createBuffer(channels: number, frames: number, rate: number) {
          return { duration: frames / rate, getChannelData: () => new Float32Array(frames) };
        }
        createBufferSource() {
          const source = { connect: jest.fn(), start: jest.fn(), stop: jest.fn(), onended: undefined };
          lastSources.push(source);
          return source;
        }
        createAnalyser() {
          return {
            fftSize: 256,
            frequencyBinCount: 128,
            connect: jest.fn(),
            getFloatTimeDomainData: (target: Float32Array) => target.set(Array.from(sample, x => x / 32768), 128),
          };
        }
      },
      window: undefined,
    };
    context.window = context;
    context.addEventListener = jest.fn();
    context.PIXI = {
      Application: class {
        stage = { addChild: jest.fn() };
        ticker = { add: jest.fn() };
      },
      Graphics: class {
        clear() {}
        lineStyle() {}
        drawCircle() {}
      },
      live2d: { Live2DModel: { from: jest.fn(async () => model) } },
    };
    context.ReactNativeWebView = { postMessage: jest.fn() };
    vm.runInNewContext(script!, context, { filename: 'public/live2d/live2d.html' });
    await new Promise((resolve) => setImmediate(resolve));
    await new Promise((resolve) => setImmediate(resolve));
    const resize = context.addEventListener.mock.calls.find(([name]: [string]) => name === 'resize')[1];
    expect(model.width).toBeCloseTo(context.innerWidth * 1.2);
    context.innerHeight = 800;
    context.setPresentationMode('call');
    resize();
    const callWidth = model.width;
    resize();
    expect(model.width).toBe(callWidth);
    expect(model.width).toBeCloseTo(context.innerWidth * 1.75);
    expect(model.y + model.height * 0.93).toBeCloseTo(context.innerHeight * 0.84);
    context.innerHeight = 400;
    context.setPresentationMode('chat');
    expect(model.width).toBeLessThan(callWidth);
    expect(model.y + model.height / 2).toBeCloseTo(context.innerHeight / 2);

    context.setCallMouthRms(0.5);
    for (let index = 0; index < 20; index++) frame?.();
    expect(model.internalModel.coreModel.setParameterValueById).toHaveBeenCalledWith(
      'ParamMouthOpenY', expect.any(Number), 0.3,
    );
    expect(parameterWrites.at(-1)).toBeGreaterThan(0);

    context.setCallMouthRms(0);
    frame?.();
    expect(parameterWrites.at(-1)).toBeGreaterThan(-1);
    const afterOneSilentFrame = parameterWrites.at(-1)!;
    for (let index = 0; index < 20; index++) frame?.();
    expect(parameterWrites.at(-1)).toBeLessThan(afterOneSilentFrame);
    context.resetCallMouth();
    expect(parameterWrites.at(-1)).toBe(-1);
    const writesAtReset = parameterWrites.length;
    frame?.();
    expect(parameterWrites).toHaveLength(writesAtReset);
    expect(context.ReactNativeWebView.postMessage).toHaveBeenCalledWith(JSON.stringify({
      type: 'mouthAnalysisWindow', sampleRate: 48_000, samples: 128,
    }));
    const pcm = Buffer.from(sample.buffer).toString('base64');
    await context.feedAudioChunk(pcm, false);
    frame?.();
    const chatValue = parameterWrites.at(-1);
    context.stopServerAudio();
    expect(parameterWrites.at(-1)).toBe(-1);
    context.setCallMouthRms(1536 / 32768);
    frame?.();
    expect(parameterWrites.at(-1)).toBeCloseTo(chatValue!);
    lastSources[0].onended?.();
    expect(parameterWrites.at(-1)).toBeCloseTo(chatValue!);
    context.resetCallMouth();
    await context.feedAudioChunk(pcm, false);
    await context.feedAudioChunk('', true);
    lastSources.at(-1)?.onended?.();
    expect(parameterWrites.at(-1)).toBe(-1);
    const mouthBridgeSource = context.setCallMouthRms.toString();
    expect(mouthBridgeSource).not.toContain('feedAudioChunk');
  });
});

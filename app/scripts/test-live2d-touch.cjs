/* global __dirname */
const assert = require('node:assert/strict');
const { test } = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '../public/live2d');

async function loadPage() {
  const html = fs.readFileSync(path.join(root, 'live2d.html'), 'utf8');
  const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
  const listeners = {};
  const messages = [];
  const circles = [];
  const styles = [];
  let tick;
  let now = 2000;
  let settings;
  const model = {
    width: 100, height: 100, scale: { set() {} }, expression() {},
    internalModel: { eyeBlink: {}, focusController: { focus() {} } },
    // 用固定矩形代替 GPU 模型几何；区域名称必须来自页面实际加载的资源。
    hitTest: (x, y) => x >= 0 && x < 100 && y >= 0 && y < 100
      ? settings.HitAreas.filter(area => area.Name === '头').map(area => area.Name) : [],
  };
  const context = {
    console, performance: { now: () => now }, innerWidth: 100, innerHeight: 100,
    addEventListener() {}, requestAnimationFrame() {},
    document: { getElementById: () => ({
      addEventListener: (name, handler) => { listeners[name] = handler; },
      getBoundingClientRect: () => ({ left: 10, top: 20 }),
    }) },
    fetch: async url => ({
      ok: true,
      json: async () => JSON.parse(fs.readFileSync(path.join(root, url), 'utf8')),
      arrayBuffer: async () => new ArrayBuffer(0),
    }),
    AudioContext: class {
      sampleRate = 48000;
      createAnalyser() { return { connect() {}, frequencyBinCount: 128 }; }
    },
    PIXI: {
      Application: class {
        stage = { addChild() {} };
        ticker = { add: callback => { tick = callback; } };
      },
      Graphics: class {
        clear() {}
        lineStyle(...args) { styles.push(args); }
        drawCircle(...args) { circles.push(args); }
      },
      live2d: { Live2DModel: { from: async url => {
        settings = JSON.parse(fs.readFileSync(path.join(root, url), 'utf8'));
        return model;
      } } },
    },
    ReactNativeWebView: { postMessage: value => messages.push(JSON.parse(value)) },
  };
  context.window = context;
  vm.runInNewContext(script, context);
  await new Promise(resolve => setImmediate(resolve));
  assert.ok(messages.some(message => message.type === 'modelLoaded' && message.success));
  return { listeners, messages, circles, styles, settings, tick: () => tick(1),
    advance: () => { now += 1100; } };
}

test('有效触摸显示扩散蓝环并向原生端发送触摸区域，空白区域不触发', async () => {
  const page = await loadPage();
  const original = JSON.parse(fs.readFileSync(
    path.resolve(root, '../../assets/live2d/models/luo/model.model3.json'), 'utf8',
  ));
  assert.ok(page.settings.HitAreas.length > 0);
  assert.deepEqual(page.settings.HitAreas, original.HitAreas);
  for (const name of ['pointerdown', 'touchstart']) {
    const before = page.messages.length;
    const event = name === 'pointerdown'
      ? { clientX: 60, clientY: 70 } : { touches: [{ clientX: 60, clientY: 70 }] };
    page.listeners[name](event);
    assert.deepEqual(page.messages.slice(before), [{
      type: 'touch', touchArea: ['头'], timeSinceLastSentTouch: name === 'pointerdown' ? 2 : 1.1,
      touchCount: 1,
    }]);
    page.tick();
    const first = page.circles.at(-1);
    assert.deepEqual(first.slice(0, 2), [50, 50]);
    assert.equal(page.styles.at(-1)[1], 0xADD8E6);
    const alpha = page.styles.at(-1)[2];
    page.tick();
    assert.ok(page.circles.at(-1)[2] > first[2]);
    assert.ok(page.styles.at(-1)[2] < alpha);
    for (let i = 0; i < 40; i++) page.tick();
    const count = page.circles.length;
    page.tick();
    assert.equal(page.circles.length, count);
    page.advance();
  }
  const messageCount = page.messages.length;
  const circleCount = page.circles.length;
  page.listeners.touchstart({ touches: [{ clientX: 210, clientY: 220 }] });
  page.tick();
  assert.equal(page.messages.length, messageCount);
  assert.equal(page.circles.length, circleCount);
});

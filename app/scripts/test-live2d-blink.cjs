const assert = require('node:assert/strict');
const { test } = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const appRoot = path.resolve(__dirname, '..');
for (const root of ['assets', 'public']) {
  for (const name of ['model.model3.json', 'model.model3_copy.json']) {
    test(`${root}/${name} declares both blink parameters`, () => {
      const data = JSON.parse(fs.readFileSync(path.join(appRoot, root, 'live2d/models/luo', name), 'utf8'));
      const groups = data.Groups.filter(group => group.Name === 'EyeBlink');
      assert.equal(groups.length, 1);
      assert.equal(groups[0].Target, 'Parameter');
      assert.deepEqual(groups[0].Ids, ['ParamEyeLOpen', 'ParamEyeROpen']);
    });
  }
}
for (const page of ['live2d.html', 'live2d_with_debug.html', 'live2d copy.html']) {
  test(`${page}: blink pauses for dumb and resumes for other expressions`, () => {
    const html = fs.readFileSync(path.join(appRoot, 'public/live2d', page), 'utf8');
    for (const match of html.matchAll(/<script>([\s\S]*?)<\/script>/g)) new vm.Script(match[1]);
    const handler = html.match(/window\.setExpression = \(expressionId\) => \{[\s\S]*?\n    \};/)[0];
    const controller = { updateParameters() {} };
    const expressions = [];
    const model = { internalModel: { eyeBlink: controller }, expression: id => expressions.push(id) };
    const context = vm.createContext({ model, autoEyeBlink: controller, mouthValueProjection: {}, window: { setMouthOpenY() {} } });
    vm.runInContext(handler, context);
    context.window.setExpression('normal');
    assert.equal(model.internalModel.eyeBlink, controller);
    context.window.setExpression('dumb');
    assert.equal(model.internalModel.eyeBlink, undefined);
    context.window.setExpression('dumb');
    context.window.setExpression('sing');
    assert.equal(model.internalModel.eyeBlink, controller);
    assert.deepEqual(expressions, ['normal', 'dumb', 'dumb', 'sing']);
    context.model = undefined;
    assert.doesNotThrow(() => context.window.setExpression('normal'));
  });
}

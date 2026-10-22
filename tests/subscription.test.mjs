// Детерминированные проверки контракта интерфейса на подменённом DOM.
// Не заменяют визуальную приёмку в браузере.
import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
const source = readFileSync(new URL('../ui/studio/subscription.js', import.meta.url), 'utf8');

class Element {
  constructor(tag = 'div') { this.tag = tag; this.children = []; this.fields = {}; this.dataset = {}; this.value = ''; this.textContent = ''; }
  appendChild(child) { this.children.push(child); }
  get options() { return this.children; }
  get selectedIndex() { return this.children.findIndex(c => c.value === this.value); }
  set innerHTML(value) {
    this.children = []; this.html = value;
    if (this.tag === 'div') {
      for (const key of ['.res', 'small', '.head input', '.head .btn', ...['transport', 'account', 'model', 'export', 'usage', 'history', 'memory_read', 'memory_write', 'tasks', 'project_read', 'task_limit'].map(k => `[data-field="${k}"]`)]) this.fields[key] = new Element(['transport', 'account', 'model'].some(k => key.includes(k)) ? 'select' : 'input');
      this.buttons = ['profiles', 'login-new', 'login', 'models', 'health', 'disconnect', 'remove', 'use-tasks'].map(op => Object.assign(new Element('button'), {dataset: {op}}));
    }
  }
}
function fixture() {
  const root = new Element(), add = new Element('button'), calls = [];
  const context = vm.createContext({document: {createElement: tag => new Element(tag)},
    $: (s, r) => r ? r.fields[s] : add, $$: (s, r) => r.buttons,
    S: {llm: {active: 'old', profiles: {old: {kind: 'openai'}, p: {kind: 'chatgpt_subscription', model: '', subscription_profile_id: 'A'}}}},
    openProf: null, uid: () => 'new', toast: () => {}, confirm: () => true, renderProfiles: () => {},
    core: {call: async (op, args) => { calls.push([op, args]); return {ok: true, data: {dependency_ready: true, profiles: [], models: [{id: 'm1', label: 'Model One'}]}}; }} });
  context.save = async patch => { context.S = JSON.parse(JSON.stringify({...context.S, ...patch, llm: {...context.S.llm, ...patch.llm}})); };
  vm.runInContext(source, context);
  context.renderSubscriptionProfile(root, 'p', context.S.llm.profiles.p);
  return {context, add, calls, el: root.children[0]};
}
test('rendering and adding do not call network or auto-activate subscription', async () => {
  const f = fixture(); assert.equal(f.calls.length, 0);
  f.add.onclick(); await Promise.resolve();
  assert.equal(f.calls.length, 0); assert.equal(f.context.S.llm.active, 'old');
  assert.equal(f.context.S.llm.profiles.new.kind, 'chatgpt_subscription');
  assert.equal(f.context.S.llm.profiles.new.subscription_transport, 'codex');
  assert.equal(f.context.S.llm.profiles.new.subscription_usage_reviewed, false);
});
test('model choice and both acknowledgements survive cloned settings snapshots', async () => {
  const f = fixture(), field = k => f.el.fields[`[data-field="${k}"]`];
  await f.el.buttons.find(b => b.dataset.op === 'models').onclick();
  field('model').value = 'm1'; await field('model').onchange();
  await field('export').onchange({target: {checked: true}});
  await field('usage').onchange({target: {checked: true}});
  const p = f.context.S.llm.profiles.p;
  assert.equal(p.model, 'm1'); assert.equal(p.subscription_export, true); assert.equal(p.subscription_usage_reviewed, true);
  assert.deepEqual(f.calls.map(c => c[0]), ['subscription_models']);
  await f.el.fields['.head input'].onclick({stopPropagation() {}, target: {}});
  assert.equal(f.context.S.llm.active, 'p');
});
test('activation is blocked without consent and a model', async () => {
  const f = fixture(), input = {checked: true};
  await f.el.fields['.head input'].onclick({stopPropagation() {}, target: input});
  assert.equal(input.checked, false); assert.equal(f.context.S.llm.active, 'old');
});
test('account switch clears model and consent', async () => {
  const f = fixture(), select = f.el.fields['[data-field="account"]'];
  select.appendChild(Object.assign(new Element('option'), {value: 'B', textContent: 'Account B'}));
  select.value = 'B'; await select.onchange();
  const p = f.context.S.llm.profiles.p;
  assert.equal(p.subscription_profile_id, 'B'); assert.equal(p.model, ''); assert.equal(p.subscription_export, false); assert.equal(p.subscription_usage_reviewed, false);
});
test('health uses only the offline endpoint', async () => {
  const f = fixture(); await f.el.buttons.find(b => b.dataset.op === 'health').onclick();
  assert.deepEqual(f.calls.map(c => c[0]), ['subscription_health']);
  assert.equal(f.calls[0][1].transport, 'siwc'); // Older profiles never migrate silently.
});

test('explicit transport change clears account model and consents without login', async () => {
  const f = fixture();
  await f.el.fields['[data-field="transport"]'].onchange({target: {value: 'codex'}});
  const p = f.context.S.llm.profiles.p;
  assert.equal(p.subscription_transport, 'codex');
  assert.equal(p.subscription_profile_id, ''); assert.equal(p.model, '');
  assert.equal(p.subscription_export, false); assert.equal(p.subscription_usage_reviewed, false);
  assert.equal(f.calls.length, 0);
  await f.el.buttons.find(b => b.dataset.op === 'health').onclick();
  assert.equal(f.calls[0][1].transport, 'codex');
});

test('late login result cannot cross a transport change', async () => {
  const f = fixture(); let finish;
  f.context.core.call = () => new Promise(resolve => { finish = resolve; });
  const pending = f.el.buttons.find(b => b.dataset.op === 'login-new').onclick();
  await f.el.fields['[data-field="transport"]'].onchange({target: {value: 'codex'}});
  finish({ok: true, data: {profile: 'old-siwc-login', sharing: true}});
  await pending;
  assert.equal(f.context.S.llm.profiles.p.subscription_profile_id, '');
  assert.match(f.el.fields['.res'].textContent, /Результат старой операции/);
});

test('extra grants default off and do not contact the backend', async () => {
  const f = fixture();
  for (const k of ['history', 'memory_read', 'memory_write', 'tasks', 'project_read']) assert.equal(f.el.fields[`[data-field="${k}"]`].checked, false);
  assert.equal(f.calls.length, 0);
});

test('Codex grants persist independently and reset on account change', async () => {
  const f = fixture();
  await f.el.fields['[data-field="transport"]'].onchange({target: {value: 'codex'}});
  for (const k of ['history', 'memory_read', 'memory_write', 'tasks', 'project_read']) await f.el.fields[`[data-field="${k}"]`].onchange({target: {checked: true}});
  assert.equal(f.context.S.llm.profiles.p.subscription_memory_write, true);
  assert.ok(f.context.S.llm.profiles.p.subscription_scope_revision);
  const select = f.el.fields['[data-field="account"]'];
  select.appendChild(Object.assign(new Element('option'), {value: 'B', textContent: 'B'})); select.value = 'B';
  await select.onchange();
  for (const k of ['history', 'memory_read', 'memory_write', 'tasks', 'project_read']) assert.equal(f.context.S.llm.profiles.p['subscription_' + k], false);
  assert.equal(f.calls.length, 0);
});

test('task assignment is guarded and does not start a task', async () => {
  const f = fixture(), button = f.el.buttons.find(b => b.dataset.op === 'use-tasks');
  await button.onclick(); assert.equal(f.context.S.tasks, undefined);
  await f.el.fields['[data-field="transport"]'].onchange({target: {value: 'codex'}});
  const select = f.el.fields['[data-field="account"]'];
  select.value = 'A'; await select.onchange();
  f.el.fields['[data-field="model"]'].value = 'm1'; await f.el.fields['[data-field="model"]'].onchange();
  for (const k of ['tasks', 'export', 'usage']) await f.el.fields[`[data-field="${k}"]`].onchange({target: {checked: true}});
  await button.onclick(); assert.equal(f.context.S.tasks.llm, 'p'); assert.equal(f.calls.length, 0);
});

test('task request limit rejects invalid numbers', async () => {
  const f = fixture(), field = f.el.fields['[data-field="task_limit"]'];
  for (const value of ['0', '21', '1.5', 'NaN']) await field.onchange({target: {value}});
  assert.equal(f.context.S.llm.profiles.p.subscription_task_limit, undefined);
  await field.onchange({target: {value: '7'}}); assert.equal(f.context.S.llm.profiles.p.subscription_task_limit, 7);
});

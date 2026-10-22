// Контракт локальной панели: назначения, свежесть, отсутствие сетевого вызова модели.
// Подменённый DOM проверяет логику, но не заменяет визуальную приёмку окна Dewiar.
import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
const source = readFileSync(new URL('../ui/studio/brains.js', import.meta.url), 'utf8');
class Element {
  constructor(tag = 'div') { this.tag = tag; this.children = []; this.dataset = {}; this.value = ''; this.textContent = ''; this.classList = {contains: () => true}; }
  appendChild(child) { this.children.push(child); }
  replaceChildren() { this.children = []; }
  contains(child) { return child === this || this.children.some(c => c.contains(child)); }
  addEventListener(event, cb) { this[event] = cb; }
  set innerHTML(_) { throw Error('Untrusted HTML must not be inserted'); }
}
function fixture() {
  const elements = {}, calls = [], listeners = {}, timers = [];
  const el = s => elements[s] ||= new Element();
  const context = vm.createContext({
    document: {createElement: tag => new Element(tag), activeElement: null, hidden: false},
    $: el, $$: () => el('#brain-routes').children.map(c => c.children[0]),
    S: {llm: {active: 'a', profiles: {a: {name: '<b>Same</b>'}, b: {name: '<b>Same</b>'}}, routes: {diary: 'gone'}}, tasks: {llm: 'b'}},
    toast: () => {}, setInterval: cb => timers.push(cb),
    core: {on: (event, cb) => { listeners[event] = cb; }, call: async (op, args) => {
      calls.push([op, args]);
      return op === 'brain_watch_status' ? {journal: true, observed_at: 1000, runs: [], events: []} : context.S;
    }},
  });
  vm.runInContext(source, context);
  return {context, el, calls, listeners, timers};
}
test('render preserves identity despite duplicate names and shows missing binding without fallback', () => {
  const f = fixture(); f.context.renderBrainRoutes();
  const fields = f.el('#brain-routes').children.map(c => c.children[0]);
  assert.equal(fields[0].value, 'b');
  assert.equal(fields[3].value, 'gone');
  assert.deepEqual(Array.from(fields[0].children, c => c.value), ['', 'a', 'b']);
  assert.equal(fields[0].children[1].textContent, '<b>Same</b>');
  assert.equal(f.calls.length, 0);
});
test('assignments use only local route command, not settings probe or model request', async () => {
  const f = fixture(); f.context.renderBrainRoutes();
  await f.el('#brain-routes-save').onclick();
  assert.deepEqual(f.calls.map(c => c[0]), ['brain_routes_set']);
  assert.equal(f.calls[0][1].routes.tasks, 'b');
});
test('heartbeat and observation settings use local commands only', async () => {
  const f = fixture(); f.context.renderBrainRoutes();
  await f.context.refreshBrainWatch();
  await f.el('#brain-watch-save').onclick();
  assert.deepEqual(f.calls.map(c => c[0]), ['brain_watch_status', 'brain_watch_set', 'brain_watch_status']);
  assert.equal(f.calls[1][1].stale_seconds, 90);
});
test('settings event renders received snapshot, not old global settings', () => {
  const f = fixture(); const next = {llm: {profiles: {new: {name: 'New'}}}, tasks: {llm: 'new'}};
  f.listeners.settings({settings: next});
  assert.equal(f.el('#brain-routes').children[0].children[0].value, 'new');
  assert.equal(f.el('#brains-count').textContent, 'Подключённые мозги · 1');
});
test('status and names are plain text; polling cannot prove success or acceptance', async () => {
  const f = fixture();
  f.context.core.call = async op => ({observed_at: 1000, journal: true, profiles: {p: '<script>private</script>'},
    runs: [{profile: 'p', role: 'chat', state: 'no_fresh_signal', elapsed_s: 92, last_signal: 908}],
    events: [{at: 1000, kind: '<img onerror=bad>', ref: 'r'}]});
  await f.context.refreshBrainWatch();
  assert.match(f.el('#brain-runs').children[0].textContent, /исход неизвестен/);
  assert.match(f.el('#brain-events').textContent, /<img onerror=bad>/);
});
test('hidden page does not poll; foreground poll only reads local status', async () => {
  const f = fixture(); f.context.document.hidden = true; f.timers[0]();
  assert.equal(f.calls.length, 0);
  f.context.document.hidden = false; f.timers[0](); await Promise.resolve();
  assert.deepEqual(f.calls.map(c => c[0]), ['brain_watch_status']);
});
test('disconnected core displays unknown instead of healthy', async () => {
  const f = fixture(); f.context.core.call = async () => { throw Error('offline'); };
  await f.context.refreshBrainWatch();
  assert.match(f.el('#brain-watch-state').textContent, /Состояние моделей неизвестно/);
});

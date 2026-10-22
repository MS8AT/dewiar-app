// Подтверждение в студии: восстановление вопроса, nonce и гонка со старым чтением.
import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
const source = readFileSync(new URL('../ui/studio/subscription_confirm.js', import.meta.url), 'utf8');
function fixture(first = null) {
  const body = {children: [], appendChild(x) { this.children.push(x); }}, events = {}, calls = [];
  const createElement = () => ({children: [], style: {}, setAttribute() {}, appendChild(x) { this.children.push(x); },
    remove() { body.children = body.children.filter(x => x !== this); }});
  const core = {on: (name, fn) => { events[name] = fn; }, call: async (name, args) => {
    calls.push([name, args]); return name === 'subscription_confirm_get' ? (first || {ok: true, data: null}) : {ok: true};
  }};
  vm.runInNewContext(source, {core, document: {body, createElement}, window: {addEventListener() {}}, setInterval() {}, toast() {}});
  return {body, events, calls};
}
const tick = () => new Promise(resolve => setImmediate(resolve));
test('reload restores pending confirmation with plain text and exact nonce', async () => {
  const f = fixture({ok: true, data: {id: 'a', text: '<script>not HTML</script>'}}); await tick();
  assert.equal(f.body.children.length, 1);
  assert.equal(f.body.children[0].children[0].textContent, '<script>not HTML</script>');
  await f.body.children[0].children[1].onclick();
  assert.equal(f.calls[1][0], 'subscription_confirm_answer');
  assert.equal(f.calls[1][1].id, 'a'); assert.equal(f.calls[1][1].ok, true);
  assert.equal(f.body.children.length, 0);
});
test('duplicate event does not duplicate dialog and completion closes it', async () => {
  const f = fixture(); await tick();
  const e = {id: 'b', source: 'subscription', text: 'question'};
  f.events.confirm(e); f.events.confirm(e);
  assert.equal(f.body.children.length, 1);
  f.events.confirm_done({id: 'other'}); assert.equal(f.body.children.length, 1);
  f.events.confirm_done({id: 'b'}); assert.equal(f.body.children.length, 0);
  assert.equal(f.calls.length, 1);
});
test('late initial read cannot overwrite a newer event', async () => {
  let resolve;
  const f = fixture(new Promise(r => { resolve = r; }));
  f.events.confirm({id: 'new', source: 'subscription', text: 'new question'});
  resolve({ok: true, data: {id: 'old', text: 'old question'}}); await tick();
  assert.equal(f.body.children[0].children[0].textContent, 'new question');
  await f.body.children[0].children[2].onclick();
  assert.equal(f.calls[1][1].id, 'new'); assert.equal(f.calls[1][1].ok, false);
});

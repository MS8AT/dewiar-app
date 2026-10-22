// Панель форка: не предлагать upstream EXE и не выдавать старые сведения за свежие.
import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
const source = readFileSync(new URL('../ui/studio/tasks.js', import.meta.url), 'utf8');
const start = source.indexOf('function renderUpdate(u)');
const fn = source.slice(start, source.indexOf('\n}', start) + 2);
function fixture() {
  const els = {};
  const context = vm.createContext({$: s => els[s] ||= {style: {}, textContent: '', onclick: () => {}},
    md: () => { throw Error('Fork notes must be plain text'); }});
  vm.runInContext(fn, context);
  return {els, context};
}
test('unconfigured fork does not claim latest and has no installer action', () => {
  const f = fixture(); f.context.renderUpdate({current: '0.39.2', fork: {product: 'MS8AT8DWiar', build: 2, message: 'Не настроен'}});
  assert.match(f.els['#up-state'].textContent, /Не настроен/);
  assert.match(f.els['#up-state'].textContent, /ещё не выполнялась/);
  assert.equal(f.els['#up-install'].style.display, 'none');
  assert.equal(f.els['#up-install'].onclick, null);
});
test('cached discovery is labeled stale after failed check; notes stay text', () => {
  const f = fixture(); f.context.renderUpdate({current: '0.39.2', fork: {product: 'MS8AT8DWiar', build: 2,
    message: 'Не настроен', discovery: {attempted_at: 2000, error: 'network_or_manifest_error'}},
    upstream: {version: '0.40.0', checked_at: 1000, newer: true, notes: '<img onerror=bad>'}});
  assert.match(f.els['#up-state'].textContent, /устаревшими/);
  assert.match(f.els['#up-state'].textContent, /Сведения получены/);
  assert.equal(f.els['#up-notes'].textContent, '<img onerror=bad>');
});

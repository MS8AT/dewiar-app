import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const source = readFileSync(new URL('../ui/studio/tasks.js', import.meta.url), 'utf8');

test('task card exposes immediate read-only API log strip and detailed tab', () => {
  assert.match(source, /core\.call\("task_observe", \{id\}\)/);
  assert.match(source, /renderTaskObserveStrip\(observation\)/);
  assert.match(source, /API \/ Лог/);
  assert.match(source, /Лог не содержит промпты, ответы, аргументы, пути, имена аккаунтов или секреты/);
});

test('Human Memory is represented only by connector state and scope fingerprint', () => {
  assert.match(source, /scope_ref/);
  assert.match(source, /human_memory\.connector\.state/);
  assert.doesNotMatch(source, /human_memory_scope/);
});

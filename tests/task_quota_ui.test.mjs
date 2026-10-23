// Проекция квоты в UI: исчерпание не маскируется обычной кнопкой «Продолжить».
import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';

const source = readFileSync(new URL('../ui/studio/task_quota.js', import.meta.url), 'utf8');
const context = vm.createContext({});
vm.runInContext(source, context);

test('normal task has no quota-specific action', () => {
  assert.equal(context.taskQuotaAction({subscription_quota: {valid: true, exhausted: false}}), null);
  assert.equal(context.taskQuotaAction({}), null);
});

test('exhausted task gets an explicit bounded grant action', () => {
  const action = context.taskQuotaAction({subscription_quota: {
    valid: true, exhausted: true, can_grant: true, grant_default: 5, max_limit: 100
  }});
  assert.equal(action.kind, 'grant');
  assert.equal(action.count, 5);
  assert.match(action.label, /ещё 5/);
});

test('maximum and malformed grants are blocked', () => {
  for (const quota of [
    {valid: true, exhausted: true, can_grant: false, max_limit: 100},
    {valid: true, exhausted: true, can_grant: true, grant_default: 21, max_limit: 100},
    {valid: true, exhausted: true, can_grant: true, grant_default: '5', max_limit: 100}
  ]) assert.equal(context.taskQuotaAction({subscription_quota: quota}).kind, 'blocked');
});

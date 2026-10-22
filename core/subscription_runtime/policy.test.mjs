import test from 'node:test';
import assert from 'node:assert/strict';
import {validate, execute, safeSession, safeProfiles, errorCode} from './policy.mjs';

const request = extra => ({v: 1, id: 'test_1', op: 'generate', profile: 'account_A', model: 'account-model',
  text: 'synthetic prompt', local_only: false, network: true, export_current_text: true, usage_reviewed: true, ...extra});
const signal = () => new AbortController().signal;
const client = () => ({calls: [],
  async selectProfile(id) { this.calls.push(['select', id]); return {profileId: id, status: 'connected', sharing: true}; },
  async streamResponse(args) { this.calls.push(['generate', args]); return {text: 'synthetic reply'}; }});

test('valid explicit request', () => assert.equal(validate(request()).profile, 'account_A'));
for (const [name, changes, code] of [
  ['local only', {local_only: true}, 'network_denied'],
  ['no network permission', {network: false}, 'network_denied'],
  ['no export consent', {export_current_text: false}, 'consent_required'],
  ['no Usage acknowledgement', {usage_reviewed: false}, 'consent_required'],
  ['no profile', {profile: ''}, 'profile_required'],
  ['unknown tool field', {tools: []}, 'invalid_request'],
  ['history field', {messages: []}, 'invalid_request'],
  ['unknown parameter', {temperature: 0.7}, 'invalid_request'],
  ['oversized text', {text: 'x'.repeat(32769)}, 'invalid_request'],
  ['invalid model', {model: '../bad'}, 'invalid_request'],
  ['old protocol', {v: 0}, 'invalid_request'],
  ['non-boolean policy', {local_only: 'false'}, 'invalid_request'],
]) test(name, () => assert.throws(() => validate(request(changes)), e => e.code === code));

test('only current user text is forwarded; selected profile is explicit', async () => {
  const c = client(), r = await execute(request(), c, signal());
  assert.deepEqual(c.calls[0], ['select', 'account_A']);
  assert.deepEqual(Object.keys(c.calls[1][1]).sort(), ['input', 'model', 'signal']);
  assert.deepEqual(c.calls[1][1].input, [{role: 'user', content: 'synthetic prompt'}]);
  assert.equal(r.completed, true); assert.equal(r.profile, 'account_A');
});
test('mismatched selection cannot send', async () => {
  const c = client(); c.selectProfile = async () => ({profileId: 'account_B', status: 'connected', sharing: true});
  await assert.rejects(execute(request(), c, signal()), e => e.code === 'sharing_required');
  assert.equal(c.calls.length, 0);
});
test('identity alone without plan sharing cannot send', async () => {
  const c = client(); c.selectProfile = async () => ({profileId: 'account_A', status: 'connected', sharing: false});
  await assert.rejects(execute(request(), c, signal()), e => e.code === 'sharing_required');
});
test('SDK failure is never retried or marked completed', async () => {
  const c = client(); let calls = 0;
  c.streamResponse = async () => { calls++; throw Object.assign(new Error('synthetic private detail'), {code: 'stream_interrupted'}); };
  await assert.rejects(execute(request(), c, signal())); assert.equal(calls, 1);
});
test('cancellation before selection has zero effects', async () => {
  const c = client(), a = new AbortController(); a.abort();
  await assert.rejects(execute(request(), c, a.signal)); assert.equal(c.calls.length, 0);
});
test('safe projections omit raw provider errors and credentials', () => {
  const s = safeSession({status: 'connected', sharing: true, profileId: 'A', error: {message: 'secret'}, accessToken: 'secret'});
  assert.equal(JSON.stringify(s).includes('secret'), false);
  const ps = safeProfiles([{id: 'A', label: 'test', status: 'connected', sharing: true, accessToken: 'secret'}]);
  assert.equal(JSON.stringify(ps).includes('secret'), false);
  assert.equal(errorCode(new Error('private secret')), 'subscription_failed');
});
test('status and health schemas disallow prompt payload', () => {
  assert.throws(() => validate({v: 1, id: 'a', op: 'profiles', local_only: true, text: 'private'}));
  assert.doesNotThrow(() => validate({v: 1, id: 'a', op: 'health', local_only: true}));
});

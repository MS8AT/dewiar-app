// Чистые проверки SIWC: без транспорта и секретов.
// Один процесс выполняет одну явно выбранную операцию.
export class SafeError extends Error {
  constructor(code) { super(code); this.code = code; }
}
const fail = code => { throw new SafeError(code); };
const text = (v, n) => typeof v === 'string' && v.length > 0 && v.length <= n;
const id = v => text(v, 128) && /^[a-zA-Z0-9_-]+$/.test(v);
const networkOps = new Set(['login', 'models', 'generate', 'disconnect']);
export function validate(r) {
  if (!r || typeof r !== 'object' || Array.isArray(r)) fail('invalid_request');
  const allowed = new Set(['v', 'id', 'op', 'profile', 'model', 'text', 'network', 'local_only', 'export_current_text', 'usage_reviewed']);
  if (Object.keys(r).some(k => !allowed.has(k)) || r.v !== 1 || !id(r.id)) fail('invalid_request');
  if (!['health', 'profiles', ...networkOps].includes(r.op)) fail('invalid_request');
  if (typeof r.local_only !== 'boolean') fail('invalid_request');
  if (networkOps.has(r.op) && (r.local_only || r.network !== true)) fail('network_denied');
  if (['models', 'generate', 'disconnect'].includes(r.op) && !id(r.profile)) fail('profile_required');
  if (r.op === 'login' && r.profile !== undefined && !id(r.profile)) fail('invalid_request');
  if (r.op === 'generate') {
    if (r.export_current_text !== true || r.usage_reviewed !== true) fail('consent_required');
    if (!text(r.text, 32768) || !text(r.model, 128) || !/^[a-zA-Z0-9._:-]+$/.test(r.model)) fail('invalid_request');
  } else if (['model', 'text', 'export_current_text', 'usage_reviewed'].some(k => k in r)) fail('invalid_request');
  return r;
}
export function safeSession(s) {
  return {status: ['disconnected', 'connecting', 'connected', 'reauth_required'].includes(s.status) ? s.status : 'disconnected',
    sharing: s.sharing === true, profile: typeof s.profileId === 'string' ? s.profileId : ''};
}
export function safeProfiles(ps) {
  return ps.map(p => ({id: p.id, label: String(p.label || p.identity?.email || 'ChatGPT').slice(0, 200),
    status: p.status, sharing: p.sharing === true, pending: p.pending === true}));
}
export async function execute(r, client, signal) {
  validate(r);
  signal.throwIfAborted();
  if (r.op === 'profiles') return {profiles: safeProfiles(await client.listProfiles())};
  if (r.op === 'login') return safeSession(await client.signIn({
    ...(r.profile ? {profileId: r.profile, reconsent: true} : {newProfile: true}), signal}));
  // Выбор аккаунта и операция должны выполняться под одним системным мьютексом.
  const session = await client.selectProfile(r.profile);
  signal.throwIfAborted();
  if (r.op === 'disconnect') { await client.disconnect(); return {disconnected: true}; }
  if (session.profileId !== r.profile || session.status !== 'connected' || session.sharing !== true) fail('sharing_required');
  if (r.op === 'models') return {models: (await client.listModels({signal})).map(m => ({id: m.slug, label: m.displayName}))};
  // Не передаём историю, инструкции, инструменты, вложения и параметры генерации.
  const result = await client.streamResponse({model: r.model, input: [{role: 'user', content: r.text}], signal});
  signal.throwIfAborted();
  if (!result || typeof result.text !== 'string' || !result.text.trim() || result.text.length > 1024 * 1024) fail('invalid_response');
  return {text: result.text, completed: true, profile: r.profile};
}
export function errorCode(e) {
  const known = new Set(['invalid_request', 'network_denied', 'profile_required', 'consent_required',
    'sharing_required', 'invalid_response', 'busy', 'storage_unavailable', 'dependency_unavailable',
    'cancelled', 'reauth_required', 'rate_limit_exceeded', 'insufficient_quota', 'network_error',
    'stream_interrupted', 'response_incomplete', 'revocation_failed', 'invalid_grant', 'access_denied']);
  return known.has(e?.code) ? e.code : 'subscription_failed';
}

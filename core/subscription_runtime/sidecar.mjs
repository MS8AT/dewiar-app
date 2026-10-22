// Отдельный SIWC-транспорт; SDK не поставляется с этим дополнением.
// Сеансы хранятся через Windows-помощник, без вывода секретов.
import {spawn} from 'node:child_process';
import {createInterface} from 'node:readline';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {dirname, join, resolve} from 'node:path';
import {existsSync} from 'node:fs';
import {SafeError, validate, execute, errorCode} from './policy.mjs';

const root = dirname(fileURLToPath(import.meta.url));
const python = process.env.WORKBOOK_SIWC_PYTHON || resolve(root, '../../../python/python.exe');
const helper = join(root, 'windows_store.py');
const sdk = join(root, 'vendor/devkit/packages/local/dist/index.js');
const MAX_FRAME = 300000;
let request, guard, timer, stopped = false;
const controller = new AbortController();
const output = value => process.stdout.write(JSON.stringify({v: 1, id: request?.id || '', ...value}) + '\n');
const env = Object.fromEntries(Object.entries(process.env).filter(([k]) => !/^(OPENAI_|NODE_OPTIONS$|NODE_PATH$|.*_PROXY$)/i.test(k)));
function child(mode) {
  return spawn(python, ['-I', '-B', helper, mode], {windowsHide: true, stdio: ['pipe', 'pipe', 'ignore'], env});
}
async function cryptoCall(mode, bytes) {
  return new Promise((ok, no) => {
    const p = child(mode);
    const chunks = []; let size = 0;
    p.stdout.on('data', b => { size += b.length; if (size > 4 * 1024 * 1024) p.kill(); else chunks.push(b); });
    p.once('error', () => no(new SafeError('storage_unavailable')));
    p.once('close', code => code === 0 ? ok(Buffer.from(Buffer.concat(chunks).toString('ascii'), 'base64')) : no(new SafeError('storage_unavailable')));
    p.stdin.on('error', () => {});
    p.stdin.end(Buffer.from(bytes).toString('base64'));
  });
}
async function acquire() {
  return new Promise((ok, no) => {
    guard = child('guard');
    let data = '', settled = false;
    const fail = () => { if (!settled) { settled = true; no(new SafeError('storage_unavailable')); } else if (!stopped) controller.abort(); };
    guard.once('error', fail); guard.once('exit', fail);
    guard.stdin.on('error', () => {});
    guard.stdout.on('data', b => {
      data += b.toString('utf8');
      if (settled) return;
      if (data.length > 10000) return fail();
      if (data.includes('\n')) {
        try {
          const result = JSON.parse(data.split('\n')[0]);
          settled = true;
          if (result.ready === true && typeof result.storage === 'string') ok(result.storage);
          else no(new SafeError(result.code === 'busy' ? 'busy' : 'storage_unavailable'));
        } catch { fail(); }
      }
    });
  });
}
async function run(r) {
  try {
    request = r && typeof r.id === 'string' && /^[a-zA-Z0-9_-]{1,128}$/.test(r.id) ? r : null;
    validate(r);
    if (request.op === 'health') {
      output({type: 'result', ok: true, data: {protocol: 1, provider: 'chatgpt_subscription',
        dependency_ready: existsSync(sdk) && existsSync(python), effective_upstream: 'openai',
        data_leaves_device: true, mode: 'personal-local-text-only', network_called: false}});
      return;
    }
    if (!existsSync(sdk) || !existsSync(python)) throw new SafeError('dependency_unavailable');
    timer = setTimeout(() => controller.abort(), request.op === 'login' ? 600000 : 240000);
    const storageDir = await acquire();
    controller.signal.throwIfAborted();
    const {createChatGPT} = await import(pathToFileURL(sdk).href);
    const client = createChatGPT({appName: 'AI WorckBook local subscription', appId: 'ai-worckbook-subscription',
      redirectPort: 0, storageDir, sendHostId: true,
      credentialEncryption: {id: 'windows-dpapi-current-user-v1', isAvailable: () => process.platform === 'win32',
        encrypt: value => cryptoCall('encrypt', Buffer.from(value, 'utf8')),
        decrypt: async value => (await cryptoCall('decrypt', value)).toString('utf8')}});
    const data = await execute(request, client, controller.signal);
    controller.signal.throwIfAborted();
    output({type: 'result', ok: true, data});
  } catch (e) {
    output({type: 'result', ok: false, code: controller.signal.aborted ? 'cancelled' : errorCode(e)});
  } finally {
    stopped = true; clearTimeout(timer);
    guard?.stdin.end();
    input.close(); process.stdin.pause();
  }
}
// Ограничиваем размер до накопления произвольно длинной строки в readline.
let frameSize = 0;
process.stdin.on('data', b => {
  for (const x of b) { frameSize = x === 10 ? 0 : frameSize + 1; if (frameSize > MAX_FRAME) { controller.abort(); process.stdin.destroy(); break; } }
});
const input = createInterface({input: process.stdin, crlfDelay: Infinity});
let started = false;
input.on('line', line => {
  if (stopped) return;
  try {
    if (Buffer.byteLength(line) > MAX_FRAME) throw new Error();
    const r = JSON.parse(line);
    if (!started) { started = true; void run(r); }
    else if (r.v === 1 && r.id === request?.id && r.op === 'cancel' && Object.keys(r).length === 3) controller.abort();
    else controller.abort();
  } catch {
    if (!started) { started = true; void run(null); } else controller.abort();
  }
});
input.on('close', () => { if (!stopped) controller.abort(); });
process.on('SIGTERM', () => controller.abort());

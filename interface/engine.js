'use strict';

// Penghubung aplikasi ke engine Python lewat CLI `binance_bot`. Tidak bergantung pada Electron,
// jadi bisa dites dengan `node --test`. Argumen selalu dikirim sebagai array (tanpa shell).
//
// Pengaturan teknis (kunci AI, token dan alamat hub) diisi admin di `interface/.env`, lalu
// diteruskan ke engine sebagai variabel lingkungan. Pengguna tidak pernah melihatnya.

const { spawn, execFile } = require('node:child_process');
const { EventEmitter } = require('node:events');
const fs = require('node:fs');
const path = require('node:path');

const REPO_DIR = path.resolve(__dirname, '..');
const ENGINE_DIR = path.join(REPO_DIR, 'engine');
const ENGINE_SRC = path.join(ENGINE_DIR, 'src');
const APP_ENV_FILE = path.join(__dirname, '.env');
const IS_WINDOWS = process.platform === 'win32';

/**
 * Perintah untuk menjalankan engine dari satu virtualenv: `python -m binance_bot` di semua OS,
 * dengan PYTHONPATH ke `engine/src` (lihat engineEnv).
 * - Windows: skrip `binance-bot.exe` hanyalah peluncur yang memulai proses Python lain, sehingga
 *   menghentikannya tidak menghentikan engine.
 * - macOS: skrip `binance-bot` bergantung pada file .pth instalasi editable, yang bisa diberi
 *   flag "hidden" oleh macOS lalu diabaikan Python (No module named 'binance_bot').
 */
function botFor(venv, platform = process.platform) {
  return platform === 'win32'
    ? { command: path.join(venv, 'Scripts', 'python.exe'), args: ['-m', 'binance_bot'] }
    : { command: path.join(venv, 'bin', 'python'), args: ['-m', 'binance_bot'] };
}

/** Virtualenv pertama yang ada: `engine/.venv`, lalu `.venv` di root repo. */
function findBot(exists = fs.existsSync, platform = process.platform) {
  const venvs = [path.join(ENGINE_DIR, '.venv'), path.join(REPO_DIR, '.venv')];
  const found = venvs.map((venv) => botFor(venv, platform)).find((bot) => exists(bot.command));
  return found || botFor(venvs[0], platform);
}

const DEFAULT_BOT = findBot();
const BOT = DEFAULT_BOT.command;

const MODES = ['single', 'leader', 'follower'];
const MAX_RANK = 5;
const MAX_INTERVAL_MIN = 1440;
const STOP_GRACE_MS = 15000;

// Hanya kunci ini yang diteruskan dari interface/.env ke engine.
const APP_ENV_KEYS = ['VIKEY_API_BASE', 'VIKEY_API_KEY', 'BOT_HUB_TOKEN', 'BOT_HUB_URL'];

class InputError extends Error {}

function number(value, label, min, max, integer = false) {
  const n = typeof value === 'number' ? value : Number(String(value).trim().replace(',', '.'));
  if (!Number.isFinite(n) || n < min || n > max || (integer && !Number.isInteger(n))) {
    throw new InputError(`${label} harus ${integer ? 'bilangan bulat' : 'angka'} ${min} sampai ${max}`);
  }
  return n;
}

function ranksOf(value) {
  const list = Array.isArray(value) ? value : [];
  const ranks = [...new Set(list.map((r) => number(r, 'Top gainer', 1, MAX_RANK, true)))];
  if (ranks.length === 0) throw new InputError('Pilih minimal satu top gainer');
  return ranks.sort((a, b) => a - b);
}

/** Alamat hub pemimpin dari jaringan lokal, mis. http://192.168.1.19:8765. */
function hubOf(value) {
  const text = String(value || '').trim();
  if (!/^http:\/\/\d{1,3}(\.\d{1,3}){3}:\d{1,5}$/.test(text)) {
    throw new InputError('Alamat laptop pemimpin tidak valid');
  }
  return text;
}

function modalOf(value) {
  if (value === undefined || value === null || String(value).trim() === '') {
    throw new InputError('Isi modal dalam USDT');
  }
  return String(number(value, 'Modal', 1, 1e9));
}

/**
 * Argumen CLI untuk satu mode. Parameter SOP memakai default V2 di engine.
 * Melempar InputError bila isian tidak valid.
 */
function buildArgs(mode, params = {}) {
  if (!MODES.includes(mode)) throw new InputError(`Mode tidak dikenal: ${mode}`);
  const p = params || {};
  if (mode === 'follower') {
    // Tanpa hub: engine memakai BOT_HUB_URL dari .env. Dengan hub: dari laptop pemimpin (team.js).
    const hub = p.hub ? ['--hub', hubOf(p.hub)] : [];
    return ['--events', 'follower', '--rank', String(number(p.rank, 'Top gainer', 1, MAX_RANK, true)),
      ...hub, '--modal', modalOf(p.modal)];
  }
  const interval = String(number(p.interval ?? 0, 'Frekuensi', 0, MAX_INTERVAL_MIN));
  const args = ['--events', mode, '--ranks', ranksOf(p.ranks).join(','), '--interval', interval];
  return mode === 'single' ? [...args, '--modal', modalOf(p.modal)] : args;
}

/** Satu baris keluaran engine -> objek log. Baris bukan JSON tetap diteruskan apa adanya. */
function parseLine(line, fallbackLevel = 'INFO') {
  try {
    const data = JSON.parse(line);
    if (data && typeof data === 'object' && typeof data.message === 'string') return data;
  } catch {
    // bukan JSON: mis. traceback Python di stderr
  }
  return { ts: Date.now() / 1000, level: fallbackLevel, logger: 'engine', message: line };
}

/** Baca interface/.env (format sama dengan engine: KEY=VALUE). Hanya kunci yang diizinkan. */
function readAppEnv(file = APP_ENV_FILE) {
  let text = '';
  try {
    text = fs.readFileSync(file, 'utf8');
  } catch (err) {
    if (err.code !== 'ENOENT') throw err;
  }
  const values = {};
  for (const raw of text.split('\n')) {
    const line = raw.trim();
    if (!line || line.startsWith('#') || !line.includes('=')) continue;
    const at = line.indexOf('=');
    const key = line.slice(0, at).trim();
    const value = line.slice(at + 1).trim().replace(/^["']|["']$/g, '');
    if (APP_ENV_KEYS.includes(key) && value !== '') values[key] = value;
  }
  return values;
}

/** Lingkungan proses engine: lingkungan aplikasi + pengaturan dari interface/.env. */
function engineEnv(base = process.env, file = APP_ENV_FILE) {
  const env = { ...base, ...readAppEnv(file) };
  env.PYTHONPATH = base.PYTHONPATH ? `${ENGINE_SRC}${path.delimiter}${base.PYTHONPATH}` : ENGINE_SRC;
  delete env.ELECTRON_RUN_AS_NODE;
  if (IS_WINDOWS) {
    // Konsol Windows memakai cp1252: tanpa ini log berbahasa Indonesia bisa gagal dicetak.
    env.PYTHONUTF8 = '1';
    env.PYTHONIOENCODING = 'utf-8';
  }
  return env;
}

function onLines(stream, callback) {
  let buffer = '';
  stream.setEncoding('utf8');
  stream.on('data', (chunk) => {
    buffer += chunk;
    const lines = buffer.split('\n');
    buffer = lines.pop();
    for (const line of lines) if (line.trim()) callback(line);
  });
  stream.on('end', () => {
    if (buffer.trim()) callback(buffer);
  });
}

function assertInstalled(bot) {
  if (!fs.existsSync(bot)) {
    throw new InputError('Mesin bot belum terpasang di laptop ini. Hubungi admin.');
  }
}

/** Satu proses engine yang berjalan lama (single/leader/follower). */
class EngineProcess extends EventEmitter {
  constructor({ bot = BOT, botArgs, cwd = ENGINE_DIR, env = engineEnv } = {}) {
    super();
    this.bot = bot;
    this.botArgs = botArgs ?? (bot === BOT ? DEFAULT_BOT.args : []);
    this.cwd = cwd;
    this.env = env;
    this.child = null;
  }

  get running() {
    return this.child !== null;
  }

  start(args) {
    if (this.child) throw new InputError('Bot sudah berjalan. Hentikan dulu.');
    assertInstalled(this.bot);
    const child = spawn(this.bot, [...this.botArgs, ...args], {
      cwd: this.cwd,
      env: this.env(),
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
    });
    this.child = child;
    onLines(child.stdout, (line) => this.emit('log', parseLine(line)));
    onLines(child.stderr, (line) => this.emit('log', parseLine(line, 'ERROR')));
    child.on('error', (err) => this.emit('log', parseLine(`Bot gagal dijalankan: ${err.message}`, 'ERROR')));
    child.on('exit', (code, signal) => {
      clearTimeout(this.killTimer);
      this.child = null;
      this.emit('exit', { code, signal });
    });
  }

  /**
   * Berhenti seperti Ctrl+C. Bila engine tidak berhenti, dipaksa setelah beberapa detik.
   * Windows tidak punya SIGINT untuk proses anak: pohon prosesnya dihentikan langsung.
   */
  stop() {
    const child = this.child;
    if (!child) return;
    if (IS_WINDOWS) {
      execFile('taskkill', ['/PID', String(child.pid), '/T', '/F'], { windowsHide: true }, () => {});
      return;
    }
    child.kill('SIGINT');
    this.killTimer = setTimeout(() => {
      if (this.child === child) child.kill('SIGKILL');
    }, STOP_GRACE_MS);
  }
}

/** Jalankan perintah singkat yang mencetak satu JSON di stdout (`cek`, `jurnal --json`). */
function runJson(
  args,
  { bot = BOT, botArgs, cwd = ENGINE_DIR, env = engineEnv, timeoutMs = 90000 } = {},
) {
  assertInstalled(bot);
  const prefix = botArgs ?? (bot === BOT ? DEFAULT_BOT.args : []);
  return new Promise((resolve, reject) => {
    const options = {
      cwd,
      env: env(),
      timeout: timeoutMs,
      maxBuffer: 8 * 1024 * 1024,
      windowsHide: true,
    };
    execFile(bot, [...prefix, ...args], options, (err, stdout) => {
      try {
        resolve(JSON.parse(stdout));
      } catch {
        reject(new Error('Data belum bisa dimuat. Coba lagi sebentar.'));
      }
    });
  });
}

/** Token hub: interface/.env, lingkungan, lalu engine/.env. '' bila belum diatur. */
function hubToken(env = process.env) {
  return readAppEnv().BOT_HUB_TOKEN || env.BOT_HUB_TOKEN
    || readAppEnv(path.join(ENGINE_DIR, '.env')).BOT_HUB_TOKEN || '';
}

module.exports = {
  APP_ENV_KEYS,
  BOT,
  ENGINE_DIR,
  EngineProcess,
  InputError,
  botFor,
  buildArgs,
  engineEnv,
  findBot,
  hubToken,
  parseLine,
  readAppEnv,
  runJson,
};

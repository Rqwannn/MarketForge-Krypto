'use strict';

// Penghubung aplikasi ke engine Python lewat CLI `binance-bot`. Tidak bergantung pada Electron,
// jadi bisa dites dengan `node --test`. Argumen selalu dikirim sebagai array (tanpa shell).
//
// Pengaturan teknis (kunci AI, token dan alamat hub) diisi admin di `interface/.env`, lalu
// diteruskan ke engine sebagai variabel lingkungan. Pengguna tidak pernah melihatnya.

const { spawn, execFile } = require('node:child_process');
const { EventEmitter } = require('node:events');
const fs = require('node:fs');
const path = require('node:path');

const ENGINE_DIR = path.resolve(__dirname, '..', 'engine');
const ENGINE_SRC = path.join(ENGINE_DIR, 'src');
const PYTHON = path.join(ENGINE_DIR, '.venv', 'bin', 'python');
// `python -m binance_bot` dengan PYTHONPATH ke source, bukan skrip `binance-bot`: instalasi
// editable bergantung pada file .pth yang bisa diberi flag "hidden" oleh macOS lalu diabaikan.
const BOT = [PYTHON, '-m', 'binance_bot'];
const APP_ENV_FILE = path.join(__dirname, '.env');

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
    return ['--events', 'follower', '--rank', String(number(p.rank, 'Top gainer', 1, MAX_RANK, true)),
      '--modal', modalOf(p.modal)];
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

function assertInstalled([program]) {
  if (!fs.existsSync(program)) {
    throw new InputError('Mesin bot belum terpasang di laptop ini. Hubungi admin.');
  }
}

/** Satu proses engine yang berjalan lama (single/leader/follower). */
class EngineProcess extends EventEmitter {
  constructor({ bot = BOT, cwd = ENGINE_DIR, env = engineEnv } = {}) {
    super();
    this.bot = bot;
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
    const [program, ...prefix] = this.bot;
    const child = spawn(program, [...prefix, ...args], { cwd: this.cwd, env: this.env(), stdio: ['ignore', 'pipe', 'pipe'] });
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

  /** Berhenti seperti Ctrl+C. Bila engine tidak berhenti, dipaksa setelah beberapa detik. */
  stop() {
    const child = this.child;
    if (!child) return;
    child.kill('SIGINT');
    this.killTimer = setTimeout(() => {
      if (this.child === child) child.kill('SIGKILL');
    }, STOP_GRACE_MS);
  }
}

/** Jalankan perintah singkat yang mencetak satu JSON di stdout (`cek`, `jurnal --json`). */
function runJson(args, { bot = BOT, cwd = ENGINE_DIR, env = engineEnv, timeoutMs = 90000 } = {}) {
  assertInstalled(bot);
  return new Promise((resolve, reject) => {
    const options = { cwd, env: env(), timeout: timeoutMs, maxBuffer: 8 * 1024 * 1024 };
    const [program, ...prefix] = bot;
    execFile(program, [...prefix, ...args], options, (err, stdout) => {
      try {
        resolve(JSON.parse(stdout));
      } catch {
        reject(new Error('Data belum bisa dimuat. Coba lagi sebentar.'));
      }
    });
  });
}

module.exports = {
  APP_ENV_KEYS,
  BOT,
  ENGINE_DIR,
  EngineProcess,
  InputError,
  buildArgs,
  engineEnv,
  parseLine,
  readAppEnv,
  runJson,
};

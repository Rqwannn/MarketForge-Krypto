'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const {
  EngineProcess, InputError, botFor, buildArgs, engineEnv, findBot, parseLine, readAppEnv,
} = require('../engine');

function tempDir() {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'mf-'));
}

test('sendiri: beberapa top gainer, frekuensi, dan modal', () => {
  assert.deepEqual(buildArgs('single', { ranks: [3, 1, 3], interval: 15, modal: '100' }), [
    '--events', 'single', '--ranks', '1,3', '--interval', '15', '--modal', '100',
  ]);
});

test('pemimpin tidak butuh modal', () => {
  assert.deepEqual(buildArgs('leader', { ranks: [1, 2, 3, 4, 5], modal: '' }), [
    '--events', 'leader', '--ranks', '1,2,3,4,5', '--interval', '0',
  ]);
});

test('pengikut: satu top gainer dan modal (alamat hub dari .env admin)', () => {
  assert.deepEqual(buildArgs('follower', { rank: 2, modal: '150,5', ranks: [1, 2] }), [
    '--events', 'follower', '--rank', '2', '--modal', '150.5',
  ]);
});

test('pengikut dari ajakan pemimpin: alamat hub ikut, dan divalidasi', () => {
  assert.deepEqual(buildArgs('follower', { rank: 3, modal: '100', hub: 'http://192.168.1.19:8765' }), [
    '--events', 'follower', '--rank', '3', '--hub', 'http://192.168.1.19:8765', '--modal', '100',
  ]);
  for (const hub of ['http://evil.example:80', 'http://1.2.3.4:80/; rm -rf /', 'https://1.2.3.4:8765']) {
    assert.throws(() => buildArgs('follower', { rank: 1, modal: '100', hub }), InputError, hub);
  }
});

test('hanya Binance yang bisa dijalankan; bursa lain ditolak', () => {
  assert.deepEqual(buildArgs('single', { exchange: 'binance', ranks: [1], modal: '100' }).slice(0, 2), ['--events', 'single']);
  for (const exchange of ['tebbit', 'bybit', '', 'BINANCE', null]) {
    assert.throws(() => buildArgs('single', { exchange, ranks: [1], modal: '100' }), InputError, String(exchange));
  }
});

test('isian tidak valid ditolak sebelum menjadi argumen', () => {
  const bad = [
    ['jual', { modal: 100, ranks: [1] }],
    ['single', { ranks: [], modal: 100 }],
    ['single', { ranks: [6], modal: 100 }],
    ['single', { ranks: [1] }], // tanpa modal
    ['single', { ranks: [1], modal: '-5' }],
    ['single', { ranks: [1], modal: '100; rm -rf /' }],
    ['single', { ranks: [1], modal: 100, interval: 99999 }],
    ['follower', { rank: 0, modal: 100 }],
  ];
  for (const [mode, params] of bad) {
    assert.throws(() => buildArgs(mode, params), InputError, `${mode} ${JSON.stringify(params)}`);
  }
});

test('baris JSON dibaca; baris lain tetap diteruskan', () => {
  const line = JSON.stringify({ ts: 1, level: 'INFO', logger: 'x', message: 'halo', event: { type: 'hub', url: 'u' } });
  assert.equal(parseLine(line).event.url, 'u');
  const plain = parseLine('Traceback (most recent call last):', 'ERROR');
  assert.equal(plain.level, 'ERROR');
});

test('interface/.env: hanya kunci yang diizinkan diteruskan ke engine', () => {
  const file = path.join(tempDir(), '.env');
  fs.writeFileSync(file, [
    '# admin',
    'VIKEY_API_KEY="sk-uji"',
    'BOT_HUB_URL=http://192.168.1.24:8765',
    'BOT_HUB_TOKEN=',
    'PATH=/jahat',
    'BOT_LOG_LEVEL=DEBUG',
  ].join('\n'));
  assert.deepEqual(readAppEnv(file), { VIKEY_API_KEY: 'sk-uji', BOT_HUB_URL: 'http://192.168.1.24:8765' });

  const env = engineEnv({ PATH: '/usr/bin', ELECTRON_RUN_AS_NODE: '1', VIKEY_API_KEY: 'lama' }, file);
  assert.equal(env.PATH, '/usr/bin');
  assert.equal(env.VIKEY_API_KEY, 'sk-uji');
  assert.equal(env.ELECTRON_RUN_AS_NODE, undefined);
  assert.ok(env.PYTHONPATH.endsWith(path.join('engine', 'src'))); // engine dari source, tanpa .pth
  assert.deepEqual(readAppEnv(path.join(tempDir(), 'tidak-ada')), {});
});

test('perintah engine: python -m binance_bot dari virtualenv di semua OS', () => {
  assert.deepEqual(botFor('/v', 'darwin'), {
    command: path.join('/v', 'bin', 'python'),
    args: ['-m', 'binance_bot'],
  });
  assert.deepEqual(botFor('C:\\v', 'win32'), {
    command: path.join('C:\\v', 'Scripts', 'python.exe'),
    args: ['-m', 'binance_bot'],
  });
});

test('virtualenv dicari di engine/.venv lalu di root repo', () => {
  const exists = (wanted) => (file) => file === wanted;
  const rootBot = botFor(path.resolve(__dirname, '..', '..', '.venv'), 'win32');
  assert.equal(findBot(exists(rootBot.command), 'win32').command, rootBot.command);
  const engineBot = botFor(path.resolve(__dirname, '..', '..', 'engine', '.venv'), 'win32');
  assert.equal(findBot(exists(engineBot.command), 'win32').command, engineBot.command);
  // tidak ada satu pun: kembali ke lokasi engine/.venv agar pesan "belum terpasang" masuk akal
  assert.equal(findBot(() => false, 'win32').command, engineBot.command);
});

test('proses engine: log per baris, lingkungan dari .env, berhenti', async () => {
  const dir = tempDir();
  const script = path.join(dir, 'fake-bot.js');
  // Engine tiruan (Node, jalan di semua OS): cetak satu event dan variabel dari .env, lalu
  // tunggu sampai dihentikan. Di Unix berhenti lewat SIGINT dengan kode 130.
  fs.writeFileSync(script, [
    "process.on('SIGINT', () => { console.error('berhenti'); process.exit(130); });",
    `console.log(JSON.stringify({ ts: 1, level: 'INFO', logger: 't', message: 'mulai', event: { type: 'cycle', phase: 'start' } }));`,
    "console.log('hub=' + process.env.BOT_HUB_URL + ' arg=' + process.argv.slice(2).join(','));",
    'setInterval(() => {}, 100);',
  ].join('\n'));

  const proc = new EngineProcess({
    bot: process.execPath,
    botArgs: [script],
    cwd: dir,
    env: () => ({ ...process.env, BOT_HUB_URL: 'http://h:1' }),
  });
  const logs = [];
  proc.on('log', (entry) => logs.push(entry));
  const exited = new Promise((resolve) => proc.once('exit', resolve));
  proc.start(['single']);
  assert.throws(() => proc.start(['single']), InputError); // hanya satu proses

  while (logs.length < 2) await new Promise((r) => setTimeout(r, 20));
  assert.equal(logs[0].event.type, 'cycle');
  assert.equal(logs[1].message, 'hub=http://h:1 arg=single');
  proc.stop();
  const { code } = await exited;
  assert.equal(proc.running, false);
  if (process.platform !== 'win32') {
    assert.equal(code, 130);
    assert.ok(logs.some((l) => l.level === 'ERROR' && l.message === 'berhenti'));
  }
});

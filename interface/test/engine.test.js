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

test('modal 50%: setengah saldo tersedia, untuk Sendiri dan Pengikut', () => {
  for (const modal of ['setengah', '50%', ' Setengah ']) {
    assert.deepEqual(buildArgs('single', { ranks: [1], modal }).slice(-2), ['--modal', 'setengah']);
  }
  assert.deepEqual(buildArgs('follower', { rank: 2, modal: '50%' }).slice(-2), ['--modal', 'setengah']);
  assert.throws(() => buildArgs('single', { ranks: [1], modal: '25%' }), InputError);
});

test('modal Max: seluruh saldo tersedia, untuk Sendiri dan Pengikut', () => {
  assert.deepEqual(buildArgs('single', { ranks: [1], modal: 'max' }).slice(-2), ['--modal', 'max']);
  assert.deepEqual(buildArgs('follower', { rank: 2, modal: ' Max ' }).slice(-2), ['--modal', 'max']);
  for (const modal of ['', 'semua', 'maks']) {
    assert.throws(() => buildArgs('single', { ranks: [1], modal }), InputError, modal);
  }
});

test('pengikut dari ajakan pemimpin: alamat hub ikut, dan divalidasi', () => {
  assert.deepEqual(buildArgs('follower', { rank: 3, modal: '100', hub: 'http://192.168.1.19:8765' }), [
    '--events', 'follower', '--rank', '3', '--hub', 'http://192.168.1.19:8765', '--modal', '100',
  ]);
  for (const hub of ['http://evil.example:80', 'http://1.2.3.4:80/; rm -rf /', 'https://1.2.3.4:8765']) {
    assert.throws(() => buildArgs('follower', { rank: 1, modal: '100', hub }), InputError, hub);
  }
});

test('pengikut semua top: --semua; angka di luar 1..5 tetap ditolak', () => {
  assert.deepEqual(buildArgs('follower', { rank: '*', modal: '100' }), ['--events', 'follower', '--semua', '--modal', '100']);
  assert.deepEqual(buildArgs('follower', { rank: 3, modal: '100' }).slice(0, 4), ['--events', 'follower', '--rank', '3']);
  for (const rank of [0, 6, '**', 'semua']) assert.throws(() => buildArgs('follower', { rank, modal: '100' }), InputError, String(rank));
});

test('pengikut beberapa top: --ranks terurut, satu top tetap --rank, tugas tidak valid ditolak', () => {
  const tops = (rank) => buildArgs('follower', { rank, modal: '100' }).slice(2, 4);
  assert.deepEqual(tops('245'), ['--ranks', '2,4,5']);
  assert.deepEqual(tops([5, 2]), ['--ranks', '2,5']);
  assert.deepEqual(tops('3'), ['--rank', '3']);
  assert.deepEqual(tops([4]), ['--rank', '4']);
  for (const bad of [[], [0], [6], '19', 'abc']) {
    assert.throws(() => buildArgs('follower', { rank: bad, modal: '100' }), InputError, String(bad));
  }
});

test('Binance dan Tebbit bisa dijalankan; bursa lain ditolak', () => {
  assert.deepEqual(buildArgs('single', { exchange: 'binance', ranks: [1], modal: '100' }).slice(0, 4), ['--bursa', 'binance', '--events', 'single']);
  assert.deepEqual(buildArgs('single', { exchange: 'tebbit', ranks: [1], modal: '100' }).slice(0, 4), ['--bursa', 'tebbit', '--events', 'single']);
  for (const exchange of ['bybit', '', 'BINANCE', null]) {
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

test('findBot melewati venv kosong dan memilih venv yang pustakanya lengkap', () => {
  const root = path.resolve(__dirname, '..', '..');
  const engineVenv = path.join(root, 'engine', '.venv');
  const rootVenv = path.join(root, '.venv');
  const pythons = [botFor(engineVenv, 'win32').command, botFor(rootVenv, 'win32').command];
  const pil = path.join(rootVenv, 'Lib', 'site-packages', 'PIL');
  // engine/.venv ada tetapi kosong; .venv di root lengkap
  const exists = (file) => pythons.includes(file) || file === pil;
  assert.equal(findBot(exists, 'win32').command, botFor(rootVenv, 'win32').command);
  // keduanya kosong: tetap pakai yang pertama ada
  const bare = (file) => pythons.includes(file);
  assert.equal(findBot(bare, 'win32').command, botFor(engineVenv, 'win32').command);
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
  const { code, stopped } = await exited;
  assert.equal(proc.running, false);
  assert.equal(stopped, true); // diminta berhenti, apa pun kode keluarnya (Windows: taskkill = 1)
  if (process.platform !== 'win32') {
    assert.equal(code, 130);
    assert.ok(logs.some((l) => l.level === 'ERROR' && l.message === 'berhenti'));
  }
});

test('proses engine yang keluar sendiri dengan galat tidak dianggap diminta berhenti', async () => {
  const dir = tempDir();
  const script = path.join(dir, 'crash.js');
  fs.writeFileSync(script, "process.exit(1);");
  const proc = new EngineProcess({ bot: process.execPath, botArgs: [script], cwd: dir, env: () => process.env });
  const exited = new Promise((resolve) => proc.once('exit', resolve));
  proc.start([]);
  const info = await exited;
  assert.equal(info.code, 1);
  assert.equal(info.stopped, false);
  proc.start([]); // dijalankan lagi: penanda dibersihkan
  assert.equal(proc.stopRequested, false);
  await new Promise((resolve) => proc.once('exit', resolve));
});

test('grafik hanya dibaca dari folder screenshots engine', () => {
  const fs = require('node:fs');
  const os = require('node:os');
  const path = require('node:path');
  const { readChart } = require('../engine');
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'mf-engine-'));
  fs.mkdirSync(path.join(dir, 'screenshots'));
  fs.writeFileSync(path.join(dir, 'screenshots', 'x_rank1_BTWUSDT_15m.png'), Buffer.from([0x89, 0x50]));
  fs.writeFileSync(path.join(dir, '.env'), 'VIKEY_API_KEY=rahasia');
  assert.equal(readChart('screenshots/x_rank1_BTWUSDT_15m.png', dir), 'data:image/png;base64,iVA=');
  for (const bad of ['.env', '../.env', 'screenshots/../.env', 'screenshots/x.png', '/etc/passwd',
    'screenshots/sub/a_15m.png', 'screenshots/hilang_15m.png', '', null]) {
    assert.throws(() => readChart(bad, dir), InputError, String(bad));
  }
});

test('Real Fund Trading: --uang-sungguhan hanya untuk Binance (Sekali atau Ulangi)', () => {
  const single = buildArgs('single', { exchange: 'binance', ranks: [1], interval: 15, modal: 100, real: true });
  assert.ok(single.includes('--uang-sungguhan'));
  assert.ok(single.indexOf('--uang-sungguhan') < single.indexOf('--events'));  // opsi global
  assert.ok(!buildArgs('single', { ranks: [1], interval: 15, modal: 100 }).includes('--uang-sungguhan'));
  assert.ok(buildArgs('single', { exchange: 'binance', ranks: [1], interval: 0, modal: 100, real: true }).includes('--uang-sungguhan'));  // Sekali boleh: bot mengawasi sampai terjual
  assert.throws(() => buildArgs('single', { exchange: 'tebbit', ranks: [1], interval: 15, modal: 100, real: true }), /Binance/);
  const follower = buildArgs('follower', { exchange: 'binance', rank: '*', modal: 100, real: true });
  assert.ok(follower.includes('--uang-sungguhan'));
});

test('exitNotice: selesai normal, dihentikan pengguna, dan kendala dibedakan', () => {
  const { exitNotice } = require('../engine');
  assert.equal(exitNotice({ code: 0, signal: null, stopped: false }).kind, 'done');
  assert.match(exitNotice({ code: 0 }).body, /Hasil uji/);
  // Hentikan di Windows keluar dengan kode 1: tetap "dihentikan", bukan kendala.
  assert.equal(exitNotice({ code: 1, signal: null, stopped: true }).kind, 'stopped');
  assert.equal(exitNotice({ code: 130 }).kind, 'stopped');
  assert.equal(exitNotice({ code: null, signal: 'SIGTERM' }).kind, 'stopped');
  assert.equal(exitNotice({ code: 1, signal: null, stopped: false }).kind, 'error');
  assert.equal(exitNotice().kind, 'error');
});

test('catat tutup manual: pair, harga wajib, hasil opsional dan boleh minus', () => {
  const { manualCloseArgs } = require('../engine');
  assert.deepEqual(manualCloseArgs('ariausdt', '0,04747', '+0,60'), ['posisi', '--catat-manual', 'ARIAUSDT', '--harga', '0.04747', '--hasil=0.6']);
  assert.deepEqual(manualCloseArgs('BTWUSDT', '2.3422', '-1,25').slice(-1), ['--hasil=-1.25']);
  assert.deepEqual(manualCloseArgs('BTWUSDT', '2.3422', ''), ['posisi', '--catat-manual', 'BTWUSDT', '--harga', '2.3422']);
  for (const [symbol, priceText] of [['ARIA; rm -rf', '1'], ['ARIAUSDT', ''], ['ARIAUSDT', '0'], ['ARIAUSDT', 'abc']]) {
    assert.throws(() => manualCloseArgs(symbol, priceText), InputError, `${symbol} ${priceText}`);
  }
});

test('arah per Top, cutloss, dan batas waktu diteruskan ke engine; tanpa pilihan tetap short saja', () => {
  const plain = buildArgs('single', { ranks: [1], modal: '100' });
  assert.ok(!plain.some((a) => a.startsWith('--top') || a === '--cutloss' || a === '--batas-waktu'));
  // Short Top 2-3-4, Long Top 1-5: Top yang dipantau = gabungannya.
  const custom = buildArgs('single', {
    ranks: [1], modal: '100', shortTops: [4, 2, 3], longTops: [5, 1], cutloss: true, timeLimit: true,
  });
  assert.equal(custom[custom.indexOf('--ranks') + 1], '1,2,3,4,5');
  assert.deepEqual(custom.slice(-7), ['--top-short', '2,3,4', '--top-long', '1,5', '--cutloss', '10', '--batas-waktu']);
  // Long saja: tanpa --top-short (engine: Top lain tidak short).
  const longOnly = buildArgs('single', { modal: '100', shortTops: [], longTops: [1, 2, 3] });
  assert.equal(longOnly[longOnly.indexOf('--ranks') + 1], '1,2,3');
  assert.ok(!longOnly.includes('--top-short') && longOnly.includes('--top-long'));
  // Pemimpin hanya meneruskan pembagian Top (AI membaca tanda long di Top long).
  assert.deepEqual(
    buildArgs('leader', { shortTops: [2, 4, 5], longTops: [1, 2, 3], cutloss: true }).slice(-4),
    ['--top-short', '2,4,5', '--top-long', '1,2,3'],
  );
  assert.deepEqual(
    buildArgs('follower', { rank: 1, modal: '100', shortTops: [2], longTops: [1], cutloss: true }).slice(-6),
    ['--top-short', '2', '--top-long', '1', '--cutloss', '10'],
  );
  assert.throws(() => buildArgs('single', { modal: '100', shortTops: [], longTops: [] }), /minimal satu Top/);
  assert.throws(() => buildArgs('single', { modal: '100', shortTops: [6], longTops: [] }), InputError);
  assert.throws(() => buildArgs('single', { modal: '100', shortTops: 'semua', longTops: [] }), InputError);
  assert.deepEqual(
    buildArgs('single', { modal: '100', shortTops: [1], longTops: [1], exchange: 'tebbit' }).slice(-4),
    ['--top-short', '1', '--top-long', '1'],
  );
  assert.deepEqual(
    buildArgs('follower', { rank: 1, modal: '100', stopFile: '/tmp/berhenti' }).slice(-2),
    ['--berkas-berhenti', '/tmp/berhenti'],
  );
});

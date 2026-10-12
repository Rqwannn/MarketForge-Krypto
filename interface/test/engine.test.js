'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const { EngineProcess, InputError, buildArgs, engineEnv, parseLine, readAppEnv } = require('../engine');

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
  assert.deepEqual(readAppEnv(path.join(tempDir(), 'tidak-ada')), {});
});

test('proses engine: log per baris, lingkungan dari .env, berhenti dengan SIGINT', async () => {
  const dir = tempDir();
  const bot = path.join(dir, 'fake-bot');
  // Engine tiruan: cetak satu event dan variabel dari .env, lalu tunggu sampai dihentikan.
  fs.writeFileSync(bot, [
    '#!/bin/sh',
    'trap "echo berhenti >&2; exit 130" INT',
    `echo '{"ts":1,"level":"INFO","logger":"t","message":"mulai","event":{"type":"cycle","phase":"start"}}'`,
    'echo "hub=$BOT_HUB_URL"',
    'while true; do sleep 0.1; done',
  ].join('\n'), { mode: 0o755 });

  const proc = new EngineProcess({ bot, cwd: dir, env: () => ({ PATH: process.env.PATH, BOT_HUB_URL: 'http://h:1' }) });
  const logs = [];
  proc.on('log', (entry) => logs.push(entry));
  const exited = new Promise((resolve) => proc.once('exit', resolve));
  proc.start(['single']);
  assert.throws(() => proc.start(['single']), InputError); // hanya satu proses

  while (logs.length < 2) await new Promise((r) => setTimeout(r, 20));
  assert.equal(logs[0].event.type, 'cycle');
  assert.equal(logs[1].message, 'hub=http://h:1');
  proc.stop();
  const { code } = await exited;
  assert.equal(code, 130);
  assert.equal(proc.running, false);
  assert.ok(logs.some((l) => l.level === 'ERROR' && l.message === 'berhenti'));
});

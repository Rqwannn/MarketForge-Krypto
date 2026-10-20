'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const { BRAND, brandedExecutable } = require('../brand');

const EXE = '/x/node_modules/electron/dist/Electron.app/Contents/MacOS/Electron';
const BRANDED = `/x/node_modules/electron/dist/${BRAND}.app/Contents/MacOS/Electron`;

function fakeFiles(existing = {}) {
  const files = { ...existing };
  return {
    files,
    existsSync: (p) => p in files,
    readFileSync: (p) => files[p],
    writeFileSync: (p, text) => { files[p] = text; },
    rmSync: () => {},
  };
}

function recorder(version = '44.4.5') {
  const calls = [];
  const run = (cmd, args) => {
    calls.push([cmd.split('/').pop(), ...args]);
    if (cmd.endsWith('PlistBuddy')) return args[1].includes('CFBundleVersion') ? `${version}\n` : 'electron.icns\n';
    return '';
  };
  return { calls, run };
}

test('bukan macOS: Electron apa adanya, tanpa perintah apa pun', () => {
  const { calls, run } = recorder();
  assert.equal(brandedExecutable(EXE, { platform: 'win32', run }), EXE);
  assert.equal(calls.length, 0);
});

test('macOS pertama kali: salin tanpa atribut, ganti nama dan id, tandatangani ulang', () => {
  const { calls, run } = recorder();
  const fs = fakeFiles();
  assert.equal(brandedExecutable(EXE, { platform: 'darwin', run, files: fs }), BRANDED);
  const tools = calls.map((c) => c[0]);
  assert.deepEqual(tools.filter((t) => t !== 'PlistBuddy'), ['ditto', 'plutil', 'plutil', 'plutil', 'sips', 'xattr', 'codesign']);
  assert.ok(calls.find((c) => c[0] === 'ditto').includes('--noextattr'));
  assert.ok(calls.some((c) => c[0] === 'plutil' && c.includes('CFBundleName') && c.includes(BRAND)));
  assert.ok(tools.indexOf('xattr') < tools.indexOf('codesign')); // atribut dibersihkan sebelum tanda tangan
  // Penanda di luar bundel (file di dalam bundel merusak segel tanda tangan).
  assert.deepEqual(Object.keys(fs.files), [`/x/node_modules/electron/dist/${BRAND}.app.brand.txt`]);
});

test('macOS berikutnya: salinan yang cocok dipakai ulang; versi Electron baru dibuat ulang', () => {
  const marker = `/x/node_modules/electron/dist/${BRAND}.app.brand.txt`;
  const fs = fakeFiles({ [BRANDED]: '', [marker]: `44.4.5 ${BRAND}` });
  const same = recorder('44.4.5');
  assert.equal(brandedExecutable(EXE, { platform: 'darwin', run: same.run, files: fs }), BRANDED);
  assert.deepEqual(same.calls.map((c) => c[0]), ['PlistBuddy']);
  const upgraded = recorder('45.0.0');
  brandedExecutable(EXE, { platform: 'darwin', run: upgraded.run, files: fs });
  assert.ok(upgraded.calls.some((c) => c[0] === 'codesign'));
});

test('gagal di tengah jalan: tetap terbuka sebagai Electron biasa', () => {
  const warnings = [];
  const run = (cmd) => { if (cmd.endsWith('codesign')) throw new Error('detritus'); return '44.4.5'; };
  assert.equal(brandedExecutable(EXE, { platform: 'darwin', run, files: fakeFiles(), log: (m) => warnings.push(m) }), EXE);
  assert.match(warnings[0], /dibuka sebagai Electron/);
});

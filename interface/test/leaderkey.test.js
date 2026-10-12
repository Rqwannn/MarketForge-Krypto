'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const {
  generateLeaderKeys, loadLeaderKey, loadLeaderPublic, openAsLeader, sealForLeader, signAsLeader, verifyLeader,
} = require('../leaderkey');

const leader = generateLeaderKeys();
const keys = loadLeaderKey(leader.privateText);
const pub = loadLeaderPublic(leader.publicText);

test('kunci dibaca dari teks .env; teks rusak atau kosong ditolak', () => {
  assert.ok(keys && pub);
  assert.equal(keys.public.text, leader.publicText); // kunci publik bisa diturunkan dari kunci privat
  for (const bad of ['', 'acak', 'mfpub1.bukan-json', leader.privateText]) assert.equal(loadLeaderPublic(bad), null, bad);
  for (const bad of ['', leader.publicText, 'mfpriv1.e30']) assert.equal(loadLeaderKey(bad), null, bad);
});

test('hanya pemegang kunci privat yang bisa menandatangani pengumuman pemimpin', () => {
  const message = 'id=a&inv=11111111:2&role=leader';
  const signature = signAsLeader(keys, message);
  assert.equal(verifyLeader(pub, message, signature), true);
  assert.equal(verifyLeader(pub, 'id=a&inv=11111111:3&role=leader', signature), false); // diubah

  const impostor = loadLeaderKey(generateLeaderKeys().privateText); // kunci lain (dibuat sendiri)
  assert.equal(verifyLeader(pub, message, signAsLeader(impostor, message)), false);
  assert.equal(verifyLeader(pub, message, ''), false);
});

test('aktivitas terenkripsi hanya bisa dibaca pemimpin', () => {
  const sealed = sealForLeader(pub, '["Membuka top 2: RSRUSDT","RSRUSDT|tunggu|skipped",1800000000]');
  assert.ok(!sealed.includes('RSRUSDT'));
  assert.equal(openAsLeader(keys, sealed), '["Membuka top 2: RSRUSDT","RSRUSDT|tunggu|skipped",1800000000]');
  const other = loadLeaderKey(generateLeaderKeys().privateText);
  assert.equal(openAsLeader(other, sealed), null); // pengikut/laptop lain tidak bisa membaca
  assert.equal(openAsLeader(keys, `${sealed.slice(0, -4)}AAAA`), null); // dirusak
});

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { hashPassword, verifyPassword, setEnvValue } = require('../leaderkey');

test('password admin disimpan sebagai hash: cocok untuk password benar saja', () => {
  const stored = hashPassword('rahasia-uji-123');
  assert.ok(stored.startsWith('scrypt$') && !stored.includes('rahasia'));
  assert.equal(verifyPassword('rahasia-uji-123', stored), true);
  assert.equal(verifyPassword('rahasia-uji-124', stored), false);
  assert.equal(verifyPassword('rahasia-uji-123', ''), false);
  assert.notEqual(hashPassword('sama'), hashPassword('sama')); // salt acak
});

test('hash password ditulis ke .env tanpa mengubah baris lain', () => {
  const file = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'mf-')), '.env');
  fs.writeFileSync(file, '# catatan\nVIKEY_API_KEY=abc\nBOT_LEADER_PASSWORD_HASH=lama\n');
  setEnvValue(file, 'BOT_LEADER_PASSWORD_HASH', 'baru');
  setEnvValue(file, 'BOT_HUB_TOKEN', 'xyz');
  assert.equal(fs.readFileSync(file, 'utf8'), '# catatan\nVIKEY_API_KEY=abc\nBOT_LEADER_PASSWORD_HASH=baru\nBOT_HUB_TOKEN=xyz\n');
  assert.equal(fs.statSync(file).mode & 0o777, 0o600);
});

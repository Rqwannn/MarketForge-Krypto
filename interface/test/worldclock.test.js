'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const {
  MARKETS, clockText, cryptoPhase, daySegments, duration, marketStatus, nextOpen, offsetMinutes,
} = require('../renderer/worldclock');

const market = (id) => MARKETS.find((m) => m.id === id);
const at = (iso) => new Date(iso);

test('zona waktu mengikuti jam musim: New York -4 jam sampai 1 Nov 2026, lalu -5 jam', () => {
  assert.equal(offsetMinutes('America/New_York', at('2026-10-19T12:00:00Z')), -240);
  assert.equal(offsetMinutes('America/New_York', at('2026-11-02T12:00:00Z')), -300);
  assert.equal(offsetMinutes('Europe/London', at('2026-10-19T12:00:00Z')), 60);
  assert.equal(offsetMinutes('Europe/London', at('2026-10-26T12:00:00Z')), 0);
  assert.equal(offsetMinutes('Asia/Jakarta', at('2026-10-19T12:00:00Z')), 420);
  assert.equal(clockText(at('2026-10-19T13:30:00Z'), 'America/New_York'), '09:30');
  assert.equal(clockText(at('2026-10-19T13:30:45Z'), 'Asia/Jakarta', { seconds: true }), '20:30:45');
});

test('bursa AS: buka 20.30 WIB musim panas dan 21.30 WIB sesudah jam musim berganti', () => {
  const ny = market('ny');
  assert.deepEqual(marketStatus(ny, at('2026-10-19T13:29:00Z')), { state: 'tutup', note: 'buka dalam 1 m' });
  assert.equal(marketStatus(ny, at('2026-10-19T13:30:00Z')).state, 'buka');
  assert.equal(marketStatus(ny, at('2026-10-19T13:30:00Z')).note, 'tutup dalam 6 j 30 m');
  assert.equal(marketStatus(ny, at('2026-10-19T20:00:00Z')).state, 'tutup'); // 16.00 EDT = 03.00 WIB
  // Sesudah 1 November: 09.30 EST = 14.30 UTC = 21.30 WIB.
  assert.equal(marketStatus(ny, at('2026-11-02T14:00:00Z')).state, 'tutup');
  assert.equal(marketStatus(ny, at('2026-11-02T14:30:00Z')).state, 'buka');
});

test('London bergeser satu jam sesudah 25 Oktober', () => {
  const london = market('london');
  assert.equal(marketStatus(london, at('2026-10-19T07:00:00Z')).state, 'buka'); // 08.00 BST
  assert.equal(marketStatus(london, at('2026-10-26T07:00:00Z')).state, 'tutup'); // 07.00 GMT
  assert.equal(marketStatus(london, at('2026-10-26T08:00:00Z')).state, 'buka'); // 08.00 GMT
});

test('Tokyo dan Hong Kong punya istirahat siang', () => {
  const tokyo = market('tokyo');
  assert.equal(marketStatus(tokyo, at('2026-10-19T02:29:00Z')).state, 'buka'); // 11.29 JST
  assert.deepEqual(marketStatus(tokyo, at('2026-10-19T03:00:00Z')), { state: 'istirahat', note: 'buka lagi dalam 30 m' });
  assert.equal(marketStatus(tokyo, at('2026-10-19T03:30:00Z')).state, 'buka'); // 12.30 JST
  assert.equal(marketStatus(market('hk'), at('2026-10-19T04:30:00Z')).state, 'istirahat'); // 12.30 HKT
});

test('akhir pekan: tutup, dan bursa berikutnya buka Senin', () => {
  const sat = marketStatus(market('ny'), at('2026-10-17T15:00:00Z'));
  assert.equal(sat.state, 'tutup');
  assert.match(sat.note, /^akhir pekan, buka dalam 1 hari /);
  const open = nextOpen(market('ny'), at('2026-10-17T15:00:00Z'));
  assert.equal(open.toISOString(), '2026-10-19T13:30:00.000Z'); // Senin 09.30 EDT
  // Jumat sore sesudah tutup: buka berikutnya Senin, melewati akhir pekan.
  assert.equal(nextOpen(market('tokyo'), at('2026-10-16T07:00:00Z')).toISOString(), '2026-10-19T00:00:00.000Z');
});

test('buka berikutnya benar walau jam musim berganti di antaranya', () => {
  // Jumat 30 Okt 2026 sesudah tutup; Senin 2 Nov New York sudah memakai EST (09.30 = 14.30 UTC).
  assert.equal(nextOpen(market('ny'), at('2026-10-30T22:00:00Z')).toISOString(), '2026-11-02T14:30:00.000Z');
  // London pindah ke GMT pada 25 Okt: Senin 26 Okt 08.00 GMT = 08.00 UTC.
  assert.equal(nextOpen(market('london'), at('2026-10-24T10:00:00Z')).toISOString(), '2026-10-26T08:00:00.000Z');
});

test('fase kripto mengikuti sesi dan rentangnya dalam WIB (musim panas)', () => {
  const phase = (iso) => cryptoPhase(at(iso));
  assert.equal(phase('2026-10-19T12:00:00Z').id, 'peak'); // 19.00 WIB
  assert.equal(phase('2026-10-19T12:00:00Z').range, '19.00–01.00 WIB');
  assert.equal(phase('2026-10-19T18:00:00Z').id, 'decline'); // 01.00 WIB
  assert.equal(phase('2026-10-19T20:00:00Z').id, 'quiet'); // 03.00 WIB
  assert.equal(phase('2026-10-19T20:00:00Z').range, '03.00–07.00 WIB');
  assert.equal(phase('2026-10-19T00:00:00Z').id, 'asia'); // 07.00 WIB
  assert.equal(phase('2026-10-19T07:00:00Z').id, 'eu'); // 14.00 WIB
  assert.equal(phase('2026-10-19T07:00:00Z').range, '14.00–19.00 WIB');
});

test('fase kripto bergeser satu jam sesudah jam musim AS dan Eropa berganti', () => {
  const peak = cryptoPhase(at('2026-11-02T13:00:00Z')); // 20.00 WIB
  assert.equal(peak.id, 'peak');
  assert.equal(peak.range, '20.00–02.00 WIB');
  assert.equal(cryptoPhase(at('2026-11-02T12:59:00Z')).id, 'eu');
  assert.equal(cryptoPhase(at('2026-11-02T08:00:00Z')).range, '15.00–20.00 WIB');
  assert.equal(cryptoPhase(at('2026-10-19T12:00:00Z')).weekend, false);
  assert.equal(cryptoPhase(at('2026-10-17T12:00:00Z')).weekend, true); // Sabtu
});

test('garis waktu 24 jam menutup seluruh hari dan menandai sesi bursa', () => {
  const day = daySegments(at('2026-10-20T12:00:00Z')); // Selasa 19.00 WIB
  const covered = day.phases.reduce((sum, s) => sum + (s.to - s.from), 0);
  assert.ok(Math.abs(covered - 1) < 1e-9);
  assert.equal(day.phases[0].from, 0);
  assert.equal(day.phases.at(-1).to, 1);
  assert.ok(Math.abs(day.now - 19 / 24) < 1e-6);
  const ny = day.markets.find((m) => m.id === 'ny').open;
  // Bursa AS buka 20.30 WIB sampai 03.00 WIB: dari 20.30 dan dari tengah malam sampai 03.00.
  assert.equal(ny.length, 2);
  assert.ok(Math.abs(ny[1].from - 20.5 / 24) < 0.01);
  assert.ok(Math.abs(ny[0].to - 3 / 24) < 0.01);
  assert.equal(day.markets.length, MARKETS.length);
});

test('format durasi', () => {
  assert.equal(duration(0.2), 'kurang dari 1 m');
  assert.equal(duration(45), '45 m');
  assert.equal(duration(135), '2 j 15 m');
  assert.equal(duration(120), '2 j');
  assert.equal(duration(1440 + 180), '1 hari 3 j');
  assert.equal(duration(2880), '2 hari');
});

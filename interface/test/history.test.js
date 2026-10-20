'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const { PAGE, filterAnalyses, pageCount, pageSlice, pageItems, countText } = require('../renderer/history');

const list = [
  { symbol: 'BRUSDT', verdict: 'ok' },
  { symbol: 'AGTUSDT', verdict: 'tunggu' },
  { symbol: 'BRUSDT', verdict: 'tunggu' },
  { symbol: 'PHAUSDT', verdict: 'jangan' },
];

test('tanpa saringan semua analisis tampil, urutannya tetap', () => {
  assert.deepEqual(filterAnalyses(list), list);
});

test('cari nama koin tanpa peduli huruf besar dan spasi', () => {
  assert.deepEqual(filterAnalyses(list, { search: ' br usdt ' }).map((a) => a.verdict), ['ok', 'tunggu']);
  assert.deepEqual(filterAnalyses(list, { search: 'pha' }).map((a) => a.symbol), ['PHAUSDT']);
});

test('saring menurut keputusan, bisa digabung dengan pencarian', () => {
  assert.equal(filterAnalyses(list, { verdict: 'tunggu' }).length, 2);
  assert.deepEqual(filterAnalyses(list, { search: 'BR', verdict: 'tunggu' }), [list[2]]);
  assert.deepEqual(filterAnalyses(list, { verdict: 'ok', search: 'AGT' }), []);
});

test('30 analisis per halaman; halaman di luar batas dipaskan', () => {
  const many = Array.from({ length: 184 }, (_, i) => i);
  assert.equal(PAGE, 30);
  assert.equal(pageCount(184), 7);
  assert.equal(pageCount(0), 1);
  assert.deepEqual(pageSlice(many, 2).items, many.slice(30, 60));
  assert.deepEqual(pageSlice(many, 7).items, many.slice(180));
  assert.equal(pageSlice(many, 99).page, 7);
  assert.equal(pageSlice(many, 0).page, 1);
});

test('nomor halaman: awal, tengah, dan akhir daftar panjang', () => {
  assert.deepEqual(pageItems(1, 1), [1]);
  assert.deepEqual(pageItems(3, 7), [1, 2, 3, 4, 5, 6, 7]);
  assert.deepEqual(pageItems(1, 12), [1, 2, 3, 4, 5, '…', 12]);
  assert.deepEqual(pageItems(6, 12), [1, '…', 4, 5, 6, 7, 8, '…', 12]);
  assert.deepEqual(pageItems(12, 12), [1, '…', 8, 9, 10, 11, 12]);
  assert.deepEqual(pageItems(4, 34), [1, 2, 3, 4, 5, '…', 34]);
});

test('penghitung menjelaskan rentang yang tampil', () => {
  assert.equal(countText(1, 184, 184, false), 'Menampilkan 1–30 dari 184 analisis');
  assert.equal(countText(7, 184, 184, false), 'Menampilkan 181–184 dari 184 analisis');
  assert.equal(countText(1, 12, 12, false), 'Menampilkan 1–12 dari 12 analisis');
  assert.equal(countText(2, 40, 184, true), 'Menampilkan 31–40 dari 40 cocok dari 184 analisis');
  assert.equal(countText(1, 0, 184, true), 'Tidak ada yang cocok dari 184 analisis');
  assert.equal(countText(1, 0, 0, false), '');
});

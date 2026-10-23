'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const Tops = require('../renderer/tops');

const pick = (shortTops, longTops) => ({ shortTops, longTops });

test('contoh pengguna: short Top 2-3-4 dan long Top 1-5, atau short 2-4-5 dan long 1-2-3', () => {
  const a = pick([2, 3, 4], [1, 5]);
  assert.deepEqual(Tops.watched(a), [1, 2, 3, 4, 5]);
  assert.equal(Tops.note(a), 'Short: Top 2, 3, 4 · Long: Top 1, 5');
  const b = pick([2, 4, 5], [1, 2, 3]);
  assert.deepEqual(Tops.watched(b), [1, 2, 3, 4, 5]);
  assert.match(Tops.note(b), /Top 2 boleh keduanya/);
});

test('klik chip menyalakan dan mematikan Top per arah', () => {
  let tops = pick([1, 2, 3, 4, 5], []);
  for (const r of [1, 5]) tops = Tops.toggle(tops, 'short', r);
  for (const r of [1, 5]) tops = Tops.toggle(tops, 'long', r);
  assert.deepEqual(tops, pick([2, 3, 4], [1, 5]));
  assert.deepEqual(Tops.toggleAll(tops, 'long'), pick([2, 3, 4], [1, 2, 3, 4, 5]));
  assert.deepEqual(Tops.toggleAll(pick([1, 2, 3, 4, 5], [1]), 'short'), pick([], [1]));
});

test('minimal satu Top tetap dipantau', () => {
  assert.equal(Tops.toggle(pick([3], []), 'short', 3), null);
  assert.equal(Tops.toggleAll(pick([1, 2, 3, 4, 5], []), 'short'), null);
  assert.deepEqual(Tops.toggle(pick([3], [1]), 'short', 3), pick([], [1]));
});

test('pilihan lama diubah ke arah per Top; isian rusak tidak lolos', () => {
  assert.deepEqual(Tops.restore({ ranks: [3, 1], direction: 'short' }), pick([1, 3], []));
  assert.deepEqual(Tops.restore({ ranks: [2], direction: 'long' }), pick([], [2]));
  assert.deepEqual(Tops.restore({ ranks: [1, 2], direction: 'keduanya' }), pick([1, 2], [1, 2]));
  assert.deepEqual(Tops.restore({}), pick([1, 2, 3, 4, 5], []));
  assert.deepEqual(Tops.restore({ shortTops: [9, 2, 2], longTops: ['1'] }), pick([2], [1]));
  assert.deepEqual(Tops.restore({ shortTops: [], longTops: [] }), pick([1, 2, 3, 4, 5], []));
  assert.deepEqual(Tops.restore({ shortTops: 'x', longTops: [1] }), pick([1, 2, 3, 4, 5], []));
});

'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const Interval = require('../renderer/interval');

test('jeda sendiri dalam menit: angka bulat 5..1440', () => {
  assert.deepEqual(Interval.parse('45'), { minutes: 45 });
  assert.deepEqual(Interval.parse(' 90 '), { minutes: 90 });
  assert.deepEqual(Interval.parse('1440'), { minutes: 1440 });
  for (const bad of ['', '4', '1441', '2,5', '10.5', '-5', 'abc', '1e3']) {
    assert.ok(Interval.parse(bad).error, `seharusnya ditolak: ${JSON.stringify(bad)}`);
  }
});

test('jeda tersimpan dipulihkan; isian rusak kembali ke Sekali', () => {
  for (const ok of [0, 15, 30, 60, 45, 1440]) assert.equal(Interval.restore(ok), ok);
  for (const bad of [3, 2.5, 5000, 'x', undefined, null]) assert.equal(Interval.restore(bad), 0);
});

test('kalimat di bawah pilihan menyebut jedanya', () => {
  assert.match(Interval.note(0), /Satu putaran saja/);
  assert.match(Interval.note(45), /tiap 45 menit/);
  assert.match(Interval.note(90), /tiap 1 jam 30 menit/);
  assert.match(Interval.note(120), /tiap 2 jam;/);
});

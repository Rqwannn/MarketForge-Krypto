'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const { explain, splitSummary } = require('../renderer/reasons');

const step = (card, id) => card.steps.find((s) => s.id === id);

// Kasus nyata dari putaran Binance 19 Okt 2026 (jurnal engine/journal/sop.jsonl).
const ARIA = {
  status: 'skipped', verdict: 'tunggu', change_pct: 23.672, funding_rate: 0.00005, spread_pct: 0.0585,
  ma_gap_pct: -0.6595, ai: { below_count: 2, below_now: true, below_recent: true, lines_close: true },
  data: { below_count: 2, below_now: false, below_recent: true },
  summary: 'MA7 sedikit di bawah MA25 di ujung kanan. (5 bacaan AI: 2+, 2+, 2+, 2+, 2+)',
  reason: 'pola garis kuning TUNGGU (garis MA7 dan MA25 berdekatan; masuk hanya bila berjauhan)',
};
const GTC = {
  status: 'skipped', verdict: 'ok', change_pct: 20.5, funding_rate: -0.00327726, spread_pct: 0.02,
  ai: { below_count: 3, below_now: false, below_recent: true, lines_close: false },
  summary: 'Garis kuning jauh di atas magenta. (5 bacaan AI: 3+, 3+, 0+, 1+, 3+)',
  reason: 'funding -0.3277% terlalu negatif (short membayar)',
};

test('garis berdekatan dijelaskan sebagai alasan menunggu, bukan "baru sekali di bawah"', () => {
  const card = explain(ARIA, { platform: 'binance' });
  assert.equal(card.tone, 'warn');
  assert.equal(card.stoppedAt, 'pola');
  assert.match(card.because, /berdekatan/);
  assert.doesNotMatch(card.because, /baru 2 kali|baru sekali/);
  assert.match(step(card, 'pola').title, /MA7 \/ MA25: Tunggu/);
  assert.ok(step(card, 'pola').details.some((l) => /0,66% di atas MA25/.test(l)));
  assert.equal(step(card, 'slot').state, 'skip');
});

test('catatan lama yang dilewati aturan funding dijelaskan sebagai aturan lama', () => {
  const card = explain(GTC, { plain: () => 'aturan funding lama' });
  assert.equal(card.tone, 'bad');
  assert.equal(card.stoppedAt, 'funding');
  assert.match(step(card, 'funding').title, /lama, sudah dihapus/);
  assert.equal(card.because, 'aturan funding lama');
  assert.equal(step(card, 'pola').state, 'pass');
  assert.equal(step(card, 'spread').state, 'pass');
  assert.equal(step(card, 'order'), undefined);
});

test('funding rate tidak pernah menyaring koin baru', () => {
  const card = explain({ ...GTC, status: 'open', reason: '' });
  assert.equal(step(card, 'funding'), undefined);
  assert.equal(card.tone, 'good');
  const pattern = explain({ ...GTC, verdict: 'jangan', reason: 'pola garis kuning JANGAN', ai: { below_count: 0 } });
  assert.equal(step(pattern, 'funding'), undefined);
  assert.equal(pattern.stoppedAt, 'pola');
});

test('baru sekali di bawah dan jangan short punya penjelasan sendiri', () => {
  const wait = explain({ status: 'skipped', verdict: 'tunggu', ai: { below_count: 1, below_recent: true, lines_close: false } });
  assert.match(wait.because, /Baru 1 kali di bawah \(minimal 2\)/);
  const no = explain({ status: 'skipped', verdict: 'jangan', ai: { below_count: 0 } });
  assert.equal(no.tone, 'bad');
  assert.match(no.because, /MA7 selalu di atas MA25/);
});

test('6 jam terakhir naik terus', () => {
  const card = explain({ status: 'skipped', verdict: 'tunggu', ai: { below_count: 3, below_recent: false } });
  assert.match(card.because, /6 jam terakhir harga naik terus/);
});

test('Tebbit memakai MA5 dan MA10', () => {
  const card = explain({ status: 'skipped', verdict: 'tunggu', ai: { below_count: 1 } }, { platform: 'tebbit' });
  assert.match(step(card, 'pola').title, /MA5 \/ MA10/);
});

test('hitungan AI dan data yang berbeda disebut, keputusan memakai AI', () => {
  const card = explain({ ...ARIA, data: { below_count: 3 } });
  assert.ok(step(card, 'pola').details.some((l) => /Hitungan dari data candle: 3 kali/.test(l)));
});

test('posisi terbuka: semua langkah lolos dengan rincian order', () => {
  const card = explain({
    status: 'open', verdict: 'ok', change_pct: 12, funding_rate: 0.0001, spread_pct: 0.05, ai: { below_count: 3, below_recent: true },
    leverage: 2, margin_usdt: 50, notional: 100, entry_price: 1.5, target_price: 1.455,
  });
  assert.equal(card.tone, 'good');
  assert.equal(card.stoppedAt, null);
  assert.match(card.headline, /uji kertas/);
  assert.match(step(card, 'order').text, /margin 50,00 USDT, leverage 2x.*Masuk di 1.5, jual otomatis di 1.455 \(tanpa stop-loss\)/);
  assert.match(explain({ status: 'open', verdict: 'ok', real: true }).headline, /uang sungguhan/);
});

test('posisi lain yang sedang rugi menahan koin berikutnya', () => {
  const card = explain({
    status: 'skipped', verdict: 'ok', change_pct: 9, funding_rate: 0, spread_pct: 0.05, ai: { below_count: 3, below_recent: true },
    reason: 'posisi ZEREBROUSDT sedang rugi (0.041781 > masuk 0.041602); koin berikutnya belum boleh dibuka',
  }, { plain: (t) => `ditunda: ${t.slice(0, 20)}` });
  assert.equal(card.stoppedAt, 'slot');
  assert.match(card.because, /^ditunda: posisi ZEREBROUSDT/);
});

test('hasil pemimpin: biaya dan slot diserahkan ke pengikut', () => {
  const ok = explain({ status: 'analyzed', verdict: 'ok', count_ai: 3, ai: { below_count: 3, below_recent: true } });
  assert.equal(ok.tone, 'good');
  assert.equal(step(ok, 'biaya').state, 'skip');
  assert.match(ok.because, /pengikut/i);
  assert.equal(explain({ status: 'analyzed', verdict: 'tunggu', count_ai: 1 }).tone, 'neutral');
});

test('peristiwa lama tanpa angka tetap dijelaskan dari alasan teks', () => {
  const card = explain({ status: 'skipped', verdict: 'ok', count_ai: 3, reason: 'Satuan kolom Jumlah bukan USDT' }, { plain: () => 'Satuan salah' });
  assert.equal(card.stoppedAt, 'order');
  assert.equal(step(card, 'order').state, 'fail');
  assert.equal(explain({ status: 'skipped', reason: 'x' }, { plain: (t) => t.toUpperCase() }).because, 'X');
});

test('ringkasan AI dipisah dari daftar bacaan', () => {
  const { text, votes } = splitSummary('Garis turun. (5 bacaan AI: 2+, 3, 0+)');
  assert.equal(text, 'Garis turun.');
  assert.deepEqual(votes, [{ count: 2, recent: true }, { count: 3, recent: false }, { count: 0, recent: true }]);
  assert.deepEqual(splitSummary('tanpa daftar').votes, []);
  assert.deepEqual(splitSummary(undefined), { text: '', votes: [] });
});

test('limits dari engine menimpa angka bawaan', () => {
  const wide = { status: 'skipped', verdict: 'ok', spread_pct: 0.4, ai: { below_count: 3, below_recent: true } };
  assert.equal(step(explain(wide), 'spread').state, 'fail');
  assert.equal(step(explain({ ...wide, limits: { max_spread_pct: 0.5 } }), 'spread').state, 'pass');
});

test('koin long: pola short tidak menghentikan, tanda long menjelaskan masuknya', () => {
  const card = explain({
    status: 'open', verdict: 'long', side: 'long', real: false, change_pct: 30,
    ai: { below_count: 1, below_now: false, below_recent: false },
    long_ai: { reversal: true, flat: false, far_above: false, summary: 'Dua dasar lalu naik.' },
    long_data: { ma7_above_ma25_pct: 1.5, ma7_above_ma99_pct: 12, ma_spread_pct: 4 },
    entry_price: 0.021, target_price: 0.02184, cutloss_price: 0.0189,
  });
  assert.equal(card.headline, 'Bot masuk long (uji kertas)');
  assert.equal(step(card, 'pola').state, 'info');
  assert.equal(step(card, 'long').state, 'pass');
  assert.match(step(card, 'long').title, /tanda 1/);
  assert.match(step(card, 'order').text, /cutloss di 0.0189/);
});

test('grafik layak short dan long sekaligus: tidak masuk karena tanda long', () => {
  const card = explain({
    status: 'skipped', verdict: 'konflik', reason: 'grafik memenuhi syarat SHORT dan menunjukkan tanda 3',
    ai: { below_count: 3, below_now: true, below_recent: true },
    long_ai: { reversal: false, flat: false, far_above: true, summary: '' },
  });
  assert.equal(step(card, 'pola').state, 'pass');
  assert.equal(card.stoppedAt, 'long');
});

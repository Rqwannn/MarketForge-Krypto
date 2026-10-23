'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const { healthWarnings, logNotice, lossAlerts, networkState, settleNetwork } = require('../alerts');

const NOW = Date.parse('2026-10-20T10:00:00+07:00');
const base = { exchange: 'binance', network: 'ok', onBattery: false, sleep: null, running: true, realOpen: 0, now: NOW };

test('jaringan: diblokir hanya bila bursa gagal tetapi internet jalan', () => {
  assert.equal(networkState(true, false), 'ok');
  assert.equal(networkState(false, true), 'blocked'); // seperti pagi ini: fapi.binance.com NXDOMAIN
  assert.equal(networkState(false, false), 'offline');
});

test('jaringan lambat: satu cek habis waktu belum memunculkan peringatan, dua beruntun baru', () => {
  let s = settleNetwork('ok', 'offline', true, 0); // Wi-Fi lambat, sistem masih tersambung
  assert.deepEqual(s, { network: 'ok', fails: 1 });
  s = settleNetwork(s.network, 'ok', true, s.fails);
  assert.deepEqual(s, { network: 'ok', fails: 0 });
  s = settleNetwork('ok', 'blocked', true, 0);
  s = settleNetwork(s.network, 'blocked', true, s.fails);
  assert.equal(s.network, 'blocked');
  assert.equal(settleNetwork('ok', 'offline', false, 0).network, 'offline'); // Wi-Fi mati: langsung
});

test('tanpa masalah: tidak ada peringatan', () => {
  assert.deepEqual(healthWarnings(base), []);
});

test('Binance diblokir di jaringan ini: peringatan merah yang menyebut solusinya', () => {
  const [w] = healthWarnings({ ...base, network: 'blocked' });
  assert.equal(w.level, 'bad');
  assert.match(w.text, /diblokir di jaringan ini.*VPN/);
  assert.match(healthWarnings({ ...base, exchange: 'tebbit', network: 'blocked' })[0].text, /Tebbit/);
});

test('posisi uang sungguhan tanpa bot berjalan: jual otomatis tidak aktif', () => {
  const [w] = healthWarnings({ ...base, running: false, realOpen: 1 });
  assert.equal(w.level, 'bad');
  assert.match(w.text, /jual otomatis tidak aktif/);
});

test('charger dilepas hanya diperingatkan saat ada yang dipantau', () => {
  assert.match(healthWarnings({ ...base, onBattery: true })[0].text, /Charger dilepas/);
  assert.deepEqual(healthWarnings({ ...base, onBattery: true, running: false }), []);
});

test('laptop sempat tidur saat memantau: berapa lama dan kapan (seperti 08.21-08.47 kemarin)', () => {
  const from = Date.parse('2026-10-20T08:21:00+07:00');
  const to = Date.parse('2026-10-20T08:47:00+07:00');
  const [w] = healthWarnings({ ...base, sleep: { from, to, minutes: 26, watching: true } });
  assert.equal(w.level, 'warn');
  assert.match(w.text, /tidur 26 menit/);
  // Tidur saat tidak ada yang dipantau, atau sudah lama sekali: tidak perlu diingatkan.
  assert.deepEqual(healthWarnings({ ...base, sleep: { from, to, minutes: 26, watching: false } }), []);
  assert.deepEqual(healthWarnings({ ...base, now: to + 13 * 3600e3, sleep: { from, to, minutes: 26, watching: true } }), []);
});

test('batas rugi: sekali per posisi sungguhan, dipasang lagi setelah membaik', () => {
  const alerted = new Set();
  const aria = (pnl) => [{ symbol: 'ARIAUSDT', real: true, pnl_pct: pnl }, { symbol: 'PAPERUSDT', real: false, pnl_pct: -40 }];
  assert.equal(lossAlerts(aria(-12), 20, alerted).length, 0);
  const [n] = lossAlerts(aria(-21.2), 20, alerted);
  assert.match(n.title, /ARIAUSDT rugi 21,2%/);
  assert.match(n.body, /tetap menahan/);
  assert.equal(lossAlerts(aria(-28.5), 20, alerted).length, 0); // sudah diberi tahu
  assert.equal(lossAlerts(aria(-10), 20, alerted).length, 0); // membaik: dipasang lagi
  assert.equal(lossAlerts(aria(-22), 20, alerted).length, 1);
  assert.equal(lossAlerts(aria(-50), 0, new Set()).length, 0); // batas mati
  lossAlerts([], 20, alerted);
  assert.equal(alerted.size, 0); // posisi sudah tertutup: lupakan
});

test('log engine jadi notifikasi: terjual, gagal jual, posisi hilang', () => {
  const sold = logNotice({ ts: 1, message: 'Posisi ditutup di bursa. Jual otomatis ICNTUSDT (target) di 0.1753: +3.60% posisi (+3.60 USDT = +3.60% modal)' });
  assert.equal(sold.title, 'ICNTUSDT terjual otomatis');
  assert.match(sold.body, /\+3,60 USDT/);
  const fail = logNotice({ message: 'Jual otomatis ARIAUSDT GAGAL di bursa, posisi tetap terbuka: Tab Posisi tidak ditemukan' });
  assert.equal(fail.key, 'fail:ARIAUSDT');
  const gone = logNotice({ message: 'Posisi ARIAUSDT tidak ada lagi...', event: { type: 'position_missing', symbol: 'ARIAUSDT' } });
  assert.match(gone.body, /ditutup manual/);
  assert.equal(logNotice({ message: '[DRY RUN] Tombol tutup posisi TIDAK ditekan. Jual otomatis X (target)' }), null);
  assert.equal(logNotice({ message: 'Cek ulang ARIAUSDT sebelum menjual' }), null);
});

test('peringatan rugi menyebut cutloss atau batas waktu bila menyala', () => {
  const at = (extra) => lossAlerts([{ symbol: 'AUSDT', real: true, pnl_pct: -12, ...extra }], 10, new Set())[0].body;
  assert.match(at({}), /menahan sampai harga turun ke target/);
  assert.match(at({ side: 'long' }), /naik ke target/);
  assert.match(at({ cutloss_price: 1.1 }), /cutloss 10%/);
  assert.match(at({ time_exit_at: 1 }), /paling lama 3 jam/);
});

test('notifikasi terjual menyebut alasan cutloss dan batas waktu', () => {
  const sold = (status) => logNotice({
    message: `Posisi ditutup di bursa. Jual otomatis AUSDT (${status}) di 1.1: -10.20% posisi (-10.20 USDT = -10.20% modal)`,
  });
  assert.equal(sold('stop').title, 'AUSDT terjual otomatis karena cutloss');
  assert.equal(sold('timeout').title, 'AUSDT terjual otomatis karena batas waktu');
  assert.equal(sold('target').title, 'AUSDT terjual otomatis');
});

'use strict';

// Peringatan untuk pengguna: kesehatan laptop (jaringan, charger, tidur), rugi posisi sungguhan,
// dan kejadian jual dari log engine. Murni tanpa Electron supaya bisa diuji di Node; main.js yang
// mengukur keadaan dan menampilkan notifikasinya.

const SITE = { binance: 'Binance', tebbit: 'Tebbit' };
// Alamat yang dipakai bot untuk data harga, dan pembanding untuk membedakan "diblokir" dari
// "tidak ada internet".
const NETWORK_TARGETS = {
  binance: 'https://fapi.binance.com/fapi/v1/ping',
  tebbit: 'https://tebbit.io/',
};
const CONTROL_TARGET = 'https://www.google.com/generate_204';
const SLEEP_MEMORY_MS = 12 * 3600 * 1000; // tidur lebih lama dari ini sudah tidak relevan
// Wi-Fi lambat bisa membuat satu cek habis waktu; peringatan baru tampil setelah gagal beruntun.
const NETWORK_FAILS_TO_WARN = 2;

/** Hasil cek bursa dan pembanding -> 'ok', 'blocked' (hanya bursa gagal), atau 'offline'. */
function networkState(exchangeOk, controlOk) {
  if (exchangeOk) return 'ok';
  return controlOk ? 'blocked' : 'offline';
}

/**
 * Keadaan jaringan yang ditampilkan setelah satu cek. `measured`: hasil `networkState`, `online`:
 * sistem operasi masih punya sambungan, `fails`: gagal beruntun sebelumnya. Tanpa sambungan sama
 * sekali langsung 'offline'; selain itu gagal harus beruntun dulu, sebelumnya keadaan lama dipakai.
 */
function settleNetwork(current, measured, online, fails) {
  if (!online) return { network: 'offline', fails: fails + 1 };
  if (measured === 'ok') return { network: 'ok', fails: 0 };
  const streak = fails + 1;
  return { network: streak >= NETWORK_FAILS_TO_WARN ? measured : current, fails: streak };
}

const clock = (ms) => new Date(ms).toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit' });

/**
 * Daftar peringatan dari keadaan laptop. `h`: { exchange, network, onBattery, sleep, running,
 * realOpen, now }. Hasil: [{ level: 'bad' | 'warn', text }], paling penting dulu.
 */
function healthWarnings(h) {
  const site = SITE[h.exchange] || 'Binance';
  const watching = Boolean(h.running || h.realOpen);
  const out = [];
  if (h.network === 'blocked') {
    out.push({
      level: 'bad',
      text: h.exchange === 'tebbit'
        ? 'Situs Tebbit tidak bisa dibuka di jaringan ini. Ganti Wi-Fi atau pakai VPN.'
        : 'Data harga Binance diblokir di jaringan ini. Ganti Wi-Fi atau pakai VPN; tanpa data ini bot tidak masuk posisi dan tidak bisa jual otomatis.',
    });
  } else if (h.network === 'offline') {
    out.push({ level: 'bad', text: 'Laptop tidak tersambung ke internet.' });
  }
  if (h.realOpen && !h.running) {
    out.push({
      level: 'bad',
      text: `Ada ${h.realOpen} posisi uang sungguhan, tetapi bot tidak berjalan: jual otomatis tidak aktif. Tekan Mulai memantau.`,
    });
  }
  if (h.onBattery && watching) {
    out.push({ level: 'warn', text: 'Charger dilepas. Pasang charger supaya laptop tidak tidur saat bot memantau.' });
  }
  const sleep = h.sleep;
  if (sleep && sleep.watching && sleep.minutes >= 1 && (h.now ?? Date.now()) - sleep.to < SLEEP_MEMORY_MS) {
    out.push({
      level: 'warn',
      text: `Laptop sempat tidur ${sleep.minutes} menit (${clock(sleep.from)}–${clock(sleep.to)}). Selama itu bot tidak memantau ${site}.`,
    });
  }
  return out;
}

/**
 * Notifikasi rugi posisi sungguhan yang melewati batas `limitPct` (persen nilai posisi).
 * `alerted` (Set simbol) mencegah notifikasi berulang; dipasang lagi bila rugi membaik jauh.
 * Hanya pemberitahuan: bot tetap menahan posisi sampai target.
 */
function lossAlerts(positions, limitPct, alerted) {
  const notices = [];
  const open = new Set();
  for (const p of positions || []) {
    if (!p.real || typeof p.pnl_pct !== 'number') continue;
    open.add(p.symbol);
    if (!(limitPct > 0)) continue;
    if (p.pnl_pct <= -limitPct && !alerted.has(p.symbol)) {
      alerted.add(p.symbol);
      notices.push({
        key: `loss:${p.symbol}`,
        title: `${p.symbol} rugi ${Math.abs(p.pnl_pct).toFixed(1).replace('.', ',')}%`,
        body: `Melewati batas ${limitPct}% yang kamu pilih. Bot tetap menahan sampai harga turun ke target.`,
      });
    } else if (p.pnl_pct > -limitPct * 0.8) {
      alerted.delete(p.symbol);
    }
  }
  for (const symbol of [...alerted]) if (!open.has(symbol)) alerted.delete(symbol);
  return notices;
}

/** Baris log engine -> notifikasi (terjual, gagal jual, posisi hilang dari bursa), atau null. */
function logNotice(entry) {
  const message = String(entry?.message || '');
  const e = entry?.event;
  if (e?.type === 'position_missing' && e.symbol) {
    return {
      key: `missing:${e.symbol}`,
      title: `${e.symbol} tidak ada lagi di Binance`,
      body: 'Kemungkinan sudah ditutup manual. Buka menu Posisi untuk mencatat penutupannya.',
    };
  }
  let m = message.match(/Posisi ditutup di bursa\. Jual otomatis (\S+) .*?\(([+-][\d.]+) USDT/);
  if (m) {
    const usdt = Number(m[2]);
    return {
      key: `sold:${m[1]}:${entry.ts || ''}`,
      title: `${m[1]} terjual otomatis`,
      body: `Hasil ${usdt >= 0 ? '+' : ''}${usdt.toFixed(2).replace('.', ',')} USDT. Cek Riwayat Posisi di Binance.`,
    };
  }
  m = message.match(/Jual otomatis (\S+) GAGAL di bursa/);
  if (m) {
    return {
      key: `fail:${m[1]}`,
      title: `Jual otomatis ${m[1]} gagal`,
      body: 'Posisi tetap terbuka; bot mencoba lagi tiap menit. Pastikan jendela Binance terlihat.',
    };
  }
  return null;
}

module.exports = { CONTROL_TARGET, NETWORK_TARGETS, healthWarnings, logNotice, lossAlerts, networkState, settleNetwork };

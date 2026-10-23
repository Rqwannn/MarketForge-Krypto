'use strict';

// Ulangi pemantauan: pilihan cepat (Sekali, 15, 30, 60 menit) atau waktu sendiri dalam menit.
// Murni fungsi tanpa DOM supaya bisa diuji di Node; app.js yang menggambarnya.

(function (root) {
  const PRESETS = [0, 15, 30, 60]; // 0 = sekali
  // Satu putaran (buka 5 koin + AI membaca grafik) sudah beberapa menit: jeda di bawah ini hanya
  // menambah panggilan AI. Paling lama sehari, sama dengan batas engine.
  const MIN_MINUTES = 5;
  const MAX_MINUTES = 1440;

  /** Teks kolom menit -> { minutes } atau { error } (pesan untuk pengguna). */
  function parse(text) {
    const raw = String(text ?? '').trim();
    if (!raw) return { error: 'Isi jeda dalam menit' };
    if (!/^\d+$/.test(raw)) return { error: 'Jeda harus angka bulat dalam menit' };
    const minutes = Number(raw);
    if (minutes < MIN_MINUTES || minutes > MAX_MINUTES) {
      return { error: `Jeda ${MIN_MINUTES}–${MAX_MINUTES} menit (1440 menit = 24 jam)` };
    }
    return { minutes };
  }

  /** Jeda tersimpan -> pilihan cepat atau waktu sendiri yang sah; selain itu Sekali. */
  function restore(minutes) {
    const n = Number(minutes);
    if (PRESETS.includes(n)) return n;
    return Number.isInteger(n) && n >= MIN_MINUTES && n <= MAX_MINUTES ? n : 0;
  }

  /** Kalimat di bawah pilihan, mis. "Diulang tiap 45 menit." */
  function note(minutes) {
    if (!minutes) return 'Satu putaran saja, lalu bot berhenti.';
    const hours = Math.floor(minutes / 60);
    const rest = minutes % 60;
    const text = hours ? `${hours} jam${rest ? ` ${rest} menit` : ''}` : `${minutes} menit`;
    return `Diulang tiap ${text}; tiap putaran membaca ulang daftar top gainers.`;
  }

  const api = { PRESETS, MIN_MINUTES, MAX_MINUTES, parse, restore, note };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.Interval = api;
})(typeof window !== 'undefined' ? window : globalThis);

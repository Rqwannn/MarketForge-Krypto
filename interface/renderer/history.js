'use strict';

// Riwayat analisis AI di halaman Hasil uji: saringan (nama koin, keputusan) dan halaman bernomor.
// Engine mengirim sampai ribuan analisis terbaru; aplikasi menampilkan 30 per halaman
// (< 1 2 3 4 5 ... 12 >) supaya gambar grafik tidak dimuat sekaligus. Murni fungsi tanpa DOM supaya
// bisa diuji di Node; app.js yang menggambarnya.

(function (root) {
  const PAGE = 30;

  /** Analisis (terbaru dulu) yang cocok dengan pencarian koin dan keputusan ('' = semua). */
  function filterAnalyses(list, { search = '', verdict = '' } = {}) {
    const term = search.trim().toUpperCase().replace(/\s+/g, '');
    return list.filter((a) =>
      (!term || String(a.symbol || '').toUpperCase().includes(term))
      && (!verdict || a.verdict === verdict));
  }

  /** Jumlah halaman untuk `count` analisis (minimal 1). */
  function pageCount(count, size = PAGE) {
    return Math.max(1, Math.ceil(count / size));
  }

  /** Isi halaman `page` (mulai 1; di luar batas dipaskan ke halaman terdekat). */
  function pageSlice(list, page, size = PAGE) {
    const current = Math.min(Math.max(1, page), pageCount(list.length, size));
    return { page: current, items: list.slice((current - 1) * size, current * size) };
  }

  /**
   * Tombol nomor halaman: halaman pertama, terakhir, dan dua di kiri-kanan halaman aktif; celahnya
   * jadi '…'. Contoh (aktif 6 dari 12): [1, '…', 4, 5, 6, 7, 8, '…', 12]. Di awal dan akhir daftar
   * lima nomor pertama/terakhir tampil berurutan: [1, 2, 3, 4, 5, '…', 12].
   */
  function pageItems(current, total) {
    if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1);
    let lo = Math.max(2, current - 2);
    let hi = Math.min(total - 1, current + 2);
    if (current <= 4) { lo = 2; hi = 5; }
    if (current >= total - 3) { lo = total - 4; hi = total - 1; }
    const items = [1];
    if (lo > 2) items.push('…');
    for (let n = lo; n <= hi; n += 1) items.push(n);
    if (hi < total - 1) items.push('…');
    items.push(total);
    return items;
  }

  /** Teks penghitung, mis. "Menampilkan 31-60 dari 184 analisis". */
  function countText(page, matched, total, filtered, size = PAGE) {
    if (!total) return '';
    if (!matched) return `Tidak ada yang cocok dari ${total} analisis`;
    const start = (page - 1) * size + 1;
    const end = Math.min(page * size, matched);
    const of = filtered && matched !== total ? `${matched} cocok dari ${total}` : `${matched}`;
    return `Menampilkan ${start}–${end} dari ${of} analisis`;
  }

  const api = { PAGE, filterAnalyses, pageCount, pageSlice, pageItems, countText };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.History = api;
})(typeof window !== 'undefined' ? window : globalThis);

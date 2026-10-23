'use strict';

// Arah per Top di Pengaturan putaran (SOP 23 Okt): Top mana yang boleh short dan Top mana yang
// boleh long. Murni fungsi tanpa DOM supaya bisa diuji di Node; app.js yang menggambarnya.

(function (root) {
  const RANKS = [1, 2, 3, 4, 5];

  /** Daftar Top yang rapi (1..5, tanpa duplikat, terurut), atau null bila bukan daftar. */
  function clean(list) {
    if (!Array.isArray(list)) return null;
    return [...new Set(list.map(Number))].filter((r) => RANKS.includes(r)).sort((a, b) => a - b);
  }

  /** Top yang dipantau: gabungan Top short dan Top long. */
  function watched({ shortTops, longTops }) {
    return clean([...shortTops, ...longTops]);
  }

  /**
   * Pilihan tersimpan -> { shortTops, longTops }. Pilihan lama (daftar Top yang dipantau + satu
   * arah untuk semua: short, long, atau keduanya) diubah ke arah per Top. Minimal satu Top.
   */
  function restore(saved) {
    let shortTops = clean(saved?.shortTops);
    let longTops = clean(saved?.longTops);
    if (shortTops === null || longTops === null) {
      const old = clean(saved?.ranks);
      const ranks = old && old.length ? old : [...RANKS];
      const direction = saved?.direction;
      shortTops = direction === 'long' ? [] : ranks;
      longTops = direction === 'long' || direction === 'keduanya' ? ranks : [];
    }
    if (!shortTops.length && !longTops.length) shortTops = [...RANKS];
    return { shortTops, longTops };
  }

  /** Ganti daftar satu arah (`side`: 'short' | 'long'). Ditolak (null) bila tidak ada Top tersisa. */
  function setSide(tops, side, list) {
    const next = { ...tops, [side === 'short' ? 'shortTops' : 'longTops']: clean(list) };
    return watched(next).length ? next : null;
  }

  /** Klik satu chip: Top `rank` dinyalakan/dimatikan untuk arah `side`. */
  function toggle(tops, side, rank) {
    const list = side === 'short' ? tops.shortTops : tops.longTops;
    return setSide(tops, side, list.includes(rank) ? list.filter((r) => r !== rank) : [...list, rank]);
  }

  /** Klik label baris: semua Top untuk arah ini, atau kosong bila sudah semua. */
  function toggleAll(tops, side) {
    const list = side === 'short' ? tops.shortTops : tops.longTops;
    return setSide(tops, side, list.length === RANKS.length ? [] : RANKS);
  }

  /** Ringkasan, mis. "Short: Top 2, 3, 4 · Long: Top 1, 5". */
  function note({ shortTops, longTops }) {
    const text = (list) => list.join(', ');
    const both = shortTops.filter((r) => longTops.includes(r));
    const parts = [
      shortTops.length ? `Short: Top ${text(shortTops)}` : 'Tanpa short',
      longTops.length ? `Long: Top ${text(longTops)}` : 'Tanpa long',
    ];
    if (both.length) parts.push(`Top ${text(both)} boleh keduanya; grafik yang cocok untuk keduanya dilewati`);
    return parts.join(' · ');
  }

  const api = { RANKS, clean, watched, restore, setSide, toggle, toggleAll, note };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.Tops = api;
})(typeof window !== 'undefined' ? window : globalThis);

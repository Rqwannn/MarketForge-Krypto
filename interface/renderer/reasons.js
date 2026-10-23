'use strict';

// Kartu "kenapa": menjelaskan keputusan bot untuk satu koin langkah demi langkah, dalam kalimat
// sehari-hari. Urutan langkah mengikuti SOP (kenaikan -> pola garis -> spread -> slot -> order).
// Funding rate tidak dinilai lagi (keputusan tim 20 Okt 2026); catatan lama yang dilewati karena
// funding tetap dijelaskan dari teks alasannya.
// Murni fungsi tanpa DOM supaya bisa diuji di Node; app.js yang menggambarnya.

(function (root) {
  const PERIODS = { binance: { fast: 7, mid: 25 }, tebbit: { fast: 5, mid: 10 } };
  // Cermin SopParams bawaan; bila engine mengirim `limits` (batas yang sedang dipakai), itu menang.
  const DEFAULT_LIMITS = { min_crosses: 2, max_spread_pct: 0.3, min_gain_pct: 0 };
  const VERDICT_LABEL = {
    ok: 'Layak short', tunggu: 'Tunggu', jangan: 'Jangan short', long: 'Layak long', konflik: 'Short dan long',
  };
  const ENTER = ['ok', 'long'];
  const SIGN_TEXT = { 1: 'turun tajam lalu berbalik', 2: 'posisi datar', 3: 'garis cepat jauh di atas' };
  const IDENTITY = (text) => String(text || '');

  const comma = (n, digits) => n.toFixed(digits).replace('.', ',');
  const signed = (n, digits) => `${n > 0 ? '+' : ''}${comma(n, digits)}`;
  const known = (v) => v !== null && v !== undefined && Number.isFinite(Number(v));

  /** "(5 bacaan AI: 2+, 3, 0+)" di akhir ringkasan -> { text, votes: [{count, recent}] }. */
  function splitSummary(summary) {
    const m = String(summary || '').match(/\s*\((\d+) bacaan AI: ([^)]*)\)\s*$/);
    if (!m) return { text: String(summary || ''), votes: [] };
    const votes = m[2].split(',').map((v) => v.trim().match(/^(\d+)(\+?)$/)).filter(Boolean)
      .map((v) => ({ count: Number(v[1]), recent: v[2] === '+' }));
    return { text: String(summary).slice(0, m.index), votes };
  }

  function patternWhy(verdict, ai, limits, names) {
    if (verdict === 'ok') return 'Sudah berkali-kali di bawah dan baru saja turun lagi: harga cenderung turun.';
    if (verdict === 'jangan') return `${names.fast} selalu di atas ${names.mid}: harga naik terus, belum ada tanda berbalik.`;
    if (ai.lines_close === true && ai.below_recent !== false) {
      return 'Kedua garis berdekatan. Bot masuk hanya bila garisnya berjauhan.';
    }
    if (known(ai.below_count) && ai.below_count < limits.min_crosses) {
      return `Baru ${ai.below_count} kali di bawah (minimal ${limits.min_crosses}): harga masih bisa naik lagi.`;
    }
    if (ai.below_recent === false) return 'Dalam 6 jam terakhir harga naik terus, walau sebelumnya sempat turun.';
    return 'Pola belum cukup meyakinkan untuk masuk.';
  }

  function patternStep(e, ai, data, limits, names) {
    // Grafik yang cocok untuk short dan long sekaligus: bacaan short-nya sendiri "layak short".
    const verdict = e.verdict === 'konflik' ? 'ok' : e.verdict;
    if (verdict === 'long') {
      return { id: 'pola', state: 'info', title: `Pola garis ${names.fast} / ${names.mid}: bukan short`, text: 'Koin ini dinilai dengan tanda long.' };
    }
    if (!ai && !data) {
      return { id: 'pola', state: 'skip', title: `Pola garis ${names.fast} / ${names.mid}`, text: 'Belum ada bacaan grafik untuk koin ini.' };
    }
    const read = ai || data;
    const source = ai ? 'AI' : 'data candle';
    const lines = [];
    if (known(read.below_count)) {
      lines.push(`${source} menghitung ${names.fast} turun di bawah ${names.mid} sebanyak ${read.below_count} kali di grafik 15 menit (minimal ${limits.min_crosses}).`);
    }
    if (read.below_recent === true) lines.push('Dalam 6 jam terakhir garis cepat pernah di bawah.');
    if (read.below_recent === false) lines.push('Dalam 6 jam terakhir garis cepat tidak pernah di bawah.');
    if (read.below_now === true) lines.push('Saat ini garis cepat ada di bawah.');
    if (read.lines_close === true) lines.push('Di ujung kanan kedua garis berdekatan.');
    if (read.lines_close === false) lines.push('Di ujung kanan kedua garis berjauhan.');
    if (ai && data && known(data.below_count) && data.below_count !== ai.below_count) {
      lines.push(`Hitungan dari data candle: ${data.below_count} kali. Yang dipakai keputusan adalah bacaan AI.`);
    }
    if (known(e.ma_gap_pct)) {
      const gap = Number(e.ma_gap_pct);
      lines.push(gap > 0
        ? `Jarak sekarang: ${names.fast} ${comma(gap, 2)}% di bawah ${names.mid}.`
        : `Jarak sekarang: ${names.fast} ${comma(-gap, 2)}% di atas ${names.mid}.`);
    }
    const state = verdict === 'ok' ? 'pass' : verdict === 'tunggu' ? 'hold' : verdict === 'jangan' ? 'fail' : 'info';
    const why = verdict ? patternWhy(verdict, read, limits, names) : '';
    return {
      id: 'pola',
      state,
      title: `Pola garis ${names.fast} / ${names.mid}: ${VERDICT_LABEL[verdict] || 'belum dinilai'}`,
      text: why,
      details: lines,
    };
  }

  /** Tanda masuk long (SOP 23 Okt), bila arah long dipilih saat koin dinilai. */
  function longStep(e) {
    const signs = ['reversal', 'flat', 'far_above'].map((key, i) => (e.long_ai[key] ? i + 1 : 0)).filter(Boolean);
    const found = signs.map((n) => `tanda ${n} (${SIGN_TEXT[n]})`).join(', ');
    const details = [];
    const d = e.long_data || {};
    if (known(d.ma7_above_ma25_pct)) details.push(`MA7 ${comma(Number(d.ma7_above_ma25_pct), 2)}% terhadap MA25, ${comma(Number(d.ma7_above_ma99_pct), 2)}% terhadap MA99.`);
    if (known(d.ma_spread_pct)) details.push(`Sebaran tiga garis ${comma(Number(d.ma_spread_pct), 2)}% dari harga.`);
    if (e.long_ai.summary) details.push(e.long_ai.summary);
    if (e.verdict === 'konflik') {
      return { id: 'long', state: 'fail', title: `Tanda long: ${found}`, text: 'Grafik juga layak short. Koin yang cocok untuk keduanya tidak dimasuki.', details };
    }
    return {
      id: 'long',
      state: signs.length ? 'pass' : 'hold',
      title: `Tanda long: ${found || 'tidak ada'}`,
      text: signs.length ? 'Satu tanda cukup untuk masuk long.' : 'Belum ada tanda masuk long.',
      details,
    };
  }

  /**
   * @param e kejadian koin dari engine atau satu baris riwayat (field sama).
   * @param opts { platform: 'binance'|'tebbit', plain: fn(teks alasan engine) -> kalimat sederhana,
   *               statusLabel: fn(status) -> label }
   */
  function explain(e, opts = {}) {
    const names0 = PERIODS[opts.platform] || PERIODS.binance;
    const names = { fast: `MA${names0.fast}`, mid: `MA${names0.mid}` };
    const plain = opts.plain || IDENTITY;
    const limits = { ...DEFAULT_LIMITS, ...(e.limits || {}) };
    const reason = String(e.reason || '');
    const ai = e.ai || (known(e.count_ai) ? { below_count: e.count_ai } : null);
    const data = e.data || (known(e.count_data) ? { below_count: e.count_data } : null);
    const { text: summary, votes } = splitSummary(e.summary);
    const leaderOnly = e.status === 'analyzed'; // pemimpin hanya membaca pola
    const opened = e.status === 'open' || ['target', 'likuidasi', 'manual', 'stop', 'timeout'].includes(e.status);
    const steps = [];

    // 1. Kenaikan 24 jam
    if (known(e.change_pct)) {
      const low = /naik .*dalam 24 jam/.test(reason);
      steps.push({ id: 'naik', state: low ? 'fail' : 'pass', title: 'Kenaikan 24 jam',
        text: low ? plain(reason) : `Naik ${signed(Number(e.change_pct), 2)}% dalam 24 jam.` });
    }

    // 2. Pola garis
    const pattern = patternStep(e, ai, data, limits, names);
    steps.push(pattern);
    if (e.long_ai) steps.push(longStep(e));
    const patternOk = ENTER.includes(e.verdict);

    // 3. Spread (angka dari bursa, dibaca saat koin dinilai)
    if (leaderOnly) {
      steps.push({ id: 'biaya', state: 'skip', title: 'Selisih harga beli dan jual', text: 'Dicek di laptop pengikut sebelum membuka posisi.' });
    } else {
      // Catatan lama (sebelum 20 Okt 2026): koin sempat dilewati oleh aturan funding yang sudah dihapus.
      if (e.status === 'skipped' && /funding/i.test(reason)) {
        steps.push({ id: 'funding', state: 'fail', title: 'Aturan funding (lama, sudah dihapus)', text: plain(reason) });
      }
      if (known(e.spread_pct)) {
        const s = Number(e.spread_pct);
        const bad = s > limits.max_spread_pct;
        const blocked = /spread/i.test(reason);
        steps.push({
          id: 'spread',
          state: bad ? (patternOk || blocked ? 'fail' : 'info') : 'pass',
          title: 'Selisih harga beli dan jual (spread)',
          text: bad
            ? `Spread ${comma(s, 3)}% lebih lebar dari batas ${comma(limits.max_spread_pct, 2)}%.${patternOk || blocked ? '' : ' Tidak menentukan: pola sudah menolak lebih dulu.'}`
            : `Spread ${comma(s, 3)}%, masih dalam batas ${comma(limits.max_spread_pct, 2)}%.`,
        });
      }
    }

    // 5. Posisi lain dan slot, 6. ukuran dan order: hanya dicapai bila langkah di atasnya lolos.
    const stopped = steps.some((s) => (s.state === 'fail' || s.state === 'hold') && !(patternOk && s.id === 'pola'));
    if (leaderOnly) {
      steps.push({ id: 'slot', state: 'skip', title: 'Posisi lain dan ukuran order', text: 'Ditentukan oleh tiap pengikut.' });
    } else if (stopped) {
      steps.push({ id: 'slot', state: 'skip', title: 'Posisi lain dan ukuran order', text: 'Belum sampai tahap ini.' });
    } else if (opened) {
      steps.push({ id: 'slot', state: 'pass', title: 'Posisi lain dan slot', text: 'Tidak ada yang menahan koin ini.' });
      const parts = [];
      if (known(e.margin_usdt)) parts.push(`margin ${comma(Number(e.margin_usdt), 2)} USDT`);
      if (known(e.leverage)) parts.push(`leverage ${e.leverage}x`);
      if (known(e.notional)) parts.push(`nilai posisi ${comma(Number(e.notional), 2)} USDT`);
      steps.push({ id: 'order', state: 'pass', title: 'Order',
        text: `${parts.length ? `${parts.join(', ')}. ` : ''}${known(e.entry_price) ? `Masuk di ${e.entry_price}` : ''}${known(e.target_price) ? `, jual otomatis di ${e.target_price}` : ''}${known(e.entry_price) ? (known(e.cutloss_price) ? `, cutloss di ${e.cutloss_price}.` : ' (tanpa stop-loss).') : ''}`.trim() });
    } else if (e.status === 'skipped' && reason) {
      const slot = /sudah ada posisi uji|sedang rugi|posisi terbuka \(maksimal/.test(reason);
      steps.push({ id: slot ? 'slot' : 'order', state: 'fail', title: slot ? 'Posisi lain dan slot' : 'Mengisi order di aplikasi', text: plain(reason) });
    }

    // Kesimpulan
    // Bila long masuk, pola short yang "tunggu" tidak menghentikan koin ini.
    const firstStop = steps.find((s) => (s.state === 'fail' || s.state === 'hold') && !(patternOk && s.id === 'pola'));
    const side = e.side === 'long' || e.verdict === 'long' ? 'long' : 'short';
    let tone = 'neutral';
    let headline;
    let because;
    if (e.status === 'contoh') {
      headline = 'Gambar contoh';
      because = plain(reason);
    } else if (leaderOnly) {
      tone = patternOk ? 'good' : 'neutral';
      headline = `Dibagikan ke pengikut: ${(VERDICT_LABEL[e.verdict] || 'dibaca').toLowerCase()}`;
      because = patternOk ? 'Pengikut mengecek biaya dan slot, lalu membuka posisi uji.' : 'Pengikut tidak membuka posisi untuk koin ini.';
    } else if (e.status === 'open') {
      tone = 'good';
      headline = `Bot masuk ${side} (${e.real ? 'uang sungguhan' : 'uji kertas'})`;
      because = 'Semua saringan lolos.';
    } else if (opened) {
      tone = 'neutral';
      const label = opts.statusLabel ? opts.statusLabel(e.status) : e.status;
      headline = `Bot sempat masuk ${side}; posisi ${String(label).toLowerCase()}`;
      because = 'Semua saringan lolos saat koin ini dinilai.';
    } else {
      tone = firstStop?.state === 'hold' ? 'warn' : 'bad';
      headline = firstStop?.state === 'hold' ? 'Tidak masuk: menunggu' : 'Tidak masuk';
      because = firstStop ? firstStop.text : (reason ? plain(reason) : 'Koin ini tidak dinilai lebih lanjut.');
    }

    return {
      tone,
      headline,
      because,
      steps,
      summary,
      votes,
      stoppedAt: firstStop ? firstStop.id : null,
    };
  }

  const api = { explain, splitSummary, PERIODS, DEFAULT_LIMITS };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.Reasons = api;
})(typeof window !== 'undefined' ? window : globalThis);

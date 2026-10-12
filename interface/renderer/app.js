'use strict';

// Tampilan aplikasi untuk pengguna non-teknis. Pesan engine diterjemahkan ke bahasa sehari-hari;
// detail teknis tetap ada di engine/logs/bot.log untuk admin. Semua teks ditulis dengan
// textContent (tanpa innerHTML) karena berasal dari engine dan jurnal.

const $ = (id) => document.getElementById(id);
const FORM_KEY = 'marketforge.form.v2';
const RANKS = [1, 2, 3, 4, 5];
const MAX_OPEN = 2; // SOP V2: maksimal 2 posisi bersamaan
const MAX_FEED = 120;
const SVG_NS = 'http://www.w3.org/2000/svg';
const NUM = new Intl.NumberFormat('id-ID', { maximumSignificantDigits: 6 });

const MODE_NOTE = {
  single: 'Membaca grafik dan mencatat posisi sendiri.',
  leader: 'Membaca grafik lalu membagikan hasil ke laptop pengikut.',
  follower: 'Memakai hasil laptop pemimpin, tanpa membaca grafik sendiri.',
};
const VERDICT = {
  ok: ['Layak short', 'ok'],
  tunggu: ['Tunggu', 'tunggu'],
  jangan: ['Jangan short', 'jangan'],
};
const STATUS = {
  open: ['Berjalan', 'open'],
  target: ['Target tercapai', 'target'],
  stop: ['Kena batas rugi', 'stop'],
  timeout: ['Waktu habis', 'timeout'],
};
const ICONS = {
  play: ['M8 5v14l11-7z'],
  stop: ['M7 7h10v10H7z'],
  check: ['M5 12.5l4.5 4.5L19 7.5'],
  cross: ['M7 7l10 10M17 7L7 17'],
  dash: ['M6 12h12'],
  laptop: ['M5 6h14v9H5z', 'M3 18h18'],
};

// --------------------------------------------------------------------------- pembantu

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (key === 'class') node.className = value;
    else node[key] = value;
  }
  for (const child of children) if (child !== null && child !== undefined && child !== false) node.append(child);
  return node;
}

function svg(tag, attrs = {}, ...children) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, String(value));
  for (const child of children) if (child) node.append(child);
  return node;
}

function icon(name) {
  return svg('svg', { viewBox: '0 0 24 24', 'aria-hidden': 'true' }, ...ICONS[name].map((d) => svg('path', { d })));
}

function setBar(id, fraction) {
  $(id).style.width = `${Math.max(0, Math.min(1, fraction || 0)) * 100}%`;
}

const price = (v) => (v === null || v === undefined ? '–' : NUM.format(v));
const percent = (v) => (v === null || v === undefined ? '–' : `${v > 0 ? '+' : ''}${v.toFixed(2).replace('.', ',')}%`);
const pct1 = (v) => `${(100 * v).toFixed(1).replace('.', ',')}%`;
const clock = (ts) => new Date(ts * 1000).toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit' });
const signClass = (v) => (v > 0 ? 'pos' : v < 0 ? 'neg' : '');

// --------------------------------------------------------------------------- bahasa sehari-hari

/** Alasan dari engine -> kalimat sederhana. Detail teknis tidak ditampilkan. */
function plain(text) {
  const t = String(text || '');
  const rules = [
    [/Data pasar Binance|fapi\.binance|certificate|urlopen/i, 'Data harga Binance tidak bisa diambil di jaringan ini'],
    [/JANGAN/, 'Garis kuning selalu di atas, harga masih naik terus'],
    [/TUNGGU/, 'Garis kuning baru sekali turun, harga masih bisa naik lagi'],
    [/sudah (\d+) posisi terbuka/, (m) => `Sudah ${m[1]} posisi berjalan, batas tercapai`],
    [/sedang rugi/, 'Posisi pertama sedang rugi, koin berikutnya ditunda'],
    [/sudah ada posisi uji/, 'Koin ini sudah punya posisi yang berjalan'],
    [/funding/i, 'Biaya funding sedang terlalu mahal'],
    [/spread/i, 'Selisih harga beli dan jual terlalu lebar'],
    [/naik .*dalam 24 jam|naik [\d.]+% </, 'Kenaikan 24 jam belum cukup'],
    [/bukan pair USDT/, 'Bukan pasangan USDT'],
    [/Grafik 15 menit|15 mnt/, 'Grafik belum termuat, koin dilewati'],
    [/Ukuran jendela/, 'Ukuran jendela Binance berubah, kembalikan seperti semula'],
    [/belum berjalan|Buka aplikasi Binance|AppNotRunning/i, 'Aplikasi Binance belum dibuka'],
    [/Kolom Jumlah/, 'Kolom Jumlah di Binance tidak terisi dengan benar'],
    [/leverage .*SOP/i, 'Leverage di Binance belum 2x (ubah sebelum memakai uang sungguhan)'],
    [/Isolated/i, 'Mode margin di Binance belum Isolated (ubah sebelum memakai uang sungguhan)'],
    [/stop-loss berturut-turut/, '3 kali kena batas rugi hari ini, bot berhenti sesuai SOP'],
    [/Hub belum punya|menunggu hasil/i, 'Hasil dari laptop pemimpin belum tersedia'],
    [/[Hh]ub .*(tidak bisa|menolak)|BOT_HUB/, 'Belum terhubung ke laptop pemimpin, hubungi admin'],
    [/VIKEY|Kunci AI|kunci API/i, 'Pengaturan AI di laptop ini belum lengkap, hubungi admin'],
    [/[Aa]nalisis AI|model/, 'AI belum bisa membaca grafik koin ini'],
    [/Top gainer|terurut|tidak terbaca|tidak ditemukan/i, 'Halaman Binance belum terbaca dengan benar'],
    [/notional|di bawah minimal|melebihi/i, 'Modal tidak cocok dengan aturan jumlah koin ini'],
  ];
  for (const [pattern, out] of rules) {
    const m = t.match(pattern);
    if (m) return typeof out === 'function' ? out(m) : out;
  }
  return 'Ada kendala, koin dilewati. Detail tersimpan untuk admin.';
}

/** Satu baris log engine -> aktivitas yang dipahami pengguna, atau null bila tidak perlu tampil. */
function activity(entry) {
  const e = entry.event;
  if (e?.type === 'cycle' && e.phase === 'start') return { text: 'Membuka daftar top gainers Futures' };
  if (e?.type === 'cycle' && e.phase === 'done') {
    const next = e.next_in_s > 0 ? `, diulang dalam ${Math.round(e.next_in_s / 60)} menit` : '';
    const what = e.records !== undefined ? `${e.records} hasil dibagikan` : `${e.opened} posisi uji baru`;
    return { text: `Putaran selesai: ${what}${next}` };
  }
  if (e?.type === 'coin') {
    if (e.status === 'open') return { text: `${e.symbol} masuk posisi uji`, css: 'good' };
    if (e.status === 'analyzed') return { text: `${e.symbol}: ${(VERDICT[e.verdict] || ['dibaca'])[0].toLowerCase()}` };
    return { text: `${e.symbol} dilewati: ${plain(e.reason).toLowerCase()}` };
  }
  if (e?.type === 'hub') return { text: 'Mulai membagikan hasil ke laptop pengikut', css: 'good' };

  const m = entry.message || '';
  const opened = m.match(/^Top gainer #(\d+): (\S+)/);
  if (opened) return { text: `Membuka top ${opened[1]}: ${opened[2]}` };
  if (/^(Tidak masuk putaran ini|Berhenti memantau): /.test(m)) return { text: plain(m), css: 'warn' };
  if (/^Tidak ada koin dengan pola OK/.test(m)) return { text: 'Belum ada koin yang layak, pantau lagi nanti' };
  if (entry.level === 'WARNING') return { text: plain(m), css: 'warn' };
  if (entry.level === 'ERROR' || entry.level === 'CRITICAL') {
    // Traceback Python terdiri dari banyak baris: cukup baris pesannya.
    if (/^(Traceback|\s|File ")/.test(m)) return null;
    return { text: plain(m), css: 'bad' };
  }
  return null;
}

// --------------------------------------------------------------------------- navigasi

const loaders = {};
function showPage(name) {
  for (const item of document.querySelectorAll('.menu-item')) item.classList.toggle('active', item.dataset.page === name);
  for (const page of document.querySelectorAll('.page')) page.hidden = page.id !== `page-${name}`;
  loaders[name]?.();
}
for (const item of document.querySelectorAll('.menu-item')) item.addEventListener('click', () => showPage(item.dataset.page));

// --------------------------------------------------------------------------- pengaturan putaran

const form = { mode: 'single', modal: '', ranks: [...RANKS], rank: 1, interval: 0 };

function loadForm() {
  try {
    Object.assign(form, JSON.parse(localStorage.getItem(FORM_KEY) || '{}'));
  } catch {
    // penyimpanan lokal tidak tersedia: pakai default
  }
  if (!Array.isArray(form.ranks) || form.ranks.length === 0) form.ranks = [...RANKS];
}

function saveForm() {
  try {
    localStorage.setItem(FORM_KEY, JSON.stringify(form));
  } catch {
    // tidak apa-apa: pilihan hanya tidak diingat
  }
}

function mark(group, isOn) {
  for (const btn of group.children) {
    const on = isOn(btn.dataset.value);
    btn.classList.toggle('on', on);
    btn.setAttribute(btn.getAttribute('role') === 'radio' ? 'aria-checked' : 'aria-pressed', String(on));
  }
}

function watchedCount() {
  return form.mode === 'follower' ? 1 : form.ranks.length;
}

function render() {
  const multi = form.mode !== 'follower';
  mark($('mode'), (v) => v === form.mode);
  mark($('interval'), (v) => Number(v) === Number(form.interval));
  const chosen = multi ? form.ranks : [form.rank];
  mark($('ranks'), (v) => chosen.includes(Number(v)));
  for (const node of document.querySelectorAll('[data-modes]')) {
    node.hidden = !node.dataset.modes.split(' ').includes(form.mode);
  }
  $('mode-note').textContent = MODE_NOTE[form.mode];
  $('ranks-title').textContent = multi ? 'Top gainers yang dipantau' : 'Top gainer untuk laptop ini';
  $('ranks-note').textContent = multi ? `Bisa pilih lebih dari satu · ${form.ranks.length} dari 5 dipilih` : 'Pilih satu';
  $('ranks-all').hidden = !multi || form.ranks.length === RANKS.length;
  if (state === 'stopped') $('seen-note').textContent = `dari ${watchedCount()} top gainers`;
  window.bot.setRole(form.mode).catch(() => {}); // peran laptop ini untuk daftar laptop di WiFi
  saveForm();
}

function setupForm() {
  for (const r of RANKS) {
    const btn = el('button', { type: 'button' }, el('small', { textContent: 'Top' }), el('strong', { textContent: String(r) }));
    btn.dataset.value = String(r);
    $('ranks').append(btn);
  }
  $('mode').addEventListener('click', (ev) => {
    const value = ev.target.closest('button')?.dataset.value;
    if (value) form.mode = value;
    render();
  });
  $('interval').addEventListener('click', (ev) => {
    const value = ev.target.closest('button')?.dataset.value;
    if (value !== undefined) form.interval = Number(value);
    render();
  });
  $('ranks').addEventListener('click', (ev) => {
    const r = Number(ev.target.closest('button')?.dataset.value);
    if (!r) return;
    if (form.mode === 'follower') form.rank = r;
    else if (!form.ranks.includes(r)) form.ranks = [...form.ranks, r].sort((a, b) => a - b);
    else if (form.ranks.length > 1) form.ranks = form.ranks.filter((x) => x !== r);
    render();
  });
  $('ranks-all').addEventListener('click', () => {
    form.ranks = [...RANKS];
    render();
  });
  $('modal').value = form.modal;
  $('modal').addEventListener('input', () => {
    form.modal = $('modal').value.trim();
    saveForm();
  });
}

// --------------------------------------------------------------------------- jalankan dan hentikan

let state = 'stopped';
const counts = { seen: 0, ok: 0, open: 0 };

function setState(next, title, sub) {
  state = next;
  const running = next === 'running';
  $('status').classList.toggle('running', running);
  $('setup').classList.toggle('locked', next !== 'stopped');

  const engine = $('engine-state');
  engine.classList.toggle('running', running);
  engine.querySelector('strong').textContent = running ? 'Bot sedang bekerja' : next === 'stopping' ? 'Menghentikan bot' : 'Bot berhenti';
  engine.querySelector('span').textContent = running ? 'Jangan pakai mouse' : 'Siap dijalankan';

  const toggle = $('toggle');
  toggle.disabled = next === 'stopping';
  toggle.classList.toggle('stop', next !== 'stopped');
  toggle.replaceChildren(icon(next === 'stopped' ? 'play' : 'stop'),
    el('span', { textContent: { stopped: 'Mulai memantau', running: 'Hentikan', stopping: 'Menghentikan…' }[next] }));
  if (title) $('status-title').textContent = title;
  if (sub) $('status-sub').textContent = sub;
}

function setCounts() {
  const watched = watchedCount();
  $('count-seen').textContent = String(counts.seen);
  $('count-ok').textContent = String(counts.ok);
  $('count-open').textContent = `${counts.open}`;
  $('seen-note').textContent = `dari ${watched} top gainers`;
  setBar('seen-bar', counts.seen / watched);
  setBar('ok-bar', counts.seen ? counts.ok / counts.seen : 0);
  setBar('open-bar', counts.open / MAX_OPEN);
}

function emptyCoins(text) {
  $('coins').replaceChildren(el('tr', { class: 'empty-row' }, el('td', { colSpan: 5, textContent: text })));
}

function emptyFeed(text) {
  $('feed').replaceChildren(el('li', { class: 'idle', textContent: text }));
}

async function toggleRun() {
  $('run-error').textContent = '';
  if (state !== 'stopped') {
    setState('stopping', 'Menghentikan', 'Bot menyelesaikan langkah yang sedang berjalan.');
    await window.bot.stop().catch(() => {});
    return;
  }
  const params = { modal: form.modal, ranks: form.ranks, rank: form.rank, interval: form.interval };
  try {
    await window.bot.start(form.mode, params);
  } catch (err) {
    $('run-error').textContent = err.message;
    return;
  }
  Object.assign(counts, { seen: 0, ok: 0, open: 0 });
  setCounts();
  $('share').hidden = true;
  $('cycle-info').textContent = 'Menyiapkan Binance…';
  emptyCoins('Menyiapkan Binance…');
  emptyFeed('Menunggu aktivitas pertama…');
  setState('running', 'Sedang memantau', 'Menyiapkan aplikasi Binance…');
}

function addFeed(item, ts) {
  const feed = $('feed');
  feed.querySelector('.idle')?.remove();
  feed.prepend(el('li', { class: item.css || '' }, el('i'),
    el('div', {}, el('span', { textContent: item.text }), el('time', { textContent: clock(ts) }))));
  while (feed.childElementCount > MAX_FEED) feed.lastElementChild.remove();
  if (state === 'running') $('status-sub').textContent = item.text;
}

function dips(count) {
  if (count === null || count === undefined) return el('span', { class: 'dips', textContent: '–' });
  const blocks = [0, 1, 2].map((i) => el('i', { class: i < count ? 'on' : '' }));
  return el('span', { class: 'dips' }, ...blocks, el('span', { textContent: `${count}×` }));
}

function addCoin(e) {
  counts.seen += 1;
  if (e.verdict === 'ok') counts.ok += 1;
  if (e.status === 'open') counts.open += 1;
  setCounts();

  const [label, css] = e.status === 'open' ? ['Posisi uji', 'opened'] : VERDICT[e.verdict] || ['Dilewati', ''];
  let note;
  if (e.status === 'open') note = `Masuk ${price(e.entry_price)} · target ${price(e.target_price)} · batas rugi ${price(e.stop_price)}`;
  else if (e.status === 'analyzed') note = 'Dibagikan ke laptop pengikut';
  else note = plain(e.reason);
  $('coins').querySelector('.empty-row')?.remove();
  $('coins').append(el('tr', {},
    el('td', { class: 'rank' }, el('span', { class: 'rank-badge', textContent: String(e.rank) })),
    el('td', { class: 'sym', textContent: e.symbol }),
    el('td', {}, dips(e.count_ai ?? e.count_data)),
    el('td', {}, el('span', { class: `tag ${css}`, textContent: label })),
    el('td', { class: 'why' }, note, e.summary ? el('small', { textContent: e.summary }) : null)));
}

window.bot.onLog((entry) => {
  const e = entry.event;
  if (e?.type === 'cycle' && e.phase === 'start') {
    emptyCoins('Membaca top gainers…');
    $('cycle-info').textContent = `Dimulai ${clock(entry.ts || Date.now() / 1000)}`;
  }
  if (e?.type === 'coin') addCoin(e);
  if (e?.type === 'hub') $('share').hidden = false;
  if (e?.type === 'cycle' && e.phase === 'done') {
    $('cycle-info').textContent = `Selesai ${clock(entry.ts || Date.now() / 1000)}`;
    if ($('coins').querySelector('.empty-row')) emptyCoins('Tidak ada koin yang bisa dinilai di putaran ini.');
  }
  const item = activity(entry);
  if (item) addFeed(item, entry.ts || Date.now() / 1000);
});

window.bot.onExit(({ code, signal }) => {
  const stopped = code === 130 || Boolean(signal);
  if (code === 0) setState('stopped', 'Selesai', 'Putaran selesai. Rekap ada di Hasil uji.');
  else if (stopped) setState('stopped', 'Dihentikan', 'Bot berhenti atas permintaan.');
  else setState('stopped', 'Berhenti karena kendala', 'Buka Cek laptop lalu coba lagi.');
  addFeed({ text: code === 0 ? 'Bot selesai' : stopped ? 'Bot dihentikan' : 'Bot berhenti karena kendala', css: code === 0 || stopped ? '' : 'bad' }, Date.now() / 1000);
});

$('toggle').addEventListener('click', toggleRun);

// --------------------------------------------------------------------------- hasil uji

function kpi(label, value, note, { css = '', bar = null, barClass = '', mark: markAt = null } = {}) {
  let meter = null;
  if (bar !== null) {
    const fill = el('i');
    fill.style.width = `${Math.max(0, Math.min(1, bar)) * 100}%`;
    meter = el('div', { class: `meter ${barClass}` }, fill);
    if (markAt !== null) {
      const line = el('span', { class: 'mark' });
      line.style.left = `${markAt * 100}%`;
      meter.append(line);
    }
  }
  return el('div', { class: 'card kpi' },
    el('span', { class: 'kpi-label', textContent: label }),
    el('strong', { class: css, textContent: value }),
    el('small', { textContent: note }),
    meter);
}

/** Batang hasil per trade (% modal), hijau untung dan merah rugi. */
function pnlChart(trades) {
  const closed = trades.filter((t) => t.pnl_capital_pct !== null && t.pnl_capital_pct !== undefined && t.status !== 'open');
  if (closed.length === 0) {
    return el('div', { class: 'chart-empty', textContent: 'Grafik muncul setelah ada trade uji yang selesai.' });
  }
  const W = 640;
  const H = 220;
  const pad = { l: 44, r: 8, t: 12, b: 22 };
  const max = Math.max(1, ...closed.map((t) => Math.abs(t.pnl_capital_pct)));
  const zero = pad.t + (H - pad.t - pad.b) / 2;
  const scale = (H - pad.t - pad.b) / 2 / max;
  const slot = (W - pad.l - pad.r) / closed.length;
  const parts = [
    svg('line', { class: 'grid', x1: pad.l, x2: W - pad.r, y1: pad.t, y2: pad.t }),
    svg('line', { class: 'grid', x1: pad.l, x2: W - pad.r, y1: H - pad.b, y2: H - pad.b }),
    svg('line', { class: 'axis', x1: pad.l, x2: W - pad.r, y1: zero, y2: zero }),
  ];
  for (const [y, text] of [[pad.t, `+${max.toFixed(1)}%`], [zero, '0%'], [H - pad.b, `-${max.toFixed(1)}%`]]) {
    const label = svg('text', { x: pad.l - 6, y: y + 3.5, 'text-anchor': 'end' });
    label.textContent = text.replace('.', ',');
    parts.push(label);
  }
  closed.forEach((t, i) => {
    const v = t.pnl_capital_pct;
    const h = Math.max(1.5, Math.abs(v) * scale);
    const w = Math.min(28, slot * 0.62);
    const rect = svg('rect', {
      class: v >= 0 ? 'bar-pos' : 'bar-neg',
      x: pad.l + slot * i + (slot - w) / 2,
      y: v >= 0 ? zero - h : zero,
      width: w,
      height: h,
      rx: 2,
    });
    const tip = svg('title');
    tip.textContent = `${t.symbol}: ${percent(v)} modal`;
    rect.append(tip);
    parts.push(rect);
  });
  return svg('svg', { viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: 'none', role: 'img', 'aria-label': 'Hasil per trade' }, ...parts);
}

/** Donat akhir posisi: target, batas rugi, waktu habis, masih berjalan. */
function donut(s) {
  const parts = [
    ['Target tercapai', s.targets, 'var(--green)'],
    ['Kena batas rugi', s.stops, 'var(--red)'],
    ['Waktu habis', s.timeouts, 'var(--amber)'],
    ['Masih berjalan', s.open, 'var(--violet-2)'],
  ];
  const total = parts.reduce((sum, [, n]) => sum + n, 0);
  const r = 58;
  const c = 2 * Math.PI * r;
  const rings = [svg('circle', { cx: 75, cy: 75, r, stroke: 'var(--card-2)', 'stroke-width': 16, fill: 'none' })];
  let offset = 0;
  for (const [, n, color] of parts) {
    if (!n) continue;
    const len = (n / total) * c;
    rings.push(svg('circle', {
      cx: 75, cy: 75, r, fill: 'none', stroke: color, 'stroke-width': 16,
      'stroke-dasharray': `${len} ${c - len}`, 'stroke-dashoffset': -offset, transform: 'rotate(-90 75 75)',
    }));
    offset += len;
  }
  const big = svg('text', { x: 75, y: 78, 'text-anchor': 'middle', class: 'center-big' });
  big.textContent = String(total);
  const small = svg('text', { x: 75, y: 96, 'text-anchor': 'middle', class: 'center-small' });
  small.textContent = 'posisi uji';
  const chart = svg('svg', { viewBox: '0 0 150 150', role: 'img', 'aria-label': 'Akhir posisi' }, ...rings, big, small);
  const legend = el('ul', { class: 'legend' }, ...parts.map(([label, n, color]) => {
    const swatch = el('i');
    swatch.style.background = color;
    return el('li', {}, swatch, el('span', { textContent: label }), el('b', { textContent: String(n) }));
  }));
  return [chart, legend];
}

async function loadJournal() {
  $('journal-refresh').disabled = true;
  const notice = $('journal-notice');
  try {
    const report = await window.bot.summary();
    const s = report.stats;
    notice.hidden = !report.warning;
    notice.className = 'notice';
    notice.textContent = 'Data harga Binance belum bisa diambil di jaringan ini; angka di bawah dari catatan terakhir.';

    const enough = s.closed >= s.required_trades;
    const passed = s.verdict.startsWith('LULUS');
    const phase = !enough ? 'Belum cukup data' : passed ? 'Lulus fase uji' : 'Belum lulus, tinjau aturan';
    $('journal-kpis').replaceChildren(
      kpi('Trade uji selesai', `${s.closed}/${s.required_trades}`, phase,
        { bar: s.closed / s.required_trades, barClass: 'violet', css: enough ? (passed ? 'pos' : 'neg') : '' }),
      kpi('Tingkat menang', s.win_rate === null ? '–' : pct1(s.win_rate), `garis = titik impas ${pct1(s.breakeven)}`,
        { bar: s.win_rate ?? 0, barClass: s.win_rate !== null && s.win_rate >= s.breakeven ? 'green' : 'red', mark: s.breakeven,
          css: s.win_rate === null ? '' : s.win_rate >= s.breakeven ? 'pos' : 'neg' }),
      kpi('Hasil bersih', percent(s.net_capital_pct), 'dari modal', { css: signClass(s.net_capital_pct) }),
      kpi('Batas rugi beruntun', String(s.stop_streak), 'bot berhenti bila 3 dalam sehari',
        { bar: s.stop_streak / 3, barClass: 'red', css: s.stop_streak >= 2 ? 'neg' : '' }),
    );

    $('pnl-chart').replaceChildren(pnlChart(report.trades));
    $('donut').replaceChildren(...donut(s));

    const rows = [...report.trades].reverse().map((t) => {
      const [label, css] = STATUS[t.status] || [t.status, ''];
      return el('tr', {},
        el('td', { textContent: new Date(t.created_at * 1000).toLocaleString('id-ID', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) }),
        el('td', { class: 'sym', textContent: t.symbol }),
        el('td', {}, el('span', { class: `tag ${css}`, textContent: label })),
        el('td', { class: 'num', textContent: price(t.entry_price) }),
        el('td', { class: 'num', textContent: price(t.exit_price) }),
        el('td', { class: `num ${signClass(t.pnl_capital_pct)}`, textContent: percent(t.pnl_capital_pct) }));
    });
    $('trades').replaceChildren(...(rows.length ? rows
      : [el('tr', { class: 'empty-row' }, el('td', { colSpan: 6, textContent: 'Belum ada posisi uji. Mulai memantau untuk mengisi catatan.' }))]));
  } catch (err) {
    notice.hidden = false;
    notice.className = 'notice bad';
    notice.textContent = err.message;
  } finally {
    $('journal-refresh').disabled = false;
  }
}
loaders.journal = loadJournal;
$('journal-refresh').addEventListener('click', loadJournal);

// --------------------------------------------------------------------------- cek laptop

const CHECKS = {
  accessibility: ['Izin mengendalikan laptop', 'Buka Pengaturan Sistem › Privasi & Keamanan › Aksesibilitas.'],
  screen: ['Izin melihat layar', 'Buka Pengaturan Sistem › Privasi & Keamanan › Perekaman Layar.'],
  binance: ['Aplikasi Binance', 'Buka Binance dan pastikan sudah login.'],
  window: ['Ukuran jendela Binance', 'Layar terlalu kecil. Pilih "Lebih Banyak Ruang" di Pengaturan Sistem › Layar, atau sembunyikan Dock otomatis.'],
  api: ['Data harga Binance', 'Jaringan ini memblokir Binance. Coba jaringan lain.'],
  ai_key: ['Pembaca grafik (AI)', 'Belum diatur di laptop ini. Hubungi admin.'],
  hub_token: ['Kerja sama antar laptop', 'Hanya perlu untuk Pemimpin dan Pengikut.'],
};

// Petunjuk yang berbeda di Windows (tidak ada izin Accessibility/Perekaman Layar per aplikasi;
// yang perlu dicek adalah Binance memblokir screenshot atau tidak).
if (window.bot.platform === 'win32') {
  CHECKS.accessibility = ['Kendali mouse dan keyboard', 'Jalankan aplikasi ini tanpa mode Administrator, kecuali Binance juga dijalankan sebagai Administrator.'];
  CHECKS.screen = ['Binance boleh di-screenshot', 'Matikan perlindungan layar di Binance (jangan klik "Aktifkan perlindungan layar" pada banner keamanan), lalu coba lagi.'];
  CHECKS.window = ['Ukuran jendela Binance', 'Layar terlalu kecil. Butuh layar 1920x1080 (jendela Binance di-maximize), atau sembunyikan taskbar otomatis.'];
}

async function loadChecks() {
  $('ready-text').textContent = 'Memeriksa laptop…';
  $('ready-refresh').disabled = true;
  try {
    const result = await window.bot.checks();
    const binanceOpen = result.checks.find((c) => c.id === 'binance')?.ok;
    const ready = result.checks.filter((c) => c.ok).length;
    $('ready-count').textContent = `${ready}/${result.checks.length}`;
    $('ready-text').textContent = result.ok ? 'Laptop ini siap dipakai.' : 'Belum siap. Selesaikan yang bertanda merah.';
    $('ready-count').className = result.ok ? 'pos' : '';
    setBar('ready-bar', ready / result.checks.length);
    $('ready-bar').parentElement.className = `meter wide ${result.ok ? 'green' : 'violet'}`;
    $('checks').replaceChildren(...result.checks.map((c) => {
      const [title, fix] = CHECKS[c.id] || [c.id, 'Belum siap.'];
      const needed = !c.ok && c.wajib;
      const kind = c.ok ? 'ok' : needed ? 'no' : '';
      const [label, tag] = c.ok ? ['Siap', 'ok'] : needed ? ['Perlu tindakan', 'jangan'] : ['Opsional', ''];
      let detail = c.ok ? 'Sudah beres.' : fix;
      if (c.id === 'window' && c.ok) detail = 'Diatur otomatis saat bot mulai.';
      if (c.id === 'window' && !c.ok && /tidak terlihat/.test(c.pesan)) {
        detail = binanceOpen ? 'Jendela Binance sedang diperkecil atau tersembunyi. Tampilkan jendelanya.' : fix;
      }
      const side = c.id === 'hub_token'
        ? el('div', { class: 'check-actions' },
          el('span', { class: `tag ${tag}`, textContent: label }),
          el('button', { class: 'secondary small', textContent: 'Lihat laptop', onclick: loadPeers }))
        : el('span', { class: `tag ${tag}`, textContent: label });
      return el('div', { class: `card check ${kind}` },
        el('span', { class: 'icon' }, icon(c.ok ? 'check' : needed ? 'cross' : 'dash')),
        el('div', {}, el('strong', { textContent: title }), el('span', { textContent: detail })),
        side);
    }));
  } catch (err) {
    $('ready-text').textContent = err.message;
  } finally {
    $('ready-refresh').disabled = false;
  }
}
loaders.ready = loadChecks;
$('ready-refresh').addEventListener('click', loadChecks);

// --------------------------------------------------------------------------- laptop di WiFi

const ROLE_LABEL = { leader: ['Pemimpin', 'open'], follower: ['Pengikut', 'follower'], single: ['Sendiri', ''] };

async function loadPeers() {
  const card = $('peers-card');
  card.hidden = false;
  $('peers-refresh').disabled = true;
  $('peers-sub').textContent = 'Mencari laptop yang membuka MarketForge…';
  $('peers').replaceChildren(el('li', { class: 'peer-empty', textContent: 'Mencari…' }));
  card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  try {
    const peers = await window.bot.peers();
    const others = peers.filter((p) => !p.self).length;
    $('peers-sub').textContent = others
      ? `${others} laptop lain ditemukan. HP dan perangkat lain tidak ditampilkan.`
      : 'Belum ada laptop lain. Pastikan laptop lain membuka MarketForge di WiFi yang sama.';
    $('peers').replaceChildren(...peers.map((p) => {
      const [role, roleCss] = ROLE_LABEL[p.role] || ROLE_LABEL.single;
      const meta = [p.os, p.address].filter(Boolean).join(' · ');
      return el('li', { class: `peer ${p.self ? 'self' : ''}` },
        el('span', { class: 'icon' }, icon('laptop')),
        el('div', {},
          el('strong', { textContent: p.self ? `${p.name} (laptop ini)` : p.name }),
          el('span', { textContent: meta })),
        el('span', { class: `tag ${roleCss}`, textContent: role }),
        el('span', { class: `tag ${p.running ? 'ok' : ''}`, textContent: p.running ? 'Bot berjalan' : 'Bot berhenti' }));
    }));
  } catch (err) {
    $('peers-sub').textContent = err.message;
    $('peers').replaceChildren();
  } finally {
    $('peers-refresh').disabled = false;
  }
}
$('peers-refresh').addEventListener('click', loadPeers);

// --------------------------------------------------------------------------- mulai

loadForm();
setupForm();
render();
setState('stopped');
setCounts();
emptyCoins('Belum ada koin yang dinilai. Tekan Mulai memantau.');
emptyFeed('Aktivitas bot akan muncul di sini.');
window.bot.status().then(({ running }) => {
  if (running) setState('running', 'Sedang memantau', 'Bot sedang bekerja.');
});

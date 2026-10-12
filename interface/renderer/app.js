'use strict';

// Tampilan aplikasi untuk pengguna non-teknis. Pesan engine diterjemahkan ke bahasa sehari-hari;
// detail teknis tetap ada di engine/logs/bot.log untuk admin. Semua teks ditulis dengan
// textContent (tanpa innerHTML) karena berasal dari engine dan jurnal.

const $ = (id) => document.getElementById(id);
const FORM_KEY = 'marketforge.form.v2';
const RANKS = [1, 2, 3, 4, 5];
const MAX_FEED = 120;
const NUM = new Intl.NumberFormat('id-ID', { maximumSignificantDigits: 6 });

const MODE_NOTE = {
  single: 'Laptop ini membaca grafik dan mencatat posisi sendiri.',
  leader: 'Laptop ini membaca grafik lalu membagikan hasilnya ke laptop pengikut.',
  follower: 'Laptop ini memakai hasil dari laptop pemimpin, tanpa membaca grafik sendiri.',
};
const VERDICT = {
  ok: ['Layak short', 'ok'],
  tunggu: ['Tunggu', 'tunggu'],
  jangan: ['Jangan short', 'jangan'],
};
const STATUS = {
  open: ['Berjalan', 'opened'],
  target: ['Target tercapai', 'pos'],
  stop: ['Kena batas rugi', 'neg'],
  timeout: ['Ditutup, waktu habis', 'hold'],
};

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (key === 'class') node.className = value;
    else node[key] = value;
  }
  for (const child of children) if (child !== null && child !== undefined && child !== false) node.append(child);
  return node;
}

const price = (v) => (v === null || v === undefined ? '–' : NUM.format(v));
const percent = (v) => (v === null || v === undefined ? '–' : `${v > 0 ? '+' : ''}${v.toFixed(2).replace('.', ',')}%`);
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
  for (const tab of document.querySelectorAll('.tab')) tab.classList.toggle('active', tab.dataset.page === name);
  for (const page of document.querySelectorAll('.page')) page.hidden = page.id !== `page-${name}`;
  loaders[name]?.();
}
for (const tab of document.querySelectorAll('.tab')) tab.addEventListener('click', () => showPage(tab.dataset.page));

// --------------------------------------------------------------------------- formulir

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
  $('ranks-note').textContent = multi
    ? `Bisa lebih dari satu. ${form.ranks.length} dari 5 dipilih.`
    : 'Pilih satu.';
  $('ranks-all').hidden = !multi || form.ranks.length === RANKS.length;
  saveForm();
}

function setupForm() {
  for (const r of RANKS) {
    const btn = el('button', { type: 'button', textContent: String(r) });
    btn.dataset.value = String(r);
    btn.setAttribute('aria-label', `Top ${r}`);
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
  $('status').classList.toggle('running', next === 'running');
  $('setup').classList.toggle('locked', next !== 'stopped');
  const side = $('engine-state');
  side.classList.toggle('running', next === 'running');
  side.textContent = { stopped: 'Berhenti', running: 'Berjalan', stopping: 'Menghentikan' }[next];
  const toggle = $('toggle');
  toggle.disabled = next === 'stopping';
  toggle.classList.toggle('stop', next !== 'stopped');
  toggle.textContent = { stopped: 'Mulai memantau', running: 'Hentikan', stopping: 'Menghentikan…' }[next];
  if (title) $('status-title').textContent = title;
  if (sub) $('status-sub').textContent = sub;
}

function setCounts() {
  $('count-seen').textContent = String(counts.seen);
  $('count-ok').textContent = String(counts.ok);
  $('count-open').textContent = String(counts.open);
}

function emptyCoins(text) {
  $('coins').replaceChildren(el('tr', {}, el('td', { class: 'empty', colSpan: 5, textContent: text })));
}

function emptyFeed(text) {
  $('feed').replaceChildren(el('li', {}, el('span', { class: 'idle', textContent: text })));
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
  emptyCoins('Menyiapkan Binance…');
  emptyFeed('Menunggu aktivitas pertama…');
  setState('running', 'Sedang memantau', 'Menyiapkan aplikasi Binance…');
}

function addFeed(item, ts) {
  const feed = $('feed');
  feed.querySelector('.idle')?.parentElement.remove();
  feed.prepend(el('li', {}, el('time', { textContent: clock(ts) }), el('span', { class: item.css || '', textContent: item.text })));
  while (feed.childElementCount > MAX_FEED) feed.lastElementChild.remove();
  if (state === 'running') $('status-sub').textContent = item.text;
}

function addCoin(e) {
  counts.seen += 1;
  if (e.verdict === 'ok') counts.ok += 1;
  if (e.status === 'open') counts.open += 1;
  setCounts();

  const [label, css] = e.status === 'open' ? ['Masuk posisi uji', 'opened'] : VERDICT[e.verdict] || ['Dilewati', ''];
  const count = e.count_ai ?? e.count_data;
  let note;
  if (e.status === 'open') note = `Masuk ${price(e.entry_price)} · target ${price(e.target_price)} · batas rugi ${price(e.stop_price)}`;
  else if (e.status === 'analyzed') note = 'Dibagikan ke laptop pengikut';
  else note = plain(e.reason);
  $('coins').querySelector('.empty')?.parentElement.remove();
  $('coins').append(el('tr', {},
    el('td', { class: 'rank', textContent: String(e.rank) }),
    el('td', { class: 'sym', textContent: e.symbol }),
    el('td', { textContent: count === null || count === undefined ? '–' : `${count}× di bawah` }),
    el('td', { class: css, textContent: label }),
    el('td', {}, note, e.summary ? el('small', { textContent: e.summary }) : null)));
}

window.bot.onLog((entry) => {
  const e = entry.event;
  if (e?.type === 'cycle' && e.phase === 'start') emptyCoins('Membaca top gainers…');
  if (e?.type === 'coin') addCoin(e);
  if (e?.type === 'hub') $('share').hidden = false;
  if (e?.type === 'cycle' && e.phase === 'done' && $('coins').querySelector('.empty')) {
    emptyCoins('Tidak ada koin yang bisa dinilai di putaran ini.');
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

function figure(label, value, note, css = '') {
  return el('div', {}, el('dt', { textContent: label }), el('dd', { class: css }, value, note ? el('small', { textContent: note }) : null));
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
    $('progress-text').textContent = `${s.closed} dari ${s.required_trades} trade uji selesai`;
    $('progress-bar').style.width = `${Math.min(100, (100 * s.closed) / s.required_trades)}%`;
    const verdict = $('verdict');
    verdict.className = enough ? (passed ? 'pos' : 'neg') : 'note';
    verdict.textContent = !enough ? 'Belum cukup data' : passed ? 'Lulus fase uji' : 'Belum lulus, aturan perlu ditinjau';

    const pct = (v) => `${(100 * v).toFixed(1).replace('.', ',')}%`;
    $('kpis').replaceChildren(
      figure('Tingkat menang', s.win_rate === null ? '–' : pct(s.win_rate), `titik impas ${pct(s.breakeven)}`,
        s.win_rate === null ? '' : s.win_rate >= s.breakeven ? 'pos' : 'neg'),
      figure('Hasil bersih', percent(s.net_capital_pct), 'dari modal', signClass(s.net_capital_pct)),
      figure('Posisi berjalan', String(s.open), s.needs_review ? `${s.needs_review} perlu ditinjau` : 'maksimal 2'),
      figure('Batas rugi beruntun', String(s.stop_streak), 'berhenti bila 3 sehari', s.stop_streak >= 2 ? 'neg' : ''),
    );

    const rows = [...report.trades].reverse().map((t) => {
      const [label, css] = STATUS[t.status] || [t.status, ''];
      return el('tr', {},
        el('td', { textContent: new Date(t.created_at * 1000).toLocaleString('id-ID', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) }),
        el('td', { class: 'sym', textContent: t.symbol }),
        el('td', { class: css, textContent: label }),
        el('td', { class: 'num', textContent: price(t.entry_price) }),
        el('td', { class: 'num', textContent: price(t.exit_price) }),
        el('td', { class: `num ${signClass(t.pnl_capital_pct)}`, textContent: percent(t.pnl_capital_pct) }));
    });
    $('trades').replaceChildren(...(rows.length ? rows
      : [el('tr', {}, el('td', { class: 'empty', colSpan: 6, textContent: 'Belum ada posisi uji.' }))]));
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
  accessibility: ['Izin mengendalikan laptop', 'Belum diizinkan. Buka Pengaturan Sistem › Privasi & Keamanan › Aksesibilitas.'],
  screen: ['Izin melihat layar', 'Belum diizinkan. Buka Pengaturan Sistem › Privasi & Keamanan › Perekaman Layar.'],
  binance: ['Aplikasi Binance', 'Belum dibuka. Buka Binance dan pastikan sudah login.'],
  window: ['Ukuran jendela Binance', 'Kembalikan ukuran jendela Binance seperti semula.'],
  api: ['Data harga Binance', 'Jaringan ini memblokir Binance. Coba jaringan lain.'],
  ai_key: ['Pembaca grafik (AI)', 'Belum diatur di laptop ini. Hubungi admin.'],
  hub_token: ['Kerja sama antar laptop', 'Belum diatur. Hanya perlu untuk Pemimpin dan Pengikut.'],
};

async function loadChecks() {
  const summary = $('ready-summary');
  summary.className = 'lede';
  summary.textContent = 'Memeriksa laptop…';
  $('ready-refresh').disabled = true;
  try {
    const result = await window.bot.checks();
    const binanceOpen = result.checks.find((c) => c.id === 'binance')?.ok;
    $('checks').replaceChildren(...result.checks.map((c) => {
      const [title, fix] = CHECKS[c.id] || [c.id, 'Belum siap.'];
      const waiting = c.id === 'window' && !binanceOpen;
      const [status, css] = c.ok ? ['Siap', 'pos'] : c.wajib && !waiting ? ['Perlu tindakan', 'neg'] : ['–', 'note'];
      const detail = c.ok ? '' : waiting ? 'Dicek setelah Binance dibuka.' : fix;
      return el('tr', {},
        el('td', { textContent: title }),
        el('td', { class: 'note', textContent: detail }),
        el('td', { class: css, textContent: status }));
    }));
    summary.className = `lede ${result.ok ? 'pos' : 'neg'}`;
    summary.textContent = result.ok ? 'Laptop ini siap dipakai.' : 'Belum siap. Selesaikan yang bertanda "Perlu tindakan".';
  } catch (err) {
    summary.className = 'lede neg';
    summary.textContent = err.message;
  } finally {
    $('ready-refresh').disabled = false;
  }
}
loaders.ready = loadChecks;
$('ready-refresh').addEventListener('click', loadChecks);

// --------------------------------------------------------------------------- mulai

loadForm();
setupForm();
render();
emptyCoins('Belum ada koin yang dinilai.');
emptyFeed('Aktivitas bot akan muncul di sini.');
window.bot.status().then(({ running }) => {
  if (running) setState('running', 'Sedang memantau', 'Bot sedang bekerja.');
  else setState('stopped');
});

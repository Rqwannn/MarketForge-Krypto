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
  manual: ['Ditutup (Sell)', 'manual'],
};
// Platform (bursa). Hanya yang `ready: true` yang bisa dipilih dan dijalankan engine.
const PLATFORMS = [
  { id: 'binance', name: 'Binance', logo: 'img/binance.png', note: 'Futures · pantau top gainers', ready: true },
  { id: 'tebbit', name: 'Tebbit', logo: 'img/tebbit.png', note: 'Website di Chrome · tebbit.io', ready: true },
];
/** Top tugas pengikut: angka 1..5, atau '*' = semua Top yang dimainkan pemimpin. */
const rankLabel = (rank) => (rank === '*' ? 'Semua top' : `Top ${String(rank).split('').join(', ')}`);
const ROLE_NAME = { single: 'Sendiri', follower: 'Pengikut', leader: 'Pemimpin' };
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
  const site = platform?.name || 'Binance';
  const rules = [
    [/Data pasar Binance|fapi\.binance|certificate|urlopen/i, 'Data harga Binance tidak bisa diambil di jaringan ini'],
    [/JANGAN/, 'Garis kuning selalu di atas, harga masih naik terus'],
    [/6 jam terakhir naik terus/, 'Garis kuning sempat turun, tapi 6 jam terakhir harga naik terus'],
    [/TUNGGU/, 'Garis kuning baru sekali turun, harga masih bisa naik lagi'],
    [/sudah (\d+) posisi terbuka/, (m) => `Sudah ${m[1]} posisi berjalan, batas tercapai`],
    [/sedang rugi/, 'Posisi pertama sedang rugi, koin berikutnya ditunda'],
    [/sudah ada posisi uji/, 'Koin ini sudah punya posisi yang berjalan'],
    [/funding/i, 'Biaya funding sedang terlalu mahal'],
    [/spread/i, 'Selisih harga beli dan jual terlalu lebar'],
    [/naik .*dalam 24 jam|naik [\d.]+% </, 'Kenaikan 24 jam belum cukup'],
    [/bukan pair USDT/, 'Bukan pasangan USDT'],
    [/Grafik 15 menit|15 mnt/, 'Grafik belum termuat, koin dilewati'],
    [/Ukuran jendela/, `Ukuran jendela ${site} berubah, kembalikan seperti semula`],
    [/belum berjalan|Buka aplikasi Binance|AppNotRunning/i, 'Aplikasi Binance belum dibuka'],
    [/Kolom (Jumlah|Quantity)/, `Kolom jumlah di ${site} tidak terisi dengan benar`],
    [/Indikator MA/, `Atur indikator grafik ${site} ke MA 7, MA 25, MA 99`],
    [/tidak tampil di layar/, `Jendela ${site} tertutup jendela lain, bot berhenti demi keamanan`],
    [/leverage .*SOP/i, `Leverage di ${site} belum 2x (ubah sebelum memakai uang sungguhan)`],
    [/Isolated/i, `Mode margin di ${site} belum Isolated (ubah sebelum memakai uang sungguhan)`],
    [/stop-loss berturut-turut/, '3 kali kena batas rugi hari ini, bot berhenti untuk hari ini'],
    [/BOT_HUB_TOKEN wajib/, 'Token hub belum diatur di laptop ini, hubungi admin'],
    [/Leader belum menilai (Top \d+)/, (m) => `Pemimpin belum menilai ${m[1]}, tidak ada tindakan`],
    [/sudah tidak di top/, 'Koin pemimpin sudah keluar dari top gainers, tidak ada tindakan'],
    [/peringkat bergeser/, 'Peringkat bergeser saat membuka koin, tidak ada tindakan'],
    [/Hub belum punya|menunggu hasil/i, 'Hasil dari laptop pemimpin belum tersedia'],
    [/[Hh]ub .*(tidak bisa|menolak)|BOT_HUB/, 'Belum terhubung ke laptop pemimpin, hubungi admin'],
    [/VIKEY|Kunci AI|kunci API/i, 'Pengaturan AI di laptop ini belum lengkap, hubungi admin'],
    [/[Aa]nalisis AI|model/, 'AI belum bisa membaca grafik koin ini'],
    [/Top gainer|terurut|tidak terbaca|tidak ditemukan/i, `Halaman ${site} belum terbaca dengan benar`],
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
  if (/tidak di depan/.test(m)) return { text: 'Binance tertutup jendela lain, dibawa ke depan lagi' };
  const waitingLeader = m.match(/^Menunggu leader menganalisis (Top \d+)/);
  if (waitingLeader) return { text: `Menunggu hasil AI dari pemimpin untuk ${waitingLeader[1]}` };
  const leaderSays = m.match(/^Hasil leader untuk Top (\d+): (\S+?), .*-> (\w+)/);
  if (leaderSays) {
    const ok = leaderSays[3] === 'OK';
    return { text: `Pemimpin: ${leaderSays[2]} ${ok ? 'layak short, ikut entry' : `${leaderSays[3].toLowerCase()}, tidak ada tindakan`}`, css: ok ? 'good' : '' };
  }
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

/** Top yang diikuti laptop ini sebagai pengikut: '*' = kelimanya, atau deretan angka tugas. */
function followedRanks() {
  if (form.rank === '*') return RANKS;
  return String(form.rank).split('').map(Number).filter((r) => RANKS.includes(r));
}

function watchedCount() {
  return form.mode !== 'follower' ? form.ranks.length : followedRanks().length;
}

function render() {
  const multi = form.mode !== 'follower';
  mark($('mode'), (v) => v === form.mode);
  mark($('interval'), (v) => Number(v) === Number(form.interval));
  const chosen = multi ? form.ranks : followedRanks();
  mark($('ranks'), (v) => chosen.includes(Number(v)));
  for (const node of document.querySelectorAll('[data-modes]')) {
    node.hidden = !node.dataset.modes.split(' ').includes(form.mode);
  }
  $('mode-note').textContent = MODE_NOTE[form.mode];
  updateLeaderLock();
  $('ranks-title').textContent = multi ? 'Top gainers yang dipantau' : 'Top gainer untuk laptop ini';
  $('ranks-note').textContent = multi
    ? `Bisa pilih lebih dari satu · ${form.ranks.length} dari 5 dipilih`
    : form.rank === '*' ? 'Mengikuti semua Top yang dimainkan pemimpin' : `Ditugaskan: ${rankLabel(form.rank)}`;
  $('ranks-all').hidden = !multi || form.ranks.length === RANKS.length;
  if (state === 'stopped') {
    $('seen-note').textContent = `dari ${watchedCount()} top gainers`;
    if (!flow.done && flow.step < 0) resetFlow(form.mode, 'Belum berjalan. Tekan Mulai memantau.');
  }
  window.bot.setRole(form.mode).then(applyTeam).catch(() => {}); // peran untuk daftar laptop di WiFi
  if (!$('peers-card').hidden) window.bot.peersNow().then(renderPeers).catch(() => {});
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
let teamInfo = { available: false, enabled: false, canLead: false, role: 'single', membership: null, loaded: false };
const counts = { seen: 0, ok: 0, open: 0 };

function setState(next, title, sub) {
  state = next;
  const running = next === 'running';
  $('status').classList.toggle('running', running);
  lockSetup();

  const engine = $('engine-state');
  engine.classList.toggle('running', running);
  engine.querySelector('strong').textContent = running ? 'Bot sedang bekerja' : next === 'stopping' ? 'Menghentikan bot' : 'Bot berhenti';
  engine.querySelector('span').textContent = running ? 'Jangan pakai mouse' : 'Siap dijalankan';

  $('platform-change').disabled = next !== 'stopped'; // ganti platform hanya saat bot berhenti
  const toggle = $('toggle');
  toggle.disabled = next === 'stopping';
  toggle.classList.toggle('stop', next !== 'stopped');
  toggle.replaceChildren(icon(next === 'stopped' ? 'play' : 'stop'),
    el('span', { textContent: { stopped: 'Mulai memantau', running: 'Hentikan', stopping: 'Menghentikan…' }[next] }));
  if (title) $('status-title').textContent = title;
  if (sub) $('status-sub').textContent = sub;
}

function lockSetup() {
  $('setup').classList.toggle('locked', state !== 'stopped' || Boolean(teamInfo.membership));
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
  const params = { exchange: platform.id, modal: form.modal, ranks: form.ranks, rank: form.rank, interval: form.interval };
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
  resetFlow(form.mode, 'Menyiapkan aplikasi Binance…');
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

  const [label, css] = VERDICT[e.verdict] || ['Tidak dibaca', ''];
  const act = actionOf(e);
  $('coins').querySelector('.empty-row')?.remove();
  $('coins').append(el('tr', {},
    el('td', { class: 'rank' }, el('span', { class: 'rank-badge', textContent: String(e.rank) })),
    el('td', { class: 'sym', textContent: e.symbol }),
    el('td', {}, dips(e.count_ai ?? e.count_data)),
    el('td', {}, el('span', { class: `tag ${css}`, textContent: label })),
    el('td', { class: 'why' },
      el('strong', { class: `act ${act.css}`, textContent: act.text }),
      el('span', { textContent: act.note }),
      e.summary ? el('small', { textContent: `AI: ${e.summary}` }) : null)));
}

/** Akibat keputusan AI untuk satu koin (kolom Tindakan). */
function actionOf(e) {
  if (e.status === 'open') {
    return { text: 'Short uji kertas dibuka', css: 'pos', note: `Masuk ${price(e.entry_price)} · target ${price(e.target_price)} · batas rugi ${price(e.stop_price)}` };
  }
  if (e.status === 'analyzed') {
    return e.verdict === 'ok'
      ? { text: 'Pengikut boleh short (uji)', css: 'pos', note: 'Hasil dibagikan; pengikut mengecek biaya lalu membuka posisi uji.' }
      : { text: 'Tidak ada tindakan', css: '', note: 'Hasil dibagikan; pengikut tidak masuk koin ini.' };
  }
  if (e.verdict === 'tunggu' || e.verdict === 'jangan') {
    return { text: 'Tidak ada tindakan', css: '', note: plain(e.reason) };
  }
  if (e.verdict === 'ok') return { text: 'Batal masuk', css: 'warn', note: plain(e.reason) };
  return { text: 'Dilewati', css: 'warn', note: plain(e.reason) };
}

// --------------------------------------------------------------------------- alur putaran

const FLOW = {
  single: ['Buka top gainers', 'Cek biaya & slot', 'AI baca grafik', 'Catat posisi uji'],
  leader: ['Buka top gainers', 'AI baca grafik', 'Keputusan', 'Bagikan ke pengikut'],
  follower: ['Tunggu AI pemimpin', 'Buka koin yang sama', 'Cek biaya & slot', 'Catat posisi uji'],
};
const flow = { mode: 'single', step: -1, done: false, symbol: '', nextAt: 0 };

function setFlow(step, sub, done = false) {
  flow.step = step;
  flow.done = done;
  $('flow-sub').textContent = sub;
  renderFlow();
}

function renderFlow() {
  const names = FLOW[flow.mode] || FLOW.single;
  $('steps').replaceChildren(...names.map((name, i) => {
    const kind = flow.done || i < flow.step ? 'done' : i === flow.step ? 'active' : '';
    return el('li', { class: `step ${kind}` },
      el('span', { class: 'step-no' }, kind === 'done' ? icon('check') : String(i + 1)),
      el('span', { textContent: name }));
  }));
}

/** Langkah putaran dari satu baris log engine. */
function advanceFlow(entry) {
  const e = entry.event;
  const m = entry.message || '';
  const leader = flow.mode === 'leader';
  const follower = flow.mode === 'follower';
  if (e?.type === 'cycle' && e.phase === 'start') {
    flow.nextAt = 0;
    setFlow(0, 'Membuka daftar top gainers Futures di Binance');
    return;
  }
  const waiting = m.match(/^Menunggu leader menganalisis (Top \d+)/);
  if (waiting) {
    setFlow(0, `Menunggu hasil AI dari pemimpin untuk ${waiting[1]}`);
    return;
  }
  const leaderSays = m.match(/^Hasil leader untuk Top (\d+): (\S+?), .*-> (\w+)/);
  if (leaderSays) {
    flow.symbol = leaderSays[2];
    if (leaderSays[3] === 'OK') setFlow(1, `Pemimpin: ${leaderSays[2]} layak short · membuka koin yang sama`);
    else setFlow(FLOW.follower.length, `Pemimpin: ${leaderSays[2]} ${leaderSays[3].toLowerCase()} · tidak ada tindakan`, true);
    return;
  }
  const opened = m.match(/^Top gainer #(\d+): (\S+)/);
  if (opened && follower) {
    setFlow(2, `Top ${opened[1]}: ${opened[2]} · cek funding, spread, dan slot posisi`);
    return;
  }
  if (opened) {
    flow.symbol = opened[2];
    setFlow(1, leader ? `Top ${opened[1]}: ${opened[2]} · membuka grafik 15 menit`
      : `Top ${opened[1]}: ${opened[2]} · cek funding, spread, dan slot posisi`);
    return;
  }
  if (/_15m\.png/.test(m) && !follower) {
    setFlow(leader ? 1 : 2, `AI membaca garis kuning ${flow.symbol} di grafik 15 menit`);
    return;
  }
  if (e?.type === 'coin') {
    const verdict = (VERDICT[e.verdict] || ['tidak dibaca'])[0];
    setFlow(3, leader ? `${e.symbol}: ${verdict} · dibagikan ke pengikut` : `${e.symbol}: ${actionOf(e).text.toLowerCase()}`);
    return;
  }
  if (e?.type === 'cycle' && e.phase === 'done') {
    flow.nextAt = e.next_in_s > 0 ? Date.now() + e.next_in_s * 1000 : 0;
    let sub = 'Putaran selesai.';
    if (flow.nextAt) sub += ' Menunggu putaran berikutnya.';
    else if (leader) sub += ' Hasil tetap dibagikan ke pengikut sampai Hentikan.';
    setFlow(FLOW[flow.mode].length, sub, true);
  }
}

function tickFlow() {
  const tag = $('flow-next');
  const left = Math.round((flow.nextAt - Date.now()) / 1000);
  tag.hidden = !(state === 'running' && flow.nextAt && left > 0);
  if (!tag.hidden) tag.textContent = `Putaran berikutnya ${Math.floor(left / 60)}:${String(left % 60).padStart(2, '0')}`;
}
setInterval(tickFlow, 1000);

function resetFlow(mode, sub) {
  flow.mode = mode;
  flow.nextAt = 0;
  setFlow(-1, sub);
}

window.bot.onLog((entry) => {
  const e = entry.event;
  if (e?.type === 'cycle' && e.phase === 'start') {
    emptyCoins('Membaca top gainers…');
    $('cycle-info').textContent = `Dimulai ${clock(entry.ts || Date.now() / 1000)}`;
  }
  if (e?.type === 'coin') addCoin(e);
  if (e?.type === 'hub') $('share').hidden = false;
  advanceFlow(entry);
  if (e?.type === 'cycle' && e.phase === 'done') {
    $('cycle-info').textContent = `Selesai ${clock(entry.ts || Date.now() / 1000)}`;
    if ($('coins').querySelector('.empty-row')) emptyCoins('Tidak ada koin yang bisa dinilai di putaran ini.');
  }
  const item = activity(entry);
  if (item) {
    addFeed(item, entry.ts || Date.now() / 1000);
    // Laptop lain (mis. pemimpin) bisa melihat aktivitas terakhir laptop ini.
    const coin = e?.type === 'coin' ? `${e.symbol}|${e.verdict || ''}|${e.status}` : '';
    window.bot.reportActivity({ text: item.text, coin }).catch(() => {});
  }
});

window.bot.onExit(({ code, signal }) => {
  const stopped = code === 130 || Boolean(signal);
  if (code === 0) setState('stopped', 'Selesai', 'Putaran selesai. Rekap ada di Hasil uji.');
  else if (stopped) setState('stopped', 'Dihentikan', 'Bot berhenti atas permintaan.');
  else setState('stopped', 'Berhenti karena kendala', 'Buka Cek laptop lalu coba lagi.');
  const text = code === 0 ? 'Bot selesai' : stopped ? 'Bot dihentikan' : 'Bot berhenti karena kendala';
  addFeed({ text, css: code === 0 || stopped ? '' : 'bad' }, Date.now() / 1000);
  window.bot.reportActivity({ text }).catch(() => {});
  flow.nextAt = 0;
  if (!flow.done) setFlow(flow.step, text);
  tickFlow();
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
    ['Ditutup (Sell)', s.manual ?? 0, 'var(--accent)'],
    ['Masih berjalan', s.open, 'var(--accent-2)'],
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
        { bar: s.closed / s.required_trades, barClass: 'accent', css: enough ? (passed ? 'pos' : 'neg') : '' }),
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
        el('td', { textContent: ROLE_NAME[t.role] || 'Sendiri' }),
        el('td', {}, el('span', { class: `tag ${css}`, textContent: label })),
        el('td', { class: 'num', textContent: price(t.entry_price) }),
        el('td', { class: 'num', textContent: price(t.exit_price) }),
        el('td', { class: `num ${signClass(t.pnl_capital_pct)}`, textContent: percent(t.pnl_capital_pct) }));
    });
    $('trades').replaceChildren(...(rows.length ? rows
      : [el('tr', { class: 'empty-row' }, el('td', { colSpan: 7, textContent: 'Belum ada posisi uji. Mulai memantau untuk mengisi catatan.' }))]));
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

// --------------------------------------------------------------------------- posisi (Sell)

function currentRole() {
  return teamInfo.membership ? 'follower' : form.mode;
}

function posNotice(text, css = '') {
  const notice = $('pos-notice');
  notice.hidden = !text;
  notice.className = `notice ${css}`;
  notice.textContent = text || '';
}

async function loadPositions() {
  const role = currentRole();
  const leading = role === 'leader' && teamInfo.canLead;
  $('pos-own').hidden = leading;
  $('pos-team').hidden = !leading;
  $('pos-close-all').hidden = !(leading || role === 'single');
  $('pos-lede').textContent = leading
    ? 'Tutup posisi para pengikut. Sell baru aktif bila semua pengikut tersambung.'
    : role === 'single'
      ? 'Tutup posisi uji kertas kapan saja. Tombol Binance tidak ditekan.'
      : 'Laptop ini pengikut: posisinya hanya bisa ditutup oleh pemimpin.';
  $('pos-refresh').disabled = true;
  try {
    if (leading) await loadTeamPositions();
    else await loadOwnPositions(role === 'single');
  } catch (err) {
    posNotice(err.message, 'bad');
  } finally {
    $('pos-refresh').disabled = false;
  }
}
loaders.positions = loadPositions;

async function loadOwnPositions(canSell) {
  const result = await window.bot.positions.list();
  posNotice(result.warning ? 'Harga Binance belum bisa diambil di jaringan ini; hasil sementara tidak tampil.' : '', 'warn');
  $('pos-close-all').disabled = !result.positions.length;
  const rows = result.positions.map((p) => el('tr', {},
    el('td', {}, el('strong', { class: 'sym', textContent: p.symbol }), el('small', { class: 'sub-role', textContent: ROLE_NAME[p.role] || 'Sendiri' })),
    el('td', { class: 'num', textContent: price(p.entry_price) }),
    el('td', { class: 'num', textContent: price(p.price) }),
    el('td', { class: `num ${signClass(p.pnl_capital_pct)}`, textContent: p.pnl_capital_pct === null ? '–' : `${percent(p.pnl_capital_pct)} modal` }),
    el('td', { class: 'num', textContent: `${price(p.target_price)} / ${price(p.stop_price)}` }),
    el('td', { class: 'num' }, canSell
      ? el('button', { class: 'sell', textContent: 'Sell', onclick: () => sellOwn(p.symbol) })
      : el('span', { class: 'locked', textContent: 'Ditutup pemimpin' }))));
  $('pos-table').replaceChildren(...(rows.length ? rows
    : [el('tr', { class: 'empty-row' }, el('td', { colSpan: 6, textContent: 'Tidak ada posisi yang terbuka.' }))]));
}

async function sellOwn(symbol) {
  const label = symbol === 'semua' ? 'semua posisi' : `posisi ${symbol}`;
  if (!window.confirm(`Tutup ${label}? (uji kertas, tombol Binance tidak ditekan)`)) return;
  try {
    const result = await window.bot.positions.close(symbol);
    const text = result.closed.map((c) => `${c.symbol} ${percent(c.pnl_capital_pct)} modal`).join(', ');
    window.bot.reportActivity({ text: text ? `Sell: ${text}` : 'Sell: tidak ada posisi' }).catch(() => {});
    await loadOwnPositions(true);
    posNotice(text ? `Ditutup: ${text}` : 'Tidak ada posisi yang ditutup.', 'good');
  } catch (err) {
    posNotice(err.message, 'bad');
  }
}

async function loadTeamPositions() {
  const { followers, allConnected } = await window.bot.team.followers();
  $('pos-close-all').disabled = !allConnected;
  if (!followers.length) {
    posNotice('Belum ada pengikut. Ajak laptop lain lewat Cek laptop › Lihat laptop.', 'warn');
  } else if (!allConnected) {
    const missing = followers.filter((f) => !f.connected).map((f) => f.name).join(', ');
    posNotice(`Sell dikunci: belum semua pengikut tersambung (${missing}).`, 'warn');
  } else {
    posNotice('Semua pengikut tersambung. Sell siap dijalankan.', 'good');
  }
  $('team-list').replaceChildren(...(followers.length ? followers.map((f) => followerCard(f, allConnected))
    : [el('li', { class: 'peer-empty', textContent: 'Belum ada pengikut.' })]));
}

function followerCard(f, allConnected) {
  const [state, css] = f.connected ? ['Tersambung', 'ok'] : f.accepted ? ['Terputus', 'jangan'] : ['Belum menerima ajakan', 'tunggu'];
  const positions = f.positions.length
    ? f.positions.map((p) => el('div', { class: 'f-pos' },
      el('strong', { class: 'sym', textContent: p.symbol }),
      el('span', { class: signClass(p.pnl), textContent: p.pnl === null ? '–' : `${percent(p.pnl)} modal` }),
      el('button', { class: 'sell', textContent: 'Sell', disabled: !allConnected, onclick: () => sellTeam(f.id, p.symbol, `${p.symbol} milik ${f.name}`) })))
    : [el('div', { class: 'f-pos none', textContent: 'Tidak ada posisi terbuka' })];
  return el('li', { class: 'follower' },
    el('div', { class: 'f-head' },
      el('span', { class: 'icon' }, icon('laptop')),
      el('div', {}, el('strong', { textContent: f.name }), el('span', { textContent: `${rankLabel(f.rank)}${f.activity ? ` · ${f.activity}` : ''}` })),
      el('span', { class: `tag ${css}`, textContent: state })),
    el('div', { class: 'f-positions' }, ...positions));
}

async function sellTeam(target, symbol, label) {
  if (!window.confirm(`Tutup ${label}? Pengikut menutupnya sendiri (uji kertas, tombol Binance tidak ditekan).`)) return;
  try {
    await window.bot.team.close(target, symbol);
    posNotice('Perintah Sell dikirim. Pengikut menutup posisinya dalam beberapa detik.', 'good');
    setTimeout(() => { if (!$('page-positions').hidden) loadPositions(); }, 8000);
  } catch (err) {
    posNotice(err.message, 'bad');
  }
}

$('pos-refresh').addEventListener('click', loadPositions);
$('pos-close-all').addEventListener('click', () => {
  if (currentRole() === 'leader') sellTeam('*', '*', 'semua posisi semua pengikut');
  else sellOwn('semua');
});
window.bot.positions.onChanged(() => {
  if (!$('page-positions').hidden) loadPositions();
});

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
    $('ready-bar').parentElement.className = `meter wide ${result.ok ? 'green' : 'accent'}`;
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
      const footer = c.id === 'hub_token'
        ? el('div', { class: 'check-footer' },
          el('span', { textContent: 'Lihat laptop lain di WiFi ini yang sedang membuka MarketForge.' }),
          el('button', { class: 'secondary with-icon', onclick: loadPeers }, icon('laptop'), 'Lihat laptop'))
        : null;
      return el('div', { class: `card check ${kind} ${footer ? 'wide' : ''}` },
        el('span', { class: 'icon' }, icon(c.ok ? 'check' : needed ? 'cross' : 'dash')),
        el('div', {}, el('strong', { textContent: title }), el('span', { textContent: detail })),
        el('span', { class: `tag ${tag}`, textContent: label }),
        footer);
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
    renderPeers(await window.bot.peers());
  } catch (err) {
    $('peers-sub').textContent = err.message;
    $('peers').replaceChildren();
  } finally {
    $('peers-refresh').disabled = false;
  }
}

/** Gambar daftar laptop. Dipanggil setelah pencarian dan setiap ada perubahan dari jaringan. */
function renderPeers(peers) {
  {
    const others = peers.filter((p) => !p.self).length;
    const leading = teamInfo.enabled && teamInfo.role === 'leader' && !teamInfo.membership;
    let hint = 'Belum ada laptop lain. Pastikan laptop lain membuka MarketForge di WiFi yang sama.';
    if (others) {
      hint = `${others} laptop lain ditemukan. `;
      if (!teamInfo.canLead) hint += 'Hanya laptop pemimpin yang bisa mengajak dan memantau laptop lain.';
      else if (!teamInfo.enabled) hint += 'Admin perlu mengisi token hub di laptop ini untuk mengajak pengikut.';
      else if (!leading) hint += 'Pilih peran Pemimpin di halaman Pantau untuk mengajak dan memantau laptop lain.';
      else hint += 'Pilih Top untuk tiap laptop, tekan Jadikan pengikut, lalu laptop itu menerima ajakannya.';
    }
    $('peers-sub').textContent = hint;
    $('peers-all').hidden = !(leading && peers.some((p) => p.followerRank || p.invitedRank));
    $('peers').replaceChildren(...peers.map((p) => peerRow(p, leading)));
  }
}

// Daftar yang sedang tampil ikut berubah saat peran/status laptop ini atau laptop lain berubah.
let peersPending = false;
window.bot.onPeersChanged(() => {
  if ($('peers-card').hidden || peersPending) return;
  peersPending = true;
  setTimeout(async () => {
    peersPending = false;
    try {
      teamInfo = await window.bot.team.state();
      renderPeers(await window.bot.peersNow());
    } catch {
      // daftar tetap seperti sebelumnya
    }
  }, 300);
});
$('peers-refresh').addEventListener('click', loadPeers);

function peerRow(p, leading) {
  const [role, roleCss] = ROLE_LABEL[p.role] || ROLE_LABEL.single;
  const meta = [p.os, p.address].filter(Boolean).join(' · ');
  const tags = el('div', { class: 'peer-tags' },
    el('span', { class: `tag ${roleCss}`, textContent: role }),
    el('span', { class: `tag ${p.running ? 'ok' : ''}`, textContent: p.running ? 'Bot berjalan' : 'Bot berhenti' }));
  let actions = [];
  if (p.self) {
    // Peran laptop ini diatur di halaman Pantau (Peran laptop).
    actions = [el('button', { class: 'secondary small', textContent: 'Ubah peran', onclick: () => showPage('run') })];
  } else if (leading) {
    actions = peerActions(p);
  }
  // Hanya pemimpin yang bisa memantau laptop lain (aktivitas terenkripsi ke kunci pemimpin).
  const monitor = !p.self && leading;
  const assigned = Boolean(p.followerRank || p.invitedRank);
  const assignable = monitor && p.team.verified !== false && (!assigned || editing.has(p.id));
  const open = monitor && expandedPeers.has(p.id);
  const row = el('li', { class: `peer ${p.self ? 'self' : ''} ${monitor ? 'clickable' : ''} ${open ? 'open' : ''}` },
    el('span', { class: 'icon' }, icon('laptop')),
    el('div', { class: 'peer-info' },
      el('strong', { textContent: p.self ? `${p.name} (laptop ini)` : p.name }),
      el('span', { textContent: monitor ? `${meta} · klik untuk memantau` : meta })),
    tags,
    el('div', { class: 'peer-actions' }, ...actions),
    assignable ? assignPanel(p, assigned) : null,
    open ? peerDetail(p) : null);
  if (monitor) {
    row.addEventListener('click', (ev) => {
      if (ev.target.closest('button, select, .peer-assign')) return;
      if (expandedPeers.has(p.id)) expandedPeers.delete(p.id);
      else expandedPeers.add(p.id);
      window.bot.peersNow().then(renderPeers).catch(() => {});
    });
  }
  return row;
}

const expandedPeers = new Set();

function ago(ms) {
  const s = Math.max(0, Math.round((Date.now() - ms) / 1000));
  return s < 60 ? `${s} detik lalu` : `${Math.round(s / 60)} menit lalu`;
}

/** Apa yang sedang dikerjakan laptop lain (diumumkan lewat Bonjour, ditandatangani token). */
function peerDetail(p) {
  const a = p.activity;
  if (!a) {
    return el('div', { class: 'peer-detail empty' },
      'Aktivitas belum terlihat. Pastikan laptop itu memakai MarketForge terbaru, token hub yang sama, dan kunci publik pemimpin.');
  }
  const coin = a.coin
    ? `${a.coin.symbol} · ${(VERDICT[a.coin.verdict] || ['tidak dibaca'])[0]} · ${a.coin.status === 'open' ? 'posisi uji dibuka' : a.coin.status === 'analyzed' ? 'dibagikan' : 'tidak masuk'}`
    : 'Belum ada';
  const item = (label, value) => el('div', {}, el('span', { textContent: label }), el('strong', { textContent: value }));
  return el('div', { class: 'peer-detail' },
    item('Sedang', a.text),
    item('Koin terakhir', coin),
    item('Diperbarui', a.at ? ago(a.at) : '–'));
}

/** Aksi pemimpin untuk satu laptop: ajak, batalkan ajakan, atau lepas pengikut. */
function peerActions(p) {
  const act = (fn) => async () => {
    try {
      await fn();
      await loadPeers();
    } catch (err) {
      $('peers-sub').textContent = err.message;
    }
  };
  const edit = el('button', { class: 'secondary small', textContent: 'Ubah Top', onclick: () => startEdit(p) });
  if (p.followerRank) {
    return [el('span', { class: 'tag follower', textContent: `Pengikut · ${rankLabel(p.followerRank)}` }), edit,
      el('button', { class: 'secondary small', textContent: 'Lepas', onclick: act(() => window.bot.team.uninvite(p.id)) })];
  }
  if (p.invitedRank) {
    return [el('span', { class: 'tag tunggu', textContent: `Menunggu jawaban · ${rankLabel(p.invitedRank)}` }), edit,
      el('button', { class: 'secondary small', textContent: 'Batal', onclick: act(() => window.bot.team.uninvite(p.id)) })];
  }
  return []; // laptop yang belum diajak: panel penugasan di bawah barisnya
}

// --------------------------------------------------------------------------- tugas Top pengikut

// Pilihan Top tiap laptop disimpan di sini (bukan di elemen), supaya tidak hilang saat daftar
// digambar ulang karena perubahan dari jaringan.
const picks = new Map(); // id laptop -> { all: boolean, tops: Set<number> }
const editing = new Set(); // id pengikut yang tugasnya sedang diubah

/** Top yang sedang dipilih pemimpin di halaman Pantau, itulah yang bisa dibagikan ke pengikut. */
const leaderTops = () => [...form.ranks].sort((a, b) => a - b);

function pickFor(p) {
  if (!picks.has(p.id)) picks.set(p.id, { all: true, tops: new Set() });
  return picks.get(p.id);
}

function startEdit(p) {
  const current = p.followerRank || p.invitedRank;
  picks.set(p.id, current === '*' || !current
    ? { all: true, tops: new Set() }
    : { all: false, tops: new Set(String(current).split('').map(Number)) });
  editing.add(p.id);
  window.bot.peersNow().then(renderPeers).catch(() => {});
}

/** Nilai tugas dari pilihan: '*' atau deretan angka dari Top pemimpin; null bila kosong. */
function pickValue(pick) {
  if (pick.all) return '*';
  const chosen = leaderTops().filter((r) => pick.tops.has(r));
  return chosen.length ? chosen.join('') : null;
}

function assignPanel(p, assigned) {
  const pick = pickFor(p);
  const rerender = () => window.bot.peersNow().then(renderPeers).catch(() => {});
  const chip = (label, on, onclick) => {
    const b = el('button', { type: 'button', class: `chip ${on ? 'on' : ''}`, textContent: label, onclick });
    b.setAttribute('aria-pressed', String(on));
    return b;
  };
  const chips = [
    chip('Semua top pilihanku', pick.all, () => {
      pick.all = !pick.all;
      if (!pick.all && pick.tops.size === 0) leaderTops().forEach((r) => pick.tops.add(r));
      rerender();
    }),
    ...leaderTops().map((r) => chip(`Top ${r}`, !pick.all && pick.tops.has(r), () => {
      pick.all = false;
      if (pick.tops.has(r)) pick.tops.delete(r); else pick.tops.add(r);
      rerender();
    })),
  ];
  const value = pickValue(pick);
  const save = el('button', {
    class: 'primary small',
    textContent: assigned ? 'Simpan' : 'Jadikan pengikut',
    disabled: value === null,
    onclick: async () => {
      try {
        await window.bot.team.invite(p.id, value);
        editing.delete(p.id);
        await rerender();
      } catch (err) {
        $('peers-sub').textContent = err.message;
      }
    },
  });
  const cancel = assigned
    ? el('button', { class: 'secondary small', textContent: 'Batal', onclick: () => { editing.delete(p.id); rerender(); } })
    : null;
  const hint = pick.all
    ? 'Mengikuti semua Top yang dimainkan pemimpin.'
    : value ? `Hanya ${rankLabel(value)}.` : 'Pilih minimal satu Top.';
  return el('div', { class: 'peer-assign' },
    el('div', { class: 'assign-chips' }, el('span', { class: 'assign-label', textContent: 'Top yang dimainkan' }), ...chips),
    el('div', { class: 'assign-foot' }, el('span', { textContent: hint }), el('div', { class: 'assign-actions' }, cancel, save)));
}

$('peers-all').addEventListener('click', async () => {
  try {
    const count = await window.bot.team.assignAll('*');
    $('peers-sub').textContent = `${count} pengikut kini memainkan semua Top yang dipilih pemimpin.`;
    window.bot.peersNow().then(renderPeers).catch(() => {});
  } catch (err) {
    $('peers-sub').textContent = err.message;
  }
});

// --------------------------------------------------------------------------- kelompok

/** Peran Pemimpin hanya untuk laptop yang memegang kunci pemimpin. */
function updateLeaderLock() {
  const button = $('mode').querySelector('[data-value="leader"]');
  const locked = teamInfo.loaded && !teamInfo.canLead;
  button.disabled = locked;
  button.title = locked ? 'Hanya laptop pemimpin (memegang kunci pemimpin dari admin)' : '';
  if (locked) $('mode-note').textContent = `${MODE_NOTE[form.mode]} Peran Pemimpin terkunci di laptop ini.`;
}

function applyTeam(info) {
  if (!info) return;
  teamInfo = { ...info, loaded: true };
  if (!info.canLead && form.mode === 'leader') {
    form.mode = 'single';
    render();
  }
  updateLeaderLock();
  const member = info.membership;
  $('group').hidden = !member;
  if (member) {
    $('group-title').textContent = `Pengikut dari ${member.leaderName} · ${rankLabel(member.rank)}`;
    $('group-sub').textContent = `Bot mulai otomatis setiap pemimpin memulai putaran (modal ${member.modal} USDT).`;
    if (form.mode !== 'follower' || form.rank !== member.rank) {
      form.mode = 'follower';
      form.rank = member.rank;
      render();
    }
  }
  lockSetup();
}

let pendingInvite = null;

function showInvite(invite) {
  pendingInvite = invite;
  $('invite-title').textContent = `${invite.leaderName} mengajak laptop ini`;
  $('invite-text').textContent = `Menjadi Pengikut untuk ${invite.rank === '*' ? 'semua Top yang dimainkan pemimpin' : rankLabel(invite.rank)}. Bot laptop ini akan mulai otomatis setiap pemimpin memulai putaran, memakai hasil AI dari pemimpin.`;
  $('invite-modal').value = form.modal;
  $('invite-error').textContent = '';
  $('invite').hidden = false;
  $('invite-modal').focus();
}

$('invite-accept').addEventListener('click', async () => {
  if (!pendingInvite) return;
  try {
    const modal = $('invite-modal').value.trim();
    applyTeam(await window.bot.team.accept(pendingInvite.leaderId, modal));
    form.modal = modal;
    $('modal').value = modal;
    $('invite').hidden = true;
    pendingInvite = null;
    render();
    showPage('run');
  } catch (err) {
    $('invite-error').textContent = err.message;
  }
});
$('invite-decline').addEventListener('click', async () => {
  if (pendingInvite) await window.bot.team.decline(pendingInvite.leaderId).catch(() => {});
  pendingInvite = null;
  $('invite').hidden = true;
});
$('group-leave').addEventListener('click', async () => {
  applyTeam(await window.bot.team.leave());
});

window.bot.team.onInvite(showInvite);
window.bot.team.onChanged((info) => {
  applyTeam(info);
  if (info.notice) addFeed({ text: info.notice, css: 'warn' }, Date.now() / 1000);
});
window.bot.team.onError((message) => addFeed({ text: message, css: 'bad' }, Date.now() / 1000));
window.bot.team.onStarted(({ leaderName, rank }) => {
  Object.assign(counts, { seen: 0, ok: 0, open: 0 });
  setCounts();
  emptyCoins('Menyiapkan Binance…');
  emptyFeed('Menunggu aktivitas pertama…');
  setState('running', 'Mengikuti pemimpin', `${leaderName} memulai putaran; laptop ini menilai Top ${rank}.`);
  resetFlow('follower', `${leaderName} memulai putaran; laptop ini menilai Top ${rank}.`);
});
window.bot.team.state().then(applyTeam).catch(() => {});

// --------------------------------------------------------------------------- mulai

loadForm();
setupForm();
render();
setState('stopped');
setCounts();
emptyCoins('Belum ada koin yang dinilai. Tekan Mulai memantau.');
resetFlow(form.mode, 'Belum berjalan. Tekan Mulai memantau.');
emptyFeed('Aktivitas bot akan muncul di sini.');
window.bot.status().then(({ running }) => {
  if (running) {
    setState('running', 'Sedang memantau', 'Bot sedang bekerja.');
    choosePlatform('binance'); // bot sudah berjalan: langsung ke dashboard
  }
});

// --------------------------------------------------------------------------- pilih platform

let platform = null; // platform yang sedang dipakai

/** Logo platform. Logo gelap (Tebbit) ditaruh di kotak terang agar terlihat di tema gelap. */
function platformMark(p) {
  const mark = el('span', { class: `plat-logo ${p.id}` }, el('img', { src: p.logo, alt: '' }));
  mark.setAttribute('aria-hidden', 'true');
  return mark;
}

function renderPlatforms() {
  $('platforms').replaceChildren(...PLATFORMS.map((p) => {
    const card = el('button', { type: 'button', class: `platform ${p.ready ? '' : 'soon'}` },
      platformMark(p),
      el('div', {}, el('strong', { textContent: p.name }), el('span', { textContent: p.note })),
      el('span', { class: `tag ${p.ready ? 'ok' : ''}`, textContent: p.ready ? 'Tersedia' : 'Segera hadir' }));
    card.setAttribute('role', 'listitem');
    if (p.ready) {
      card.addEventListener('click', () => choosePlatform(p.id));
    } else {
      card.disabled = true; // belum bisa dipilih
      card.title = 'Belum tersedia';
    }
    return card;
  }));
}

function choosePlatform(id) {
  const chosen = PLATFORMS.find((p) => p.id === id);
  if (!chosen?.ready) return; // bursa yang belum siap tidak pernah menjadi platform aktif
  platform = chosen;
  $('platform-name').textContent = chosen.name;
  $('platform-logo').src = chosen.logo;
  $('platform-logo').parentElement.className = `plat-logo ${chosen.id}`;
  $('chooser').hidden = true;
  $('app').inert = false;
  showPage('run');
}

function showChooser() {
  if (state !== 'stopped') return; // tidak bisa ganti platform saat bot berjalan
  $('chooser').hidden = false;
  $('app').inert = true;
  $('platforms').querySelector('button:not(:disabled)')?.focus();
}

renderPlatforms();
$('platform-change').addEventListener('click', showChooser);
$('platforms').querySelector('button:not(:disabled)')?.focus();

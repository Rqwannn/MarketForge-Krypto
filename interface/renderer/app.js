'use strict';

// Tampilan aplikasi untuk pengguna non-teknis. Pesan engine diterjemahkan ke bahasa sehari-hari;
// detail teknis tetap ada di engine/logs/bot.log untuk admin. Semua teks ditulis dengan
// textContent (tanpa innerHTML) karena berasal dari engine dan jurnal.

const $ = (id) => document.getElementById(id);
const FORM_KEY = 'marketforge.form.v2';
const RANKS = [1, 2, 3, 4, 5];
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
  long: ['Layak long', 'ok'],
  konflik: ['Short dan long', 'tunggu'],
  tunggu: ['Tunggu', 'tunggu'],
  jangan: ['Jangan short', 'jangan'],
};
const ENTER_VERDICTS = ['ok', 'long'];
const STATUS = {
  open: ['Berjalan', 'open'],
  target: ['Target tercapai', 'target'],
  likuidasi: ['Likuidasi', 'stop'],
  stop: ['Kena cutloss', 'stop'], // juga catatan lama "batas rugi"
  timeout: ['Batas waktu', 'timeout'],
  manual: ['Ditutup (Sell)', 'manual'],
};
const SIDE_NAME = { short: 'Short', long: 'Long' };
const sideOf = (x) => SIDE_NAME[x?.side] || 'Short';
const TopChoice = window.Tops; // arah per Top (renderer/tops.js)
const Interval = window.Interval; // jeda pemantauan (renderer/interval.js)
let platform = null; // platform yang sedang dipakai
// Platform (bursa). Hanya yang `ready: true` yang bisa dipilih dan dijalankan engine.
const PLATFORMS = [
  { id: 'binance', name: 'Binance', logo: 'img/binance.png', note: 'Futures · pantau top gainers', ready: true },
  { id: 'tebbit', name: 'Tebbit', logo: 'img/tebbit.png', note: 'Website di Chrome · tebbit.io', ready: true },
];
/** Top tugas pengikut: angka 1..5, atau '*' = semua Top yang dimainkan pemimpin. */
const rankLabel = (rank) => (rank === '*' ? 'Semua top' : `Top ${String(rank).split('').join(', ')}`);
const ROLE_NAME = { single: 'Sendiri', follower: 'Pengikut', leader: 'Pemimpin', contoh: 'Contoh' };
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
    // Pemberitahuan Real Fund Trading (bukan kendala): kalimat sederhana, tanpa detail teknis.
    [/MODE UANG SUNGGUHAN/, 'Mode uang sungguhan menyala: bot menekan tombol di Binance'],
    [/saldo tersedia ([\d.,]+) USDT kurang dari margin ([\d.,]+) USDT/, (m) => `Saldo tersedia ${m[1]} USDT kurang dari margin ${m[2]} USDT: tidak masuk`],
    [/saldo tersedia tidak terbaca/, 'Saldo tersedia tidak terbaca di form order, tidak masuk demi keamanan'],
    [/Cek ulang (\S+) sebelum menjual/, (m) => `Cek ulang harga ${m[1]} sebelum menjual`],
    [/ORDER SUNGGUHAN: tekan (Jual\/Short|Beli\/Long) (\S+)/, (m) => `Uang sungguhan: bot menekan ${m[1]} ${m[2]}`],
    [/ORDER SUNGGUHAN: tutup posisi (\S+)/, (m) => `Uang sungguhan: bot menekan Market untuk menjual ${m[1]}`],
    [/Posisi ditutup di bursa\. Jual otomatis (\S+)/, (m) => `${m[1]} terjual otomatis di Binance`],
    [/Jual otomatis (\S+) GAGAL di bursa/, (m) => `Jual otomatis ${m[1]} gagal, posisi tetap terbuka dan dicoba lagi`],
    [/Leverage tidak bisa diubah/, 'Leverage koin ini tidak bisa diubah ke 2x otomatis'],
    [/belum terbaca untuk jual otomatis/, 'Harga posisi belum terbaca, jual otomatis dicoba lagi'],
    [/Data pasar Binance|fapi\.binance|certificate|urlopen/i, 'Data harga Binance tidak bisa diambil di jaringan ini'],
    [/memenuhi syarat SHORT dan menunjukkan/, 'Grafik cocok untuk short dan long sekaligus, tidak masuk'],
    [/arah SHORT tidak dipilih/, 'Pola cocok untuk short, tetapi arah short tidak dipilih'],
    [/berdekatan/, 'Garis kuning dan magenta berdekatan; masuk hanya bila berjauhan'],
    [/JANGAN/, 'Garis kuning selalu di atas, harga masih naik terus'],
    [/6 jam terakhir naik terus/, 'Garis kuning sempat turun, tapi 6 jam terakhir harga naik terus'],
    [/TUNGGU/, 'Garis kuning baru sekali turun, harga masih bisa naik lagi'],
    [/tanda LONG tidak terbaca/, 'Tanda long belum terbaca oleh AI, tidak masuk'],
    [/tidak ada tanda LONG/, 'Belum ada tanda masuk long'],
    [/sedang rugi/, 'Posisi pertama sedang rugi, koin berikutnya ditunda'],
    [/Leader tidak (memainkan|menilai) Top/, 'Pemimpin tidak menilai Top ini di putaran ini, tidak ada tindakan'],
    [/belum memulai putaran/, 'Pemimpin belum memulai putaran baru, tidak ada tindakan'],
    [/sudah diikuti di putaran ini/, 'Koin ini sudah diikuti dari Top lain di putaran ini'],
    [/sudah ada posisi uji/, 'Koin ini sudah punya posisi yang berjalan'],
    // Catatan lama: aturan funding sudah dihapus 20 Okt 2026, bot tidak menyaring funding lagi.
    [/funding (-?[\d.]+)%/i, (m) => `Dilewati aturan funding lama (${m[1].replace('.', ',')}%), aturan ini sudah dihapus`],
    [/funding/i, 'Dilewati aturan funding lama, aturan ini sudah dihapus'],
    [/spread ([\d.]+)% > ([\d.]+)%/i, (m) => `Selisih harga beli dan jual terlalu lebar (${m[1].replace('.', ',')}%, batas ${m[2].replace('.', ',')}%)`],
    [/spread/i, 'Selisih harga beli dan jual terlalu lebar'],
    [/naik .*dalam 24 jam|naik [\d.]+% </, 'Kenaikan 24 jam belum cukup'],
    [/bukan pair USDT/, 'Bukan pasangan USDT'],
    [/Tombol '15 mnt'/, 'Tombol 15 menit tidak terlihat di halaman koin ini (tata letak bergeser), koin dilewati'],
    [/Grafik 15 menit|15 mnt/, 'Grafik belum termuat, koin dilewati'],
    [/Ukuran jendela/, `Ukuran jendela ${site} berubah, kembalikan seperti semula`],
    [/belum berjalan|Buka aplikasi Binance|AppNotRunning/i, 'Aplikasi Binance belum dibuka'],
    [/Satuan kolom (Jumlah|Quantity)|Margin Awal|menu satuan|Ukuran Order/i, `Satuan kolom jumlah di ${site} bukan USDT. Pilih USDT > Ukuran Order, lalu coba lagi`],
    [/Kolom (Jumlah|Quantity)/, `Kolom jumlah di ${site} tidak terisi dengan benar`],
    [/Indikator MA/, `Atur indikator grafik ${site} ke MA 7, MA 25, MA 99`],
    [/tidak tampil di layar/, `Jendela ${site} tertutup jendela lain, bot berhenti demi keamanan`],
    [/leverage \S+x, seharusnya/i, `Leverage di ${site} belum 2x (ubah sebelum memakai uang sungguhan)`],
    [/BOT_HUB_TOKEN wajib/, 'Token hub belum diatur di laptop ini, hubungi admin'],
    [/Leader belum menilai (Top \d+)/, (m) => `Pemimpin belum menilai ${m[1]}, tidak ada tindakan`],
    [/sudah tidak di top/, 'Koin pemimpin sudah keluar dari top gainers, tidak ada tindakan'],
    [/peringkat bergeser/, 'Peringkat bergeser saat membuka koin, tidak ada tindakan'],
    [/sudah tidak di daftar|di luar Top 5/, 'Koin keluar dari Top 5 saat akan dibuka, tidak dinilai'],
    [/Hub belum punya|menunggu hasil/i, 'Hasil dari laptop pemimpin belum tersedia'],
    [/[Hh]ub .*(tidak bisa|menolak)|BOT_HUB/, 'Belum terhubung ke laptop pemimpin, hubungi admin'],
    [/VIKEY|Kunci AI|kunci API/i, 'Pengaturan AI di laptop ini belum lengkap, hubungi admin'],
    [/[Aa]nalisis AI|model/, 'AI belum bisa membaca grafik koin ini'],
    [/Leverage tidak terbaca/, `Leverage di ${site} tidak terbaca di layar, koin dilewati`],
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
    if (e.status === 'open') return { text: `${e.symbol} masuk posisi ${e.real ? 'sungguhan' : 'uji'}`, css: 'good' };
    if (e.status === 'analyzed') return { text: `${e.symbol}: ${(VERDICT[e.verdict] || ['dibaca'])[0].toLowerCase()}` };
    return { text: `${e.symbol} dilewati: ${plain(e.reason).toLowerCase()}` };
  }
  if (e?.type === 'hub') return { text: 'Mulai membagikan hasil ke laptop pengikut', css: 'good' };
  if (e?.type === 'watch') return { text: `Mengawasi ${e.open} posisi sampai terjual atau putaran pemimpin berikutnya` };
  if (e?.type === 'sell') {
    const why = { target: 'target tercapai', stop: 'cutloss', timeout: 'batas waktu' }[e.status] || e.status;
    return { text: `Jual otomatis ${e.symbol}: ${why} (${percent(e.pnl_pct)}), tombol tidak ditekan`, css: e.pnl_pct >= 0 ? 'good' : 'bad' };
  }
  if (e?.type === 'view') return { text: entry.message };  // "AI membaca grafik X", "Kembali ke Binance"

  const m = entry.message || '';
  const opened = m.match(/^Top gainer #(\d+): (\S+)/);
  if (opened) return { text: `Membuka top ${opened[1]}: ${opened[2]}` };
  if (/^(Tidak masuk putaran ini|Berhenti memantau): /.test(m)) return { text: plain(m), css: 'warn' };
  if (/^Tidak ada koin dengan pola OK/.test(m)) return { text: 'Belum ada koin yang layak, pantau lagi nanti' };
  if (/tidak di depan/.test(m)) return { text: `${platform?.name || 'Binance'} tertutup jendela lain, dibawa ke depan lagi` };
  const button = m.match(/Tombol (?:Jual\/(Short)|Beli\/(Long))/);
  const side = button ? button[1] || button[2] : '';
  if (/^Tombol \S+ ditemukan/.test(m)) return { text: `Tombol ${side} ditemukan di layar, tidak ditekan (uji kertas)` };
  if (/^Tombol \S+ tidak ditemukan/.test(m)) return { text: `Tombol ${side} tidak terbaca di layar (uji kertas tetap jalan)`, css: 'warn' };
  if (/^\[DRY RUN\] Tombol \S+ TIDAK ditekan/.test(m)) return { text: `Uji kertas: order dicatat, tombol ${side} tidak ditekan`, css: 'good' };
  const waitingLeader = m.match(/^Menunggu leader menganalisis (Top \d+)/);
  if (waitingLeader) return { text: `Menunggu hasil AI dari pemimpin untuk ${waitingLeader[1]}` };
  const leaderSays = m.match(/^Hasil leader untuk Top (\d+): (\S+?), .*-> (\w+)/);
  if (leaderSays) {
    const ok = ['OK', 'LONG'].includes(leaderSays[3]);
    const fit = leaderSays[3] === 'LONG' ? 'layak long' : 'layak short';
    return { text: `Pemimpin: ${leaderSays[2]} ${ok ? `${fit}, ikut entry` : `${leaderSays[3].toLowerCase()}, tidak ada tindakan`}`, css: ok ? 'good' : '' };
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
  window.scrollTo(0, 0); // halaman baru selalu mulai dari atas, bukan posisi gulir halaman lama
  loaders[name]?.();
}
for (const item of document.querySelectorAll('.menu-item')) item.addEventListener('click', () => showPage(item.dataset.page));

// --------------------------------------------------------------------------- pengaturan putaran

// Arah per Top (shortTops, longTops) dan aturan keluar: cutloss 10% dan batas waktu 2,5-3 jam
// menyala sejak 23 Okt (bisa dimatikan).
const form = {
  mode: 'single', modal: '', shortTops: [...RANKS], longTops: [], rank: 1, interval: 0, cutloss: true, timeLimit: true,
  customInterval: false, // "Atur": jeda sendiri dalam menit (form.interval)
};
let intervalError = ''; // isian menit yang belum sah: Mulai ditahan sampai diperbaiki

/** Top yang dipantau Sendiri/Pemimpin: gabungan Top short dan Top long. */
const watchedTops = () => TopChoice.watched(form);

function loadForm() {
  try {
    Object.assign(form, JSON.parse(localStorage.getItem(FORM_KEY) || '{}'));
  } catch {
    // penyimpanan lokal tidak tersedia: pakai default
  }
  // Pilihan lama (Top yang dipantau + satu arah untuk semua) diubah ke arah per Top.
  Object.assign(form, TopChoice.restore(form));
  form.interval = Interval.restore(form.interval);
  form.customInterval = form.customInterval === true || !Interval.PRESETS.includes(form.interval);
  delete form.ranks;
  delete form.direction;
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
  return form.mode !== 'follower' ? watchedTops().length : followedRanks().length;
}

function render() {
  const multi = form.mode !== 'follower';
  mark($('mode'), (v) => v === form.mode);
  renderInterval();
  mark($('ranks'), (v) => followedRanks().includes(Number(v)));
  mark($('tops-short'), (v) => form.shortTops.includes(Number(v)));
  mark($('tops-long'), (v) => form.longTops.includes(Number(v)));
  for (const node of document.querySelectorAll('[data-modes]')) {
    node.hidden = !node.dataset.modes.split(' ').includes(form.mode);
  }
  $('mode-note').textContent = MODE_NOTE[form.mode];
  renderModal();
  renderExits();
  updateLeaderLock();
  $('ranks-title').textContent = multi ? 'Top gainers dan arahnya' : 'Top gainer untuk laptop ini';
  $('ranks-note').textContent = multi
    ? TopChoice.note(form)
    : form.rank === '*' ? 'Mengikuti semua Top yang dimainkan pemimpin' : `Ditugaskan: ${rankLabel(form.rank)}`;
  if (state === 'stopped') {
    $('seen-note').textContent = `dari ${watchedCount()} top gainers`;
    if (!flow.done && flow.step < 0) resetFlow(form.mode, 'Belum berjalan. Tekan Mulai memantau.');
  }
  window.bot.setRole(form.mode).then(applyTeam).catch(() => {}); // peran untuk daftar laptop di WiFi
  if (!$('peers-card').hidden) window.bot.peersNow().then(renderPeers).catch(() => {});
  saveForm();
}

function setupForm() {
  for (const id of ['ranks', 'tops-short', 'tops-long']) {
    for (const r of RANKS) {
      const btn = el('button', { type: 'button' }, el('small', { textContent: 'Top' }), el('strong', { textContent: String(r) }));
      btn.dataset.value = String(r);
      $(id).append(btn);
    }
  }
  // Arah per Top: klik chip = Top itu boleh/tidak untuk arah tersebut. Klik label baris = semua
  // atau kosong. Minimal satu Top tetap terpilih (di arah mana pun).
  for (const side of ['short', 'long']) {
    $(`tops-${side}`).addEventListener('click', (ev) => {
      const r = Number(ev.target.closest('button')?.dataset.value);
      if (r) setTops(TopChoice.toggle(form, side, r));
    });
    $(`tops-${side}-all`).addEventListener('click', () => setTops(TopChoice.toggleAll(form, side)));
  }
  $('mode').addEventListener('click', (ev) => {
    const value = ev.target.closest('button')?.dataset.value;
    if (value) form.mode = value;
    render();
  });
  $('interval').addEventListener('click', (ev) => {
    const value = ev.target.closest('button')?.dataset.value;
    if (value === undefined) return;
    form.customInterval = value === 'custom';
    if (form.customInterval) {
      const typed = Interval.parse($('interval-custom').value);
      if (typed.minutes) form.interval = typed.minutes;
      render();
      $('interval-custom').focus();
      return;
    }
    form.interval = Number(value);
    intervalError = '';
    render();
  });
  $('interval-custom').addEventListener('input', () => {
    const typed = Interval.parse($('interval-custom').value);
    intervalError = typed.error || '';
    if (typed.minutes) form.interval = typed.minutes;
    render();
  });
  $('ranks').addEventListener('click', (ev) => {
    const r = Number(ev.target.closest('button')?.dataset.value);
    if (!r) return;
    form.rank = r; // pengikut: Top tugasnya
    render();
  });
  // Seluruh kartu bisa diklik, bukan hanya saklarnya.
  for (const card of document.querySelectorAll('.exit-option')) {
    card.addEventListener('click', () => {
      const key = EXIT_SWITCHES[card.dataset.switch];
      form[key] = !form[key];
      render();
    });
  }
  renderModal();
  $('modal').addEventListener('input', () => {
    form.modal = $('modal').value.trim();
    renderModal();
    saveForm();
  });
  for (const [kind, id] of [['setengah', 'modal-half'], ['max', 'modal-max']]) {
    $(id).addEventListener('click', () => {
      form.modal = balanceModal(form.modal) === kind ? '' : kind;
      renderModal();
      saveForm();
      if (!balanceModal(form.modal)) $('modal').focus();
    });
  }
}

/**
 * Modal dari saldo, dibaca bot dari form order saat akan masuk: 'max' = seluruh saldo USDT
 * tersedia, 'setengah' = 50%-nya (saldo 600 -> modal 300). Selain itu null (modal angka USDT).
 */
const BALANCE_LABEL = { max: 'Max', setengah: '50%' };
function balanceModal(modal) {
  const key = String(modal || '').trim().toLowerCase();
  if (key === 'max') return 'max';
  return key === 'setengah' || key === '50%' ? 'setengah' : null;
}

/** Teks modal untuk dibaca orang: "100 USDT", "Max (seluruh saldo)", atau "50% saldo". */
function modalText(modal) {
  const kind = balanceModal(modal);
  if (kind === 'max') return 'Max (seluruh saldo)';
  return kind === 'setengah' ? '50% saldo (setengah)' : `${modal} USDT`;
}

const MODAL_NOTE = {
  max: 'Modal = seluruh saldo USDT tersedia saat bot masuk. Tiap posisi memakai separuhnya, leverage 2x.',
  setengah: 'Modal = setengah saldo USDT tersedia saat bot masuk (saldo 600 → modal 300). Tiap posisi memakai separuh modal, leverage 2x.',
};

function renderModal() {
  const kind = balanceModal(form.modal);
  const input = $('modal');
  if (kind) input.value = BALANCE_LABEL[kind];
  else if (balanceModal(input.value)) input.value = '';
  else if (input.value !== form.modal) input.value = form.modal;
  input.readOnly = Boolean(kind);
  input.classList.toggle('is-max', Boolean(kind));
  for (const [key, id] of [['setengah', 'modal-half'], ['max', 'modal-max']]) {
    $(id).classList.toggle('on', kind === key);
    $(id).setAttribute('aria-pressed', String(kind === key));
  }
  $('modal-note').textContent = MODAL_NOTE[kind] || 'Tiap posisi memakai separuh modal, leverage 2x.';
}

const EXIT_SWITCHES = { cutloss: 'cutloss', 'time-limit': 'timeLimit' }; // id saklar -> isian form

/** Ulangi pemantauan: pilihan cepat, atau "Atur" dengan kolom menit. */
function renderInterval() {
  const custom = form.customInterval;
  mark($('interval'), (v) => (v === 'custom' ? custom : !custom && Number(v) === Number(form.interval)));
  $('interval-custom-wrap').hidden = !custom;
  const input = $('interval-custom');
  if (custom && document.activeElement !== input && !intervalError) {
    input.value = Interval.PRESETS.includes(form.interval) ? '' : String(form.interval);
  }
  const waiting = custom && !intervalError && Interval.PRESETS.includes(form.interval) && !input.value;
  const error = intervalError || (waiting ? 'Isi jeda dalam menit' : '');
  $('interval-note').textContent = error || Interval.note(form.interval);
  $('interval-note').classList.toggle('bad', Boolean(error));
}

/** Pilihan Top baru; null = ditolak (minimal satu Top tetap dipantau). */
function setTops(next) {
  if (!next) return;
  form.shortTops = next.shortTops;
  form.longTops = next.longTops;
  render();
}

/** Cutloss dan batas waktu (Binance dan Tebbit). */
function renderExits() {
  for (const [id, key] of Object.entries(EXIT_SWITCHES)) {
    $(id).setAttribute('aria-checked', String(form[key]));
    $(id).closest('.exit-option').classList.toggle('on', form[key]);
  }
  // Tanpa cutloss, satu-satunya batas rugi adalah batas waktu atau likuidasi: diingatkan.
  const note = $('exit-note');
  note.hidden = form.cutloss;
  note.textContent = form.timeLimit
    ? 'Tanpa cutloss: rugi hanya dibatasi batas waktu 3 jam.'
    : 'Tanpa cutloss dan batas waktu: rugi bisa bertambah sampai likuidasi.';
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
  renderReal();
}

// --------------------------------------------------------------------------- Real Fund Trading

// Mati setiap aplikasi dibuka; hanya menyala lewat modal peringatan. Untuk Pemimpin, menyalakan
// juga mengajak pengikut (tiap laptop pengikut menyetujui sendiri di modal yang sama).
let realOn = false;
let runningReal = false; // bot yang sedang berjalan memakai uang sungguhan

function renderReal() {
  const button = $('real-toggle');
  const binance = (platform?.id || 'binance') === 'binance';
  if (!binance) realOn = false;
  button.disabled = state !== 'stopped' || !binance;
  button.setAttribute('aria-checked', String(realOn));
  $('real-card').classList.toggle('on', realOn);
  $('real-state').textContent = realOn ? 'Aktif' : 'Mati';
  $('real-note').textContent = !binance
    ? 'Belum tersedia untuk Tebbit.'
    : realOn
      ? 'Uang sungguhan: bot membeli dan menjual sendiri di Binance, dan tetap menyala sampai posisinya terjual.'
      : 'Sekarang uji kertas: posisi hanya dicatat, tanpa uang sungguhan.';
  const real = state !== 'stopped' ? runningReal : realOn;
  $('paper').classList.toggle('real', real);
  $('paper-tag').className = real ? 'tag danger' : 'tag outline';
  $('paper-tag').textContent = real ? 'Uang sungguhan' : 'Uji kertas';
  $('paper-text').textContent = real
    ? `Bot menekan tombol order dan tutup posisi di Binance dengan uangmu. ${form.cutloss ? 'Cutloss 10%.' : 'Tanpa stop-loss.'}`
    : 'Bot tidak pernah menekan tombol beli atau jual. Setiap posisi hanya dicatat.';
}

/** Modal peringatan uang sungguhan. Selesai dengan true hanya bila dicentang dan diketik SETUJU. */
function askReal({ follower = false, leaderName = '', modal = '' } = {}) {
  const dialog = $('real-dialog');
  const ack = $('real-ack');
  const word = $('real-word');
  const confirm = $('real-confirm');
  $('real-title').textContent = follower ? `${leaderName} memakai uang sungguhan` : 'Nyalakan Real Fund Trading?';
  $('real-intro').textContent = follower
    ? 'Laptop ini ikut memakai uang sungguhan hanya bila kamu setuju; bila ditolak, laptop ini mengikuti sebagai uji kertas. Tiap posisi:'
    : 'Mulai putaran berikutnya, bot memakai uangmu di Binance. Tiap posisi:';
  const chosen = modal || form.modal || '';
  const capital = Number(String(chosen).replace(',', '.'));
  const usdt = (v) => `${v.toLocaleString('id-ID', { maximumFractionDigits: 2 })} USDT`;
  const kind = balanceModal(chosen);
  if (kind === 'max') {
    $('real-notional').textContent = 'Seluruh saldo USDT tersedia';
    $('real-margin').textContent = 'Separuh saldo tersedia';
  } else if (kind === 'setengah') {
    $('real-notional').textContent = 'Setengah saldo USDT tersedia';
    $('real-margin').textContent = 'Seperempat saldo tersedia';
  } else {
    $('real-notional').textContent = capital > 0 ? usdt(capital) : '–';
    $('real-margin').textContent = capital > 0 ? usdt(capital / 2) : '50% modal';
  }
  const cutloss = follower ? undefined : form.cutloss;
  $('real-risk-title').textContent = cutloss ? 'Cutloss 10%' : 'Tanpa stop-loss';
  $('real-risk-text').textContent = cutloss === undefined
    ? 'Cutloss dan batas waktu mengikuti pilihan pemimpin. Tanpa cutloss, rugi bisa bertambah sampai likuidasi.'
    : cutloss
      ? 'Bot menjual bila harga melawan posisi 10% (rugi sekitar 10% modal), bisa lebih jauh bila harga melompat.'
      : 'Bila harga terus melawan posisi, rugi bertambah sampai likuidasi.';
  ack.checked = false;
  word.value = '';
  confirm.disabled = true;
  dialog.hidden = false;
  word.focus();
  const valid = () => { confirm.disabled = !(ack.checked && word.value.trim().toUpperCase() === 'SETUJU'); };
  return new Promise((resolve) => {
    const done = (ok) => {
      dialog.hidden = true;
      ack.onchange = word.oninput = confirm.onclick = $('real-cancel').onclick = null;
      resolve(ok);
    };
    ack.onchange = valid;
    word.oninput = valid;
    confirm.onclick = () => done(true);
    $('real-cancel').onclick = () => done(false);
  });
}

$('real-toggle').addEventListener('click', async () => {
  if (state !== 'stopped') return;
  realOn = realOn ? false : await askReal();
  renderReal();
});

window.bot.team.onRealRequest(async (request) => {
  const ok = await askReal({ follower: true, ...request });
  window.bot.team.realAnswer(ok).catch(() => {});
});

function setCounts() {
  const watched = watchedCount();
  $('count-seen').textContent = String(counts.seen);
  $('count-ok').textContent = String(counts.ok);
  $('count-open').textContent = `${counts.open}`;
  $('seen-note').textContent = `dari ${watched} top gainers`;
  setBar('seen-bar', counts.seen / watched);
  setBar('ok-bar', counts.seen ? counts.ok / counts.seen : 0);
  setBar('open-bar', counts.ok ? counts.open / counts.ok : 0);
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
  if (form.mode !== 'follower' && form.customInterval) {
    const typed = Interval.parse($('interval-custom').value);
    if (typed.error) {
      $('run-error').textContent = typed.error;
      $('interval-custom').focus();
      return;
    }
    form.interval = typed.minutes;
  }
  const params = {
    exchange: platform.id, modal: form.modal, ranks: watchedTops(), rank: form.rank, interval: form.interval, real: realOn,
    shortTops: form.shortTops, longTops: form.longTops, cutloss: form.cutloss, timeLimit: form.timeLimit,
  };
  try {
    await window.bot.start(form.mode, params);
    runningReal = realOn;
  } catch (err) {
    $('run-error').textContent = err.message;
    return;
  }
  Object.assign(counts, { seen: 0, ok: 0, open: 0 });
  setCounts();
  $('share').hidden = true;
  const site = platform.name;
  $('cycle-info').textContent = `Menyiapkan ${site}…`;
  emptyCoins(`Menyiapkan ${site}…`);
  emptyFeed('Menunggu aktivitas pertama…');
  setState('running', 'Sedang memantau', `Menyiapkan ${site}…`);
  resetFlow(form.mode, `Menyiapkan ${site}…`);
}

function addFeed(item, ts) {
  const feed = $('feed');
  feed.querySelector('.idle')?.remove();
  // Baris yang sama berturut-turut (mis. "Menunggu hasil AI..." tiap 5 detik) digabung: waktu
  // diperbarui dan jumlahnya ditulis, supaya baris penting tidak tertimbun.
  const top = feed.firstElementChild;
  const topText = top?.querySelector('span');
  if (top && topText && topText.base === item.text && top.className === (item.css || '')) {
    const repeats = Number(topText.repeats || 1) + 1;
    topText.repeats = repeats;
    topText.textContent = `${item.text} (${repeats}×)`;
    top.querySelector('time').textContent = clock(ts);
    if (state === 'running') $('status-sub').textContent = item.text;
    return;
  }
  feed.prepend(el('li', { class: item.css || '' }, el('i'),
    el('div', {}, el('span', { textContent: item.text, base: item.text }), el('time', { textContent: clock(ts) }))));
  while (feed.childElementCount > MAX_FEED) feed.lastElementChild.remove();
  if (state === 'running') $('status-sub').textContent = item.text;
}

function dips(count) {
  if (count === null || count === undefined) return el('span', { class: 'dips', textContent: '–' });
  const blocks = [0, 1, 2].map((i) => el('i', { class: i < count ? 'on' : '' }));
  return el('span', { class: 'dips' }, ...blocks, el('span', { textContent: `${count}×` }));
}

/** Baris sementara selama AI membaca grafik koin ini; diganti hasilnya oleh addCoin. */
function addPending(e) {
  $('coins').querySelector('.empty-row')?.remove();
  $('coins').querySelector(`tr[data-pending="${CSS.escape(e.symbol)}"]`)?.remove();
  const row = el('tr', { class: 'pending-row' },
    el('td', { class: 'rank' }, e.rank ? el('span', { class: 'rank-badge', textContent: String(e.rank) }) : null),
    el('td', { class: 'sym', textContent: e.symbol }),
    el('td', {}, el('span', { class: 'dips', textContent: '…' })),
    el('td', {}, el('span', { class: 'tag reading', textContent: 'AI membaca…' })),
    el('td', { class: 'why' },
      el('strong', { class: 'act', textContent: 'Menunggu hasil AI' }),
      el('span', { textContent: 'Grafik 15 menit yang sedang dibaca:' }),
      chartThumb(e.chart, `${e.symbol} · sedang dibaca`)));
  row.dataset.pending = e.symbol;
  $('coins').append(row);
}

function addCoin(e) {
  $('coins').querySelector(`tr[data-pending="${CSS.escape(e.symbol)}"]`)?.remove();
  counts.seen += 1;
  if (ENTER_VERDICTS.includes(e.verdict)) counts.ok += 1;
  if (e.status === 'open') counts.open += 1;
  setCounts();

  const [label, css] = VERDICT[e.verdict] || ['Tidak dibaca', ''];
  const act = actionOf(e);
  $('coins').querySelector('.empty-row')?.remove();
  $('coins').append(el('tr', {},
    el('td', { class: 'rank' }, el('span', { class: 'rank-badge', textContent: e.rank ? String(e.rank) : '↻', title: e.rank ? '' : 'Dicek ulang setelah terjual (lewat pencarian)' })),
    el('td', { class: 'sym', textContent: e.symbol }),
    el('td', {}, dips(e.count_ai ?? e.count_data)),
    el('td', {}, el('span', { class: `tag ${css}`, textContent: label })),
    el('td', { class: 'why' },
      el('strong', { class: `act ${act.css}`, textContent: act.text }),
      el('span', { textContent: act.note }),
      e.summary ? el('small', { textContent: `AI: ${e.summary}` }) : null,
      chartThumb(e.chart, `${e.symbol} · ${label}`),
      whyButton(e))));
}

// --------------------------------------------------------------------------- kartu "kenapa"

const STEP_MARK = { pass: '✓', fail: '✕', hold: '!', skip: '–', info: 'i' };
let cardReturnFocus = null;

/** Tombol "Kenapa?" yang membuka kartu alasan keputusan untuk satu koin. */
function whyButton(e, label = 'Lihat alasan lengkap') {
  const button = el('button', { type: 'button', class: 'secondary small why-link', textContent: label });
  button.addEventListener('click', () => openCard(e, button));
  return button;
}

function explainCoin(e) {
  return window.Reasons.explain(e, {
    platform: platform?.id,
    plain,
    statusLabel: (status) => (STATUS[status] || [status])[0],
  });
}

function cardSteps(card) {
  return card.steps.map((s) => el('li', { class: s.state },
    el('span', { class: 'cc-mark', textContent: STEP_MARK[s.state] || '' }),
    el('div', {},
      el('b', { textContent: s.title }),
      s.text ? el('span', { class: 't', textContent: s.text }) : null,
      s.details?.length ? el('ul', {}, ...s.details.map((line) => el('li', { textContent: line }))) : null)));
}

function cardAi(card) {
  if (!card.summary && !card.votes.length) return [];
  return [
    el('h3', { textContent: 'Pembacaan AI' }),
    card.summary ? el('p', { textContent: card.summary }) : null,
    card.votes.length
      ? el('div', { class: 'cc-votes', title: 'Tiap AI membaca grafik yang sama; hasil akhir = nilai tengah' },
        ...card.votes.map((v) => el('span', {
          class: `cc-vote${v.recent ? ' recent' : ''}`,
          textContent: `${v.count}×`,
        })))
      : null,
    card.votes.length ? el('small', { class: 'cc-legend', textContent: 'Tiap kotak = satu bacaan AI (berapa kali garis turun). Oranye = garis juga di bawah dalam 6 jam terakhir.' }) : null,
  ];
}

function openCard(e, returnTo = null) {
  const card = explainCoin(e);
  const [label, css] = VERDICT[e.verdict] || ['Tidak dibaca', ''];
  const when = e.created_at
    ? ` · ${new Date(e.created_at * 1000).toLocaleString('id-ID', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })}`
    : '';
  $('cc-title').replaceChildren(el('span', { textContent: e.symbol }), el('span', { class: `tag ${css}`, textContent: label }));
  $('cc-meta').textContent = `${e.rank ? `Top ${e.rank}` : 'Koin'} · ${platform?.name || 'Binance'}${when}`;
  $('cc-verdict').className = `cc-verdict ${card.tone}`;
  $('cc-headline').textContent = card.headline;
  $('cc-because').textContent = card.because;
  $('cc-steps').replaceChildren(...cardSteps(card));
  $('cc-chart').replaceChildren(chartThumb(e.chart, `${e.symbol} · ${label}`)
    || el('span', { class: 'chart-thumb none', textContent: 'Tanpa grafik' }));
  $('cc-ai').className = 'cc-ai';
  $('cc-ai').replaceChildren(...cardAi(card).filter(Boolean));
  cardReturnFocus = returnTo;
  $('coin-card').hidden = false;
  $('cc-close').focus();
}

function closeCard() {
  $('coin-card').hidden = true;
  cardReturnFocus?.focus?.();
  cardReturnFocus = null;
}
$('cc-close').addEventListener('click', closeCard);
$('coin-card').addEventListener('click', (event) => { if (event.target === $('coin-card')) closeCard(); });
document.addEventListener('keydown', (event) => { if (event.key === 'Escape' && !$('coin-card').hidden) closeCard(); });

/** Screenshot grafik 15 menit yang dibaca AI; klik untuk memperbesar. Kosong bila tidak ada. */
function chartThumb(file, caption) {
  if (!file) return null;
  const img = el('img', { class: 'chart-thumb', alt: `Grafik 15 menit ${caption}` });
  img.title = 'Klik untuk memperbesar';
  img.addEventListener('click', () => img.classList.toggle('big'));
  window.bot.chartImage(file).then((src) => { img.src = src; }).catch(() => img.remove());
  return img;
}

/** Akibat keputusan AI untuk satu koin (kolom Tindakan). */
function actionOf(e) {
  if (e.status === 'open') {
    const cut = e.cutloss_price ? `cutloss di ${price(e.cutloss_price)}` : 'tanpa stop-loss';
    return { text: `${sideOf(e)} ${e.real ? 'sungguhan' : 'uji kertas'} dibuka`, css: 'pos', note: `Masuk ${price(e.entry_price)} · jual otomatis di ${price(e.target_price)} · ${cut}` };
  }
  if (e.status === 'analyzed') {
    return ENTER_VERDICTS.includes(e.verdict)
      ? { text: `Pengikut boleh ${e.verdict === 'long' ? 'long' : 'short'} (uji)`, css: 'pos', note: 'Hasil dibagikan; pengikut mengecek biaya lalu membuka posisi uji.' }
      : { text: 'Tidak ada tindakan', css: '', note: 'Hasil dibagikan; pengikut tidak masuk koin ini.' };
  }
  if (['tunggu', 'jangan', 'konflik'].includes(e.verdict)) {
    return { text: 'Tidak ada tindakan', css: '', note: plain(e.reason) };
  }
  if (ENTER_VERDICTS.includes(e.verdict)) return { text: 'Batal masuk', css: 'warn', note: plain(e.reason) };
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
    setFlow(0, `Membuka daftar top gainers Futures di ${platform?.name || 'Binance'}`);
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
    if (['OK', 'LONG'].includes(leaderSays[3])) {
      setFlow(1, `Pemimpin: ${leaderSays[2]} layak ${leaderSays[3] === 'LONG' ? 'long' : 'short'} · membuka koin yang sama`);
    }
    else setFlow(FLOW.follower.length, `Pemimpin: ${leaderSays[2]} ${leaderSays[3].toLowerCase()} · tidak ada tindakan`, true);
    return;
  }
  const opened = m.match(/^Top gainer #(\d+): (\S+)/);
  if (opened && follower) {
    setFlow(2, `Top ${opened[1]}: ${opened[2]} · cek spread dan slot posisi`);
    return;
  }
  if (opened) {
    flow.symbol = opened[2];
    setFlow(1, leader ? `Top ${opened[1]}: ${opened[2]} · membuka grafik 15 menit`
      : `Top ${opened[1]}: ${opened[2]} · cek spread dan slot posisi`);
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
    emptyCoins(flow.mode === 'follower' ? 'Menunggu hasil AI dari pemimpin…' : 'Membaca top gainers…');
    $('cycle-info').textContent = `Dimulai ${clock(entry.ts || Date.now() / 1000)}`;
  }
  if (e?.type === 'view' && e.target === 'app' && e.symbol) addPending(e);
  if (e?.type === 'coin') addCoin(e);
  if (e?.type === 'hub') $('share').hidden = false;
  advanceFlow(entry);
  if (e?.type === 'cycle' && e.phase === 'done') {
    $('cycle-info').textContent = `Selesai ${clock(entry.ts || Date.now() / 1000)}`;
    if ($('coins').querySelector('.empty-row')) emptyCoins('Tidak ada koin yang bisa dinilai di putaran ini.');
  }
  // Detak pengawasan uang sungguhan (tiap menit): tampil di kartu Status sebagai tanda masih hidup,
  // tanpa memenuhi daftar aktivitas. Menggantikan pesan kegagalan sesaat yang sudah lewat.
  const watching = String(entry.message || '').match(/^Mengawasi (\d+) posisi uang sungguhan/);
  if (watching && state === 'running') {
    $('status-sub').textContent = `Mengawasi ${watching[1]} posisi uang sungguhan, harga dicek tiap menit · terakhir ${clock(entry.ts || Date.now() / 1000)}`;
  }
  const item = activity(entry);
  if (item) {
    addFeed(item, entry.ts || Date.now() / 1000);
    // Laptop lain (mis. pemimpin) bisa melihat aktivitas terakhir laptop ini.
    const coin = e?.type === 'coin' ? `${e.symbol}|${e.verdict || ''}|${e.status}` : '';
    window.bot.reportActivity({ text: item.text, coin }).catch(() => {});
  }
});

window.bot.onExit(({ code, signal, stopped: requested }) => {
  // Diminta pengguna (Hentikan): di Windows keluar dengan kode 1, bukan 130.
  const stopped = Boolean(requested) || code === 130 || Boolean(signal);
  if (code === 0 && !requested) setState('stopped', 'Selesai', 'Putaran selesai. Rekap ada di Hasil uji.');
  else if (stopped) setState('stopped', 'Dihentikan', 'Bot berhenti atas permintaan.');
  else setState('stopped', 'Berhenti karena kendala', 'Buka Cek laptop lalu coba lagi.');
  const text = code === 0 && !requested ? 'Bot selesai' : stopped ? 'Bot dihentikan' : 'Bot berhenti karena kendala';
  addFeed({ text, css: code === 0 || stopped ? '' : 'bad' }, Date.now() / 1000);
  window.bot.reportActivity({ text }).catch(() => {});
  flow.nextAt = 0;
  if (!flow.done) setFlow(flow.step, text);
  tickFlow();
});

$('toggle').addEventListener('click', toggleRun);

// --------------------------------------------------------------------------- jam pasar dunia

const WORLD_AXIS = [0, 3, 6, 9, 12, 15, 18, 21];
const WORLD = { tiles: new Map(), key: '', lineKey: '' };

function worldTile(id, region, city, extra = '') {
  const time = el('span', { class: 'wc-time' });
  const day = el('span', { class: 'wc-day' });
  const state = el('span', { class: 'wc-state' });
  const note = el('span', { class: 'wc-note' });
  const node = el('div', { class: `wc ${extra}` }, el('span', { class: 'wc-region', textContent: region }),
    el('span', { class: 'wc-city', textContent: city }), time, day, state, note);
  WORLD.tiles.set(id, { node, time, day, state, note });
  return node;
}

function buildWorldClocks() {
  const clocks = window.WorldClock;
  $('world-clocks').replaceChildren(
    worldTile('home', 'Kamu', `${clocks.HOME.city} · ${clocks.HOME.label}`, 'home'),
    ...clocks.MARKETS.map((m) => worldTile(m.id, m.region, `${m.city} · ${m.exchange}`)));
}

function worldDay(date, tz) {
  return date.toLocaleDateString('id-ID', { timeZone: tz, weekday: 'short', day: 'numeric', month: 'short' });
}

/** Garis waktu 24 jam (WIB): sesi tiap bursa dan fase kripto, dengan penanda "sekarang". */
function renderWorldLine(date) {
  const clocks = window.WorldClock;
  const day = clocks.daySegments(date);
  const segments = (list, css) => list.map((s) => {
    const seg = el('i', { class: `wl-seg ${css(s)}` });
    seg.style.left = `${s.from * 100}%`;
    seg.style.width = `${(s.to - s.from) * 100}%`;
    return seg;
  });
  const row = (label, bars) => el('div', { class: 'wl-row' }, el('span', { class: 'wl-label', textContent: label }),
    el('div', { class: 'wl-track' }, ...bars));
  const level = Object.fromEntries(clocks.PHASES.map((p) => [p.id, p.level]));
  const axis = el('div', { class: 'wl-axis' }, ...WORLD_AXIS.map((h) => {
    const tick = el('span', { textContent: String(h).padStart(2, '0') });
    tick.style.left = `${(h / 24) * 100}%`;
    return tick;
  }));
  const now = el('i', { class: 'wl-now' });
  now.style.setProperty('--f', String(day.now));
  const legend = el('div', { class: 'wl-legend' },
    ...[['q5', 'Paling ramai'], ['q3', 'Naik / menurun'], ['q2', 'Sedang'], ['q1', 'Paling sepi']]
      .map(([css, text]) => el('span', {}, el('i', { class: css }), text)));
  $('world-line').replaceChildren(
    row('Kripto', segments(day.phases, (s) => `q${level[s.value]}`)),
    ...day.markets.map((m) => row(m.city, segments(m.open, () => ''))),
    axis, now, legend);
  WORLD.lineKey = `${day.startMs}`;
}

function updateWorld() {
  const clocks = window.WorldClock;
  if (!clocks || $('page-run').hidden) return;
  if (!WORLD.tiles.size) buildWorldClocks();
  const date = new Date();
  const home = WORLD.tiles.get('home');
  home.time.textContent = clocks.clockText(date, clocks.HOME.tz, { seconds: true });
  home.day.textContent = worldDay(date, clocks.HOME.tz);
  home.state.style.display = 'none'; // jam laptop sendiri: tanpa status bursa
  home.note.textContent = 'Jam di laptop ini';
  for (const m of clocks.MARKETS) {
    const tile = WORLD.tiles.get(m.id);
    const status = clocks.marketStatus(m, date);
    tile.time.textContent = clocks.clockText(date, m.tz, { seconds: true });
    tile.day.textContent = worldDay(date, m.tz);
    tile.state.className = `wc-state ${status.state}`;
    tile.state.textContent = status.state === 'buka' ? 'Buka' : status.state === 'istirahat' ? 'Istirahat' : 'Tutup';
    tile.note.textContent = status.note;
  }
  const phase = clocks.cryptoPhase(date);
  const tag = $('world-phase');
  tag.className = `tag q${phase.level}`;
  tag.textContent = `Kripto sekarang: ${phase.label}`;
  $('world-note').textContent = `${phase.range} · ${phase.note}.${phase.weekend ? ' Akhir pekan: umumnya lebih sepi dari biasa.' : ''} Hari libur bursa tidak dihitung.`;
  // Garis waktu dihitung ulang tiap menit (penanda "sekarang" bergerak) atau saat tanggal WIB berganti.
  const minuteKey = `${Math.floor(date.getTime() / 60000)}`;
  if (WORLD.key !== minuteKey) {
    WORLD.key = minuteKey;
    renderWorldLine(date);
  }
}
setInterval(updateWorld, 1000);
updateWorld();

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

/** Donat akhir posisi: target, likuidasi, Sell, masih berjalan (dan catatan lama V2). */
function donut(s) {
  const parts = [
    ['Target tercapai', s.targets, 'var(--green)'],
    ['Likuidasi', s.liquidations ?? 0, 'var(--red)'],
    ['Stop/waktu habis (catatan lama)', (s.stops ?? 0) + (s.timeouts ?? 0), 'var(--amber)'],
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

// --------------------------------------------------------------------------- filter waktu Hasil uji

// Satu filter untuk seluruh halaman (angka, grafik, donat, tabel, analisis AI), berlaku per
// tanggal masuk posisi. Pilihan diingat per laptop; kegagalan penyimpanan tidak masalah.
const RANGE_KEY = 'marketforge.range.v1';
const range = { preset: 'all', from: '', to: '' };

try {
  Object.assign(range, JSON.parse(localStorage.getItem(RANGE_KEY) || '{}'));
} catch { /* bawaan: Semua */ }
if (!['all', 'today', '7', '30', 'custom'].includes(range.preset)) range.preset = 'all';

const dayText = (date) => {
  const pad = (n) => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
};
const shiftDays = (days) => { const d = new Date(); d.setDate(d.getDate() + days); return dayText(d); };

/** Rentang tanggal {from, to} (YYYY-MM-DD, kedua ujung termasuk) dari pilihan sekarang. */
function activeRange() {
  switch (range.preset) {
    case 'today': return { from: shiftDays(0), to: shiftDays(0) };
    case '7': return { from: shiftDays(-6), to: shiftDays(0) };
    case '30': return { from: shiftDays(-29), to: shiftDays(0) };
    case 'custom': return { from: range.from || '', to: range.to || '' };
    default: return {};
  }
}

function renderRange() {
  for (const btn of $('range-presets').children) btn.classList.toggle('on', btn.dataset.range === range.preset);
  $('range-dates').hidden = range.preset !== 'custom';
  $('range-from').value = range.from;
  $('range-to').value = range.to;
  $('range-from').max = range.to || '';
  $('range-to').min = range.from || '';
}

const dayLabel = (text) => new Date(`${text}T00:00:00`).toLocaleDateString('id-ID', { day: 'numeric', month: 'short', year: 'numeric' });

function rangeNote(report) {
  const { from, to } = activeRange();
  if (!from && !to) return 'Menampilkan semua catatan.';
  const span = from && to ? (from === to ? dayLabel(from) : `${dayLabel(from)} – ${dayLabel(to)}`)
    : from ? `sejak ${dayLabel(from)}` : `sampai ${dayLabel(to)}`;
  return `Posisi yang masuk ${span} · ${report.stats.closed} selesai, ${report.stats.open} berjalan`;
}

function saveRange() {
  try { localStorage.setItem(RANGE_KEY, JSON.stringify(range)); } catch { /* tidak masalah */ }
}

$('range-presets').addEventListener('click', (ev) => {
  const value = ev.target.closest('button')?.dataset.range;
  if (!value) return;
  range.preset = value;
  if (value === 'custom' && !range.from && !range.to) { // mulai dari 7 hari terakhir
    range.from = shiftDays(-6);
    range.to = shiftDays(0);
  }
  saveRange();
  renderRange();
  loadJournal();
});
for (const [id, key] of [['range-from', 'from'], ['range-to', 'to']]) {
  $(id).addEventListener('change', () => {
    range[key] = $(id).value;
    saveRange();
    renderRange();
    loadJournal();
  });
}

async function loadJournal() {
  $('journal-refresh').disabled = true;
  renderRange();
  $('journal-check').hidden = platform?.id !== 'tebbit';
  const notice = $('journal-notice');
  try {
    const report = await window.bot.summary(activeRange());
    const s = report.stats;
    $('range-note').textContent = rangeNote(report);
    $('trades-note').textContent = activeRange().from || activeRange().to
      ? 'Semua posisi pada rentang waktu ini, terbaru di atas.' : 'Semua posisi, terbaru di atas.';
    notice.hidden = !report.warning;
    notice.className = 'notice';
    notice.textContent = platform?.id === 'tebbit'
      ? 'Posisi Tebbit dinilai dari harga di layar: otomatis tiap 5 menit saat bot berjalan, atau tekan Cek harga Tebbit.'
      : 'Data harga Binance belum bisa diambil di jaringan ini; angka di bawah dari catatan terakhir.';

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
      kpi('Perlu ditinjau', String(s.needs_review), 'posisi ditahan lebih dari 1 hari',
        { css: s.needs_review > 0 ? 'neg' : '' }),
    );

    // Grafik: 20 trade terakhir (dengan filter tanggal: semua dalam rentang itu).
    const ranged = activeRange().from || activeRange().to;
    $('pnl-chart').replaceChildren(pnlChart(ranged ? report.trades : report.trades.slice(-RECENT_CHART)));
    $('donut').replaceChildren(...donut(s));

    TRADES.all = [...report.trades].reverse(); // terbaru dulu
    TRADES.page = 1;
    renderTrades();
    HIST.all = [...(report.analyses || [])].reverse();
    HIST.total = report.analyses_total ?? HIST.all.length;
    HIST.page = 1;
    renderHistory();

  } catch (err) {
    notice.hidden = false;
    notice.className = 'notice bad';
    notice.textContent = err.message;
  } finally {
    $('journal-refresh').disabled = false;
  }
}
loaders.journal = loadJournal;

// Trade terakhir: semua trade dari engine (terbaru dulu), 20 per halaman, bisa disaring.
const TRADES = { all: [], page: 1 };
const RECENT_CHART = 20; // batang grafik Hasil per trade tanpa filter tanggal

function tradesFilter() {
  return {
    search: $('trades-search').value, side: $('trades-side').value,
    status: $('trades-status').value, kind: $('trades-kind').value,
  };
}

function tradeRow(t) {
  const [label, css] = STATUS[t.status] || [t.status, ''];
  return el('tr', {},
    el('td', { textContent: new Date(t.created_at * 1000).toLocaleString('id-ID', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) }),
    el('td', {}, el('strong', { class: 'sym', textContent: t.symbol }),
      el('span', { class: `side-tag ${t.side === 'long' ? 'long' : 'short'}`, textContent: sideOf(t) }),
      t.real ? el('span', { class: 'badge-real', textContent: 'Uang sungguhan' }) : null),
    el('td', { textContent: ROLE_NAME[t.role] || 'Sendiri' }),
    el('td', {}, el('span', { class: `tag ${css}`, textContent: label })),
    el('td', { class: 'num', textContent: price(t.entry_price) }),
    el('td', { class: 'num', textContent: price(t.exit_price) }),
    // Hasil dalam USDT (seperti PNL Terealisasi di Binance) dan persen modal di bawahnya.
    el('td', { class: `num ${signClass(t.pnl_usdt ?? t.pnl_capital_pct)}` },
      typeof t.pnl_usdt === 'number' ? usdtText(t.pnl_usdt) : percent(t.pnl_capital_pct),
      typeof t.pnl_usdt === 'number' && typeof t.pnl_capital_pct === 'number'
        ? el('small', { class: 'price-age', textContent: `${percent(t.pnl_capital_pct)} modal` }) : null));
}

function renderTrades() {
  const { filterTrades, pageSlice, pageCount, countText, TRADE_PAGE } = window.History;
  const filter = tradesFilter();
  const filtered = Boolean(filter.search.trim() || filter.side || filter.status || filter.kind);
  const matched = filterTrades(TRADES.all, filter);
  const { page, items } = pageSlice(matched, TRADES.page, TRADE_PAGE);
  TRADES.page = page;
  let empty = 'Belum ada posisi. Mulai memantau untuk mengisi catatan.';
  if (filtered) empty = 'Tidak ada trade yang cocok. Ubah pencarian atau saringan.';
  else if (activeRange().from || activeRange().to) empty = 'Tidak ada posisi pada rentang waktu ini. Ubah filter waktu di atas.';
  $('trades').replaceChildren(...(matched.length
    ? items.map(tradeRow)
    : [el('tr', { class: 'empty-row' }, el('td', { colSpan: 7, textContent: empty }))]));
  $('trades-count').textContent = countText(page, matched.length, TRADES.all.length, filtered, TRADE_PAGE, 'trade');
  renderPager($('trades-pager'), page, pageCount(matched.length, TRADE_PAGE), (n) => {
    TRADES.page = n;
    renderTrades();
    $('trades-search').closest('.card').scrollIntoView({ block: 'start', behavior: 'smooth' });
  });
}

$('trades-search').addEventListener('input', () => { TRADES.page = 1; renderTrades(); });
for (const id of ['trades-side', 'trades-status', 'trades-kind']) {
  $(id).addEventListener('change', () => { TRADES.page = 1; renderTrades(); });
}

// Riwayat analisis AI: semua yang dikirim engine (terbaru dulu), 30 per halaman, bisa disaring.
const HIST = { all: [], total: 0, page: 1 };

function historyFilter() {
  return { search: $('history-search').value, verdict: $('history-verdict').value };
}

function renderHistory() {
  const { filterAnalyses, pageSlice, pageCount, countText } = window.History;
  const filter = historyFilter();
  const filtered = Boolean(filter.search.trim() || filter.verdict);
  const matched = filterAnalyses(HIST.all, filter);
  const { page, items } = pageSlice(matched, HIST.page);
  HIST.page = page;
  let empty = 'Belum ada koin yang dinilai AI di platform ini.';
  if (filtered) empty = 'Tidak ada analisis yang cocok. Ubah pencarian atau saringan keputusan.';
  else if (activeRange().from || activeRange().to) empty = 'Tidak ada koin yang dinilai AI pada rentang waktu ini.';
  $('analyses').replaceChildren(...(matched.length
    ? items.map(analysisItem)
    : [el('li', { class: 'idle', textContent: empty })]));
  let note = countText(page, matched.length, HIST.all.length, filtered);
  if (HIST.total > HIST.all.length) {
    note += ` (${HIST.all.length} terbaru dari ${HIST.total}; pakai filter tanggal untuk yang lebih lama)`;
  }
  $('history-count').textContent = note;
  renderPager($('history-pager'), page, pageCount(matched.length), (n) => {
    HIST.page = n;
    renderHistory();
    $('history-search').closest('.card').scrollIntoView({ block: 'start', behavior: 'smooth' });
  });
}

/** Navigasi halaman: < 1 2 3 4 5 … 12 >. Tersembunyi bila hanya satu halaman. */
function renderPager(pager, page, pages, go) {
  pager.hidden = pages <= 1;
  if (pager.hidden) { pager.replaceChildren(); return; }
  const arrow = (label, n, disabled, path) => {
    const b = el('button', { type: 'button', class: 'pg-arrow', title: label, disabled },
      svg('svg', { viewBox: '0 0 24 24', 'aria-hidden': 'true' }, svg('path', { d: path })));
    b.setAttribute('aria-label', label);
    b.addEventListener('click', () => go(n));
    return b;
  };
  pager.replaceChildren(
    arrow('Halaman sebelumnya', page - 1, page === 1, 'M15 6l-6 6 6 6'),
    ...window.History.pageItems(page, pages).map((n) => {
      if (n === '…') return el('span', { class: 'pg-gap', textContent: '…' });
      const b = el('button', { type: 'button', class: n === page ? 'pg-num on' : 'pg-num', textContent: String(n) });
      if (n === page) b.setAttribute('aria-current', 'page');
      b.addEventListener('click', () => go(n));
      return b;
    }),
    arrow('Halaman berikutnya', page + 1, page === pages, 'M9 6l6 6-6 6'));
}

$('history-search').addEventListener('input', () => { HIST.page = 1; renderHistory(); });
$('history-verdict').addEventListener('change', () => { HIST.page = 1; renderHistory(); });

/** Satu hasil analisis di riwayat: grafik, status, alasan singkat, dan ringkasan AI. */
function analysisItem(a) {
  const [label, css] = VERDICT[a.verdict] || ['Tidak dibaca', ''];
  const when = new Date(a.created_at * 1000).toLocaleString('id-ID', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
  const example = a.status === 'contoh';
  const opened = `${sideOf(a)} ${a.real ? 'sungguhan' : 'uji kertas'} dibuka`;
  const action = example ? a.reason : a.status === 'open' || STATUS[a.status] ? opened : plain(a.reason);
  const where = example ? 'Gambar contoh' : `${a.rank ? `Top ${a.rank}` : 'Dicek ulang setelah terjual'} · ${ROLE_NAME[a.role] || 'Sendiri'}`;
  return el('li', { class: 'hist-item' },
    chartThumb(a.chart, `${a.symbol} · ${label}`) || el('span', { class: 'chart-thumb none', textContent: 'Tanpa grafik' }),
    el('div', {},
      el('div', { class: 'hist-head' },
        el('strong', { class: 'sym', textContent: a.symbol }),
        el('span', { class: `tag ${css}`, textContent: label }),
        el('span', { class: 'hist-meta', textContent: `${where} · ${when}` })),
      a.old_rule ? el('p', { class: 'hist-old', textContent: 'Dinilai dengan aturan lama (tanpa syarat 6 jam terakhir). Dengan aturan sekarang hasilnya bisa berbeda.' }) : null,
      el('p', { class: 'hist-act', textContent: action }),
      a.summary ? el('small', { textContent: `AI: ${a.summary}` }) : null,
      el('div', { class: 'hist-actions' }, a.status === 'contoh' ? null : whyButton(a, 'Detail'), historyDelete(a))));
}

const NOT_TRADES = ['skipped', 'contoh'];

/** Tombol hapus satu riwayat. Menghapus posisi uji juga menghapusnya dari hasil uji. */
function historyDelete(a) {
  const button = el('button', { type: 'button', class: 'secondary small hist-del', textContent: 'Hapus' });
  button.addEventListener('click', async () => {
    const trade = !NOT_TRADES.includes(a.status);
    const ask = trade
      ? `Hapus ${a.symbol}? Ini posisi uji: ikut terhapus dari hasil uji (50 trade).`
      : `Hapus riwayat ${a.symbol}?`;
    if (!window.confirm(ask)) return;
    await editHistory(() => window.bot.history.remove(a.id));
  });
  return button;
}

async function editHistory(action) {
  const notice = $('journal-notice');
  try {
    await action();
    await loadJournal();
  } catch (err) {
    notice.hidden = false;
    notice.className = 'notice bad';
    notice.textContent = err.message;
  }
}

$('history-clear').addEventListener('click', async () => {
  if (!window.confirm('Bersihkan riwayat? Koin yang dilewati dan gambar contoh dihapus; posisi uji tetap ada.')) return;
  await editHistory(() => window.bot.history.clear());
});
$('journal-refresh').addEventListener('click', loadJournal);
$('journal-check').addEventListener('click', async () => {
  const button = $('journal-check');
  button.disabled = true;
  button.textContent = 'Membaca harga…';
  try {
    await window.bot.positions.check();
  } catch (err) {
    $('journal-notice').hidden = false;
    $('journal-notice').textContent = err.message;
  } finally {
    button.disabled = false;
    button.textContent = 'Cek harga Tebbit';
  }
  await loadJournal();
});

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
      ? `Tutup posisi uji kertas kapan saja. Tombol ${platform?.name || 'Binance'} tidak ditekan.`
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

let ownRealOpen = false; // ada posisi uang sungguhan di daftar (Sell semua ikut menekan Market)

/** Usia harga yang tersimpan ("dicek 3 menit lalu"); kosong bila harga baru dibaca. */
function priceAge(p) {
  if (!p.price_stale || !p.price_at) return null;
  const minutes = Math.max(0, Math.round((Date.now() / 1000 - p.price_at) / 60));
  const text = minutes < 1 ? 'dicek barusan' : minutes < 60 ? `dicek ${minutes} mnt lalu` : `dicek ${Math.round(minutes / 60)} jam lalu`;
  return el('small', { class: 'price-age', textContent: text });
}

$('pos-check').addEventListener('click', async () => {
  const button = $('pos-check');
  button.disabled = true;
  button.textContent = 'Membaca harga…';
  try {
    await window.bot.positions.check();
  } catch (err) {
    posNotice(err.message, 'bad');
  } finally {
    button.disabled = false;
    button.textContent = 'Cek harga Tebbit';
  }
  await loadPositions();
});

async function loadOwnPositions(canSell) {
  renderOwnPositions(await window.bot.positions.list(), canSell);
}

let ownCanSell = false;
function renderOwnPositions(result, canSell = ownCanSell) {
  ownCanSell = canSell;
  const missingSet = new Set(healthState.missing || []);
  posNotice(result.warning ? `Harga ${platform?.name || 'Binance'} belum bisa diambil; hasil sementara tidak tampil.` : '', 'warn');
  $('pos-close-all').disabled = !result.positions.length;
  ownRealOpen = result.positions.some((p) => p.real);
  const tebbit = platform?.id === 'tebbit';
  $('pos-check').hidden = !tebbit;
  if (tebbit && !result.warning && result.positions.some((p) => p.price === null || p.price === undefined)) {
    posNotice('Harga Tebbit dibaca dari layar: tekan Cek harga Tebbit, atau jalankan bot (otomatis tiap 5 menit).', 'warn');
  }
  const rows = result.positions.map((p) => el('tr', {},
    el('td', {}, el('strong', { class: 'sym', textContent: p.symbol }),
      el('span', { class: `side-tag ${p.side === 'long' ? 'long' : 'short'}`, textContent: sideOf(p) }),
      p.real ? el('span', { class: 'badge-real', textContent: 'Uang sungguhan' }) : null,
      el('small', { class: 'sub-role', textContent: ROLE_NAME[p.role] || 'Sendiri' })),
    el('td', { class: 'num', textContent: price(p.entry_price) }),
    el('td', { class: 'num' }, price(p.price), priceAge(p) || (p.price_at ? el('small', { class: 'price-age', textContent: `dicek ${clock(p.price_at)}` }) : null)),
    el('td', { class: `num ${signClass(p.pnl_capital_pct)}` }, p.pnl_capital_pct === null || p.pnl_capital_pct === undefined ? '–' : `${percent(p.pnl_capital_pct)} modal`,
      typeof p.pnl_usdt === 'number' ? el('small', { class: 'price-age', textContent: usdtText(p.pnl_usdt) }) : null),
    el('td', { class: 'num' }, typeof p.worst_pnl_pct === 'number' && p.worst_pnl_pct < 0 ? `-${pctText(p.worst_pnl_pct)}` : '–'),
    el('td', { class: 'num' }, price(p.target_price), el('small', { class: 'price-age', textContent: targetText(p) }),
      exitLimits(p) ? el('small', { class: 'price-age', textContent: exitLimits(p) }) : null),
    el('td', { class: 'num actions' },
      missingSet.has(p.symbol) ? el('small', { class: 'gone-note', textContent: 'Tidak ada lagi di Binance' }) : null,
      p.real && canSell ? el('button', { class: 'secondary small', textContent: 'Tutup manual?', title: 'Catat posisi yang sudah kamu tutup sendiri di bursa', onclick: () => askManual(p.symbol) }) : null,
      canSell
        ? el('button', { class: 'sell', textContent: 'Sell', onclick: () => sellOwn(p.symbol, p.real === true) })
        : el('span', { class: 'locked', textContent: 'Ditutup pemimpin' }))));
  $('pos-table').replaceChildren(...(rows.length ? rows
    : [el('tr', { class: 'empty-row' }, el('td', { colSpan: 7, textContent: 'Tidak ada posisi yang terbuka.' }))]));
}

async function sellOwn(symbol, real = false) {
  const label = symbol === 'semua' ? 'semua posisi' : `posisi ${symbol}`;
  const site = platform?.name || 'Binance';
  const question = real
    ? `Tutup ${label} SUNGGUHAN? Bot membuka ${site} dan menekan Market di tab Posisi (uang sungguhan).`
    : `Tutup ${label}? (uji kertas, tombol ${site} tidak ditekan)`;
  if (!window.confirm(question)) return;
  if (real) posNotice(`Menutup posisi di ${site}… jangan pakai mouse.`, '');
  try {
    const result = await window.bot.positions.close(symbol, real);
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
  if (!window.confirm(`Tutup ${label}? Pengikut menutupnya sendiri (uji kertas, tombol ${platform?.name || 'Binance'} tidak ditekan).`)) return;
  try {
    await window.bot.team.close(target, symbol);
    posNotice('Perintah Sell dikirim. Pengikut menutup posisinya dalam beberapa detik.', 'good');
    setTimeout(() => { if (!$('page-positions').hidden) loadPositions(); }, 8000);
  } catch (err) {
    posNotice(err.message, 'bad');
  }
}

// --------------------------------------------------------------------------- kesehatan dan posisi berjalan

const LOSS_KEY = 'marketforge.lossLimit.v1';
let healthState = { warnings: [], missing: [] };
let livePositions = [];

const usdtText = (v) => (typeof v === 'number' ? `${v > 0 ? '+' : ''}${v.toFixed(2).replace('.', ',')} USDT` : '–');
const pctText = (v) => (typeof v === 'number' ? `${Math.abs(v).toFixed(1).replace('.', ',')}%` : '–');

/** Peringatan laptop di atas halaman Pantau; baris "aman" hanya saat ada yang dipantau. */
function renderHealth() {
  const box = $('health');
  const h = healthState;
  const items = (h.warnings || []).map((w) => el('div', { class: `health-item ${w.level}` },
    el('i', { 'aria-hidden': 'true' }), el('span', { textContent: w.text })));
  if (!items.length && (h.running || livePositions.length)) {
    const site = platform?.name || 'Binance';
    const parts = [h.network === 'ok' ? `Jaringan ${site} aman` : null, h.onBattery ? null : 'charger terpasang',
      h.keepAwake ? 'laptop dan layar dijaga tetap menyala selama bot berjalan' : null].filter(Boolean);
    if (parts.length) items.push(el('div', { class: 'health-item ok' }, el('i', { 'aria-hidden': 'true' }), el('span', { textContent: `${parts.join(' · ')}.` })));
  }
  box.replaceChildren(...items);
  box.hidden = !items.length;
}

/** Jarak harga sekarang ke harga jual otomatis, dalam kalimat. */
function targetText(p) {
  if (typeof p.to_target_pct !== 'number') return '';
  const move = p.side === 'long' ? 'naik' : 'turun';
  return p.to_target_pct <= 0 ? 'sudah di target' : `${move} ${pctText(p.to_target_pct)} lagi`;
}

/** Cutloss dan batas waktu posisi ini (kosong bila keduanya mati). */
function exitLimits(p) {
  const parts = [];
  if (p.cutloss_price) parts.push(`cutloss ${price(p.cutloss_price)}`);
  if (p.time_exit_at) parts.push(`paling lama ${clock(p.time_exit_at)}`);
  return parts.join(' · ');
}

/** Ringkasan posisi di Pantau (uang sungguhan dulu): satu baris per koin, detail di Posisi. */
function renderLive() {
  const list = [...livePositions].sort((a, b) => Number(Boolean(b.real)) - Number(Boolean(a.real)));
  $('live').hidden = !list.length;
  const missingSet = new Set(healthState.missing || []);
  $('live-list').replaceChildren(...list.map((p) => {
    const gone = missingSet.has(p.symbol);
    const note = gone ? 'Tidak ada lagi di Binance: catat di Posisi' : targetText(p) ? `Target: ${targetText(p)}` : '';
    return el('button', { type: 'button', class: `live-row ${gone ? 'gone' : ''}`, title: 'Buka di halaman Posisi', onclick: () => showPage('positions') },
      el('strong', { class: 'sym', textContent: p.symbol }),
      el('span', { class: p.real ? 'badge-real' : 'badge-paper', textContent: p.real ? 'Uang sungguhan' : 'Uji kertas' }),
      el('strong', { class: `live-pnl ${signClass(p.pnl_usdt)}`, textContent: usdtText(p.pnl_usdt) }),
      el('span', { class: 'live-note', textContent: note }));
  }));
}

function applyHealth(h) {
  if (!h) return;
  healthState = h;
  renderHealth();
  renderLive();
}

function applyPositions(positions) {
  if (!Array.isArray(positions)) return;
  livePositions = positions;
  renderLive();
  renderHealth();
}

function setupLossLimit() {
  let saved = '0';
  try { saved = localStorage.getItem(LOSS_KEY) || '0'; } catch { /* default */ }
  const select = $('loss-limit');
  select.value = saved;
  window.bot.health.setLossLimit(Number(saved)).catch(() => {});
  select.addEventListener('change', () => {
    try { localStorage.setItem(LOSS_KEY, select.value); } catch { /* tidak diingat */ }
    window.bot.health.setLossLimit(Number(select.value)).catch(() => {});
  });
}

/** Dialog catat tutup manual (posisi yang sudah ditutup sendiri di bursa). */
let manualSymbol = null;
function askManual(symbol) {
  manualSymbol = symbol;
  $('manual-title').textContent = `${symbol} sudah ditutup di ${platform?.name || 'Binance'}?`;
  $('manual-price').value = '';
  $('manual-pnl').value = '';
  $('manual-error').textContent = '';
  $('manual-dialog').hidden = false;
  $('manual-price').focus();
}
$('manual-cancel').addEventListener('click', () => { $('manual-dialog').hidden = true; });
$('manual-save').addEventListener('click', async () => {
  const button = $('manual-save');
  button.disabled = true;
  try {
    const result = await window.bot.positions.recordManual(manualSymbol, $('manual-price').value, $('manual-pnl').value);
    $('manual-dialog').hidden = true;
    const c = result.closed?.[0];
    window.bot.reportActivity({ text: c ? `Tutup manual dicatat: ${c.symbol}` : 'Tutup manual dicatat' }).catch(() => {});
    if (!$('page-positions').hidden) {
      await loadPositions();
      posNotice(c ? `${c.symbol} dicatat ditutup manual (${percent(c.pnl_capital_pct)} modal).` : 'Dicatat.', 'good');
    }
  } catch (err) {
    $('manual-error').textContent = err.message;
  } finally {
    button.disabled = false;
  }
});

$('live-open').addEventListener('click', () => showPage('positions'));
window.bot.health.onChanged(applyHealth);
window.bot.health.get().then(applyHealth).catch(() => {});
window.bot.positions.cached().then(applyPositions).catch(() => {});
setupLossLimit();

$('pos-refresh').addEventListener('click', loadPositions);
$('pos-close-all').addEventListener('click', () => {
  if (currentRole() === 'leader') sellTeam('*', '*', 'semua posisi semua pengikut');
  else sellOwn('semua', ownRealOpen);
});
window.bot.positions.onChanged((payload) => {
  if (payload?.positions) {
    // Penyegaran tiap menit: gambar ulang dari data yang sudah dibaca (tanpa menjalankan engine lagi).
    applyPositions(payload.positions);
    if (!$('page-positions').hidden && !$('pos-own').hidden) {
      renderOwnPositions({ warning: null, positions: payload.positions });
    }
    return;
  }
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
const leaderTops = watchedTops;

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
    $('group-sub').textContent = `Bot mulai otomatis setiap pemimpin memulai putaran (modal ${modalText(member.modal)}).`;
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
  const kind = balanceModal(form.modal);
  $('invite-modal').value = kind ? BALANCE_LABEL[kind] : form.modal; // ketik angka, 50%, atau Max
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
window.bot.team.onStarted(({ leaderName, rank, exchange, real }) => {
  runningReal = real === true;
  Object.assign(counts, { seen: 0, ok: 0, open: 0 });
  setCounts();
  // Tampilan pengikut berpindah ke platform pemimpin (jurnal dan posisi dibaca dari platform itu).
  if (exchange && exchange !== platform?.id) choosePlatform(exchange);
  emptyCoins(`Menyiapkan ${platform?.name || 'Binance'}…`);
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
window.bot.status().then(({ running, exchange }) => {
  if (running) {
    setState('running', 'Sedang memantau', 'Bot sedang bekerja.');
    choosePlatform(exchange || 'binance'); // bot sudah berjalan: langsung ke dashboard
  }
});

// --------------------------------------------------------------------------- pilih platform


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

// Tampilan putaran per platform (koin, aktivitas, angka, status, alur): Binance dan Tebbit tidak
// saling menimpa saat platform diganti. Hanya di memori; riwayat AI tetap di jurnal masing-masing.
const views = new Map();

function saveView(id) {
  views.set(id, {
    coins: [...$('coins').childNodes],
    feed: [...$('feed').childNodes],
    counts: { ...counts },
    cycle: $('cycle-info').textContent,
    status: [$('status-title').textContent, $('status-sub').textContent],
    flow: { ...flow, sub: $('flow-sub').textContent },
  });
}

function restoreView(id) {
  const view = views.get(id);
  if (!view) {
    Object.assign(counts, { seen: 0, ok: 0, open: 0 });
    setCounts();
    emptyCoins('Belum ada koin yang dinilai. Tekan Mulai memantau.');
    emptyFeed('Aktivitas bot akan muncul di sini.');
    $('cycle-info').textContent = 'Belum ada putaran.';
    $('status-title').textContent = 'Belum berjalan';
    $('status-sub').textContent = 'Tekan Mulai memantau.';
    resetFlow(form.mode, 'Belum berjalan. Tekan Mulai memantau.');
    return;
  }
  $('coins').replaceChildren(...view.coins);
  $('feed').replaceChildren(...view.feed);
  Object.assign(counts, view.counts);
  setCounts();
  $('cycle-info').textContent = view.cycle;
  [$('status-title').textContent, $('status-sub').textContent] = view.status;
  const { sub: flowSub, ...rest } = view.flow;
  Object.assign(flow, rest);
  setFlow(rest.step, flowSub, rest.done);
}

function choosePlatform(id) {
  const chosen = PLATFORMS.find((p) => p.id === id);
  if (!chosen?.ready) return; // bursa yang belum siap tidak pernah menjadi platform aktif
  if (platform && platform.id !== chosen.id) {
    saveView(platform.id);
    restoreView(chosen.id);
  }
  platform = chosen;
  window.bot.setPlatform(chosen.id).catch(() => {});
  $('platform-name').textContent = chosen.name;
  $('platform-logo').src = chosen.logo;
  $('platform-logo').parentElement.className = `plat-logo ${chosen.id}`;
  renderReal(); // Real Fund Trading hanya untuk Binance
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

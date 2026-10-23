'use strict';

// Proses utama Electron: jendela, IPC, dan satu proses engine. Isian dari tampilan divalidasi
// di engine.js sebelum menjadi argumen CLI. Tidak ada kontrol untuk order sungguhan.

const { app, BrowserWindow, Notification, ipcMain, net, powerMonitor, powerSaveBlocker } = require('electron');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { pathToFileURL } = require('node:url');

const alerts = require('./alerts');
const engine = require('./engine');
const {
  COIN, Discovery, MAX_ACTIVITY, localAddress, primaryAddress, sealedFields,
} = require('./discovery');
const { loadLeaderKey, loadLeaderPublic, sealForLeader } = require('./leaderkey');
const { Team, normalizeRank } = require('./team');

const PAGE = path.join(__dirname, 'renderer', 'index.html');
const ICON = path.join(__dirname, 'assets', 'icon.png'); // logo MarketForge (dari app_icon_adaptive)
const PAGE_URL = pathToFileURL(PAGE).href;

const { BRAND, BUNDLE_ID } = require('./brand');

// Nama di menu Quit/Hide/About, notifikasi, dan taskbar Windows (bar menu macOS: lihat brand.js).
app.setName(BRAND);
if (process.platform === 'win32') app.setAppUserModelId(BUNDLE_ID);

const proc = new engine.EngineProcess();
let win = null;
let discovery = null; // dibuat saat aplikasi siap; null bila jaringan tidak mendukung mDNS
let team = null; // kelompok pemimpin-pengikut (team.js)
let uiRole = 'single'; // peran yang dipilih di halaman Pantau
let runningMode = null; // mode engine yang sedang berjalan
const invitations = new Map(); // id pemimpin -> ajakan yang belum dijawab
let exchange = 'binance'; // platform aktif: jurnal dan posisi dibaca dari bursa ini

/** Argumen engine untuk platform aktif (jurnal dan posisi terpisah per bursa). */
function onExchange(args) {
  return ['--bursa', exchange, ...args];
}
// Aktivitas terakhir laptop ini, diumumkan ke laptop lain (hanya bila token hub diatur).
let activity = { text: '', coin: '', at: 0 };
let activityTimer = null;
const ACTIVITY_THROTTLE_MS = 4000; // tiap pengumuman ulang = goodbye + announce: jangan terlalu sering

// Kunci pemimpin (leaderkey.js): privat hanya di laptop pemimpin, publik di semua laptop kelompok.
const leaderKeys = loadLeaderKey(engine.appSetting('BOT_LEADER_KEY'));
const leaderPublic = leaderKeys?.public ?? loadLeaderPublic(engine.appSetting('BOT_LEADER_PUBLIC'));
const LEADER_ONLY = 'Peran Pemimpin hanya untuk laptop yang memegang kunci pemimpin. Hubungi admin.';

let ownPositions = []; // posisi terbuka laptop ini (`posisi`), diumumkan ke pemimpin
const PAIR = /^[A-Z0-9]{1,20}USD[TC]$/;
const HEARTBEAT_MS = 20 * 1000; // pengikut mengumumkan ulang posisinya (tanda masih tersambung)
const FOLLOWER_FRESH_MS = 3 * HEARTBEAT_MS; // terputus bila 3 detak terlewat

/** Aktivitas dan posisi terenkripsi ke pemimpin: hanya laptop pemimpin yang bisa memantaunya. */
function activityFields() {
  if (!team?.enabled || !leaderPublic || leaderKeys) return {};
  if (!activity.text && !team.membership) return {};
  const positions = ownPositions.slice(0, 4).map((p) => [
    p.symbol,
    Number.isFinite(p.pnl_capital_pct) ? Math.round(p.pnl_capital_pct * 100) / 100 : null,
  ]);
  const payload = JSON.stringify([
    activity.text || 'Siap mengikuti pemimpin', activity.coin, Math.floor((activity.at || Date.now()) / 1000), positions,
  ]);
  return sealedFields(sealForLeader(leaderPublic, payload));
}

/** Baca ulang posisi terbuka laptop ini dari jurnal (tanpa menyentuh Binance). */
async function refreshPositions() {
  try {
    const result = await engine.runJson(onExchange(['posisi']));
    if (Array.isArray(result.positions)) ownPositions = result.positions;
  } catch {
    return;
  }
  syncPresence();
  send('positions:changed');
}

/** Pengikut pemimpin ini: sudah menerima ajakan dan masih terdengar di WiFi? */
function followersStatus() {
  if (!discovery || !team) return { followers: [], allConnected: false };
  const now = Date.now();
  const followers = [...team.invites].map(([id, rank]) => {
    const peer = discovery.peers.get(id);
    const accepted = Boolean(peer && team.describe(peer).followerRank);
    return {
      id,
      rank,
      name: peer?.name ?? followerNames.get(id) ?? 'Laptop pengikut',
      accepted,
      connected: accepted && now - (peer.seenAt || 0) < FOLLOWER_FRESH_MS,
      positions: peer?.activity?.positions ?? [],
      activity: peer?.activity?.text ?? '',
      activityAt: peer?.activity?.at ?? 0,
    };
  });
  return { followers, allConnected: followers.length > 0 && followers.every((f) => f.connected) };
}

const followerNames = new Map(); // id pengikut -> nama, diingat sejak diajak (bila nanti terputus)

const closeQueue = []; // perintah Sell pemimpin yang menunggu bot di laptop ini selesai
// Real Fund Trading. runReal: bot yang sedang berjalan memakai uang sungguhan. followerRealOk:
// laptop pengikut ini sudah menyetujui modal peringatan untuk pemimpinnya (sampai keluar kelompok
// atau aplikasi ditutup). pendingRealStart: putaran pemimpin yang menunggu jawaban modal itu.
let runReal = false;
let runStrategy = null; // arah, cutloss, dan batas waktu bot yang sedang berjalan (diumumkan pemimpin)
let followerRealOk = null; // id pemimpin yang sudah disetujui
let pendingRealStart = null;
// Pengikut tetap mengawasi posisinya (target, cutloss, batas waktu) sesudah putarannya selesai.
// Untuk menghentikannya dengan aman (putaran baru pemimpin, Sell dari pemimpin), aplikasi membuat
// berkas ini; bot berhenti di antara dua pengecekan, tidak pernah di tengah klik.
const FOLLOWER_STOP_FILE = path.join(os.tmpdir(), `marketforge-follower-stop-${process.pid}`);
let pendingFollowerStart = null; // putaran pemimpin yang menunggu bot pengikut sebelumnya selesai
// Arah, cutloss, dan batas waktu terakhir dari pemimpin. Pengikut tidak memilih sendiri (isiannya
// tersembunyi di layar pengikut), juga saat Mulai ditekan langsung di laptop pengikut.
let leaderStrategy = {};

function askFollowerStop() {
  try {
    fs.writeFileSync(FOLLOWER_STOP_FILE, '');
  } catch {
    // tidak bisa menulis: bot tetap berhenti sendiri saat pemimpin memulai putaran baru
  }
}

function clearFollowerStop() {
  fs.rmSync(FOLLOWER_STOP_FILE, { force: true });
}

/** Pengikut: jalankan perintah Sell dari pemimpin (uji kertas, tombol tidak ditekan). */
async function closeForLeader({ leaderName, symbol }) {
  if (proc.running) {
    closeQueue.push({ leaderName, symbol });
    if (runningMode === 'follower') askFollowerStop(); // pengikut sedang mengawasi posisi
    return;
  }
  let text;
  try {
    // Posisi sungguhan pengikut hanya ditutup di bursa bila laptop ini menyetujui Real Fund Trading.
    const real = followerRealOk && followerRealOk === team?.membership?.leaderId ? ['--uang-sungguhan'] : [];
    const result = await engine.runJson(
      onExchange([...real, 'posisi', '--tutup', symbol === '*' ? 'semua' : symbol]), { timeoutMs: 180000 },
    );
    if (Array.isArray(result.positions)) ownPositions = result.positions;
    const done = (result.closed || []).map((c) => c.symbol).join(', ');
    if (result.error) text = `Gagal menutup posisi: ${result.error}`;
    else text = done ? `${leaderName} menutup posisi: ${done}` : `${leaderName} menutup posisi: tidak ada posisi terbuka`;
  } catch {
    text = 'Gagal menutup posisi';
  }
  reportActivity({ text });
  send('positions:changed');
  send('team:changed', { ...teamState(), notice: text });
}

function reportActivity({ text, coin }) {
  activity = {
    text: String(text || '').slice(0, MAX_ACTIVITY),
    coin: COIN.test(String(coin || '')) ? String(coin) : activity.coin,
    at: Date.now(),
  };
  if (activityTimer) return;
  activityTimer = setTimeout(() => {
    activityTimer = null;
    syncPresence();
  }, ACTIVITY_THROTTLE_MS);
}

/** Umumkan peran, status bot, dan data kelompok laptop ini. */
function syncPresence() {
  if (!discovery) return;
  const role = team.membership ? 'follower' : uiRole;
  discovery.update({ role, running: proc.running, extra: { ...team.fields(role), ...activityFields() } });
  send('peers:changed');
}

/** Daftar laptop saat ini (tanpa menunggu pengumuman ulang), dengan status kelompok. */
function peersNow() {
  return discovery ? discovery.snapshot().map((peer) => team.describe(peer)) : [];
}

function teamState() {
  return {
    available: discovery !== null,
    enabled: Boolean(team?.enabled && leaderPublic),
    canLead: Boolean(leaderKeys),
    role: team?.membership ? 'follower' : uiRole,
    membership: team?.membership ?? null,
  };
}

/** Pemimpin memulai putaran: pengikut yang sudah menerima ikut menjalankan bot. */
function startFollower(start) {
  const { leaderName, rank, modal, hub, exchange: leaderExchange, real = false } = start;
  // Arah, cutloss, dan batas waktu mengikuti pemimpin (tanpa keterangan: short saja, seperti dulu).
  const { shortTops, longTops, cutloss, timeLimit } = start;
  leaderStrategy = { shortTops, longTops, cutloss, timeLimit };
  if (proc.running) {
    // Bot pengikut putaran sebelumnya masih mengawasi posisi: hentikan dengan aman, lalu mulai.
    if (runningMode === 'follower') {
      pendingFollowerStart = start;
      askFollowerStop();
    }
    return;
  }
  // Pengikut memakai platform pemimpin (Binance atau Tebbit); tanpa keterangan, platform laptop ini.
  const platform = engine.EXCHANGES.includes(leaderExchange) ? leaderExchange : exchange;
  const leaderId = team?.membership?.leaderId;
  if (real && platform === 'binance' && followerRealOk !== leaderId && start.answered === undefined) {
    // Pemimpin memakai uang sungguhan: laptop ini menyetujui dulu lewat modal peringatan.
    pendingRealStart = start;
    send('team:realRequest', { leaderName, modal, exchange: platform });
    showAppWindow();
    return;
  }
  const useReal = real && platform === 'binance' && followerRealOk === leaderId;
  try {
    clearFollowerStop();
    proc.start(engine.buildArgs('follower', {
      rank, modal, hub, exchange: platform, real: useReal, shortTops, longTops, cutloss, timeLimit,
      stopFile: FOLLOWER_STOP_FILE,
    }));
  } catch (err) {
    send('team:error', `Gagal mengikuti ${leaderName}: ${err.message}`);
    return;
  }
  exchange = platform;
  runReal = useReal;
  runningMode = 'follower';
  syncPresence();
  send('team:started', { leaderName, rank, exchange: platform, real: useReal });
  win?.minimize();
}

/** Umumkan laptop ini ke MarketForge lain di WiFi yang sama (Bonjour) dan dengarkan mereka. */
async function startDiscovery() {
  try {
    const { Bonjour } = require('bonjour-service');
    // Bonjour hanya lewat kartu jaringan utama (rute bawaan). Tanpa ini, laptop dengan kartu virtual
    // (VirtualBox, WSL, Hyper-V) bisa mengumumkan diri lewat kartu yang salah dan tak terlihat.
    const lan = localAddress(undefined, await primaryAddress()); // WiFi/Ethernet sungguhan, bukan VPN
    const options = lan ? { interface: lan, bind: '0.0.0.0' } : {};
    const bonjour = new Bonjour(options, (err) => console.error(`Bonjour: ${err.message}`));
    const token = engine.hubToken();
    discovery = new Discovery({
      bonjour, token, leaderKeys, leaderPublic, address: lan,
    });
    team = new Team({ myId: discovery.id, token });
    discovery.on('peers', (peers) => {
      if (team.evaluate(peers)) {
        syncPresence();
        send('team:changed', teamState()); // tugas Top diubah pemimpin: segarkan banner pengikut
      }
      send('peers:changed');
    });
    team.on('invite', (invite) => {
      invitations.set(invite.leaderId, invite);
      send('team:invite', invite);
    });
    team.on('removed', (info) => {
      followerRealOk = null; // persetujuan uang sungguhan berlaku per pemimpin
      pendingFollowerStart = null;
      leaderStrategy = {};
      syncPresence();
      send('team:changed', { ...teamState(), notice: `${info.leaderName} mengeluarkan laptop ini dari kelompok.` });
    });
    team.on('start', startFollower);
    team.on('close', closeForLeader);
    discovery.start();
    syncPresence();
    refreshPositions();
    // Detak pengikut: posisi terbaru dan tanda masih tersambung untuk pemimpin.
    setInterval(() => {
      if (!team?.membership) return;
      activity.at = Date.now();
      refreshPositions();
    }, HEARTBEAT_MS).unref?.();
  } catch (err) {
    console.error(`Penemuan laptop tidak aktif: ${err.message}`);
    discovery = null;
    team = null;
  }
}

function send(channel, payload) {
  if (win && !win.isDestroyed()) win.webContents.send(channel, payload);
}

/**
 * Engine menyerahkan layar ke aplikasi selama AI membaca grafik (sama di macOS dan Windows).
 * Engine membawa Binance/Tebbit ke depan lagi sendiri sebelum klik, ketik, atau tangkap layar.
 */
function showAppWindow() {
  if (!win || win.isDestroyed()) return;
  if (win.isMinimized()) win.restore();
  win.show();
  if (process.platform === 'darwin') app.focus({ steal: true });
  win.moveTop();
  win.focus();
}

/**
 * Bot selesai: jendela aplikasi dibawa ke depan di atas Binance/Tebbit dan sebuah notifikasi
 * muncul, supaya pengguna tahu tanpa memantau layar. Windows menahan jendela merebut fokus dari
 * aplikasi lain, jadi jendela dinaikkan dulu (always-on-top sebentar) dan taskbar berkedip.
 */
function announceExit(info) {
  const notice = engine.exitNotice(info);
  if (!win || win.isDestroyed()) return;
  showAppWindow();
  if (process.platform === 'win32') {
    win.setAlwaysOnTop(true);
    win.setAlwaysOnTop(false);
  }
  if (notice.kind === 'stopped') return; // pengguna sendiri yang menghentikan: sudah di aplikasi
  win.flashFrame(true);
  try {
    if (Notification.isSupported()) new Notification({ title: notice.title, body: notice.body, silent: false }).show();
  } catch {
    // notifikasi hanya tambahan; jendela yang tampil sudah cukup
  }
}

// --------------------------------------------------------------------------- kesehatan dan peringatan

const HEALTH_MS = 60 * 1000; // cek jaringan, charger, dan harga posisi tiap menit
const NETWORK_TIMEOUT_MS = 12000; // Wi-Fi lambat: sambungan ke Binance bisa 2-3 detik
let networkFails = 0; // cek jaringan gagal beruntun (lihat alerts.settleNetwork)
const REPEAT_NOTICE_MS = 30 * 60 * 1000; // notifikasi gagal/hilang yang sama paling sering 30 menit
const health = { network: 'unknown', onBattery: false, sleep: null, keepAwake: false, checkedAt: 0 };
let sleepingSince = null; // saat laptop mulai tidur (powerMonitor 'suspend')
let awakeBlocker = null; // powerSaveBlocker selama bot berjalan (layar dan laptop tetap menyala)
let lossLimit = 0; // batas rugi (%) untuk notifikasi; 0 = mati
const lossAlerted = new Set();
const noticeAt = new Map(); // kunci notifikasi -> waktu terakhir tampil
const missing = new Set(); // posisi yang tidak ada lagi di tab Posisi bursa (mungkin ditutup manual)

function realOpen() {
  return ownPositions.filter((p) => p.real).length;
}

function notify(notice, repeatMs = 0) {
  if (!notice) return;
  const last = noticeAt.get(notice.key);
  if (repeatMs && last && Date.now() - last < repeatMs) return;
  noticeAt.set(notice.key, Date.now());
  try {
    if (Notification.isSupported()) new Notification({ title: notice.title, body: notice.body }).show();
  } catch {
    // notifikasi hanya tambahan; peringatan juga tampil di aplikasi
  }
}

function healthSnapshot() {
  const state = { ...health, exchange, running: proc.running, realOpen: realOpen(), now: Date.now() };
  return { ...state, warnings: alerts.healthWarnings(state), missing: [...missing], lossLimit };
}

/**
 * Jaga Mac/PC dan LAYAR tetap menyala selama bot berjalan. Bot mengklik dan membaca layar Binance,
 * jadi penghemat layar atau kunci layar yang muncul di tengah jeda putaran menggagalkan putaran
 * dan jual otomatis. 'prevent-display-sleep' (setara `caffeinate -d`) menahan layar mati dan
 * penghemat layar, dan sekaligus menahan laptop tidur; 'prevent-app-suspension' hanya menahan
 * tidur (setara `caffeinate -i`) dan tidak cukup. Dilepas begitu bot berhenti.
 */
function syncKeepAwake() {
  const want = proc.running;
  if (want && awakeBlocker === null) awakeBlocker = powerSaveBlocker.start('prevent-display-sleep');
  if (!want && awakeBlocker !== null) {
    powerSaveBlocker.stop(awakeBlocker);
    awakeBlocker = null;
  }
  health.keepAwake = awakeBlocker !== null;
}

async function reachable(url) {
  try {
    // net.fetch: jaringan Chromium, mengikuti proxy/VPN sistem seperti browser.
    const res = await net.fetch(url, { method: 'GET', signal: AbortSignal.timeout(NETWORK_TIMEOUT_MS) });
    return res.status < 500;
  } catch {
    return false;
  }
}

async function checkNetwork() {
  const online = net.isOnline();
  const exchangeOk = online && (await reachable(alerts.NETWORK_TARGETS[exchange] || alerts.NETWORK_TARGETS.binance));
  const controlOk = exchangeOk || (online && (await reachable(alerts.CONTROL_TARGET)));
  const settled = alerts.settleNetwork(health.network, alerts.networkState(exchangeOk, controlOk), online, networkFails);
  health.network = settled.network;
  networkFails = settled.fails;
  health.checkedAt = Date.now();
}

/** Harga posisi terbuka tanpa menulis jurnal (aman di samping bot), lalu cek batas rugi. */
async function refreshLivePositions() {
  try {
    const result = await engine.runJson(onExchange(['posisi', '--baca']));
    if (!Array.isArray(result.positions)) return;
    ownPositions = result.positions;
  } catch {
    return;
  }
  const open = new Set(ownPositions.map((p) => p.symbol));
  for (const symbol of [...missing]) if (!open.has(symbol)) missing.delete(symbol);
  for (const notice of alerts.lossAlerts(ownPositions, lossLimit, lossAlerted)) notify(notice);
  syncPresence();
  send('positions:changed', { positions: ownPositions });
}

async function healthTick() {
  syncKeepAwake();
  health.onBattery = powerMonitor.isOnBatteryPower();
  await checkNetwork();
  await refreshLivePositions(); // juga menemukan posisi baru (mis. setelah ganti platform)
  send('health:changed', healthSnapshot());
}

function startHealth() {
  powerMonitor.on('suspend', () => {
    sleepingSince = Date.now();
  });
  powerMonitor.on('resume', () => {
    if (sleepingSince !== null) {
      const to = Date.now();
      const watching = proc.running || realOpen() > 0;
      health.sleep = { from: sleepingSince, to, minutes: Math.round((to - sleepingSince) / 60000), watching };
      sleepingSince = null;
      if (watching && health.sleep.minutes >= 1) {
        notify({ key: 'sleep', title: `Laptop sempat tidur ${health.sleep.minutes} menit`, body: 'Selama itu bot tidak memantau posisi. Pasang charger dan jangan tutup layar.' });
      }
    }
    healthTick();
  });
  const power = () => {
    health.onBattery = powerMonitor.isOnBatteryPower();
    if (health.onBattery && (proc.running || realOpen())) {
      notify({ key: 'battery', title: 'Charger dilepas', body: 'Pasang charger supaya laptop tidak tidur saat bot memantau.' }, REPEAT_NOTICE_MS);
    }
    send('health:changed', healthSnapshot());
  };
  powerMonitor.on('on-battery', power);
  powerMonitor.on('on-ac', power);
  healthTick();
  setInterval(healthTick, HEALTH_MS).unref?.();
}

proc.on('log', (entry) => {
  send('engine:log', entry);
  if (!health.keepAwake) syncKeepAwake();
  const notice = alerts.logNotice(entry);
  if (notice) {
    notify(notice, notice.key.startsWith('sold:') ? 0 : REPEAT_NOTICE_MS);
    if (entry.event?.type === 'position_missing') {
      missing.add(entry.event.symbol);
      send('health:changed', healthSnapshot());
    }
  }
  const e = entry.event;
  if (e?.type === 'view' && e.target === 'app') showAppWindow();
  if (team && runningMode === 'leader' && e?.type === 'cycle' && e.phase === 'start') {
    // Pengikut ikut memulai putaran ini, di platform yang sama dan dengan arah serta aturan keluar yang sama.
    team.startCycle(exchange, runReal, runStrategy);
    syncPresence();
  }
});
proc.on('exit', (info) => {
  send('engine:exit', info);
  runReal = false;
  runningMode = null;
  syncPresence();
  refreshPositions();
  syncKeepAwake();
  send('health:changed', healthSnapshot());
  clearFollowerStop();
  announceExit(info); // bot selesai: aplikasi kembali ke depan dan memberi tahu
  // Sell pemimpin dijalankan dulu, satu per satu, baru putaran pemimpin yang menunggu dimulai.
  (async () => {
    for (const job of closeQueue.splice(0)) await closeForLeader(job);
    const start = pendingFollowerStart;
    pendingFollowerStart = null;
    if (start && team?.membership) startFollower(start);
  })();
});

function createWindow() {
  win = new BrowserWindow({
    width: 1360,
    height: 880,
    minWidth: 1000,
    minHeight: 680,
    title: BRAND,
    icon: ICON, // Windows/Linux; di macOS ikon Dock diatur lewat app.dock
    backgroundColor: '#121316',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  win.webContents.on('will-navigate', (event) => event.preventDefault());
  win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  win.loadFile(PAGE);
  win.on('closed', () => {
    win = null;
  });
}

/** IPC hanya diterima dari halaman aplikasi sendiri. Error dikirim balik sebagai teks. */
function handle(channel, fn) {
  ipcMain.handle(channel, async (event, ...args) => {
    if (event.senderFrame?.url !== PAGE_URL) throw new Error('Permintaan ditolak');
    try {
      return { ok: true, value: await fn(...args) };
    } catch (err) {
      return { ok: false, error: err.message };
    }
  });
}

handle('engine:start', (mode, params) => {
  if (team?.membership && mode !== 'follower') throw new Error('Laptop ini pengikut. Keluar dari kelompok dulu.');
  if (mode === 'leader' && !leaderKeys) throw new Error(LEADER_ONLY);
  if ((mode === 'leader' || mode === 'follower') && !engine.hubToken()) {
    throw new Error('Mode Pemimpin dan Pengikut butuh token hub yang sama di semua laptop. Minta admin mengisinya.');
  }
  let args;
  if (mode === 'follower') {
    const { shortTops, longTops, cutloss, timeLimit, ...own } = params || {};
    const rank = team?.membership ? { rank: team.membership.rank } : {};
    args = engine.buildArgs(mode, { ...own, ...rank, ...leaderStrategy, stopFile: FOLLOWER_STOP_FILE });
    clearFollowerStop();
  } else {
    args = engine.buildArgs(mode, params);
  }
  proc.start(args);
  exchange = params?.exchange || 'binance';
  runReal = params?.real === true;
  runStrategy = {
    shortTops: params?.shortTops,
    longTops: params?.longTops,
    cutloss: params?.cutloss === true,
    timeLimit: params?.timeLimit === true,
  };
  runningMode = mode;
  uiRole = mode;
  syncPresence();
  // Bot memakai layar Binance: jendela aplikasi jangan menutupinya (screenshot dan OCR).
  win?.minimize();
  return true;
});
handle('engine:stop', () => {
  pendingFollowerStart = null; // dihentikan pengguna: tidak langsung dimulai lagi
  proc.stop();
  return true;
});
handle('engine:status', () => ({ running: proc.running, exchange }));
handle('engine:checks', () => engine.runJson(['cek']));
const DAY = /^\d{4}-\d{2}-\d{2}$/;
handle('engine:summary', (range) => {
  // Filter waktu Hasil uji: hanya tanggal YYYY-MM-DD yang diteruskan ke engine.
  const args = ['jurnal', '--json'];
  if (range?.from) {
    if (!DAY.test(String(range.from))) throw new Error('Tanggal awal tidak valid');
    args.push('--dari', String(range.from));
  }
  if (range?.to) {
    if (!DAY.test(String(range.to))) throw new Error('Tanggal akhir tidak valid');
    args.push('--sampai', String(range.to));
  }
  return engine.runJson(onExchange(args));
});
handle('platform:set', (id) => {
  if (!engine.EXCHANGES.includes(id)) throw new Error('Platform tidak dikenal');
  if (!proc.running && exchange !== id) {
    exchange = id; // saat bot berjalan, platform mengikuti bot
    ownPositions = []; // posisi dan jaringan dicek ulang untuk bursa ini
    missing.clear();
    healthTick();
  }
  return exchange;
});
handle('chart:image', (file) => engine.readChart(file));
const HISTORY_ID = /^[A-Za-z0-9_.-]{1,120}$/;
function editHistory(args) {
  if (proc.running) throw new Error('Hentikan bot dulu sebelum menghapus riwayat.');
  return engine.runJson(onExchange(['riwayat', ...args]));
}
handle('history:delete', (id) => {
  if (!HISTORY_ID.test(String(id))) throw new Error('Riwayat tidak dikenal');
  return editHistory(['--hapus', String(id)]);
});
handle('history:clear', () => editHistory(['--bersihkan']));
handle('presence:update', (role) => {
  if (['single', 'follower'].includes(role) || (role === 'leader' && leaderKeys)) uiRole = role;
  syncPresence();
  return teamState();
});
handle('peers:list', async () => {
  if (!discovery) throw new Error('Pencarian laptop tidak bisa berjalan di jaringan ini.');
  return (await discovery.list()).map((peer) => team.describe(peer));
});
handle('peers:now', () => peersNow());
handle('presence:activity', (update) => {
  reportActivity(update || {});
  return true;
});
handle('team:state', () => teamState());
handle('positions:list', async () => {
  const result = await engine.runJson(onExchange(['posisi']));
  if (Array.isArray(result.positions)) ownPositions = result.positions;
  return result;
});
handle('positions:check', async () => {
  // Tebbit: bot membuka Chrome sebentar untuk membaca harga tiap posisi (OCR), lalu jual otomatis
  // bila sudah target. Tidak bersamaan dengan bot yang sedang memakai layar.
  if (proc.running) throw new Error('Bot sedang berjalan dan sudah mengecek posisi tiap 5 menit.');
  const result = await engine.runJson(onExchange(['posisi', '--cek']), { timeoutMs: 300000 });
  if (Array.isArray(result.positions)) ownPositions = result.positions;
  return result;
});
handle('positions:cached', () => ownPositions);
handle('positions:recordManual', async (symbol, exitPrice, pnlUsdt) => {
  // Hanya mencatat jurnal; tidak menyentuh bursa. Aman saat bot berjalan (kunci jual yang sama).
  const result = await engine.runJson(onExchange(engine.manualCloseArgs(symbol, exitPrice, pnlUsdt)));
  if (result.error) throw new Error(result.error);
  if (Array.isArray(result.positions)) ownPositions = result.positions;
  missing.delete(String(symbol).toUpperCase());
  syncPresence();
  send('positions:changed', { positions: ownPositions });
  send('health:changed', healthSnapshot());
  return result;
});
handle('health:get', () => healthSnapshot());
handle('alerts:setLossLimit', (pct) => {
  const value = Number(pct);
  lossLimit = [0, 10, 20, 30, 50].includes(value) ? value : 0;
  lossAlerted.clear();
  return lossLimit;
});
handle('team:realAnswer', (ok) => {
  const start = pendingRealStart;
  pendingRealStart = null;
  if (!start) return false;
  if (ok === true) followerRealOk = team?.membership?.leaderId ?? null;
  startFollower({ ...start, answered: ok === true }); // ditolak: ikut sebagai uji kertas
  return true;
});
handle('positions:close', async (symbol, real = false) => {
  // Hanya mode Sendiri; posisi pengikut hanya ditutup oleh pemimpinnya.
  if (team?.membership || uiRole !== 'single') {
    throw new Error('Hanya mode Sendiri yang bisa menutup posisinya sendiri. Posisi pengikut ditutup oleh pemimpin.');
  }
  if (symbol !== 'semua' && !PAIR.test(String(symbol))) throw new Error('Pair tidak valid');
  // Posisi sungguhan: bot membuka Binance dan menekan Market di tab Posisi (layar dipakai).
  if (real === true && proc.running) throw new Error('Hentikan bot dulu: menutup posisi sungguhan memakai layar Binance.');
  const live = real === true ? ['--uang-sungguhan'] : [];
  const result = await engine.runJson(onExchange([...live, 'posisi', '--tutup', symbol]), { timeoutMs: 180000 });
  if (result.error) throw new Error(`Posisi belum ditutup: ${result.error}`);
  if (Array.isArray(result.positions)) ownPositions = result.positions;
  syncPresence();
  return result;
});
handle('team:followers', async () => {
  if (discovery) await discovery.list(1500);
  return followersStatus();
});
handle('team:close', (target, symbol) => {
  if (!leaderKeys) throw new Error(LEADER_ONLY);
  if (team.membership || uiRole !== 'leader') throw new Error('Pilih peran Pemimpin di halaman Pantau dulu.');
  if (target !== '*' && !team.invites.has(target)) throw new Error('Laptop itu bukan pengikut pemimpin ini.');
  if (symbol !== '*' && !PAIR.test(String(symbol))) throw new Error('Pair tidak valid');
  const { followers, allConnected } = followersStatus();
  if (!allConnected) {
    const missing = followers.filter((f) => !f.connected).map((f) => f.name).join(', ');
    throw new Error(followers.length ? `Belum semua pengikut tersambung: ${missing}.` : 'Belum ada pengikut.');
  }
  team.requestClose(target, symbol);
  syncPresence();
  return true;
});
handle('team:invite', (peerId, rank) => {
  if (!leaderKeys) throw new Error(LEADER_ONLY);
  if (!team?.enabled) throw new Error('Token hub belum diatur di laptop ini. Hubungi admin.');
  if (team.membership || uiRole !== 'leader') throw new Error('Pilih peran Pemimpin di halaman Pantau dulu.');
  if (!discovery.peers.has(peerId)) throw new Error('Laptop itu sudah tidak terlihat. Cari ulang.');
  const assignment = normalizeRank(rank);
  if (!assignment) throw new Error('Pilih Top 1 sampai 5, atau semua Top pemimpin');
  team.invite(peerId, assignment);
  followerNames.set(peerId, discovery.peers.get(peerId).name);
  syncPresence();
  return true;
});
handle('team:assignAll', (rank) => {
  if (!leaderKeys) throw new Error(LEADER_ONLY);
  if (team.membership || uiRole !== 'leader') throw new Error('Pilih peran Pemimpin di halaman Pantau dulu.');
  const assignment = normalizeRank(rank);
  if (!assignment) throw new Error('Pilih Top 1 sampai 5, atau semua Top pemimpin');
  const count = team.assignAll(assignment);
  syncPresence();
  return count;
});
handle('team:uninvite', (peerId) => {
  team?.uninvite(String(peerId));
  syncPresence();
  return true;
});
handle('team:accept', (leaderId, modal) => {
  const invite = invitations.get(leaderId);
  if (!invite) throw new Error('Ajakan sudah tidak berlaku.');
  engine.buildArgs('follower', { rank: invite.rank, modal }); // validasi modal sebelum disimpan
  team.accept({ ...invite, modal: String(modal).trim() });
  invitations.clear();
  uiRole = 'follower';
  syncPresence();
  return teamState();
});
handle('team:decline', (leaderId) => {
  const invite = invitations.get(leaderId);
  if (invite) team.decline(invite.leaderId, invite.rank);
  invitations.delete(leaderId);
  return true;
});
handle('team:leave', () => {
  team?.leave();
  followerRealOk = null;
  syncPresence();
  return teamState();
});

app.whenReady().then(async () => {
  if (process.platform === 'darwin') app.dock?.setIcon(ICON);
  await startDiscovery(); // selesai sebelum jendela memuat daftar laptop
  createWindow();
  startHealth();
});
app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow();
});
app.on('window-all-closed', () => app.quit());
// Keluar: hentikan bot dan pamit di jaringan dulu (maks 0,5 detik) agar pemimpin langsung tahu
// laptop ini pergi; tanpa pamit, pemimpin baru tahu setelah detak terlewat.
let quitting = false;
function shutdown() {
  if (quitting) return;
  quitting = true;
  proc.stop();
  const exit = () => app.exit(0);
  if (!discovery) return exit();
  discovery.stop(exit);
  setTimeout(exit, 500);
}
app.on('before-quit', (event) => {
  if (quitting) return;
  event.preventDefault();
  shutdown();
});
for (const signal of ['SIGTERM', 'SIGINT']) process.on(signal, shutdown);

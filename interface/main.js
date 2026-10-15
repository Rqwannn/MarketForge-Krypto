'use strict';

// Proses utama Electron: jendela, IPC, dan satu proses engine. Isian dari tampilan divalidasi
// di engine.js sebelum menjadi argumen CLI. Tidak ada kontrol untuk order sungguhan.

const { app, BrowserWindow, ipcMain } = require('electron');
const path = require('node:path');
const { pathToFileURL } = require('node:url');

const engine = require('./engine');
const {
  COIN, Discovery, MAX_ACTIVITY, localAddress, primaryAddress, sealedFields,
} = require('./discovery');
const { loadLeaderKey, loadLeaderPublic, sealForLeader } = require('./leaderkey');
const { Team, normalizeRank } = require('./team');

const PAGE = path.join(__dirname, 'renderer', 'index.html');
const ICON = path.join(__dirname, 'assets', 'icon.png'); // logo MarketForge (dari app_icon_adaptive)
const PAGE_URL = pathToFileURL(PAGE).href;

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

/** Pengikut: jalankan perintah Sell dari pemimpin (uji kertas, tombol tidak ditekan). */
async function closeForLeader({ leaderName, symbol }) {
  if (proc.running) {
    closeQueue.push({ leaderName, symbol });
    return;
  }
  let text;
  try {
    const result = await engine.runJson(onExchange(['posisi', '--tutup', symbol === '*' ? 'semua' : symbol]));
    if (Array.isArray(result.positions)) ownPositions = result.positions;
    const done = (result.closed || []).map((c) => c.symbol).join(', ');
    if (result.error) text = 'Gagal menutup posisi: harga Binance tidak bisa diambil';
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
function startFollower({ leaderName, rank, modal, hub }) {
  if (proc.running) return;
  try {
    proc.start(engine.buildArgs('follower', { rank, modal, hub }));
  } catch (err) {
    send('team:error', `Gagal mengikuti ${leaderName}: ${err.message}`);
    return;
  }
  runningMode = 'follower';
  syncPresence();
  send('team:started', { leaderName, rank });
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

proc.on('log', (entry) => {
  send('engine:log', entry);
  const e = entry.event;
  if (e?.type === 'view' && e.target === 'app') showAppWindow();
  if (team && runningMode === 'leader' && e?.type === 'cycle' && e.phase === 'start') {
    team.startCycle(); // pengikut ikut memulai putaran ini
    syncPresence();
  }
});
proc.on('exit', (info) => {
  send('engine:exit', info);
  runningMode = null;
  syncPresence();
  refreshPositions();
  for (const job of closeQueue.splice(0)) closeForLeader(job);
  // Bot selesai: tampilkan lagi jendela aplikasi.
  if (win && !win.isDestroyed()) {
    win.restore();
    win.focus();
  }
});

function createWindow() {
  win = new BrowserWindow({
    width: 1360,
    height: 880,
    minWidth: 1000,
    minHeight: 680,
    title: 'MarketForge',
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
  const args = mode === 'follower' && team?.membership
    ? engine.buildArgs(mode, { ...params, rank: team.membership.rank })
    : engine.buildArgs(mode, params);
  proc.start(args);
  exchange = params?.exchange || 'binance';
  runningMode = mode;
  uiRole = mode;
  syncPresence();
  // Bot memakai layar Binance: jendela aplikasi jangan menutupinya (screenshot dan OCR).
  win?.minimize();
  return true;
});
handle('engine:stop', () => {
  proc.stop();
  return true;
});
handle('engine:status', () => ({ running: proc.running, exchange }));
handle('engine:checks', () => engine.runJson(['cek']));
handle('engine:summary', () => engine.runJson(onExchange(['jurnal', '--json'])));
handle('platform:set', (id) => {
  if (!engine.EXCHANGES.includes(id)) throw new Error('Platform tidak dikenal');
  if (!proc.running) exchange = id; // saat bot berjalan, platform mengikuti bot
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
handle('positions:close', async (symbol) => {
  // Hanya mode Sendiri; posisi pengikut hanya ditutup oleh pemimpinnya.
  if (team?.membership || uiRole !== 'single') {
    throw new Error('Hanya mode Sendiri yang bisa menutup posisinya sendiri. Posisi pengikut ditutup oleh pemimpin.');
  }
  if (symbol !== 'semua' && !PAIR.test(String(symbol))) throw new Error('Pair tidak valid');
  const result = await engine.runJson(onExchange(['posisi', '--tutup', symbol]));
  if (result.error) throw new Error('Harga Binance tidak bisa diambil, posisi belum ditutup.');
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
  syncPresence();
  return teamState();
});

app.whenReady().then(async () => {
  if (process.platform === 'darwin') app.dock?.setIcon(ICON);
  await startDiscovery(); // selesai sebelum jendela memuat daftar laptop
  createWindow();
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

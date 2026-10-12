'use strict';

// Proses utama Electron: jendela, IPC, dan satu proses engine. Isian dari tampilan divalidasi
// di engine.js sebelum menjadi argumen CLI. Tidak ada kontrol untuk order sungguhan.

const { app, BrowserWindow, ipcMain } = require('electron');
const path = require('node:path');
const { pathToFileURL } = require('node:url');

const engine = require('./engine');
const { Discovery } = require('./discovery');
const { Team } = require('./team');

const PAGE = path.join(__dirname, 'renderer', 'index.html');
const PAGE_URL = pathToFileURL(PAGE).href;

const proc = new engine.EngineProcess();
let win = null;
let discovery = null; // dibuat saat aplikasi siap; null bila jaringan tidak mendukung mDNS
let team = null; // kelompok pemimpin-pengikut (team.js)
let uiRole = 'single'; // peran yang dipilih di halaman Pantau
let runningMode = null; // mode engine yang sedang berjalan
const invitations = new Map(); // id pemimpin -> ajakan yang belum dijawab

/** Umumkan peran, status bot, dan data kelompok laptop ini. */
function syncPresence() {
  if (!discovery) return;
  const role = team.membership ? 'follower' : uiRole;
  discovery.update({ role, running: proc.running, extra: team.fields(role) });
}

function teamState() {
  return {
    available: discovery !== null,
    enabled: Boolean(team?.enabled),
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
function startDiscovery() {
  try {
    const { Bonjour } = require('bonjour-service');
    const bonjour = new Bonjour({}, (err) => console.error(`Bonjour: ${err.message}`));
    const token = engine.hubToken();
    discovery = new Discovery({ bonjour, token });
    team = new Team({ myId: discovery.id, token });
    discovery.on('peers', (peers) => {
      if (team.evaluate(peers)) syncPresence();
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
    discovery.start();
    syncPresence();
  } catch (err) {
    console.error(`Penemuan laptop tidak aktif: ${err.message}`);
    discovery = null;
    team = null;
  }
}

function send(channel, payload) {
  if (win && !win.isDestroyed()) win.webContents.send(channel, payload);
}

proc.on('log', (entry) => {
  send('engine:log', entry);
  const e = entry.event;
  if (team && runningMode === 'leader' && e?.type === 'cycle' && e.phase === 'start') {
    team.startCycle(); // pengikut ikut memulai putaran ini
    syncPresence();
  }
});
proc.on('exit', (info) => {
  send('engine:exit', info);
  runningMode = null;
  syncPresence();
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
    backgroundColor: '#0c0d14',
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
  if ((mode === 'leader' || mode === 'follower') && !engine.hubToken()) {
    throw new Error('Mode Pemimpin dan Pengikut butuh token hub yang sama di semua laptop. Minta admin mengisinya.');
  }
  const args = mode === 'follower' && team?.membership
    ? engine.buildArgs(mode, { ...params, rank: team.membership.rank })
    : engine.buildArgs(mode, params);
  proc.start(args);
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
handle('engine:status', () => ({ running: proc.running }));
handle('engine:checks', () => engine.runJson(['cek']));
handle('engine:summary', () => engine.runJson(['jurnal', '--json']));
handle('presence:update', (role) => {
  if (['single', 'leader', 'follower'].includes(role)) uiRole = role;
  syncPresence();
  return teamState();
});
handle('peers:list', async () => {
  if (!discovery) throw new Error('Pencarian laptop tidak bisa berjalan di jaringan ini.');
  return (await discovery.list()).map((peer) => team.describe(peer));
});
handle('team:state', () => teamState());
handle('team:invite', (peerId, rank) => {
  if (!team?.enabled) throw new Error('Token hub belum diatur di laptop ini. Hubungi admin.');
  if (team.membership || uiRole !== 'leader') throw new Error('Pilih peran Pemimpin di halaman Pantau dulu.');
  if (!discovery.peers.has(peerId)) throw new Error('Laptop itu sudah tidak terlihat. Cari ulang.');
  if (!Number.isInteger(rank) || rank < 1 || rank > 5) throw new Error('Top gainer harus 1 sampai 5');
  team.invite(peerId, rank);
  syncPresence();
  return true;
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

app.whenReady().then(() => {
  startDiscovery();
  createWindow();
});
app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow();
});
app.on('window-all-closed', () => {
  proc.stop();
  app.quit();
});
app.on('before-quit', () => {
  proc.stop();
  discovery?.stop();
});

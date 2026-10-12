'use strict';

// Proses utama Electron: jendela, IPC, dan satu proses engine. Isian dari tampilan divalidasi
// di engine.js sebelum menjadi argumen CLI. Tidak ada kontrol untuk order sungguhan.

const { app, BrowserWindow, ipcMain } = require('electron');
const path = require('node:path');
const { pathToFileURL } = require('node:url');

const engine = require('./engine');

const PAGE = path.join(__dirname, 'renderer', 'index.html');
const PAGE_URL = pathToFileURL(PAGE).href;

const proc = new engine.EngineProcess();
let win = null;

function send(channel, payload) {
  if (win && !win.isDestroyed()) win.webContents.send(channel, payload);
}

proc.on('log', (entry) => send('engine:log', entry));
proc.on('exit', (info) => send('engine:exit', info));

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
  proc.start(engine.buildArgs(mode, params));
  return true;
});
handle('engine:stop', () => {
  proc.stop();
  return true;
});
handle('engine:status', () => ({ running: proc.running }));
handle('engine:checks', () => engine.runJson(['cek']));
handle('engine:summary', () => engine.runJson(['jurnal', '--json']));

app.whenReady().then(createWindow);
app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow();
});
app.on('window-all-closed', () => {
  proc.stop();
  app.quit();
});
app.on('before-quit', () => proc.stop());

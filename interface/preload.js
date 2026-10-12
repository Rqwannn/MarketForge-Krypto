'use strict';

// API sempit untuk tampilan. Tidak ada akses Node.js, file, atau shell dari halaman.

const { contextBridge, ipcRenderer } = require('electron');

function call(channel, ...args) {
  return ipcRenderer.invoke(channel, ...args).then((result) => {
    if (!result.ok) throw new Error(result.error);
    return result.value;
  });
}

function listen(channel, callback) {
  const handler = (_event, payload) => callback(payload);
  ipcRenderer.on(channel, handler);
  return () => ipcRenderer.removeListener(channel, handler);
}

contextBridge.exposeInMainWorld('bot', {
  platform: process.platform,
  start: (mode, params) => call('engine:start', mode, params),
  stop: () => call('engine:stop'),
  status: () => call('engine:status'),
  checks: () => call('engine:checks'),
  summary: () => call('engine:summary'),
  onLog: (callback) => listen('engine:log', callback),
  onExit: (callback) => listen('engine:exit', callback),
});

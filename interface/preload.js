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
  setPlatform: (id) => call('platform:set', id),
  chartImage: (file) => call('chart:image', file),
  history: {
    remove: (id) => call('history:delete', id),
    clear: () => call('history:clear'),
  },
  peers: () => call('peers:list'),
  peersNow: () => call('peers:now'),
  reportActivity: (update) => call('presence:activity', update),
  positions: {
    list: () => call('positions:list'),
    check: () => call('positions:check'),
    close: (symbol) => call('positions:close', symbol),
    onChanged: (callback) => listen('positions:changed', callback),
  },
  onPeersChanged: (callback) => listen('peers:changed', callback),
  setRole: (role) => call('presence:update', role),
  team: {
    state: () => call('team:state'),
    invite: (peerId, rank) => call('team:invite', peerId, rank),
    uninvite: (peerId) => call('team:uninvite', peerId),
    assignAll: (rank) => call('team:assignAll', rank),
    accept: (leaderId, modal) => call('team:accept', leaderId, modal),
    decline: (leaderId) => call('team:decline', leaderId),
    leave: () => call('team:leave'),
    followers: () => call('team:followers'),
    close: (target, symbol) => call('team:close', target, symbol),
    onInvite: (callback) => listen('team:invite', callback),
    onStarted: (callback) => listen('team:started', callback),
    onChanged: (callback) => listen('team:changed', callback),
    onError: (callback) => listen('team:error', callback),
  },
  onLog: (callback) => listen('engine:log', callback),
  onExit: (callback) => listen('engine:exit', callback),
});

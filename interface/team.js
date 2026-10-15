'use strict';

// Kelompok pemimpin-pengikut di atas pengumuman Bonjour (discovery.js), tanpa port baru.
//
// - Pemimpin mengumumkan ajakan di TXT-nya: `inv=<id pengikut>:<top>,...`.
// - Laptop yang diajak menampilkan ajakan; pemiliknya harus menekan Terima.
// - Pengikut mengumumkan `leader=<id pemimpin>` dan `rank`.
// - Setiap putaran pemimpin dimulai, pemimpin mengumumkan `cycle=<waktu>`; pengikut yang sudah
//   menerima ikut menjalankan bot untuk putaran itu, di platform yang sama dengan pemimpin
//   (`ex=binance|tebbit`).
//
// Semua TXT ditandatangani HMAC dengan BOT_HUB_TOKEN. Data kelompok dari laptop yang tanda
// tangannya tidak cocok diabaikan, sehingga perangkat lain di WiFi tidak bisa memalsukan ajakan
// atau memicu bot.

const crypto = require('node:crypto');
const { EventEmitter } = require('node:events');

const SHORT_ID = 8;
const EXCHANGES = ['binance', 'tebbit']; // platform yang boleh diumumkan pemimpin
const SIG_LENGTH = 32;
const CYCLE_FRESH_MS = 2 * 60 * 1000; // sinyal putaran lebih tua dari ini tidak memicu bot
const HUB_PORT = 8765;

const shortId = (id) => String(id).slice(0, SHORT_ID);
// Perintah Sell dari pemimpin: "<waktu ms>:<id pengikut|*>:<PAIR|*>"
const CLOSE = /^(\d{10,16}):([0-9a-f]{8}|\*):([A-Z0-9]{1,20}USD[TC]|\*)$/;

/** Teks yang ditandatangani: semua field kecuali tanda tangan itu sendiri. */
function canonical(fields, skip = ['sig']) {
  return Object.keys(fields)
    .filter((key) => !skip.includes(key))
    .sort()
    .map((key) => `${key}=${fields[key]}`)
    .join('&');
}

function sign(token, fields) {
  return crypto.createHmac('sha256', token).update(canonical(fields)).digest('hex').slice(0, SIG_LENGTH);
}

function isSigned(token, txt) {
  if (!token || typeof txt.sig !== 'string' || txt.sig.length !== SIG_LENGTH) return false;
  const want = Buffer.from(sign(token, txt));
  const got = Buffer.from(txt.sig);
  return got.length === want.length && crypto.timingSafeEqual(got, want);
}

/** Map(id lengkap -> tugas Top) -> "abcd1234:245,ef567890:*". */
function encodeInvites(invites) {
  return [...invites].map(([id, rank]) => `${shortId(id)}:${rank}`).join(',');
}

/**
 * Tugas Top seorang pengikut, dalam bentuk baku: '*' (semua Top yang dimainkan pemimpin) atau
 * deretan angka terurut tanpa duplikat, mis. '245' = Top 2, 4, dan 5. Menerima angka tunggal,
 * deretan angka, atau larik. null bila tidak valid.
 */
function normalizeRank(value) {
  if (value === '*') return '*';
  let list;
  if (Array.isArray(value)) list = value;
  else if (typeof value === 'number') list = [value];
  else if (typeof value === 'string' && /^[1-5]{1,5}$/.test(value)) list = value.split('');
  else return null;
  const nums = [...new Set(list.map(Number))];
  if (nums.length === 0 || nums.some((n) => !Number.isInteger(n) || n < 1 || n > 5)) return null;
  return nums.sort((a, b) => a - b).join('');
}

/** "abcd1234:245,ef567890:*" -> Map(id pendek -> tugas Top). Bagian yang tidak valid diabaikan. */
function decodeInvites(text) {
  const invites = new Map();
  for (const part of String(text || '').split(',')) {
    const match = /^([0-9a-f]{8}):([1-5]{1,5}|\*)$/.exec(part);
    const rank = match && normalizeRank(match[2]);
    if (rank) invites.set(match[1], rank);
  }
  return invites;
}

/** Field kelompok dari TXT laptop lain; hanya bila tanda tangannya cocok dengan token kita. */
function teamFieldsFrom(txt, token) {
  if (!isSigned(token, txt)) {
    return { verified: false, invites: new Map(), leader: '', rank: null, cycle: 0, exchange: '', close: null };
  }
  const rank = normalizeRank(txt.rank);
  const close = CLOSE.exec(txt.cls || '');
  return {
    verified: true,
    invites: decodeInvites(txt.inv),
    leader: /^[0-9a-f]{8}$/.test(txt.leader || '') ? txt.leader : '',
    rank,
    cycle: Number.isFinite(Number(txt.cycle)) ? Number(txt.cycle) : 0,
    exchange: EXCHANGES.includes(txt.ex) ? txt.ex : '',
    close: close ? { seq: Number(close[1]), target: close[2], symbol: close[3] } : null,
  };
}

class Team extends EventEmitter {
  /** `myId`: id laptop ini (discovery). `token`: BOT_HUB_TOKEN atau '' (fitur kelompok mati). */
  constructor({ myId, token, now = Date.now }) {
    super();
    this.myId = myId;
    this.token = token || '';
    this.now = now;
    this.invites = new Map(); // pemimpin: id pengikut -> top
    this.cycle = 0; // pemimpin: waktu mulai putaran terakhir
    this.exchange = ''; // pemimpin: platform putaran itu (pengikut memakai platform yang sama)
    this.closeCommand = null; // pemimpin: perintah Sell terakhir { seq, target, symbol }
    this.membership = null; // pengikut: { leaderId, leaderName, rank, modal }
    this.answered = new Set(); // ajakan yang sudah dijawab atau sedang ditampilkan
    this.lastCycle = 0;
    this.lastClose = 0; // pengikut: perintah Sell terakhir yang sudah dijalankan
  }

  get enabled() {
    return this.token !== '';
  }

  /** Field kelompok untuk TXT laptop ini (ditandatangani di discovery.js). */
  fields(role) {
    if (!this.enabled) return {};
    if (this.membership) return { leader: shortId(this.membership.leaderId), rank: String(this.membership.rank) };
    if (role !== 'leader') return {};
    const fields = {};
    if (this.invites.size) fields.inv = encodeInvites(this.invites);
    if (this.cycle) {
      fields.cycle = String(this.cycle);
      if (this.exchange) fields.ex = this.exchange;
    }
    const c = this.closeCommand;
    if (c) fields.cls = `${c.seq}:${c.target}:${c.symbol}`;
    return fields;
  }

  /** Tugaskan pengikut ke Top tertentu (atau '*'); memanggil ulang = mengubah tugasnya. */
  invite(peerId, rank) {
    const normal = normalizeRank(rank);
    if (!normal) throw new Error('Top tidak valid');
    this.invites.set(peerId, normal);
  }

  /** Beri semua pengikut (yang diajak atau sudah bergabung) tugas yang sama. */
  assignAll(rank) {
    for (const id of this.invites.keys()) this.invite(id, rank);
    return this.invites.size;
  }

  uninvite(peerId) {
    this.invites.delete(peerId);
  }

  /** Pemimpin: tutup posisi pengikut. target = id pengikut atau '*'; symbol = pair atau '*'. */
  requestClose(target, symbol) {
    this.closeCommand = { seq: this.now(), target: target === '*' ? '*' : shortId(target), symbol };
  }

  startCycle(exchange = '') {
    this.cycle = this.now();
    this.exchange = EXCHANGES.includes(exchange) ? exchange : '';
  }

  accept({ leaderId, leaderName, rank, modal }) {
    this.membership = { leaderId, leaderName, rank: normalizeRank(rank), modal };
    this.invites.clear();
    this.lastCycle = 0;
    this.lastClose = this.now(); // perintah Sell sebelum bergabung tidak berlaku
  }

  decline(leaderId, rank) {
    this.answered.add(`${leaderId}:${rank}`);
  }

  leave() {
    this.membership = null;
  }

  /** Status kelompok tiap laptop untuk daftar di layar pemimpin. */
  describe(peer) {
    const following = peer.team.verified && peer.team.leader === shortId(this.myId) ? peer.team.rank : null;
    return { ...peer, invitedRank: this.invites.get(peer.id) ?? null, followerRank: following };
  }

  /**
   * Nilai pengumuman laptop lain. Memancarkan:
   * - 'invite' {leaderId, leaderName, rank}: ada ajakan baru untuk laptop ini
   * - 'start' {leaderName, rank, modal, hub}: pemimpin memulai putaran baru
   * - 'removed' {leaderName}: pemimpin mengeluarkan laptop ini dari kelompok
   * - 'close' {leaderName, symbol}: pemimpin menutup posisi laptop ini (symbol '*' = semua)
   * Mengembalikan true bila pengumuman laptop ini perlu diperbarui.
   */
  evaluate(peers) {
    if (!this.enabled) return false;
    const me = shortId(this.myId);
    let changed = false;
    const active = new Set(); // ajakan yang saat ini diumumkan untuk laptop ini
    for (const peer of peers) {
      // Ajakan dan sinyal putaran hanya dari pemegang kunci pemimpin (tanda tangan Ed25519).
      if (peer.self || !peer.team.verified || peer.role !== 'leader' || !peer.leaderVerified) continue;
      const rank = peer.team.invites.get(me);
      if (rank) active.add(`${peer.id}:${rank}`);
      const member = this.membership;
      if (member && member.leaderId === peer.id) {
        if (!rank) {
          this.membership = null;
          this.emit('removed', { leaderName: peer.name });
          changed = true;
          continue;
        }
        if (rank !== member.rank) {
          member.rank = rank;
          changed = true;
        }
        const cycle = peer.team.cycle;
        if (cycle > this.lastCycle && this.now() - cycle < CYCLE_FRESH_MS && peer.address) {
          this.lastCycle = cycle;
          this.emit('start', {
            leaderName: peer.name,
            rank: member.rank,
            modal: member.modal,
            hub: `http://${peer.address}:${HUB_PORT}`,
            ...(peer.team.exchange ? { exchange: peer.team.exchange } : {}),
          });
        }
        const close = peer.team.close;
        if (close && close.seq > this.lastClose && this.now() - close.seq < CYCLE_FRESH_MS
          && (close.target === '*' || close.target === me)) {
          this.lastClose = close.seq;
          this.emit('close', { leaderName: peer.name, symbol: close.symbol });
        }
      } else if (rank && !member && !this.answered.has(`${peer.id}:${rank}`)) {
        this.answered.add(`${peer.id}:${rank}`);
        this.emit('invite', { leaderId: peer.id, leaderName: peer.name, rank });
      }
    }
    // Jawaban hanya berlaku selama ajakannya masih diumumkan: bila dicabut, ajakan baru (walau Top
    // sama) harus muncul lagi.
    for (const key of this.answered) if (!active.has(key)) this.answered.delete(key);
    return changed;
  }
}

module.exports = {
  CYCLE_FRESH_MS,
  canonical,
  HUB_PORT,
  Team,
  decodeInvites,
  encodeInvites,
  isSigned,
  normalizeRank,
  shortId,
  sign,
  teamFieldsFrom,
};

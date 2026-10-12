'use strict';

// Kelompok pemimpin-pengikut di atas pengumuman Bonjour (discovery.js), tanpa port baru.
//
// - Pemimpin mengumumkan ajakan di TXT-nya: `inv=<id pengikut>:<top>,...`.
// - Laptop yang diajak menampilkan ajakan; pemiliknya harus menekan Terima.
// - Pengikut mengumumkan `leader=<id pemimpin>` dan `rank`.
// - Setiap putaran pemimpin dimulai, pemimpin mengumumkan `cycle=<waktu>`; pengikut yang sudah
//   menerima ikut menjalankan bot untuk putaran itu.
//
// Semua TXT ditandatangani HMAC dengan BOT_HUB_TOKEN. Data kelompok dari laptop yang tanda
// tangannya tidak cocok diabaikan, sehingga perangkat lain di WiFi tidak bisa memalsukan ajakan
// atau memicu bot.

const crypto = require('node:crypto');
const { EventEmitter } = require('node:events');

const SHORT_ID = 8;
const SIG_LENGTH = 32;
const CYCLE_FRESH_MS = 2 * 60 * 1000; // sinyal putaran lebih tua dari ini tidak memicu bot
const HUB_PORT = 8765;

const shortId = (id) => String(id).slice(0, SHORT_ID);

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

/** Map(id lengkap -> top) -> "abcd1234:2,ef567890:3". */
function encodeInvites(invites) {
  return [...invites].map(([id, rank]) => `${shortId(id)}:${rank}`).join(',');
}

/** "abcd1234:2,..." -> Map(id pendek -> top). Bagian yang tidak valid diabaikan. */
function decodeInvites(text) {
  const invites = new Map();
  for (const part of String(text || '').split(',')) {
    const match = /^([0-9a-f]{8}):([1-5])$/.exec(part);
    if (match) invites.set(match[1], Number(match[2]));
  }
  return invites;
}

/** Field kelompok dari TXT laptop lain; hanya bila tanda tangannya cocok dengan token kita. */
function teamFieldsFrom(txt, token) {
  if (!isSigned(token, txt)) return { verified: false, invites: new Map(), leader: '', rank: null, cycle: 0 };
  const rank = Number(txt.rank);
  return {
    verified: true,
    invites: decodeInvites(txt.inv),
    leader: /^[0-9a-f]{8}$/.test(txt.leader || '') ? txt.leader : '',
    rank: Number.isInteger(rank) && rank >= 1 && rank <= 5 ? rank : null,
    cycle: Number.isFinite(Number(txt.cycle)) ? Number(txt.cycle) : 0,
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
    this.membership = null; // pengikut: { leaderId, leaderName, rank, modal }
    this.answered = new Set(); // ajakan yang sudah dijawab atau sedang ditampilkan
    this.lastCycle = 0;
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
    if (this.cycle) fields.cycle = String(this.cycle);
    return fields;
  }

  invite(peerId, rank) {
    this.invites.set(peerId, rank);
  }

  uninvite(peerId) {
    this.invites.delete(peerId);
  }

  startCycle() {
    this.cycle = this.now();
  }

  accept({ leaderId, leaderName, rank, modal }) {
    this.membership = { leaderId, leaderName, rank, modal };
    this.invites.clear();
    this.lastCycle = 0;
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
   * Mengembalikan true bila pengumuman laptop ini perlu diperbarui.
   */
  evaluate(peers) {
    if (!this.enabled) return false;
    const me = shortId(this.myId);
    let changed = false;
    for (const peer of peers) {
      // Ajakan dan sinyal putaran hanya dari pemegang kunci pemimpin (tanda tangan Ed25519).
      if (peer.self || !peer.team.verified || peer.role !== 'leader' || !peer.leaderVerified) continue;
      const rank = peer.team.invites.get(me);
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
          });
        }
      } else if (rank && !member && !this.answered.has(`${peer.id}:${rank}`)) {
        this.answered.add(`${peer.id}:${rank}`);
        this.emit('invite', { leaderId: peer.id, leaderName: peer.name, rank });
      }
    }
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
  shortId,
  sign,
  teamFieldsFrom,
};

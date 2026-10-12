'use strict';

// Menemukan laptop lain yang membuka MarketForge di WiFi yang sama, lewat Bonjour/mDNS (protokol
// yang sama dengan AirDrop dan printer jaringan). Hanya aplikasi MarketForge yang mengumumkan
// layanan ini, jadi HP atau perangkat lain tidak pernah masuk daftar. Tidak memindai jaringan.
// Field kelompok (team.js) ikut diumumkan dan ditandatangani dengan token hub.

const { execFileSync } = require('node:child_process');
const crypto = require('node:crypto');
const { EventEmitter } = require('node:events');
const os = require('node:os');

const { openAsLeader, signAsLeader, verifyLeader } = require('./leaderkey');
const { canonical, sign, teamFieldsFrom } = require('./team');

const LEADER_SIGNED = ['sig', 'lsig']; // field yang tidak ikut ditandatangani kunci pemimpin

const SERVICE_TYPE = 'marketforge';
const SERVICE_PORT = 8765; // SRV wajib punya port; sama dengan port hub laptop pemimpin
const ROLES = ['single', 'leader', 'follower'];
const OS_NAMES = { darwin: 'macOS', win32: 'Windows' };
const MAX_NAME = 64;

/** Nama laptop untuk ditampilkan, mis. "MacBook-Air-Raqwan.local" -> "MacBook-Air-Raqwan". */
function laptopName(hostname = os.hostname()) {
  return hostname.replace(/\.local\.?$/i, '').slice(0, MAX_NAME) || 'Laptop';
}

/** Nama yang diberikan pemilik laptop (macOS: Nama Komputer), bukan nama host jaringan. */
function computerName(platform = process.platform) {
  if (platform === 'darwin') {
    try {
      const name = execFileSync('scutil', ['--get', 'ComputerName'], { encoding: 'utf8' }).trim();
      if (name) return name.slice(0, MAX_NAME);
    } catch {
      // pakai nama host di bawah
    }
  }
  return laptopName();
}

const MAX_ACTIVITY = 90;
const COIN = /^([A-Z0-9]{1,20}USD[TC])\|(ok|tunggu|jangan|)\|(open|skipped|analyzed)$/;
const SEALED_CHUNK = 200; // satu string TXT maksimal 255 byte: aktivitas terenkripsi dibagi e1, e2

/** Pecah aktivitas terenkripsi ke field TXT e1, e2, ... */
function sealedFields(sealed) {
  const fields = {};
  for (let i = 0; i * SEALED_CHUNK < sealed.length; i += 1) {
    fields[`e${i + 1}`] = sealed.slice(i * SEALED_CHUNK, (i + 1) * SEALED_CHUNK);
  }
  return fields;
}

const PAIR = /^[A-Z0-9]{1,20}USD[TC]$/;
const MAX_POSITIONS = 4;

/** Posisi terbuka laptop lain: [[PAIR, hasil % modal | null], ...] -> [{symbol, pnl}]. */
function positionsFrom(value) {
  if (!Array.isArray(value)) return [];
  return value.slice(0, MAX_POSITIONS)
    .filter((p) => Array.isArray(p) && PAIR.test(String(p[0])))
    .map(([symbol, pnl]) => ({ symbol, pnl: Number.isFinite(pnl) ? pnl : null }));
}

/**
 * Aktivitas terakhir laptop lain (mis. "Membuka top 2: RSRUSDT") dan hasil koin terakhirnya.
 * Dienkripsi ke kunci pemimpin: hanya laptop pemimpin yang bisa membacanya.
 */
function activityFrom(txt, verified, leaderKeys) {
  if (!verified || !leaderKeys || typeof txt.e1 !== 'string') return null;
  let sealed = '';
  for (let i = 1; typeof txt[`e${i}`] === 'string' && i <= 4; i += 1) sealed += txt[`e${i}`];
  const plain = openAsLeader(leaderKeys, sealed);
  if (!plain) return null;
  try {
    const [text, coinText, at, positions] = JSON.parse(plain);
    const coin = COIN.exec(String(coinText || ''));
    return {
      text: String(text || '').slice(0, MAX_ACTIVITY),
      coin: coin ? { symbol: coin[1], verdict: coin[2], status: coin[3] } : null,
      at: Number(at) > 0 ? Number(at) * 1000 : 0,
      positions: positionsFrom(positions),
    };
  } catch {
    return null;
  }
}

/** Layanan Bonjour -> data laptop. Isinya dari jaringan: dibatasi dan divalidasi. */
function peerFrom(service, selfId, token = '', { leaderPublic = null, leaderKeys = null } = {}) {
  const txt = service.txt || {};
  if (typeof txt.id !== 'string' || !/^[0-9a-f-]{8,40}$/.test(txt.id)) return null;
  const team = teamFieldsFrom(txt, token);
  const leaderVerified = txt.role === 'leader'
    && verifyLeader(leaderPublic, canonical(txt, LEADER_SIGNED), txt.lsig);
  return {
    id: txt.id,
    name: String(txt.name || service.host || 'Laptop').slice(0, MAX_NAME),
    role: ROLES.includes(txt.role) ? txt.role : 'single',
    running: txt.state === 'running',
    os: OS_NAMES[txt.os] || 'Lainnya',
    address: lanAddress(service),
    self: txt.id === selfId,
    team,
    leaderVerified,
    activity: activityFrom(txt, team.verified, leaderKeys),
  };
}

const IPV4 = /^\d{1,3}(\.\d{1,3}){3}$/;
// Kartu jaringan WiFi/Ethernet (macOS en0, Windows "Wi-Fi"/"Ethernet"), bukan VPN (utun, tap).
const LAN_INTERFACE = /^(en\d|eth\d|wl|wi-?fi|wlan|ethernet)/i;

/**
 * Alamat laptop lain yang bisa dihubungi dari WiFi ini. Sumber paket Bonjour (referer) didahulukan:
 * daftar alamat yang diumumkan bisa berisi alamat VPN yang tidak terjangkau laptop lain.
 */
function lanAddress(service) {
  const referer = service.referer?.address;
  if (IPV4.test(referer || '')) return referer;
  return (service.addresses || []).find((a) => IPV4.test(a)) || '';
}

/** Alamat IPv4 laptop ini di WiFi/Ethernet (untuk ditampilkan); VPN hanya bila tidak ada yang lain. */
function localAddress(interfaces = os.networkInterfaces()) {
  const candidates = Object.entries(interfaces)
    .flatMap(([name, list]) => (list || []).map((i) => ({ name, ...i })))
    .filter((i) => i.family === 'IPv4' && !i.internal);
  const lan = candidates.find((i) => LAN_INTERFACE.test(i.name));
  return (lan || candidates[0])?.address || '';
}

function sortPeers(peers) {
  return [...peers].sort((a, b) => Number(b.self) - Number(a.self) || a.name.localeCompare(b.name));
}

class Discovery extends EventEmitter {
  /** `bonjour`: objek dengan publish/find/unpublishAll/destroy (pustaka bonjour-service). */
  constructor({
    bonjour,
    name = computerName(),
    platform = process.platform,
    id = crypto.randomUUID(),
    token = '',
    leaderKeys = null, // kunci privat pemimpin (hanya di laptop pemimpin)
    leaderPublic = null, // kunci publik pemimpin (di semua laptop kelompok)
  }) {
    super();
    this.leaderKeys = leaderKeys;
    this.leaderPublic = leaderPublic;
    this.bonjour = bonjour;
    this.id = id;
    this.name = name;
    this.platform = platform;
    this.token = token;
    this.role = 'single';
    this.running = false;
    this.extra = {};
    this.service = null;
    this.stopping = false;
    this.browser = null;
    this.peers = new Map();
  }

  /** Mulai mengumumkan laptop ini dan mendengarkan laptop lain. */
  start() {
    this.publish();
    this.browser = this.bonjour.find({ type: SERVICE_TYPE }, (service) => this.seen(service));
    this.browser.on?.('txt-update', (service) => this.seen(service));
    this.browser.on?.('down', (service) => this.gone(service));
  }

  txt() {
    const txt = {
      id: this.id,
      name: this.name,
      role: this.role,
      state: this.running ? 'running' : 'idle',
      os: this.platform,
      ...this.extra,
    };
    if (this.role === 'leader' && this.leaderKeys) {
      txt.lsig = signAsLeader(this.leaderKeys, canonical(txt, LEADER_SIGNED));
    }
    if (this.token) txt.sig = sign(this.token, txt);
    return txt;
  }

  /**
   * Umumkan laptop ini. Diulang setiap peran, status bot, atau data kelompok berubah.
   * Pengumuman lama dicabut dulu sampai selesai: paket pencabutannya bisa terbaca sebagai nama
   * yang bentrok oleh pengumuman baru ("Service name is already in use") sehingga peran baru
   * tidak pernah terkirim. Perubahan selama pencabutan digabung menjadi satu pengumuman.
   */
  publish() {
    if (this.stopping) return; // announce() setelah pencabutan memakai data terbaru
    const old = this.service;
    if (!old) {
      this.announce();
      return;
    }
    this.stopping = true;
    this.service = null;
    old.stop(() => {
      this.stopping = false;
      this.announce();
    });
  }

  announce() {
    this.service = this.bonjour.publish({
      name: `MarketForge ${this.id.slice(0, 8)}`,
      // Nama host sendiri: memakai nama host macOS membuat mDNSResponder menganggapnya bentrok
      // lalu mengganti nama Mac (MacBook-Air-2, -3, ...).
      host: `marketforge-${this.id.slice(0, 8)}.local`,
      type: SERVICE_TYPE,
      port: SERVICE_PORT,
      // Nama layanan memakai id acak laptop ini, jadi tidak mungkin bentrok: lewati pengecekan.
      probe: false,
      txt: this.txt(),
    });
  }

  update({ role = this.role, running = this.running, extra = this.extra } = {}) {
    const next = ROLES.includes(role) ? role : this.role;
    const same = next === this.role && running === this.running
      && JSON.stringify(extra) === JSON.stringify(this.extra);
    if (same && this.service) return;
    this.role = next;
    this.running = running;
    this.extra = { ...extra };
    this.publish();
  }

  seen(service) {
    const peer = peerFrom(service, this.id, this.token, {
      leaderPublic: this.leaderPublic,
      leaderKeys: this.leaderKeys,
    });
    if (!peer || peer.self) return;
    peer.seenAt = Date.now(); // dipakai pemimpin untuk menilai pengikut masih tersambung
    this.peers.set(peer.id, peer);
    this.emit('peers', this.snapshot());
  }

  gone(service) {
    const id = service.txt?.id;
    if (id && this.peers.delete(id)) this.emit('peers', this.snapshot());
  }

  /** Laptop ini (paling atas) dan laptop lain yang terakhir terdengar. */
  snapshot() {
    const self = {
      id: this.id,
      name: this.name,
      role: this.role,
      running: this.running,
      os: OS_NAMES[this.platform] || 'Lainnya',
      address: localAddress(),
      self: true,
      team: teamFieldsFrom({}, ''),
      leaderVerified: this.role === 'leader' && Boolean(this.leaderKeys),
      activity: null,
    };
    return sortPeers([self, ...this.peers.values()]);
  }

  /** Minta semua laptop mengumumkan ulang, tunggu sebentar, lalu kembalikan daftarnya. */
  async list(timeoutMs = 2000) {
    this.browser?.update?.();
    await new Promise((resolve) => setTimeout(resolve, timeoutMs));
    return this.snapshot();
  }

  /** Pamit di jaringan, lalu tutup. Koneksi baru ditutup setelah paket pamit terkirim. */
  stop(done = () => {}) {
    this.browser?.stop?.();
    this.bonjour.unpublishAll(() => {
      this.bonjour.destroy();
      done();
    });
  }
}

module.exports = {
  COIN, Discovery, MAX_ACTIVITY, SERVICE_TYPE, computerName, laptopName, localAddress, peerFrom, sealedFields,
};

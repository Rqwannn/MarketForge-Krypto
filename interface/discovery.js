'use strict';

// Menemukan laptop lain yang membuka MarketForge di WiFi yang sama, lewat Bonjour/mDNS (protokol
// yang sama dengan AirDrop dan printer jaringan). Hanya aplikasi MarketForge yang mengumumkan
// layanan ini, jadi HP atau perangkat lain tidak pernah masuk daftar. Tidak memindai jaringan.

const { execFileSync } = require('node:child_process');
const crypto = require('node:crypto');
const os = require('node:os');

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

/** Layanan Bonjour -> data laptop. Isinya dari jaringan: dibatasi dan divalidasi. */
function peerFrom(service, selfId) {
  const txt = service.txt || {};
  if (typeof txt.id !== 'string' || !/^[0-9a-f-]{8,40}$/.test(txt.id)) return null;
  return {
    id: txt.id,
    name: String(txt.name || service.host || 'Laptop').slice(0, MAX_NAME),
    role: ROLES.includes(txt.role) ? txt.role : 'single',
    running: txt.state === 'running',
    os: OS_NAMES[txt.os] || 'Lainnya',
    address: (service.addresses || []).find((a) => /^\d+\.\d+\.\d+\.\d+$/.test(a)) || '',
    self: txt.id === selfId,
  };
}

function sortPeers(peers) {
  return [...peers].sort((a, b) => Number(b.self) - Number(a.self) || a.name.localeCompare(b.name));
}

class Discovery {
  /** `bonjour`: objek dengan publish/find/unpublishAll/destroy (pustaka bonjour-service). */
  constructor({ bonjour, name = computerName(), platform = process.platform, id = crypto.randomUUID() }) {
    this.bonjour = bonjour;
    this.id = id;
    this.name = name;
    this.platform = platform;
    this.role = 'single';
    this.running = false;
    this.service = null;
  }

  /** Umumkan laptop ini. Diulang setiap peran atau status bot berubah. */
  publish() {
    if (this.service) this.service.stop?.();
    this.service = this.bonjour.publish({
      name: `MarketForge ${this.id.slice(0, 8)}`,
      // Nama host sendiri: memakai nama host macOS membuat mDNSResponder menganggapnya bentrok
      // lalu mengganti nama Mac (MacBook-Air-2, -3, ...).
      host: `marketforge-${this.id.slice(0, 8)}.local`,
      type: SERVICE_TYPE,
      port: SERVICE_PORT,
      txt: {
        id: this.id,
        name: this.name,
        role: this.role,
        state: this.running ? 'running' : 'idle',
        os: this.platform,
      },
    });
  }

  update({ role = this.role, running = this.running } = {}) {
    const next = ROLES.includes(role) ? role : this.role;
    if (next === this.role && running === this.running && this.service) return;
    this.role = next;
    this.running = running;
    this.publish();
  }

  /** Cari laptop selama `timeoutMs`. Laptop ini selalu ada di daftar, paling atas. */
  async list(timeoutMs = 2500) {
    const peers = new Map();
    const browser = this.bonjour.find({ type: SERVICE_TYPE }, (service) => {
      const peer = peerFrom(service, this.id);
      if (peer) peers.set(peer.id, peer);
    });
    await new Promise((resolve) => setTimeout(resolve, timeoutMs));
    browser.stop();
    if (!peers.has(this.id)) {
      peers.set(this.id, {
        id: this.id,
        name: this.name,
        role: this.role,
        running: this.running,
        os: OS_NAMES[this.platform] || 'Lainnya',
        address: '',
        self: true,
      });
    }
    return sortPeers(peers.values());
  }

  stop() {
    this.bonjour.unpublishAll();
    this.bonjour.destroy();
  }
}

module.exports = { Discovery, SERVICE_TYPE, computerName, laptopName, peerFrom };

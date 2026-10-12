'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');

const { Discovery, SERVICE_TYPE, laptopName, localAddress, peerFrom } = require('../discovery');
const { sign } = require('../team');

const SELF = '11111111-2222-3333-4444-555555555555';
const ATTA = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee';
const TOKEN = 'token-uji';

/** Bonjour tiruan: mencatat publikasi; `browser` bisa memutar layanan yang "terdengar". */
function fakeBonjour() {
  const fake = { published: [], stopped: 0, destroyed: false, updates: 0 };
  fake.browser = Object.assign(new EventEmitter(), { stop() {}, update() { fake.updates += 1; } });
  fake.pendingStops = [];
  fake.publish = (opts) => {
    fake.published.push(opts);
    return { stop: (done) => { fake.stopped += 1; fake.pendingStops.push(done); } };
  };
  /** Selesaikan pencabutan pengumuman yang sedang berjalan (paket goodbye terkirim). */
  fake.finishStops = () => fake.pendingStops.splice(0).forEach((done) => done());
  fake.find = (opts, onup) => {
    assert.equal(opts.type, SERVICE_TYPE);
    fake.browser.on('up', onup);
    return fake.browser;
  };
  fake.unpublishAll = () => {};
  fake.destroy = () => { fake.destroyed = true; };
  return fake;
}

function service(txt, address = '192.168.1.30') {
  return { host: 'x.local', addresses: ['fe80::1', address], txt };
}

test('nama laptop tanpa akhiran .local; alamat IPv4 lokal', () => {
  assert.equal(laptopName('MacBook-Air-Raqwan.local'), 'MacBook-Air-Raqwan');
  assert.equal(localAddress({ lo0: [{ family: 'IPv4', internal: true, address: '127.0.0.1' }], en0: [{ family: 'IPv4', internal: false, address: '192.168.1.19' }] }), '192.168.1.19');
  // VPN (utun) tercantum lebih dulu: WiFi tetap didahulukan
  assert.equal(localAddress({ utun4: [{ family: 'IPv4', internal: false, address: '10.190.129.250' }], en0: [{ family: 'IPv4', internal: false, address: '192.168.1.19' }] }), '192.168.1.19');
  assert.equal(localAddress({ 'Wi-Fi': [{ family: 'IPv4', internal: false, address: '192.168.1.30' }] }), '192.168.1.30');
});

test('alamat laptop lain: sumber paket WiFi didahulukan dari alamat VPN yang diumumkan', () => {
  const svc = { addresses: ['10.190.129.250', '192.168.1.30'], referer: { address: '192.168.1.30' }, txt: { id: ATTA } };
  assert.equal(peerFrom(svc, SELF).address, '192.168.1.30');
  assert.equal(peerFrom({ addresses: ['fe80::1', '192.168.1.31'], txt: { id: ATTA } }, SELF).address, '192.168.1.31');
});

test('laptop ini diumumkan dengan peran, status, nama host sendiri, dan tanda tangan', () => {
  const bonjour = fakeBonjour();
  const discovery = new Discovery({ bonjour, id: SELF, name: 'MacBook', platform: 'darwin', token: TOKEN });
  discovery.start();
  discovery.update({ role: 'leader' });
  bonjour.finishStops();
  const txt = bonjour.published.at(-1).txt;
  assert.equal(txt.role, 'leader');
  assert.equal(txt.state, 'idle');
  assert.equal(txt.sig, sign(TOKEN, txt));
  // nama host sendiri, bukan nama host Mac (supaya macOS tidak mengganti nama komputernya)
  assert.equal(bonjour.published.at(-1).host, `marketforge-${SELF.slice(0, 8)}.local`);

  bonjour.finishStops();
  assert.equal(bonjour.published.at(-1).probe, false); // nama acak: tanpa pengecekan bentrok
  const count = bonjour.published.length;
  discovery.update({ role: 'leader' }); // tidak berubah: tidak diumumkan ulang
  assert.equal(bonjour.published.length, count);
  discovery.update({ running: true, extra: { cycle: '5' } });
  bonjour.finishStops();
  assert.equal(bonjour.published.length, count + 1);
  assert.equal(bonjour.published.at(-1).txt.cycle, '5');
  discovery.update({ role: 'jual' }); // peran tidak dikenal diabaikan
  assert.equal(bonjour.published.at(-1).txt.role, 'leader');
});

test('ganti peran: pengumuman baru dikirim setelah pengumuman lama selesai dicabut', () => {
  const bonjour = fakeBonjour();
  const discovery = new Discovery({ bonjour, id: SELF, name: 'MacBook', platform: 'darwin' });
  discovery.start();
  const count = bonjour.published.length;
  discovery.update({ role: 'leader' });
  discovery.update({ role: 'single' }); // berubah lagi sebelum pencabutan selesai
  assert.equal(bonjour.published.length, count); // belum diumumkan selama pencabutan
  bonjour.finishStops();
  assert.equal(bonjour.published.length, count + 1); // digabung menjadi satu pengumuman
  assert.equal(bonjour.published.at(-1).txt.role, 'single');
  assert.equal(discovery.snapshot()[0].role, 'single');
});

test('laptop lain terdengar terus; laptop ini selalu di atas; pergi saat goodbye', async () => {
  const bonjour = fakeBonjour();
  const discovery = new Discovery({ bonjour, id: SELF, name: 'MacBook', platform: 'darwin' });
  const seen = [];
  discovery.on('peers', (peers) => seen.push(peers.length));
  discovery.start();
  const atta = service({ id: ATTA, name: 'LAPTOP-ATTA', role: 'follower', state: 'running', os: 'win32' });
  bonjour.browser.emit('up', atta);
  bonjour.browser.emit('up', atta);
  bonjour.browser.emit('up', service({ txt: {} }.txt || {}));
  const peers = await discovery.list(5);
  assert.equal(bonjour.updates, 1); // daftar meminta pengumuman ulang
  assert.deepEqual(peers.map((p) => [p.name, p.self]), [['MacBook', true], ['LAPTOP-ATTA', false]]);
  assert.equal(peers[1].os, 'Windows');
  assert.equal(peers[1].address, '192.168.1.30');
  assert.equal(peers[1].running, true);

  bonjour.browser.emit('down', atta);
  assert.equal(discovery.snapshot().length, 1);
  assert.deepEqual(seen, [2, 2, 1]);
});

test('data dari jaringan divalidasi; field kelompok hanya dari tanda tangan yang cocok', () => {
  assert.equal(peerFrom({ txt: { id: 'bukan id; <script>' } }, SELF), null);
  const peer = peerFrom({ txt: { id: ATTA, name: 'x'.repeat(500), role: 'admin', os: 'linux' } }, SELF);
  assert.equal(peer.name.length, 64);
  assert.equal(peer.role, 'single');

  const txt = { id: ATTA, name: 'Pemimpin', role: 'leader', state: 'idle', os: 'darwin', inv: '11111111:2' };
  const signed = { ...txt, sig: sign(TOKEN, txt) };
  assert.equal(peerFrom({ txt: signed }, SELF, TOKEN).team.invites.get('11111111'), 2);
  assert.equal(peerFrom({ txt: signed }, SELF, 'token-lain').team.verified, false);
  assert.equal(peerFrom({ txt: { ...signed, inv: '11111111:5' } }, SELF, TOKEN).team.verified, false); // diubah
});

test('berhenti: pengumuman dicabut', () => {
  const bonjour = fakeBonjour();
  const discovery = new Discovery({ bonjour, id: SELF });
  discovery.start();
  discovery.stop();
  assert.equal(bonjour.destroyed, true);
});

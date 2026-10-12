'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const { Discovery, SERVICE_TYPE, laptopName, peerFrom } = require('../discovery');

const SELF = '11111111-2222-3333-4444-555555555555';
const ATTA = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee';

/** Bonjour tiruan: mencatat publikasi dan memutar layanan yang "ditemukan" di jaringan. */
function fakeBonjour(found = []) {
  const fake = { published: [], stopped: 0, destroyed: false, browsers: 0 };
  fake.publish = (opts) => {
    const service = { opts, stop: () => { fake.stopped += 1; } };
    fake.published.push(opts);
    return service;
  };
  fake.find = (opts, onup) => {
    assert.equal(opts.type, SERVICE_TYPE);
    fake.browsers += 1;
    setTimeout(() => found.forEach(onup), 5);
    return { stop: () => {} };
  };
  fake.unpublishAll = () => {};
  fake.destroy = () => { fake.destroyed = true; };
  return fake;
}

test('nama laptop tanpa akhiran .local', () => {
  assert.equal(laptopName('MacBook-Air-Raqwan.local'), 'MacBook-Air-Raqwan');
  assert.equal(laptopName('LAPTOP-ATTA'), 'LAPTOP-ATTA');
});

test('laptop ini diumumkan dengan peran dan status, diumumkan ulang bila berubah', () => {
  const bonjour = fakeBonjour();
  const discovery = new Discovery({ bonjour, id: SELF, name: 'MacBook', platform: 'darwin' });
  discovery.update({ role: 'leader', running: false });
  assert.deepEqual(bonjour.published[0].txt, { id: SELF, name: 'MacBook', role: 'leader', state: 'idle', os: 'darwin' });
  assert.equal(bonjour.published[0].type, SERVICE_TYPE);
  // nama host sendiri, bukan nama host Mac (supaya macOS tidak mengganti nama komputernya)
  assert.equal(bonjour.published[0].host, `marketforge-${SELF.slice(0, 8)}.local`);

  discovery.update({ role: 'leader', running: false }); // tidak berubah: tidak diumumkan ulang
  assert.equal(bonjour.published.length, 1);
  discovery.update({ running: true });
  assert.equal(bonjour.published.length, 2);
  assert.equal(bonjour.stopped, 1); // pengumuman lama dihentikan dulu
  assert.equal(bonjour.published[1].txt.state, 'running');

  discovery.update({ role: 'jual' }); // peran tidak dikenal diabaikan
  assert.equal(bonjour.published.at(-1).txt.role, 'leader');
});

test('daftar: laptop ini di atas, laptop lain dari jaringan, tanpa duplikat', async () => {
  const atta = { host: 'LAPTOP-ATTA.local', addresses: ['fe80::1', '192.168.1.30'], txt: { id: ATTA, name: 'LAPTOP-ATTA', role: 'follower', state: 'running', os: 'win32' } };
  const bonjour = fakeBonjour([atta, atta, { host: 'printer.local', txt: {} }]);
  const discovery = new Discovery({ bonjour, id: SELF, name: 'MacBook', platform: 'darwin' });
  discovery.update({ role: 'leader' });

  const peers = await discovery.list(30);
  assert.deepEqual(peers.map((p) => [p.name, p.self]), [['MacBook', true], ['LAPTOP-ATTA', false]]);
  assert.deepEqual(peers[1], {
    id: ATTA, name: 'LAPTOP-ATTA', role: 'follower', running: true, os: 'Windows', address: '192.168.1.30', self: false,
  });
});

test('data dari jaringan divalidasi', () => {
  assert.equal(peerFrom({ txt: { id: 'bukan id; <script>' } }, SELF), null);
  assert.equal(peerFrom({ txt: {} }, SELF), null);
  const peer = peerFrom({ txt: { id: ATTA, name: 'x'.repeat(500), role: 'admin', os: 'linux' } }, SELF);
  assert.equal(peer.name.length, 64);
  assert.equal(peer.role, 'single');
  assert.equal(peer.os, 'Lainnya');
});

test('berhenti: pengumuman dicabut', () => {
  const bonjour = fakeBonjour();
  new Discovery({ bonjour, id: SELF }).stop();
  assert.equal(bonjour.destroyed, true);
});

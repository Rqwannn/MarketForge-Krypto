'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const { CYCLE_FRESH_MS, Team, decodeInvites, encodeInvites, teamFieldsFrom, sign } = require('../team');

const TOKEN = 'token-uji';
const LEADER = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee';
const ME = '11111111-2222-3333-4444-555555555555';
const NOW = 1_800_000_000_000;

/** Laptop pemimpin seperti yang terlihat di jaringan (TXT ditandatangani). */
function leaderPeer(extra = {}, token = TOKEN, leaderVerified = true) {
  const txt = { id: LEADER, name: 'MacBook Pemimpin', role: 'leader', state: 'idle', os: 'darwin', ...extra };
  const signed = { ...txt, sig: sign(token, txt) };
  return {
    id: LEADER, name: 'MacBook Pemimpin', role: 'leader', address: '192.168.1.19', self: false,
    team: teamFieldsFrom(signed, TOKEN), leaderVerified,
  };
}

function follower() {
  const team = new Team({ myId: ME, token: TOKEN, now: () => NOW });
  const events = [];
  for (const name of ['invite', 'start', 'removed', 'close']) team.on(name, (e) => events.push([name, e]));
  return { team, events };
}

test('ajakan dikodekan singkat dan bagian rusak diabaikan', () => {
  assert.equal(encodeInvites(new Map([[ME, 2], [LEADER, 5]])), '11111111:2,aaaaaaaa:5');
  assert.deepEqual([...decodeInvites('11111111:2,zzz:9,aaaaaaaa:7,aaaaaaaa:3')], [['11111111', 2], ['aaaaaaaa', 3]]);
});

test('pemimpin mengumumkan ajakan dan putaran; tanpa token tidak ada fitur kelompok', () => {
  const team = new Team({ myId: LEADER, token: TOKEN, now: () => NOW });
  team.invite(ME, 2);
  team.startCycle();
  assert.deepEqual(team.fields('leader'), { inv: '11111111:2', cycle: String(NOW) });
  assert.deepEqual(team.fields('single'), {}); // bukan pemimpin: tidak mengajak
  assert.deepEqual(new Team({ myId: LEADER, token: '' }).fields('leader'), {});
});

test('ajakan muncul sekali; setelah diterima, putaran baru pemimpin memicu bot pengikut', () => {
  const { team, events } = follower();
  team.evaluate([leaderPeer({ inv: '11111111:2' })]);
  team.evaluate([leaderPeer({ inv: '11111111:2' })]); // tidak ditampilkan dua kali
  assert.deepEqual(events, [['invite', { leaderId: LEADER, leaderName: 'MacBook Pemimpin', rank: 2 }]]);

  team.accept({ leaderId: LEADER, leaderName: 'MacBook Pemimpin', rank: 2, modal: '100' });
  assert.deepEqual(team.fields('follower'), { leader: 'aaaaaaaa', rank: '2' });

  team.evaluate([leaderPeer({ inv: '11111111:2', cycle: String(NOW - 1000) })]);
  team.evaluate([leaderPeer({ inv: '11111111:2', cycle: String(NOW - 1000) })]); // putaran sama: sekali
  assert.deepEqual(events.at(-1), ['start', { leaderName: 'MacBook Pemimpin', rank: 2, modal: '100', hub: 'http://192.168.1.19:8765' }]);
  assert.equal(events.filter(([name]) => name === 'start').length, 1);
});

test('laptop bertoken hub tapi tanpa kunci pemimpin tidak bisa mengajak atau memicu bot', () => {
  const { team, events } = follower();
  team.evaluate([leaderPeer({ inv: '11111111:2' }, TOKEN, false)]);
  team.accept({ leaderId: LEADER, leaderName: 'P', rank: 2, modal: '100' });
  team.evaluate([leaderPeer({ inv: '11111111:2', cycle: String(NOW) }, TOKEN, false)]);
  assert.deepEqual(events, []);
});

test('putaran lama tidak memicu bot', () => {
  const { team, events } = follower();
  team.accept({ leaderId: LEADER, leaderName: 'P', rank: 1, modal: '100' });
  team.evaluate([leaderPeer({ inv: '11111111:1', cycle: String(NOW - CYCLE_FRESH_MS - 1) })]);
  assert.deepEqual(events, []);
});

test('pengumuman palsu (token lain) tidak menghasilkan ajakan atau memicu bot', () => {
  const { team, events } = follower();
  team.evaluate([leaderPeer({ inv: '11111111:2' }, 'token-penyusup')]);
  team.accept({ leaderId: LEADER, leaderName: 'P', rank: 2, modal: '100' });
  team.evaluate([leaderPeer({ inv: '11111111:2', cycle: String(NOW) }, 'token-penyusup')]);
  assert.deepEqual(events, []);
});

test('ajakan yang ditolak tidak muncul lagi; pemimpin mengeluarkan pengikut', () => {
  const { team, events } = follower();
  team.decline(LEADER, 3);
  team.evaluate([leaderPeer({ inv: '11111111:3' })]);
  assert.deepEqual(events, []);

  team.accept({ leaderId: LEADER, leaderName: 'P', rank: 3, modal: '100' });
  assert.equal(team.evaluate([leaderPeer({})]), true); // ajakan dicabut
  assert.equal(team.membership, null);
  assert.deepEqual(events.at(-1), ['removed', { leaderName: 'MacBook Pemimpin' }]);
});

test('daftar pemimpin: status diajak dan sudah menjadi pengikut', () => {
  const team = new Team({ myId: LEADER, token: TOKEN });
  team.invite(ME, 4);
  const txt = { id: ME, name: 'Laptop', role: 'follower', state: 'idle', os: 'win32', leader: 'aaaaaaaa', rank: '4' };
  const peer = { id: ME, name: 'Laptop', role: 'follower', self: false, team: teamFieldsFrom({ ...txt, sig: sign(TOKEN, txt) }, TOKEN) };
  assert.deepEqual([team.describe(peer).invitedRank, team.describe(peer).followerRank], [4, 4]);
});

test('perintah Sell pemimpin: hanya untuk pengikutnya, sekali, masih baru, dan bukan dari sebelum bergabung', () => {
  const leader = new Team({ myId: LEADER, token: TOKEN, now: () => NOW });
  leader.requestClose(ME, 'CKBUSDT');
  assert.equal(leader.fields('leader').cls, `${NOW}:11111111:CKBUSDT`);
  leader.requestClose('*', '*');
  assert.equal(leader.fields('leader').cls, `${NOW}:*:*`);

  const { team, events } = follower();
  team.accept({ leaderId: LEADER, leaderName: 'P', rank: 2, modal: '100' });
  const closes = () => events.filter(([name]) => name === 'close');
  team.evaluate([leaderPeer({ inv: '11111111:2', cls: `${NOW - 5000}:11111111:CKBUSDT` })]);
  assert.equal(closes().length, 0); // dikirim sebelum laptop ini bergabung
  team.lastClose = 0;
  team.evaluate([leaderPeer({ inv: '11111111:2', cls: `${NOW - 1000}:11111111:CKBUSDT` })]);
  team.evaluate([leaderPeer({ inv: '11111111:2', cls: `${NOW - 1000}:11111111:CKBUSDT` })]); // sama: sekali
  team.evaluate([leaderPeer({ inv: '11111111:2', cls: `${NOW - 900}:22222222:WUSDT` })]); // pengikut lain
  team.evaluate([leaderPeer({ inv: '11111111:2', cls: `${NOW - CYCLE_FRESH_MS - 1}:*:*` })]); // basi
  assert.deepEqual(closes(), [['close', { leaderName: 'MacBook Pemimpin', symbol: 'CKBUSDT' }]]);
  team.evaluate([leaderPeer({ inv: '11111111:2', cls: `${NOW - 500}:*:*` })]);
  assert.deepEqual(closes().at(-1), ['close', { leaderName: 'MacBook Pemimpin', symbol: '*' }]);
});

test('perintah Sell dari laptop tanpa kunci pemimpin diabaikan', () => {
  const { team, events } = follower();
  team.accept({ leaderId: LEADER, leaderName: 'P', rank: 2, modal: '100' });
  team.lastClose = 0;
  team.evaluate([leaderPeer({ inv: '11111111:2', cls: `${NOW - 1000}:*:*` }, TOKEN, false)]);
  assert.deepEqual(events.filter(([name]) => name === 'close'), []);
});

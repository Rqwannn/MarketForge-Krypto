'use strict';

// Kunci pemimpin: hanya laptop yang memegang kunci privat (BOT_LEADER_KEY) yang bisa menjadi
// pemimpin. Laptop lain cukup memegang kunci publiknya (BOT_LEADER_PUBLIC) untuk:
// - memverifikasi pengumuman pemimpin (ajakan, sinyal putaran) dengan tanda tangan Ed25519;
// - mengenkripsi aktivitasnya ke pemimpin (X25519 + AES-256-GCM), sehingga hanya pemimpin yang
//   bisa memantaunya walaupun pengumuman Bonjour terbaca semua perangkat di WiFi.
// Memegang token hub saja tidak cukup untuk menjadi pemimpin.
//
// Buat sekali dengan `make leader-key` di laptop pemimpin.

const crypto = require('node:crypto');

const PRIVATE_PREFIX = 'mfpriv1.';
const PUBLIC_PREFIX = 'mfpub1.';
const HKDF_INFO = 'marketforge-activity-v1';

const b64 = (buf) => Buffer.from(buf).toString('base64url');
const unb64 = (text) => Buffer.from(String(text), 'base64url');

function encode(prefix, value) {
  return prefix + b64(JSON.stringify(value));
}

function decode(prefix, text) {
  const raw = String(text || '').trim();
  if (!raw.startsWith(prefix)) return null;
  try {
    return JSON.parse(unb64(raw.slice(prefix.length)).toString('utf8'));
  } catch {
    return null;
  }
}

/** Buat pasangan kunci baru: { privateText (laptop pemimpin), publicText (semua laptop) }. */
function generateLeaderKeys() {
  const sign = crypto.generateKeyPairSync('ed25519').privateKey.export({ format: 'jwk' });
  const box = crypto.generateKeyPairSync('x25519').privateKey.export({ format: 'jwk' });
  return {
    privateText: encode(PRIVATE_PREFIX, { sign, box }),
    publicText: encode(PUBLIC_PREFIX, { sign: sign.x, box: box.x }),
  };
}

function publicFromRaw(sign, box) {
  return {
    verifyKey: crypto.createPublicKey({ key: { kty: 'OKP', crv: 'Ed25519', x: sign }, format: 'jwk' }),
    boxKey: crypto.createPublicKey({ key: { kty: 'OKP', crv: 'X25519', x: box }, format: 'jwk' }),
    text: encode(PUBLIC_PREFIX, { sign, box }),
  };
}

/** BOT_LEADER_PUBLIC -> kunci publik, atau null bila kosong/tidak valid. */
function loadLeaderPublic(text) {
  const value = decode(PUBLIC_PREFIX, text);
  if (!value || typeof value.sign !== 'string' || typeof value.box !== 'string') return null;
  try {
    return publicFromRaw(value.sign, value.box);
  } catch {
    return null;
  }
}

/** BOT_LEADER_KEY -> kunci privat (+ publiknya), atau null bila kosong/tidak valid. */
function loadLeaderKey(text) {
  const value = decode(PRIVATE_PREFIX, text);
  if (!value?.sign?.d || !value?.box?.d) return null;
  try {
    return {
      signKey: crypto.createPrivateKey({ key: { ...value.sign, kty: 'OKP', crv: 'Ed25519' }, format: 'jwk' }),
      boxKey: crypto.createPrivateKey({ key: { ...value.box, kty: 'OKP', crv: 'X25519' }, format: 'jwk' }),
      public: publicFromRaw(value.sign.x, value.box.x),
    };
  } catch {
    return null;
  }
}

/** Tanda tangan pemimpin atas teks kanonik pengumuman. */
function signAsLeader(keys, message) {
  return b64(crypto.sign(null, Buffer.from(message), keys.signKey));
}

function verifyLeader(pub, message, signature) {
  if (!pub || typeof signature !== 'string' || !signature) return false;
  try {
    return crypto.verify(null, Buffer.from(message), pub.verifyKey, unb64(signature));
  } catch {
    return false;
  }
}

function aesKey(shared, salt) {
  return Buffer.from(crypto.hkdfSync('sha256', shared, salt, HKDF_INFO, 32));
}

/** Enkripsi `plaintext` agar hanya pemegang kunci privat pemimpin yang bisa membacanya. */
function sealForLeader(pub, plaintext) {
  const eph = crypto.generateKeyPairSync('x25519');
  const ephRaw = unb64(eph.publicKey.export({ format: 'jwk' }).x);
  const shared = crypto.diffieHellman({ privateKey: eph.privateKey, publicKey: pub.boxKey });
  const iv = crypto.randomBytes(12);
  const cipher = crypto.createCipheriv('aes-256-gcm', aesKey(shared, ephRaw), iv);
  const body = Buffer.concat([cipher.update(String(plaintext), 'utf8'), cipher.final()]);
  return b64(Buffer.concat([ephRaw, iv, cipher.getAuthTag(), body]));
}

/** Buka pesan dari sealForLeader. null bila bukan untuk kunci ini atau rusak. */
function openAsLeader(keys, sealed) {
  try {
    const raw = unb64(sealed);
    if (raw.length < 32 + 12 + 16) return null;
    const ephRaw = raw.subarray(0, 32);
    const ephPub = crypto.createPublicKey({ key: { kty: 'OKP', crv: 'X25519', x: b64(ephRaw) }, format: 'jwk' });
    const shared = crypto.diffieHellman({ privateKey: keys.boxKey, publicKey: ephPub });
    const decipher = crypto.createDecipheriv('aes-256-gcm', aesKey(shared, ephRaw), raw.subarray(32, 44));
    decipher.setAuthTag(raw.subarray(44, 60));
    return Buffer.concat([decipher.update(raw.subarray(60)), decipher.final()]).toString('utf8');
  } catch {
    return null;
  }
}

module.exports = {
  generateLeaderKeys,
  loadLeaderKey,
  loadLeaderPublic,
  openAsLeader,
  sealForLeader,
  signAsLeader,
  verifyLeader,
};

// --------------------------------------------------------------------------- password admin
// `make leader-key` hanya jalan dengan password admin. Yang disimpan di .env hanya hash-nya
// (BOT_LEADER_PASSWORD_HASH, scrypt + salt acak), bukan password-nya, dan tidak ada di kode.

const fs = require('node:fs');
const path = require('node:path');

const PASSWORD_KEY = 'BOT_LEADER_PASSWORD_HASH';
const SCRYPT = { N: 16384, r: 8, p: 1 };

function hashPassword(password, salt = crypto.randomBytes(16)) {
  const hash = crypto.scryptSync(String(password), salt, 32, SCRYPT);
  return `scrypt$${b64(salt)}$${b64(hash)}`;
}

function verifyPassword(password, stored) {
  const [kind, salt, hash] = String(stored || '').split('$');
  if (kind !== 'scrypt' || !salt || !hash) return false;
  const want = unb64(hash);
  const got = crypto.scryptSync(String(password), unb64(salt), want.length, SCRYPT);
  return got.length === want.length && crypto.timingSafeEqual(got, want);
}

/** Ganti atau tambah KEY=VALUE di file .env; baris lain dipertahankan, izin file 600. */
function setEnvValue(file, key, value) {
  const text = fs.existsSync(file) ? fs.readFileSync(file, 'utf8') : '';
  const lines = text === '' ? [] : text.replace(/\n$/, '').split('\n');
  let found = false;
  const out = lines.map((line) => {
    if (line.split('=')[0].trim() !== key || line.trim().startsWith('#')) return line;
    found = true;
    return `${key}=${value}`;
  });
  if (!found) out.push(`${key}=${value}`);
  fs.writeFileSync(file, `${out.join('\n')}\n`, { encoding: 'utf8', mode: 0o600 });
  fs.chmodSync(file, 0o600);
}

/** Minta input tanpa menampilkan ketikan (TTY); dari pipe dibaca satu baris. */
function askHidden(prompt) {
  return new Promise((resolve) => {
    const input = process.stdin;
    process.stderr.write(prompt);
    if (!input.isTTY) {
      let data = '';
      input.setEncoding('utf8');
      input.on('data', (chunk) => { data += chunk; });
      input.on('end', () => resolve(data.split(/\r?\n/)[0]));
      return;
    }
    let value = '';
    input.setRawMode(true);
    input.resume();
    input.setEncoding('utf8');
    const onData = (chunk) => {
      for (const ch of chunk) {
        if (ch === '\r' || ch === '\n') {
          input.setRawMode(false);
          input.pause();
          input.removeListener('data', onData);
          process.stderr.write('\n');
          resolve(value);
          return;
        }
        if (ch === '\u0003') process.exit(130); // Ctrl+C
        if (ch === '\u007f' || ch === '\b') value = value.slice(0, -1);
        else value += ch;
      }
    };
    input.on('data', onData);
  });
}

async function main(argv) {
  const engine = require('./engine');
  const envFile = path.join(engine.ENGINE_DIR, '.env');
  const stored = engine.appSetting(PASSWORD_KEY);

  if (argv.includes('--set-password')) {
    if (stored && !verifyPassword(await askHidden('Password lama: '), stored)) {
      console.error('Password lama salah. Tidak ada yang diubah.');
      return 1;
    }
    const first = await askHidden('Password baru: ');
    const second = process.stdin.isTTY ? await askHidden('Ulangi password baru: ') : first;
    if (first.length < 8 || first !== second) {
      console.error('Password baru minimal 8 karakter dan harus sama saat diulang.');
      return 1;
    }
    setEnvValue(envFile, PASSWORD_KEY, hashPassword(first));
    console.error(`Hash password disimpan di ${path.relative(process.cwd(), envFile)} (${PASSWORD_KEY}).`);
    return 0;
  }

  if (!stored) {
    console.error(`Password admin belum diatur. Jalankan dulu: make leader-password`);
    return 1;
  }
  if (!verifyPassword(await askHidden('Password admin: '), stored)) {
    console.error('Password salah. Kunci pemimpin tidak dibuat.');
    return 1;
  }
  const { privateText, publicText } = generateLeaderKeys();
  console.log('# Laptop PEMIMPIN saja (rahasia, jangan dibagikan) -> .env:');
  console.log(`BOT_LEADER_KEY=${privateText}`);
  console.log('');
  console.log('# Boleh dibagikan ke semua laptop pengikut -> .env:');
  console.log(`BOT_LEADER_PUBLIC=${publicText}`);
  return 0;
}

module.exports.hashPassword = hashPassword;
module.exports.verifyPassword = verifyPassword;
module.exports.setEnvValue = setEnvValue;

if (require.main === module) {
  main(process.argv.slice(2)).then((code) => process.exit(code));
}

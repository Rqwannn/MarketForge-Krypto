'use strict';

// Nama aplikasi di bar menu macOS dan Dock. Electron versi pengembangan selalu bernama "Electron"
// (diambil dari Info.plist bundel, tidak bisa diganti saat berjalan). Di macOS, salinan bundel
// bernama "MarketForge Kripto" dibuat sekali di node_modules dan ditandatangani ulang secara
// lokal (ad-hoc, sama seperti bundel aslinya); dibuat ulang bila versi Electron berganti.
// Windows: nama di taskbar diambil dari judul jendela dan AppUserModelId (main.js).

const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');

const BRAND = 'MarketForge Kripto';
const BUNDLE_ID = 'com.marketforge.kripto';
const MARKER = 'brand.txt'; // isi: versi Electron + nama, penanda salinan masih cocok
const ICON = path.join(__dirname, 'assets', 'icon.png');

/** `.../Electron.app/Contents/MacOS/Electron` -> folder `.../Electron.app`. */
function bundleOf(executable) {
  return path.resolve(executable, '..', '..', '..');
}

function plistValue(plist, key, run) {
  return String(run('/usr/libexec/PlistBuddy', ['-c', `Print :${key}`, plist])).trim();
}

/**
 * Executable Electron bermerek (macOS), atau `executable` apa adanya bila bukan macOS atau gagal.
 * `run(cmd, args)` dan `files` bisa diganti di tes.
 */
function brandedExecutable(executable, { platform = process.platform, run = defaultRun, files = fs, log = console.warn } = {}) {
  if (platform !== 'darwin') return executable;
  const source = bundleOf(executable);
  const target = path.join(path.dirname(source), `${BRAND}.app`);
  const branded = path.join(target, 'Contents', 'MacOS', path.basename(executable));
  try {
    const version = plistValue(path.join(source, 'Contents', 'Info.plist'), 'CFBundleVersion', run);
    const stamp = `${version} ${BRAND}`;
    const marker = `${target}.${MARKER}`; // di luar bundel: file di dalamnya merusak segel tanda tangan
    if (files.existsSync(branded) && files.existsSync(marker) && files.readFileSync(marker, 'utf8') === stamp) {
      return branded;
    }
    files.rmSync(target, { recursive: true, force: true });
    // Tanpa resource fork/atribut Finder: codesign menolak bundel yang membawanya.
    run('/usr/bin/ditto', ['--norsrc', '--noextattr', '--noqtn', source, target]);
    const plist = path.join(target, 'Contents', 'Info.plist');
    for (const [key, value] of [['CFBundleName', BRAND], ['CFBundleDisplayName', BRAND], ['CFBundleIdentifier', BUNDLE_ID]]) {
      run('/usr/bin/plutil', ['-replace', key, '-string', value, plist]);
    }
    try { // ikon MarketForge untuk Dock, Finder, dan notifikasi; gagal = ikon Electron tetap
      const icon = plistValue(plist, 'CFBundleIconFile', run);
      run('/usr/bin/sips', ['-s', 'format', 'icns', ICON, '--out', path.join(target, 'Contents', 'Resources', icon)]);
    } catch {
      // bukan masalah
    }
    run('/usr/bin/xattr', ['-cr', target]); // sips dan plutil bisa menambah atribut lagi
    run('/usr/bin/codesign', ['--force', '--deep', '--sign', '-', target]);
    files.writeFileSync(marker, stamp);
    return branded;
  } catch (err) {
    log(`Nama ${BRAND} belum bisa dipasang (${err.message}); aplikasi dibuka sebagai Electron.`);
    return executable;
  }
}

function defaultRun(cmd, args) {
  return execFileSync(cmd, args, { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] });
}

module.exports = { BRAND, BUNDLE_ID, brandedExecutable };

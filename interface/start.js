'use strict';

// Membuka aplikasi Electron di macOS, Linux, dan Windows. Pengganti `env -u ELECTRON_RUN_AS_NODE
// electron .` yang hanya jalan di shell Unix: variabel itu dibuang agar Electron tidak berjalan
// sebagai Node biasa (mis. bila dijalankan dari terminal sebuah aplikasi Electron lain).

const { spawn } = require('node:child_process');

let electron;
try {
  electron = require('electron'); // jalur ke binary Electron
} catch {
  console.error('Electron belum terpasang. Jalankan: npm ci (di folder interface).');
  process.exit(1);
}

const env = { ...process.env };
delete env.ELECTRON_RUN_AS_NODE;

const child = spawn(electron, ['.'], { cwd: __dirname, env, stdio: 'inherit' });
child.on('exit', (code, signal) => {
  if (signal) process.kill(process.pid, signal);
  else process.exit(code ?? 0);
});
child.on('error', (err) => {
  console.error(`Electron gagal dibuka: ${err.message}`);
  process.exit(1);
});

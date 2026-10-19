'use strict';

// Jam pasar dunia: jam kota, status buka/tutup bursa saham, dan ramai-sepinya pasar kripto menurut
// sesi Asia, Eropa, dan Amerika. Murni fungsi tanpa DOM supaya bisa diuji di Node; app.js yang
// menggambarnya. Zona waktu memakai Intl, jadi pergantian jam musim (Eropa 25 Okt, AS 1 Nov 2026)
// ikut benar. Hari libur bursa tidak diperhitungkan.

(function (root) {
  const HOME = { city: 'Jakarta', tz: 'Asia/Jakarta', label: 'WIB', offset: 7 * 60 };

  // Sesi dalam menit sejak tengah malam waktu setempat, Senin-Jumat.
  const MARKETS = [
    { id: 'ny', city: 'New York', region: 'Amerika', tz: 'America/New_York', exchange: 'NYSE · Nasdaq', sessions: [[570, 960]] },
    { id: 'london', city: 'London', region: 'Eropa', tz: 'Europe/London', exchange: 'LSE', sessions: [[480, 990]] },
    { id: 'tokyo', city: 'Tokyo', region: 'Asia', tz: 'Asia/Tokyo', exchange: 'TSE', sessions: [[540, 690], [750, 930]] },
    { id: 'hk', city: 'Hong Kong', region: 'Asia', tz: 'Asia/Hong_Kong', exchange: 'HKEX', sessions: [[570, 720], [780, 960]] },
    { id: 'sg', city: 'Singapura', region: 'Asia', tz: 'Asia/Singapore', exchange: 'SGX', sessions: [[540, 1020]] },
  ];

  const WEEKDAYS = { Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6, Sun: 7 };
  const formatters = new Map();

  function formatter(tz) {
    if (!formatters.has(tz)) {
      formatters.set(tz, new Intl.DateTimeFormat('en-GB', {
        timeZone: tz, hourCycle: 'h23', weekday: 'short', year: 'numeric', month: 'numeric',
        day: 'numeric', hour: 'numeric', minute: 'numeric', second: 'numeric',
      }));
    }
    return formatters.get(tz);
  }

  /** Waktu dinding `date` di zona `tz`. weekday: Senin = 1 ... Minggu = 7. */
  function zoned(date, tz) {
    const parts = {};
    for (const p of formatter(tz).formatToParts(date)) parts[p.type] = p.value;
    const hour = Number(parts.hour);
    const minute = Number(parts.minute);
    const second = Number(parts.second);
    return {
      year: Number(parts.year), month: Number(parts.month), day: Number(parts.day),
      hour, minute, second, weekday: WEEKDAYS[parts.weekday],
      minutes: hour * 60 + minute, // menit sejak tengah malam
      exact: hour * 60 + minute + second / 60,
    };
  }

  /** Selisih zona terhadap UTC dalam menit (New York musim panas = -240). */
  function offsetMinutes(tz, date) {
    const z = zoned(date, tz);
    const wall = Date.UTC(z.year, z.month - 1, z.day, z.hour, z.minute, z.second);
    return Math.round((wall - Math.floor(date.getTime() / 1000) * 1000) / 60000);
  }

  const pad = (n) => String(n).padStart(2, '0');

  function clockText(date, tz, { seconds = false } = {}) {
    const z = zoned(date, tz);
    return `${pad(z.hour)}:${pad(z.minute)}${seconds ? `:${pad(z.second)}` : ''}`;
  }

  /** "2 j 15 m", "45 m", "1 hari 3 j". */
  function duration(minutes) {
    const total = Math.max(0, Math.round(minutes));
    if (total < 1) return 'kurang dari 1 m';
    const days = Math.floor(total / 1440);
    const hours = Math.floor((total % 1440) / 60);
    const mins = total % 60;
    if (days > 0) return hours ? `${days} hari ${hours} j` : `${days} hari`;
    if (hours > 0) return mins ? `${hours} j ${mins} m` : `${hours} j`;
    return `${mins} m`;
  }

  /** Saat bursa `market` berikutnya buka setelah `date`, atau null. */
  function nextOpen(market, date) {
    const z = zoned(date, market.tz);
    for (let d = 0; d <= 8; d += 1) {
      const weekday = ((z.weekday - 1 + d) % 7) + 1;
      if (weekday > 5) continue;
      for (const [start] of market.sessions) {
        const delta = d * 1440 + start - z.exact;
        if (delta <= 0) continue;
        let candidate = new Date(date.getTime() + delta * 60000);
        // Pergantian jam musim di antara dua waktu itu menggeser satu jam: samakan dengan jam dinding.
        const wall = zoned(candidate, market.tz).minutes;
        if (wall !== start) candidate = new Date(candidate.getTime() + (start - wall) * 60000);
        return candidate;
      }
    }
    return null;
  }

  /**
   * Status bursa pada `date`: { state: 'buka' | 'istirahat' | 'tutup', note }.
   * note: sisa waktu sampai tutup atau buka berikutnya.
   */
  function marketStatus(market, date) {
    const z = zoned(date, market.tz);
    if (z.weekday <= 5) {
      for (let i = 0; i < market.sessions.length; i += 1) {
        const [start, end] = market.sessions[i];
        if (z.exact >= start && z.exact < end) {
          return { state: 'buka', note: `tutup dalam ${duration(end - z.exact)}` };
        }
        const next = market.sessions[i + 1];
        if (next && z.exact >= end && z.exact < next[0]) {
          return { state: 'istirahat', note: `buka lagi dalam ${duration(next[0] - z.exact)}` };
        }
      }
    }
    const open = nextOpen(market, date);
    const weekend = z.weekday > 5;
    const wait = open ? duration((open.getTime() - date.getTime()) / 60000) : null;
    return {
      state: 'tutup',
      note: weekend ? `akhir pekan, buka dalam ${wait}` : wait ? `buka dalam ${wait}` : 'tutup',
    };
  }

  // Ramai-sepinya kripto menurut sesi. Batas dihitung dari jam bursa (bukan jam WIB tetap) supaya
  // ikut bergeser saat jam musim berganti: Asia buka 00.00 UTC, Eropa 08.00 London, puncak 08.00-14.00
  // New York (rilis data AS 08.30 dan bursa AS buka 09.30), menurun sampai bursa AS tutup, lalu sepi
  // sampai Asia buka lagi.
  const PHASES = [
    { id: 'asia', label: 'Sedang', note: 'Sesi Asia buka', level: 2 },
    { id: 'eu', label: 'Naik bertahap', note: 'Eropa buka, menuju sesi Amerika', level: 3 },
    { id: 'peak', label: 'Paling ramai', note: 'Eropa dan Amerika aktif bersamaan', level: 5 },
    { id: 'decline', label: 'Mulai menurun', note: 'Bursa AS masih buka, Eropa sudah tutup', level: 3 },
    { id: 'quiet', label: 'Paling sepi', note: 'Amerika tutup, Asia belum buka', level: 1 },
  ];

  const mod = (n, m) => ((n % m) + m) % m;

  /** Batas awal tiap fase dalam menit UTC pada hari `date`, berurutan. */
  function phaseStarts(date) {
    const ny = offsetMinutes('America/New_York', date);
    const london = offsetMinutes('Europe/London', date);
    return [0, mod(480 - london, 1440), mod(480 - ny, 1440), mod(840 - ny, 1440), mod(960 - ny, 1440)];
  }

  /** Fase kripto pada `date` beserta rentang jamnya (WIB). */
  function cryptoPhase(date) {
    const starts = phaseStarts(date);
    const utc = date.getUTCHours() * 60 + date.getUTCMinutes();
    let index = 0;
    for (let i = 0; i < starts.length; i += 1) if (utc >= starts[i]) index = i;
    const from = starts[index];
    const to = index + 1 < starts.length ? starts[index + 1] : 1440;
    const wib = (m) => { const t = mod(m + HOME.offset, 1440); return `${pad(Math.floor(t / 60))}.${pad(t % 60)}`; };
    const day = date.getUTCDay(); // 0 = Minggu, 6 = Sabtu
    return {
      ...PHASES[index],
      range: `${wib(from)}–${wib(to)} WIB`,
      weekend: day === 0 || day === 6,
    };
  }

  const STEP_MIN = 10;

  /** Garis waktu 24 jam (hari WIB yang memuat `date`): sesi tiap bursa dan fase kripto, dalam pecahan 0..1. */
  function daySegments(date) {
    const wib = zoned(date, HOME.tz);
    const start = Date.UTC(wib.year, wib.month - 1, wib.day) - HOME.offset * 60000;
    const steps = 1440 / STEP_MIN;
    const merge = (values) => {
      const out = [];
      values.forEach((value, i) => {
        const last = out[out.length - 1];
        if (last && last.value === value) last.to = (i + 1) / steps;
        else out.push({ value, from: i / steps, to: (i + 1) / steps });
      });
      return out;
    };
    const instants = Array.from({ length: steps }, (_, i) => new Date(start + (i + 0.5) * STEP_MIN * 60000));
    return {
      startMs: start,
      now: (date.getTime() - start) / 86400000,
      markets: MARKETS.map((m) => ({
        id: m.id,
        city: m.city,
        open: merge(instants.map((t) => marketStatus(m, t).state === 'buka')).filter((s) => s.value),
      })),
      phases: merge(instants.map((t) => cryptoPhase(t).id)),
    };
  }

  const api = { HOME, MARKETS, PHASES, zoned, offsetMinutes, clockText, duration, nextOpen, marketStatus, cryptoPhase, daySegments };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.WorldClock = api;
})(typeof window !== 'undefined' ? window : globalThis);

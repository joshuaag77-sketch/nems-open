// Shared by 2050.html and engine3d.html: the instant estimate (data/ux2050/emulator.json), the lever
// address both pages read, and a finished real run handed from one page to the other.
(function () {
  "use strict";
  // Lever order is part of the signature a real run is stored under; keep it fixed.
  const KEYS = ["carbon_price", "ev_2035", "load_growth", "building_code", "appliance_standard",
    "coal_retirement", "renewable_cost", "gas_supply", "oil_price", "nuclear"];
  const REAL_ONLY = ["building_code", "appliance_standard"];

  function defaults(emu) {
    return Object.fromEntries(KEYS.map((k) => [k, emu.levers[k] ? emu.levers[k].off : 0]));
  }
  const sig = (x) => KEYS.map((k) => `${k}=${(+x[k]).toFixed(3)}`).join("&");

  function poly(emu, x) {
    const names = Object.keys(emu.levers);
    const z = names.map((n) => { const L = emu.levers[n]; return 2 * (x[n] - L.low) / (L.high - L.low) - 1; });
    const f = emu.terms.map((t) => t.reduce((a, i) => a * z[i], 1));
    const out = {};
    for (const [k, coef] of Object.entries(emu.coef)) {
      const ny = coef[0].length, y = new Array(ny).fill(0);
      for (let t = 0; t < coef.length; t++) { const ft = f[t]; if (ft === 0) continue; const row = coef[t]; for (let j = 0; j < ny; j++) y[j] += row[j] * ft; }
      out[k] = y;
    }
    return out;
  }
  const refCache = new WeakMap();
  // The polynomial, shifted so EIA's settings return the reference run exactly (the fit was measured that way).
  function emulate(emu, x) {
    const raw = poly(emu, x);
    if (!refCache.has(emu)) refCache.set(emu, poly(emu, Object.fromEntries(Object.entries(emu.levers).map(([n, L]) => [n, L.off]))));
    const ref = refCache.get(emu), out = {};
    for (const k in raw) {
      const y = raw[k].map((v, j) => v - ref[k][j] + emu.fast_reference[k][j]);
      out[k] = k.startsWith("co2") ? y : y.map((v) => Math.max(0, v));   // a polynomial can dip below zero
    }
    return out;
  }

  // The levers in an address: "carbon_price:100,ev_2035:0.9". Only levers away from EIA's settings.
  function encode(emu, x) {
    const d = defaults(emu);
    return KEYS.filter((k) => Math.abs(x[k] - d[k]) > 1e-9).map((k) => `${k}:${+(+x[k]).toFixed(3)}`).join(",");
  }
  function decode(emu, s) {
    const x = defaults(emu);
    for (const kv of (s || "").split(",")) {
      const [k, v] = kv.split(":");
      if (KEYS.includes(k) && v !== undefined && isFinite(+v)) x[k] = +v;
    }
    return x;
  }

  // A real run the 2050 page finished, kept for this tab only (sessionStorage can be missing or full).
  function saveReal(x, job) { try { sessionStorage.setItem("ux2050:real:" + sig(x), JSON.stringify(job)); } catch (e) { /* not kept */ } }
  function loadReal(x) { try { return JSON.parse(sessionStorage.getItem("ux2050:real:" + sig(x)) || "null"); } catch (e) { return null; } }

  window.UX2050 = { KEYS, REAL_ONLY, defaults, sig, emulate, encode, decode, saveReal, loadReal };
})();

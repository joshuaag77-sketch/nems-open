// NEMS Open engine: EIA's NEMS in 3D, drawn from data read out of EIA's release
// (scripts/engine_structure.py), the runs (scripts/engine_runs.py) and the grades
// (scripts/fidelity.py). Nothing here is placed by hand except the layout.
(async function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const load = (u) => fetch(u).then((r) => { if (!r.ok) throw new Error(`${u}: ${r.status}`); return r.json(); });
  let S, R, RUNS, FID;
  try {
    [S, R, RUNS, FID] = await Promise.all(["data/engine3d/structure.json", "data/engine3d/routines.json",
      "data/engine3d/runs.json", "data/fidelity.json"].map(load));
  } catch (e) {
    $("err").style.display = "grid";
    $("err").textContent = "The engine's data did not load. Serve the web folder (python -m http.server --directory web) and open engine3d.html from there.";
    return;
  }

  await new Promise((ok) => { const s = document.createElement("script"); s.src = "data/datacenter.js"; s.onload = s.onerror = ok; document.head.appendChild(s); });
  const DC = window.NEMS_DATACENTER;
  const STORY = [];
  if (DC && FID.sets.datacenter) {
    Object.entries(DC.cases).forEach(([k, c]) => {
      const key = "dc_" + k;
      STORY.push(key);
      RUNS.scenarios[key] = { key, label: c.label, set: "datacenter", story: true, raw: c, short: DC.case_notes[k].short,
        run: { co2: c.co2, bill: c.bill, gas_price: c.prices.gas_home }, eia: RUNS.scenarios.reference.eia };
    });
  }

  // A fractional change as a percent, in plain decimals.
  const pctText = (x) => (100 * x < 0.01 ? (100 * x).toPrecision(2) : (100 * x).toFixed(2)) + "%";

  function flatView() {
    document.body.classList.add("flat");
    const esc = (x) => String(x).replace(/&/g, "&amp;").replace(/</g, "&lt;");
    const name = { match: "Matches EIA", partial: "Partly ported", stand: "Stand-in, fitted to EIA side cases", fixed: "EIA's own path" };
    $("hero-text").textContent = `${S.counts.switches.toLocaleString("en-US")} switches go in. Thirteen modules trade prices and quantities through ` +
      `${S.counts.outputs.toLocaleString("en-US")} shared variables until they agree, every year to 2050. The 3D view needs a larger screen; here are the same facts.`;
    $("flat").innerHTML = `<h2>Modules</h2>` + S.modules.map((m) => {
      const g = grade(m);
      const links = S.edges.filter((e) => e.from === m.key && e.shown && !e.hub).map((e) => S.modules.find((x) => x.key === e.to).name);
      return `<div class="fm"><b>${esc(m.name)}</b> <span class="fg ${g.grade}">${name[g.grade]}</span>
        <p>${esc(g.text)}</p>
        <p class="dim">${m.routines ? `${m.routines.toLocaleString("en-US")} routines, ${m.ported_routines} ported. ` : `${esc(m.language)} model. `}` +
        `Reads ${m.reads.toLocaleString("en-US")} shared variables, writes ${m.writes.toLocaleString("en-US")}.` +
        `${links.length ? ` Feeds ${links.map(esc).join(", ")}.` : ""}</p></div>`;
    }).join("");
    const showYear = () => {
      const ps = RUNS.trace.convergence[yearEl.value] || [];
      $("counter").innerHTML = `<b>${yearEl.value}: ${ps.length} passes to agree.</b> ` + ps.map((p) =>
        `Pass ${p.itr}: prices moved up to ${pctText(p.dp)}${p.itr === 1 ? " (the first pass is not tested)" : `, quantities ${pctText(p.dq)}`}.`).join(" ");
    };
    yearEl.addEventListener("input", showYear); showYear();
    $("status").textContent = "Recorded runs, not live.";
    $("note").textContent = `Read from EIA's AEO2026 release on ${S.generated}. Precomputed, not live.`;
  }

  // ---- grades ------------------------------------------------------------------------
  const COLOR = { match: 0x1D9E75, partial: 0xEF9F27, stand: 0x888780, fixed: 0x4a4945,
                  input: 0x7F77DD, output: 0x5DCAA5, hub: 0xFAC775 };
  const GRADE_TEXT = { match: "Matches EIA", partial: "Partly ported", stand: "Stand-in", fixed: "EIA's own path" };
  // Wiring: which fidelity parts (data/fidelity.json) stand behind each engine module.
  const PARTS = {
    residential: ["port:residential"], commercial: ["port:commercial"], transportation: ["port:transportation"],
    industrial: ["stand:demand_stub"], electricity: ["port:ldsm", "port:efp", "own:dispatch", "stand:electricity"],
    coal: ["stand:coal"], natural_gas: ["stand:natural_gas"], oil_gas_supply: ["stand:oil"], refining: ["stand:oil"],
    economy: [], renewables: [], hydrogen: [], international: [],
  };
  function grade(m) {
    const parts = (PARTS[m.key] || []).filter((p) => FID.parts[p]);
    const g = parts.map((p) => FID.parts[p].grade);
    const share = m.fortran_lines ? m.ported_lines / m.fortran_lines : 0;
    if (!parts.length) return { grade: "fixed", parts, share,
      text: "Not modeled here yet: the loop uses EIA's own published path for this module." };
    if (g.every((x) => x === "match") && share > 0.8) return { grade: "match", parts, share, text: FID.parts[parts[0]].summary };
    if (g.some((x) => x !== "stand") || m.ported_routines > 0) return { grade: "partial", parts, share,
      text: `${Math.round(share * 100)}% of its Fortran lines ported and checked against EIA's code; the rest runs on stand-ins.` };
    return { grade: "stand", parts, share, text: FID.parts[parts[0]].summary };
  }

  // ---- the year, and the address (#a=high_gas_price&b=reference&y=2035&sw=AB32SW&m=coal) -----
  const yearEl = $("year"), yearOut = $("year-out");
  const traceYears = Object.keys(RUNS.trace.convergence).map(Number);
  yearEl.min = Math.min(...traceYears); yearEl.max = Math.max(...traceYears);
  yearEl.value = yearEl.max; yearOut.textContent = yearEl.max;
  yearEl.addEventListener("input", () => { yearOut.textContent = yearEl.value; });
  const asked = new URLSearchParams(location.hash.slice(1));
  let followKey = null, openMod = null, mapOn = false;
  let dollarOn = false;
  function writeHash() {
    const q = new URLSearchParams();
    if (selA !== "reference") q.set("a", selA);
    if (selB) q.set("b", selB);
    q.set("y", yearEl.value);
    if (followKey) q.set("sw", followKey);
    if (openMod) q.set("m", openMod);
    if (mapOn) q.set("map", "1");
    if (dollarOn) q.set("d", "1");
    history.replaceState(null, "", "#" + q.toString());
  }

  // ---- scenario cards and diff-two-runs (data/engine3d/runs.json, scenarios) -------------
  const SC = RUNS.scenarios, YEARS = RUNS.years;
  let OUT = FID.sets.fast.outputs;     // the grades of the set the selected run belongs to
  const RANK = { match: 0, within: 1, stand: 2 };
  const worst = (keys) => keys.map((k) => OUT[k]).filter(Boolean).sort((a, b) => RANK[b.grade] - RANK[a.grade])[0];
  // Each headline and the demo numbers its grade comes from (data/fidelity.json): the bill is
  // home fuel use times home prices, so it is only as good as the weakest of those.
  const HEADS = {
    co2: { label: "US energy CO2", unit: " Mt", d: 0, grade: () => OUT.co2 },
    bill: { label: "Household energy bill", unit: " a year", d: 0, pre: "$", grade: () => worst(["energy.residential", "pel", "ng"]) },
    gas_price: { label: "Home natural gas price", unit: " per MMBtu", d: 2, pre: "$", grade: () => OUT.ng },
  };
  let selA = RUNS.scenarios[asked.get("a")] ? asked.get("a") : "reference";
  let selB = RUNS.scenarios[asked.get("b")] && asked.get("b") !== selA ? asked.get("b") : null;
  let comparing = !!selB;
  let stepFrom = null;                 // the data center step we came from: the diff shows the change
  let onStep = null;                   // set once the scene exists: the ring animates the change
  if (traceYears.includes(+asked.get("y"))) { yearEl.value = +asked.get("y"); yearOut.textContent = yearEl.value; }
  $("compare").setAttribute("aria-pressed", comparing);
  const year = () => +yearEl.value;
  const val = (key, m, src = "run") => SC[key][src][m][YEARS.indexOf(year())];
  const num = (x, d) => Number(x).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
  const escA = (x) => String(x).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");

  function cards() {
    const card = (s) => `<button type="button" class="card ${s.key === selA ? "a" : ""} ${s.key === selB ? "b" : ""}" data-k="${s.key}">${s.label}` +
      `<small>${s.story ? `${escA(s.short)} Ported modules and dispatch LP, precomputed.` : `EIA's ${s.case} case inputs, ${s.model}, precomputed`}</small></button>`;
    const all = Object.values(SC);
    $("cards").innerHTML = all.filter((s) => !s.story).map(card).join("") +
      (STORY.length ? `<div class="scen-head story-head"><span>Data center story</span><button class="ghost small" id="step-through" type="button">Step through</button></div>` +
        all.filter((s) => s.story).map(card).join("") : "");
    $("cards").querySelectorAll("[data-k]").forEach((b) => b.addEventListener("click", () => pick(b.dataset.k)));
    const st = $("step-through");
    if (st) st.addEventListener("click", stepThrough);
  }
  function pick(k) {
    if (comparing && k !== selA) selB = selB === k ? null : k;
    else {
      stepFrom = SC[selA].story && SC[k].story && selA !== k ? selA : null;
      selA = k;
      if (selB === k) selB = null;
    }
    render(true);
    if (onStep) onStep(stepFrom, selA);
  }
  let stepping = false;
  async function stepThrough() {
    if (stepping) return;
    stepping = true;
    comparing = false; selB = null; $("compare").setAttribute("aria-pressed", false);
    if (+yearEl.value === +yearEl.max) { yearEl.value = 2035; yearEl.dispatchEvent(new Event("input")); }
    selA = "reference";
    for (const k of STORY) { pick(k); await new Promise((ok) => setTimeout(ok, 3600)); }
    stepping = false;
  }
  let tweenId = 0;
  function heads(animate) {
    const id = ++tweenId, t0 = performance.now(), dur = animate ? 900 : 0;
    const ref = (m) => SC.reference.eia[m][YEARS.indexOf(year())];
    $("heads").innerHTML = Object.entries(HEADS).map(([m, h]) => {
      const g = h.grade();
      return `<div class="head"><span class="k">${h.label}, ${year()}</span>` +
        (g ? `<span class="pill ${g.grade}" title="${escA(g.summary)}">${g.label_grade}</span>` : "<span></span>") +
        `<span class="v" data-m="${m}"></span><span class="from">EIA reference ${h.pre || ""}${num(ref(m), h.d)}${h.unit}</span></div>`;
    }).join("");
    const step = (now) => {
      if (id !== tweenId) return;
      const f = dur ? Math.min(1, (now - t0) / dur) : 1, e = 1 - Math.pow(1 - f, 3);
      $("heads").querySelectorAll("[data-m]").forEach((el) => {
        const m = el.dataset.m, h = HEADS[m], from = ref(m), to = val(selA, m);
        el.textContent = `${h.pre || ""}${num(from + (to - from) * e, h.d)}${h.unit}`;
      });
      if (f < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }
  function spark(a, b) {
    const w = 260, h = 30, all = a.concat(b), lo = Math.min(...all), hi = Math.max(...all), span = hi - lo || 1;
    const path = (s) => s.map((v, i) => `${i ? "L" : "M"}${(i / (s.length - 1)) * w},${h - ((v - lo) / span) * h}`).join("");
    return `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true"><path d="${path(a)}" fill="none" stroke="#1D9E75" stroke-width="1.5"/>` +
      `<path d="${path(b)}" fill="none" stroke="#FAC775" stroke-width="1.5" stroke-dasharray="4 3"/></svg>`;
  }
  function diff() {
    const pair = selB ? [selA, selB] : stepFrom ? [stepFrom, selA] : null;
    if (!pair) { $("diff").innerHTML = comparing ? `<span class="k" style="color:var(--dim)">Pick a second scenario.</span>` : ""; return; }
    const A = SC[pair[0]], B = SC[pair[1]];
    $("diff").innerHTML = `<span style="color:var(--muted)">${B.label} minus ${A.label}, ${year()}</span>` +
      Object.entries(HEADS).map(([m, h]) => {
        const d = val(B.key, m) - val(A.key, m), p = val(A.key, m) ? (100 * d) / val(A.key, m) : 0;
        const cls = Math.abs(p) < 0.05 ? "" : d > 0 ? "up" : "down";
        return `<div><span class="k">${h.label}</span> <span class="d ${cls}">${d >= 0 ? "+" : "-"}${h.pre || ""}${num(Math.abs(d), h.d)}${h.unit} (${p >= 0 ? "+" : ""}${p.toFixed(1)}%)</span>` +
          spark(A.run[m].slice(YEARS.indexOf(RUNS.start_year)), B.run[m].slice(YEARS.indexOf(RUNS.start_year))) + `</div>`;
      }).join("") +
      `<span class="k" style="color:var(--dim)">Lines: ${A.label} solid, ${B.label} dashed, ${RUNS.start_year}-${YEARS[YEARS.length - 1]}.</span>`;
  }
  function render(animate) {
    OUT = (FID.sets[SC[selA].set || "fast"] || FID.sets.fast).outputs;
    cards(); heads(animate); diff(); writeHash();
    if (onStep && stepFrom) onStep(stepFrom, selA, true);
  }
  $("compare").addEventListener("click", () => {
    comparing = !comparing; $("compare").setAttribute("aria-pressed", comparing);
    if (!comparing) selB = null;
    render(false);
  });
  yearEl.addEventListener("input", () => render(false));
  render(true);

  // ---- phones and browsers without WebGL: the same facts, flat -------------------------------
  const webgl = (() => { try { return !!document.createElement("canvas").getContext("webgl"); } catch (e) { return false; } })();
  if (innerWidth < 700 || !webgl) { flatView(); return; }

  if (innerWidth < 1280) { $("scen").classList.add("shut"); $("scen-toggle").textContent = "Show scenarios"; $("scen-toggle").setAttribute("aria-expanded", false); }

  // ---- scene -------------------------------------------------------------------------
  const canvas = $("c");
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  const scene = new THREE.Scene();
  scene.fog = new THREE.FogExp2(0x07090d, 0.0032);
  const camera = new THREE.PerspectiveCamera(50, 1, 0.1, 3000);
  const controls = new THREE.OrbitControls(camera, canvas);
  controls.enableDamping = true; controls.autoRotate = true; controls.autoRotateSpeed = 0.3;
  // The scene is about 400 units wide. Back the camera off until it fits the space the scenario
  // panel leaves free, and slide it into that space, so no module hides behind the panel.
  const PANEL_W = 328, LEFT_W = 360;
  const rightW = () => ($("scen").classList.contains("shut") ? 0 : PANEL_W);
  const leftW = () => ($("panel").style.display === "block" ? LEFT_W : 0);
  const freeW = () => innerWidth - rightW() - leftW();
  let framed = "";
  function frame() {
    framed = `${rightW()}:${leftW()}`;
    const x = (rightW() - leftW()) / 2;
    if (!x) camera.clearViewOffset(); else camera.setViewOffset(innerWidth, innerHeight, x, 0, innerWidth, innerHeight);
    camera.updateProjectionMatrix();
  }
  const home = () => {
    const d = Math.max(310, (340 * innerHeight) / (freeW() * 0.9326));
    camera.position.set(0, d * 0.24, d); controls.target.set(0, 0, 0); frame();
  };
  home();
  $("scen-toggle").addEventListener("click", () => {
    const shut = $("scen").classList.toggle("shut");
    $("scen-toggle").textContent = shut ? "Show scenarios" : "Hide";
    $("scen-toggle").setAttribute("aria-expanded", !shut);
    home();
  });

  // A seeded random, so the layout is the same on every load.
  function rng(seed) { return () => { seed |= 0; seed = (seed + 0x6D2B79F5) | 0; let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }
  const V = (x, y, z) => new THREE.Vector3(x, y, z);
  function inBall(rand, r) {
    const u = rand(), v = rand(), t = 2 * Math.PI * u, p = Math.acos(2 * v - 1), rr = r * Math.cbrt(rand());
    return V(rr * Math.sin(p) * Math.cos(t), rr * Math.sin(p) * Math.sin(t), rr * Math.cos(p));
  }
  const additive = { transparent: true, depthWrite: false, blending: THREE.AdditiveBlending };
  function segments(pairs, color, opacity) {
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(pairs.flatMap(([a, b]) => [a.x, a.y, a.z, b.x, b.y, b.z]), 3));
    const l = new THREE.LineSegments(g, new THREE.LineBasicMaterial({ color, opacity, ...additive }));
    scene.add(l); return l;
  }
  const dotGeo = new THREE.IcosahedronGeometry(1, 1);
  function dots(items, posOf, sizeOf, colorOf, opacity = 0.95) {
    const mesh = new THREE.InstancedMesh(dotGeo, new THREE.MeshBasicMaterial({ opacity, ...additive }), items.length);
    const m4 = new THREE.Matrix4(), q = new THREE.Quaternion(), c = new THREE.Color();
    items.forEach((it, i) => {
      const s = sizeOf(it, i);
      m4.compose(posOf(it, i), q, V(s, s, s));
      mesh.setMatrixAt(i, m4);
      it.hex = colorOf(it, i);
      mesh.setColorAt(i, c.setHex(it.hex));
    });
    mesh.instanceMatrix.needsUpdate = true; if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
    scene.add(mesh); return mesh;
  }

  // ---- modules on a ring around the integrating hub ----------------------------------
  const hub = V(0, 0, 0);
  const hubMesh = new THREE.Mesh(new THREE.IcosahedronGeometry(7, 1), new THREE.MeshBasicMaterial({ color: COLOR.hub, wireframe: true, transparent: true, opacity: 0.7 }));
  scene.add(hubMesh);
  const MODS = S.modules;
  const byKey = Object.fromEntries(MODS.map((m) => [m.key, m]));
  const maxLines = Math.max(...MODS.map((m) => m.fortran_lines + m.other_lines));
  const ringR = 78;
  const routinesBy = {};
  R.routines.forEach((r) => (routinesBy[r.module] = routinesBy[r.module] || []).push(r));
  MODS.forEach((m, i) => {
    const a = (i / MODS.length) * Math.PI * 2;
    m.center = V(Math.cos(a) * ringR, Math.sin(a * 2) * 12, Math.sin(a) * ringR);
    m.radius = 4 + 16 * Math.sqrt((m.fortran_lines + m.other_lines) / maxLines);
    m.g = grade(m);
    m.color = COLOR[m.g.grade];
    const rand = rng(i + 1);
    const rs = routinesBy[m.key] || [];
    if (rs.length) {
      // one dot per routine, sized by its length; ported routines in the "matches EIA" color
      const big = Math.max(...rs.map((r) => r.lines));
      rs.forEach((r) => (r.pos = inBall(rand, m.radius).add(m.center)));
      m.dots = dots(rs, (r) => r.pos, (r) => 0.35 + 1.6 * Math.sqrt(r.lines / big),
        (r) => (r.ported ? COLOR.match : m.g.grade === "match" ? COLOR.stand : m.color));
      m.dots.userData = { kind: "routine", items: rs };
      const idx = Object.fromEntries(rs.map((r) => [r.name, r]));
      const calls = [];
      // calls drawn only between ported routines: for the rest, the dots are EIA's code, not this model's
      rs.forEach((r) => r.ported && r.calls.forEach((c) => idx[c] && idx[c].ported && idx[c] !== r && calls.push([r.pos, idx[c].pos])));
      m.inner = calls.length ? segments(calls, COLOR.match, 0.16) : null;
      m.callCount = calls.length;
    } else {
      // AIMMS, GAMS and Python models: their insides are not parsed, so a closed shell
      m.shell = new THREE.Mesh(new THREE.IcosahedronGeometry(m.radius, 2),
        new THREE.MeshBasicMaterial({ color: m.color, wireframe: true, opacity: 0.22, ...additive }));
      m.shell.position.copy(m.center); scene.add(m.shell);
    }
    m.hit = new THREE.Mesh(new THREE.SphereGeometry(m.radius + 2, 10, 10), new THREE.MeshBasicMaterial({ visible: false }));
    m.hit.position.copy(m.center); m.hit.userData.key = m.key; scene.add(m.hit);
  });

  // ---- edges: one module writes a shared variable another reads -----------------------
  const ctr = (k) => (k === "hub" ? hub : byKey[k].center);
  const shown = S.edges.filter((e) => e.shown && !e.hub);
  const maxW = Math.max(...shown.map((e) => e.weight));
  shown.forEach((e) => {
    const a = ctr(e.from), b = ctr(e.to);
    const mid = a.clone().add(b).multiplyScalar(0.5);
    mid.y += 18 + a.distanceTo(b) * 0.12;
    const curve = new THREE.QuadraticBezierCurve3(a, mid, b);
    const tube = new THREE.Mesh(new THREE.TubeGeometry(curve, 24, 0.12 + 0.55 * (e.weight / maxW), 5, false),
      new THREE.MeshBasicMaterial({ color: byKey[e.from].color, opacity: 0.35, ...additive }));
    scene.add(tube);
    e.curve = curve; e.tube = tube;
  });
  const spokes = S.edges.filter((e) => e.hub);
  spokes.forEach((e) => {
    const k = e.from === "hub" ? e.to : e.from;
    e.line = segments([[byKey[k].center, hub]], COLOR.hub, 0.06 + 0.03 * e.weight);
  });

  // ---- switches in, numbers out -------------------------------------------------------
  const order = MODS.map((m) => m.key).concat(["hub", "other"]);
  const band = (k) => Math.max(0, order.indexOf(k));
  const randIn = rng(101), randOut = rng(202);
  const sw = S.switches;
  sw.forEach((s) => {
    const b = band(s.module), y = 70 - (140 * (b + 0.5)) / order.length;
    s.pos = V(-170 + (randIn() - 0.5) * 34, y + (randIn() - 0.5) * 8, (randIn() - 0.5) * 50);
  });
  const swMesh = dots(sw, (s) => s.pos, () => 0.55, () => COLOR.input, 0.85);
  swMesh.userData = { kind: "switch", items: sw };
  // One bundled link per module to its band of switches (and below, of variables it writes),
  // as wide as the count: thousands of single lines would read as one beam.
  function bundle(points, to, color, n, maxN) {
    if (!points.length) return null;
    const c0 = points.reduce((s, p) => s.add(p), V(0, 0, 0)).multiplyScalar(1 / points.length);
    const mid = c0.clone().add(to).multiplyScalar(0.5); mid.y += 6;
    const tube = new THREE.Mesh(new THREE.TubeGeometry(new THREE.QuadraticBezierCurve3(c0, mid, to), 20, 0.15 + 1.2 * Math.sqrt(n / maxN), 5, false),
      new THREE.MeshBasicMaterial({ color, opacity: 0.22, ...additive }));
    scene.add(tube); return tube;
  }
  const swBy = {};
  sw.forEach((s) => byKey[s.module] && (swBy[s.module] = swBy[s.module] || []).push(s));
  const maxSw = Math.max(...Object.values(swBy).map((a) => a.length));
  Object.entries(swBy).forEach(([k, a]) => (byKey[k].inBundle = bundle(a.map((s) => s.pos), byKey[k].center, COLOR.input, a.length, maxSw)));

  const outs = S.outputs;
  outs.forEach((o) => {
    const w = o.writers[0];
    const b = w ? band(w) : order.length;
    const y = 70 - (140 * (b + 0.5)) / (order.length + 1);
    o.pos = V(170 + (randOut() - 0.5) * 40, y + (randOut() - 0.5) * 8, (randOut() - 0.5) * 60);
  });
  const outMesh = dots(outs, (o) => o.pos, (o) => (o.writers.length ? 0.42 : 0.3), (o) => (o.writers.length ? COLOR.output : 0x2f4a43), 0.8);
  outMesh.userData = { kind: "output", items: outs };
  const outBy = {};
  outs.forEach((o) => o.writers.length && (outBy[o.writers[0]] = outBy[o.writers[0]] || []).push(o));
  const maxOut = Math.max(...Object.values(outBy).map((a) => a.length));
  Object.entries(outBy).forEach(([k, a]) => (byKey[k].outBundle = bundle(a.map((o) => o.pos), byKey[k].center, COLOR.output, a.length, maxOut)));

  // ---- words on the page ---------------------------------------------------------------
  const fmt = (x) => Number(x).toLocaleString("en-US");
  const c = S.counts;
  $("hero-text").textContent = `${fmt(c.switches)} switches go in. Thirteen modules trade prices and quantities through ` +
    `${fmt(c.outputs)} shared variables until they agree, every year to 2050. ${fmt(c.routines)} Fortran routines, ` +
    `read from EIA's own code. Drag to look around. Click a module.`;
  $("legend").innerHTML = ["match", "partial", "stand", "fixed"].map((g) =>
    `<span style="--c:#${COLOR[g].toString(16).padStart(6, "0")}">${GRADE_TEXT[g]}</span>`).join("") +
    `<span style="--c:#7F77DD">Switch</span><span style="--c:#5DCAA5">Shared variable</span>`;
  $("note").textContent = `Read from EIA's AEO2026 release on ${S.generated}. Edges: ${S.edge_rule}. Precomputed, not live. Positions carry no meaning: this is code, not a map.`;
  $("status").textContent = `${shown.length} module links shown, thickness = COMMON blocks shared.`;

  const labels = MODS.map((m) => {
    const d = document.createElement("div");
    d.className = "lbl";
    const sub = { match: "", partial: `${Math.round(m.g.share * 100)}% ported`, stand: "fitted to EIA side cases", fixed: "EIA's path" }[m.g.grade];
    d.innerHTML = `${m.name}${sub ? `<br><small>${sub}</small>` : ""}`;
    document.body.appendChild(d);
    return d;
  });

  // ---- click a module -------------------------------------------------------------------
  const hex = (n) => "#" + n.toString(16).padStart(6, "0");
  const panel = $("panel");
  function showModule(m) {
    openMod = m.key; writeHash();
    const ins = S.edges.filter((e) => e.to === m.key && !e.hub).sort((a, b) => b.weight - a.weight).slice(0, 4);
    const outsE = S.edges.filter((e) => e.from === m.key && !e.hub).sort((a, b) => b.weight - a.weight).slice(0, 4);
    const name = (k) => (byKey[k] ? byKey[k].name : "Integrating module");
    const rows = [
      ["Language", m.language],
      [m.language === "Fortran" ? "Fortran lines" : "Model lines", fmt(m.language === "Fortran" ? m.fortran_lines : m.other_lines)],
      ...(m.routines ? [["Routines", fmt(m.routines)], ["Ported routines", fmt(m.ported_routines)],
                        ["Ported lines", `${fmt(m.ported_lines)} (${Math.round(m.g.share * 100)}%)`]] : []),
      ["Shared variables read", fmt(m.reads)], ["Shared variables written", fmt(m.writes)], ["Switches it owns", fmt(m.switches)],
    ];
    panel.innerHTML = `<h3>${m.name}</h3><span class="tag" style="color:${hex(m.color)}">${GRADE_TEXT[m.g.grade]}</span>
      <p>${m.g.text}</p>
      <table>${rows.map(([k, v]) => `<tr><td>${k}</td><td class="n">${v}</td></tr>`).join("")}</table>
      ${outsE.length ? `<p>Writes what these read: ${outsE.map((e) => `${name(e.to)} (${e.weight})`).join(", ")}</p>` : ""}
      ${ins.length ? `<p>Reads what these write: ${ins.map((e) => `${name(e.from)} (${e.weight})`).join(", ")}</p>` : ""}
      ${m.routines ? "" : `<p>Its ${m.language} model is not parsed into routines here; its links come from its transfer lists.</p>`}`;
    panel.style.display = "block";
  }
  const ray = new THREE.Raycaster(), mouse = new THREE.Vector2();
  let downAt = null;
  canvas.addEventListener("pointerdown", (e) => (downAt = [e.clientX, e.clientY]));
  canvas.addEventListener("pointerup", (e) => {
    tip.style.display = "none";
    if (!downAt || Math.hypot(e.clientX - downAt[0], e.clientY - downAt[1]) > 5) return;  // a drag, not a click
    mouse.set((e.clientX / innerWidth) * 2 - 1, -(e.clientY / innerHeight) * 2 + 1);
    ray.setFromCamera(mouse, camera);
    const sh = ray.intersectObject(swMesh)[0];
    if (sh && sh.instanceId !== undefined) { follow(sw[sh.instanceId]); return; }
    const hit = ray.intersectObjects(MODS.map((m) => m.hit))[0];
    if (following) clearFollow();
    if (!hit) { panel.style.display = "none"; openMod = null; writeHash(); return; }
    showModule(byKey[hit.object.userData.key]);
  });
  $("reset").addEventListener("click", home);

  // ---- convergence replay (data/engine3d/runs.json, trace) --------------------------------
  // Each pass of NEMS's integrating loop: the hub sends prices to the demand modules, gets
  // quantities back, sends those to supply, gets prices back. Which modules ran, and how far
  // prices and quantities still moved, come from the recorded run.
  const T = RUNS.trace;
  const RAN = {   // run_model's routine names -> engine modules
    residential: ["residential"], commercial: ["commercial"], "residential (stub)": ["residential"],
    "commercial (stub)": ["commercial"], "industrial (stub)": ["industrial"], "transportation (stub)": ["transportation"],
    "supply stand-in": ["electricity", "natural_gas", "coal", "refining", "oil_gas_supply"],
  };
  const DEMAND_SIDE = new Set(["residential", "commercial", "industrial", "transportation"]);
  const ranMods = (routines) => routines.flatMap((r) => (RAN[r] || []).map((k) => ({ key: k, real: !/stub|stand-in/.test(r) })));
  const pulses = [];
  const pulseGeo = new THREE.SphereGeometry(1, 10, 10);
  function pulse(from, to, color, dur, size = 1.3, dim = false) {
    // a solid pulse for code that really ran; a dashed run of beads for a stand-in or stub
    (dim ? [0, -0.14, -0.28] : [0]).forEach((t0) => {
      const mesh = new THREE.Mesh(pulseGeo, new THREE.MeshBasicMaterial({ color, opacity: dim ? 0.55 : 1, ...additive }));
      mesh.scale.setScalar(dim ? size * 0.5 : size); mesh.visible = false;
      scene.add(mesh); pulses.push({ mesh, from: from.clone(), to: to.clone(), t: t0, dur, dim });
    });
  }
  const varName = Object.fromEntries(S.outputs.map((o) => [o.key, o.description]));
  function worstText(w) {
    const m = /^(\w+)\/(\w+)(?:, region (\d+))?/.exec(w || "");
    if (!m) return w || "";
    const key = `${m[1]}/${m[2]}`, d = varName[key];
    return `${d ? d.toLowerCase() : key}${m[3] ? `, census division ${m[3]}` : ""} <span class="dimk">(${key})</span>`;
  }
  let spin = 0.0006, playing = false, stopFlag = false;
  const sleep = (ms) => new Promise((ok) => setTimeout(ok, ms));
  const counter = $("counter");
  let calls = 0, passesDone = 0;
  function hot(keys) { labels.forEach((el, i) => el.classList.toggle("hot", keys.includes(MODS[i].key))); }

  async function replayYear(y, pace) {
    const ps = T.convergence[String(y)] || [];
    yearEl.value = y; yearOut.textContent = y;
    yearEl.dispatchEvent(new Event("input"));
    const mods = ranMods(T.routines);
    for (const p of ps) {
      if (stopFlag) return;
      // the hub spins with the largest price change still moving
      spin = 0.0006 + 0.012 * Math.min(1, Math.log10(1 + p.dp * 1e4) / 3);
      for (const side of [true, false]) {
        const these = mods.filter((m) => DEMAND_SIDE.has(m.key) === side);
        hot(these.map((m) => m.key));
        these.forEach((m) => { const c = byKey[m.key]; pulse(hub, c.center, COLOR.hub, 320 * pace, m.real ? 1.4 : 1, !m.real); });
        await sleep(330 * pace);
        these.forEach((m) => { const c = byKey[m.key]; pulse(c.center, hub, c.color, 320 * pace, m.real ? 1.4 : 1, !m.real); });
        calls += these.length;
        await sleep(330 * pace);
      }
      passesDone += 1;
      counter.innerHTML = `<b>${y}, pass ${p.itr} of ${ps.length}</b>${p.fcrl ? " (final reporting loop)" : ""}. ` +
        `Largest price change <span class="gap">${pctText(p.dp)}</span>: ${worstText(p.worst)}. ` +
        (p.itr === 1 ? "" : `Quantities moved up to <span class="gap">${pctText(p.dq)}</span>. `) +
        (p.itr === 1 ? "The first pass is never tested. " : p.converged ? "Under NEMS's tolerance. " : "Not converged yet. ") +
        `<br>${passesDone} passes and ${calls} module calls so far.`;
    }
    hot([]);
    spin = 0.0006;
  }
  async function play() {
    if (playing) { stopFlag = true; return; }
    playing = true; stopFlag = false; controls.autoRotate = false; calls = 0; passesDone = 0;
    $("play").textContent = "Stop";
    $("status").textContent = `Replaying the recorded ${T.label.toLowerCase()} run (${T.model}), not live.`;
    const from = +yearEl.value >= +yearEl.max ? +yearEl.min : +yearEl.value;
    for (let y = from; y <= +yearEl.max && !stopFlag; y++) await replayYear(y, y === from ? 1.4 : 0.5);
    playing = false; controls.autoRotate = true; $("play").textContent = "Replay the reference run"; hot([]); spin = 0.0006;
  }
  $("play").addEventListener("click", play);
  yearEl.addEventListener("change", () => { if (!playing) { calls = 0; passesDone = 0; replayYear(+yearEl.value, 1.2); } });

  // ---- the ring animates the change between two data center steps ----------------------------
  // Each module's own quantity in the two runs; a module with no such number here gets nothing.
  const THEIR_NUMBER = {
    residential: (c) => c.energy.residential, commercial: (c) => c.energy.commercial, industrial: (c) => c.energy.industrial,
    transportation: (c) => c.energy.transportation, electricity: (c) => c.trace.totals.elec,
    natural_gas: (c) => c.trace.totals.gas, coal: (c) => c.trace.power_burn.coal, refining: (c) => c.trace.totals.gasoline,
  };
  const halos = {};
  Object.keys(THEIR_NUMBER).forEach((k) => {
    const m = byKey[k];
    const h = new THREE.Mesh(new THREE.TorusGeometry(m.radius + 3, 0.5, 8, 48), new THREE.MeshBasicMaterial({ color: COLOR.hub, opacity: 0, ...additive }));
    h.position.copy(m.center); h.visible = false; scene.add(h); halos[k] = { mesh: h, from: 1, to: 1, t: 1, op: 0 };
  });
  const changeLbl = {};
  MODS.forEach((m, i) => { const s = document.createElement("span"); s.className = "chg"; labels[i].appendChild(s); changeLbl[m.key] = s; });
  onStep = (fromKey, toKey, quiet) => {
    Object.values(changeLbl).forEach((s) => (s.textContent = ""));
    Object.values(halos).forEach((h) => { h.op = 0; h.mesh.visible = false; });
    const A = fromKey && SC[fromKey] && SC[fromKey].raw, B = SC[toKey] && SC[toKey].raw;
    if (!A || !B) return;
    const j = YEARS.indexOf(year());
    Object.entries(THEIR_NUMBER).forEach(([k, get]) => {
      const a = get(A)[j], b = get(B)[j], pctCh = a ? (100 * (b - a)) / a : 0;
      if (Math.abs(pctCh) < 0.05) return;     // no visible change
      const h = halos[k], m = byKey[k];
      h.mesh.visible = true;
      h.mesh.material.color.setHex(pctCh > 0 ? COLOR.partial : COLOR.output);
      h.from = 1; h.to = 1 + Math.min(0.7, Math.abs(pctCh) / 25); h.t = quiet ? 1 : 0;
      h.op = Math.min(0.95, 0.25 + Math.abs(pctCh) / 12);
      changeLbl[k].textContent = ` ${pctCh > 0 ? "+" : ""}${pctCh.toFixed(1)}%`;
      if (!quiet) for (let n = 0; n < Math.min(6, Math.ceil(Math.abs(pctCh) / 2)); n++)
        setTimeout(() => pulse(pctCh > 0 ? hub : m.center, pctCh > 0 ? m.center : hub, pctCh > 0 ? COLOR.partial : COLOR.output, 700), n * 130);
    });
  };

  // ---- follow a switch, and hover labels ---------------------------------------------------
  // Click a switch: light the routines that read it by name (RTOVALUE) or, if none does, its
  // owning module; the shared variables those write; and the modules that read those.
  const routineKey = (r) => `${r.module}:${r.name}`;
  const routineBy = Object.fromEntries(R.routines.map((r) => [routineKey(r), r]));
  const outByKey = Object.fromEntries(outs.map((o) => [o.key, o]));
  const meshes = [swMesh, outMesh, ...MODS.filter((m) => m.dots).map((m) => m.dots)];
  const tmpC = new THREE.Color();
  function paint(mesh, litOf) {
    mesh.userData.items.forEach((it, i) => {
      tmpC.setHex(it.hex);
      if (litOf && !litOf(it)) tmpC.multiplyScalar(0.12);
      mesh.setColorAt(i, tmpC);
    });
    mesh.instanceColor.needsUpdate = true;
  }
  let following = null;
  function clearFollow() {
    following = null; followKey = null;
    if (dollarOn) { dollarOn = false; $("dollar").setAttribute("aria-pressed", false); clearInterval(dollarTimer); dollarTimer = null; document.body.classList.remove("focus"); }
    writeHash();
    meshes.forEach((m) => paint(m, null));
    MODS.forEach((m) => { if (m.inner) m.inner.material.opacity = 0.16; if (m.shell) m.shell.material.opacity = 0.22; });
    shown.forEach((e) => (e.tube.material.opacity = 0.35));
    hot([]);
  }
  function follow(s) {
    if (dollarOn) { dollarOn = false; $("dollar").setAttribute("aria-pressed", false); clearInterval(dollarTimer); dollarTimer = null; document.body.classList.remove("focus"); }
    following = s; followKey = s.key; openMod = null; writeHash();
    const rs = s.routines.map((k) => routineBy[k]).filter(Boolean);
    const startMods = rs.length ? [...new Set(rs.map((r) => r.module))] : byKey[s.module] ? [s.module] : [];
    const writes = new Set(rs.length ? rs.flatMap((r) => r.writes)
      : outs.filter((o) => startMods.some((k) => o.writers.includes(k))).map((o) => o.key));
    const readers = new Set([...writes].flatMap((k) => (outByKey[k] ? outByKey[k].readers : [])));
    startMods.forEach((k) => readers.delete(k));
    const litRoutines = new Set(rs.length ? rs.map(routineKey) : (routinesBy[startMods[0]] || []).map(routineKey));
    paint(swMesh, (x) => x === s);
    paint(outMesh, (o) => writes.has(o.key));
    MODS.filter((m) => m.dots).forEach((m) => paint(m.dots, (r) => litRoutines.has(routineKey(r)) || readers.has(m.key)));
    MODS.forEach((m) => {
      const on = startMods.includes(m.key) || readers.has(m.key);
      if (m.inner) m.inner.material.opacity = on ? 0.3 : 0.03;
      if (m.shell) m.shell.material.opacity = on ? 0.5 : 0.06;
    });
    shown.forEach((e) => (e.tube.material.opacity = startMods.includes(e.from) && readers.has(e.to) ? 0.8 : 0.05));
    hot(startMods.concat([...readers]));
    const name = (k) => (byKey[k] ? byKey[k].name : k === "hub" ? "the integrating module" : k);
    panel.innerHTML = `<h3>${escA(s.key)} = ${escA(s.value)}</h3><span class="tag" style="color:#7F77DD">Switch</span>
      <p>${escA(s.description || "")}</p>
      <p>${rs.length ? `Read by name in ${rs.length} routine${rs.length > 1 ? "s" : ""}: ${[...new Set(rs.map((r) => `${r.name} (${name(r.module)})`))].join(", ")}.`
        : `Owned by ${name(s.module)}${s.file ? ", which reads the file it names" : ""}; no routine reads it by name, so the whole module is lit.`}</p>
      <p>${rs.length ? "Those routines write" : "That module writes"} ${writes.size.toLocaleString("en-US")} shared variables,
        read by ${readers.size ? [...readers].map(name).join(", ") : "no other module"}.</p>
      <p style="color:var(--dim)">From EIA's code as written: assignments, RTOVALUE reads and transfer lists, not a live run.</p>
      <button class="ghost small" id="unfollow" type="button">Clear</button>`;
    panel.style.display = "block";
    $("unfollow").addEventListener("click", () => { clearFollow(); panel.style.display = "none"; });
  }

  // ---- follow a dollar ---------------------------------------------------------------------
  // Start at the household bill. The bill is what a home buys times what it pays, so walk to the
  // prices the residential module reads (RDPR), to the modules that write those prices, and to
  // the switches read by the code that sets them. Variables, routines and writers come from
  // EIA's code (structure.json, routines.json); switches and their verification from switches.json.
  const RDPR = R.routines.find((r) => r.module === "residential" && r.name === "RDPR");
  const FUEL = { pel: "Electricity", png: "Natural gas", pds: "Distillate", plg: "Liquid petroleum gases" };
  const SWNAME = { electricity: "Electricity", natural_gas: "Natural gas", refining: "Refinery", coal: "Coal", oil_gas_supply: "Oil and gas supply" };
  const SW_KIND = { policy: "policy", technology_or_market_assumption: "market assumption", model_control: "model control" };
  const priceVars = RDPR ? RDPR.reads.filter((k) => k.startsWith("AMPBLK/")).sort((a, b) => Object.keys(FUEL).indexOf(a.slice(7, 10)) - Object.keys(FUEL).indexOf(b.slice(7, 10))).map((k) => {
    const sfx = k.split("/")[1], mp = "MPBLK/" + sfx, q = "QBLK/q" + sfx.slice(1);
    const wr = R.routines.filter((r) => r.writes.includes(mp));
    return { adj: k, mp, q: outByKey[q] ? q : null, fuel: FUEL[sfx.slice(0, 3)] || sfx, desc: (outByKey[mp] || outByKey[k] || {}).description,
      units: (outByKey[k] || {}).units, mods: ((outByKey[mp] || {}).writers || []).filter((x) => byKey[x]),
      wr, wrNames: new Set(wr.map((r) => r.name)), hubWriter: wr.find((r) => r.module === "hub") };
  }) : [];
  let SWD = null, dollarTimer = null;
  const verifiedOf = (s) => /^verified/.test(s.verification || "");
  const outsHas = (k) => sw.some((s) => s.key === k);
  function switchesFor(p) {
    const eligible = (s) => s.status === "active" && (s.kind in SW_KIND);
    const direct = (s) => (s.sites || []).some((x) => p.wrNames.has(x.routine));
    const modLevel = (s) => (s.kind === "policy" || s.kind === "technology_or_market_assumption") && p.mods.some((m) => SWNAME[m] && (s.modules || []).includes(SWNAME[m]));
    const all = SWD.filter((s) => eligible(s) && (direct(s) || modLevel(s)));
    const ok = all.filter(verifiedOf);
    const rank = (s) => (s.kind === "model_control" ? 2 : 0) + (direct(s) ? 0 : 1);
    ok.sort((a, b) => rank(a) - rank(b) || a.key.localeCompare(b.key));
    return { ok, left: all.length - ok.length, direct };
  }
  const swNameOf = (m) => (byKey[m] ? byKey[m].name : m);
  function dollarPanel() {
    const j = YEARS.indexOf(year()), g = HEADS.bill.grade();
    const ref = SC.reference.run, hg = SC.high_gas_price;
    const effect = selA !== "reference"
      ? `${SC[selA].label} vs Reference, ${year()}: home gas price $${num(val(selA, "gas_price"), 2)} vs $${num(ref.gas_price[j], 2)} per MMBtu, bill $${num(val(selA, "bill"), 0)} vs $${num(ref.bill[j], 0)}.`
      : hg ? `In the recorded High gas price run, ${year()}: home gas price $${num(val("high_gas_price", "gas_price"), 2)} vs $${num(ref.gas_price[j], 2)} per MMBtu, and the bill $${num(val("high_gas_price", "bill"), 0)} vs $${num(ref.bill[j], 0)}.` : "";
    const trust = SWD.filter(verifiedOf).length;
    const rows = priceVars.map((p) => {
      const sx = switchesFor(p), shownSw = sx.ok.slice(0, 5), rest = sx.ok.slice(5);
      const item = (s) => `<details class="swd"><summary><b>${escA(s.key)}</b> <span class="dimk">${SW_KIND[s.kind]}${sx.direct(s) ? ", read where the price is set" : ""}</span></summary>` +
        `<p>${escA((s.what || s.description || "").slice(0, 260))}${(s.what || "").length > 260 ? "..." : ""}</p>` +
        `<p class="dimk">Value in this release: ${escA(s.value)}. ${escA(s.verification)}. ` +
        `${outsHas(s.key) ? `<a href="#" data-sw="${escA(s.key)}">Follow it in 3D</a>` : ""}</p></details>`;
      const setter = p.mods.length ? p.mods.map(swNameOf).join(", ") : p.hubWriter ? `the integrating module (${p.hubWriter.name})` : "no module here";
      const byName = {}; p.wr.forEach((r) => ((byName[r.name] = byName[r.name] || new Set()).add(r.file)));
      const where = p.wr.length ? ` in ${Object.entries(byName).map(([n, f]) => `${n} (${[...f].join(", ")})`).join("; ")}` : "";
      const unparsed = p.mods.find((m) => !byKey[m].routines);
      return `<div class="dstep"><b>${p.fuel}</b> <span class="dimk">${p.mp}, ${escA(p.units || "")}</span>` +
        `<p>Set by <b>${setter}</b>${escA(where)}.${unparsed ? ` ${swNameOf(unparsed)} is not parsed into routines here.` : ""}</p>` +
        (shownSw.length ? `<p class="dimk">Switches read in that code:</p>${shownSw.map(item).join("")}${rest.length ? `<details class="more"><summary>${rest.length} more</summary>${rest.map(item).join("")}</details>` : ""}`
          : `<p class="dimk">No verified policy or market switch found for this price in the parsed reads.</p>`) +
        (sx.left ? `<p class="dimk">${sx.left} entries left out: not marked verified.</p>` : "") + `</div>`;
    }).join("");
    panel.innerHTML = `<h3>Follow a dollar</h3><span class="tag" style="color:#FAC775">Walked back from the bill</span>
      <p><b>$${num(val(selA, "bill"), 0)}</b> a year per household, ${year()}, ${SC[selA].label}${g ? ` <span class="pill ${g.grade}" title="${escA(g.summary)}">${g.label_grade}</span>` : ""}.
      A bill is what a home buys times what it pays. The residential module's routine RDPR reads ${priceVars.length} prices (${priceVars.map((p) => p.fuel.toLowerCase()).join(", ")});
      the quantities it buys are written by its own EXCONS routine.</p>
      <p class="dimk">The home reads the adjusted copy of each price (AMPBLK). The code that copies EIA's supply-side price (MPBLK) into it is not fully parsed here, so that link is matched by name: same fuel, same sector.</p>
      ${rows}
      ${effect ? `<p>${effect}</p>` : ""}
      <p class="dimk">${trust} of ${SWD.length} switch entries are marked verified. Verified means checked by two readers of the code, not proven. A stand-in model produced the bill, so read the levels as stand-in numbers.</p>
      <button class="ghost small" id="unfollow" type="button">Clear</button>`;
    panel.style.display = "block";
    panel.querySelectorAll("[data-sw]").forEach((a) => a.addEventListener("click", (e) => {
      e.preventDefault(); const s = sw.find((x) => x.key === a.dataset.sw); if (s) { clearFollow(); follow(s); } }));
    $("unfollow").addEventListener("click", () => { clearFollow(); panel.style.display = "none"; });
  }
  async function dollarStart() {
    if (dollarOn) { clearFollow(); panel.style.display = "none"; return; }
    if (following) clearFollow();
    if (mapOn) setMap(false);
    openMod = null;
    if (!SWD) {
      panel.innerHTML = "<p>Reading the switch data...</p>"; panel.style.display = "block";
      try { SWD = (await load("data/switches.json")).switches; } catch (e) { panel.innerHTML = "<p>The switch data did not load.</p>"; return; }
    }
    dollarOn = true; $("dollar").setAttribute("aria-pressed", true); document.body.classList.add("focus");
    following = { dollar: true };
    const setters = new Set(priceVars.flatMap((p) => p.mods));
    const lit = new Set(priceVars.flatMap((p) => [p.adj, p.mp, p.q].filter(Boolean)));
    const perPrice = priceVars.map((p) => ({ p, list: switchesFor(p).ok.slice(0, 5) }));
    const litSw = new Set(perPrice.flatMap((x) => x.list.map((s) => s.key)));
    const litR = new Set([...(RDPR ? [routineKey(RDPR)] : []), ...priceVars.flatMap((p) => p.wr.map(routineKey))]);
    const on = new Set(["residential", ...setters]);
    paint(swMesh, (x) => litSw.has(x.key));
    paint(outMesh, (o) => lit.has(o.key));
    MODS.filter((m) => m.dots).forEach((m) => paint(m.dots, (r) => litR.has(routineKey(r))));
    MODS.forEach((m) => {
      if (m.inner) m.inner.material.opacity = on.has(m.key) ? 0.3 : 0.03;
      if (m.shell) m.shell.material.opacity = on.has(m.key) ? 0.5 : 0.06;
    });
    shown.forEach((e) => (e.tube.material.opacity = setters.has(e.from) && e.to === "residential" ? 0.8 : 0.05));
    hot([...on]); writeHash(); dollarPanel(); home();
    // a bead runs switch -> the module that sets the price -> the home, again and again while this is on
    const run = () => {
      const res = byKey.residential.center, seen = new Set();
      perPrice.forEach(({ p, list }) => p.mods.forEach((k) => {
        list.slice(0, 2).forEach((s, i) => { const o = sw.find((x) => x.key === s.key); if (o) setTimeout(() => pulse(o.pos, byKey[k].center, COLOR.input, 900), i * 160); });
        if (!seen.has(k)) { seen.add(k); setTimeout(() => pulse(byKey[k].center, res, COLOR.hub, 900, 1.5), 1000); }
      }));
    };
    run(); dollarTimer = setInterval(run, 2600);
  }
  $("dollar").addEventListener("click", dollarStart);

  const tip = document.createElement("div");
  tip.className = "tip"; tip.setAttribute("role", "tooltip"); document.body.appendChild(tip);
  function describe(kind, it) {
    if (kind === "switch") return `<b>${escA(it.key)}</b> = ${escA(it.value)}<br>${escA(it.description || "")}<br><i>Switch, owner: ${byKey[it.module] ? byKey[it.module].name : it.module}. Click to follow.</i>`;
    if (kind === "output") return `<b>${escA(it.key)}</b> ${it.units ? `(${escA(it.units)})` : ""}<br>${escA(it.description || "")}<br><i>Written by ${it.writers.map((k) => byKey[k].name).join(", ") || "no module here"}; read by ${it.readers.map((k) => byKey[k].name).join(", ") || "none"}.</i>`;
    return `<b>${it.name}</b> (${byKey[it.module].name}, ${escA(it.file)})<br>${it.lines.toLocaleString("en-US")} lines, calls ${it.calls.length}, writes ${it.writes.length} shared variables<br><i>${it.ported ? "Ported to Python and checked against EIA's code" : "Not ported"}</i>`;
  }
  const hov = new THREE.Raycaster(); hov.params.Points = { threshold: 1 };
  let lastMove = 0;
  canvas.addEventListener("pointermove", (e) => {
    if (e.pointerType === "touch" || performance.now() - lastMove < 40) return;
    lastMove = performance.now();
    mouse.set((e.clientX / innerWidth) * 2 - 1, -(e.clientY / innerHeight) * 2 + 1);
    hov.setFromCamera(mouse, camera);
    const h = hov.intersectObjects(meshes)[0];
    if (!h || h.instanceId === undefined) { tip.style.display = "none"; canvas.style.cursor = ""; return; }
    const it = h.object.userData.items[h.instanceId];
    tip.innerHTML = describe(h.object.userData.kind, it);
    tip.style.display = "block";
    tip.style.left = Math.min(innerWidth - 300, e.clientX + 14) + "px";
    tip.style.top = Math.min(innerHeight - 90, e.clientY + 14) + "px";
    canvas.style.cursor = h.object.userData.kind === "switch" ? "pointer" : "";
  });
  canvas.addEventListener("pointerleave", () => (tip.style.display = "none"));

  // ---- fidelity map: everything colored by how close it is to EIA --------------------------
  const GRADE_HEX = { match: COLOR.match, partial: COLOR.stand, stand: COLOR.stand, fixed: COLOR.fixed };
  const moduleMapHex = (k) => (byKey[k] ? { match: COLOR.match, partial: COLOR.partial, stand: COLOR.stand, fixed: COLOR.fixed }[byKey[k].g.grade] : 0x24262b);
  const routineHex = (r) => (r.ported ? COLOR.match : GRADE_HEX[byKey[r.module].g.grade] === COLOR.match ? COLOR.stand : GRADE_HEX[byKey[r.module].g.grade]);
  // Shares of EIA's code, by lines: routines ported and checked; the rest of a module with a
  // stand-in behind it; modules that only follow EIA's published path.
  const lineShares = (() => {
    const out = { match: 0, stand: 0, fixed: 0 };
    MODS.forEach((m) => {
      const lines = m.fortran_lines + m.other_lines;
      out.match += m.ported_lines;
      out[m.g.grade === "fixed" ? "fixed" : "stand"] += lines - m.ported_lines;
    });
    return out;
  })();
  function paintBy(mesh, hexOf) {
    mesh.userData.items.forEach((it, i) => mesh.setColorAt(i, tmpC.setHex(hexOf(it))));
    mesh.instanceColor.needsUpdate = true;
  }
  const bundles = MODS.flatMap((m) => [m.inBundle, m.outBundle]).filter(Boolean);
  function setMap(on) {
    mapOn = on;
    $("map").setAttribute("aria-pressed", on);
    if (following) clearFollow();
    if (on) {
      MODS.filter((m) => m.dots).forEach((m) => paintBy(m.dots, routineHex));
      paintBy(outMesh, (o) => (o.writers.length ? moduleMapHex(o.writers[0]) : 0x24262b));
      paintBy(swMesh, (s) => moduleMapHex(s.module));
    } else {
      meshes.forEach((m) => paint(m, null));
    }
    // additive blending would wash dense clusters to white; here the color is the message
    meshes.forEach((m) => { m.material.blending = on ? THREE.NormalBlending : THREE.AdditiveBlending; m.material.depthWrite = on; m.material.needsUpdate = true; });
    MODS.forEach((m) => { if (m.inner) m.inner.material.opacity = on ? 0.05 : 0.16; });
    shown.forEach((e) => (e.tube.material.opacity = on ? 0.06 : 0.35));
    bundles.forEach((b) => (b.material.opacity = on ? 0.05 : 0.22));
    const total = lineShares.match + lineShares.stand + lineShares.fixed;
    const row = (g, label, hex) => `<i style="width:${(100 * lineShares[g]) / total}%;background:#${hex.toString(16).padStart(6, "0")}"></i>`;
    const line = (g, label) => `<div><span>${label}</span><span>${fmt(lineShares[g])} lines, ${((100 * lineShares[g]) / total).toFixed(0)}%</span></div>`;
    $("mapbar").innerHTML = on ? `<div class="bar3">${row("match", "", COLOR.match)}${row("stand", "", COLOR.stand)}${row("fixed", "", COLOR.fixed)}</div>` +
      line("match", "Ported, checked against EIA's code") + line("stand", "Not ported, stand-in fitted to EIA's runs") + line("fixed", "Not modeled, EIA's own path") +
      `<a href="scoreboard.html">Every grade and its evidence</a>` : "";
    $("mapbar").style.display = on ? "block" : "none";
    writeHash();
  }
  $("map").addEventListener("click", () => setMap(!mapOn));

  if (asked.get("map") === "1") setMap(true);
  if (asked.get("d") === "1") dollarStart();
  if (asked.get("sw") && sw.find((s) => s.key === asked.get("sw"))) follow(sw.find((s) => s.key === asked.get("sw")));
  else if (byKey[asked.get("m")]) showModule(byKey[asked.get("m")]);

  // ---- loop -----------------------------------------------------------------------------
  function resize() { renderer.setSize(innerWidth, innerHeight, false); camera.aspect = innerWidth / innerHeight; frame(); camera.updateProjectionMatrix(); }
  addEventListener("resize", resize); resize();
  let last = performance.now();
  function tick(now) {
    const dt = now - last; last = now;
    hubMesh.rotation.y += dt * spin; hubMesh.rotation.x += dt * spin * 0.5;
    Object.values(halos).forEach((h) => {
      if (!h.mesh.visible) return;
      h.t = Math.min(1, h.t + dt / 900);
      const e = 1 - Math.pow(1 - h.t, 3), s = h.from + (h.to - h.from) * e;
      h.mesh.scale.setScalar(s); h.mesh.material.opacity = h.op * (0.35 + 0.65 * e);
      h.mesh.quaternion.copy(camera.quaternion);
    });
    for (let i = pulses.length - 1; i >= 0; i--) {
      const p = pulses[i]; p.t += dt / p.dur;
      if (p.t < 0) continue;
      p.mesh.visible = true;
      if (p.t >= 1) { scene.remove(p.mesh); p.mesh.material.dispose(); pulses.splice(i, 1); continue; }
      p.mesh.position.lerpVectors(p.from, p.to, p.t);
      p.mesh.material.opacity = (p.dim ? 0.55 : 1) * (1 - p.t * 0.6);
    }
    if (framed !== `${rightW()}:${leftW()}`) frame();
    controls.update(); renderer.render(scene, camera);
    MODS.forEach((m, i) => {
      const v = m.center.clone().add(V(0, m.radius, 0)).project(camera), el = labels[i];
      if (v.z > 1) { el.style.display = "none"; return; }
      el.style.display = "block";
      el.style.left = ((v.x + 1) / 2) * innerWidth + "px";
      el.style.top = ((1 - v.y) / 2) * innerHeight + "px";
    });
    requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
  window.NEMS_ENGINE3D = { S, R, RUNS, FID, MODS, byKey, scene, camera, controls, COLOR, follow, clearFollow };
})();

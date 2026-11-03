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
  let followKey = null, openMod = null;
  function writeHash() {
    const q = new URLSearchParams();
    if (selA !== "reference") q.set("a", selA);
    if (selB) q.set("b", selB);
    q.set("y", yearEl.value);
    if (followKey) q.set("sw", followKey);
    if (openMod) q.set("m", openMod);
    history.replaceState(null, "", "#" + q.toString());
  }

  // ---- scenario cards and diff-two-runs (data/engine3d/runs.json, scenarios) -------------
  const SC = RUNS.scenarios, YEARS = RUNS.years;
  const OUT = FID.sets.fast.outputs;   // the scenarios run on the fast stand-ins
  const RANK = { match: 0, within: 1, stand: 2 };
  const worst = (keys) => keys.map((k) => OUT[k]).filter(Boolean).sort((a, b) => RANK[b.grade] - RANK[a.grade])[0];
  // Each headline and the demo numbers its grade comes from (data/fidelity.json): the bill is
  // home fuel use times home prices, so it is only as good as the weakest of those.
  const HEADS = {
    co2: { label: "US energy CO2", unit: " Mt", d: 0, grade: () => OUT.co2 },
    bill: { label: "Household energy bill", unit: " $/yr", d: 0, pre: "$", grade: () => worst(["energy.residential", "pel", "ng"]) },
    gas_price: { label: "Home natural gas price", unit: " $/MMBtu", d: 2, pre: "$", grade: () => OUT.ng },
  };
  let selA = RUNS.scenarios[asked.get("a")] ? asked.get("a") : "reference";
  let selB = RUNS.scenarios[asked.get("b")] && asked.get("b") !== selA ? asked.get("b") : null;
  let comparing = !!selB;
  if (traceYears.includes(+asked.get("y"))) { yearEl.value = +asked.get("y"); yearOut.textContent = yearEl.value; }
  $("compare").setAttribute("aria-pressed", comparing);
  const year = () => +yearEl.value;
  const val = (key, m, src = "run") => SC[key][src][m][YEARS.indexOf(year())];
  const num = (x, d) => Number(x).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
  const escA = (x) => String(x).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");

  function cards() {
    $("cards").innerHTML = Object.values(SC).map((s) =>
      `<button type="button" class="card ${s.key === selA ? "a" : ""} ${s.key === selB ? "b" : ""}" data-k="${s.key}">${s.label}` +
      `<small>EIA's ${s.case} case inputs, ${s.model}, precomputed</small></button>`).join("");
    $("cards").querySelectorAll("[data-k]").forEach((b) => b.addEventListener("click", () => {
      const k = b.dataset.k;
      if (comparing && k !== selA) selB = selB === k ? null : k;
      else { selA = k; if (selB === k) selB = null; }
      render(true);
    }));
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
    if (!selB) { $("diff").innerHTML = comparing ? `<span class="k" style="color:var(--dim)">Pick a second scenario.</span>` : ""; return; }
    const A = SC[selA], B = SC[selB];
    $("diff").innerHTML = `<span style="color:var(--muted)">${B.label} minus ${A.label}, ${year()}</span>` +
      Object.entries(HEADS).map(([m, h]) => {
        const d = val(selB, m) - val(selA, m), p = val(selA, m) ? (100 * d) / val(selA, m) : 0;
        const cls = Math.abs(p) < 0.05 ? "" : d > 0 ? "up" : "down";
        return `<div><span class="k">${h.label}</span> <span class="d ${cls}">${d >= 0 ? "+" : "-"}${h.pre || ""}${num(Math.abs(d), h.d)}${h.unit} (${p >= 0 ? "+" : ""}${p.toFixed(1)}%)</span>` +
          spark(A.run[m].slice(YEARS.indexOf(RUNS.start_year)), B.run[m].slice(YEARS.indexOf(RUNS.start_year))) + `</div>`;
      }).join("") +
      `<span class="k" style="color:var(--dim)">Lines: ${A.label} solid, ${B.label} dashed, ${RUNS.start_year}-${YEARS[YEARS.length - 1]}.</span>`;
  }
  function render(animate) { cards(); heads(animate); diff(); writeHash(); }
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

  // ---- scene -------------------------------------------------------------------------
  const canvas = $("c");
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  const scene = new THREE.Scene();
  scene.fog = new THREE.FogExp2(0x07090d, 0.0032);
  const camera = new THREE.PerspectiveCamera(50, 1, 0.1, 3000);
  const controls = new THREE.OrbitControls(camera, canvas);
  controls.enableDamping = true; controls.autoRotate = true; controls.autoRotateSpeed = 0.3;
  const home = () => { camera.position.set(0, 80, 330); controls.target.set(0, 0, 0); };
  home();

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
    following = null; followKey = null; writeHash();
    meshes.forEach((m) => paint(m, null));
    MODS.forEach((m) => { if (m.inner) m.inner.material.opacity = 0.16; if (m.shell) m.shell.material.opacity = 0.22; });
    shown.forEach((e) => (e.tube.material.opacity = 0.35));
    hot([]);
  }
  function follow(s) {
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

  if (asked.get("sw") && sw.find((s) => s.key === asked.get("sw"))) follow(sw.find((s) => s.key === asked.get("sw")));
  else if (byKey[asked.get("m")]) showModule(byKey[asked.get("m")]);

  // ---- loop -----------------------------------------------------------------------------
  function resize() { renderer.setSize(innerWidth, innerHeight, false); camera.aspect = innerWidth / innerHeight; camera.updateProjectionMatrix(); }
  addEventListener("resize", resize); resize();
  let last = performance.now();
  function tick(now) {
    const dt = now - last; last = now;
    hubMesh.rotation.y += dt * spin; hubMesh.rotation.x += dt * spin * 0.5;
    for (let i = pulses.length - 1; i >= 0; i--) {
      const p = pulses[i]; p.t += dt / p.dur;
      if (p.t < 0) continue;
      p.mesh.visible = true;
      if (p.t >= 1) { scene.remove(p.mesh); p.mesh.material.dispose(); pulses.splice(i, 1); continue; }
      p.mesh.position.lerpVectors(p.from, p.to, p.t);
      p.mesh.material.opacity = (p.dim ? 0.55 : 1) * (1 - p.t * 0.6);
    }
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

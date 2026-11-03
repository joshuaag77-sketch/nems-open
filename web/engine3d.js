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
      mesh.setColorAt(i, c.setHex(colorOf(it, i)));
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
      const idx = Object.fromEntries(rs.map((r) => [r.name, r]));
      const calls = [];
      rs.forEach((r) => r.calls.forEach((c) => idx[c] && idx[c] !== r && calls.push([r.pos, idx[c].pos])));
      m.inner = segments(calls, m.color, 0.16);
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
  dots(sw, (s) => s.pos, () => 0.55, () => COLOR.input, 0.85);
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
  dots(outs, (o) => o.pos, (o) => (o.writers.length ? 0.42 : 0.3), (o) => (o.writers.length ? COLOR.output : 0x2f4a43), 0.8);
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
  $("note").textContent = `Read from EIA's AEO2026 release on ${S.generated}. Edges: ${S.edge_rule}. Precomputed, not live.`;
  $("status").textContent = `${shown.length} module links shown, thickness = COMMON blocks shared.`;

  const labels = MODS.map((m) => {
    const d = document.createElement("div");
    d.className = "lbl";
    d.innerHTML = `${m.name}`;
    document.body.appendChild(d);
    return d;
  });

  // ---- click a module -------------------------------------------------------------------
  const hex = (n) => "#" + n.toString(16).padStart(6, "0");
  const panel = $("panel");
  function showModule(m) {
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
    const hit = ray.intersectObjects(MODS.map((m) => m.hit))[0];
    if (!hit) { panel.style.display = "none"; return; }
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
    const mesh = new THREE.Mesh(pulseGeo, new THREE.MeshBasicMaterial({ color, opacity: dim ? 0.55 : 1, ...additive }));
    mesh.scale.setScalar(size);
    scene.add(mesh); pulses.push({ mesh, from: from.clone(), to: to.clone(), t: 0, dur, dim });
  }
  const varName = Object.fromEntries(S.outputs.map((o) => [o.key, o.description]));
  function worstText(w) {
    const m = /^(\w+)\/(\w+)(?:, region (\d+))?/.exec(w || "");
    if (!m) return w || "";
    const key = `${m[1]}/${m[2]}`, d = varName[key];
    return `${d ? d.toLowerCase() : key}${m[3] ? `, census division ${m[3]}` : ""} <span class="dimk">(${key})</span>`;
  }
  const pct = (x) => (100 * x < 0.01 ? (100 * x).toPrecision(2) : (100 * x).toFixed(2)) + "%";
  let spin = 0.0006, playing = false, stopFlag = false;
  const sleep = (ms) => new Promise((ok) => setTimeout(ok, ms));
  const yearEl = $("year"), yearOut = $("year-out"), counter = $("counter");
  yearEl.min = Math.min(...Object.keys(T.convergence).map(Number)); yearEl.max = Math.max(...Object.keys(T.convergence).map(Number));
  let calls = 0, passesDone = 0;
  function hot(keys) { labels.forEach((el, i) => el.classList.toggle("hot", keys.includes(MODS[i].key))); }

  async function replayYear(y, pace) {
    const ps = T.convergence[String(y)] || [];
    yearEl.value = y; yearOut.textContent = y;
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
        `Largest price change <span class="gap">${pct(p.dp)}</span>: ${worstText(p.worst)}. ` +
        `Quantities moved up to <span class="gap">${pct(p.dq)}</span>. ` +
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
    for (let y = +yearEl.value; y <= +yearEl.max && !stopFlag; y++) await replayYear(y, y === +yearEl.value ? 1.4 : 0.5);
    playing = false; controls.autoRotate = true; $("play").textContent = "Replay the reference run"; hot([]); spin = 0.0006;
  }
  $("play").addEventListener("click", play);
  yearEl.addEventListener("input", () => { yearOut.textContent = yearEl.value; });
  yearEl.addEventListener("change", () => { if (!playing) { calls = 0; passesDone = 0; replayYear(+yearEl.value, 1.2); } });

  // ---- loop -----------------------------------------------------------------------------
  function resize() { renderer.setSize(innerWidth, innerHeight, false); camera.aspect = innerWidth / innerHeight; camera.updateProjectionMatrix(); }
  addEventListener("resize", resize); resize();
  let last = performance.now();
  function tick(now) {
    const dt = now - last; last = now;
    hubMesh.rotation.y += dt * spin; hubMesh.rotation.x += dt * spin * 0.5;
    for (let i = pulses.length - 1; i >= 0; i--) {
      const p = pulses[i]; p.t += dt / p.dur;
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
  window.NEMS_ENGINE3D = { S, R, RUNS, FID, MODS, byKey, scene, camera, controls, COLOR, segments, dots, ctr, hub, labels, $ };
})();

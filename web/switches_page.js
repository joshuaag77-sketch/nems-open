// Switch atlas: search and filter over data/switches.js.
(function () {
  const D = window.SWITCHES;
  const $ = (id) => document.getElementById(id);
  const KIND = {
    policy: "Policy", technology_or_market_assumption: "Technology or market assumption", model_control: "Model control",
    debug_reporting: "Debug and reporting", file_path: "File path", build_or_software: "Build and software", unknown: "Unknown",
  };
  const STATUS = { active: "Active", read_no_effect: "Read, no effect", not_read: "Not read by any code", unknown: "Unknown" };

  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }

  function fill(sel, entries) {
    sel.append(new Option("All", ""));
    for (const [v, label] of entries) sel.append(new Option(label, v));
  }

  const mods = [...new Set(D.switches.flatMap((s) => s.modules))].sort();
  fill($("kind"), Object.entries(KIND));
  fill($("module"), mods.map((m) => [m, m === "unknown" ? "Unknown" : m]));
  fill($("status"), Object.entries(STATUS));
  fill($("verif"), Object.keys(D.summary.verification).map((v) => [v, v]));

  const VERIFIED = "verified, second read";
  for (const [v, n] of Object.entries(D.summary.verification)) {
    const tile = el("div", v === VERIFIED ? "sw-tile sw-tile-ok" : "sw-tile");
    tile.append(el("div", "sw-tile-n", String(n)), el("div", "sw-tile-l", v));
    $("trust").append(tile);
  }
  $("trust-note").textContent = D.summary.trust_note || "";

  for (const s of D.switches) {
    s._hay = [s.key, s.what, s.description, s.notes, s.allowed, s.value, s.modules.join(" "), s.section,
      s.sites.map((x) => x.file + " " + (x.routine || "")).join(" "),
      s.values.map((v) => v.value + " " + v.meaning).join(" "),
      Object.keys(s.side_cases).join(" ")].join(" ").toLowerCase();
  }

  function row(label, node) {
    const r = el("div", "sw-row");
    r.append(el("div", "sw-label", label));
    const v = el("div", "sw-val");
    if (typeof node === "string") v.textContent = node; else v.append(node);
    r.append(v);
    return r;
  }

  function detail(s) {
    const box = el("div", "sw-detail");
    if (s.description) box.append(row("EIA's description", s.description));
    box.append(row("Value in cb2026", s.in_cb2026 ? (s.value === "" ? "(blank)" : s.value) : "Not in cb2026"));
    if (s.code_default.length) box.append(row("Default in code", s.code_default.join(", ")));
    box.append(row("Allowed", s.allowed));
    if (s.values.length) {
      const ul = el("ul", "sw-ul");
      for (const v of s.values) ul.append(el("li", "", `${v.value}: ${v.meaning} (from ${v.source})`));
      box.append(row("Values", ul));
    }
    box.append(row("Modules", s.modules.map((m) => (m === "unknown" ? "Unknown" : m)).join(", ")));
    const cases = Object.entries(s.side_cases);
    if (cases.length) {
      const ul = el("ul", "sw-ul");
      for (const [c, v] of cases) ul.append(el("li", "", `${D.side_cases[c] || c}: ${v}`));
      box.append(row("Side cases that change it", ul));
    } else {
      box.append(row("Side cases that change it", "None of the ten"));
    }
    const other = Object.entries(s.other_scedes).filter(([, v]) => v !== null);
    if (other.length) box.append(row("Other scedes files", other.map(([c, v]) => `${c}: ${v}`).join("; ")));
    if (s.notes) box.append(row("Notes", s.notes));
    if (s.sites.length) {
      const ul = el("ul", "sw-ul sw-mono");
      for (const x of s.sites) ul.append(el("li", "", `${x.file}:${x.line}${x.routine ? " in " + x.routine : ""}`));
      const more = s.site_count > s.sites.length ? ` (first ${s.sites.length} of ${s.site_count})` : "";
      box.append(row("Where it appears" + more, ul));
    } else {
      box.append(row("Where it appears", s.mention_count ? `No read site found; the word appears ${s.mention_count} times, unquoted` : "No read site found"));
    }
    if (s.evidence.length) box.append(row("Checked at", s.evidence.join(", ")));
    box.append(row("Established by", { reader: "Reading the code", script: "Script, from the scedes row and site search", none: "Nothing yet" }[s.established_by]));
    box.append(row("Checked", s.verification));
    if (s.correction) box.append(row("Corrected on second read", s.correction));
    return box;
  }

  function item(s) {
    const d = el("details", "card sw-item");
    const sum = el("summary", "sw-sum");
    const head = el("div", "sw-head");
    head.append(el("code", "sw-key", s.key));
    head.append(el("span", "sw-tag", KIND[s.kind]));
    head.append(el("span", s.verification === VERIFIED ? "sw-tag sw-ok" : "sw-tag sw-warn", s.verification));
    if (s.status !== "active") head.append(el("span", "sw-tag sw-warn", STATUS[s.status]));
    if (Object.keys(s.side_cases).length) head.append(el("span", "sw-tag sw-side", `${Object.keys(s.side_cases).length} side cases`));
    sum.append(head);
    sum.append(el("p", s.what === "unknown" ? "sw-what sw-unknown" : "sw-what", s.what === "unknown" ? "Unknown" : s.what));
    d.append(sum);
    d.addEventListener("toggle", () => {
      if (d.open && !d.dataset.built) { d.append(detail(s)); d.dataset.built = "1"; }
    }, { once: false });
    return d;
  }

  function apply() {
    const terms = $("q").value.toLowerCase().split(/\s+/).filter(Boolean);
    const kind = $("kind").value, mod = $("module").value, st = $("status").value, verif = $("verif").value;
    const side = $("side").checked, nofile = $("nofile").checked;
    const hits = D.switches.filter((s) =>
      terms.every((t) => s._hay.includes(t)) &&
      (!kind || s.kind === kind) && (!mod || s.modules.includes(mod)) && (!st || s.status === st) && (!verif || s.verification === verif) &&
      (!side || Object.keys(s.side_cases).length) && (!nofile || (s.kind !== "file_path" && s.kind !== "build_or_software")));
    const list = $("list");
    list.replaceChildren(...hits.slice(0, 200).map(item));
    const u = D.summary;
    $("count").textContent = `${hits.length} of ${u.keys} keys` + (hits.length > 200 ? ", first 200 shown" : "") +
      `. ${u.what_unknown} have an unknown meaning. ${u.changed_in_side_cases} change in a side case.`;
  }

  for (const id of ["q", "kind", "module", "status", "verif", "side", "nofile"]) $(id).addEventListener("input", apply);
  const hash = decodeURIComponent(location.hash.slice(1));
  if (hash) $("q").value = hash;
  apply();
})();

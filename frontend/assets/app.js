(() => {
  const API = window.DEALDESK_API;
  const $ = (s) => document.querySelector(s);
  const $$ = (s) => Array.from(document.querySelectorAll(s));
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const store = {
    get(k, d) { try { return localStorage.getItem(k) ?? d; } catch { return d; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch {} },
  };
  const rid = () => Math.random().toString(36).slice(2, 10);
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // ---------- identity (user_id) + conversation (thread_id)
  let userId = store.get("dd_user", "");
  let userLabel = store.get("dd_user_label", "");
  if (!userId) { userId = "guest-" + rid(); store.set("dd_user", userId); }
  let threadId = store.get("dd_thread_" + userId, "") || newThreadId();
  function newThreadId() { const t = "web-" + Date.now().toString(36); store.set("dd_thread_" + userId, t); return t; }
  function slug(s) { return s.trim().toLowerCase().replace(/[^a-z0-9@._-]+/g, "-").slice(0, 80); }
  function renderWho() {
    $("#whoBtn").textContent = userLabel ? "👤 " + userLabel : "Sign in";
    $("#chatWho").textContent = (userLabel || "Guest") + " · #" + threadId.slice(-5);
  }

  // =========================================================
  // Generative listing art (unique per listing ID, matches its type)
  // =========================================================
  function hash(s) { let h = 2166136261; for (const c of String(s)) { h ^= c.charCodeAt(0); h = Math.imul(h, 16777619); } return h >>> 0; }
  function rng(seed) { let a = seed || 1; return () => { a |= 0; a = (a + 0x6D2B79F5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }
  const PALETTES = [
    ["#120c2e", "#3d2580", "#f5b94a"], ["#06202b", "#0f4f5e", "#4fe3d0"], ["#1e0a1c", "#6a1a45", "#ff5e8a"],
    ["#0e0d26", "#2f2a86", "#8b7bff"], ["#1d1206", "#6b3f10", "#ffd98a"], ["#0a1424", "#1d3d73", "#7cc4ff"],
  ];
  const PAINT = { white: "#e9e7e2", black: "#22222a", silver: "#b9bdc6", grey: "#6f737c", gray: "#6f737c", red: "#c9343f", blue: "#2f62bd",
    green: "#2f7a52", maroon: "#6d1f2c", beige: "#cdb994", brown: "#6b4a2f", gold: "#c9a24a", orange: "#d9692a", yellow: "#d8b330" };
  const CAR = {
    sedan: { body: "M48 160C48 146 56 138 72 136L128 130 170 104C178 99 188 96 200 96L262 96C276 96 288 101 298 110L322 130 350 134C362 136 370 144 370 156L370 164C370 168 366 170 362 170L340 170A26 26 0 0 0 288 170L142 170A26 26 0 0 0 90 170L56 170C51 170 48 166 48 160Z",
      win: ["M140 129L176 106C182 102 190 100 198 100L228 100 228 129Z", "M236 100L260 100C272 100 282 104 290 112L308 129 236 129Z"], wheels: [116, 314], r: 21 },
    suv: { body: "M46 162C46 140 52 132 66 130L110 126 140 88C146 81 154 78 164 78L290 78C302 78 310 82 316 90L340 126 356 130C366 133 372 142 372 154L372 164C372 168 368 170 364 170L342 170A27 27 0 0 0 288 170L144 170A27 27 0 0 0 90 170L54 170C49 170 46 167 46 162Z",
      win: ["M120 124L146 92C150 87 156 84 164 84L218 84 218 124Z", "M226 84L284 84C294 84 300 87 304 93L328 124 226 124Z"], wheels: [117, 315], r: 23, rails: true },
    hatchback: { body: "M60 162C60 146 66 136 82 134L120 130 156 98C164 91 174 88 186 88L262 88C276 88 286 94 292 106L314 156 314 164C314 168 310 170 306 170L296 170A24 24 0 0 0 248 170L146 170A24 24 0 0 0 98 170L68 170C63 170 60 167 60 162Z",
      win: ["M132 128L162 101C168 96 176 94 184 94L214 94 214 128Z", "M222 94L260 94C270 94 278 99 282 108L290 128 222 128Z"], wheels: [122, 272], r: 21, dx: 30 },
    pickup: { body: "M40 162C40 146 46 138 60 136L100 132 128 96C134 89 142 86 152 86L208 86C216 86 220 90 220 98L220 130 368 130C372 130 374 132 374 136L374 164C374 168 370 170 366 170L346 170A26 26 0 0 0 294 170L138 170A26 26 0 0 0 86 170L48 170C43 170 40 167 40 162Z",
      win: ["M110 128L134 98C138 93 144 91 150 91L212 91 212 128Z"], wheels: [112, 320], r: 22 },
  };
  function carArt(l, R, pal, uid) {
    const kind = CAR[l.subtype] || CAR.sedan;
    const s = l.specs || {};
    const paint = PAINT[String(s.color || "").toLowerCase()] || ["#c9343f", "#2f62bd", "#e9e7e2", "#22222a", "#b9bdc6"][Math.floor(R() * 5)];
    let sky = "";
    for (let i = 0; i < 9; i++) { const w = 18 + R() * 30, h = 20 + R() * 55, x = i * 46 + R() * 10 - 10; sky += `<rect x="${x.toFixed(0)}" y="${(150 - h).toFixed(0)}" width="${w.toFixed(0)}" height="${h.toFixed(0)}" fill="#000" opacity=".28"/>`; }
    let streaks = "";
    for (let i = 0; i < 7; i++) { const y = 60 + R() * 100, x = R() * 300, w = 40 + R() * 120; streaks += `<rect x="${x.toFixed(0)}" y="${y.toFixed(0)}" width="${w.toFixed(0)}" height="1.4" rx=".7" fill="${pal[2]}" opacity="${(0.15 + R() * 0.35).toFixed(2)}"/>`; }
    const dx = kind.dx || 0;
    const wheel = (cx) => `<g transform="translate(${cx} 170)"><circle r="${kind.r}" fill="#0b0b0f"/><circle r="${kind.r * 0.62}" fill="url(#rim${uid})"/><circle r="${kind.r * 0.18}" fill="#2a2a33"/>
      ${[0, 72, 144, 216, 288].map((a) => `<rect x="-1.2" y="${-kind.r * 0.58}" width="2.4" height="${kind.r * 0.4}" fill="#3a3a44" transform="rotate(${a})"/>`).join("")}</g>`;
    return `
      <defs>
        <linearGradient id="sky${uid}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${pal[0]}"/><stop offset="1" stop-color="${pal[1]}"/></linearGradient>
        <radialGradient id="sun${uid}" cx=".5" cy=".5" r=".5"><stop offset="0" stop-color="${pal[2]}" stop-opacity=".9"/><stop offset="1" stop-color="${pal[2]}" stop-opacity="0"/></radialGradient>
        <linearGradient id="paint${uid}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".55"/><stop offset=".35" stop-color="#fff" stop-opacity=".08"/><stop offset=".6" stop-color="#000" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity=".45"/></linearGradient>
        <linearGradient id="glass${uid}" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="${pal[1]}"/><stop offset=".5" stop-color="#0a0a12"/><stop offset="1" stop-color="${pal[2]}" stop-opacity=".5"/></linearGradient>
        <radialGradient id="rim${uid}"><stop offset="0" stop-color="#d9dde5"/><stop offset="1" stop-color="#6b707a"/></radialGradient>
        <linearGradient id="beam${uid}" x1="1" y1="0" x2="0" y2="0"><stop offset="0" stop-color="#fff6d8" stop-opacity=".55"/><stop offset="1" stop-color="#fff6d8" stop-opacity="0"/></linearGradient>
      </defs>
      <rect width="400" height="220" fill="url(#sky${uid})"/>
      <circle cx="${(260 + R() * 100).toFixed(0)}" cy="${(55 + R() * 30).toFixed(0)}" r="90" fill="url(#sun${uid})"/>
      ${sky}
      <rect y="150" width="400" height="70" fill="#07070b" opacity=".75"/>
      <path d="M0 192 H400" stroke="${pal[2]}" stroke-opacity=".25" stroke-dasharray="18 14"/>
      ${streaks}
      <ellipse cx="${210 - dx / 2}" cy="${176}" rx="170" ry="9" fill="#000" opacity=".55"/>
      <g transform="translate(${dx / 2} 0)">
        <path d="M52 146 L-40 128 L-40 176 Z" fill="url(#beam${uid})"/>
        <path d="${kind.body}" fill="${paint}"/>
        <path d="${kind.body}" fill="url(#paint${uid})"/>
        ${kind.win.map((w) => `<path d="${w}" fill="url(#glass${uid})" stroke="#000" stroke-opacity=".4"/>`).join("")}
        ${kind.rails ? `<path d="M150 76 H300" stroke="#15151b" stroke-width="3" stroke-linecap="round"/>` : ""}
        <path d="M74 150 H${CAR[l.subtype] === CAR.hatchback ? 300 : 360}" stroke="#000" stroke-opacity=".25"/>
        <ellipse cx="58" cy="146" rx="7" ry="4" fill="#fff8e0"/><ellipse cx="58" cy="146" rx="16" ry="9" fill="#fff8e0" opacity=".25"/>
        <rect x="${CAR[l.subtype] === CAR.hatchback ? 304 : 360}" y="138" width="8" height="8" rx="2" fill="#ff3b4e"/>
        ${kind.wheels.map(wheel).join("")}
      </g>`;
  }
  // isometric helpers
  const ISO = { cx: 200, cy: 70, s: 15 };
  const P = (x, y, z) => [ISO.cx + (x - y) * 0.866 * ISO.s, ISO.cy + (x + y) * 0.5 * ISO.s - z * ISO.s];
  const poly = (pts, fill, extra = "") => `<polygon points="${pts.map((p) => p.map((n) => n.toFixed(1)).join(",")).join(" ")}" fill="${fill}" ${extra}/>`;
  function box(x, y, w, d, h, c, z0 = 0) {
    const top = [P(x, y, z0 + h), P(x + w, y, z0 + h), P(x + w, y + d, z0 + h), P(x, y + d, z0 + h)];
    const left = [P(x, y + d, z0), P(x + w, y + d, z0), P(x + w, y + d, z0 + h), P(x, y + d, z0 + h)];
    const right = [P(x + w, y, z0), P(x + w, y + d, z0), P(x + w, y + d, z0 + h), P(x + w, y, z0 + h)];
    return poly(left, c[1]) + poly(right, c[2]) + poly(top, c[0]);
  }
  function windows(x, y, w, d, h, R, glow, cols, rows, z0 = 0, lit = 0.55) {
    let out = "";
    const pw = w / cols, ph = h / rows;
    for (let i = 0; i < cols; i++) for (let j = 0; j < rows; j++) {   // +y face
      const on = R() < lit; const ax = x + i * pw + pw * 0.25, az = z0 + j * ph + ph * 0.3;
      out += poly([P(ax, y + d, az), P(ax + pw * 0.5, y + d, az), P(ax + pw * 0.5, y + d, az + ph * 0.45), P(ax, y + d, az + ph * 0.45)], on ? glow : "#000", `opacity="${on ? (0.6 + R() * 0.4).toFixed(2) : 0.25}"`);
    }
    const dc = Math.max(1, Math.round(cols * d / w)), pd = d / dc;
    for (let i = 0; i < dc; i++) for (let j = 0; j < rows; j++) {     // +x face
      const on = R() < lit; const ay = y + i * pd + pd * 0.25, az = z0 + j * ph + ph * 0.3;
      out += poly([P(x + w, ay, az), P(x + w, ay + pd * 0.5, az), P(x + w, ay + pd * 0.5, az + ph * 0.45), P(x + w, ay, az + ph * 0.45)], on ? glow : "#000", `opacity="${on ? (0.45 + R() * 0.4).toFixed(2) : 0.25}"`);
    }
    return out;
  }
  const tree = (x, y, R, c) => { const [px, py] = P(x, y, 0); const r = 6 + R() * 5; return `<rect x="${px - 1}" y="${py - 10}" width="2" height="10" fill="#1a1410"/><circle cx="${px}" cy="${py - 10 - r * 0.6}" r="${r}" fill="${c}"/><circle cx="${px - r * 0.3}" cy="${py - 10 - r}" r="${r * 0.45}" fill="#fff" opacity=".08"/>`; };
  function propertyArt(l, R, pal, uid) {
    let stars = "";
    for (let i = 0; i < 40; i++) stars += `<circle cx="${(R() * 400).toFixed(0)}" cy="${(R() * 120).toFixed(0)}" r="${(R() * 1.2 + 0.2).toFixed(1)}" fill="#fff" opacity="${(R() * 0.7 + 0.1).toFixed(2)}"/>`;
    const glow = pal[2];
    const C = { wall: ["#4b4566", "#2e2944", "#1e1b30"], ground: ["#1c2a24", "#121c18", "#0c1310"], soil: ["#4a3a26", "#2e2416", "#211a10"] };
    let scene = box(-4, -4, 11, 11, 0.3, C.ground);
    const t = l.subtype;
    if (t === "plot") {
      scene += box(-1.5, -1.5, 6, 6, 0.35, C.soil, 0.3);
      for (let i = 0; i <= 6; i++) scene += `<polyline points="${[P(-1.5 + i, -1.5, 0.66), P(-1.5 + i, 4.5, 0.66)].map((p) => p.join(",")).join(" ")}" stroke="${glow}" stroke-opacity=".35" stroke-width=".8" fill="none"/>`
        + `<polyline points="${[P(-1.5, -1.5 + i, 0.66), P(4.5, -1.5 + i, 0.66)].map((p) => p.join(",")).join(" ")}" stroke="${glow}" stroke-opacity=".35" stroke-width=".8" fill="none"/>`;
      [[-1.5, -1.5], [4.5, -1.5], [-1.5, 4.5], [4.5, 4.5]].forEach(([x, y]) => { scene += box(x - 0.12, y - 0.12, 0.24, 0.24, 1.6, [glow, "#8a6a2a", "#5a4419"], 0.3); });
      const [sx, sy] = P(1.5, 1.5, 3.4);
      scene += `<circle cx="${sx}" cy="${sy}" r="9" fill="${glow}"/><circle cx="${sx}" cy="${sy}" r="3.5" fill="#000" opacity=".6"/><path d="M${sx - 8} ${sy + 4} L${sx} ${sy + 22} L${sx + 8} ${sy + 4}Z" fill="${glow}"/>`
        + `<ellipse cx="${P(1.5, 1.5, 0.66)[0]}" cy="${P(1.5, 1.5, 0.66)[1]}" rx="22" ry="11" fill="none" stroke="${glow}" stroke-opacity=".6"><animate attributeName="rx" values="10;30;10" dur="3s" repeatCount="indefinite"/><animate attributeName="ry" values="5;15;5" dur="3s" repeatCount="indefinite"/></ellipse>`;
      for (let i = 0; i < 5; i++) scene += tree(-3.5 + R() * 1.5, -3.5 + i * 2.2, R, "#1f4a36");
    } else if (t === "house") {
      scene += box(-2, -1, 10, 9, 0.05, ["#203a2c", "#16281e", "#0f1c15"], 0.3);
      scene += box(-0.5, 0, 5, 4, 2.4, C.wall, 0.3) + windows(-0.5, 0, 5, 4, 2.4, R, glow, 4, 2, 0.3, 0.7);
      const r0 = 2.7, rh = 1.8;   // roof
      scene += poly([P(-0.5, 4, r0), P(4.5, 4, r0), P(4.5, 2, r0 + rh), P(-0.5, 2, r0 + rh)], "#5a2b2b") + poly([P(4.5, 0, r0), P(4.5, 4, r0), P(4.5, 2, r0 + rh)], "#3a1c1c")
        + poly([P(-0.5, 0, r0), P(4.5, 0, r0), P(4.5, 2, r0 + rh), P(-0.5, 2, r0 + rh)], "#7a3a36", `opacity=".001"`);
      scene += box(5, 1, 2.5, 3, 1.6, ["#3d3856", "#26223a", "#1a1729"], 0.3) + windows(5, 1, 2.5, 3, 1.6, R, glow, 2, 1, 0.3, 0.8);
      scene += poly([P(1.6, 4, 0.3), P(2.4, 4, 0.3), P(2.4, 4, 1.5), P(1.6, 4, 1.5)], glow, `opacity=".9"`);
      for (let i = 0; i < 4; i++) scene += tree(-2.6 + R(), 5 + R() * 2, R, "#24553d");
      scene += tree(6.5, 5.6, R, "#2a6046");
    } else if (t === "apartment") {
      const h1 = 6 + R() * 2, h2 = 3.5 + R() * 2;
      scene += box(3.5, -2.5, 2.6, 2.6, h2, C.wall, 0.3) + windows(3.5, -2.5, 2.6, 2.6, h2, R, glow, 3, Math.round(h2 * 1.4), 0.3, 0.5);
      scene += box(-0.5, 0, 3, 3, h1, ["#544e74", "#332e4c", "#221f36"], 0.3) + windows(-0.5, 0, 3, 3, h1, R, glow, 3, Math.round(h1 * 1.4), 0.3, 0.6);
      const [ax, ay] = P(1, 1.5, h1 + 0.3);
      scene += `<line x1="${ax}" y1="${ay}" x2="${ax}" y2="${ay - 22}" stroke="#aaa" stroke-width="1.2"/><circle cx="${ax}" cy="${ay - 23}" r="2.6" fill="#ff3b4e"><animate attributeName="opacity" values="1;.15;1" dur="1.6s" repeatCount="indefinite"/></circle>`;
      for (let i = 0; i < 4; i++) scene += tree(-3 + R() * 0.8, 3 + i * 1.3, R, "#1f4a36");
    } else {
      scene += box(-2, -1, 7, 4, 3.2, ["#3c4a66", "#243048", "#182033"], 0.3);
      for (let j = 0; j < 4; j++) {
        const z = 0.3 + 0.4 + j * 0.75;
        scene += poly([P(-2, 3, z), P(5, 3, z), P(5, 3, z + 0.42), P(-2, 3, z + 0.42)], glow, `opacity="${(0.35 + R() * 0.5).toFixed(2)}"`)
          + poly([P(5, -1, z), P(5, 3, z), P(5, 3, z + 0.42), P(5, -1, z + 0.42)], glow, `opacity="${(0.2 + R() * 0.3).toFixed(2)}"`);
      }
      const [bx, by] = P(1.5, 1, 3.5);
      scene += `<rect x="${bx - 30}" y="${by - 18}" width="60" height="14" rx="3" fill="#07070b" stroke="${glow}"/><text x="${bx}" y="${by - 8}" font-family="monospace" font-size="8" fill="${glow}" text-anchor="middle" letter-spacing="2">OPEN</text>`;
      for (let i = 0; i < 5; i++) scene += tree(-3.3, -2 + i * 1.6, R, "#1f4a36");
    }
    return `
      <defs>
        <linearGradient id="sky${uid}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${pal[0]}"/><stop offset="1" stop-color="${pal[1]}"/></linearGradient>
        <radialGradient id="halo${uid}" cx=".5" cy=".6" r=".55"><stop offset="0" stop-color="${glow}" stop-opacity=".35"/><stop offset="1" stop-color="${glow}" stop-opacity="0"/></radialGradient>
      </defs>
      <rect width="400" height="220" fill="url(#sky${uid})"/>${stars}
      <circle cx="${(40 + R() * 80).toFixed(0)}" cy="${(30 + R() * 20).toFixed(0)}" r="11" fill="#fff6e0" opacity=".85"/>
      <rect width="400" height="220" fill="url(#halo${uid})"/>
      <g transform="translate(0 ${t === "apartment" ? 52 : 30})">${scene}</g>`;
  }
  function art(l) {
    const seed = hash(l.id);
    const R = rng(seed);
    const pal = PALETTES[seed % PALETTES.length];
    const uid = l.id.replace(/[^a-zA-Z0-9]/g, "");
    const inner = l.category === "car" ? carArt(l, R, pal, uid) : propertyArt(l, R, pal, uid);
    return `<svg class="art" viewBox="0 0 400 220" preserveAspectRatio="xMidYMid slice" aria-hidden="true">${inner}</svg>`;
  }

  // ---------- listings
  let cat = "";
  function specChips(l) {
    const s = l.specs || {};
    if (l.category === "car") return [l.year, s.mileage_km != null ? `${Number(s.mileage_km).toLocaleString()} km` : null, s.transmission, s.fuel].filter(Boolean);
    return [s.size, s.beds ? `${s.beds} bed` : null, s.possession === "yes" ? "possession" : null].filter(Boolean);
  }
  function card(l, i) {
    return `
      <article class="card" style="animation-delay:${Math.min(i, 12) * 45}ms">
        <div class="thumb">${art(l)}<span class="badge">${esc(l.id)}</span><span class="badge badge-r">${esc(l.subtype || l.category)}</span></div>
        <div class="card-body">
          <div class="card-title">${esc(l.title)}</div>
          <div class="price"><small>PKR</small>${esc(l.price_text)}</div>
          <div class="meta">📍 ${esc(l.area)}, ${esc(l.city)} · ${esc(l.dealer)}</div>
          <div class="specs">${specChips(l).map((x) => `<span>${esc(x)}</span>`).join("")}</div>
          <div class="card-actions">
            <button class="btn btn-ghost" data-ask="Tell me more about ${esc(l.id)}">Ask</button>
            <button class="btn btn-primary" data-ask="I'd like to book a ${l.category === "car" ? "test drive" : "site visit"} for ${esc(l.id)}">${l.category === "car" ? "Test drive" : "Book visit"}</button>
          </div>
        </div>
      </article>`;
  }
  let marqueeFilled = false;
  function fillMarquee(data) {
    if (marqueeFilled || !data.length) return; marqueeFilled = true;
    const item = (l) => `<span class="m-item" data-ask="Tell me more about ${esc(l.id)}"><span class="m-id">${esc(l.id)}</span><b>${esc(l.title)}</b><span class="m-price">${esc(l.price_text)}</span></span>`;
    const half = Math.ceil(data.length / 2);
    [[data.slice(0, half), "#marqueeA"], [data.slice(half), "#marqueeB"]].forEach(([rows, sel]) => {
      const html = rows.map(item).join(""); $(sel + " .track").innerHTML = html + html;
    });
  }
  async function loadListings() {
    const p = new URLSearchParams();
    if (cat) p.set("category", cat);
    if ($("#cityFilter").value) p.set("city", $("#cityFilter").value);
    if ($("#budgetFilter").value) p.set("max_price", $("#budgetFilter").value);
    if ($("#searchBox").value.trim()) p.set("q", $("#searchBox").value.trim());
    try {
      const res = await fetch(`${API}/api/listings?${p}`);
      const data = await res.json();
      if (!p.toString()) {
        const st = $("#statListings"); st.dataset.count = data.length; if (st.dataset.done) st.textContent = data.length;
        fillMarquee(data);
      }
      $("#resultCount").textContent = `${data.length} result${data.length === 1 ? "" : "s"}`;
      $("#grid").innerHTML = data.length ? data.map(card).join("") : `<div class="empty">No listings match. Try the assistant, it can widen the search for you.</div>`;
    } catch {
      $("#grid").innerHTML = `<div class="empty">Couldn't reach the DealDesk API at ${esc(API)}. Is the backend running?</div>`;
    }
  }
  function setCat(c) {
    cat = c;
    $$("#catTabs button").forEach((x) => x.classList.toggle("active", x.dataset.cat === c));
    moveInk(); loadListings();
  }
  function moveInk() {
    const a = $("#catTabs button.active"), ink = $(".tab-ink"); if (!a || !ink) return;
    ink.style.width = a.offsetWidth + "px"; ink.style.transform = `translateX(${a.offsetLeft - 4}px)`;
  }
  $("#catTabs").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) setCat(b.dataset.cat); });
  ["#cityFilter", "#budgetFilter"].forEach((s) => $(s).addEventListener("change", loadListings));
  let t; $("#searchBox").addEventListener("input", () => { clearTimeout(t); t = setTimeout(loadListings, 300); });
  $$(".world").forEach((w) => w.addEventListener("click", () => { setCat(w.dataset.world); $("#listings").scrollIntoView({ behavior: "smooth" }); }));
  window.addEventListener("resize", moveInk);
  document.fonts && document.fonts.ready.then(moveInk);

  // card tilt + spotlight
  const grid = $("#grid");
  grid.addEventListener("pointermove", (e) => {
    const c = e.target.closest(".card"); if (!c || e.pointerType !== "mouse") return;
    const r = c.getBoundingClientRect(), x = (e.clientX - r.left) / r.width, y = (e.clientY - r.top) / r.height;
    c.style.setProperty("--mx", x * 100 + "%"); c.style.setProperty("--my", y * 100 + "%");
    if (!reduced) { c.style.setProperty("--ry", (x - 0.5) * 10 + "deg"); c.style.setProperty("--rx", (0.5 - y) * 8 + "deg"); }
  });
  grid.addEventListener("pointerout", (e) => {
    const c = e.target.closest(".card"); if (c && !c.contains(e.relatedTarget)) { c.style.setProperty("--rx", "0deg"); c.style.setProperty("--ry", "0deg"); }
  });

  // ---------- chat
  const body = $("#chatBody");
  const historyKey = () => `dd_hist_${userId}_${threadId}`;
  const linkify = (text) => esc(text).replace(/\b([PC]-\d{2,4})\b/g, '<span class="lid" data-ask="Tell me more about $1">$1</span>');
  function addMsg(role, text, tools) {
    const div = document.createElement("div");
    div.className = "msg " + (role === "user" ? "user" : "bot");
    if (role === "user") div.textContent = text; else div.innerHTML = linkify(text);
    body.appendChild(div);
    if (tools && tools.length) {
      const chips = document.createElement("div");
      chips.className = "tool-chips";
      chips.innerHTML = tools.map((x) => `<span class="tool-chip">⚙ ${esc(x.name)}${x.status === "awaiting_customer_confirmation" ? " · needs OK" : ""}</span>`).join("");
      body.appendChild(chips);
    }
    body.scrollTop = body.scrollHeight;
  }
  function saveHist(role, text, tools) {
    let h = []; try { h = JSON.parse(store.get(historyKey(), "[]")); } catch {}
    h.push({ role, text, tools }); store.set(historyKey(), JSON.stringify(h.slice(-40)));
  }
  function restore() {
    body.innerHTML = "";
    let h = []; try { h = JSON.parse(store.get(historyKey(), "[]")); } catch {}
    if (!h.length) addMsg("bot", `Hi${userLabel ? " " + userLabel.split(/[@ ]/)[0] : ""}! I'm DealDesk. Looking for a property or a car? Tell me your budget and area, e.g. "Corolla under 60 lakh".`);
    h.forEach((m) => addMsg(m.role, m.text, m.tools));
  }
  let busy = false;
  async function send(text) {
    text = text.trim(); if (!text || busy) return;
    openChat(); busy = true;
    addMsg("user", text); saveHist("user", text);
    const typing = document.createElement("div"); typing.className = "typing"; typing.innerHTML = "<i></i><i></i><i></i>";
    body.appendChild(typing); body.scrollTop = body.scrollHeight;
    try {
      const res = await fetch(`${API}/chat`, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: userId, thread_id: threadId, message: text }) });
      const data = await res.json();
      typing.remove();
      addMsg("bot", data.reply || "Sorry, something went wrong.", data.tool_calls); saveHist("bot", data.reply, data.tool_calls);
    } catch {
      typing.remove(); addMsg("bot", "I couldn't reach the server. Please try again.");
    } finally { busy = false; }
  }
  function openChat() { $("#chatPanel").classList.add("open"); $("#chatFab").style.display = "none"; setTimeout(() => $("#chatInput").focus(), 50); }
  $("#chatFab").onclick = openChat;
  $("#closeChat").onclick = () => { $("#chatPanel").classList.remove("open"); $("#chatFab").style.display = ""; };
  $("#newChat").onclick = () => { threadId = newThreadId(); renderWho(); restore(); };
  $("#chatForm").addEventListener("submit", (e) => { e.preventDefault(); const v = $("#chatInput").value; $("#chatInput").value = ""; send(v); });
  document.addEventListener("click", (e) => { const b = e.target.closest("[data-ask]"); if (b) send(b.dataset.ask); });

  // ---------- sign-in modal
  $("#whoBtn").onclick = () => { $("#whoInput").value = userLabel; $("#whoModal").classList.add("open"); $("#whoInput").focus(); };
  $("#whoCancel").onclick = () => $("#whoModal").classList.remove("open");
  $("#whoInput").addEventListener("keydown", (e) => { if (e.key === "Enter") $("#whoSave").click(); });
  $("#whoSave").onclick = () => {
    const v = $("#whoInput").value.trim(); if (!v) return;
    userLabel = v; userId = "web-" + slug(v);
    store.set("dd_user", userId); store.set("dd_user_label", userLabel);
    threadId = store.get("dd_thread_" + userId, "") || newThreadId();
    $("#whoModal").classList.remove("open"); renderWho(); restore();
  };

  // =========================================================
  // Motion & ambience
  // =========================================================
  // reveal on scroll + counters
  const countUp = (el) => {
    if (el.dataset.done) return; el.dataset.done = "1";
    const target = Number(el.dataset.count) || 0, t0 = performance.now(), dur = reduced ? 1 : 1400;
    const step = (now) => { const k = Math.min(1, (now - t0) / dur); el.textContent = Math.round(target * (1 - Math.pow(1 - k, 3))); if (k < 1) requestAnimationFrame(step); else el.textContent = el.dataset.count; };
    requestAnimationFrame(step);
  };
  const io = new IntersectionObserver((ents) => ents.forEach((en) => {
    if (!en.isIntersecting) return;
    en.target.classList.add("in"); en.target.querySelectorAll("[data-count]").forEach(countUp); io.unobserve(en.target);
  }), { threshold: 0.12 });
  $$(".reveal").forEach((el, i) => { el.style.transitionDelay = (el.closest(".hero") ? 0.35 + i * 0.08 : 0) + "s"; io.observe(el); });

  // top bar
  const topbar = $(".topbar");
  const onScroll = () => {
    topbar.classList.toggle("scrolled", scrollY > 30);
    const g = $("#galleryTrack");
    if (g && !reduced) {
      const r = g.parentElement.getBoundingClientRect(), vh = innerHeight;
      const prog = (vh - r.top) / (vh + r.height);
      g.style.transform = `translateX(${-(Math.max(0, Math.min(1, prog))) * (g.scrollWidth - innerWidth + 48)}px)`;
    }
  };
  addEventListener("scroll", onScroll, { passive: true }); onScroll();

  // cursor glow + magnetic buttons
  const glow = $("#cursorGlow"); let gx = -999, gy = -999, tx = -999, ty = -999;
  addEventListener("pointermove", (e) => { tx = e.clientX; ty = e.clientY; }, { passive: true });
  (function loop() { gx += (tx - gx) * 0.12; gy += (ty - gy) * 0.12; glow.style.transform = `translate3d(${gx}px,${gy}px,0)`; requestAnimationFrame(loop); })();
  $$(".magnetic").forEach((b) => {
    b.addEventListener("pointermove", (e) => { const r = b.getBoundingClientRect(); b.style.transform = `translate(${(e.clientX - r.left - r.width / 2) * 0.25}px, ${(e.clientY - r.top - r.height / 2) * 0.35}px)`; });
    b.addEventListener("pointerleave", () => { b.style.transform = ""; });
  });

  // calendar viz
  const cal = $("#calViz");
  if (cal) { const d0 = new Date(); let h = ""; for (let i = 0; i < 14; i++) { const d = new Date(d0); d.setDate(d0.getDate() + i); h += `<span class="${i === 4 ? "on" : ""}">${d.getDate()}</span>`; } cal.innerHTML = h; }

  // hero demo conversation
  const demo = $("#demoBody");
  const script = [
    ["user", "Corolla under 60 lakh, Lahore"],
    ["bot", "Found 3 at Prime Motors:\nC-303 Altis X 2022 · 59.5 lakh\nC-302 Altis 1.6 2020 · 54 lakh\nC-301 GLi 2019 · 46 lakh"],
    ["user", "Test drive C-302 on Saturday 4pm"],
    ["bot", "Please confirm: test drive for C-302 on Sat, 4:00 PM. Reply YES."],
    ["user", "YES"],
    ["bot", "Booked ✓ Prime Motors will confirm your slot shortly."],
  ];
  async function runDemo() {
    const wait = (ms) => new Promise((r) => setTimeout(r, ms));
    while (true) {
      demo.innerHTML = "";
      for (const [role, text] of script) {
        if (role === "bot") { const ty = document.createElement("div"); ty.className = "typing"; ty.innerHTML = "<i></i><i></i><i></i>"; demo.appendChild(ty); await wait(1100); ty.remove(); }
        const m = document.createElement("div"); m.className = "msg " + role; if (role === "bot") m.innerHTML = linkify(text); else m.textContent = text;
        demo.appendChild(m); await wait(role === "user" ? 900 : 1700);
      }
      await wait(2600);
    }
  }
  if (demo) { if (reduced) script.forEach(([r, x]) => { const m = document.createElement("div"); m.className = "msg " + r; m.textContent = x; demo.appendChild(m); }); else runDemo(); }

  renderWho(); restore(); loadListings(); moveInk();
})();

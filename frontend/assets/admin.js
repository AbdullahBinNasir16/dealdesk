(() => {
  const API = window.DEALDESK_API;
  const $ = (s) => document.querySelector(s);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const store = { get(k) { try { return localStorage.getItem(k); } catch { return null; } },
                  set(k, v) { try { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch {} } };
  let token = store.get("dd_admin_token");
  let agency = JSON.parse(store.get("dd_admin_agency") || "null");
  const STAGES = ["new", "qualifying", "qualified", "visit_booked", "visited", "won", "lost"];
  const STAGE_LABEL = { new: "New", qualifying: "Qualifying", qualified: "Qualified", visit_booked: "Visit booked", visited: "Visited", won: "Won", lost: "Lost" };

  function toast(msg) { const t = $("#toast"); t.textContent = msg; t.style.display = "block"; setTimeout(() => (t.style.display = "none"), 2200); }
  const fmtDate = (s) => { if (!s) return ""; const d = new Date(s); return isNaN(d) ? s : d.toLocaleString([], { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }); };

  async function api(path, opts = {}) {
    const res = await fetch(API + path, { ...opts, headers: { "Content-Type": "application/json", Authorization: "Bearer " + token, ...(opts.headers || {}) } });
    if (res.status === 401) { logout(); throw new Error("auth"); }
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText);
    return res.json();
  }

  // ---------- auth
  $("#loginForm").addEventListener("submit", async (e) => {
    e.preventDefault(); $("#loginError").textContent = "";
    try {
      const res = await fetch(API + "/admin/login", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: $("#username").value, password: $("#password").value }) });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Login failed");
      token = data.token; agency = data.agency;
      store.set("dd_admin_token", token); store.set("dd_admin_agency", JSON.stringify(agency));
      boot();
    } catch (err) { $("#loginError").textContent = err.message === "Failed to fetch" ? "Can't reach the API." : err.message; }
  });
  document.querySelectorAll(".demo-acc").forEach((d) => d.addEventListener("click", () => {
    $("#username").value = d.dataset.u; $("#password").value = d.dataset.p; $("#password").focus();
  }));
  function logout() { token = null; store.set("dd_admin_token", null); $("#appView").style.display = "none"; $("#loginView").style.display = ""; }
  $("#logout").onclick = (e) => { e.preventDefault(); logout(); };

  // ---------- navigation
  let view = "overview";
  $("#sidebar").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-view]"); if (!b) return;
    document.querySelectorAll("#sidebar button").forEach((x) => x.classList.toggle("active", x === b));
    view = b.dataset.view; render();
  });

  async function refreshCounts() {
    try {
      const s = await api("/admin/stats");
      const a = $("#cntApprove"), f = $("#cntFollow");
      a.textContent = s.approval_queue; a.style.display = s.approval_queue ? "" : "none";
      f.textContent = s.followups_pending; f.style.display = s.followups_pending ? "" : "none";
      return s;
    } catch { return null; }
  }

  const views = {
    async overview(m) {
      const s = await refreshCounts();
      const leadsList = await api("/admin/leads");
      m.innerHTML = `<h1>Good day, <em>${esc(agency.name)}</em></h1><p class="sub">Your AI sales desk at a glance.</p>
        <div class="kpis">
          <div class="kpi"><b>${s.leads_total}</b><span>Total leads</span></div>
          <div class="kpi"><b>${(s.leads_by_stage.qualified || 0)}</b><span>Qualified, not booked</span></div>
          <div class="kpi"><b>${(s.leads_by_stage.visit_booked || 0)}</b><span>Visits booked</span></div>
          <div class="kpi"><b>${s.approval_queue}</b><span>Awaiting your approval</span></div>
          <div class="kpi"><b>${s.followups_pending}</b><span>Follow-ups scheduled</span></div>
          <div class="kpi"><b>${s.booking_rate}%</b><span>Lead → visit rate</span></div>
        </div>
        <div class="panel"><h3>Latest leads</h3>${leadsTable(leadsList.slice(0, 8))}</div>`;
    },
    async pipeline(m) {
      const list = await api("/admin/leads");
      const cols = ["new", "qualifying", "qualified", "visit_booked", "visited", "won"];
      m.innerHTML = `<h1>Leads pipeline</h1><p class="sub">Leads are created automatically when a customer views or books your listings. Move them as deals progress.</p>
        <div class="kanban">${cols.map((c) => {
          const items = list.filter((l) => l.stage === c || (c === "won" && l.stage === "lost"));
          return `<div class="col"><h4>${STAGE_LABEL[c]}${c === "won" ? " / Lost" : ""} <span>${items.length}</span></h4>${items.map(leadCard).join("") || '<div class="meta" style="padding:4px">No leads</div>'}</div>`;
        }).join("")}</div>`;
      m.querySelectorAll("select[data-lead]").forEach((sel) => sel.addEventListener("change", async () => {
        await api(`/admin/leads/${sel.dataset.lead}`, { method: "PATCH", body: JSON.stringify({ stage: sel.value }) });
        toast("Lead moved"); render();
      }));
    },
    async visits(m) {
      const list = await api("/admin/visits");
      const queue = list.filter((v) => v.status === "requested");
      const rest = list.filter((v) => v.status !== "requested");
      const row = (v, actions) => `<tr><td><b>V-${v.id}</b></td><td>${fmtDate(v.scheduled_at)}</td><td>${esc(v.title)}<div class="meta">${esc(v.listing_id)} · ${v.kind === "test_drive" ? "Test drive" : "Site visit"}</div></td>
        <td>${esc(v.customer_name || "—")}<div class="meta">${esc(v.customer_phone || "no phone yet")}</div></td><td><span class="pill ${v.status}">${v.status}</span></td><td>${actions(v)}</td></tr>`;
      m.innerHTML = `<h1>Visits & approvals</h1><p class="sub">Customers confirm in chat; your team approves the slot here.</p>
        <div class="panel"><h3>Approval queue (${queue.length})</h3>${queue.length ? `<table><tr><th>Ref</th><th>When</th><th>Listing</th><th>Customer</th><th>Status</th><th></th></tr>
          ${queue.map((v) => row(v, (x) => `<button class="btn btn-ok btn-sm" data-visit="${x.id}" data-status="confirmed">Approve</button> <button class="btn btn-bad btn-sm" data-visit="${x.id}" data-status="declined">Decline</button>`)).join("")}</table>` : '<p class="meta">Nothing waiting. 🎉</p>'}</div>
        <div class="panel"><h3>Visit calendar</h3>${rest.length ? `<table><tr><th>Ref</th><th>When</th><th>Listing</th><th>Customer</th><th>Status</th><th></th></tr>
          ${rest.map((v) => row(v, (x) => x.status === "confirmed" ? `<button class="btn btn-ghost btn-sm" data-visit="${x.id}" data-status="completed">Mark visited</button>` : "")).join("")}</table>` : '<p class="meta">No visits yet.</p>'}</div>`;
      m.querySelectorAll("button[data-visit]").forEach((b) => b.addEventListener("click", async () => {
        await api(`/admin/visits/${b.dataset.visit}`, { method: "PATCH", body: JSON.stringify({ status: b.dataset.status }) });
        toast("Visit " + b.dataset.status); render();
      }));
    },
    async followups(m) {
      const list = await api("/admin/followups");
      m.innerHTML = `<h1>Follow-ups</h1><p class="sub">Leads that didn't book get an automatic day 1 / 3 / 7 sequence. Booking a visit cancels the rest.</p>
        <div class="panel">${list.length ? `<table><tr><th>Due</th><th>Customer</th><th>Day</th><th>Message</th><th>Status</th><th></th></tr>
        ${list.map((f) => `<tr><td>${fmtDate(f.due_at)}</td><td>${esc(f.name || f.user_id)}<div class="meta">${esc(f.phone || "")}</div></td><td>Day ${f.day}</td>
          <td style="max-width:420px">${esc(f.message)}</td><td><span class="pill ${f.status}">${f.status}</span></td>
          <td>${f.status === "pending" ? `<button class="btn btn-ghost btn-sm" data-fu="${f.id}">Mark sent</button>` : ""}</td></tr>`).join("")}</table>` : '<p class="meta">No follow-ups scheduled.</p>'}</div>`;
      m.querySelectorAll("button[data-fu]").forEach((b) => b.addEventListener("click", async () => {
        await api(`/admin/followups/${b.dataset.fu}/sent`, { method: "POST" }); toast("Marked as sent"); render();
      }));
    },
    async chats(m) {
      const list = await api("/admin/chats");
      m.innerHTML = `<h1>Chat history</h1><p class="sub">Conversations from customers who engaged with your listings.</p>
        <div style="display:grid;grid-template-columns:minmax(220px,320px) 1fr;gap:16px" class="chat-admin">
          <div class="panel" style="margin:0">${list.length ? list.map((c) => `<div class="lead" style="cursor:pointer" data-u="${esc(c.user_id)}" data-t="${esc(c.thread_id)}">
            <b>${esc(c.user_id)}</b><div class="meta">${esc(c.thread_id)} · ${c.messages} msgs</div><div class="meta">${fmtDate(c.last_at)}</div></div>`).join("") : '<p class="meta">No conversations yet.</p>'}</div>
          <div class="panel" style="margin:0"><div id="transcript" class="meta">Select a conversation.</div></div></div>`;
      m.querySelectorAll("[data-u]").forEach((el) => el.addEventListener("click", async () => {
        const rows = await api(`/admin/chats/${encodeURIComponent(el.dataset.u)}/${encodeURIComponent(el.dataset.t)}`);
        $("#transcript").className = "transcript";
        $("#transcript").innerHTML = rows.map((r) => `<div class="msg ${r.role === "user" ? "user" : "bot"}">${esc(r.content)}</div>
          ${(r.tool_calls || []).length ? `<div class="tool-chips">${r.tool_calls.map((t) => `<span class="tool-chip">⚙ ${esc(t.name)}</span>`).join("")}</div>` : ""}`).join("");
      }));
    },
    async listings(m) {
      const list = await api("/admin/listings");
      const isCar = agency.kind === "car";
      m.innerHTML = `<h1>Listings</h1><p class="sub">${list.filter((l) => l.status === "active").length} active. The assistant only recommends active listings.</p>
        <div class="panel"><h3>Add a listing</h3>
          <form id="addForm" class="form-grid">
            <input class="input" name="title" placeholder="Title" required />
            <input class="input" name="price_pkr" type="number" placeholder="Price (PKR)" required />
            <input class="input" name="city" placeholder="City" value="${esc(agency.city || "")}" required />
            <input class="input" name="area" placeholder="${isCar ? "Showroom / area" : "Area e.g. DHA Phase 6"}" />
            <input class="input" name="subtype" placeholder="${isCar ? "sedan / suv / hatchback" : "plot / house / apartment"}" />
            ${isCar ? '<input class="input" name="make" placeholder="Make" /><input class="input" name="model" placeholder="Model" /><input class="input" name="year" type="number" placeholder="Year" />' : '<input class="input" name="size" placeholder="Size e.g. 10 marla" />'}
            <input class="input" name="description" placeholder="Short description" />
            <button class="btn btn-primary" type="submit">Add listing</button>
          </form></div>
        <div class="panel"><h3>Bulk upload (CSV)</h3>
          <p class="meta">Columns: title,price_pkr,city,area,subtype,make,model,year,description. Extra columns (size, beds, mileage_km, transmission…) are saved as specs.</p>
          <input type="file" id="csvFile" accept=".csv,text/csv" /> <button class="btn btn-ghost btn-sm" id="csvBtn">Upload</button></div>
        <div class="panel"><table><tr><th>ID</th><th>Title</th><th>Price</th><th>Location</th><th>Status</th><th></th></tr>
          ${list.map((l) => `<tr><td><b>${esc(l.id)}</b></td><td>${esc(l.title)}</td><td>${esc(l.price_text)}</td><td>${esc(l.area)}, ${esc(l.city)}</td>
            <td><span class="pill ${l.status === "active" ? "confirmed" : "cancelled"}">${l.status}</span></td>
            <td><select class="input" data-listing="${esc(l.id)}" style="padding:4px 6px">${["active", "sold", "hidden"].map((s) => `<option ${s === l.status ? "selected" : ""}>${s}</option>`).join("")}</select></td></tr>`).join("")}</table></div>`;
      $("#addForm").addEventListener("submit", async (e) => {
        e.preventDefault();
        const f = Object.fromEntries(new FormData(e.target).entries());
        const body = { title: f.title, price_pkr: Number(f.price_pkr), city: f.city, area: f.area, subtype: f.subtype,
          make: f.make || "", model: f.model || "", year: f.year ? Number(f.year) : null, description: f.description,
          specs: f.size ? { size: f.size } : {} };
        try { const r = await api("/admin/listings", { method: "POST", body: JSON.stringify(body) }); toast("Added " + r.id); render(); }
        catch (err) { toast(err.message); }
      });
      $("#csvBtn").onclick = async () => {
        const file = $("#csvFile").files[0]; if (!file) return toast("Choose a CSV file first");
        const r = await api("/admin/listings/upload", { method: "POST", body: JSON.stringify({ csv: await file.text() }) });
        toast(`Created ${r.created.length}, errors ${r.errors.length}`); render();
      };
      m.querySelectorAll("select[data-listing]").forEach((sel) => sel.addEventListener("change", async () => {
        await api(`/admin/listings/${sel.dataset.listing}`, { method: "PATCH", body: JSON.stringify({ status: sel.value }) }); toast("Updated");
      }));
    },
  };

  function leadsTable(list) {
    if (!list.length) return '<p class="meta">No leads yet. They appear when customers view or book your listings in chat.</p>';
    return `<table><tr><th>Customer</th><th>Wants</th><th>Budget</th><th>Area</th><th>Timeline</th><th>Stage</th><th>Score</th></tr>
      ${list.map((l) => `<tr><td><b>${esc(l.name || l.user_id)}</b><div class="meta">${esc(l.phone || "")}</div></td><td>${esc(l.want || "—")}</td>
        <td>${esc(l.budget)}</td><td>${esc(l.area || "—")}</td><td>${esc(l.timeline || "—")}</td>
        <td><span class="pill ${l.stage}">${STAGE_LABEL[l.stage] || l.stage}</span></td><td>${l.score}</td></tr>`).join("")}</table>`;
  }
  function leadCard(l) {
    return `<div class="lead"><span class="score">${l.score}</span><b>${esc(l.name || l.user_id)}</b>
      <div class="meta">${esc(l.want || "")} · ${esc(l.budget)}${l.area ? " · " + esc(l.area) : ""}</div>
      ${l.timeline ? `<div class="meta">⏱ ${esc(l.timeline)}</div>` : ""}
      ${(l.objections || []).length ? `<div class="meta">⚠ ${esc(l.objections.join(", "))}</div>` : ""}
      <div class="meta">Viewed: ${esc((l.interested || []).join(", "))}</div>
      <select data-lead="${l.id}">${STAGES.map((s) => `<option value="${s}" ${s === l.stage ? "selected" : ""}>${STAGE_LABEL[s]}</option>`).join("")}</select></div>`;
  }

  async function render() {
    const m = $("#main");
    m.innerHTML = '<p class="meta">Loading…</p>';
    try { await views[view](m); if (view !== "overview") refreshCounts(); }
    catch (err) { if (err.message !== "auth") m.innerHTML = `<p class="error">Couldn't load: ${esc(err.message)}</p>`; }
  }
  function boot() {
    $("#loginView").style.display = "none"; $("#appView").style.display = "";
    $("#agencyName").textContent = agency ? agency.name : "";
    render();
  }
  if (token && agency) boot();
})();

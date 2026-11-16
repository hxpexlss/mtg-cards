"use strict";
/* MTG Cards – Karte nachschlagen: beliebige Karte per Name ansehen, ohne sie zu speichern. */

const lk = { card: null, back: false, prints: [] };
const FORMATS = { commander: "Commander", standard: "Standard", pioneer: "Pioneer", modern: "Modern", legacy: "Legacy",
  vintage: "Vintage", pauper: "Pauper", brawl: "Brawl" };
const LEGAL = { legal: ["✓", "ok"], not_legal: ["✗", ""], banned: ["gebannt", "bad"], restricted: ["beschränkt", "warn"] };

function openLookup(name) {
  let dlg = $("#dlg-lookup");
  if (!dlg) {
    dlg = document.createElement("dialog");
    dlg.id = "dlg-lookup";
    dlg.className = "modal wide";
    document.body.appendChild(dlg);
    dlg.addEventListener("click", (e) => { if (e.target === dlg || e.target.closest("[data-close]")) dlg.close(); });
  }
  dlg.innerHTML = `<div class="modal-body">
    <header><h2>🔍 Karte nachschlagen</h2><button class="x" data-close>×</button></header>
    <form class="row" id="lk-form" autocomplete="off">
      <input id="lk-name" list="lk-ac" placeholder="Kartenname (deutsch oder englisch) …" style="flex:1;min-width:220px" required>
      <datalist id="lk-ac"></datalist>
      <select id="lk-lang" style="width:auto" title="Sprache der Anzeige"><option value="">Englisch</option>
        ${Object.entries(LANG_NAMES).filter(([k]) => k !== "en").map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("")}</select>
      <button class="btn primary">Suchen</button>
    </form>
    <p class="muted small">Nur ansehen – gespeichert wird nur, wenn du unten „Zur Sammlung“ oder „Auf Wunschliste“ wählst.</p>
    <div id="lk-result"></div></div>`;
  const input = $("#lk-name", dlg);
  const ac = debounce(async () => {
    const q = input.value.trim();
    if (q.length < 2) return;
    try {
      const { data } = await api("/api/autocomplete?q=" + encodeURIComponent(q));
      $("#lk-ac", dlg).innerHTML = data.slice(0, 20).map((n) => `<option value="${esc(n)}">`).join("");
    } catch (_) { /* egal */ }
  }, 200);
  input.addEventListener("input", ac);
  $("#lk-form", dlg).addEventListener("submit", (e) => { e.preventDefault(); lookupCard("name=" + encodeURIComponent(input.value.trim())); });
  $("#lk-lang", dlg).onchange = () => { if (lk.card) lookupCard("id=" + encodeURIComponent(lk.card.scryfall_id)); };
  dlg.showModal();
  if (name) { input.value = name; lookupCard("name=" + encodeURIComponent(name)); } else input.focus();
}

async function lookupCard(query) {
  const box = $("#lk-result");
  const lang = $("#lk-lang").value;
  box.innerHTML = `<p class="muted">Suche …</p>`;
  try {
    lk.card = await api(`/api/lookup?${query}${lang ? "&lang=" + lang : ""}`);
    lk.back = false;
  } catch (e) { box.innerHTML = `<p class="muted">${esc(e.message)}</p>`; return; }
  renderLookup();
  try {
    lk.prints = (await api(`/api/prints?name=${encodeURIComponent(lk.card.name)}${lang ? "&lang=" + lang : ""}`)).data;
    renderLookup();
  } catch (_) { /* Drucke optional */ }
}

function renderLookup() {
  const c = lk.card;
  const box = $("#lk-result");
  const own = c.owned || {};
  const price = (v, cur = "€") => v ? (cur === "€" ? `${v} €` : `$${v}`) : "–";
  const pt = c.power != null ? `${c.power}/${c.toughness}` : (c.loyalty ? `Loyalität ${c.loyalty}` : "");
  const img = lk.back && c.image_url_back ? c.image_url_back : c.image_url;
  box.innerHTML = `<div class="card-detail">
    <div>${img ? `<img src="${esc(img)}" alt="" style="cursor:${c.image_url_back ? "pointer" : "default"}" id="lk-img"
        title="${c.image_url_back ? "Antippen: andere Seite" : ""}">` : ""}
      ${c.image_url_back ? `<div class="muted small" style="text-align:center">↻ Bild antippen für die ${lk.back ? "Vorderseite" : "Rückseite"}</div>` : ""}</div>
    <div>
      <h2 style="margin:0">${esc(c.name)} ${manaHtml(c.mana_cost)}</h2>
      ${c.printed_name && c.printed_name !== c.name ? `<div class="muted">${esc(c.printed_name)}</div>` : ""}
      <div class="typeline">${esc(c.type_line)} ${pt ? `<span class="muted">· ${esc(pt)}</span>` : ""}</div>
      <div class="oracle">${oracleHtml(c.oracle_text) || "<span class='muted'>Kein Regeltext</span>"}</div>
      ${c.flavor_text ? `<p class="muted small" style="font-style:italic">${esc(c.flavor_text)}</p>` : ""}
      <dl class="kv">
        <dt>Farbidentität</dt><dd>${ciHtml(c.color_identity)}</dd>
        <dt>Druck</dt><dd><select id="lk-print" style="max-width:100%">
          ${(lk.prints.length ? lk.prints.slice().reverse() : [c]).map((p) => `<option value="${esc(p.scryfall_id)}" ${p.scryfall_id === c.scryfall_id ? "selected" : ""}>
            ${esc(p.set_name)} (${esc(p.set_code)}) #${esc(p.collector_number)}${p.price_eur ? " · " + esc(p.price_eur) + " €" : ""}</option>`).join("")}</select></dd>
        <dt>Preis</dt><dd>${price(c.price_eur)} · Foil ${price(c.price_eur_foil)} <span class="muted">(${price(c.price_usd, "$")} / Foil ${price(c.price_usd_foil, "$")})</span></dd>
        ${c.artist ? `<dt>Künstler</dt><dd>${esc(c.artist)}</dd>` : ""}
        <dt>Legal</dt><dd><div class="tags">${Object.entries(c.legalities || {}).map(([f, v]) => {
          const [t, cls] = LEGAL[v] || [v, ""];
          return `<span class="pill ${cls}" title="${esc(v)}">${esc(FORMATS[f] || f)} ${t}</span>`;
        }).join(" ") || "–"}</div></dd>
        <dt>Bei dir</dt><dd>${own.all_prints ? `<b>${own.all_prints}×</b> in der Sammlung (${own.this_print || 0}× dieser Druck)` : "nicht in der Sammlung"}
          ${c.wished ? ` · ${c.wished}× auf der Wunschliste` : ""}
          ${(c.decks || []).length ? `<br>In Decks: ${c.decks.map((u) => `${esc(u.deck)} (${u.quantity})`).join(", ")}` : ""}</dd>
      </dl>
      <div class="row">
        <input id="lk-qty" type="number" min="1" value="1" style="width:64px" title="Anzahl">
        <label class="check" style="margin:0"><input type="checkbox" id="lk-foil"> Foil</label>
        <button class="btn primary" id="lk-add">＋ Zur Sammlung</button>
        <button class="btn" id="lk-wish">★ Auf Wunschliste</button>
        <button class="btn" id="lk-pm" title="In eine Druckliste oder ein Deck von Proxie Maker – zum Gestalten und Drucken">🖨 In Proxie Maker</button>
        ${c.scryfall_uri ? `<a class="btn" href="${esc(c.scryfall_uri)}" target="_blank" rel="noopener">Scryfall ↗</a>` : ""}
      </div>
    </div></div>`;
  const imgEl = $("#lk-img");
  if (imgEl && c.image_url_back) imgEl.onclick = () => { lk.back = !lk.back; renderLookup(); };
  $("#lk-print").onchange = (e) => lookupCard("id=" + encodeURIComponent(e.target.value));
  $("#lk-add").onclick = async () => {
    try {
      const r = await api("/api/cards", { method: "POST", json: { scryfall_id: c.scryfall_id, quantity: +$("#lk-qty").value || 1,
        foil: $("#lk-foil").checked } });
      toast(`${r.name} – jetzt ${r.quantity}× in der Sammlung`, "ok");
      if (typeof loadCards === "function") loadCards();
      lookupCard("id=" + encodeURIComponent(c.scryfall_id));
    } catch (e) { toast(e.message, "err"); }
  };
  $("#lk-pm").onclick = async () => {
    let projects;
    try { projects = (await api("/proxies/api/projects")).projects; } catch (e) { return toast(e.message, "err"); }
    const list = projects.map((p, i) => `${i + 1}: ${p.kind === "deck" ? "Deck: " : ""}${p.name}`).join("\n");
    const pick = prompt(`In welche Druckliste? Nummer eingeben – oder einen neuen Namen für eine neue Druckliste.\n\n${list}`,
      projects.length ? "1" : "Proxies");
    if (!pick) return;
    try {
      let pid;
      const n = parseInt(pick, 10);
      if (String(n) === pick.trim() && projects[n - 1]) pid = projects[n - 1].id;
      else pid = (await api("/proxies/api/projects", { method: "POST", json: { name: pick.trim() } })).project.id;
      await api(`/proxies/api/projects/${pid}/items`, { method: "POST",
        json: { scryfall_id: c.scryfall_id, quantity: +$("#lk-qty").value || 1 } });
      toast(`${c.name} ist in Proxie Maker`, "ok");
      if (confirm("Jetzt in Proxie Maker öffnen?")) {
        try { localStorage.setItem("pm-tab", projects.find((p) => p.id === pid)?.kind || "list");
          localStorage.setItem("pm-project-" + (projects.find((p) => p.id === pid)?.kind || "list"), String(pid)); } catch (_) { /* egal */ }
        location.href = "/proxies/";
      }
    } catch (e) { toast(e.message, "err"); }
  };
  $("#lk-wish").onclick = async () => {
    const specific = confirm("Genau diesen Druck wünschen?\n\nOK = dieser Druck\nAbbrechen = beliebiger (günstigster) Druck");
    try {
      const w = await api("/api/wishlist", { method: "POST", json: specific
        ? { scryfall_id: c.scryfall_id, quantity: +$("#lk-qty").value || 1, foil: $("#lk-foil").checked }
        : { name: c.name, any_print: true, quantity: +$("#lk-qty").value || 1, foil: $("#lk-foil").checked } });
      toast(`${w.name} auf der Wunschliste`, "ok");
      if (typeof refreshWishBadge === "function") refreshWishBadge();
    } catch (e) { toast(e.message, "err"); }
  };
}

(function bindLookup() {
  const btn = $("#btn-lookup");
  if (btn) btn.onclick = () => openLookup();
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); openLookup(); }
  });
})();

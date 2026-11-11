"use strict";
/* MTG Cards – Set-Sammelfortschritt */

const sets = { list: [], detail: null, scope: "main", rarity: "_all", show: "all", sort: "percent" };
const RARITY_LABEL = { _all: "Alle", common: "Common", uncommon: "Uncommon", rare: "Rare", mythic: "Mythic" };

async function loadSets() {
  const box = $("#sets-main");
  if (sets.detail) return renderSetDetail();
  box.innerHTML = `<p class="muted">Lade Editionen …</p>`;
  try { sets.list = (await api("/api/sets")).sets; } catch (e) { box.innerHTML = `<p class="muted">${esc(e.message)}</p>`; return; }
  renderSetList();
}

function sortedSets() {
  const l = [...sets.list];
  if (sets.sort === "name") l.sort((a, b) => (a.name || "").localeCompare(b.name || ""));
  else if (sets.sort === "released") l.sort((a, b) => (b.released || "").localeCompare(a.released || ""));
  else if (sets.sort === "cards") l.sort((a, b) => b.owned_cards - a.owned_cards);
  else l.sort((a, b) => (b.percent || 0) - (a.percent || 0));
  return l;
}

function renderSetList() {
  const box = $("#sets-main");
  box.innerHTML = `
    <div class="deck-head">
      <h2>Editionen</h2><span class="muted">${sets.list.length} Editionen in der Sammlung</span>
      <span class="spacer"></span>
      <form id="set-open" class="row" style="gap:6px">
        <input id="set-code" placeholder="Edition öffnen, z.B. MH3" style="width:200px">
        <button class="btn small">Öffnen</button>
      </form>
      <select id="set-sort" style="width:auto">
        <option value="percent">Fortschritt</option><option value="released">Neueste</option>
        <option value="name">Name</option><option value="cards">Anzahl Karten</option>
      </select>
    </div>
    <div class="set-grid">${sortedSets().map((s) => `
      <div class="set-item" data-set="${esc(s.code)}">
        <div class="set-top">${s.icon ? `<img class="set-icon" src="${esc(s.icon)}" alt="">` : ""}
          <div><div class="t">${esc(s.name)}</div><div class="muted small">${esc(s.code)}${s.released ? " · " + esc(s.released.slice(0, 4)) : ""}</div></div>
          <b class="pct">${s.percent == null ? "–" : Math.round(s.percent) + " %"}</b></div>
        <div class="progress"><div style="width:${Math.min(100, s.percent || 0)}%"></div></div>
        <div class="muted small">${s.main_owned}/${s.main_size || "?"} im Grundset · ${s.owned_prints} Drucke · ${s.owned_cards} Karten</div>
      </div>`).join("") || `<p class="muted">Noch keine Karten in der Sammlung.</p>`}</div>`;
  $("#set-sort").value = sets.sort;
}

async function openSet(code) {
  const box = $("#sets-main");
  box.innerHTML = `<p class="muted">Lade Kartenliste von ${esc(code.toUpperCase())} …</p>`;
  try {
    sets.detail = await api(`/api/sets/${encodeURIComponent(code)}`);
  } catch (e) {
    toast(e.message, "err");
    sets.detail = null;
    return loadSets();
  }
  renderSetDetail();
}

function setCardsFiltered() {
  const d = sets.detail;
  return d.cards.filter((c) => (sets.scope === "all" || c.main)
    && (sets.rarity === "_all" || c.rarity === sets.rarity)
    && (sets.show === "all" || (sets.show === "missing" ? !c.owned : c.owned)));
}

function renderSetDetail() {
  const d = sets.detail;
  const st = (d.stats[sets.scope] || {})[sets.rarity] || { total: 0, owned: 0, percent: 0, missing_value: 0 };
  const cards = setCardsFiltered();
  const missing = cards.filter((c) => !c.owned);
  const rarities = ["_all", ...["common", "uncommon", "rare", "mythic"].filter((r) => (d.stats[sets.scope] || {})[r])];
  $("#sets-main").innerHTML = `
    <div class="deck-head">
      <button class="btn small" data-sact="back">← Editionen</button>
      ${d.icon ? `<img class="set-icon big" src="${esc(d.icon)}" alt="">` : ""}
      <h2>${esc(d.name)}</h2><span class="muted">${esc(d.code)}${d.released ? " · " + esc(d.released) : ""}</span>
      <span class="spacer"></span>
      ${missing.length ? `<button class="btn small" data-sact="towish">Fehlende (${missing.length}) → Wunschliste</button>` : ""}
    </div>
    <div class="deck-stats">
      <div class="stat hero"><b>${st.percent} %</b>${st.owned} von ${st.total} Karten</div>
      <div class="stat ${st.total - st.owned ? "bad" : "good"}"><b>${st.total - st.owned}</b>fehlen</div>
      <div class="stat"><b>${esc(eur(st.missing_value))}</b>Wert der fehlenden</div>
    </div>
    <div class="progress big"><div style="width:${st.percent}%"></div></div>
    <div class="set-filters">
      <div class="seg">
        <button data-scope="main" class="${sets.scope === "main" ? "active" : ""}">Grundset (${d.main_size})</button>
        <button data-scope="all" class="${sets.scope === "all" ? "active" : ""}">inkl. Varianten (${d.cards.length})</button>
      </div>
      <div class="seg">${rarities.map((r) => `<button data-rar="${r}" class="${sets.rarity === r ? "active" : ""}">${RARITY_LABEL[r]}</button>`).join("")}</div>
      <div class="seg">
        <button data-show="all" class="${sets.show === "all" ? "active" : ""}">Alle</button>
        <button data-show="missing" class="${sets.show === "missing" ? "active" : ""}">Fehlende</button>
        <button data-show="owned" class="${sets.show === "owned" ? "active" : ""}">Vorhandene</button>
      </div>
    </div>
    <div class="grid set-cards">${cards.map((c) => `
      <div class="card ${c.owned ? "" : "missing"}" ${c.ids.length ? `data-id="${c.ids[0]}"` : ""} title="${esc(c.name)} #${esc(c.collector_number)}${c.owned ? "" : " – fehlt"}">
        ${c.image_url ? `<img loading="lazy" src="${esc(c.image_url)}" alt="${esc(c.name)}">` : `<div class="noimg">${esc(c.name)}</div>`}
        ${c.owned ? `<span class="badge">${c.owned}×</span>` : ""}
        <div class="meta"><div class="name">${esc(c.name)}</div>
          <div class="sub">#${esc(c.collector_number)} · ${esc(RARITY_LABEL[c.rarity] || c.rarity)}${c.price ? " · " + esc(eur(c.price)) : ""}</div></div>
      </div>`).join("")}</div>`;
}

function bindSets() {
  const box = $("#sets-main");
  box.addEventListener("click", async (e) => {
    const item = e.target.closest("[data-set]");
    if (item) return openSet(item.dataset.set);
    const a = e.target.closest("[data-sact]");
    if (a && a.dataset.sact === "back") { sets.detail = null; return loadSets(); }
    if (a && a.dataset.sact === "towish") {
      const ids = setCardsFiltered().filter((c) => !c.owned).map((c) => c.scryfall_id);
      if (ids.length > 50 && !confirm(`${ids.length} Karten auf die Wunschliste setzen?`)) return;
      try {
        const r = await api("/api/wishlist/bulk", { method: "POST", json: { scryfall_ids: ids, notes: `Set ${sets.detail.code}` } });
        toast(`${r.added.length} Karten auf die Wunschliste gesetzt`, "ok");
        if (typeof refreshWishBadge === "function") refreshWishBadge();
      } catch (err) { toast(err.message, "err"); }
      return;
    }
    const b = e.target.closest("[data-scope],[data-rar],[data-show]");
    if (b) {
      if (b.dataset.scope) sets.scope = b.dataset.scope;
      if (b.dataset.rar) sets.rarity = b.dataset.rar;
      if (b.dataset.show) sets.show = b.dataset.show;
      return renderSetDetail();
    }
    const card = e.target.closest(".set-cards [data-id]");
    if (card) openCard(card.dataset.id);
  });
  box.addEventListener("change", (e) => {
    if (e.target.id === "set-sort") { sets.sort = e.target.value; renderSetList(); }
  });
  box.addEventListener("submit", (e) => {
    if (e.target.id !== "set-open") return;
    e.preventDefault();
    const code = $("#set-code").value.trim();
    if (code) openSet(code);
  });
}

bindSets();

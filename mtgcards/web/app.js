"use strict";
/* MTG Cards – Web-Oberfläche (Desktop-Fenster & Server im Browser) */

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const PAGE_SIZE = 1000;   // Karten pro Ladevorgang; mehr über „Weitere laden“
const AUTO_TAGS = ["Commander", "Partner", "Companion", "Token", "Emblem", "Proxies"];   // immer in der Seitenleiste

const state = {
  token: "",
  q: "", ci: new Set(), ciMode: "within", tag: "", type: "", rarity: "", sort: "name", foilOnly: false,
  view: "grid", revision: -1, isDesktop: false, cards: [], dupMin: 0,
};

// ---------------------------------------------------------------- Hilfen
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }
function store(key, val) { try { if (val === undefined) return localStorage.getItem(key); localStorage.setItem(key, val); } catch (_) { return null; } }

function toast(msg, kind = "") {
  const el = document.createElement("div");
  el.className = "toast " + kind;
  el.textContent = msg;
  $("#toasts").appendChild(el);
  setTimeout(() => el.remove(), kind === "err" ? 6000 : 3500);
}

function manaHtml(cost) {
  if (!cost) return "";
  // erst escapen, dann Symbole einsetzen – Text außerhalb von {…} darf kein HTML einschleusen
  return `<span class="mana">` + esc(cost).replace(/\{([^}]+)\}/g, (_, s) => {
    const cls = /^[WUBRG]$/.test(s) ? `ms-${s}` : (s.includes("/") ? "ms-hybrid" : "");
    return `<span class="ms ${cls}" title="{${s}}">${s.replace("/", "")}</span>`;
  }).replace(/ \/\/ /g, " / ") + `</span>`;
}
function ciHtml(ci) {
  const letters = String(ci || "").split("").filter((c) => "WUBRGC".includes(c));
  const colors = letters.length ? letters : ["C"];
  return `<span class="mana">${colors.map((c) => `<span class="ms ms-${c}">${c}</span>`).join("")}</span>`;
}
function tagHtml(t, extra = "") {
  return `<span class="tag t-${esc(t.replace(/\W/g, ""))}" ${extra}>${esc(t)}</span>`;
}
function oracleHtml(text) {
  return esc(text).replace(/\{([^}]+)\}/g, (m, s) => {
    const cls = /^[WUBRG]$/.test(s) ? `ms-${s}` : (s.includes("/") ? "ms-hybrid" : "");
    return `<span class="ms ${cls}">${s.replace("/", "")}</span>`;
  });
}

// ---------------------------------------------------------------- API
async function api(path, opts = {}) {
  const headers = Object.assign({}, opts.headers || {});
  if (state.token) headers["Authorization"] = "Bearer " + state.token;
  if (opts.json !== undefined) {
    headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(opts.json);
  }
  let res;
  try {
    res = await fetch(path, { method: opts.method || "GET", headers, body: opts.body });
  } catch (e) {
    setConn(false);
    throw new Error("Keine Verbindung zum Server");
  }
  setConn(true);
  const ctype = res.headers.get("Content-Type") || "";
  const data = ctype.includes("json") ? await res.json() : await res.text();
  if (res.status === 401) {
    showLogin();
    throw new Error(data.error || "Nicht autorisiert");
  }
  if (!res.ok) throw new Error((data && data.error) || `HTTP ${res.status}`);
  return data;
}

function setConn(ok) {
  const el = $("#conn");
  el.className = "conn " + (ok ? "ok" : "err");
  el.title = ok ? "Verbunden" : "Keine Verbindung";
}

function showLogin() {
  const dlg = $("#dlg-login");
  if (!dlg.open) dlg.showModal();
}

// ---------------------------------------------------------------- Liste
function queryString() {
  const p = new URLSearchParams();
  if (state.q) p.set("q", state.q);
  if (state.ci.size) { p.set("ci", [...state.ci].join("")); p.set("ci_mode", state.ciMode); }
  if (state.tag) p.set("tag", state.tag);
  if (state.type) p.set("type", state.type);
  if (state.rarity) p.set("rarity", state.rarity);
  if (state.foilOnly) p.set("foil", "1");
  if (state.dupMin > 1) p.set("dup_min", String(state.dupMin));
  p.set("sort", state.sort);
  p.set("limit", String(PAGE_SIZE));
  return p.toString();
}

async function loadCards() {
  try {
    // nach einer Live-Aktualisierung so viele Karten laden wie vorher sichtbar (nachgeladene bleiben da)
    const want = Math.max(PAGE_SIZE, Math.min(state.cards.length, 5000));
    const key = queryString();
    const data = await api("/api/cards?" + key.replace(/limit=\d+/, "limit=" + (state.listKey === key ? want : PAGE_SIZE)));
    state.listKey = key;
    state.cards = data.cards;
    state.total = data.total;
    state.duplicates = data.duplicates;
    state.revision = data.revision;
    renderCards(data);
  } catch (e) {
    if (!/autorisiert/.test(e.message)) toast(e.message, "err");
  }
  loadSidebar();
}

function renderCards(data) {
  const box = $("#results");
  const total = data.cards.reduce((s, c) => s + c.quantity, 0);
  const rest = Math.max(0, data.total - data.cards.length);
  $("#result-count").textContent = rest
    ? `${data.total} Einträge · ${data.cards.length} geladen (${total} Karten)`
    : `${data.total} Einträge · ${total} Karten`;
  $("#more").classList.toggle("hidden", !rest);
  $("#btn-more").textContent = `Weitere ${Math.min(rest, PAGE_SIZE)} laden (noch ${rest})`;
  if (data.duplicates) {
    const d = data.duplicates;
    $("#result-count").textContent += ` · ${d.cards} Karten ab ${d.min}× · ${d.extra_copies} überzählige Exemplare`
      + ` (Wert ca. ${d.extra_value_eur.toLocaleString("de-DE", { style: "currency", currency: "EUR" })}, wertvollstes Exemplar jeweils behalten)`;
  }
  const filtered = state.q || state.ci.size || state.tag || state.type || state.rarity || state.foilOnly || state.dupMin;
  $("#empty").classList.toggle("hidden", data.total > 0 || filtered);
  if (state.view === "grid") {
    box.className = "grid";
    box.innerHTML = data.cards.map((c) => `
      <div class="card" data-id="${c.id}">
        ${c.image_url ? `<img loading="lazy" src="${esc(c.image_url)}" alt="${esc(c.name)}">` : `<div class="noimg">${esc(c.name)}</div>`}
        <span class="badge">${c.quantity}×</span>
        ${c.foil ? `<span class="badge foil">Foil</span>` : ""}
        ${c.proxy ? `<span class="badge proxy">PROXY</span>` : ""}
        <div class="meta">
          <div class="name" title="${esc(c.name)}">${esc(c.name)}</div>
          <div class="sub">${esc(c.set_code)} #${esc(c.collector_number)} · ${esc(c.type_line)}</div>
          ${c.tags.length ? `<div class="tags">${c.tags.map((t) => tagHtml(t)).join("")}</div>` : ""}
        </div>
      </div>`).join("");
  } else {
    box.className = "";
    box.innerHTML = `<table class="list"><thead><tr>
        <th>#</th><th>Name</th><th>Kosten</th><th>Typ</th><th>Farbid.</th><th>Edition</th><th>Tags</th><th>€</th>
      </tr></thead><tbody>${data.cards.map((c) => `
      <tr data-id="${c.id}">
        <td><b>${c.quantity}</b>${c.foil ? " ✦" : ""}${c.proxy ? ` <span class="pill proxy">Proxy</span>` : ""}</td>
        <td>${esc(c.name)}${c.printed_name && c.printed_name !== c.name ? `<div class="muted small">${esc(c.printed_name)}</div>` : ""}</td>
        <td>${manaHtml(c.mana_cost)}</td>
        <td>${esc(c.type_line)}</td>
        <td>${ciHtml(c.color_identity)}</td>
        <td>${esc(c.set_code)} #${esc(c.collector_number)}</td>
        <td><div class="tags">${c.tags.map((t) => tagHtml(t)).join("")}</div></td>
        <td>${esc(priceText(c))}</td>
      </tr>`).join("")}</tbody></table>`;
  }
}

/** Preis einer Karte als Text: Euro, sonst Dollar (Scryfall hat nicht für jeden Druck einen Euro-Preis). */
function priceText(c, withEuro) {
  const eur = c.foil ? (c.price_eur_foil || c.price_eur) : (c.price_eur || c.price_eur_foil);
  if (eur) return withEuro ? `${eur} €` : String(eur);
  const usd = c.foil ? (c.price_usd_foil || c.price_usd) : (c.price_usd || c.price_usd_foil);
  return usd ? `$${usd}` : "";
}

const LANG_NAMES = { en: "Englisch", de: "Deutsch", fr: "Französisch", it: "Italienisch", es: "Spanisch",
  pt: "Portugiesisch", ja: "Japanisch", ko: "Koreanisch", ru: "Russisch", zhs: "Chinesisch (vereinf.)",
  zht: "Chinesisch (trad.)" };

/** Nächste Seite der Liste nachladen (große Sammlungen). */
async function loadMore() {
  const btn = $("#btn-more");
  btn.disabled = true;
  try {
    const data = await api("/api/cards?" + queryString() + "&offset=" + state.cards.length);
    state.cards = state.cards.concat(data.cards);
    state.total = data.total;
    renderCards({ cards: state.cards, total: data.total, duplicates: state.duplicates });
  } catch (e) { toast(e.message, "err"); }
  finally { btn.disabled = false; }
}

async function loadSidebar() {
  try {
    const [tags, stats] = await Promise.all([api("/api/tags"), api("/api/stats")]);
    const names = Object.keys(tags.tags);
    for (const t of AUTO_TAGS) if (!names.includes(t)) names.push(t);
    $("#taglist").innerHTML = names.map((t) =>
      `<span class="tag t-${esc(t.replace(/\W/g, ""))} ${state.tag === t ? "active" : ""}" data-tag="${esc(t)}">${esc(t)} <span class="n">${tags.tags[t] || 0}</span></span>`
    ).join("");
    $("#stats").innerHTML = `
      <div><b>${stats.cards}</b> Karten · <b>${stats.unique_names}</b> verschiedene</div>
      <div><b>${stats.entries}</b> Einträge</div>
      <div>Wert ca. <b>${stats.value_eur.toLocaleString("de-DE", { style: "currency", currency: "EUR" })}</b></div>`;
  } catch (_) { /* ignorieren */ }
}

// ---------------------------------------------------------------- Kartendetails
async function openCard(id) {
  let c;
  try { c = await api(`/api/cards/${id}`); } catch (e) { return toast(e.message, "err"); }
  renderDetail(c);
  const dlg = $("#dlg-card");
  if (!dlg.open) dlg.showModal();
}

function renderDetail(c) {
  $("#cd-title").innerHTML = `${esc(c.name)} ${manaHtml(c.mana_cost)}`;
  const pt = c.power != null ? `${c.power}/${c.toughness}` : (c.loyalty ? `Loyalität ${c.loyalty}` : "");
  const price = priceText(c, true);
  const rel = c.related || [];
  const relLabel = rel.length && rel[0].kind === "emblem" ? "Emblem vorhanden" : "Gehört zu";
  $("#cd-body").innerHTML = `
    <div>${c.image_url ? `<img src="${esc(c.image_url)}" alt="">` : ""}</div>
    <div>
      ${c.printed_name && c.printed_name !== c.name ? `<div class="muted">${esc(c.printed_name)} (${esc(c.lang)})</div>` : ""}
      <div class="typeline">${esc(c.type_line)} ${pt ? `<span class="muted">· ${esc(pt)}</span>` : ""}</div>
      <div class="oracle">${oracleHtml(c.oracle_text) || "<span class='muted'>Kein Regeltext</span>"}</div>
      <dl class="kv">
        <dt>Anzahl</dt><dd><span class="qty">
          <button class="btn small" data-act="dec">−</button><b>${c.quantity}</b>
          <button class="btn small" data-act="inc">＋</button></span></dd>
        <dt>Foil</dt><dd><label class="check" style="margin:0"><input type="checkbox" data-act="foil" ${c.foil ? "checked" : ""}> Foil</label></dd>
        <dt>Farbidentität</dt><dd>${ciHtml(c.color_identity)}</dd>
        <dt>Schlüsselwörter</dt><dd>${esc(c.keywords.join(", ")) || "–"}</dd>
        <dt>Edition</dt><dd>${esc(c.set_name)} (${esc(c.set_code)}) #${esc(c.collector_number)} · ${esc(c.rarity)}
          · ${esc(LANG_NAMES[c.lang] || c.lang)} <button class="btn small" data-act="print" title="Andere Edition oder Sprache wählen">Druck ändern</button>
          <div id="cd-prints" class="hidden" style="margin-top:6px">
            <select id="cd-print-lang" style="width:auto"><option value="">Englisch</option>
              ${Object.entries(LANG_NAMES).filter(([k]) => k !== "en").map(([k, v]) => `<option value="${k}" ${k === c.lang ? "selected" : ""}>${esc(v)}</option>`).join("")}</select>
            <select id="cd-print-sel" style="max-width:340px"><option value="">Lade …</option></select>
            <button class="btn small primary" data-act="printok">Übernehmen</button>
          </div></dd>
        <dt>Preis</dt><dd>${price ? esc(price) : "–"}</dd>
        ${rel.length ? `<dt>${relLabel}</dt><dd>${rel.map((r) => `<a href="#" data-open="${r.id}">${esc(r.name)}</a> <span class="muted small">(${esc(r.set_code)}${r.quantity > 1 ? `, ${r.quantity}×` : ""})</span>`).join(", ")}</dd>` : ""}
        <dt>Tags</dt><dd><div class="tag-edit">
          ${c.tags.map((t) => `<span class="tag t-${esc(t.replace(/\W/g, ""))}">${esc(t)} <span class="rm" data-rm="${esc(t)}">×</span></span>`).join("")}
          <input placeholder="Tag hinzufügen ↵" data-act="addtag"></div></dd>
        <dt>Notizen</dt><dd><textarea rows="2" data-act="notes">${esc(c.notes)}</textarea></dd>
        <dt>In Decks</dt><dd>${(c.decks || []).length ? c.decks.map((u) => `${esc(u.deck)} (${u.quantity})`).join(", ")
          + ((c.decks || []).reduce((s, u) => s + u.quantity, 0) > c.quantity ? ` <span style="color:var(--accent2)">⇄ mehr verplant als vorhanden</span>` : "") : "–"}</dd>
        <dt>Hinzugefügt</dt><dd>${esc(new Date(c.added_at).toLocaleString("de-DE"))}</dd>
      </dl>
      <div class="row">
        ${c.scryfall_uri ? `<a class="btn" href="${esc(c.scryfall_uri)}" target="_blank" rel="noopener">Auf Scryfall öffnen ↗</a>` : ""}
        <button class="btn" data-act="refresh" title="Daten & Preise neu von Scryfall laden">⟳ Aktualisieren</button>
      </div>
      <div class="row" style="margin-top:10px">
        <select id="cd-decksel" style="max-width:240px"><option value="">Decks laden …</option></select>
        <button class="btn" data-act="todeck">＋ Zu Deck</button>
        <span class="spacer"></span>
        <button class="btn danger" data-act="delete">Löschen</button>
      </div>
    </div>`;
  const body = $("#cd-body");
  if (typeof fillDeckSelect === "function") fillDeckSelect($("#cd-decksel"));
  const patch = async (changes) => {
    try {
      const res = await api(`/api/cards/${c.id}`, { method: "PATCH", json: changes });
      if (res.deleted) { $("#dlg-card").close(); toast(`${c.name} entfernt`); }
      else renderDetail(res);
      loadCards();
    } catch (e) { toast(e.message, "err"); }
  };
  const loadPrintChoices = async () => {
    const sel = $("#cd-print-sel");
    sel.innerHTML = `<option value="">Lade …</option>`;
    const lang = $("#cd-print-lang").value;
    try {
      const { data } = await api(`/api/prints?name=${encodeURIComponent(c.name)}${lang ? "&lang=" + lang : ""}`);
      sel.innerHTML = data.length ? data.slice().reverse().map((p) => `<option value="${esc(p.scryfall_id)}" ${p.scryfall_id === c.scryfall_id ? "selected" : ""}>
        ${esc(p.set_name)} (${esc(p.set_code)}) #${esc(p.collector_number)}${p.released_at ? " · " + esc(p.released_at.slice(0, 4)) : ""}${p.artist ? " · " + esc(p.artist) : ""}${p.price_eur ? " · " + esc(p.price_eur) + " €" : ""}</option>`).join("")
        : `<option value="">Keine Drucke in dieser Sprache</option>`;
    } catch (e) { sel.innerHTML = `<option value="">${esc(e.message)}</option>`; }
  };
  $("#cd-print-lang").onchange = loadPrintChoices;
  body.onclick = async (ev) => {
    const act = ev.target.dataset.act;
    const rm = ev.target.dataset.rm;
    if (ev.target.dataset.open) { ev.preventDefault(); return openCard(ev.target.dataset.open); }
    if (act === "print") {
      $("#cd-prints").classList.toggle("hidden");
      if (!$("#cd-prints").classList.contains("hidden")) loadPrintChoices();
      return;
    }
    if (act === "printok") {
      const id = $("#cd-print-sel").value;
      if (!id || id === c.scryfall_id) return;
      return patch({ scryfall_id: id });
    }
    if (rm) return patch({ tags: c.tags.filter((t) => t !== rm) });
    if (act === "inc") return patch({ quantity: c.quantity + 1 });
    if (act === "dec") {
      if (c.quantity <= 1 && !confirm(`${c.name} aus der Sammlung entfernen?`)) return;
      return patch({ quantity: c.quantity - 1 });
    }
    if (act === "delete") {
      if (!confirm(`${c.name} (${c.quantity}×) wirklich löschen?`)) return;
      try { await api(`/api/cards/${c.id}`, { method: "DELETE" }); $("#dlg-card").close(); toast("Gelöscht"); loadCards(); }
      catch (e) { toast(e.message, "err"); }
    }
    if (act === "todeck") {
      const did = $("#cd-decksel").value;
      if (!did) return toast("Zuerst unter „Decks“ ein Deck anlegen", "err");
      try {
        const d = await api(`/api/decks/${did}/cards`, { method: "POST", json: { collection_id: c.id } });
        toast(`${c.name} → ${d.name}`, "ok");
      } catch (e) { toast(e.message, "err"); }
      return;
    }
    if (act === "refresh") {
      try { renderDetail(await api(`/api/cards/${c.id}/refresh`, { method: "POST" })); toast("Aktualisiert", "ok"); loadCards(); }
      catch (e) { toast(e.message, "err"); }
    }
  };
  body.onchange = (ev) => {
    const act = ev.target.dataset.act;
    if (act === "foil") patch({ foil: ev.target.checked });
    if (act === "notes") patch({ notes: ev.target.value });
  };
  body.onkeydown = (ev) => {
    if (ev.target.dataset.act === "addtag" && ev.key === "Enter") {
      const v = ev.target.value.trim();
      if (v) patch({ tags: [...c.tags, v] });
    }
  };
}

// ---------------------------------------------------------------- Hinzufügen
const add = { suggestions: [], sel: -1, lookupSeq: 0, printSeq: 0, preview: null };

/** Vorschau und Druck-Auswahl verwerfen – sie gehören zum alten Namen. Laufende Abfragen werden ignoriert. */
function resetAddPreview() {
  add.preview = null;
  add.lookupSeq++;
  add.printSeq++;
  $("#add-print").innerHTML = `<option value="">automatisch (neuester Druck)</option>`;
  $("#add-preview").innerHTML = `<div class="placeholder">Vorschau</div>`;
}

function openAdd() {
  const dlg = $("#dlg-add");
  $("#add-name").value = "";
  $("#add-qty").value = 1;
  $("#add-foil").checked = false;
  resetAddPreview();
  dlg.showModal();
  $("#add-name").focus();
}

const autocomplete = debounce(async () => {
  const q = $("#add-name").value.trim();
  const list = $("#ac-list");
  if (q.length < 2) { list.classList.add("hidden"); return; }
  try {
    const { data } = await api("/api/autocomplete?q=" + encodeURIComponent(q));
    add.suggestions = data.slice(0, 15);
    add.sel = -1;
    list.innerHTML = add.suggestions.map((n, i) => `<li data-i="${i}">${esc(n)}</li>`).join("");
    list.classList.toggle("hidden", !add.suggestions.length);
  } catch (e) { list.classList.add("hidden"); }
}, 200);

async function chooseName(name) {
  $("#add-name").value = name;
  $("#ac-list").classList.add("hidden");
  await loadPrints(name);
  await previewLookup();
}

async function loadPrints(name) {
  const sel = $("#add-print");
  const seq = ++add.printSeq;
  sel.innerHTML = `<option value="">automatisch (neuester Druck)</option>`;
  try {
    const { data } = await api("/api/prints?name=" + encodeURIComponent(name));
    if (seq !== add.printSeq) return;     // Name wurde inzwischen geändert
    sel.innerHTML += data.map((p) =>
      `<option value="${esc(p.scryfall_id)}">${esc(p.set_name)} (${esc(p.set_code)}) #${esc(p.collector_number)} · ${esc(p.rarity)}${p.price_eur ? " · " + esc(p.price_eur) + " €" : ""}</option>`).join("");
  } catch (_) { /* egal */ }
}

async function previewLookup() {
  const name = $("#add-name").value.trim();
  const id = $("#add-print").value;
  if (!name && !id) return;
  const seq = ++add.lookupSeq;
  const pv = $("#add-preview");
  pv.innerHTML = `<div class="placeholder">Suche …</div>`;
  try {
    const lang = $("#add-lang").value;
    const qs = id ? "id=" + encodeURIComponent(id) : "name=" + encodeURIComponent(name) + (lang ? "&lang=" + lang : "");
    const c = await api("/api/lookup?" + qs);
    if (seq !== add.lookupSeq) return;
    add.preview = c;
    pv.innerHTML = `
      ${c.image_url ? `<img src="${esc(c.image_url)}" alt="">` : `<div class="placeholder">${esc(c.name)}</div>`}
      <div style="margin-top:6px"><b>${esc(c.name)}</b> ${manaHtml(c.mana_cost)}</div>
      <div class="muted small">${esc(c.type_line)} · ${esc(c.set_code)} #${esc(c.collector_number)}</div>
      <div class="small">Farbidentität ${ciHtml(c.color_identity)}</div>
      <div class="ptags">${c.auto_tags.map((t) => tagHtml(t)).join("")}</div>
      <div class="muted small">Im Bestand: ${c.owned.this_print} (dieser Druck), ${c.owned.all_prints} gesamt</div>`;
  } catch (e) {
    if (seq !== add.lookupSeq) return;
    add.preview = null;
    pv.innerHTML = `<div class="placeholder">${esc(e.message)}</div>`;
  }
}

async function submitAdd(ev) {
  ev.preventDefault();
  const name = $("#add-name").value.trim();
  // Die Vorschau gilt nur für den Namen, der gerade im Feld steht (wird beim Tippen verworfen) –
  // sonst würde die zuvor hinzugefügte Karte noch einmal gespeichert.
  const id = $("#add-print").value || (add.preview && add.preview.scryfall_id) || "";
  if (!name && !id) return;
  const btn = $("#add-submit");
  btn.disabled = true;
  try {
    const tags = $("#add-tags").value.split(",").map((s) => s.trim()).filter(Boolean);
    if ($("#add-proxy").checked && !tags.includes("Proxies")) tags.push("Proxies");
    const c = await api("/api/cards", {
      method: "POST",
      json: { name, scryfall_id: id || undefined,
        lang: $("#add-lang").value || undefined, quantity: +$("#add-qty").value || 1, foil: $("#add-foil").checked, tags },
    });
    toast(`${c.name}${c.proxy ? " (Proxy)" : ""} hinzugefügt (jetzt ${c.quantity}×)`, "ok");
    for (const w of c.wish_fulfilled || []) toast(`★ Wunsch erfüllt: ${w.name}${w.remaining ? ` (noch ${w.remaining} gewünscht)` : ""}`, "ok");
    loadCards();
    if ($("#add-keep").checked) {
      $("#add-name").value = "";
      resetAddPreview();
      $("#add-qty").value = 1;
      $("#add-name").focus();
    } else {
      $("#dlg-add").close();
    }
  } catch (e) {
    toast(e.message, "err");
  } finally {
    btn.disabled = false;
  }
}

// ---------------------------------------------------------------- Import/Export
function openIO() {
  const t = encodeURIComponent(state.token || "");
  $("#exp-json").href = `/api/export?format=json&token=${t}`;
  $("#exp-csv").href = `/api/export?format=csv&token=${t}`;
  $("#imp-result").classList.add("hidden");
  $("#dlg-io").showModal();
}

async function doImport() {
  const file = $("#imp-file").files[0];
  if (!file) return toast("Bitte eine Datei auswählen", "err");
  const mode = $("input[name=imp-mode]:checked").value;
  if (mode === "replace" && !confirm("Die gesamte Sammlung wird durch den Import ersetzt. Fortfahren?")) return;
  const btn = $("#imp-go");
  btn.disabled = true;
  btn.textContent = "Importiere … (kann bei vielen Karten dauern)";
  try {
    const text = await file.text();
    const r = await api(`/api/import?mode=${mode}`, { method: "POST", body: text, headers: { "Content-Type": "text/plain" } });
    const out = $("#imp-result");
    out.textContent = `${r.imported} Karten importiert (${r.created} neue Einträge, ${r.merged} zusammengeführt, ${r.looked_up} über Scryfall ergänzt)`
      + (r.errors.length ? `\n\n${r.errors.length} Fehler:\n` + r.errors.join("\n") : "");
    out.classList.remove("hidden");
    toast("Import abgeschlossen", "ok");
    loadCards();
  } catch (e) {
    toast(e.message, "err");
  } finally {
    btn.disabled = false;
    btn.textContent = "Importieren";
  }
}

// ---------------------------------------------------------------- Einstellungen
async function openSettings() {
  const body = $("#settings-body");
  body.innerHTML = "Lade …";
  $("#dlg-settings").showModal();
  let desk = null;
  if (state.isDesktop) {
    try { desk = await api("/api/desktop/settings"); } catch (_) { desk = null; }
  }
  let info = null;
  try { info = await api("/api/info"); } catch (_) { /* evtl. remote nicht erreichbar */ }
  renderSettings(desk, info);
}

function addrList(addresses, port, scheme = "http") {
  return addresses.map((a) => `<div><span class="addr">${scheme}://${esc(a.address)}:${port}</span>
    <span class="muted small">${a.tailscale ? "Tailscale" : esc(a.iface)}</span></div>`).join("");
}

function renderSettings(desk, info) {
  const body = $("#settings-body");
  let html = "";
  if (desk) {
    const scheme = desk.tls_active ? "https" : "http";
    const tsName = desk.tailscale_name ? `<div><span class="addr">${scheme}://${esc(desk.tailscale_name)}:${desk.port}</span> <span class="muted small">Tailscale MagicDNS</span></div>` : "";
    html += `<div class="settings-grid">
      <div class="box">
        <h3>Datenbank</h3>
        <div class="seg" id="mode-seg">
          <button data-mode="local" class="${desk.mode === "local" ? "active" : ""}">Lokal auf diesem PC</button>
          <button data-mode="remote" class="${desk.mode === "remote" ? "active" : ""}">Headless-Server</button>
        </div>
        <div id="mode-local" class="${desk.mode === "local" ? "" : "hidden"}">
          <p class="muted small">Datenbank: <code>${esc(desk.db_path)}</code></p>
        </div>
        <div id="mode-remote" class="${desk.mode === "remote" ? "" : "hidden"}">
          <label>Server-Adresse<input id="rm-url" value="${esc(desk.remote_url)}" placeholder="http://mein-server:8765 oder http://100.x.y.z:8765"></label>
          <label>Server-Token<input id="rm-token" placeholder="${desk.remote_token_set ? "(gespeichert – zum Ändern neu eingeben)" : "XXXX-XXXX-XXXX-XXXX"}"></label>
          <p class="muted small">Token auf dem Server anzeigen: <code>mtg-cards-server --show-token</code></p>
        </div>
        <div class="row" style="margin-top:10px">
          <button class="btn primary" id="mode-save">Übernehmen</button>
          <span id="mode-msg" class="small"></span>
        </div>
      </div>
      <div class="box">
        <h3>Handy-App verbinden</h3>
        <p class="muted small">In der App unter <b>Einstellungen</b> „Im WLAN suchen“ tippen oder eine dieser Adressen eintragen:</p>
        ${addrList(desk.addresses, desk.port, scheme)}${tsName}
        <h3>Token für die App</h3>
        <div class="token">${esc(desk.local_token)}</div>
        <div class="row" style="margin-top:8px">
          <button class="btn small" id="tok-regen">Neuen Token erzeugen</button>
        </div>
        <h3>Verschlüsselung</h3>
        <label class="check"><input type="checkbox" id="tls-toggle" ${desk.tls ? "checked" : ""}> HTTPS für Handy-Verbindung</label>
        ${desk.tls_fingerprint ? `<div class="muted small">Zertifikats-Fingerabdruck (in der App vergleichen):</div><div class="fp">${esc(desk.tls_fingerprint)}</div>` : ""}
        ${desk.restart_required ? `<p class="small" style="color:var(--accent2)">⚠ Wird nach einem Neustart der Anwendung aktiv.</p>` : ""}
        ${desk.mode === "remote" ? `<p class="muted small">Im Server-Modus kann die App auch direkt mit dem Headless-Server verbunden werden (empfohlen).</p>` : ""}
      </div>
    </div>`;
  }
  if (info && (!desk || desk.mode === "remote")) {
    html += `<div class="box" style="margin-top:16px">
      <h3>${info.kind === "server" ? "Verbundener Server" : "Server"}: ${esc(info.name)} (v${esc(info.version)})</h3>
      ${addrList(info.addresses || [], info.port, info.tls ? "https" : "http")}
      ${info.tls_fingerprint ? `<div class="muted small">Fingerabdruck:</div><div class="fp">${esc(info.tls_fingerprint)}</div>` : ""}
      ${info.tailscale_name ? `<div><span class="addr">http://${esc(info.tailscale_name)}:${info.port}</span> <span class="muted small">Tailscale MagicDNS</span></div>` : ""}
      <p class="muted small">${info.stats.cards} Karten in der Datenbank.</p>
    </div>`;
  }
  html += `<div class="box" style="margin-top:16px">
      <h3>Zugangs-Token dieser Oberfläche</h3>
      <div class="row"><input id="ui-token" value="${esc(state.token)}" style="max-width:300px">
      <button class="btn" id="ui-token-save">Speichern</button></div>
    </div>`;
  body.innerHTML = html;

  if (desk) {
    let mode = desk.mode;
    $$("#mode-seg button").forEach((b) => b.onclick = () => {
      mode = b.dataset.mode;
      $$("#mode-seg button").forEach((x) => x.classList.toggle("active", x === b));
      $("#mode-local").classList.toggle("hidden", mode !== "local");
      $("#mode-remote").classList.toggle("hidden", mode !== "remote");
    });
    $("#mode-save").onclick = async () => {
      const msg = $("#mode-msg");
      msg.textContent = "Prüfe …";
      const payload = { mode };
      if (mode === "remote") {
        payload.remote_url = $("#rm-url").value.trim();
        if ($("#rm-token").value.trim()) payload.remote_token = $("#rm-token").value.trim();
      }
      try {
        let r = await api("/api/desktop/settings", { method: "POST", json: payload });
        if (!r.ok && r.needs_trust) {
          const yes = confirm("Der Server nutzt ein selbstsigniertes Zertifikat.\n\nFingerabdruck:\n" + r.fingerprint +
            "\n\nStimmt er mit der Ausgabe von „sudo mtg-cards-server --show-fingerprint“ überein?");
          if (!yes) { msg.textContent = "✗ Abgebrochen"; return; }
          payload.remote_fingerprint = r.fingerprint;
          r = await api("/api/desktop/settings", { method: "POST", json: payload });
        }
        if (!r.ok) { msg.textContent = "✗ " + r.error; return; }
        msg.textContent = "✓ Gespeichert";
        toast(mode === "remote" ? "Mit Server verbunden" : "Lokale Datenbank aktiv", "ok");
        state.revision = -1;
        loadCards();
        openSettings();
      } catch (e) { msg.textContent = "✗ " + e.message; }
    };
    $("#tls-toggle").onchange = async (e) => {
      const r = await api("/api/desktop/settings", { method: "POST", json: { tls: e.target.checked } });
      if (!r.ok) { toast(r.error, "err"); e.target.checked = !e.target.checked; return; }
      toast(e.target.checked ? "HTTPS aktiviert – Anwendung neu starten" : "HTTPS deaktiviert – Anwendung neu starten", "ok");
      renderSettings(r, info);
    };
    $("#tok-regen").onclick = async () => {
      if (!confirm("Neuen Token erzeugen? Die Handy-App muss danach neu verbunden werden.")) return;
      const r = await api("/api/desktop/settings", { method: "POST", json: { regenerate_token: true } });
      state.token = r.local_token;
      store("mtg-token", state.token);
      renderSettings(r, info);
    };
  }
  $("#ui-token-save").onclick = () => {
    state.token = $("#ui-token").value.trim();
    store("mtg-token", state.token);
    toast("Token gespeichert", "ok");
    loadCards();
  };
}

// ---------------------------------------------------------------- Live-Update
async function poll() {
  try {
    const { revision } = await api("/api/revision");
    if (state.revision >= 0 && revision !== state.revision) {
      const latest = await api("/api/cards?sort=updated&limit=1");
      const c = latest.cards[0];
      const stamp = c ? `${c.id}|${c.updated_at}` : "";
      if (c && state.lastStamp && stamp !== state.lastStamp) toast(`Aktualisiert: ${c.name} (${c.quantity}×)`);
      state.lastStamp = stamp;
      await loadCards();
      if (typeof onRevisionChange === "function") onRevisionChange();
    }
    state.revision = revision;
  } catch (_) { /* nächster Versuch */ }
}

// ---------------------------------------------------------------- Init
function bind() {
  $("#q").addEventListener("input", debounce((e) => { state.q = e.target.value.trim(); loadCards(); }, 250));
  $$("#ci-pips .pip").forEach((b) => b.onclick = () => {
    const c = b.dataset.c;
    state.ci.has(c) ? state.ci.delete(c) : state.ci.add(c);
    b.classList.toggle("active", state.ci.has(c));
    loadCards();
  });
  $("#ci-mode").onchange = (e) => { state.ciMode = e.target.value; loadCards(); };
  $("#f-type").onchange = (e) => { state.type = e.target.value; loadCards(); };
  $("#f-rarity").onchange = (e) => { state.rarity = e.target.value; loadCards(); };
  $("#f-sort").onchange = (e) => { state.sort = e.target.value; loadCards(); };
  $("#f-foil").onchange = (e) => { state.foilOnly = e.target.checked; loadCards(); };
  $("#f-dup").onchange = (e) => {
    state.dupMin = +e.target.value;
    if (state.dupMin && state.sort === "name") { /* Doppelte nach Name gruppiert lassen */ }
    loadCards();
  };
  $("#taglist").onclick = (e) => {
    const t = e.target.closest("[data-tag]");
    if (!t) return;
    state.tag = state.tag === t.dataset.tag ? "" : t.dataset.tag;
    loadCards();
  };
  $("#btn-reset").onclick = () => {
    Object.assign(state, { q: "", tag: "", type: "", rarity: "", foilOnly: false, dupMin: 0 });
    $("#f-dup").value = "0";
    state.ci.clear();
    $("#q").value = ""; $("#f-type").value = ""; $("#f-rarity").value = ""; $("#f-foil").checked = false;
    $$("#ci-pips .pip").forEach((b) => b.classList.remove("active"));
    loadCards();
  };
  $$(".viewtoggle button").forEach((b) => b.onclick = () => {
    state.view = b.dataset.view;
    store("mtg-view", state.view);
    $$(".viewtoggle button").forEach((x) => x.classList.toggle("active", x === b));
    renderCards({ cards: state.cards, total: state.total ?? state.cards.length, duplicates: state.duplicates });
  });
  $("#results").onclick = (e) => {
    const el = e.target.closest("[data-id]");
    if (el) openCard(el.dataset.id);
  };

  $("#btn-more").onclick = loadMore;
  $("#btn-add").onclick = openAdd;
  $("#btn-io").onclick = openIO;
  $("#btn-settings").onclick = openSettings;
  $("#imp-go").onclick = doImport;
  $("#refresh-all").onclick = async (e) => {
    const btn = e.target;
    btn.disabled = true;
    btn.textContent = "Aktualisiere …";
    try {
      const r = await api("/api/refresh-all", { method: "POST" });
      toast(`${r.updated} von ${r.total} Einträgen aktualisiert`, "ok");
      loadCards();
    } catch (err) { toast(err.message, "err"); }
    finally { btn.disabled = false; btn.textContent = "⟳ Alle Karten aktualisieren"; }
  };
  $$("[data-close]").forEach((b) => b.onclick = () => b.closest("dialog").close());
  $$("dialog").forEach((d) => d.addEventListener("click", (e) => { if (e.target === d && d.id !== "dlg-login") d.close(); }));

  const name = $("#add-name");
  name.addEventListener("input", () => { resetAddPreview(); autocomplete(); });
  name.addEventListener("keydown", (e) => {
    const list = $("#ac-list");
    const items = $$("li", list);
    if (list.classList.contains("hidden") || !items.length) return;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      add.sel = (add.sel + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
      items.forEach((li, i) => li.classList.toggle("sel", i === add.sel));
    } else if (e.key === "Enter" && add.sel >= 0) {
      e.preventDefault();
      chooseName(add.suggestions[add.sel]);
    } else if (e.key === "Escape") {
      list.classList.add("hidden");
    }
  });
  name.addEventListener("blur", () => setTimeout(() => {
    $("#ac-list").classList.add("hidden");
    if (name.value.trim() && (!add.preview || add.preview.name.toLowerCase() !== name.value.trim().toLowerCase())) {
      loadPrints(name.value.trim()).then(previewLookup);
    }
  }, 150));
  $("#ac-list").addEventListener("mousedown", (e) => {
    const li = e.target.closest("li");
    if (li) { e.preventDefault(); chooseName(add.suggestions[+li.dataset.i]); }
  });
  $("#add-print").onchange = previewLookup;
  $("#add-lang").onchange = () => { $("#add-print").value = ""; previewLookup(); };
  $("#add-form").addEventListener("submit", submitAdd);

  $("#login-form").addEventListener("submit", () => {
    state.token = $("#login-token").value.replace(/\s+/g, "").toUpperCase();
    store("mtg-token", state.token);
    loadCards();
  });

  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "n") { e.preventDefault(); openAdd(); }
    if ((e.ctrlKey || e.metaKey) && e.key === "f") { e.preventDefault(); $("#q").focus(); }
  });
}

async function init() {
  // Token aus URL-Fragment (vom Desktop-Launcher) übernehmen
  const m = location.hash.match(/token=([^&]+)/);
  if (m) {
    store("mtg-token", decodeURIComponent(m[1]));
    history.replaceState(null, "", location.pathname);
  }
  state.token = store("mtg-token") || "";
  state.view = store("mtg-view") || "grid";
  $$(".viewtoggle button").forEach((x) => x.classList.toggle("active", x.dataset.view === state.view));
  bind();
  try {
    const health = await (await fetch("/api/health")).json();
    state.isDesktop = health.kind === "desktop";
    document.title = state.isDesktop ? "MTG Cards" : `MTG Cards – ${health.name}`;
    if (health.auth_required && !state.token) showLogin();
  } catch (_) { setConn(false); }
  await loadCards();
  setInterval(poll, 3000);
}

init();

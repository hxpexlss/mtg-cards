"use strict";
/* Proxie Maker – Oberfläche: Drucklisten, Karten, Druck, Import, Einstellungen */

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const state = { token: "", projects: [], current: null, tab: "list" };
// Teil von MTG Cards: Oberfläche unter /proxies/, API unter /proxies/api/…
const BASE = location.pathname.startsWith("/proxies") ? "/proxies" : "";
const BOARD_NAMES = { commander: "Commander", companion: "Companion", main: "Deck", side: "Sideboard", maybe: "Vielleicht" };
const TYPE_GROUPS = [["Creature", "Kreaturen"], ["Planeswalker", "Planeswalker"], ["Battle", "Schlachten"],
  ["Instant", "Spontanzauber"], ["Sorcery", "Hexereien"], ["Artifact", "Artefakte"], ["Enchantment", "Verzauberungen"],
  ["Land", "Länder"]];
const LANGS = { en: "Englisch", de: "Deutsch", fr: "Französisch", it: "Italienisch", es: "Spanisch", pt: "Portugiesisch",
  ja: "Japanisch", ko: "Koreanisch", ru: "Russisch", zhs: "Chinesisch (vereinf.)", zht: "Chinesisch (trad.)" };

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function store(k, v) {
  try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (_) { /* privat */ }
  return null;
}
const euro = (v) => v == null ? "–" : Number(v).toLocaleString("de-DE", { style: "currency", currency: "EUR" });
const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };

function toast(msg, kind = "") {
  const t = document.createElement("div");
  t.className = `toast ${kind}`;
  t.textContent = msg;
  $("#toasts").appendChild(t);
  setTimeout(() => t.remove(), kind === "err" ? 7000 : 3500);
}

async function api(path, opts = {}) {
  const headers = { Authorization: "Bearer " + state.token };
  let body;
  if (opts.json !== undefined) { headers["Content-Type"] = "application/json"; body = JSON.stringify(opts.json); }
  const res = await fetch(BASE + path, { method: opts.method || "GET", headers, body });
  if (res.status === 401) { showLogin(); throw new Error("Token fehlt oder ist falsch"); }
  const data = res.headers.get("Content-Type")?.includes("json") ? await res.json() : null;
  if (!res.ok) throw new Error((data && data.error) || `Fehler ${res.status}`);
  return data;
}
const authUrl = (path) => BASE + path + (path.includes("?") ? "&" : "?") + "token=" + encodeURIComponent(state.token);

/** Bild-Datei -> JPEG (Data-URL), höchstens maxPx an der längsten Seite. */
function fileToJpeg(file, maxPx = 2200, quality = 0.92) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      const s = Math.min(1, maxPx / Math.max(img.width, img.height));
      const c = document.createElement("canvas");
      c.width = Math.round(img.width * s);
      c.height = Math.round(img.height * s);
      const g = c.getContext("2d");
      g.fillStyle = "#fff";
      g.fillRect(0, 0, c.width, c.height);
      g.drawImage(img, 0, 0, c.width, c.height);
      URL.revokeObjectURL(url);
      resolve(c.toDataURL("image/jpeg", quality));
    };
    img.onerror = () => { URL.revokeObjectURL(url); reject(new Error(`${file.name}: kein lesbares Bild`)); };
    img.src = url;
  });
}

/** Bild ins Kartenformat (745 × 1040) bringen – für komplett eigene Karten und Rückseiten. */
function fileToCard(file, fit = "cover") {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      const c = document.createElement("canvas");
      c.width = 745; c.height = 1040;
      const g = c.getContext("2d");
      g.fillStyle = "#fff";
      g.fillRect(0, 0, 745, 1040);
      const s = (fit === "contain" ? Math.min : Math.max)(745 / img.width, 1040 / img.height);
      g.imageSmoothingQuality = "high";
      g.drawImage(img, (745 - img.width * s) / 2, (1040 - img.height * s) / 2, img.width * s, img.height * s);
      URL.revokeObjectURL(url);
      resolve(c.toDataURL("image/jpeg", 0.93));
    };
    img.onerror = () => { URL.revokeObjectURL(url); reject(new Error(`${file.name}: kein lesbares Bild`)); };
    img.src = url;
  });
}

function pickFiles(accept = "image/*", multiple = false) {
  return new Promise((resolve) => {
    const inp = document.createElement("input");
    inp.type = "file";
    inp.accept = accept;
    inp.multiple = multiple;
    inp.onchange = () => resolve([...inp.files]);
    inp.click();
  });
}

function dialog(html, cls = "modal") {
  const d = document.createElement("dialog");
  d.className = cls;
  d.innerHTML = html;
  document.body.appendChild(d);
  d.addEventListener("close", () => d.remove());
  d.addEventListener("click", (e) => { if (e.target === d || e.target.closest("[data-close]")) d.close(); });
  d.showModal();
  return d;
}

// ------------------------------------------------------------------ Anmeldung
function showLogin() {
  $("#login").classList.remove("hidden");
  $("#login-token").focus();
}
$("#login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  state.token = $("#login-token").value.replace(/\s+/g, "").toUpperCase();
  store("pm-token", state.token);
  try { await api("/api/info"); $("#login").classList.add("hidden"); loadProjects(); }
  catch (err) { toast(err.message, "err"); }
});

// ------------------------------------------------------------------ Drucklisten
const tabProjects = () => state.projects.filter((p) => (p.kind || "list") === state.tab);

async function loadProjects(selectId) {
  try { state.projects = (await api("/api/projects")).projects; } catch (e) { return; }
  const mine = tabProjects();
  const id = selectId ?? (state.current && (state.current.kind || "list") === state.tab ? state.current.id : null)
    ?? (+store("pm-project-" + state.tab) || null);
  renderProjectList();
  if (id && mine.some((p) => p.id === id)) openProject(id);
  else if (mine.length) openProject(mine[0].id);
  else renderEmpty();
}

function showTab(tab) {
  state.tab = tab;
  store("pm-tab", tab);
  $$(".tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  $("#side-title").textContent = tab === "deck" ? "Decks" : "Drucklisten";
  state.current = null;
  loadProjects();
}

function renderProjectList() {
  $("#project-list").innerHTML = tabProjects().map((p) => `
    <div class="project-item ${state.current?.id === p.id ? "active" : ""}" data-pid="${p.id}">
      <div>${esc(p.name)}</div>
      <div class="s">${p.cards} Karten · ${p.copies} Exemplare${p.edited ? ` · ${p.edited} bearbeitet` : ""} · ${euro(p.value_eur)}</div>
    </div>`).join("") || `<p class="muted small">${state.tab === "deck" ? "Noch keine Decks." : "Noch keine Drucklisten."}</p>`;
}

function renderEmpty() {
  state.current = null;
  if (state.tab === "deck") {
    $("#main").innerHTML = `<div class="empty"><h2>Decks</h2>
      <p>Füge eine komplette Deckliste ein (Moxfield, Archidekt, MTG Arena, MTGO) oder übernimm ein Deck aus MTG Cards.
        Du siehst das ganze Deck nach Kartentypen sortiert, kannst jede Karte oder das ganze Deck auf einmal gestalten
        und es mit oder ohne Sideboard und Standardländer drucken.</p>
      <button class="btn primary" onclick="newProject()">＋ Neues Deck</button></div>`;
    return;
  }
  $("#main").innerHTML = `<div class="empty"><h2>Willkommen bei Proxie Maker</h2>
    <p>Lege eine Druckliste an (z.B. für ein Deck), füge Karten per Name, Deckliste oder aus MTG Cards hinzu,
      personalisiere sie im Editor – eigenes Artwork, Farben, Rand, Texte – und drucke sie als PDF (9 pro Seite).</p>
    <button class="btn primary" onclick="newProject()">＋ Neue Druckliste</button></div>`;
}

async function newProject() {
  const deck = state.tab === "deck";
  const d = dialog(`<form class="modal-body" id="np">
    <header><h2>${deck ? "Neues Deck" : "Neue Druckliste"}</h2><button type="button" class="x" data-close>×</button></header>
    <label>Name <input id="np-name" required placeholder="${deck ? "z.B. Atraxa Superfriends" : "z.B. Playtest-Karten"}"></label>
    <label>Deckliste${deck ? "" : " (optional)"} <textarea id="np-list" rows="${deck ? 14 : 8}" placeholder="Commander&#10;1 Atraxa, Praetors' Voice&#10;&#10;Deck&#10;1 Sol Ring&#10;1 Lightning Bolt (M11) 149&#10;&#10;Sideboard&#10;1 Swords to Plowshares"></textarea></label>
    ${deck ? `<p class="muted small">Abschnitte „Commander“, „Companion“, „Deck“, „Sideboard“ werden erkannt (auch *CMDR* von Moxfield).
      Mit Set-Code wird genau dieser Druck genommen.</p>
      <label>… oder Deck aus MTG Cards übernehmen <select id="np-mtg"><option value="">– (Deckliste oben verwenden)</option></select></label>` : ""}
    <label>Sprache der Karten <select id="np-lang"><option value="">Englisch</option>
      ${Object.entries(LANGS).filter(([k]) => k !== "en").map(([k, v]) => `<option value="${k}">${v}</option>`).join("")}</select></label>
    <footer><span class="spacer"></span><button type="button" class="btn" data-close>Abbrechen</button>
      <button class="btn primary">Anlegen</button></footer></form>`);
  $("#np-name", d).focus();
  if (deck) {
    api("/api/mtg/decks").then(({ decks }) => {
      $("#np-mtg", d).innerHTML += decks.map((k) => `<option value="${k.id}">${esc(k.name)} (${k.cards} Karten)</option>`).join("");
      $("#np-mtg", d).onchange = (e) => {
        const k = decks.find((x) => String(x.id) === e.target.value);
        if (k && !$("#np-name", d).value) $("#np-name", d).value = k.name;
      };
    }).catch(() => { $("#np-mtg", d).innerHTML = `<option value="">MTG Cards nicht verbunden (⚙ Einstellungen)</option>`; });
  }
  $("#np", d).onsubmit = async (e) => {
    e.preventDefault();
    const btn = $("button.primary", d);
    btn.disabled = true;
    btn.textContent = "Lege an …";
    try {
      const r = await api("/api/projects", { method: "POST", json: { name: $("#np-name", d).value,
        list: $("#np-list", d).value, lang: $("#np-lang", d).value, kind: state.tab,
        mtg_deck_id: deck ? $("#np-mtg", d).value || null : null } });
      if (r.errors.length) toast("Nicht gefunden:\n" + r.errors.slice(0, 10).join("\n"), "err");
      d.close();
      loadProjects(r.project.id);
    } catch (err) { toast(err.message, "err"); btn.disabled = false; btn.textContent = "Anlegen"; }
  };
}

async function openProject(id) {
  try { state.current = await api(`/api/projects/${id}`); } catch (e) { return toast(e.message, "err"); }
  store("pm-project-" + state.tab, String(id));
  renderProjectList();
  renderProject();
  $("#sidebar").classList.remove("open");
}

async function reloadProject() {
  if (!state.current) return;
  state.current = await api(`/api/projects/${state.current.id}`);
  renderProject();
  try { state.projects = (await api("/api/projects")).projects; renderProjectList(); } catch (_) { /* egal */ }
}

function itemImage(it) {
  if (it.has_rendered) return authUrl(`/api/items/${it.id}/rendered?v=${it.version}`);
  if (it.kind === "custom") return authUrl(`/api/items/${it.id}/custom?v=${it.version}`);
  return it.image_url || "";
}

function renderProject() {
  const p = state.current;
  if (p.kind === "deck") return renderDeck();
  const edited = p.items.filter((i) => i.has_rendered).length;
  $("#main").innerHTML = `
    <div class="head">
      <h2>${esc(p.name)}</h2>
      <button class="btn small" data-pact="rename" title="Umbenennen">✎</button>
      <span class="spacer"></span>
      <button class="btn small" data-pact="prices">⟳ Preise</button>
      <button class="btn small" data-pact="duplicate">Duplizieren</button>
      <button class="btn small danger" data-pact="delete">Löschen</button>
      <button class="btn primary" data-pact="print">🖨 Drucken</button>
    </div>
    <div class="stats">
      <div class="stat"><b>${p.items.length}</b>Karten</div>
      <div class="stat"><b>${p.copies}</b>Exemplare</div>
      <div class="stat"><b>${Math.ceil(p.copies / 9) || 0}</b>Seiten</div>
      <div class="stat"><b>${edited}</b>personalisiert</div>
      <div class="stat" title="Wert der Originalkarten (zum Vergleich)"><b>${euro(p.value_eur)}</b>Wert der Originale</div>
      ${p.alerts ? `<div class="stat ok"><b>${p.alerts}</b>unter Zielpreis</div>` : ""}
    </div>
    <form class="addbar" id="addbar" autocomplete="off">
      <label class="grow">Karte <input id="add-name" class="grow" list="add-ac" placeholder="Name (deutsch oder englisch) …" required>
        <datalist id="add-ac"></datalist></label>
      <label>Anzahl <input id="add-qty" type="number" min="1" value="1" style="width:70px"></label>
      <label>Sprache <select id="add-lang"><option value="">Englisch</option>
        ${Object.entries(LANGS).filter(([k]) => k !== "en").map(([k, v]) => `<option value="${k}" ${store("pm-lang") === k ? "selected" : ""}>${v}</option>`).join("")}</select></label>
      <label>Zielpreis € <input id="add-max" style="width:90px" placeholder="–"></label>
      <label class="check" title="Günstigsten Druck verwenden (sonst Scryfalls Standard-Druck)"><input type="checkbox" id="add-any" checked> günstigster Druck</label>
      <button class="btn primary">＋ Hinzufügen</button>
      <span class="spacer"></span>
      <button type="button" class="btn small" data-pact="list">Liste einfügen</button>
      <button type="button" class="btn small" data-pact="mtg">Aus MTG Cards</button>
      <button type="button" class="btn small" data-pact="custom">Eigenes Bild</button>
    </form>
    ${p.items.length ? `<div class="row" style="margin-bottom:10px">
        <label class="check"><input type="checkbox" id="sel-all"> alle auswählen</label>
        <span class="muted small">Auswahl gilt für Drucken und „Stil anwenden“. Karte antippen = Editor.</span></div>
      <div class="grid">${p.items.map(cardHtml).join("")}</div>`
      : `<div class="empty"><p>Noch keine Karten. Oben per Name hinzufügen, eine Deckliste einfügen oder aus MTG Cards übernehmen.</p></div>`}`;
}

function deckGroup(it) {
  const board = it.board || "main";
  if (board !== "main") return BOARD_NAMES[board];
  const front = (it.type_line || "").split("//")[0];
  const g = TYPE_GROUPS.find(([t]) => front.includes(t));
  return g ? g[1] : (it.kind === "custom" ? "Eigene Karten" : "Sonstige");
}

function renderDeck() {
  const p = state.current;
  const order = ["Commander", "Companion", ...TYPE_GROUPS.map((g) => g[1]), "Sonstige", "Eigene Karten", "Sideboard", "Vielleicht"];
  const groups = {};
  for (const it of p.items) (groups[deckGroup(it)] = groups[deckGroup(it)] || []).push(it);
  const inDeck = p.items.filter((i) => ["commander", "companion", "main"].includes(i.board || "main"));
  const count = (list) => list.reduce((s, i) => s + i.quantity, 0);
  const commanders = p.items.filter((i) => i.board === "commander").map((i) => i.name);
  const edited = p.items.filter((i) => i.has_rendered).length;
  $("#main").innerHTML = `
    <div class="head">
      <h2>${esc(p.name)}</h2>
      <button class="btn small" data-pact="rename" title="Umbenennen">✎</button>
      <span class="spacer"></span>
      <button class="btn small" data-pact="style" title="Eine Karte gestalten und den Stil auf das ganze Deck übertragen">🎨 Stil fürs ganze Deck</button>
      <a class="btn small" href="${esc(authUrl(`/api/projects/${p.id}/decklist.txt`))}" download>Deckliste ⇩</a>
      <button class="btn small" data-pact="duplicate">Duplizieren</button>
      <button class="btn small danger" data-pact="delete">Löschen</button>
      <button class="btn primary" data-pact="print">🖨 Deck drucken</button>
    </div>
    ${commanders.length ? `<p class="muted">Commander: <b>${commanders.map(esc).join(" & ")}</b></p>` : ""}
    <div class="stats">
      <div class="stat"><b>${count(inDeck)}</b>Karten im Deck</div>
      ${groups.Sideboard ? `<div class="stat"><b>${count(groups.Sideboard)}</b>Sideboard</div>` : ""}
      <div class="stat"><b>${count(groups["Länder"] || [])}</b>Länder</div>
      <div class="stat"><b>${edited}/${p.items.length}</b>personalisiert</div>
      <div class="stat" title="Wert der Originalkarten (zum Vergleich)"><b>${euro(p.value_eur)}</b>Wert der Originale</div>
    </div>
    <form class="addbar" id="addbar" autocomplete="off">
      <label class="grow">Karte hinzufügen <input id="add-name" class="grow" list="add-ac" placeholder="Name …" required>
        <datalist id="add-ac"></datalist></label>
      <label>Anzahl <input id="add-qty" type="number" min="1" value="1" style="width:70px"></label>
      <label>Bereich <select id="add-board">${Object.entries(BOARD_NAMES).map(([k, v]) => `<option value="${k}" ${k === "main" ? "selected" : ""}>${v}</option>`).join("")}</select></label>
      <label>Sprache <select id="add-lang"><option value="">Englisch</option>
        ${Object.entries(LANGS).filter(([k]) => k !== "en").map(([k, v]) => `<option value="${k}" ${store("pm-lang") === k ? "selected" : ""}>${v}</option>`).join("")}</select></label>
      <input type="checkbox" id="add-any" checked hidden><input id="add-max" hidden>
      <button class="btn primary">＋</button>
      <span class="spacer"></span>
      <button type="button" class="btn small" data-pact="list">Liste ergänzen</button>
      <button type="button" class="btn small" data-pact="custom">Eigenes Bild</button>
    </form>
    ${p.items.length ? `<div class="row" style="margin-bottom:10px">
        <label class="check"><input type="checkbox" id="sel-all"> alle auswählen</label>
        <span class="muted small">Karte antippen = Editor. Auswahl gilt für Drucken und „Stil anwenden“.</span></div>
      ${order.filter((g) => groups[g]).map((g) => `<div class="deck-sec"><h3>${esc(g)} <span class="n">(${count(groups[g])})</span>
        <button class="btn small" data-selgroup="${esc(g)}" title="Diesen Abschnitt auswählen">auswählen</button></h3>
        <div class="grid small">${groups[g].map((it) => cardHtml(it, true)).join("")}</div></div>`).join("")}`
      : `<div class="empty"><p>Das Deck ist leer – „Liste ergänzen“ oder oben Karten hinzufügen.</p></div>`}`;
}

function cardHtml(it, deckMode = false) {
  const print = it.kind === "custom" ? "eigenes Bild" : (it.any_print ? "günstigster Druck" : `${it.set_code} #${it.collector_number}`);
  return `<div class="card ${it.target_reached ? "reached" : ""}" data-iid="${it.id}">
    <div class="img" data-iact="edit">
      <img src="${esc(itemImage(it))}" alt="" loading="lazy">
      <label class="sel" onclick="event.stopPropagation()"><input type="checkbox" class="sel-item"></label>
      <div class="badges">
        ${it.has_rendered ? `<span class="pill edit">✎ personalisiert</span>` : ""}
        ${it.lowres && !it.has_rendered ? `<span class="pill warn" title="Scryfall hat hier nur einen unscharfen Scan – beim Druck wird ein scharfer mit gleichem Artwork gesucht">unscharf</span>` : ""}
        ${it.image_url_back ? `<span class="pill">doppelseitig</span>` : ""}
        ${it.target_reached ? `<span class="pill ok">✓ Zielpreis</span>` : ""}
      </div>
    </div>
    <div class="name" title="${esc(it.name)}">${esc(it.name)}</div>
    <div class="meta">${it.kind === "custom" ? print : `<a href="#" data-iact="print" title="Druck / Sprache wählen">${esc(print)}${it.lang && it.lang !== "en" ? " · " + esc(it.lang.toUpperCase()) : ""} ✎</a>`}
      ${it.kind === "scryfall" ? ` · ${euro(it.price_eur)}` : ""}</div>
    <div class="acts">
      <span class="qty"><button class="btn small" data-iact="dec">−</button><b>${it.quantity}</b><button class="btn small" data-iact="inc">＋</button></span>
      <span class="spacer"></span>
      ${deckMode ? `<select class="board-sel" title="Bereich">${Object.entries(BOARD_NAMES).map(([k, v]) => `<option value="${k}" ${(it.board || "main") === k ? "selected" : ""}>${v}</option>`).join("")}</select>` : ""}
      ${it.kind === "scryfall" && !deckMode ? `<input class="target" value="${it.max_price_eur == null ? "" : String(it.max_price_eur).replace(".", ",")}" placeholder="Ziel €" title="Zielpreis" style="width:62px;padding:3px 5px">` : ""}
      ${it.has_rendered ? `<button class="btn small" data-iact="reset" title="Bearbeitung entfernen (Original drucken)">↺</button>` : ""}
      <button class="btn small danger" data-iact="del" title="Entfernen">✕</button>
    </div></div>`;
}

const selectedIds = () => $$(".sel-item:checked").map((c) => +c.closest("[data-iid]").dataset.iid);

// ------------------------------------------------------------------ Aktionen
$("#main").addEventListener("submit", async (e) => {
  if (e.target.id !== "addbar") return;
  e.preventDefault();
  const btn = $("button.primary", e.target);
  btn.disabled = true;
  try {
    const lang = $("#add-lang").value;
    store("pm-lang", lang);
    const it = await api(`/api/projects/${state.current.id}/items`, { method: "POST", json: {
      name: $("#add-name").value.trim(), quantity: +$("#add-qty").value || 1, lang,
      any_print: $("#add-any").checked, max_price_eur: $("#add-max").value.trim(),
      board: $("#add-board") ? $("#add-board").value : "main" } });
    toast(`${it.name} hinzugefügt`, "ok");
    await reloadProject();
    $("#add-name").focus();
  } catch (err) { toast(err.message, "err"); btn.disabled = false; }
});

const autocomplete = debounce(async (q) => {
  if (q.length < 2) return;
  try {
    const { data } = await api("/api/autocomplete?q=" + encodeURIComponent(q));
    $("#add-ac").innerHTML = data.slice(0, 20).map((n) => `<option value="${esc(n)}">`).join("");
  } catch (_) { /* egal */ }
}, 220);
$("#main").addEventListener("input", (e) => { if (e.target.id === "add-name") autocomplete(e.target.value.trim()); });

$("#main").addEventListener("change", async (e) => {
  if (e.target.id === "sel-all") return $$(".sel-item").forEach((c) => { c.checked = e.target.checked; });
  if (e.target.classList.contains("board-sel")) {
    const id = e.target.closest("[data-iid]").dataset.iid;
    try { await api(`/api/items/${id}`, { method: "PATCH", json: { board: e.target.value } }); reloadProject(); }
    catch (err) { toast(err.message, "err"); }
    return;
  }
  if (e.target.classList.contains("target")) {
    const id = e.target.closest("[data-iid]").dataset.iid;
    try { await api(`/api/items/${id}`, { method: "PATCH", json: { max_price_eur: e.target.value.trim() } }); reloadProject(); }
    catch (err) { toast(err.message, "err"); }
  }
});

$("#main").addEventListener("click", async (e) => {
  const sg = e.target.closest("[data-selgroup]");
  if (sg) {
    const boxes = $$(".sel-item", sg.closest(".deck-sec"));
    const on = !boxes.every((c) => c.checked);
    boxes.forEach((c) => { c.checked = on; });
    return;
  }
  const pa = e.target.closest("[data-pact]");
  if (pa) return projectAction(pa.dataset.pact);
  const ia = e.target.closest("[data-iact]");
  if (!ia) return;
  e.preventDefault();
  const id = +ia.closest("[data-iid]").dataset.iid;
  const it = state.current.items.find((x) => x.id === id);
  try {
    switch (ia.dataset.iact) {
      case "edit": return openEditor(it);
      case "print": return choosePrint(it);
      case "inc": await api(`/api/items/${id}`, { method: "PATCH", json: { quantity: it.quantity + 1 } }); break;
      case "dec":
        if (it.quantity <= 1 && !confirm(`${it.name} entfernen?`)) return;
        await api(`/api/items/${id}`, { method: "PATCH", json: { quantity: it.quantity - 1 } }); break;
      case "del":
        if (!confirm(`${it.name} entfernen?`)) return;
        await api(`/api/items/${id}`, { method: "DELETE" }); break;
      case "reset":
        if (!confirm("Personalisierung entfernen und das Original drucken?")) return;
        await api(`/api/items/${id}/rendered?settings=1`, { method: "DELETE" }); break;
      default: return;
    }
    reloadProject();
  } catch (err) { toast(err.message, "err"); }
});

async function projectAction(act) {
  const p = state.current;
  try {
    if (act === "rename") {
      const name = prompt("Name der Druckliste", p.name);
      if (name) { await api(`/api/projects/${p.id}`, { method: "PATCH", json: { name } }); reloadProject(); }
    } else if (act === "delete") {
      if (!confirm(`Druckliste „${p.name}“ mit allen Bearbeitungen löschen?`)) return;
      await api(`/api/projects/${p.id}`, { method: "DELETE" });
      state.current = null;
      loadProjects();
    } else if (act === "duplicate") {
      const d = await api(`/api/projects/${p.id}/duplicate`, { method: "POST", json: {} });
      loadProjects(d.id);
    } else if (act === "prices") {
      toast("Prüfe Preise …");
      const r = await api(`/api/projects/${p.id}/refresh-prices`, { method: "POST" });
      toast(`${r.updated} Preise aktualisiert`, "ok");
      reloadProject();
    } else if (act === "style") {
      const first = p.items.find((i) => i.board === "commander") || p.items.find((i) => i.kind === "scryfall") || p.items[0];
      if (!first) return toast("Das Deck ist leer", "err");
      toast("Gestalte diese Karte und nutze dann unter „⭐ Vorlagen“ „Diesen Stil … anwenden“ für das ganze Deck.");
      openEditor(first);
    } else if (act === "print") printDialog();
    else if (act === "list") listDialog();
    else if (act === "mtg") mtgDialog();
    else if (act === "custom") customDialog();
  } catch (err) { toast(err.message, "err"); }
}

// ------------------------------------------------------------------ Druck / Sprache wählen
async function choosePrint(it) {
  let chosen = it.any_print ? null : it.scryfall_id;
  const d = dialog(`<form class="modal-body" id="cp">
    <header><h2>Druck – ${esc(it.name)}</h2><button type="button" class="x" data-close>×</button></header>
    <p class="muted small">Bestimmt Bild (Edition, Sprache, Artwork) und Preis. Eine vorhandene Personalisierung bleibt als
      Einstellung erhalten und wird beim nächsten Öffnen des Editors auf den neuen Druck angewendet.</p>
    <label>Sprache <select id="cp-lang"><option value="">Englisch</option>
      ${Object.entries(LANGS).filter(([k]) => k !== "en").map(([k, v]) => `<option value="${k}" ${it.lang === k ? "selected" : ""}>${v}</option>`).join("")}</select></label>
    <div class="list-pick" id="cp-list"><p class="muted">Lade …</p></div>
    <footer><button type="button" class="btn" id="cp-any">Günstigster Druck</button><span class="spacer"></span>
      <button type="button" class="btn" data-close>Abbrechen</button><button class="btn primary">Übernehmen</button></footer></form>`);
  const load = async () => {
    const lang = $("#cp-lang", d).value;
    $("#cp-list", d).innerHTML = `<p class="muted">Lade …</p>`;
    try {
      const { data } = await api(`/api/prints?name=${encodeURIComponent(it.name)}${lang ? "&lang=" + lang : ""}`);
      $("#cp-list", d).innerHTML = data.slice().reverse().map((p) => `
        <label class="pick ${p.scryfall_id === chosen ? "active" : ""}"><input type="radio" name="cp" value="${esc(p.scryfall_id)}" ${p.scryfall_id === chosen ? "checked" : ""}>
          ${p.image_url ? `<img src="${esc(p.image_url)}" alt="" loading="lazy">` : ""}
          <span><b>${esc(p.set_name)}</b> (${esc(p.set_code)}) #${esc(p.collector_number)}<br>
          <span class="muted small">${esc((p.released_at || "").slice(0, 4))}${p.artist ? " · " + esc(p.artist) : ""}${p.image_status === "lowres" ? " · unscharfer Scan" : ""}</span></span>
          <span class="spacer"></span><b>${p.price_eur ? esc(p.price_eur) + " €" : (p.price_usd ? "$" + esc(p.price_usd) : "–")}</b></label>`).join("")
        || `<p class="muted">Keine Drucke in dieser Sprache.</p>`;
    } catch (err) { $("#cp-list", d).innerHTML = `<p class="muted">${esc(err.message)}</p>`; }
  };
  $("#cp-lang", d).onchange = load;
  $("#cp-list", d).onchange = (e) => { chosen = e.target.value; $$(".pick", d).forEach((l) => l.classList.toggle("active", $("input", l).checked)); };
  const save = async (json) => {
    try { await api(`/api/items/${it.id}`, { method: "PATCH", json }); d.close(); reloadProject(); }
    catch (err) { toast(err.message, "err"); }
  };
  $("#cp-any", d).onclick = () => save({ any_print: true });
  $("#cp", d).onsubmit = (e) => { e.preventDefault(); if (chosen) save({ scryfall_id: chosen }); };
  load();
}

// ------------------------------------------------------------------ Drucken
function printDialog() {
  const p = state.current;
  const ids = selectedIds();
  const items = ids.length ? p.items.filter((i) => ids.includes(i.id)) : p.items;
  const n = items.reduce((s, i) => s + i.quantity, 0);
  const d = dialog(`<form class="modal-body" id="pr">
    <header><h2>Drucken – ${esc(p.name)}</h2><button type="button" class="x" data-close>×</button></header>
    <p class="muted">${ids.length ? "Ausgewählt" : "Alle"}: ${items.length} Karten, ${n} Exemplare (≈ ${Math.ceil(n / 9)} Seiten).
      9 Karten pro Seite in Originalgröße (63,5 × 88,9 mm).</p>
    <div class="two">
      <label>Papier <select id="pr-paper"><option value="a4">A4</option><option value="letter">US Letter</option></select></label>
      <label>Anzahl <select id="pr-copies"><option value="">wie angegeben</option><option value="one">1 je Karte</option></select></label>
      <label>Abstand <select id="pr-gap"><option value="0">kein (Schnittmarken)</option><option value="1">1 mm</option>
        <option value="2">2 mm</option><option value="3">3 mm</option></select></label>
      <label>Rückseite <select id="pr-back"><option value="">ohne</option></select></label>
    </div>
    ${p.kind === "deck" ? `<div class="row">
      <label class="check"><input type="checkbox" id="pr-side"> Sideboard mitdrucken</label>
      <label class="check"><input type="checkbox" id="pr-maybe"> „Vielleicht“ mitdrucken</label>
      <label class="check"><input type="checkbox" id="pr-basic" checked> Standardländer weglassen</label></div>` : ""}
    <label class="check"><input type="checkbox" id="pr-cut" checked> Schnittmarken</label>
    <label class="check"><input type="checkbox" id="pr-duplex"> Beidseitig drucken (Rückseiten-Seiten einfügen, Wenden an der langen Kante)</label>
    <label class="check"><input type="checkbox" id="pr-hq" checked> Unscharfe Scryfall-Bilder durch scharfe mit gleichem Artwork ersetzen</label>
    <p class="muted small">Beim Drucken <b>100 % / tatsächliche Größe</b> wählen. Doppelseitige Karten: ohne „Beidseitig“
      wird die Rückseite als eigene Karte gedruckt. „Bilder (ZIP)“ liefert jede Karte als Einzelbild, z.B. für Druckdienste.</p>
    <footer><a class="btn" id="pr-zip">Bilder (ZIP)</a><span class="spacer"></span>
      <button type="button" class="btn" data-close>Abbrechen</button><button class="btn primary">PDF erstellen</button></footer></form>`);
  api("/api/backs").then(({ backs }) => {
    $("#pr-back", d).innerHTML = `<option value="">ohne eigene Rückseite</option>` +
      backs.map((b) => `<option value="${b.id}" ${p.back_id === b.id ? "selected" : ""}>${esc(b.name)}</option>`).join("");
  }).catch(() => {});
  const params = () => {
    const q = new URLSearchParams({ paper: $("#pr-paper", d).value, gap: $("#pr-gap", d).value,
      cut: $("#pr-cut", d).checked ? "1" : "0", hq: $("#pr-hq", d).checked ? "1" : "0",
      duplex: $("#pr-duplex", d).checked ? "1" : "0", token: state.token });
    if ($("#pr-copies", d).value) q.set("copies", "one");
    if (ids.length) q.set("ids", ids.join(","));
    if (p.kind === "deck") {
      q.set("boards", ["commander", "companion", "main", $("#pr-side", d).checked ? "side" : "", $("#pr-maybe", d).checked ? "maybe" : ""]
        .filter(Boolean).join(","));
      if ($("#pr-basic", d).checked) q.set("skip_basic", "1");
    }
    return q;
  };
  $("#pr-back", d).onchange = async () => {
    await api(`/api/projects/${p.id}`, { method: "PATCH", json: { back_id: $("#pr-back", d).value || null } });
    state.current.back_id = +$("#pr-back", d).value || null;
    if ($("#pr-back", d).value) $("#pr-duplex", d).checked = true;
  };
  const go = (path) => {
    const a = document.createElement("a");
    a.href = `${BASE}${path}?${params()}`;
    a.download = "";
    document.body.appendChild(a);
    a.click();
    a.remove();
    toast("Wird erstellt – Kartenbilder werden geladen …");
  };
  $("#pr-zip", d).onclick = () => go(`/api/projects/${p.id}/images.zip`);
  $("#pr", d).onsubmit = (e) => { e.preventDefault(); go(`/api/projects/${p.id}/print.pdf`); d.close(); };
}

// ------------------------------------------------------------------ Import
function listDialog() {
  const d = dialog(`<form class="modal-body" id="li">
    <header><h2>Liste einfügen</h2><button type="button" class="x" data-close>×</button></header>
    <p class="muted small">Formate von Moxfield, Archidekt, MTG Arena, MTGO: „1 Sol Ring“, „2x Lightning Bolt (M11) 149“ …
      Mit Set-Code wird genau dieser Druck genommen, sonst der günstigste.</p>
    <textarea id="li-text" rows="12"></textarea>
    <label>Sprache <select id="li-lang"><option value="">Englisch</option>
      ${Object.entries(LANGS).filter(([k]) => k !== "en").map(([k, v]) => `<option value="${k}">${v}</option>`).join("")}</select></label>
    <footer><span class="spacer"></span><button type="button" class="btn" data-close>Abbrechen</button><button class="btn primary">Übernehmen</button></footer></form>`);
  $("#li", d).onsubmit = async (e) => {
    e.preventDefault();
    const btn = $("button.primary", d);
    btn.disabled = true;
    btn.textContent = "Suche Karten …";
    try {
      const r = await api(`/api/projects/${state.current.id}/import`, { method: "POST",
        json: { list: $("#li-text", d).value, lang: $("#li-lang", d).value } });
      if (r.errors.length) toast("Nicht gefunden:\n" + r.errors.slice(0, 10).join("\n"), "err");
      else toast("Übernommen", "ok");
      d.close();
      reloadProject();
    } catch (err) { toast(err.message, "err"); btn.disabled = false; btn.textContent = "Übernehmen"; }
  };
}

async function mtgDialog() {
  let cfg;
  try { cfg = await api("/api/mtg/settings"); } catch (e) { return toast(e.message, "err"); }
  if (!cfg.url) { toast("Zuerst unter ⚙ Einstellungen den MTG-Cards-Server eintragen", "err"); return settingsDialog(); }
  const d = dialog(`<form class="modal-body" id="mi">
    <header><h2>Aus MTG Cards übernehmen</h2><button type="button" class="x" data-close>×</button></header>
    <label class="check"><input type="radio" name="src" value="wishlist" checked> Wunschliste (mit gewähltem Druck und Zielpreis)</label>
    <label class="check"><input type="radio" name="src" value="deck"> Deck:</label>
    <select id="mi-deck"><option>Lade Decks …</option></select>
    <label class="check"><input type="checkbox" id="mi-missing" checked> nur fehlende Karten</label>
    <label>Sprache <select id="mi-lang"><option value="">Englisch</option>
      ${Object.entries(LANGS).filter(([k]) => k !== "en").map(([k, v]) => `<option value="${k}">${v}</option>`).join("")}</select></label>
    <footer><span class="spacer"></span><button type="button" class="btn" data-close>Abbrechen</button><button class="btn primary">Übernehmen</button></footer></form>`);
  api("/api/mtg/decks").then(({ decks }) => {
    $("#mi-deck", d).innerHTML = decks.map((k) => `<option value="${k.id}">${esc(k.name)} (${k.missing} fehlen)</option>`).join("")
      || "<option value=''>keine Decks</option>";
  }).catch((e) => { $("#mi-deck", d).innerHTML = `<option value="">${esc(e.message)}</option>`; });
  $("#mi", d).onsubmit = async (e) => {
    e.preventDefault();
    const btn = $("button.primary", d);
    btn.disabled = true;
    btn.textContent = "Übernehme …";
    const src = $("input[name=src]:checked", d).value;
    try {
      const r = await api(`/api/projects/${state.current.id}/import-mtg`, { method: "POST", json: {
        source: src, deck_id: $("#mi-deck", d).value, missing_only: $("#mi-missing", d).checked, lang: $("#mi-lang", d).value } });
      toast(`${r.added} Exemplare übernommen` + (r.errors.length ? `\nNicht gefunden: ${r.errors.slice(0, 5).join(", ")}` : ""),
        r.errors.length ? "err" : "ok");
      d.close();
      reloadProject();
    } catch (err) { toast(err.message, "err"); btn.disabled = false; btn.textContent = "Übernehmen"; }
  };
}

async function customDialog() {
  const files = await pickFiles("image/*", true);
  if (!files.length) return;
  const fit = confirm("Bild auf Kartenformat zuschneiden?\n\nOK = zuschneiden (füllt die Karte)\nAbbrechen = ganzes Bild mit weißem Rand") ? "cover" : "contain";
  let ok = 0;
  for (const f of files) {
    try {
      const image = await fileToCard(f, fit);
      await api(`/api/projects/${state.current.id}/custom`, { method: "POST",
        json: { name: f.name.replace(/\.[^.]+$/, ""), image } });
      ok++;
    } catch (err) { toast(err.message, "err"); }
  }
  toast(`${ok} eigene Karten hinzugefügt`, "ok");
  reloadProject();
}

// ------------------------------------------------------------------ Einstellungen
async function settingsDialog() {
  const d = dialog(`<div class="modal-body">
    <header><h2>Einstellungen</h2><button type="button" class="x" data-close>×</button></header>
    <div id="st-mtg"><h3>MTG Cards verbinden</h3>
    <p class="muted small">Damit lassen sich Wunschliste und Decks aus deiner MTG-Cards-Sammlung übernehmen.</p>
    <label>Adresse <input id="st-url" placeholder="http://192.168.178.50:8765"></label>
    <label>Token <input id="st-token" placeholder="(gespeichert – zum Ändern neu eingeben)"></label>
    <label>Zertifikats-Fingerabdruck (nur bei HTTPS) <input id="st-fp" placeholder="AB:CD:…"></label>
    <div class="row"><button class="btn primary" id="st-save">Verbinden & speichern</button></div></div>
    <h3>Kartenrückseiten</h3>
    <p class="muted small">Für den beidseitigen Druck (Druck-Dialog → Rückseite). Bild wird ins Kartenformat gebracht.</p>
    <div id="st-backs" class="row"></div>
    <div class="row"><button class="btn" id="st-back-add">＋ Rückseite hochladen</button></div>
    <h3>Stil-Vorlagen</h3><div id="st-presets" class="row"></div>
    <h3>Sicherung</h3>
    <p class="muted small">Alle Drucklisten inkl. Bearbeitungen, eigener Bilder, Rückseiten und Vorlagen.</p>
    <div class="row"><a class="btn" href="${esc(authUrl("/api/export"))}" download>⇩ Sicherung speichern</a>
      <button class="btn" id="st-import">⇧ Sicherung einlesen</button></div>
    <h3>Zugang</h3>
    <div class="row"><button class="btn" id="st-logout">Abmelden (Token auf diesem Gerät vergessen)</button></div>
    <p class="muted small">Proxies sind nur für den Eigengebrauch (Playtest, eigene Decks) – nicht zum Verkauf oder Tausch.</p>
  </div>`);
  const loadBacks = async () => {
    const { backs } = await api("/api/backs");
    $("#st-backs", d).innerHTML = backs.map((b) => `<div style="text-align:center"><img src="${esc(authUrl(`/api/backs/${b.id}/image`))}"
      style="width:70px;border-radius:5px;display:block"><span class="small">${esc(b.name)}</span>
      <button class="btn small danger" data-back="${b.id}">✕</button></div>`).join("") || `<span class="muted small">keine</span>`;
  };
  const loadPresets = async () => {
    const { presets } = await api("/api/presets");
    $("#st-presets", d).innerHTML = presets.map((p) => `<span class="pill">${esc(p.name)} <a href="#" data-preset="${p.id}">✕</a></span>`).join(" ")
      || `<span class="muted small">Im Editor „Als Vorlage speichern“.</span>`;
  };
  try {
    const cfg = await api("/api/mtg/settings");
    if (cfg.local) $("#st-mtg", d).innerHTML = `<h3>MTG Cards</h3><p class="muted small">✓ Läuft auf demselben Server –
      Wunschliste und Decks stehen direkt zur Verfügung („Aus MTG Cards“, „Neues Deck“).</p>`;
    $("#st-url", d).value = cfg.url || "";
    $("#st-fp", d).value = cfg.fingerprint || "";
  } catch (_) { /* egal */ }
  loadBacks().catch(() => {});
  loadPresets().catch(() => {});
  d.addEventListener("click", async (e) => {
    try {
      if (e.target.id === "st-save") {
        const r = await api("/api/mtg/settings", { method: "POST", json: { url: $("#st-url", d).value.trim(),
          token: $("#st-token", d).value.trim(), fingerprint: $("#st-fp", d).value.trim() } });
        toast(`Verbunden mit MTG Cards ${r.version}`, "ok");
      } else if (e.target.id === "st-back-add") {
        const [f] = await pickFiles();
        if (!f) return;
        const name = prompt("Name der Rückseite", f.name.replace(/\.[^.]+$/, "")) || "Rückseite";
        await api("/api/backs", { method: "POST", json: { name, image: await fileToCard(f) } });
        loadBacks();
      } else if (e.target.dataset.back) {
        if (!confirm("Rückseite löschen?")) return;
        await api(`/api/backs/${e.target.dataset.back}`, { method: "DELETE" });
        loadBacks();
      } else if (e.target.dataset.preset) {
        e.preventDefault();
        await api(`/api/presets/${e.target.dataset.preset}`, { method: "DELETE" });
        loadPresets();
      } else if (e.target.id === "st-import") {
        const [f] = await pickFiles(".json,application/json");
        if (!f) return;
        const replace = confirm("Alles ersetzen?\n\nOK = vorhandene Drucklisten ersetzen\nAbbrechen = ergänzen");
        const r = await api(`/api/import?mode=${replace ? "replace" : "add"}`, { method: "POST", json: JSON.parse(await f.text()) });
        toast(`${r.projects} Drucklisten, ${r.items} Karten eingelesen`, "ok");
        loadProjects();
      } else if (e.target.id === "st-logout") {
        store("pm-token", "");
        store("mtg-token", "");
        state.token = "";
        location.hash = "";
        location.reload();
      }
    } catch (err) { toast(err.message, "err"); }
  });
}

// ------------------------------------------------------------------ Start
$("#btn-new").onclick = newProject;
$$(".tabs button").forEach((b) => { b.onclick = () => showTab(b.dataset.tab); });
$("#btn-settings").onclick = settingsDialog;
$("#btn-side").onclick = () => $("#sidebar").classList.toggle("open");
$("#project-list").addEventListener("click", (e) => {
  const p = e.target.closest("[data-pid]");
  if (p) openProject(+p.dataset.pid);
});

(function init() {
  const m = location.hash.match(/token=([^&]+)/);
  if (m) {
    state.token = decodeURIComponent(m[1]);
    store("pm-token", state.token);
    history.replaceState(null, "", location.pathname);
  } else state.token = store("pm-token") || store("mtg-token") || "";   // gleicher Token wie MTG Cards
  if (BASE) {
    const back = document.createElement("a");
    back.className = "btn small";
    back.href = "/#token=" + encodeURIComponent(state.token);
    back.textContent = "← MTG Cards";
    back.title = "Zur Kartensammlung";
    if (!navigator.userAgent.includes("MTGCardsApp")) $(".topbar").insertBefore(back, $(".topbar .spacer"));
  }
  state.tab = store("pm-tab") === "deck" ? "deck" : "list";
  $$(".tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === state.tab));
  $("#side-title").textContent = state.tab === "deck" ? "Decks" : "Drucklisten";
  if (!state.token) return showLogin();
  loadProjects();
})();

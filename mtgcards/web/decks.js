"use strict";
/* MTG Cards – Deck-Verwaltung (nutzt Hilfsfunktionen aus app.js) */

const decks = { current: null, list: [], formMode: "new" };
const BOARD_TITLES = { side: "Sideboard", maybe: "Vielleicht" };
const GROUP_ORDER = ["Commander", "Creature", "Planeswalker", "Battle", "Instant", "Sorcery", "Artifact",
  "Enchantment", "Land", "Sonstige", "Sideboard", "Vielleicht"];
const GROUP_TITLES = { Creature: "Kreaturen", Planeswalker: "Planeswalker", Battle: "Schlachten", Instant: "Spontanzauber",
  Sorcery: "Hexereien", Artifact: "Artefakte", Enchantment: "Verzauberungen", Land: "Länder" };

function showTab(tab) {
  $$(".tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  $("#collection-view").classList.toggle("hidden", tab !== "collection");
  $("#decks-view").classList.toggle("hidden", tab !== "decks");
  $("#stats-view").classList.toggle("hidden", tab !== "stats");
  $("#wish-view").classList.toggle("hidden", tab !== "wishlist");
  $(".searchbox").style.visibility = tab === "collection" ? "" : "hidden";
  store("mtg-tab", tab);
  if (tab === "decks") loadDecks();
  if (tab === "stats" && typeof loadStats === "function") loadStats();
  if (tab === "wishlist" && typeof loadWishlist === "function") loadWishlist();
}

function decksVisible() { return !$("#decks-view").classList.contains("hidden"); }

async function loadDecks(selectId) {
  try {
    decks.list = (await api("/api/decks")).decks;
  } catch (e) { return toast(e.message, "err"); }
  const id = selectId ?? (decks.current && decks.current.id) ?? (decks.list[0] && decks.list[0].id);
  if (id && decks.list.some((d) => d.id === id)) await openDeck(id);
  else { decks.current = null; renderDeckEmpty(); }
  renderDeckList();
}

function renderDeckList() {
  $("#deck-list").innerHTML = decks.list.map((d) => {
    const pct = d.stats.cards ? Math.round(100 * d.stats.owned / d.stats.cards) : 0;
    return `<div class="deck-item ${decks.current && decks.current.id === d.id ? "active" : ""}" data-deck="${d.id}">
      <div class="t">${esc(d.name)}</div>
      <div class="s"><span>${esc(d.commanders.join(" & ") || d.format)}</span>${d.commanders.length ? ciHtml(d.color_identity) : ""}</div>
      <div class="s"><span>${d.stats.cards} Karten</span><span>${d.stats.missing ? d.stats.missing + " fehlen" : "✓ komplett"}</span></div>
      <div class="progress"><div style="width:${pct}%"></div></div>
    </div>`;
  }).join("") || `<p class="muted small">Noch keine Decks.</p>`;
}

function renderDeckEmpty() {
  $("#deck-main").innerHTML = `<div class="empty"><h2>Decks</h2>
    <p>Lege ein Deck an und füge eine Deckliste ein (z.B. Export aus Moxfield, Archidekt oder MTG Arena).
    Du siehst dann sofort, welche Karten du schon besitzt und welche fehlen.</p></div>`;
}

async function openDeck(id) {
  try {
    decks.current = await api(`/api/decks/${id}`);
  } catch (e) { return toast(e.message, "err"); }
  renderDeck(decks.current);
  renderDeckList();
}

function cardGroup(c) {
  if (c.board === "side" || c.board === "maybe") return BOARD_TITLES[c.board];
  return c.group;
}

function renderDeck(d) {
  const st = d.stats;
  const groups = {};
  for (const c of d.cards) (groups[cardGroup(c)] = groups[cardGroup(c)] || []).push(c);
  const order = GROUP_ORDER.filter((g) => groups[g]);
  const t = encodeURIComponent(state.token || "");
  $("#deck-main").innerHTML = `
    <div class="deck-head">
      <h2>${esc(d.name)}</h2> ${d.commanders.length ? ciHtml(d.color_identity) : ""}
      <span class="muted">${esc(d.format)}</span>
      <span class="spacer"></span>
      <button class="btn small" data-dact="import">⇩ Liste einfügen</button>
      <button class="btn small" data-dact="missing">Fehlende kopieren</button>
      ${st.missing ? `<button class="btn small" data-dact="towish">Fehlende → Wunschliste</button>` : ""}
      <a class="btn small" href="/api/decks/${d.id}/export?token=${t}" download="${esc(d.name)}.txt">Exportieren</a>
      <button class="btn small" data-dact="rename">Umbenennen</button>
      <button class="btn small danger" data-dact="delete">Löschen</button>
    </div>
    <div class="deck-stats">
      <div class="stat"><b>${st.cards}</b>Karten</div>
      <div class="stat good"><b>${st.owned}</b>vorhanden</div>
      <div class="stat ${st.missing ? "bad" : "good"}"><b>${st.missing}</b>fehlen</div>
      ${st.basic_lands ? `<div class="stat"><b>${st.basic_lands}</b>Standardländer</div>` : ""}
      ${st.shared ? `<div class="stat warn" title="Diese Karten besitzt du, sie stecken aber auch in anderen Decks. Um alle Decks gleichzeitig zu bauen, fehlen ${st.missing_reserved}."><b>${st.shared}</b>mit anderen Decks geteilt ⇄</div>` : ""}
      ${d.commanders.length ? `<div class="stat ${st.outside_identity ? "bad" : "good"}"><b>${st.outside_identity}</b>außerhalb der Farbidentität</div>` : ""}
      ${deckCurveHtml(d)}
    </div>
    <div class="deck-add">
      <div class="ac-wrap"><input id="deck-add-name" list="deck-ac" placeholder="Karte hinzufügen (Name) …" autocomplete="off">
        <datalist id="deck-ac"></datalist></div>
      <select id="deck-add-board" style="width:auto">
        <option value="main">Deck</option><option value="commander">Commander</option>
        <option value="side">Sideboard</option><option value="maybe">Vielleicht</option></select>
      <button class="btn primary" data-dact="add">＋</button>
    </div>
    ${d.cards.length ? "" : `<p class="muted">Noch keine Karten – „Liste einfügen“ oder oben einzeln hinzufügen.</p>`}
    <div class="deck-groups">${order.map((g) => {
      const cards = groups[g];
      const n = cards.reduce((s, c) => s + c.quantity, 0);
      return `<div class="deck-group"><h3>${esc(GROUP_TITLES[g] || g)} (${n})</h3>${cards.map(deckCardHtml).join("")}</div>`;
    }).join("")}</div>`;
}

/** Mini-Manakurve des Decks (ohne Länder, nur Deck + Commander). */
function deckCurveHtml(d) {
  const curve = [0, 0, 0, 0, 0, 0, 0, 0];
  for (const c of d.cards) {
    if (!["main", "commander"].includes(c.board) || (c.type_line || "").split("//")[0].includes("Land") || c.cmc == null) continue;
    curve[Math.min(7, Math.floor(c.cmc))] += c.quantity;
  }
  const max = Math.max(...curve, 1);
  if (!curve.some(Boolean)) return "";
  return `<div class="stat mini-curve" title="Manakurve">${curve.map((n, i) =>
    `<span data-n="${n}" title="Manawert ${i === 7 ? "7+" : i}: ${n} Karten"><i style="height:${n ? Math.max(8, 100 * n / max) : 0}%"></i><em>${i === 7 ? "7+" : i}</em></span>`).join("")}</div>`;
}

function deckCardHtml(c) {
  const cls = c.basic ? "basic" : (c.missing ? "miss" : (c.shared ? "shared" : "own"));
  const status = c.basic ? "–" : (c.missing ? "✗" : (c.shared ? "⇄" : "✓"));
  const others = (c.other_decks || []).map((u) => `${u.deck} (${u.quantity})`).join(", ");
  let tip = c.basic ? "Standardland" : `${c.owned} in der Sammlung`;
  if (others) tip += ` · auch in: ${others}`;
  if (c.shared) tip += " – reicht nicht für alle Decks gleichzeitig";
  return `<div class="dc ${cls}" data-dc="${c.id}">
    <span class="q">${c.quantity}</span>
    <span class="st" title="${esc(tip)}">${status}</span>
    <span class="n" data-img="${esc(c.image_url || "")}" title="${esc(tip)}">${esc(c.name)}${c.missing && c.owned ? ` <span class="small">(${c.owned}/${c.quantity})</span>` : ""}</span>
    ${c.outside_identity ? `<span class="warn" title="Außerhalb der Farbidentität des Commanders">⚠</span>` : ""}
    ${manaHtml(c.mana_cost)}
    <span class="acts">
      <button data-op="inc" title="+1">＋</button><button data-op="dec" title="−1">−</button>
      <button data-op="cmd" title="${c.board === "commander" ? "Kein Commander mehr" : "Als Commander"}">★</button>
      <button data-op="side" title="${c.board === "side" ? "Ins Deck" : "Ins Sideboard"}">⇄</button>
      <button data-op="del" title="Entfernen">✕</button>
    </span></div>`;
}

async function deckCardOp(id, op) {
  const c = decks.current.cards.find((x) => x.id === +id);
  if (!c) return;
  let req;
  if (op === "inc") req = { method: "PATCH", json: { quantity: c.quantity + 1 } };
  if (op === "dec") req = { method: "PATCH", json: { quantity: c.quantity - 1 } };
  if (op === "cmd") req = { method: "PATCH", json: { board: c.board === "commander" ? "main" : "commander" } };
  if (op === "side") req = { method: "PATCH", json: { board: c.board === "side" ? "main" : "side" } };
  if (op === "del") req = { method: "DELETE" };
  try {
    decks.current = await api(`/api/deck-cards/${id}`, req);
    renderDeck(decks.current);
    refreshDeckSummary();
  } catch (e) { toast(e.message, "err"); }
}

async function refreshDeckSummary() {
  try { decks.list = (await api("/api/decks")).decks; renderDeckList(); } catch (_) { /* egal */ }
}

function showText(title, text) {
  let dlg = $("#dlg-text");
  if (!dlg) {
    dlg = document.createElement("dialog");
    dlg.id = "dlg-text";
    dlg.className = "modal";
    dlg.innerHTML = `<div class="modal-body"><header><h2></h2><button class="x" data-close>×</button></header>
      <textarea rows="16" readonly></textarea></div>`;
    document.body.appendChild(dlg);
    $("[data-close]", dlg).onclick = () => dlg.close();
  }
  $("h2", dlg).textContent = title;
  $("textarea", dlg).value = text;
  dlg.showModal();
  $("textarea", dlg).select();
}

async function deckAction(act) {
  const d = decks.current;
  if (act === "import") return openDeckForm("import");
  if (act === "missing") {
    try {
      const res = await fetch(`/api/decks/${d.id}/export?missing=1`, { headers: { Authorization: "Bearer " + state.token } });
      const text = await res.text();
      if (!text.trim()) return toast("Es fehlen keine Karten 🎉", "ok");
      try { await navigator.clipboard.writeText(text); toast("Fehlende Karten in die Zwischenablage kopiert", "ok"); }
      catch (_) { /* Zwischenablage nicht erlaubt */ }
      showText(`Fehlende Karten – ${d.name}`, text);
    } catch (e) { toast(e.message, "err"); }
  }
  if (act === "towish") {
    toast("Suche günstigste Drucke …");
    try {
      const r = await api(`/api/decks/${d.id}/to-wishlist`, { method: "POST" });
      toast(`${r.added.length} Karten auf die Wunschliste gesetzt`, "ok");
      if (typeof refreshWishBadge === "function") refreshWishBadge();
    } catch (e) { toast(e.message, "err"); }
  }
  if (act === "rename") {
    const name = prompt("Neuer Name", d.name);
    if (name && name.trim()) {
      decks.current = await api(`/api/decks/${d.id}`, { method: "PATCH", json: { name: name.trim() } });
      renderDeck(decks.current);
      refreshDeckSummary();
    }
  }
  if (act === "delete") {
    if (!confirm(`Deck „${d.name}“ löschen? (Die Karten bleiben in der Sammlung.)`)) return;
    await api(`/api/decks/${d.id}`, { method: "DELETE" });
    decks.current = null;
    loadDecks();
  }
  if (act === "add") {
    const name = $("#deck-add-name").value.trim();
    if (!name) return;
    try {
      decks.current = await api(`/api/decks/${d.id}/cards`, { method: "POST", json: { name, board: $("#deck-add-board").value } });
      renderDeck(decks.current);
      refreshDeckSummary();
      $("#deck-add-name").focus();
    } catch (e) { toast(e.message, "err"); }
  }
}

function openDeckForm(mode) {
  decks.formMode = mode;
  $("#deck-form-title").textContent = mode === "new" ? "Neues Deck" : `Liste einfügen – ${decks.current.name}`;
  $("#deck-name-wrap").classList.toggle("hidden", mode !== "new");
  $("#deck-replace-wrap").classList.toggle("hidden", mode === "new");
  $("#deck-name").value = "";
  $("#deck-list-text").value = "";
  $("#deck-replace").checked = false;
  $("#dlg-deck").showModal();
  (mode === "new" ? $("#deck-name") : $("#deck-list-text")).focus();
}

async function submitDeckForm(ev) {
  ev.preventDefault();
  if (ev.submitter && ev.submitter.value === "cancel") return $("#dlg-deck").close();
  const text = $("#deck-list-text").value;
  const btn = $("#deck-save");
  btn.disabled = true;
  btn.textContent = "Lade Karten …";
  try {
    let errors = [];
    let id;
    if (decks.formMode === "new") {
      const name = $("#deck-name").value.trim();
      if (!name) { toast("Bitte einen Namen eingeben", "err"); return; }
      const r = await api("/api/decks", { method: "POST", json: { name, list: text } });
      errors = r.errors;
      id = r.deck.id;
    } else {
      const r = await api(`/api/decks/${decks.current.id}/import`, { method: "POST", json: { text, replace: $("#deck-replace").checked } });
      errors = r.errors || [];
      id = decks.current.id;
    }
    $("#dlg-deck").close();
    await loadDecks(id);
    if (errors.length) showText("Nicht gefundene Karten", errors.join("\n"));
    else toast("Deck gespeichert", "ok");
  } catch (e) {
    toast(e.message, "err");
  } finally {
    btn.disabled = false;
    btn.textContent = "Speichern";
  }
}

const deckAutocomplete = debounce(async (q) => {
  if (q.length < 2) return;
  try {
    const { data } = await api("/api/autocomplete?q=" + encodeURIComponent(q));
    $("#deck-ac").innerHTML = data.slice(0, 20).map((n) => `<option value="${esc(n)}">`).join("");
  } catch (_) { /* egal */ }
}, 200);

/** Für Kartendetails in der Sammlung: Deck-Auswahl befüllen. */
async function fillDeckSelect(sel) {
  try {
    const list = (await api("/api/decks")).decks;
    sel.innerHTML = list.length ? list.map((d) => `<option value="${d.id}">${esc(d.name)}</option>`).join("")
      : `<option value="">(noch keine Decks)</option>`;
  } catch (_) { /* egal */ }
}

function bindDecks() {
  $$(".tabs button").forEach((b) => b.onclick = () => showTab(b.dataset.tab));
  $("#deck-new").onclick = () => openDeckForm("new");
  $("#deck-form").addEventListener("submit", submitDeckForm);
  $("#deck-list").onclick = (e) => {
    const el = e.target.closest("[data-deck]");
    if (el) openDeck(+el.dataset.deck);
  };
  const main = $("#deck-main");
  main.addEventListener("click", (e) => {
    const a = e.target.closest("[data-dact]");
    if (a) return deckAction(a.dataset.dact);
    const op = e.target.closest("[data-op]");
    if (op) return deckCardOp(op.closest("[data-dc]").dataset.dc, op.dataset.op);
  });
  main.addEventListener("input", (e) => { if (e.target.id === "deck-add-name") deckAutocomplete(e.target.value.trim()); });
  main.addEventListener("keydown", (e) => {
    if (e.target.id === "deck-add-name" && e.key === "Enter") { e.preventDefault(); deckAction("add"); }
  });
  // Kartenbild beim Überfahren anzeigen
  const pv = document.createElement("img");
  pv.style.cssText = "position:fixed;width:240px;border-radius:12px;pointer-events:none;z-index:50;display:none;box-shadow:0 10px 30px rgba(0,0,0,.5)";
  document.body.appendChild(pv);
  main.addEventListener("mouseover", (e) => {
    const n = e.target.closest("[data-img]");
    if (n && n.dataset.img) { pv.src = n.dataset.img; pv.style.display = "block"; }
  });
  main.addEventListener("mouseout", (e) => { if (e.target.closest("[data-img]")) pv.style.display = "none"; });
  main.addEventListener("mousemove", (e) => {
    pv.style.left = Math.min(e.clientX + 24, innerWidth - 260) + "px";
    pv.style.top = Math.max(10, Math.min(e.clientY - 120, innerHeight - 350)) + "px";
  });
  if (["decks", "stats", "wishlist"].includes(store("mtg-tab"))) setTimeout(() => showTab(store("mtg-tab")), 0);
}

function onRevisionChange() {
  if (decksVisible() && decks.current) openDeck(decks.current.id);
  if (!$("#stats-view").classList.contains("hidden") && typeof loadStats === "function") loadStats();
  if (!$("#wish-view").classList.contains("hidden") && typeof loadWishlist === "function") loadWishlist();
  else if (typeof refreshWishBadge === "function") refreshWishBadge();
}

bindDecks();

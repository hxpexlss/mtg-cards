"use strict";
/* MTG Cards – Wunschliste */

const wish = { items: [] };
const fmtEur = (v) => v == null ? "–" : v.toLocaleString("de-DE", { style: "currency", currency: "EUR" });

async function loadWishlist() {
  let r;
  try { r = await api("/api/wishlist"); } catch (e) { return toast(e.message, "err"); }
  wish.items = r.items;
  setWishBadge(r.alerts);
  renderWishlist(r);
}

function setWishBadge(n) {
  const b = $('.tabs button[data-tab="wishlist"]');
  if (b) b.innerHTML = `Wunschliste${n ? ` <span class="badge-n" title="Zielpreis erreicht">${n}</span>` : ""}`;
}

async function refreshWishBadge() {
  try { setWishBadge((await api("/api/wishlist")).alerts); } catch (_) { /* egal */ }
}

function renderWishlist(r) {
  const box = $("#wish-main");
  box.innerHTML = `
    <div class="deck-head">
      <h2>Wunschliste</h2>
      <span class="muted">${r.items.length} Karten · aktuell ${esc(fmtEur(r.total_eur))}</span>
      <span class="spacer"></span>
      <button class="btn small" data-wact="refresh">⟳ Preise prüfen</button>
      ${r.items.length ? `<button class="btn small primary" data-wact="proxies">🖨 Proxies drucken (PDF)</button>` : ""}
    </div>
    <form class="wish-add" id="wish-add" autocomplete="off">
      <input id="wish-name" list="wish-ac" placeholder="Karte (Name) …" required>
      <datalist id="wish-ac"></datalist>
      <input id="wish-qty" type="number" min="1" value="1" title="Anzahl" style="width:70px">
      <input id="wish-max" placeholder="Zielpreis €" title="Hinweis, sobald der Preis darunter fällt" style="width:120px">
      <label class="check" style="margin:0"><input type="checkbox" id="wish-foil"> Foil</label>
      <button class="btn primary">＋ Wünschen</button>
    </form>
    <p class="muted small">Preise werden täglich geprüft (günstigster Druck, Cardmarket-Trend). Sobald eine Karte den Zielpreis
      erreicht, wird sie markiert und die Handy-App meldet sich. Scannst du eine gewünschte Karte ein, wird der Wunsch automatisch erfüllt.</p>
    ${r.items.length ? `<table class="list wish-table"><thead><tr>
      <th><input type="checkbox" id="wish-all" title="Alle auswählen"></th><th></th><th>Karte</th><th>Anzahl</th><th>Zielpreis</th><th>Aktuell</th><th>Status</th><th></th></tr></thead><tbody>
      ${r.items.map((w) => `<tr data-wid="${w.id}" class="${w.target_reached ? "reached" : ""}">
        <td><input type="checkbox" class="wish-sel" title="Für Proxies auswählen"></td>
        <td>${w.image_url ? `<img class="thumb" src="${esc(w.image_url)}" alt="" data-img="${esc(w.image_url)}" data-wview="1">` : ""}</td>
        <td><b class="wish-name" data-wview="1">${esc(w.name)}</b>${w.foil ? " ✦" : ""}
          <div class="muted small"><a href="#" data-wop="print" title="Druck wählen – für Proxies in dieser Edition/Sprache und den passenden Preis">${w.any_print ? "beliebiger Druck" : esc(w.set_code + " #" + w.collector_number)} ✎</a>${w.notes ? " · " + esc(w.notes) : ""}${w.owned ? ` · ${w.owned} bereits in der Sammlung` : ""}</div></td>
        <td><span class="qty"><button class="btn small" data-wop="dec">−</button><b>${w.quantity}</b><button class="btn small" data-wop="inc">＋</button></span></td>
        <td><input class="wish-target" value="${w.max_price_eur == null ? "" : String(w.max_price_eur).replace(".", ",")}" placeholder="–" style="width:90px"> €</td>
        <td>${esc(fmtEur(w.price_eur))}${w.price_set && w.any_print ? `<div class="muted small">${esc(w.price_set)}</div>` : ""}</td>
        <td>${w.target_reached ? `<span class="pill ok">✓ Zielpreis erreicht</span>` : (w.max_price_eur != null && w.price_eur != null
          ? `<span class="muted small">noch ${esc(fmtEur(w.price_eur - w.max_price_eur))}</span>` : "")}</td>
        <td><button class="btn small danger" data-wop="del" title="Entfernen">✕</button></td>
      </tr>`).join("")}</tbody></table>`
      : `<div class="empty"><p>Noch keine Wünsche. Karten oben eintragen – oder im Deck „Fehlende → Wunschliste“.</p></div>`}`;
}

async function wishOp(id, op) {
  const w = wish.items.find((x) => x.id === +id);
  if (op === "print") return chooseWishPrint(w);
  try {
    if (op === "del") await api(`/api/wishlist/${id}`, { method: "DELETE" });
    if (op === "inc") await api(`/api/wishlist/${id}`, { method: "PATCH", json: { quantity: w.quantity + 1 } });
    if (op === "dec") await api(`/api/wishlist/${id}`, { method: "PATCH", json: { quantity: w.quantity - 1 } });
    loadWishlist();
  } catch (e) { toast(e.message, "err"); }
}

const wishAutocomplete = debounce(async (q) => {
  if (q.length < 2) return;
  try {
    const { data } = await api("/api/autocomplete?q=" + encodeURIComponent(q));
    $("#wish-ac").innerHTML = data.slice(0, 20).map((n) => `<option value="${esc(n)}">`).join("");
  } catch (_) { /* egal */ }
}, 200);

/** Druck eines Wunsches wählen: Edition + Sprache (für Proxies und den richtigen Preis) oder "beliebig". */
async function chooseWishPrint(w) {
  let dlg = $("#dlg-wprint");
  if (!dlg) {
    dlg = document.createElement("dialog");
    dlg.id = "dlg-wprint";
    dlg.className = "modal";
    document.body.appendChild(dlg);
  }
  dlg.innerHTML = `<form method="dialog" class="modal-body" id="wp-form">
    <header><h2>Druck wählen – ${esc(w.name)}</h2><button type="button" class="x" data-close>×</button></header>
    <p class="muted small">Der gewählte Druck wird für den Preis (inkl. Zielpreis-Alarm) und für die Proxy-PDF verwendet.
      „Beliebig“ nimmt immer den günstigsten Druck.</p>
    <div class="row">
      <label>Sprache <select id="wp-lang"><option value="">Englisch</option>
        ${Object.entries(LANG_NAMES).filter(([k]) => k !== "en").map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("")}</select></label>
    </div>
    <div class="wp-list" id="wp-list"><p class="muted">Lade Drucke …</p></div>
    <footer><button type="button" class="btn" id="wp-any">Beliebig (günstigster)</button><span class="spacer"></span>
      <button type="button" class="btn" data-close>Abbrechen</button>
      <button class="btn primary" id="wp-ok" value="default">Übernehmen</button></footer>
  </form>`;
  let chosen = w.any_print ? null : w.scryfall_id;
  const load = async () => {
    const list = $("#wp-list", dlg);
    list.innerHTML = `<p class="muted">Lade Drucke …</p>`;
    try {
      const lang = $("#wp-lang", dlg).value;
      const { data } = await api(`/api/prints?name=${encodeURIComponent(w.name)}${lang ? "&lang=" + lang : ""}`);
      list.innerHTML = data.length ? data.slice().reverse().map((p) => `
        <label class="wp-item ${p.scryfall_id === chosen ? "active" : ""}" data-img="${esc(p.image_url || "")}">
          <input type="radio" name="wp" value="${esc(p.scryfall_id)}" ${p.scryfall_id === chosen ? "checked" : ""}>
          ${p.image_url ? `<img src="${esc(p.image_url)}" alt="" loading="lazy">` : ""}
          <span><b>${esc(p.set_name)}</b> (${esc(p.set_code)}) #${esc(p.collector_number)}
            <span class="muted small">${p.released_at ? esc(p.released_at.slice(0, 4)) : ""}${p.artist ? " · " + esc(p.artist) : ""}</span></span>
          <span class="spacer"></span><b>${p.price_eur ? esc(p.price_eur) + " €" : (p.price_usd ? "$" + esc(p.price_usd) : "–")}</b>
        </label>`).join("") : `<p class="muted">Keine Drucke in dieser Sprache.</p>`;
    } catch (e) { list.innerHTML = `<p class="muted">${esc(e.message)}</p>`; }
  };
  $$("[data-close]", dlg).forEach((b) => { b.onclick = () => dlg.close(); });
  $("#wp-lang", dlg).onchange = load;
  $("#wp-list", dlg).onchange = (e) => {
    chosen = e.target.value;
    $$(".wp-item", dlg).forEach((l) => l.classList.toggle("active", $("input", l).checked));
  };
  const save = async (body) => {
    try {
      const r = await api(`/api/wishlist/${w.id}`, { method: "PATCH", json: body });
      toast(r.any_print ? `${w.name}: beliebiger Druck` : `${w.name}: ${r.set_code} #${r.collector_number}`, "ok");
      dlg.close();
      loadWishlist();
    } catch (e) { toast(e.message, "err"); }
  };
  $("#wp-any", dlg).onclick = () => save({ any_print: true });
  $("#wp-form", dlg).addEventListener("submit", (e) => {
    e.preventDefault();
    if (!chosen) return toast("Bitte einen Druck auswählen", "err");
    save({ scryfall_id: chosen });
  });
  dlg.showModal();
  load();
}

/** Kartenansicht für einen Wunsch: großes Bild, Regeltext, Preise. */
async function showWishCard(id) {
  const w = wish.items.find((x) => x.id === id);
  if (!w) return;
  let dlg = $("#dlg-wish");
  if (!dlg) {
    dlg = document.createElement("dialog");
    dlg.id = "dlg-wish";
    dlg.className = "modal wide";
    document.body.appendChild(dlg);
  }
  const render = (c) => {
    const text = c && c.oracle_text ? `<div class="oracle">${oracleHtml(c.oracle_text)}</div>` : "";
    dlg.innerHTML = `<div class="modal-body">
      <header><h2>${esc(w.name)}${w.foil ? " ✦" : ""} ${manaHtml((c && c.mana_cost) || w.mana_cost)}</h2><button class="x" data-close>×</button></header>
      <div class="card-detail">
        <div>${(w.image_url || (c && c.image_url)) ? `<img src="${esc(w.image_url || c.image_url)}" alt="">` : ""}</div>
        <div>
          <div class="typeline">${esc((c && c.type_line) || w.type_line || "")}</div>
          ${text}
          <dl class="kv">
            <dt>Aktueller Preis</dt><dd>${esc(fmtEur(w.price_eur))}${w.any_print && w.price_set ? ` <span class="muted">(günstigster Druck: ${esc(w.price_set)})</span>` : ""}</dd>
            <dt>Zielpreis</dt><dd>${w.max_price_eur == null ? "–" : esc(fmtEur(w.max_price_eur))} ${w.target_reached ? `<span class="pill ok">✓ erreicht</span>` : ""}</dd>
            <dt>Gewünscht</dt><dd>${w.quantity}×${w.owned ? ` · ${w.owned} bereits in der Sammlung` : ""}</dd>
            <dt>Druck</dt><dd>${w.any_print ? "beliebig (günstigster)" : esc(w.set_code + " #" + w.collector_number)}
              <button class="btn small" id="wd-print">Druck wählen</button></dd>
            ${c && c.color_identity !== undefined ? `<dt>Farbidentität</dt><dd>${ciHtml(c.color_identity)}</dd>` : ""}
            ${w.notes ? `<dt>Notiz</dt><dd>${esc(w.notes)}</dd>` : ""}
          </dl>
          ${c && c.scryfall_uri ? `<a class="btn" href="${esc(c.scryfall_uri)}" target="_blank" rel="noopener">Auf Scryfall öffnen ↗</a>` : ""}
        </div>
      </div></div>`;
  };
  render(null);
  dlg.onclick = (e) => {
    if (e.target.id === "wd-print") { dlg.close(); chooseWishPrint(w); }
    else if (e.target === dlg || e.target.closest("[data-close]")) dlg.close();
  };
  if (!dlg.open) dlg.showModal();
  try {
    const q = w.any_print ? "name=" + encodeURIComponent(w.name) : "id=" + encodeURIComponent(w.scryfall_id);
    render(await api("/api/lookup?" + q));
  } catch (_) { /* ohne Regeltext anzeigen */ }
}

function bindWishlist() {
  const box = $("#wish-main");
  box.addEventListener("submit", async (e) => {
    if (e.target.id !== "wish-add") return;
    e.preventDefault();
    const btn = $("button", e.target);
    btn.disabled = true;
    try {
      const w = await api("/api/wishlist", { method: "POST", json: {
        name: $("#wish-name").value.trim(), quantity: +$("#wish-qty").value || 1,
        max_price_eur: $("#wish-max").value.trim(), foil: $("#wish-foil").checked } });
      toast(`${w.name} auf der Wunschliste${w.price_eur != null ? " (aktuell " + fmtEur(w.price_eur) + ")" : ""}`, "ok");
      await loadWishlist();
      $("#wish-name").focus();
    } catch (err) { toast(err.message, "err"); btn.disabled = false; }
  });
  box.addEventListener("click", async (e) => {
    if (e.target.closest("[data-wview]")) return showWishCard(+e.target.closest("[data-wid]").dataset.wid);
    const op = e.target.closest("[data-wop]");
    if (op) { e.preventDefault(); return wishOp(op.closest("[data-wid]").dataset.wid, op.dataset.wop); }
    const a = e.target.closest("[data-wact]");
    if (a && a.dataset.wact === "proxies") {
      const ids = $$(".wish-sel:checked").map((c) => +c.closest("[data-wid]").dataset.wid);
      const sel = ids.length ? wish.items.filter((w) => ids.includes(w.id)) : wish.items;
      const n = sel.reduce((s, w) => s + w.quantity, 0);
      openProxyDialog({ title: "Proxies aus der Wunschliste", url: "/api/wishlist/proxies.pdf", ids,
        info: `${ids.length ? "Ausgewählt" : "Alle"}: ${sel.length} Karten, ${n} Exemplare (≈ ${Math.ceil(n / 9)} ${Math.ceil(n / 9) === 1 ? "Seite" : "Seiten"})` });
      return;
    }
    if (e.target.id === "wish-all") {
      $$(".wish-sel").forEach((c) => { c.checked = e.target.checked; });
      return;
    }
    if (a && a.dataset.wact === "refresh") {
      a.disabled = true;
      a.textContent = "Prüfe Preise …";
      try {
        const r = await api("/api/wishlist/refresh", { method: "POST" });
        toast(`${r.updated} Preise aktualisiert`, "ok");
      } catch (err) { toast(err.message, "err"); }
      loadWishlist();
    }
  });
  box.addEventListener("change", async (e) => {
    if (!e.target.classList.contains("wish-target")) return;
    const id = e.target.closest("[data-wid]").dataset.wid;
    try {
      await api(`/api/wishlist/${id}`, { method: "PATCH", json: { max_price_eur: e.target.value.trim() } });
      loadWishlist();
    } catch (err) { toast(err.message, "err"); }
  });
  box.addEventListener("input", (e) => { if (e.target.id === "wish-name") wishAutocomplete(e.target.value.trim()); });
  // Kartenbild beim Überfahren groß anzeigen
  const pv = document.createElement("img");
  pv.style.cssText = "position:fixed;width:240px;border-radius:12px;pointer-events:none;z-index:50;display:none;box-shadow:0 10px 30px rgba(0,0,0,.5)";
  document.body.appendChild(pv);
  box.addEventListener("mouseover", (e) => {
    const t = e.target.closest("[data-img]");
    if (t && t.dataset.img) { pv.src = t.dataset.img; pv.style.display = "block"; }
  });
  box.addEventListener("mouseout", (e) => { if (e.target.closest("[data-img]")) pv.style.display = "none"; });
  box.addEventListener("mousemove", (e) => {
    pv.style.left = Math.min(e.clientX + 24, innerWidth - 260) + "px";
    pv.style.top = Math.max(10, Math.min(e.clientY - 120, innerHeight - 350)) + "px";
  });
  refreshWishBadge();
}

bindWishlist();

"use strict";
/* MTG Cards – Statistik-Ansicht (einfarbige SVG-Diagramme mit Tooltips, ohne externe Bibliotheken) */

const eur = (v) => (v || 0).toLocaleString("de-DE", { style: "currency", currency: "EUR" });
const num = (v) => (v || 0).toLocaleString("de-DE");
const RARITY = { common: "Common", uncommon: "Uncommon", rare: "Rare", mythic: "Mythic", special: "Special", bonus: "Bonus" };
const TYPES = { Creature: "Kreaturen", Planeswalker: "Planeswalker", Battle: "Schlachten", Instant: "Spontanzauber",
  Sorcery: "Hexereien", Artifact: "Artefakte", Enchantment: "Verzauberungen", Land: "Länder", Sonstige: "Sonstige" };

let chartTip;
function tip(html, ev) {
  if (!chartTip) {
    chartTip = document.createElement("div");
    chartTip.className = "chart-tip";
    document.body.appendChild(chartTip);
  }
  if (!html) { chartTip.style.display = "none"; return; }
  chartTip.innerHTML = html;
  chartTip.style.display = "block";
  const x = Math.min(ev.clientX + 14, innerWidth - chartTip.offsetWidth - 8);
  const y = Math.max(8, ev.clientY - chartTip.offsetHeight - 12);
  chartTip.style.left = x + "px";
  chartTip.style.top = y + "px";
}

/** Horizontale Balken: rows = [{label(html), value, tip(html)}] */
function hbars(rows, { max } = {}) {
  if (!rows.length) return `<p class="muted small">Keine Daten</p>`;
  const m = max || Math.max(...rows.map((r) => r.value), 1);
  return `<div class="hbars">${rows.map((r, i) => `
    <div class="hbar" data-tip="${esc(r.tip)}">
      <span class="hb-label">${r.label}</span>
      <span class="hb-track"><span class="hb-fill" style="width:${Math.max(1, 100 * r.value / m)}%"></span></span>
      <span class="hb-val">${esc(r.valueText ?? num(r.value))}</span>
    </div>`).join("")}</div>`;
}

/** Senkrechte Balken: rows = [{label, value, tip}] */
function vbars(rows) {
  if (!rows.length) return `<p class="muted small">Keine Daten</p>`;
  const m = Math.max(...rows.map((r) => r.value), 1);
  return `<div class="vbars">${rows.map((r) => `
    <div class="vbar" data-tip="${esc(r.tip)}">
      <span class="vb-val">${r.value ? num(r.value) : ""}</span>
      <span class="vb-col"><span class="vb-fill" style="height:${r.value ? Math.max(2, 100 * r.value / m) : 0}%"></span></span>
      <span class="vb-label">${esc(r.label)}</span>
    </div>`).join("")}</div>`;
}

/** Liniendiagramm für den Wertverlauf (eine Reihe, Fadenkreuz + Tooltip). */
function lineChart(points, width) {
  const W = Math.max(280, Math.round(width || 640)), H = 200, P = { l: 56, r: 12, t: 12, b: 26 };
  const vals = points.map((p) => p.value);
  let lo = Math.min(...vals), hi = Math.max(...vals);
  if (hi === lo) { hi += 1; lo = Math.max(0, lo - 1); }
  const pad = (hi - lo) * 0.1;
  lo = Math.max(0, lo - pad); hi += pad;
  const x = (i) => P.l + (points.length === 1 ? (W - P.l - P.r) / 2 : i * (W - P.l - P.r) / (points.length - 1));
  const y = (v) => P.t + (H - P.t - P.b) * (1 - (v - lo) / (hi - lo));
  const ticks = [lo, (lo + hi) / 2, hi];
  const path = points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.value).toFixed(1)}`).join("");
  const labelIdx = [...new Set([0, Math.floor((points.length - 1) / 2), points.length - 1])];
  return `<svg class="line-chart" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" data-points='${esc(JSON.stringify(points))}'>
    ${ticks.map((t) => `<line class="grid" x1="${P.l}" x2="${W - P.r}" y1="${y(t)}" y2="${y(t)}"/>
      <text class="axis" x="${P.l - 6}" y="${y(t) + 4}" text-anchor="end">${esc(eur(t).replace(/,\d\d/, ""))}</text>`).join("")}
    ${labelIdx.map((i) => `<text class="axis" x="${x(i)}" y="${H - 6}" text-anchor="middle">${esc(points[i].label)}</text>`).join("")}
    <path class="line" d="${path}"/>
    ${points.length < 40 ? points.map((p, i) => `<circle class="dot" cx="${x(i)}" cy="${y(p.value)}" r="3.5"/>`).join("") : ""}
    <line class="cross hidden" y1="${P.t}" y2="${H - P.b}"/>
    <circle class="focus hidden" r="5"/>
    <rect class="hit" x="${P.l}" y="0" width="${W - P.l - P.r}" height="${H}" data-geom='${JSON.stringify({ W, P, lo, hi, H, n: points.length })}'/>
  </svg>`;
}

function bindLineHover(svg) {
  const pts = JSON.parse(svg.dataset.points);
  const hit = svg.querySelector(".hit");
  const g = JSON.parse(hit.dataset.geom);
  const cross = svg.querySelector(".cross");
  const focus = svg.querySelector(".focus");
  hit.addEventListener("mousemove", (ev) => {
    const r = svg.getBoundingClientRect();
    const sx = (ev.clientX - r.left) * g.W / r.width;
    const step = g.n === 1 ? 1 : (g.W - g.P.l - g.P.r) / (g.n - 1);
    const i = Math.max(0, Math.min(g.n - 1, Math.round((sx - g.P.l) / step)));
    const px = g.n === 1 ? g.P.l + (g.W - g.P.l - g.P.r) / 2 : g.P.l + i * step;
    const py = g.P.t + (g.H - g.P.t - g.P.b) * (1 - (pts[i].value - g.lo) / (g.hi - g.lo));
    cross.setAttribute("x1", px); cross.setAttribute("x2", px);
    focus.setAttribute("cx", px); focus.setAttribute("cy", py);
    cross.classList.remove("hidden"); focus.classList.remove("hidden");
    tip(`<b>${esc(pts[i].label)}</b><br>${esc(eur(pts[i].value))} · ${num(pts[i].cards)} Karten`, ev);
  });
  hit.addEventListener("mouseleave", () => { cross.classList.add("hidden"); focus.classList.add("hidden"); tip(null); });
}

function pipsFor(ci) {
  return `<span class="mana">${(ci === "C" ? ["C"] : ci.split("")).map((c) => `<span class="ms ms-${c}">${c}</span>`).join("")}</span>`;
}

async function loadStats() {
  const box = $("#stats-main");
  box.innerHTML = `<p class="muted">Lade Statistik …</p>`;
  let s;
  try { s = await api("/api/stats/detail"); } catch (e) { box.innerHTML = `<p class="muted">${esc(e.message)}</p>`; return; }
  const hist = s.value_history.map((h) => ({ label: new Date(h.day).toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit" }),
    value: h.value_eur, cards: h.cards }));
  const last = s.last_price_refresh ? new Date(s.last_price_refresh).toLocaleString("de-DE") : "noch nie";
  const change = hist.length > 1 ? hist[hist.length - 1].value - hist[0].value : 0;

  box.innerHTML = `
    <div class="deck-stats">
      <div class="stat hero"><b>${eur(s.value_eur)}</b>Wert der Sammlung${s.value_usd ? ` · $${num(Math.round(s.value_usd))}` : ""}</div>
      <div class="stat"><b>${num(s.cards)}</b>Karten</div>
      <div class="stat"><b>${num(s.unique_names)}</b>verschiedene</div>
      <div class="stat"><b>${num(s.foils)}</b>Foils</div>
      <div class="stat"><b>${num(s.set_count)}</b>Editionen</div>
      ${s.without_price ? `<div class="stat"><b>${num(s.without_price)}</b>ohne Preis</div>` : ""}
    </div>
    <div class="stats-grid">
      <section class="panel wide">
        <h3>Wertverlauf ${hist.length > 1 ? `<span class="muted">${change >= 0 ? "▲" : "▼"} ${esc(eur(Math.abs(change)))} seit ${esc(hist[0].label)}</span>` : ""}</h3>
        ${hist.length > 1 ? lineChart(hist, box.clientWidth - 74) : `<p class="muted small">Der Verlauf entsteht automatisch: Preise werden täglich aktualisiert und der Wert gespeichert.</p>`}
        <p class="muted small">Letzte Preis-Aktualisierung: ${esc(last)} · Preise von Scryfall (Cardmarket-Trend in €)</p>
      </section>
      <section class="panel">
        <h3>Manakurve (ohne Länder)</h3>
        ${vbars(s.mana_curve.map((b) => ({ label: b.cmc === 7 ? "7+" : String(b.cmc), value: b.cards,
          tip: `<b>Manawert ${b.cmc === 7 ? "7+" : b.cmc}</b><br>${num(b.cards)} Karten` })))}
      </section>
      <section class="panel">
        <h3>Kartentypen</h3>
        ${hbars(s.by_type.map((b) => ({ label: esc(TYPES[b.key] || b.key), value: b.cards,
          tip: `<b>${esc(TYPES[b.key] || b.key)}</b><br>${num(b.cards)} Karten · ${esc(eur(b.value_eur))}` })))}
      </section>
      <section class="panel">
        <h3>Farbidentität</h3>
        ${hbars(s.by_color_identity.slice(0, 12).map((b) => ({ label: pipsFor(b.key), value: b.cards,
          tip: `<b>${esc(b.key === "C" ? "Farblos" : b.key)}</b><br>${num(b.cards)} Karten · ${esc(eur(b.value_eur))}` })))}
        ${s.by_color_identity.length > 12 ? `<p class="muted small">+ ${s.by_color_identity.length - 12} weitere Kombinationen</p>` : ""}
      </section>
      <section class="panel">
        <h3>Seltenheit</h3>
        ${hbars(s.by_rarity.map((b) => ({ label: esc(RARITY[b.key] || b.key), value: b.cards,
          tip: `<b>${esc(RARITY[b.key] || b.key)}</b><br>${num(b.cards)} Karten · ${esc(eur(b.value_eur))}` })))}
      </section>
      <section class="panel">
        <h3>Häufigste Editionen</h3>
        ${hbars(s.by_set.map((b) => ({ label: `<span title="${esc(b.name)}">${esc(b.key)}</span>`, value: b.cards,
          tip: `<b>${esc(b.name)} (${esc(b.key)})</b><br>${num(b.cards)} Karten · ${esc(eur(b.value_eur))}` })))}
      </section>
      <section class="panel">
        <h3>Hinzugefügt pro Monat</h3>
        ${vbars(s.added_per_month.map((m) => ({ label: m.month.slice(5) + "/" + m.month.slice(2, 4), value: m.cards,
          tip: `<b>${esc(m.month)}</b><br>${num(m.cards)} Karten hinzugefügt` })))}
      </section>
      <section class="panel wide">
        <h3>Wertvollste Karten</h3>
        ${s.top_cards.length ? `<table class="list"><thead><tr><th>Karte</th><th>Edition</th><th>Anzahl</th><th>Stückpreis</th><th>Gesamt</th></tr></thead>
        <tbody>${s.top_cards.map((c) => `<tr data-id="${c.id}" data-img="${esc(c.image_url || "")}">
          <td>${esc(c.name)}${c.foil ? " ✦" : ""}</td><td>${esc(c.set_code)}</td><td>${c.quantity}</td>
          <td>${esc(eur(c.price_eur))}</td><td><b>${esc(eur(c.total_eur))}</b></td></tr>`).join("")}</tbody></table>`
          : `<p class="muted small">Noch keine Preise – unter Import/Export „Alle Karten aktualisieren“.</p>`}
      </section>
    </div>`;

  box.querySelectorAll(".line-chart").forEach(bindLineHover);
}

function bindStats() {
  const box = $("#stats-main");
  box.addEventListener("mousemove", (ev) => {
    const t = ev.target.closest("[data-tip]");
    if (t) tip(t.dataset.tip, ev); else if (!ev.target.closest(".line-chart")) tip(null);
  });
  box.addEventListener("mouseleave", () => tip(null));
  box.addEventListener("click", (ev) => {
    const row = ev.target.closest("tr[data-id]");
    if (row) openCard(row.dataset.id);
  });
}

bindStats();

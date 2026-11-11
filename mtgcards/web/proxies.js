"use strict";
/* MTG Cards – Proxy-PDF-Dialog (Wunschliste und Decks) */

function openProxyDialog({ title, url, ids, info }) {
  let dlg = $("#dlg-proxy");
  if (!dlg) {
    dlg = document.createElement("dialog");
    dlg.id = "dlg-proxy";
    dlg.className = "modal";
    document.body.appendChild(dlg);
  }
  dlg.innerHTML = `<form method="dialog" class="modal-body" id="proxy-form">
    <header><h2>${esc(title)}</h2><button class="x" value="cancel" formnovalidate>×</button></header>
    <p class="muted">${esc(info)} · 9 Karten pro Seite in Originalgröße (63,5 × 88,9 mm), passend für Standard-Sleeves.</p>
    <div class="row">
      <label>Papier <select id="px-paper"><option value="a4">A4</option><option value="letter">US Letter</option></select></label>
      <label>Anzahl <select id="px-copies"><option value="">wie angegeben</option><option value="one">1 je Karte</option></select></label>
      <label>Abstand zwischen Karten <select id="px-gap"><option value="0">kein Abstand (Schnittmarken)</option>
        <option value="1">1 mm</option><option value="2">2 mm</option><option value="3">3 mm</option></select></label>
    </div>
    <label class="check"><input type="checkbox" id="px-cut" checked> Schnittmarken</label>
    <p class="muted small">Beim Drucken <b>„Tatsächliche Größe“ / 100 %</b> wählen (nicht „An Seite anpassen“).
      Doppelseitige Karten erhalten beide Seiten. Nur für Playtests und den privaten Gebrauch.</p>
    <footer><span class="spacer"></span>
      <button class="btn" value="cancel" formnovalidate>Abbrechen</button>
      <button class="btn primary" value="default" id="px-go">PDF erstellen</button></footer>
  </form>`;
  $("#proxy-form", dlg).addEventListener("submit", (ev) => {
    ev.preventDefault();
    if (ev.submitter && ev.submitter.value === "cancel") { dlg.close(); return; }
    const p = new URLSearchParams({ paper: $("#px-paper").value, gap: $("#px-gap").value,
      cut: $("#px-cut").checked ? "1" : "0", token: state.token || "" });
    if ($("#px-copies").value) p.set("copies", $("#px-copies").value);
    if (ids && ids.length) p.set("ids", ids.join(","));
    let link = $("#px-link");
    if (!link) {
      link = document.createElement("a");
      link.id = "px-link";
      link.style.display = "none";
      document.body.appendChild(link);
    }
    link.href = `${url}?${p}`;
    link.download = "proxies.pdf";
    link.click();
    toast("PDF wird erstellt – Kartenbilder werden geladen …");
    dlg.close();
  });
  dlg.showModal();
}

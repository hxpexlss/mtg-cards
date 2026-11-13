"use strict";
/* MTG Cards – Eigene Proxies: Bilder hochladen (Fun-Karten, Alters …), speichern und als PDF drucken */

const custom = { items: [] };
const CARD_PX = { w: 745, h: 1040 };      // ≈ 300 dpi bei 63 × 88 mm

function customImageUrl(p) {
  return `/api/custom-proxies/${p.id}/image?v=${encodeURIComponent(p.image_version)}&token=${encodeURIComponent(state.token || "")}`;
}

async function loadCustomProxies() {
  try { custom.items = (await api("/api/custom-proxies")).items; } catch (e) { return toast(e.message, "err"); }
  renderCustomProxies();
}

function renderCustomProxies() {
  const box = $("#custom-main");
  const n = custom.items.reduce((s, p) => s + p.quantity, 0);
  box.innerHTML = `
    <div class="deck-head">
      <h2>Eigene Proxies</h2>
      <span class="muted">${custom.items.length} Karten · ${n} Exemplare</span>
      <span class="spacer"></span>
      ${custom.items.length ? `<label class="check" style="margin:0"><input type="checkbox" id="cp-all"> alle auswählen</label>
        <button class="btn small primary" data-cact="pdf">🖨 Drucken (PDF)</button>` : ""}
    </div>
    <form class="custom-upload" id="cp-form">
      <div class="drop" id="cp-drop">
        <b>Bilder hierher ziehen</b> oder <label class="btn small">Dateien wählen<input type="file" id="cp-file" accept="image/*" multiple hidden></label>
        <div class="muted small">JPEG, PNG, WebP … – wird automatisch ins Kartenformat (63 × 88 mm) gebracht.</div>
      </div>
      <div class="row">
        <label>Name <input id="cp-name" placeholder="Standard: Dateiname"></label>
        <label>Anzahl <input id="cp-qty" type="number" min="1" value="1" style="width:70px"></label>
        <label>Anpassen <select id="cp-fit">
          <option value="cover">Auf Kartenformat zuschneiden</option>
          <option value="contain">Ganzes Bild (weißer Rand)</option></select></label>
      </div>
    </form>
    ${custom.items.length ? `<div class="custom-grid">${custom.items.map((p) => `
      <div class="custom-card" data-cid="${p.id}">
        <label class="sel"><input type="checkbox" class="cp-sel" title="Zum Drucken auswählen"></label>
        <img src="${esc(customImageUrl(p))}" alt="" data-cop="view" loading="lazy">
        <div class="cn" title="${esc(p.notes || "")}">${esc(p.name)}</div>
        <div class="row tight">
          <span class="qty"><button class="btn small" data-cop="dec">−</button><b>${p.quantity}</b><button class="btn small" data-cop="inc">＋</button></span>
          <span class="spacer"></span>
          <button class="btn small" data-cop="rename" title="Umbenennen / Notiz">✎</button>
          <label class="btn small" title="Bild ersetzen">🖼<input type="file" accept="image/*" data-cop="replace" hidden></label>
          <button class="btn small danger" data-cop="del" title="Löschen">✕</button>
        </div>
      </div>`).join("")}</div>`
    : `<div class="empty"><p>Noch keine eigenen Proxies. Lade Bilder von Fun-Karten, Alters oder selbst gestalteten Karten hoch –
        sie werden gespeichert und lassen sich wie die Wunschliste als PDF (9 pro Seite) drucken.</p></div>`}`;
}

/** Beliebiges Bild -> JPEG im Kartenformat (Base64), im Browser umgerechnet. */
function imageToCardJpeg(file, fit) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      const c = document.createElement("canvas");
      c.width = CARD_PX.w;
      c.height = CARD_PX.h;
      const g = c.getContext("2d");
      g.fillStyle = "#fff";
      g.fillRect(0, 0, c.width, c.height);
      const scale = fit === "contain" ? Math.min(c.width / img.width, c.height / img.height)
        : Math.max(c.width / img.width, c.height / img.height);
      const w = img.width * scale, h = img.height * scale;
      g.imageSmoothingQuality = "high";
      g.drawImage(img, (c.width - w) / 2, (c.height - h) / 2, w, h);
      URL.revokeObjectURL(url);
      resolve(c.toDataURL("image/jpeg", 0.92));
    };
    img.onerror = () => { URL.revokeObjectURL(url); reject(new Error(`${file.name}: Bild kann nicht gelesen werden`)); };
    img.src = url;
  });
}

async function uploadCustom(files) {
  const list = [...files].filter((f) => f.type.startsWith("image/") || /\.(jpe?g|png|webp|gif|bmp|avif)$/i.test(f.name));
  if (!list.length) return toast("Keine Bilddateien", "err");
  const fit = $("#cp-fit").value;
  const qty = Math.max(1, +$("#cp-qty").value || 1);
  const given = $("#cp-name").value.trim();
  let ok = 0;
  for (const f of list) {
    try {
      const image = await imageToCardJpeg(f, fit);
      const name = (list.length === 1 && given) ? given : (given ? `${given} ${ok + 1}` : f.name.replace(/\.[^.]+$/, ""));
      await api("/api/custom-proxies", { method: "POST", json: { name, image, quantity: qty } });
      ok++;
    } catch (e) { toast(e.message, "err"); }
  }
  if (ok) toast(`${ok} ${ok === 1 ? "Bild" : "Bilder"} gespeichert`, "ok");
  loadCustomProxies();
}

async function customOp(id, op, target) {
  const p = custom.items.find((x) => x.id === +id);
  if (!p) return;
  try {
    if (op === "inc" || op === "dec") {
      if (op === "dec" && p.quantity <= 1) return;
      await api(`/api/custom-proxies/${id}`, { method: "PATCH", json: { quantity: p.quantity + (op === "inc" ? 1 : -1) } });
    } else if (op === "del") {
      if (!confirm(`„${p.name}“ löschen?`)) return;
      await api(`/api/custom-proxies/${id}`, { method: "DELETE" });
    } else if (op === "rename") {
      const name = prompt("Name", p.name);
      if (name === null) return;
      const notes = prompt("Notiz (optional)", p.notes || "");
      await api(`/api/custom-proxies/${id}`, { method: "PATCH", json: { name, notes: notes ?? p.notes } });
    } else if (op === "replace") {
      const f = target.files && target.files[0];
      if (!f) return;
      const image = await imageToCardJpeg(f, $("#cp-fit").value);
      await api(`/api/custom-proxies/${id}`, { method: "PATCH", json: { image } });
      toast("Bild ersetzt", "ok");
    } else if (op === "view") {
      return window.open(customImageUrl(p), "_blank");
    }
    loadCustomProxies();
  } catch (e) { toast(e.message, "err"); }
}

function bindCustomProxies() {
  const box = $("#custom-main");
  box.addEventListener("change", (e) => {
    if (e.target.id === "cp-file") return uploadCustom(e.target.files);
    if (e.target.id === "cp-all") return $$(".cp-sel").forEach((c) => { c.checked = e.target.checked; });
    if (e.target.dataset.cop === "replace") customOp(e.target.closest("[data-cid]").dataset.cid, "replace", e.target);
  });
  box.addEventListener("click", (e) => {
    const op = e.target.closest("[data-cop]");
    if (op && op.dataset.cop !== "replace") return customOp(op.closest("[data-cid]").dataset.cid, op.dataset.cop);
    const a = e.target.closest("[data-cact]");
    if (a && a.dataset.cact === "pdf") {
      const ids = $$(".cp-sel:checked").map((c) => +c.closest("[data-cid]").dataset.cid);
      const sel = ids.length ? custom.items.filter((p) => ids.includes(p.id)) : custom.items;
      const n = sel.reduce((s, p) => s + p.quantity, 0);
      openProxyDialog({ title: "Eigene Proxies drucken", url: "/api/custom-proxies/proxies.pdf", ids,
        info: `${ids.length ? "Ausgewählt" : "Alle"}: ${sel.length} Karten, ${n} Exemplare (≈ ${Math.ceil(n / 9)} ${Math.ceil(n / 9) === 1 ? "Seite" : "Seiten"})` });
    }
  });
  box.addEventListener("submit", (e) => e.preventDefault());
  box.addEventListener("dragover", (e) => { if (e.target.closest("#cp-drop")) { e.preventDefault(); $("#cp-drop").classList.add("over"); } });
  box.addEventListener("dragleave", (e) => { if (e.target.closest("#cp-drop")) $("#cp-drop").classList.remove("over"); });
  box.addEventListener("drop", (e) => {
    if (!e.target.closest("#cp-drop")) return;
    e.preventDefault();
    $("#cp-drop").classList.remove("over");
    uploadCustom(e.dataTransfer.files);
  });
}

bindCustomProxies();

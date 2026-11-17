"use strict";
/* Proxie Maker – Editor: eigenes Artwork, Farben, Rand, unterer Rand (Sammlernummer/Copyright), Texte.
   Alles wird im Browser auf einem Canvas (745 × 1040 px ≈ 300 dpi) berechnet; gespeichert wird das fertige JPEG. */

const W = 745, H = 1040;
const ART_BOXES = {
  modern: { label: "Moderner Rahmen (2003+)", l: 0.082, t: 0.112, r: 0.918, b: 0.557 },
  old: { label: "Alter Rahmen (1993–2003)", l: 0.105, t: 0.104, r: 0.895, b: 0.537 },
  fullart: { label: "Vollbild / randlos", l: 0, t: 0, r: 1, b: 0.62 },
  whole: { label: "Ganze Karte", l: 0, t: 0, r: 1, b: 1 },
};
const DEFAULTS = {
  artBox: { l: 0.082, t: 0.112, r: 0.918, b: 0.557 },
  art: { use: false, zoom: 1, dx: 0, dy: 0, fit: "cover" },
  artFx: { brightness: 0, contrast: 0, saturation: 0, hue: 0 },
  frameFx: { target: "frame", hue: 0, saturation: 0, brightness: 0, contrast: 0, grayscale: false, tint: "#e2a03f", tintAmount: 0 },
  border: { mode: "keep", color: "#000000", width: 0.045 },
  footer: { mode: "keep", text: "Proxy", top: 0.938, bottom: 0.985, spare: true, rightTop: 0.952, gap: 0.06 },
  corners: "border",
  texts: [],
};

const clone = (o) => JSON.parse(JSON.stringify(o));
function withDefaults(s) {
  const out = clone(DEFAULTS);
  for (const k of Object.keys(s || {})) {
    if (out[k] && typeof out[k] === "object" && !Array.isArray(out[k])) Object.assign(out[k], s[k]);
    else out[k] = s[k];
  }
  return out;
}

function loadImage(src) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("Bild konnte nicht geladen werden"));
    img.src = src;
  });
}

// ------------------------------------------------------------------ Farbberechnung
/** 3×3-Matrix für Farbton-Drehung + Sättigung (wie CSS hue-rotate/saturate). */
function colorMatrix(hueDeg, sat) {
  const a = hueDeg * Math.PI / 180, c = Math.cos(a), s = Math.sin(a);
  const h = [0.213 + c * 0.787 - s * 0.213, 0.715 - c * 0.715 - s * 0.715, 0.072 - c * 0.072 + s * 0.928,
    0.213 - c * 0.213 + s * 0.143, 0.715 + c * 0.285 + s * 0.140, 0.072 - c * 0.072 - s * 0.283,
    0.213 - c * 0.213 - s * 0.787, 0.715 - c * 0.715 + s * 0.715, 0.072 + c * 0.928 + s * 0.072];
  const t = [0.213 + 0.787 * sat, 0.715 - 0.715 * sat, 0.072 - 0.072 * sat,
    0.213 - 0.213 * sat, 0.715 + 0.285 * sat, 0.072 - 0.072 * sat,
    0.213 - 0.213 * sat, 0.715 - 0.715 * sat, 0.072 + 0.928 * sat];
  const m = new Array(9);
  for (let r = 0; r < 3; r++) for (let k = 0; k < 3; k++)
    m[r * 3 + k] = t[r * 3] * h[k] + t[r * 3 + 1] * h[3 + k] + t[r * 3 + 2] * h[6 + k];
  return m;
}

function hexRgb(hex) {
  const n = parseInt((hex || "#000000").slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

const isNeutral = (fx) => !fx.hue && !fx.saturation && !fx.brightness && !fx.contrast && !fx.grayscale && !fx.tintAmount;

/** Farbänderungen auf einen Bereich anwenden. inside(x, y) entscheidet pro Pixel. */
function applyFx(data, fx, inside) {
  if (isNeutral(fx)) return;
  const m = colorMatrix(fx.hue || 0, fx.grayscale ? 0 : 1 + (fx.saturation || 0) / 100);
  const br = 1 + (fx.brightness || 0) / 100;
  const ct = 1 + (fx.contrast || 0) / 100;
  const ta = (fx.tintAmount || 0) / 100;
  const [tr, tg, tb] = hexRgb(fx.tint);
  const d = data.data;
  for (let y = 0; y < H; y++) {
    for (let x = 0; x < W; x++) {
      if (!inside(x, y)) continue;
      const i = (y * W + x) * 4;
      let r = d[i], g = d[i + 1], b = d[i + 2];
      const nr = m[0] * r + m[1] * g + m[2] * b, ng = m[3] * r + m[4] * g + m[5] * b, nb = m[6] * r + m[7] * g + m[8] * b;
      r = ((nr * br) - 128) * ct + 128; g = ((ng * br) - 128) * ct + 128; b = ((nb * br) - 128) * ct + 128;
      if (ta) {
        const lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
        r = r * (1 - ta) + tr * lum * ta * 1.15; g = g * (1 - ta) + tg * lum * ta * 1.15; b = b * (1 - ta) + tb * lum * ta * 1.15;
      }
      d[i] = r; d[i + 1] = g; d[i + 2] = b;
    }
  }
}

function sampleColor(ctx, y, x0 = 0.15, x1 = 0.85) {
  const row = ctx.getImageData(Math.round(W * x0), Math.max(0, Math.min(H - 1, Math.round(y))), Math.round(W * (x1 - x0)), 1).data;
  const ch = [[], [], []];
  for (let i = 0; i < row.length; i += 4) if (row[i + 3] > 200) { ch[0].push(row[i]); ch[1].push(row[i + 1]); ch[2].push(row[i + 2]); }
  if (!ch[0].length) return "#000000";
  const med = (a) => a.sort((p, q) => p - q)[a.length >> 1];
  return "#" + ch.map((a) => med(a).toString(16).padStart(2, "0")).join("");
}

function contrastText(hex) {
  const [r, g, b] = hexRgb(hex);
  return (0.299 * r + 0.587 * g + 0.114 * b) > 140 ? "#111111" : "#f2f2f2";
}

/** Komplette Karte rendern. images: {base, art} (Image-Objekte). */
function renderCard(canvas, s, images, opts = {}) {
  canvas.width = W;
  canvas.height = H;
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  const box = { l: s.artBox.l * W, t: s.artBox.t * H, r: s.artBox.r * W, b: s.artBox.b * H };

  // 1. Untergrund für die (transparenten) Ecken, dann das Kartenbild
  ctx.clearRect(0, 0, W, H);
  ctx.drawImage(images.base, 0, 0, W, H);
  const edge = sampleColor(ctx, 6, 0.3, 0.7);
  const cornerColor = s.border.mode === "color" ? s.border.color : (s.corners === "white" ? "#ffffff" : edge);
  ctx.globalCompositeOperation = "destination-over";
  ctx.fillStyle = cornerColor;
  ctx.fillRect(0, 0, W, H);
  ctx.globalCompositeOperation = "source-over";

  // 2. eigenes Artwork in den Bildbereich
  if (s.art.use && images.art && !opts.back) {
    const bw = box.r - box.l, bh = box.b - box.t;
    const fit = (s.art.fit === "contain" ? Math.min : Math.max)(bw / images.art.width, bh / images.art.height) * (s.art.zoom || 1);
    const w = images.art.width * fit, h = images.art.height * fit;
    ctx.save();
    ctx.beginPath();
    ctx.rect(box.l, box.t, bw, bh);
    ctx.clip();
    if (s.art.fit === "contain") { ctx.fillStyle = "#000"; ctx.fillRect(box.l, box.t, bw, bh); }
    ctx.drawImage(images.art, box.l + (bw - w) / 2 + s.art.dx * bw, box.t + (bh - h) / 2 + s.art.dy * bh, w, h);
    ctx.restore();
  }

  // 3. Farben: Rahmen (außerhalb des Bildbereichs) oder ganze Karte; Artwork-Korrekturen im Bildbereich
  const fx = s.frameFx;
  const inBox = (x, y) => x >= box.l && x < box.r && y >= box.t && y < box.b;
  if ((fx.target !== "none" && !isNeutral(fx)) || !isNeutral(s.artFx)) {
    const data = ctx.getImageData(0, 0, W, H);
    if (fx.target === "frame") applyFx(data, fx, (x, y) => !inBox(x, y));
    else if (fx.target === "all") applyFx(data, fx, () => true);
    if (!opts.back) applyFx(data, s.artFx, inBox);
    ctx.putImageData(data, 0, 0);
  }

  // 4. Rand umfärben
  if (s.border.mode === "color") {
    const bw = s.border.width * W;
    ctx.fillStyle = s.border.color;
    ctx.fillRect(0, 0, W, bw);
    ctx.fillRect(0, H - bw, W, bw);
    ctx.fillRect(0, 0, bw, H);
    ctx.fillRect(W - bw, 0, bw, H);
  }

  // 5. Unterer Rand: Sammlernummer, Edition, Künstler, Copyright
  if (s.footer.mode !== "keep") {
    const f = s.footer;
    const top = f.top * H, bottom = f.bottom * H;
    const fill = s.border.mode === "color" ? s.border.color : sampleColor(ctx, Math.min(H - 3, bottom + 3), 0.08, 0.4);
    ctx.fillStyle = fill;
    if (f.spare !== false) {
      // Moderne Rahmen: Nummer/Edition links, Copyright rechts (tiefer). Holo-Stempel in der Mitte und das
      // Stärke-Feld rechts bleiben stehen.
      const gap = (f.gap ?? 0.06) * W;
      const rTop = Math.max(top, (f.rightTop ?? 0.952) * H);
      ctx.fillRect(W * 0.03, top, W / 2 - gap - W * 0.03, bottom - top);
      ctx.fillRect(W / 2 + gap, rTop, W * 0.97 - W / 2 - gap, bottom - rTop);
    } else {
      ctx.fillRect(W * 0.03, top, W * 0.94, bottom - top);
    }
    if (f.mode === "text" && f.text) {
      const h = Math.min(bottom - top, (bottom - (f.spare !== false ? Math.max(top, (f.rightTop ?? 0.952) * H) : top)) * 1.4);
      ctx.fillStyle = contrastText(fill);
      ctx.font = `${Math.max(9, h * 0.55)}px "Segoe UI", system-ui, sans-serif`;
      ctx.textAlign = f.spare !== false ? "left" : "center";
      ctx.textBaseline = "middle";
      ctx.fillText(f.text, f.spare !== false ? W * 0.06 : W / 2, (top + bottom) / 2);
    }
  }

  // 6. eigene Texte
  for (const t of s.texts || []) {
    if (!t.text || (opts.back && !t.both)) continue;
    const size = (t.size || 0.04) * H;
    ctx.font = `${t.bold ? "bold " : ""}${t.italic ? "italic " : ""}${size}px ${t.font || "Georgia, serif"}`;
    ctx.textAlign = t.align || "left";
    ctx.textBaseline = "middle";
    const lines = String(t.text).split("\n");
    const x = t.x * W, y = t.y * H;
    if (t.bg) {
      const wMax = Math.max(...lines.map((l) => ctx.measureText(l).width));
      const pad = size * 0.3;
      const left = t.align === "center" ? x - wMax / 2 : (t.align === "right" ? x - wMax : x);
      ctx.fillStyle = t.bgColor || "#000000";
      ctx.fillRect(left - pad, y - size * 0.6 - pad / 2, wMax + 2 * pad, size * 1.2 * lines.length + pad);
    }
    ctx.fillStyle = t.color || "#ffffff";
    lines.forEach((l, i) => ctx.fillText(l, x, y + i * size * 1.2));
  }
  return canvas;
}

// ------------------------------------------------------------------ Editor-Dialog
const ed = { item: null, s: null, images: {}, side: "front", artData: null, artChanged: false, showOriginal: false };

async function openEditor(item) {
  ed.item = item;
  ed.s = withDefaults(item.settings);
  ed.side = "front";
  ed.artData = null;
  ed.artChanged = false;
  ed.images = {};
  const d = dialog(`<div class="ed">
    <div class="ed-preview">
      <canvas id="ed-canvas" width="${W}" height="${H}"></canvas>
      <div class="row">
        ${item.image_url_back ? `<button class="btn small" id="ed-side">Rückseite zeigen</button>` : ""}
        <button class="btn small" id="ed-orig" title="Gedrückt halten">Original</button>
        <span class="muted small">Artwork: ziehen = verschieben, Mausrad = zoomen</span>
      </div>
    </div>
    <div class="ed-panel">
      <div class="ed-scroll">
        <div class="row" style="margin-bottom:8px"><h3>${esc(item.name)}</h3><button class="x" data-close>×</button></div>
        <details class="sec" open><summary>🎨 Artwork</summary><div>
          <div class="row"><button class="btn small" id="ed-art-up">Eigenes Artwork …</button>
            <button class="btn small" id="ed-art-rm">Original-Artwork</button></div>
          <label class="check"><input type="checkbox" data-k="art.use"> eigenes Artwork verwenden</label>
          <label>Zoom <input type="range" min="0.3" max="4" step="0.01" data-k="art.zoom"></label>
          <div class="two"><label>Einpassen <select data-k="art.fit"><option value="cover">füllen</option><option value="contain">ganz zeigen</option></select></label>
            <label>&nbsp;<button class="btn small" id="ed-art-center">Zentrieren</button></label></div>
          <label>Bildbereich <select id="ed-box">${Object.entries(ART_BOXES).map(([k, v]) => `<option value="${k}">${v.label}</option>`).join("")}<option value="custom">eigener …</option></select></label>
          <div class="two"><label>links <input type="range" min="0" max="0.5" step="0.001" data-k="artBox.l"></label>
            <label>rechts <input type="range" min="0.5" max="1" step="0.001" data-k="artBox.r"></label>
            <label>oben <input type="range" min="0" max="0.5" step="0.001" data-k="artBox.t"></label>
            <label>unten <input type="range" min="0.3" max="1" step="0.001" data-k="artBox.b"></label></div>
          <div class="two"><label>Helligkeit <input type="range" min="-60" max="60" data-k="artFx.brightness"></label>
            <label>Kontrast <input type="range" min="-60" max="60" data-k="artFx.contrast"></label>
            <label>Sättigung <input type="range" min="-100" max="100" data-k="artFx.saturation"></label>
            <label>Farbton <input type="range" min="-180" max="180" data-k="artFx.hue"></label></div>
        </div></details>
        <details class="sec"><summary>🖌 Rahmen & Farben</summary><div>
          <label>Gilt für <select data-k="frameFx.target"><option value="frame">Rahmen (ohne Artwork)</option>
            <option value="all">ganze Karte</option><option value="none">nichts</option></select></label>
          <div class="two"><label>Farbton <input type="range" min="-180" max="180" data-k="frameFx.hue"></label>
            <label>Sättigung <input type="range" min="-100" max="100" data-k="frameFx.saturation"></label>
            <label>Helligkeit <input type="range" min="-60" max="60" data-k="frameFx.brightness"></label>
            <label>Kontrast <input type="range" min="-60" max="60" data-k="frameFx.contrast"></label></div>
          <label class="check"><input type="checkbox" data-k="frameFx.grayscale"> Schwarzweiß</label>
          <div class="two"><label>Einfärben <input type="color" data-k="frameFx.tint"></label>
            <label>Stärke <input type="range" min="0" max="100" data-k="frameFx.tintAmount"></label></div>
        </div></details>
        <details class="sec"><summary>▭ Rand</summary><div>
          <label>Rand <select data-k="border.mode"><option value="keep">wie Original</option><option value="color">Farbe</option></select></label>
          <div class="two"><label>Farbe <input type="color" data-k="border.color"></label>
            <label>Breite <input type="range" min="0.01" max="0.08" step="0.001" data-k="border.width"></label></div>
          <label>Ecken <select data-k="corners"><option value="border">Randfarbe (gerade schneiden)</option><option value="white">weiß</option></select></label>
          <div class="row"><button class="btn small" data-bc="#000000">Schwarz</button><button class="btn small" data-bc="#ffffff">Weiß</button>
            <button class="btn small" data-bc="#b9b9bd">Silber</button><button class="btn small" data-bc="#c9a24a">Gold</button></div>
        </div></details>
        <details class="sec"><summary>✂ Unterer Rand (Nummer, Edition, Copyright)</summary><div>
          <label>Inhalt <select data-k="footer.mode"><option value="keep">wie Original</option>
            <option value="remove">entfernen</option><option value="text">durch eigenen Text ersetzen</option></select></label>
          <label>Text <input data-k="footer.text" placeholder="z.B. Proxy"></label>
          <label class="check"><input type="checkbox" data-k="footer.spare"> Holo-Stempel (Mitte) und Stärke-Feld aussparen</label>
          <div class="two"><label>Bereich oben (links) <input type="range" min="0.88" max="0.99" step="0.001" data-k="footer.top"></label>
            <label>Bereich unten <input type="range" min="0.9" max="1" step="0.001" data-k="footer.bottom"></label>
            <label>Bereich oben (rechts) <input type="range" min="0.9" max="0.99" step="0.001" data-k="footer.rightTop"></label>
            <label>Lücke in der Mitte <input type="range" min="0" max="0.2" step="0.002" data-k="footer.gap"></label></div>
          <p class="muted small">Bei alten Karten (Künstler/Copyright mittig) „aussparen“ ausschalten.</p>
          <p class="muted small">Nur für eigene Proxies (Playtest, eigene Decks) – nicht zum Verkauf oder Tausch.</p>
        </div></details>
        <details class="sec"><summary>🔤 Eigene Texte</summary><div>
          <div id="ed-texts"></div>
          <button class="btn small" id="ed-text-add">＋ Text</button>
          <p class="muted small">Z.B. Signatur, eigener Kartenname (mit Hintergrund über den alten legen) oder Deck-Kennung.</p>
        </div></details>
        <details class="sec"><summary>⭐ Vorlagen</summary><div>
          <div class="row"><select id="ed-preset"><option value="">Vorlage anwenden …</option></select>
            <button class="btn small" id="ed-preset-save">Als Vorlage speichern</button></div>
          <button class="btn small" id="ed-apply-all">Diesen Stil auf ausgewählte / alle Karten der Liste anwenden</button>
          <p class="muted small">Vorlagen speichern Farben, Rand, unteren Rand und Texte – nicht das Artwork.</p>
        </div></details>
      </div>
      <footer><button class="btn" id="ed-reset">Zurücksetzen</button><span class="spacer"></span>
        <button class="btn" data-close>Abbrechen</button><button class="btn primary" id="ed-save">Speichern</button></footer>
    </div></div>`, "modal editor");

  const canvas = $("#ed-canvas", d);
  try {
    ed.images.base = await loadImage(authUrl(`/api/items/${item.id}/base?v=${item.version}`));
    if (item.image_url_back) ed.images.back = await loadImage(authUrl(`/api/items/${item.id}/base?side=back&v=${item.version}`));
    if (item.has_art) ed.images.art = await loadImage(authUrl(`/api/items/${item.id}/art?v=${item.version}`));
  } catch (e) { toast(e.message, "err"); d.close(); return; }

  const draw = () => {
    if (ed.showOriginal) {
      const ctx = canvas.getContext("2d");
      ctx.clearRect(0, 0, W, H);
      ctx.drawImage(ed.side === "back" ? ed.images.back : ed.images.base, 0, 0, W, H);
      return;
    }
    renderCard(canvas, ed.s, { base: ed.side === "back" ? ed.images.back : ed.images.base, art: ed.images.art },
      { back: ed.side === "back" });
  };
  const redraw = (() => { let pending = false; return () => { if (pending) return; pending = true; requestAnimationFrame(() => { pending = false; draw(); }); }; })();

  // Felder <-> Einstellungen
  const getK = (k) => k.split(".").reduce((o, p) => o[p], ed.s);
  const setK = (k, v) => { const ps = k.split("."); const last = ps.pop(); ps.reduce((o, p) => o[p], ed.s)[last] = v; };
  const syncFields = () => {
    $$("[data-k]", d).forEach((el) => {
      const v = getK(el.dataset.k);
      if (el.type === "checkbox") el.checked = !!v; else el.value = v;
    });
    const match = Object.entries(ART_BOXES).find(([, b]) => ["l", "t", "r", "b"].every((k) => Math.abs(b[k] - ed.s.artBox[k]) < 0.002));
    $("#ed-box", d).value = match ? match[0] : "custom";
    renderTexts();
  };
  d.addEventListener("input", (e) => {
    const k = e.target.dataset.k;
    if (!k) return;
    const el = e.target;
    let v = el.type === "checkbox" ? el.checked : el.value;
    if (el.type === "range") v = parseFloat(v);
    setK(k, v);
    if (k === "footer.text" && ed.s.footer.mode === "keep") { ed.s.footer.mode = "text"; syncFields(); }
    if (k === "border.color") ed.s.border.mode = "color";
    redraw();
  });
  $("#ed-box", d).onchange = (e) => {
    const b = ART_BOXES[e.target.value];
    if (b) { ed.s.artBox = { l: b.l, t: b.t, r: b.r, b: b.b }; syncFields(); redraw(); }
  };

  // Texte
  function renderTexts() {
    $("#ed-texts", d).innerHTML = ed.s.texts.map((t, i) => `<div class="txt" data-ti="${i}">
      <textarea rows="2" data-t="text" placeholder="Text">${esc(t.text)}</textarea>
      <div class="two"><label>links/rechts <input type="range" min="0" max="1" step="0.002" data-t="x" value="${t.x}"></label>
        <label>oben/unten <input type="range" min="0" max="1" step="0.002" data-t="y" value="${t.y}"></label>
        <label>Größe <input type="range" min="0.015" max="0.12" step="0.001" data-t="size" value="${t.size}"></label>
        <label>Schrift <select data-t="font">${["Georgia, serif", "\"Segoe UI\", system-ui, sans-serif", "\"Times New Roman\", serif", "\"Courier New\", monospace", "cursive"]
          .map((f) => `<option value='${f}' ${t.font === f ? "selected" : ""}>${f.split(",")[0].replace(/"/g, "")}</option>`).join("")}</select></label>
        <label>Farbe <input type="color" data-t="color" value="${t.color}"></label>
        <label>Ausrichtung <select data-t="align"><option value="left" ${t.align === "left" ? "selected" : ""}>links</option>
          <option value="center" ${t.align === "center" ? "selected" : ""}>Mitte</option><option value="right" ${t.align === "right" ? "selected" : ""}>rechts</option></select></label></div>
      <div class="row"><label class="check"><input type="checkbox" data-t="bold" ${t.bold ? "checked" : ""}> fett</label>
        <label class="check"><input type="checkbox" data-t="italic" ${t.italic ? "checked" : ""}> kursiv</label>
        <label class="check"><input type="checkbox" data-t="bg" ${t.bg ? "checked" : ""}> Hintergrund</label>
        <input type="color" data-t="bgColor" value="${t.bgColor || "#000000"}">
        ${ed.images.back ? `<label class="check"><input type="checkbox" data-t="both" ${t.both ? "checked" : ""}> auch Rückseite</label>` : ""}
        <span class="spacer"></span><button class="btn small danger" data-trm="${i}">✕</button></div></div>`).join("");
  }
  $("#ed-texts", d).addEventListener("input", (e) => {
    const box = e.target.closest("[data-ti]");
    const k = e.target.dataset.t;
    if (!box || !k) return;
    const t = ed.s.texts[+box.dataset.ti];
    t[k] = e.target.type === "checkbox" ? e.target.checked : (e.target.type === "range" ? parseFloat(e.target.value) : e.target.value);
    redraw();
  });
  $("#ed-text-add", d).onclick = () => {
    ed.s.texts.push({ text: "Text", x: 0.5, y: 0.5, size: 0.045, color: "#ffffff", align: "center", font: "Georgia, serif",
      bold: true, italic: false, bg: false, bgColor: "#000000", both: false });
    renderTexts();
    redraw();
  };
  $("#ed-texts", d).addEventListener("click", (e) => {
    if (e.target.dataset.trm === undefined) return;
    ed.s.texts.splice(+e.target.dataset.trm, 1);
    renderTexts();
    redraw();
  });

  // Artwork
  $("#ed-art-up", d).onclick = async () => {
    const [f] = await pickFiles();
    if (!f) return;
    try {
      ed.artData = await fileToJpeg(f, 2400, 0.93);
      ed.images.art = await loadImage(ed.artData);
      ed.artChanged = true;
      Object.assign(ed.s.art, { use: true, zoom: 1, dx: 0, dy: 0 });
      syncFields();
      redraw();
    } catch (err) { toast(err.message, "err"); }
  };
  $("#ed-art-rm", d).onclick = () => { ed.s.art.use = false; syncFields(); redraw(); };
  $("#ed-art-center", d).onclick = () => { Object.assign(ed.s.art, { zoom: 1, dx: 0, dy: 0 }); syncFields(); redraw(); };
  $$("[data-bc]", d).forEach((b) => { b.onclick = () => { ed.s.border.mode = "color"; ed.s.border.color = b.dataset.bc; syncFields(); redraw(); }; });

  // Artwork verschieben (ziehen) und zoomen (Mausrad / zwei Finger)
  let drag = null;
  canvas.addEventListener("pointerdown", (e) => {
    if (!ed.s.art.use || ed.side === "back") return;
    canvas.setPointerCapture(e.pointerId);
    drag = { x: e.clientX, y: e.clientY, dx: ed.s.art.dx, dy: ed.s.art.dy };
  });
  canvas.addEventListener("pointermove", (e) => {
    if (!drag) return;
    const rect = canvas.getBoundingClientRect();
    const bw = (ed.s.artBox.r - ed.s.artBox.l) * rect.width, bh = (ed.s.artBox.b - ed.s.artBox.t) * rect.height;
    ed.s.art.dx = drag.dx + (e.clientX - drag.x) / bw;
    ed.s.art.dy = drag.dy + (e.clientY - drag.y) / bh;
    redraw();
  });
  canvas.addEventListener("pointerup", () => { drag = null; });
  canvas.addEventListener("wheel", (e) => {
    if (!ed.s.art.use) return;
    e.preventDefault();
    ed.s.art.zoom = Math.max(0.3, Math.min(4, ed.s.art.zoom * (e.deltaY < 0 ? 1.06 : 1 / 1.06)));
    syncFields();
    redraw();
  }, { passive: false });

  // Ansicht
  const orig = $("#ed-orig", d);
  const on = () => { ed.showOriginal = true; draw(); }, off = () => { ed.showOriginal = false; draw(); };
  orig.addEventListener("pointerdown", on);
  orig.addEventListener("pointerup", off);
  orig.addEventListener("pointerleave", off);
  if ($("#ed-side", d)) $("#ed-side", d).onclick = (e) => {
    ed.side = ed.side === "front" ? "back" : "front";
    e.target.textContent = ed.side === "front" ? "Rückseite zeigen" : "Vorderseite zeigen";
    draw();
  };

  // Vorlagen
  const loadPresets = async () => {
    try {
      const { presets } = await api("/api/presets");
      ed.presets = presets;
      $("#ed-preset", d).innerHTML = `<option value="">Vorlage anwenden …</option>` +
        presets.map((p, i) => `<option value="${i}">${esc(p.name)}</option>`).join("");
    } catch (_) { /* egal */ }
  };
  loadPresets();
  $("#ed-preset", d).onchange = (e) => {
    const p = ed.presets[+e.target.value];
    if (!p) return;
    const keepArt = { art: ed.s.art, artBox: ed.s.artBox };
    ed.s = withDefaults(Object.assign({}, p.settings, keepArt));
    syncFields();
    redraw();
  };
  $("#ed-preset-save", d).onclick = async () => {
    const name = prompt("Name der Vorlage");
    if (!name) return;
    const st = clone(ed.s);
    delete st.art;
    await api("/api/presets", { method: "POST", json: { name, settings: st } });
    toast("Vorlage gespeichert", "ok");
    loadPresets();
  };
  $("#ed-apply-all", d).onclick = () => applyToMany(d);

  $("#ed-reset", d).onclick = () => {
    ed.s = withDefaults({});
    ed.images.art = null;
    ed.artChanged = false;
    syncFields();
    redraw();
  };
  $("#ed-save", d).onclick = async (e) => {
    e.target.disabled = true;
    e.target.textContent = "Speichere …";
    try {
      await saveItem(ed.item, ed.s, ed.images, ed.artChanged ? ed.artData : null);
      toast(`${item.name} gespeichert`, "ok");
      d.close();
      reloadProject();
    } catch (err) { toast(err.message, "err"); e.target.disabled = false; e.target.textContent = "Speichern"; }
  };

  syncFields();
  draw();
}

/** Rendern und speichern (Vorder- und ggf. Rückseite). */
async function saveItem(item, s, images, artData) {
  if (artData) await api(`/api/items/${item.id}/art`, { method: "PUT", json: { image: artData } });
  const c = document.createElement("canvas");
  const front = renderCard(c, s, images).toDataURL("image/png");      // verlustfrei
  const body = { front, settings: s };
  if (images.back) body.back = renderCard(c, s, { base: images.back }, { back: true }).toDataURL("image/png");
  await api(`/api/items/${item.id}/rendered`, { method: "PUT", json: body });
}

/** Aktuellen Stil (ohne Artwork) auf weitere Karten der Liste anwenden – Rendern im Browser, nacheinander. */
async function applyToMany(dlg) {
  const ids = selectedIds();
  const targets = state.current.items.filter((i) => i.id !== ed.item.id && (!ids.length || ids.includes(i.id)));
  if (!targets.length) return toast("Keine weiteren Karten", "err");
  if (!confirm(`Stil (Farben, Rand, unterer Rand, Texte) auf ${targets.length} Karten anwenden?\nEigenes Artwork der Karten bleibt erhalten.`)) return;
  const style = clone(ed.s);
  let done = 0;
  for (const it of targets) {
    try {
      const own = withDefaults(it.settings);
      const s = withDefaults(Object.assign({}, style, { art: own.art, artBox: it.has_art ? own.artBox : style.artBox, artFx: own.artFx }));
      const images = { base: await loadImage(authUrl(`/api/items/${it.id}/base?v=${it.version}`)) };
      if (it.image_url_back) images.back = await loadImage(authUrl(`/api/items/${it.id}/base?side=back&v=${it.version}`));
      if (it.has_art && s.art.use) images.art = await loadImage(authUrl(`/api/items/${it.id}/art?v=${it.version}`));
      await saveItem(it, s, images, null);
      done++;
      toast(`Stil angewendet: ${done}/${targets.length}`);
    } catch (err) { toast(`${it.name}: ${err.message}`, "err"); }
  }
  toast(`Fertig – ${done} Karten`, "ok");
  if (dlg) dlg.close();
  reloadProject();
}

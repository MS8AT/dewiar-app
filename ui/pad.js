/* Блокнот у виджета: вкладки, правка «как выглядит», сохранение само (core/pad.py — команды pad_*), правки с других
   устройств — событие pad_changed (sync.py). Окно — ui/app.py (pad_open / pad_hide / pad_toggle). */
const $ = (s) => document.querySelector(s), $$ = (s) => [...document.querySelectorAll(s)];
const Q = new URLSearchParams(location.search);
const ED = $("#ed");
const P = { tabs: [], active: "", base: null, dirty: false, saving: false, loaded: false, t: 0, imgCache: {} };

/* ---------- тема и «выезд» ---------- */
function skin(id) {
  const sk = window.dewiarSkin ? dewiarSkin(id) : { id: "brand" };
  document.body.className = document.body.className.replace(/\b(skin-\S+|light|neu)\b/g, "").trim();
  document.body.classList.add("skin-" + sk.id);
  if (sk.light) document.body.classList.add("light");
  if (sk.neu) document.body.classList.add("neu");
  document.documentElement.style.background = getComputedStyle(document.body).getPropertyValue("--paper").trim() || (sk.light ? "#e7edf6" : "#12131b");
}
skin(Q.get("skin") || "");
window.padSide = (side) => { document.body.classList.toggle("side-left", side !== "right"); document.body.classList.toggle("side-right", side === "right"); };
/* окно = лист + зазор до виджета; в зазоре — защёлки (ui/app.py _pad_geom: side, gap, clips [[y, высота]]) */
window.padCfg = (c) => {
  c = c || {}; padSide(c.side || "left");
  const gap = +c.gap || 0, st = document.documentElement.style;
  st.setProperty("--gap-l", (c.side === "right" ? gap : 0) + "px"); st.setProperty("--gap-r", (c.side === "right" ? 0 : gap) + "px");
  $("#clips").innerHTML = (c.clips || []).map(([y, h]) => `<i class="clip" style="top:${y}px;height:${h}px;width:${gap + 10}px"></i>`).join("");
};
try { padCfg(JSON.parse(Q.get("cfg") || "null") || { side: Q.get("side") || "left" }); } catch (e) { padCfg({ side: Q.get("side") || "left" }); }
window.padShown = (side) => { if (side) padSide(side); document.body.classList.remove("snap"); $("#wrap").classList.add("away");
  requestAnimationFrame(() => requestAnimationFrame(() => { $("#wrap").classList.remove("away"); document.body.classList.add("snap"); }));
  setTimeout(() => ED.focus(), 280); refresh(); };
window.padClose = async () => { await saveNow(); document.body.classList.remove("snap"); setTimeout(() => $("#wrap").classList.add("away"), 90);
  setTimeout(() => { const a = api(); if (a && a.pad_hide) a.pad_hide(); }, 320); };
$("#b-close").onclick = () => padClose();

/* ---------- состояние внизу ---------- */
function status(t, cls) { $("#st").textContent = t; $("#foot").className = cls || ""; }

/* ---------- вкладки ---------- */
function drawTabs() {
  const box = $("#tabs");
  box.innerHTML = "";
  for (const t of P.tabs) {
    const el = document.createElement("div");
    el.className = "tab" + (t.name === P.active ? " on" : ""); el.setAttribute("role", "tab"); el.setAttribute("aria-selected", t.name === P.active);
    el.draggable = true; el.dataset.name = t.name; el.title = t.name + " — двойной щелчок: переименовать; перетащите, чтобы переставить";
    el.innerHTML = `<span></span><button class="x" title="Удалить вкладку" aria-label="Удалить вкладку"><svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6 6 18"/></svg></button>`;
    el.querySelector("span").textContent = t.name;
    el.onclick = (e) => { if (!e.target.closest(".x") && t.name !== P.active) openTab(t.name); };
    el.ondblclick = () => rename(el, t.name);
    el.querySelector(".x").onclick = (e) => { e.stopPropagation(); askDelete(t.name); };
    el.onauxclick = (e) => { if (e.button === 1) askDelete(t.name); };
    el.ondragstart = (e) => { e.dataTransfer.setData("text/x-pad-tab", t.name); e.dataTransfer.effectAllowed = "move"; };
    el.ondragover = (e) => { if ([...e.dataTransfer.types].includes("text/x-pad-tab")) { e.preventDefault(); el.classList.add("drop"); } };
    el.ondragleave = () => el.classList.remove("drop");
    el.ondrop = (e) => { e.preventDefault(); el.classList.remove("drop"); const from = e.dataTransfer.getData("text/x-pad-tab"); if (!from || from === t.name) return;
      const names = P.tabs.map(x => x.name).filter(n => n !== from); names.splice(names.indexOf(t.name), 0, from);
      P.tabs = names.map(n => P.tabs.find(x => x.name === n)); drawTabs(); core.call("pad_order", { names }).catch(() => {}); };
    box.appendChild(el);
  }
  const on = box.querySelector(".tab.on"); if (on) on.scrollIntoView({ block: "nearest", inline: "nearest" });
}
async function refresh() {
  try {
    const r = await core.call("pad_tabs");
    P.tabs = r.tabs; if (!P.active || !P.tabs.some(t => t.name === P.active)) P.active = r.active;
    drawTabs();
    if (!P.loaded) await openTab(P.active, true);
  } catch (e) { status("Нет связи с Dewiar — " + e.message, "bad"); }
}
async function openTab(name, first) {
  if (!first) await saveNow();
  try {
    const r = await core.call("pad_read", { name });
    P.active = r.name; P.base = r.mtime; P.dirty = false; P.loaded = true;
    ED.innerHTML = PadMD.md2html(r.text); paint(); drawTabs();
    status(P.tabs.length > 1 ? `«${r.name}» · сохраняется само, синхронизируется` : "Сохраняется само и синхронизируется с вашими устройствами");
    if (!first) ED.focus();
  } catch (e) { status(e.message, "bad"); P.loaded = true; }
}
$("#b-new").onclick = () => newTab();
async function newTab() {
  await saveNow();
  try { const r = await core.call("pad_new", {}); P.tabs = r.tabs; P.active = r.created; drawTabs(); await openTab(r.created, true); ED.focus(); const el = $(`.tab.on`); if (el) rename(el, r.created); }
  catch (e) { status(e.message, "bad"); }
}
function rename(el, name) {
  const sp = el.querySelector("span"); const inp = document.createElement("input"); inp.value = name; sp.replaceWith(inp); inp.focus(); inp.select();
  let done = false;
  const fin = async (ok) => { if (done) return; done = true; const to = inp.value.trim();
    if (ok && to && to !== name) { try { await saveNow(); const r = await core.call("pad_rename", { name, to }); P.tabs = r.tabs; if (P.active === name) P.active = r.tabs.find(t => t.name === to.replace(/[\\/:*?"<>|#\[\]^]/g, " ").replace(/\s+/g, " ").trim().slice(0, 60))?.name || r.active; }
      catch (e) { status(e.message, "bad"); } }
    drawTabs(); };
  inp.onkeydown = (e) => { if (e.key === "Enter") fin(true); if (e.key === "Escape") fin(false); e.stopPropagation(); };
  inp.onblur = () => fin(true);
}
let askFn = null;
function askDelete(name) {
  $("#ask-t").textContent = P.tabs.length > 1 ? `Удалить вкладку «${name}»? Она уйдёт в корзину Dewiar.` : `Очистить «${name}»? Последнюю вкладку не удаляю.`;
  $("#ask").classList.add("on"); $("#ask-yes").focus();
  askFn = async () => { $("#ask").classList.remove("on");
    try { const r = await core.call("pad_delete", { name }); P.tabs = r.tabs; if (P.active === name || !P.tabs.some(t => t.name === P.active)) { P.loaded = false; P.active = r.active; } drawTabs();
      if (!P.loaded || P.active !== name) await openTab(P.active, true); } catch (e) { status(e.message, "bad"); } };
}
$("#ask-yes").onclick = () => askFn && askFn();
$("#ask-no").onclick = () => $("#ask").classList.remove("on");

/* ---------- сохранение ---------- */
function changed() { P.dirty = true; clearTimeout(P.t); P.t = setTimeout(saveNow, 700); status("Сохраняю…", "busy"); }
async function saveNow() {
  clearTimeout(P.t);
  if (!P.dirty || !P.active || P.saving) return;
  P.saving = true; P.dirty = false;
  const md = PadMD.html2md(ED);
  try {
    const r = await core.call("pad_write", { name: P.active, text: md, base: P.base });
    P.base = r.mtime;
    if (r.conflict) { status(`Её правили и на другом устройстве — их вариант сохранён во вкладке «${r.conflict}»`, "busy"); refresh(); }
    else status("Сохранено · синхронизируется с вашими устройствами");
  } catch (e) { P.dirty = true; status("Не сохранилось: " + e.message, "bad"); }
  P.saving = false;
  if (P.dirty) changed();
}
ED.addEventListener("input", () => { tidy(); ensureP(); changed(); });
ED.addEventListener("focus", ensureP);
window.addEventListener("beforeunload", () => { if (P.dirty) saveNow(); });
core.on("pad_changed", async (e) => {                 // правка с другого устройства
  if (e.deleted || e.name !== P.active) return refresh();
  if (P.dirty || document.activeElement === ED && Date.now() - lastKey < 4000) return;   // сейчас печатают — их вариант не перетирает
  const r = await core.call("pad_read", { name: P.active }).catch(() => null);
  if (r && r.mtime !== P.base) { P.base = r.mtime; ED.innerHTML = PadMD.md2html(r.text); paint(); status("Обновлено с другого устройства"); }
});
core.on("hello", (d) => { try { const u = (d && d.settings && d.settings.ui) || {}; if (u.skin) skin(u.skin); } catch (e) { }
  if (P.loaded) { P.loaded = false; refresh(); } });
core.on("settings", (e) => { try { const u = ((e && e.settings) || e || {}).ui || {}; if (u.skin) skin(u.skin); } catch (x) { } });   // тему сменили в студии        // ядро перезапустилось — перечитать

/* ---------- картинки ---------- */
/* пустой лист — всегда с абзацем: иначе первая строка — голый текст без блока, и «- », «[] » не срабатывают (WebKitGTK) */
function ensureP() {
  if (!ED.firstElementChild || (ED.childNodes.length && [...ED.childNodes].every(n => n.nodeType === 3))) {
    const t = ED.textContent; ED.innerHTML = "<p>" + (t ? t.replace(/</g, "&lt;") : "<br>") + "</p>";
    if (document.activeElement === ED) { const r = document.createRange(); r.selectNodeContents(ED.firstChild); r.collapse(false); const sel = getSelection(); sel.removeAllRanges(); sel.addRange(r); }
  }
  blank();
}
function blank() { ED.classList.toggle("blank", !ED.textContent.trim() && !ED.querySelector("li, img, table, hr, pre")); }
function paint() {
  ensureP();
  for (const img of ED.querySelectorAll("img[data-src]:not([src])")) {
    const link = img.getAttribute("data-src");
    if (/^https?:/i.test(link)) { img.src = link; continue; }
    if (P.imgCache[link]) { img.src = P.imgCache[link]; continue; }
    core.call("pad_file", { link }).then(r => { P.imgCache[link] = r.url; img.src = r.url; }).catch(() => { img.alt = "картинка не найдена: " + link; });
  }
}
async function addImages(files) {
  for (const f of files) {
    if (!/^image\//.test(f.type)) continue;
    status("Кладу картинку…", "busy");
    const b64 = await new Promise((ok, bad) => { const r = new FileReader(); r.onload = () => ok(r.result); r.onerror = bad; r.readAsDataURL(f); });
    try {
      const name = f.name && f.name !== "image.png" ? f.name : "Снимок " + new Date().toLocaleString("ru-RU").replace(/[:/]/g, "-").replace(",", "") + ".png";
      const r = await core.call("pad_attach", { name: P.active, filename: name, b64 });
      const link = r.line.match(/\]\(([^)]+)\)/)[1];
      P.imgCache[link] = b64;
      insertHtml(`<p><img alt="" data-src="${link.replace(/"/g, "&quot;")}" src="${b64}"></p><p><br></p>`);
      changed();
    } catch (e) { status("Картинка не легла: " + e.message, "bad"); }
  }
}
$("#file").onchange = (e) => { addImages([...e.target.files]); e.target.value = ""; };

/* ---------- вставка: картинки, таблицы, ссылки, Markdown ---------- */
function insertHtml(html) { ED.focus(); document.execCommand("insertHTML", false, html); }
ED.addEventListener("paste", (e) => {
  const dt = e.clipboardData; if (!dt) return;
  const imgs = [...dt.files].filter(f => /^image\//.test(f.type));
  if (imgs.length) { e.preventDefault(); addImages(imgs); return; }
  const html = dt.getData("text/html"), text = dt.getData("text/plain");
  e.preventDefault();
  const after = (h) => /<\/(table|pre|ul|ol|blockquote)>$/.test(h) ? h + "<p><br></p>" : h;   // после таблицы и списка — дальше обычной строкой
  if (html && !/^\s*$/.test(html)) { insertHtml(after(PadMD.md2html(PadMD.html2md(html)))); }      // сайт, Word, таблица — в наш вид, лишнее прочь
  else if (/^\s*https?:\/\/\S+\s*$/.test(text)) {
    const sel = getSelection(); const u = text.trim();
    if (sel && !sel.isCollapsed) document.execCommand("createLink", false, u); else insertHtml(`<a href="${u.replace(/"/g, "%22")}">${u.replace(/</g, "&lt;")}</a>&nbsp;`);
  } else if (/(^|\n)\s*([-*+] |\d+[.)] |#{1,3} |\|.*\||```|> )/.test(text) || /\[[^\]]+\]\(|\*\*/.test(text)) insertHtml(after(PadMD.md2html(text)));
  else document.execCommand("insertText", false, text);
  changed();
});
ED.addEventListener("drop", (e) => { const f = [...(e.dataTransfer?.files || [])].filter(x => /^image\//.test(x.type)); if (f.length) { e.preventDefault(); addImages(f); } });

/* ---------- клавиши и Markdown на лету ---------- */
let lastKey = 0;
const block = () => { let n = getSelection().anchorNode; while (n && n !== ED && !(n.nodeType === 1 && /^(P|DIV|H[1-6]|LI|BLOCKQUOTE|PRE)$/.test(n.tagName))) n = n.parentNode; return n === ED ? null : n; };
ED.addEventListener("keydown", (e) => {
  lastKey = Date.now();
  const k = e.key, mod = e.ctrlKey || e.metaKey;
  if (mod && (k === "b" || k === "и")) { e.preventDefault(); cmd("bold"); return; }
  if (mod && (k === "i" || k === "ш")) { e.preventDefault(); cmd("italic"); return; }
  if (mod && (k === "k" || k === "л")) { e.preventDefault(); cmd("link"); return; }
  if (mod && (k === "s" || k === "ы")) { e.preventDefault(); saveNow(); return; }
  if (k === "Tab") { const b = block(); if (b && b.tagName === "LI") { e.preventDefault(); document.execCommand(e.shiftKey ? "outdent" : "indent"); changed(); } else { e.preventDefault(); document.execCommand("insertText", false, "    "); } return; }
  if (k === "Enter" && !e.shiftKey) {
    const b = block();
    if (b && b.tagName === "LI" && b.classList.contains("task")) setTimeout(() => { const n = block(); if (n && n !== b && n.tagName === "LI") { n.classList.add("task"); n.setAttribute("data-done", "0"); } }, 0);
    if (b && b.tagName === "P" && /^```\s*$/.test(b.textContent)) { e.preventDefault(); b.outerHTML = "<pre><code>​</code></pre><p><br></p>"; changed(); return; }
    if (b && b.tagName === "P" && /^(-{3,}|\*{3,})$/.test(b.textContent.trim())) { e.preventDefault(); b.outerHTML = "<hr><p><br></p>"; const p = ED.querySelector("hr + p"); caretIn(p); changed(); return; }
  }
  if (k === " ") {                                   // «- », «1. », «[] », «# », «> » в начале строки
    ensureP();
    const b = block(); if (!b || b.tagName === "PRE") return;
    const sel = getSelection(); if (!sel.rangeCount) return;
    const r = sel.getRangeAt(0);
    const pre = r.cloneRange(); pre.selectNodeContents(b); pre.setEnd(r.endContainer, r.endOffset);
    const t = pre.toString();
    if (!/^(#{1,3}|[-*+]|1[.)]|\[\s?\]|-\s\[\s?\]|>)$/.test(t)) return;
    e.preventDefault();
    shortcut(b, t);
    changed();
  }
});
/* Markdown на лету — сами, через DOM: execCommand в WebKitGTK (Ubuntu) ставил список не туда, а текст оставался рядом */
function shortcut(b, t) {
  let left = t.length;                                // убрать «- » из начала строки
  const tw = document.createTreeWalker(b, NodeFilter.SHOW_TEXT);
  while (left > 0 && tw.nextNode()) { const n = tw.currentNode, k = Math.min(left, n.nodeValue.length); n.nodeValue = n.nodeValue.slice(k); left -= k; }
  const kids = [...b.childNodes].filter(n => !(n.nodeType === 3 && !n.nodeValue) && n.nodeName !== "BR");
  const fill = (el) => { kids.forEach(n => el.appendChild(n)); if (!el.textContent && !el.querySelector("img")) el.appendChild(document.createElement("br")); return el; };
  let target;
  if (b.tagName === "LI") {                           // уже в списке: «[] » — сделать задачей
    if (/\[/.test(t)) { b.classList.add("task"); b.setAttribute("data-done", "0"); }
    target = b;
  } else if (/^#/.test(t)) { target = fill(document.createElement("h" + t.length)); b.replaceWith(target); }
  else if (t === ">") { const q = document.createElement("blockquote"); target = fill(document.createElement("p")); q.appendChild(target); b.replaceWith(q); }
  else {
    const ol = /^1/.test(t), task = /\[/.test(t), li = fill(document.createElement("li"));
    if (task) { li.className = "task"; li.setAttribute("data-done", "0"); }
    const prev = b.previousElementSibling;
    if (prev && prev.tagName === (ol ? "OL" : "UL")) { prev.appendChild(li); b.remove(); }
    else { const list = document.createElement(ol ? "ol" : "ul"); list.appendChild(li); b.replaceWith(list); }
    target = li;
  }
  const rr = document.createRange(), first = (() => { const w = document.createTreeWalker(target, NodeFilter.SHOW_TEXT); return w.nextNode(); })();
  if (first) rr.setStart(first, 0); else rr.setStart(target, 0);
  rr.collapse(true); const sel = getSelection(); sel.removeAllRanges(); sel.addRange(rr);
  blank();
}
document.addEventListener("keydown", (e) => {
  document.body.classList.toggle("ctrl", e.ctrlKey || e.metaKey);
  if (e.key === "Escape") { if ($("#ask").classList.contains("on")) $("#ask").classList.remove("on"); else padClose(); }
  if ((e.ctrlKey || e.metaKey) && (e.key === "t" || e.key === "е")) { e.preventDefault(); newTab(); }
  if ((e.ctrlKey || e.metaKey) && e.key === "Tab") { e.preventDefault(); const i = P.tabs.findIndex(t => t.name === P.active); const n = P.tabs[(i + (e.shiftKey ? -1 : 1) + P.tabs.length) % P.tabs.length]; if (n) openTab(n.name); }
});
document.addEventListener("keyup", (e) => document.body.classList.toggle("ctrl", e.ctrlKey || e.metaKey));
function caretIn(el) { if (!el) return; const r = document.createRange(); r.selectNodeContents(el); r.collapse(true); const s = getSelection(); s.removeAllRanges(); s.addRange(r); }
function makeTasks() {
  const b = block();
  if (!b || b.tagName !== "LI") document.execCommand("insertUnorderedList");
  const li = block(); if (!li || li.tagName !== "LI") return;
  const list = li.parentNode;
  if (list.tagName === "OL") { const ul = document.createElement("ul"); ul.innerHTML = list.innerHTML; list.replaceWith(ul); }
  const cur = block(); if (cur && cur.tagName === "LI") { const on = cur.classList.contains("task"); cur.classList.toggle("task", !on); if (!on) cur.setAttribute("data-done", "0"); else cur.removeAttribute("data-done"); }
}
/* галочка: щелчок по квадратику слева от задачи; ссылка: Ctrl+щелчок — открыть */
ED.addEventListener("mousedown", (e) => {
  const li = e.target.closest && e.target.closest("li.task");
  if (li && e.clientX - li.getBoundingClientRect().left < 22) {
    e.preventDefault(); li.setAttribute("data-done", li.getAttribute("data-done") === "1" ? "0" : "1"); changed();
  }
});
ED.addEventListener("click", (e) => {
  const a = e.target.closest && e.target.closest("a[href]");
  if (a && (e.ctrlKey || e.metaKey)) { e.preventDefault(); const x = api(); const u = a.getAttribute("href"); if (/^https?:/i.test(u)) { if (x && x.open_url) x.open_url(u); else window.open(u, "_blank"); } }
  ED.querySelectorAll("img.sel").forEach(i => i.classList.remove("sel"));
  if (e.target.tagName === "IMG") e.target.classList.add("sel");
});
ED.addEventListener("mouseover", (e) => { $("#hint").textContent = e.target.closest && e.target.closest("a[href]") ? "Ctrl+щелчок — открыть ссылку" : ""; });

/* ---------- панель ---------- */
async function cmd(c) {
  ED.focus();
  if (c === "h1" || c === "h2") { const b = block(); document.execCommand("formatBlock", false, b && b.tagName === c.toUpperCase() ? "p" : c); }
  else if (c === "bold" || c === "italic") document.execCommand(c);
  else if (c === "strike") document.execCommand("strikeThrough");
  else if (c === "ul") document.execCommand("insertUnorderedList");
  else if (c === "ol") document.execCommand("insertOrderedList");
  else if (c === "task") makeTasks();
  else if (c === "link") {
    const s = getSelection(); const txt = s ? s.toString() : ""; const keep = s && s.rangeCount ? s.getRangeAt(0).cloneRange() : null;
    const u = await askText("Адрес ссылки", /^https?:\/\//.test(txt) ? txt : "https://", { ok: "Вставить" }); if (!u || u === "https://") return;
    ED.focus(); if (keep) { s.removeAllRanges(); s.addRange(keep); }              // окно вопроса забрало выделение — вернуть
    if (s && !s.isCollapsed) document.execCommand("createLink", false, u); else insertHtml(`<a href="${u.replace(/"/g, "%22")}">${u.replace(/</g, "&lt;")}</a>&nbsp;`);
  } else if (c === "table") insertHtml("<table><thead><tr><th>Столбец</th><th>Столбец</th></tr></thead><tbody><tr><td><br></td><td><br></td></tr><tr><td><br></td><td><br></td></tr></tbody></table><p><br></p>");
  else if (c === "image") { $("#file").click(); return; }
  else if (c === "code") { const s = getSelection(); const t = s ? s.toString() : ""; if (t && !t.includes("\n")) insertHtml(`<code>${t.replace(/</g, "&lt;")}</code>&nbsp;`); else document.execCommand("formatBlock", false, "pre"); }
  tidy(); changed();
}
$$("#tools .tool").forEach(b => { b.onmousedown = (e) => e.preventDefault(); b.onclick = () => cmd(b.dataset.c); });
/* Chrome/WebKit при правке иногда оставляют <div> вместо <p> и <span style> — приводим к нашему виду */
function tidy() {
  for (const d of ED.querySelectorAll(":scope > div")) { const p = document.createElement("p"); p.innerHTML = d.innerHTML; d.replaceWith(p); }
  for (const p of ED.querySelectorAll(":scope > p")) {          // список или таблица внутри абзаца (так делает Chrome) — наружу; курсор остаётся
    const k = p.firstElementChild;
    if (k && p.childNodes.length === 1 && /^(UL|OL|TABLE|PRE|BLOCKQUOTE|H[1-3])$/.test(k.tagName)) p.replaceWith(k);
  }
  for (const s of ED.querySelectorAll("span[style], font")) s.replaceWith(...s.childNodes);
  for (const b of ED.querySelectorAll("b")) { const n = document.createElement("strong"); n.innerHTML = b.innerHTML; b.replaceWith(n); }
  for (const i of ED.querySelectorAll("i")) { const n = document.createElement("em"); n.innerHTML = i.innerHTML; i.replaceWith(n); }
  for (const s of ED.querySelectorAll("strike")) { const n = document.createElement("s"); n.innerHTML = s.innerHTML; s.replaceWith(n); }
}

try { document.execCommand("defaultParagraphSeparator", false, "p"); } catch (e) { }   // новый абзац — <p>, а не <div>
/* первое открытие */
const wait = setInterval(() => { if (core.connected) { clearInterval(wait); padShown(Q.get("side")); } }, 120);

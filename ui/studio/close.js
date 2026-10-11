/* Студия → «Близкие» (core/close.py): список близких, переписка, приглашение QR-кодом и ссылкой, принять ссылку.
   Данные — core.call("close_*"); новое приходит событиями close (состояние) и close_msg (входящее). Точка у пункта
   меню — есть непрочитанные. Отправка файла: файл из окна читается здесь и уходит base64 (files_b64), ядро шифрует его. */
const CL = { st: null, cur: "", hist: [], files: [] };
const clEsc = (t) => String(t == null ? "" : t).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const CL_COLORS = ["#9BD4FF", "#FFB547", "#3DF5C8", "#FF7AB6", "#B78CFF", "#9BE15D", "#7C8CFF", "#FF6B5A"];
const clColor = (pid) => CL_COLORS[[...String(pid)].reduce((a, c) => a + c.charCodeAt(0), 0) % CL_COLORS.length];
const clTime = (ts) => { const d = new Date(ts), now = new Date(); const hm = d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
  return d.toDateString() === now.toDateString() ? hm : d.toLocaleDateString("ru-RU", { day: "numeric", month: "short" }) + ", " + hm; };
const clSize = (n) => n > 1048576 ? (n / 1048576).toFixed(1).replace(".", ",") + " МБ" : Math.max(1, Math.round(n / 1024)) + " КБ";

function clDot(st) {
  const n = ((st && st.people) || []).reduce((a, p) => a + (p.unread || 0), 0);
  $("#close-dot").classList.toggle("on", n > 0);
}
async function loadClose(hello) {
  try { CL.st = await core.call("close_state", { hello: !!hello }); }
  catch (e) { $("#cl-res").className = "res bad"; $("#cl-res").textContent = e.message; return; }
  clRender();
}
function clRender() {
  const st = CL.st || { people: [] }, people = st.people || [];
  clDot(st);
  if (document.activeElement !== $("#cl-myname")) $("#cl-myname").value = (st.me && st.me.name && st.me.name !== "Без имени") ? st.me.name : "";
  $("#cl-speak").checked = !(S && S.close && S.close.speak === false);
  const r = $("#cl-res");
  if (st.error) { r.className = "res bad"; r.textContent = st.error; } else if (r.classList.contains("bad")) { r.className = "res"; r.textContent = ""; }
  $("#cl-people").innerHTML = people.length ? people.map(p => `<button class="cl-p ${p.pid === CL.cur ? "cur" : ""}" data-pid="${clEsc(p.pid)}">
      <i class="cl-ava" style="--c:${clColor(p.pid)}">${clEsc((p.name || "?").slice(0, 1).toUpperCase())}</i>
      <span><b>${clEsc(p.name)}</b><small>${p.last && (p.last.t || (p.last.f || []).length) ? clEsc((p.last.out ? "Вы: " : "") + (p.last.t || "📎 " + ((p.last.f[0] || {}).name || "файл"))) : "пока без сообщений"}</small></span>
      ${p.unread ? `<em>${p.unread}</em>` : ""}</button>`).join("")
    : `<p class="hint" style="margin:6px 2px 12px">Пока никого. Пригласите тех, с кем хотите переписываться через помощников.</p>`;
  $$("#cl-people .cl-p").forEach(b => b.onclick = () => clOpen(b.dataset.pid));
  if (CL.cur && !people.some(p => p.pid === CL.cur)) CL.cur = "";
  if (!CL.cur && people.length && !$("#cl-invite").offsetParent) clOpen(people[0].pid);
  else clHead();
}
function clHead() {
  const p = ((CL.st && CL.st.people) || []).find(x => x.pid === CL.cur);
  $("#cl-empty").style.display = p ? "none" : ""; $("#cl-head").style.display = p ? "" : "none"; $("#cl-send").style.display = p ? "" : "none";
  if (!p) { $("#cl-msgs").innerHTML = ""; return; }
  $("#cl-ava").textContent = (p.name || "?").slice(0, 1).toUpperCase(); $("#cl-ava").style.setProperty("--c", clColor(p.pid));
  $("#cl-who").textContent = p.name;
  $("#cl-devs").textContent = (p.devs || []).length ? "устройств: " + p.devs.length + " · сообщения шифруются" : "ещё не открывал Dewiar после приглашения";
  $("#cl-call").style.display = $("#cl-vcall").style.display = (p.devs || []).length ? "" : "none";
}
async function clOpen(pid) {
  CL.cur = pid; $("#cl-invite").style.display = "none";
  $$("#cl-people .cl-p").forEach(b => b.classList.toggle("cur", b.dataset.pid === pid));
  clHead();
  try { CL.hist = await core.call("close_history", { pid }); } catch (e) { CL.hist = []; }
  clMsgs();
}
function clMsgs() {
  const box = $("#cl-msgs");
  box.innerHTML = CL.hist.map(m => `<div class="cl-m ${m.out ? "out" : ""}">${m.t ? `<div class="tx">${clEsc(m.t)}</div>` : ""}
      ${(m.f || []).map(f => `<button class="cl-f" data-path="${clEsc(f.path || "")}" ${f.path ? "" : "disabled"}><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M6 3.5h8.5L19 8v12.5H6z"/><path d="M14 3.5V8h5"/></svg><span>${clEsc(f.name)}</span><small>${f.error ? "не скачался" : clSize(f.size || 0)}</small></button>`).join("")}
      <time>${clTime(m.ts)}</time></div>`).join("") || `<p class="hint" style="text-align:center;margin:30px 0">Напишите первое сообщение — или скажите помощнице: «Напиши ${clEsc((((CL.st || {}).people || []).find(x => x.pid === CL.cur) || {}).name || "")}, …»</p>`;
  $$("#cl-msgs .cl-f[data-path]").forEach(b => b.onclick = () => {
    const path = b.dataset.path, i = path.indexOf("/Близкие/"), rel = i >= 0 ? path.slice(path.lastIndexOf("Близкие/")) : "";
    if (rel) core.call("ws_open", { path: rel }).catch(e => toast(e.message));
  });
  box.scrollTop = box.scrollHeight;
}
async function clSend() {
  const text = $("#cl-text").value.trim(), pid = CL.cur;
  if (!pid || (!text && !CL.files.length)) return;
  const b = $("#cl-go"); b.disabled = true;
  try {
    await core.call("close_send", { pid, text, files_b64: CL.files });
    $("#cl-text").value = ""; CL.files = []; clFiles();
    CL.hist = await core.call("close_history", { pid }); clMsgs();
  } catch (e) { toast(e.message, 4000); }
  b.disabled = false; $("#cl-text").focus();
}
function clFiles() {
  $("#cl-files").innerHTML = CL.files.map((f, i) => `<span>${clEsc(f.name)} <button data-i="${i}" title="Убрать">✕</button></span>`).join("");
  $$("#cl-files button").forEach(x => x.onclick = () => { CL.files.splice(+x.dataset.i, 1); clFiles(); });
}
async function clInvite(renew) {
  const r = $("#cl-res");
  try {
    const d = await core.call("close_invite", { renew: !!renew });
    const code = String(d.link || "").split("&from=")[0];        // в коде — короткая ссылка (без имени)
    const seal = window.DewiarCodes ? DewiarCodes.seal(code) : "";
    $("#cl-invite").style.display = ""; $("#cl-qr").innerHTML = seal || qrSvg(code); $("#cl-qr").classList.toggle("seal", !!seal); $("#cl-inv-link").textContent = d.link;
    $("#cl-inv-qr").textContent = seal ? "Показать обычный QR" : "";
    $("#cl-inv-qr").onclick = (e) => { e.preventDefault(); const isSeal = $("#cl-qr").classList.contains("seal");
      $("#cl-qr").innerHTML = isSeal ? qrSvg(code) : seal; $("#cl-qr").classList.toggle("seal", !isSeal); $("#cl-inv-qr").textContent = isSeal ? "Показать печать Dewiar" : "Показать обычный QR"; };
    $("#cl-inv-copy").onclick = () => navigator.clipboard.writeText(`Добавь меня в «Близкие» в Dewiar — наши помощники смогут передавать друг другу сообщения: ${d.link}`)
      .then(() => toast("Ссылка скопирована"), () => toast(d.link));
    r.className = "res"; r.textContent = "";
  } catch (e) { r.className = "res bad"; r.textContent = e.message; }
}
async function clAccept() {
  const link = $("#cl-link").value.trim(), r = $("#cl-res");
  if (!link) return;
  r.className = "res"; r.textContent = "проверяю приглашение…";
  try {
    const who = await core.call("close_peek", { link });
    if (!confirm(`Принять приглашение в «Близкие» от «${who.name}»? Ваши помощники смогут передавать друг другу сообщения.`)) { r.textContent = ""; return; }
    const p = await core.call("close_accept", { link });
    $("#cl-link").value = ""; r.className = "res ok"; r.textContent = `Готово — ${p.name || who.name} в ваших близких.`;
    await loadClose(); if (p.pid) clOpen(p.pid);
  } catch (e) { r.className = "res bad"; r.textContent = e.message; }
}

$("#cl-go").onclick = clSend;
$("#cl-text").onkeydown = (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); clSend(); } };
$("#cl-file").onchange = () => {
  [...$("#cl-file").files].forEach(f => {
    if (f.size > 10 * 1024 * 1024) { toast(`«${f.name}» больше 10 МБ`); return; }
    const fr = new FileReader(); fr.onload = () => { CL.files.push({ name: f.name, b64: String(fr.result).split(",")[1] || "" }); clFiles(); }; fr.readAsDataURL(f);
  });
  $("#cl-file").value = "";
};
$("#cl-inv-go").onclick = () => clInvite(false);
$("#cl-inv-new").onclick = () => { if (confirm("Сделать новую ссылку? Старая перестанет действовать — те, кто уже добавился, останутся в близких.")) clInvite(true); };
$("#cl-inv-x").onclick = () => { $("#cl-invite").style.display = "none"; clHead(); };
$("#cl-link-go").onclick = clAccept;
$("#cl-myname").onchange = () => core.call("close_name", { name: $("#cl-myname").value }).then(st => { CL.st = st; toast("Сохранено"); }).catch(e => toast(e.message));
$("#cl-speak").onchange = () => core.call("close_speak", { on: $("#cl-speak").checked }).catch(() => {});
$("#cl-call").onclick = () => core.call("close_call", { pid: CL.cur, video: false }).then(r => toast("Звоню " + r.name + " — окно звонка открыто в браузере", 3000)).catch(e => toast(e.message, 4000));
$("#cl-vcall").onclick = () => core.call("close_call", { pid: CL.cur, video: true }).then(r => toast("Видеозвонок " + r.name + " — окно открыто в браузере", 3000)).catch(e => toast(e.message, 4000));
$("#cl-del").onclick = async () => {
  const p = ((CL.st && CL.st.people) || []).find(x => x.pid === CL.cur); if (!p) return;
  if (!confirm(`Убрать «${p.name}» из близких? Переписка у вас останется, но писать друг другу будет нельзя, пока не пригласите снова.`)) return;
  try { CL.st = await core.call("close_remove", { pid: p.pid }); CL.cur = ""; clRender(); } catch (e) { toast(e.message); }
};
core.on("close", e => { CL.st = e.state; if ($("#p-close").classList.contains("cur")) clRender(); else clDot(CL.st); })
  .on("close_msg", e => { if ($("#p-close").classList.contains("cur") && e.pid === CL.cur) clOpen(CL.cur); })
  .on("hello", () => core.call("close_state").then(st => { CL.st = st; clDot(st); }).catch(() => {}));

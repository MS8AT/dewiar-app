/* Студия: «Чат» — вся переписка с персонажами (просьба 14.10: «на компьютере не понятно, где наша с Лирой переписка; на
   телефоне это есть»). Лента — из ядра (chat_list, core/chatlog.py): что человек сказал голосом или написал и что ответили,
   по дням, старые сверху; «Показать раньше» подгружает предыдущие. Новые реплики приходят событием chat; пока модель
   отвечает — живой пузырь из событий answer. Внизу — поле: написать текстом (то же, что сказать, — команда say).
   Пузыри — те же, что в «Близких» (.cl-m), чтобы переписка везде выглядела одинаково. */
const CH = { items: [], more: false, loaded: false, live: null };
function chatWho(pid) { return (personas || []).find(p => p.id === pid) || null; }
function chatDay(ts) {
  const d = new Date(ts * 1000), now = new Date(), y = new Date(now); y.setDate(now.getDate() - 1);
  if (d.toDateString() === now.toDateString()) return "Сегодня";
  if (d.toDateString() === y.toDateString()) return "Вчера";
  return d.toLocaleDateString("ru-RU", { day: "numeric", month: "long", year: d.getFullYear() === now.getFullYear() ? undefined : "numeric" });
}
function chatBubble(x, lastWho) {
  const out = x.role === "user", p = out ? null : chatWho(x.who);
  const hm = new Date(x.ts * 1000).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
  // имя персонажа — над его первым ответом за день и когда отвечает другой персонаж (не над каждым ответом)
  const head = !out && lastWho !== (x.who || "")
    ? `<div class="ch-who"><i style="background:${escH((p && p.color) || "#8A9BFF")}"></i>${escH((p && p.name) || "Ассистент")}</div>` : "";
  const body = out ? `<div class="tx">${escH(x.text)}</div>` : `<div class="tx md">${md(x.text)}</div>`;
  return `${head}<div class="cl-m${out ? " out" : ""}" data-id="${escH(x.id)}">${x.via ? `<small class="ch-via">из мессенджера</small>` : ""}${body}<time>${hm}</time></div>`;
}
function chatRender(keep) {
  const box = $("#ch-msgs"); if (!box) return;
  const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 60, oldH = box.scrollHeight, oldTop = box.scrollTop;
  let html = CH.more ? `<button class="btn small ch-older" id="ch-older">Показать раньше</button>` : "", day = "", lastWho = null;
  CH.items.forEach((x) => {
    const d = chatDay(x.ts);
    if (d !== day) { html += `<div class="ch-day"><span>${escH(d)}</span></div>`; day = d; lastWho = null; }
    html += chatBubble(x, lastWho);
    if (x.role === "assistant") lastWho = x.who || "";
  });
  if (CH.live && lastWho === active) html += `<div class="cl-m ch-live">${CH.live.text ? `<div class="tx md">${md(CH.live.text)}</div>` : `<div class="ch-dots"><i></i><i></i><i></i></div>`}</div>`;
  else if (CH.live) {
    const p = chatWho(active);
    html += `<div class="ch-who"><i style="background:${escH((p && p.color) || "#8A9BFF")}"></i>${escH((p && p.name) || "Ассистент")}</div>`
      + `<div class="cl-m ch-live">${CH.live.text ? `<div class="tx md">${md(CH.live.text)}</div>` : `<div class="ch-dots"><i></i><i></i><i></i></div>`}</div>`;
  }
  $("#ch-empty").style.display = CH.items.length || CH.live ? "none" : "";
  box.innerHTML = html;
  if (keep === "older") box.scrollTop = box.scrollHeight - oldH + oldTop;   // подгрузили раньше — лента не прыгает
  else if (keep !== "stay" || atBottom) box.scrollTop = box.scrollHeight;
  const o = $("#ch-older"); if (o) o.onclick = chatOlder;
  const p = chatWho(active);
  $("#ch-text").placeholder = `Сообщение — ответит ${p ? p.name : "ассистент"}. Enter — отправить, Shift+Enter — новая строка`;
}
async function loadChat() {
  try {
    const r = await core.call("chat_list", { limit: 80 });
    CH.items = r.items || []; CH.more = !!r.more; CH.loaded = true;
  } catch (e) { $("#ch-res").textContent = e.message; }
  chatRender();
}
async function chatOlder() {
  if (!CH.items.length) return;
  const r = await core.call("chat_list", { before: CH.items[0].id, limit: 80 }).catch(() => null);
  if (!r) return;
  CH.items = (r.items || []).concat(CH.items); CH.more = !!r.more;
  chatRender("older");
}
core.on("chat", e => {
  const x = e.item; if (!x || !CH.loaded) return;
  const i = CH.items.findIndex(y => y.id === x.id);
  if (i >= 0) CH.items[i] = x; else CH.items.push(x);
  if (x.role === "assistant") CH.live = null;
  if ($("#p-chat").classList.contains("cur")) chatRender("stay");
});
// пока модель отвечает — живой пузырь (текст по мере ответа); готовый ответ придёт событием chat
core.on("answer", e => {
  if (!CH.loaded || e.done) return;
  CH.live = { text: e.text || "" };
  if ($("#p-chat").classList.contains("cur")) chatRender("stay");
});
core.on("state", e => {
  if (!CH.loaded) return;
  if (e.state === "thinking" && !CH.live) { CH.live = { text: "" }; if ($("#p-chat").classList.contains("cur")) chatRender("stay"); }
  if ((e.state === "idle" || e.state === "listening") && CH.live && !CH.live.text) { CH.live = null; if ($("#p-chat").classList.contains("cur")) chatRender("stay"); }
});
function chatSend() {
  const t = $("#ch-text"), q = t.value.trim(); if (!q) return;
  t.value = ""; t.style.height = "";
  core.call("say", { text: q }).catch(e => { $("#ch-res").textContent = e.message; });
}
$("#ch-go").onclick = chatSend;
$("#ch-text").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); chatSend(); } });
$("#ch-text").addEventListener("input", (e) => { const t = e.target; t.style.height = ""; t.style.height = Math.min(160, t.scrollHeight) + "px"; });
$("#ch-clear").onclick = async () => {
  if (!confirm("Очистить всю переписку в «Чате»? Память ассистента и заметки это не трогает.")) return;
  await core.call("chat_clear").catch(() => {}); CH.items = []; CH.more = false; chatRender();
};
core.on("hello", () => { if ($("#p-chat").classList.contains("cur")) loadChat(); });

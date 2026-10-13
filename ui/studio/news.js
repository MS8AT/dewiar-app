/* Студия → «Что нового» после обновления (core/news.py, data/whatsnew.json — тот же текст, что на телефоне).
   При связи с ядром: есть невиданное — окно с пунктами (что это и как попробовать); «Понятно» — больше не показывать
   (news_seen). Открыть снова — «О программе» → «✨ Что нового». */
const nwEsc = (t) => String(t == null ? "" : t).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
function newsShow(r) {
  const rels = (r && r.releases) || [];
  if (!rels.length) return false;
  $("#nw-sub").textContent = `Dewiar ${rels[0].version} — вот что появилось`;
  $("#nw-list").innerHTML = rels.map(x => x.items.map(i => `<div class="nwi"><i aria-hidden="true">${nwEsc(i.icon || "✨")}</i><div><b>${nwEsc(i.title)}</b>
    <p>${nwEsc(i.text)}</p>${i.try ? `<small>${/^«/.test(i.try) ? "Скажите: " : ""}${nwEsc(i.try)}</small>` : ""}</div></div>`).join("")).join("");
  const d = $("#news-dlg"); if (!d.open) d.showModal(); d.scrollTop = 0; $("#nw-title").focus();
  return true;
}
$("#nw-ok").onclick = () => { $("#news-dlg").close(); core.call("news_seen").catch(() => {}); };
$("#news-dlg").addEventListener("cancel", () => core.call("news_seen").catch(() => {}));
$("#ab-news").onclick = () => core.call("news", { all: true }).then(r => { if (!newsShow(r)) toast("Новостей пока нет"); }).catch(e => toast(e.message));
core.on("hello", () => setTimeout(() => core.call("news").then(newsShow).catch(() => {}), 600));

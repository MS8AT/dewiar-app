/* Студия → «Оформление»: тема виджета (ui.skin) и чем голос отзывается вокруг портрета (ui.voice_fx).
   Карточки — живые образцы: тема — фон, портрет и строка состояния в её цветах; анимация — настоящий облик
   (DewiarEntity) главного персонажа, который «говорит» в выбранной манере. Выбор сохраняется сразу (save), виджет
   получает событие settings и перекрашивается (hud.html applyLook); студия перекрашивается сама (studio/theme.js). */
const LOOK_FX = [
  ["bars", "Лучи", "Полоски вокруг портрета отзываются на голос"],
  ["pulse", "Пульс", "От портрета мягко расходятся круги"],
  ["wave", "Волна", "Живая линия по кругу"],
];
let lookEnts = [];

function loadLook() {
  const ui = (S && S.ui) || {};
  const skin = window.dewiarSkin ? dewiarSkin(ui.skin).id : "brand";
  const fx = LOOK_FX.some(x => x[0] === ui.voice_fx) ? ui.voice_fx : "bars";
  const p = personas.find(x => x.id === "lira") || personas.find(x => x.id === active) || personas[0] || {};
  const img = p.avatar_url || "";
  const esc = (t) => String(t).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const skins = window.DEWIAR_SKINS || [], groups = [...new Set(skins.map(x => x.group))];
  $("#lk-skins").innerHTML = groups.map(g => `<div class="lk-group">${esc(g)}</div><div class="lk-grid">` + skins.filter(x => x.group === g).map(x => `<button class="lk ${x.id === skin ? "on" : ""}" data-skin="${x.id}">
      <div class="lk-prev skin-${x.id}" style="--persona:${esc(p.color || "#9BD4FF")}"><canvas class="pc"></canvas><span class="pl">Ваша очередь</span></div>
      <b>${esc(x.name)}</b><span>${esc(x.sub)}</span></button>`).join("") + `</div>`).join("");
  lookEnts.forEach(e => e.destroy()); lookEnts = [];
  const look = (cv, sk, fx, still) => new DewiarEntity(cv, { style: img && p.style !== "aura" ? "photo" : (p.style || "nexus"), color: p.color || "#9BD4FF",
    image: img || null, live: p.live || "", plate: false, still, tone: (window.dewiarSkin ? dewiarSkin(sk).tone : "") || "mono", fx });
  // образцы фона — тот же облик, что в виджете (живое лицо, край портрета этой темы), неподвижный
  $$("#lk-skins .lk").forEach(b => lookEnts.push(look($("canvas", b), b.dataset.skin, "bars", true)));
  $("#lk-fx").innerHTML = LOOK_FX.map(([id, name, sub]) => `<button class="lk ${id === fx ? "on" : ""}" data-fx="${id}">
      <div class="lk-prev skin-${skin}"><canvas></canvas></div><b>${name}</b><span>${sub}</span></button>`).join("");
  $$("#lk-fx .lk").forEach(b => {
    const e = look($("canvas", b), skin, b.dataset.fx, false);
    e.set({ state: "speaking", level: 0.45 });
    lookEnts.push(e);
  });
  $$("#lk-skins .lk").forEach(b => b.onclick = () => save({ ui: { skin: b.dataset.skin } }).then(() => { if (window.studioSkin) studioSkin(b.dataset.skin); loadLook(); }));
  $$("#lk-fx .lk").forEach(b => b.onclick = () => save({ ui: { voice_fx: b.dataset.fx } }).then(loadLook));
}

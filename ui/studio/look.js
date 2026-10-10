/* Студия → «Оформление»: тема виджета (ui.skin) и чем голос отзывается вокруг портрета (ui.voice_fx).
   Карточки — живые образцы: тема — фон, портрет и строка состояния в её цветах; анимация — настоящий облик
   (DewiarEntity) главного персонажа, который «говорит» в выбранной манере. Выбор сохраняется сразу (save), виджет
   получает событие settings и перекрашивается (hud.html applyLook). */
const LOOK_SKINS = [
  ["calm", "Сдержанная", "Стекло и холодный белый, мягкий тёмный фон с тёплым отливом"],
  ["brand", "Фирменная", "Цвета Dewiar: сиреневый, розовый и голубой на тёмном"],
  ["graphite", "Графит", "Почти чёрная, без цветных бликов — ничего не отвлекает"],
  ["neon", "Неон", "Как раньше: свечение и цвет персонажа"],
];
const LOOK_FX = [
  ["bars", "Лучи", "Полоски вокруг портрета отзываются на голос"],
  ["pulse", "Пульс", "От портрета мягко расходятся круги"],
  ["wave", "Волна", "Живая линия по кругу"],
];
let lookEnts = [];

function loadLook() {
  const ui = (S && S.ui) || {};
  const skin = LOOK_SKINS.some(x => x[0] === ui.skin) ? ui.skin : "calm";
  const fx = LOOK_FX.some(x => x[0] === ui.voice_fx) ? ui.voice_fx : "bars";
  const p = personas.find(x => x.id === "lira") || personas.find(x => x.id === active) || personas[0] || {};
  const img = p.avatar_url || "";
  const esc = (t) => String(t).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  $("#lk-skins").innerHTML = LOOK_SKINS.map(([id, name, sub]) => `<button class="lk ${id === skin ? "on" : ""}" data-skin="${id}">
      <div class="lk-prev sk-${id}" style="--pc:${esc(p.color || "#B78CFF")}"><i class="pt" style="${img ? `background-image:url('${esc(img)}')` : ""}"></i><span class="pl">Ваша очередь</span></div>
      <b>${name}</b><span>${sub}</span></button>`).join("");
  lookEnts.forEach(e => e.destroy()); lookEnts = [];
  $("#lk-fx").innerHTML = LOOK_FX.map(([id, name, sub]) => `<button class="lk ${id === fx ? "on" : ""}" data-fx="${id}">
      <div class="lk-prev sk-${skin}"><canvas></canvas></div><b>${name}</b><span>${sub}</span></button>`).join("");
  $$("#lk-fx .lk").forEach(b => {
    const e = new DewiarEntity($("canvas", b), { style: img && p.style !== "aura" ? "photo" : (p.style || "nexus"), color: p.color || "#B78CFF",
      image: img || null, live: p.live || "", plate: false, tone: skin === "neon" ? "color" : "mono", fx: b.dataset.fx });
    e.set({ state: "speaking", level: 0.45 });
    lookEnts.push(e);
  });
  $$("#lk-skins .lk").forEach(b => b.onclick = () => save({ ui: { skin: b.dataset.skin } }).then(loadLook));
  $$("#lk-fx .lk").forEach(b => b.onclick = () => save({ ui: { voice_fx: b.dataset.fx } }).then(loadLook));
}

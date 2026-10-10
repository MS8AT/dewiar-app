/* Студия Dewiar: «Обо мне» (память и «Знания»), почта, Telegram, серверы (SSH), MAX, Obsidian, аккаунт dewiar.pro,
   отчёты о сбоях и кнопка «Проверить обновления».
   Каждый блок — функция *Fill(данные) плюс обработчики кнопок; команды ядра: memory_get/set, knowledge_*, mail_*, tg_*,
   server_*, max_*, obsidian_*, account_*, report*, update_check; события telegram, max, obsidian, account,
   report_offer, update — ядро присылает в них то же, что отвечает на команды; жалобы — complaint_send, complaints,
   bug_shot/bug_state и события bug_shot, complaints.
   Файлы студии подключаются по порядку из ui/settings.html и делят одну глобальную область: при загрузке здесь только
   вешаются обработчики; SVG/ICONS (выше), escH (folder.js), RI (brain.js), renderUpdate (tasks.js) нужны при отрисовке.
   openExt и obLast отсюда использует memory.js. */
/* ---------- обо мне: память и «Знания» ---------- */
function fmtSize(b) { return b > 1e6 ? (b / 1e6).toFixed(1).replace(".", ",") + " МБ" : Math.max(1, Math.round(b / 1e3)) + " КБ"; }
function renderKn(files) {
  const box = $("#kn-list"); box.innerHTML = "";
  if (!files.length) { box.innerHTML = '<p class="hint">Пока пусто. Добавьте файлы — и ассистент сможет по ним отвечать.</p>'; return; }
  files.forEach(f => {
    const row = document.createElement("div"); row.className = "kn-row";
    row.innerHTML = `<b></b><span class="${f.error ? "bad" : ""}"></span><span>${fmtSize(f.size)}</span><button class="btn small" title="Убрать из «Знаний»">Убрать</button>`;
    $("b", row).textContent = f.path; $("span", row).textContent = f.error ? f.error : `${f.chunks} ${f.chunks % 10 === 1 && f.chunks % 100 !== 11 ? "отрывок" : "отрывков"}`;
    $("button", row).onclick = () => core.call("knowledge_remove", { path: f.path }).then(renderKn).catch(e => toast(e.message));
    box.appendChild(row);
  });
}
function loadMe() {
  core.call("memory_get").then(t => { $("#me-mem").value = t.trim(); }).catch(() => {});
  core.call("knowledge_list").then(r => renderKn(r.files)).catch(e => ($("#kn-res").textContent = e.message));
  const a = S && lastAccount; $("#kn-site").textContent = a && a.logged_in ? `Знания с сайта тоже подключены: аккаунт ${a.user && a.user.login || a.login} (раздел «Подключение»).` : "";
}
let lastAccount = null;
$("#me-save").onclick = () => core.call("memory_set", { text: $("#me-mem").value }).then(() => { $("#me-res").className = "res ok"; $("#me-res").textContent = "Сохранено"; setTimeout(() => ($("#me-res").textContent = ""), 2500); }).catch(e => toast(e.message));
$("#kn-open").onclick = () => core.call("knowledge_open").catch(e => toast(e.message));
$("#kn-file").onchange = async (ev) => {
  const files = [...ev.target.files]; ev.target.value = ""; const r = $("#kn-res"); let n = 0;
  for (const f of files) {
    // файл идёт в ядро одним сообщением base64 (+⅓ к размеру), а сообщение — не больше 16 МБ (core/bridge.py)
    if (f.size > 11e6) { toast(`«${f.name}» больше 11 МБ — положите его в папку сами: «Открыть папку»`); continue; }
    r.className = "res"; r.textContent = `добавляю ${f.name}…`;
    const b64 = await new Promise((ok, bad) => { const fr = new FileReader(); fr.onload = () => ok(fr.result); fr.onerror = bad; fr.readAsDataURL(f); });
    try { const res = await core.call("knowledge_add", { name: f.name, b64 }); renderKn(res.files); n++; }
    catch (e) { toast(`${f.name}: ${e.message}`); }
  }
  r.className = n ? "res ok" : "res"; r.textContent = n ? `Добавлено файлов: ${n}` : "";
};
$("#kn-go").onclick = async () => {
  const q = $("#kn-q").value.trim(); if (!q) return; const box = $("#kn-found"); box.innerHTML = "";
  try {
    const hits = await core.call("knowledge_search", { query: q });
    if (!hits.length) { box.innerHTML = '<p class="hint" style="margin-top:8px">Ничего не нашлось.</p>'; return; }
    hits.forEach(h => { const d = document.createElement("div"); d.className = "kn-hit"; d.innerHTML = "<b></b><div></div>"; $("b", d).textContent = h.path; $("div", d).textContent = h.text.slice(0, 420) + (h.text.length > 420 ? "…" : ""); box.appendChild(d); });
  } catch (e) { toast(e.message); }
};
$("#kn-q").onkeydown = (e) => { if (e.key === "Enter") $("#kn-go").click(); };

/* ---------- почта ---------- */
const HELP = { yandex: "Яндекс", mailru: "Mail.ru", gmail: "Google", outlook: "Microsoft", icloud: "Apple" };
function mlHelp(g) {
  $("#ml-help").innerHTML = g && g.help ? `Обычный пароль почта сторонним программам не даёт — нужен <b>пароль приложения</b>: <a href="${g.help}" target="_blank">создать в ${HELP[g.provider] || "настройках почты"}</a> (тип «Почта»), затем вставьте его сюда.`
    : "Нужен пароль приложения (в настройках безопасности вашей почты) или обычный пароль, если почта его разрешает.";
}
function mlFill(m) {
  if (!m) return;
  if (m.address && !$("#ml-addr").value) $("#ml-addr").value = m.address;
  $("#ml-name").value = m.name || ""; $("#ml-login").value = m.login || "";
  $("#ml-smtp").value = m.smtp_host || ""; $("#ml-sport").value = m.smtp_port || ""; $("#ml-sec").value = m.smtp_security || "ssl";
  $("#ml-imap").value = m.imap_host || ""; $("#ml-iport").value = m.imap_port || "";
  $("#ml-pass").placeholder = m.has_password ? "пароль сохранён — впишите, чтобы сменить" : "пароль приложения";
  $("#ml-on").style.display = m.configured ? "" : "none";
  $("#ml-state").textContent = m.configured ? `Подключена: ${m.address}` : "";
  mlHelp(m);
}
$("#ml-addr").onchange = () => { const v = $("#ml-addr").value.trim(); if (!v.includes("@")) return;
  core.call("mail_guess", { address: v }).then(g => { $("#ml-smtp").value = g.smtp_host; $("#ml-sport").value = g.smtp_port; $("#ml-sec").value = g.smtp_security;
    $("#ml-imap").value = g.imap_host; $("#ml-iport").value = g.imap_port; mlHelp(g); }).catch(() => {}); };
$("#ml-save").onclick = async (ev) => {
  const r = $("#ml-res"); ev.target.disabled = true; r.className = "res"; r.textContent = "проверяю вход в почту…";
  const patch = { address: $("#ml-addr").value.trim(), password: $("#ml-pass").value, name: $("#ml-name").value.trim(), login: $("#ml-login").value.trim(),
                  smtp_host: $("#ml-smtp").value.trim(), smtp_port: +$("#ml-sport").value || 465, smtp_security: $("#ml-sec").value,
                  imap_host: $("#ml-imap").value.trim(), imap_port: +$("#ml-iport").value || 993 };
  try {
    const m = await core.call("mail_save", { patch }); $("#ml-pass").value = ""; mlFill(m);
    const tr = await core.call("mail_test");
    const ok = tr.smtp === "ok" && (!patch.imap_host || tr.imap === "ok");
    r.className = ok ? "res ok" : "res bad";
    r.textContent = ok ? "Готово: отправка и чтение работают. Скажите: «пришли мне на почту список дел»." :
      [tr.smtp !== "ok" ? "Отправка: " + tr.smtp : "", tr.imap && tr.imap !== "ok" ? "Чтение: " + tr.imap : ""].filter(Boolean).join(" · ");
  } catch (e) { r.className = "res bad"; r.textContent = e.message; } finally { ev.target.disabled = false; }
};
$("#ml-test").onclick = async (ev) => { const r = $("#ml-res"); ev.target.disabled = true; r.className = "res"; r.textContent = "отправляю…";
  try { const x = await core.call("mail_send_test"); r.className = "res ok"; r.textContent = `Письмо отправлено на ${x.to.join(", ")} — проверьте ящик.`; }
  catch (e) { r.className = "res bad"; r.textContent = e.message; } finally { ev.target.disabled = false; } };
$("#ml-off").onclick = () => core.call("mail_forget").then(m => { $("#ml-addr").value = ""; mlFill(m); $("#ml-res").textContent = "Почта отключена."; }).catch(e => toast(e.message));

/* ---------- Telegram ---------- */
let tgTimer = null;
let tgWas = null, tgMode = "";   // tgWas: был ли привязан владелец в прошлый раз — чтобы поздравить ровно в момент привязки
function tgFill(t) {
  if (!t) return;
  if (tgWas === false && t.paired) { $("#tg-res").className = "res ok"; $("#tg-res").textContent = "Готово! Напишите боту что-нибудь — ответит ассистент."; }
  tgWas = !!t.paired; tgMode = t.mode || "";
  $("#tg-setup").style.display = t.connected ? "none" : "";
  $("#tg-pair").style.display = t.connected && !t.paired ? "" : "none";
  $("#tg-on").style.display = t.paired ? "" : "none";
  if (t.bot) { $("#tg-link").textContent = "@" + t.bot; $("#tg-link").href = t.link || ("https://t.me/" + t.bot + (t.code ? "?start=" + t.code : ""));
              $("#tg-open").href = $("#tg-link").href;
              $("#tg-web").href = "https://web.telegram.org/k/#?tgaddr=" + encodeURIComponent("tg://resolve?domain=" + t.bot + (t.code ? "&start=" + t.code : ""));
              tgQr(t.connected && !t.paired ? $("#tg-link").href : ""); }
  tgSharedVis();
  $("#tg-code").textContent = "/start " + (t.code || "");
  $("#tg-state").textContent = t.paired ? `Подключён${t.mode === "dewiar" ? " через бота Dewiar" : ""}: @${t.bot} · владелец ${t.owner || "вы"}` : "";
  $("#tg-notify").checked = t.notify !== false; $("#tg-voice").checked = !!t.voice_home; $("#tg-vreply").checked = t.voice_reply !== false;
  if (t.api) $("#tg-api").value = t.api;
  $("#tg-off-row").style.display = t.can_offline ? "" : "none";
  $("#tg-offline").checked = t.offline !== false;
  { const os_ = t.offline_state || {}, base = "Бот Dewiar сам отвечает с сервера: вопросы, заметки, список покупок, напоминания. Включится компьютер — всё окажется и на нём.";
    $("#tg-off-why").textContent = !os_.synced ? base : !os_.ok ? "Чтобы отвечать без компьютера, нужны модели Dewiar: войдите в аккаунт dewiar.pro (раздел «Dewiar.pro») или подключите ключ Dewiar."
      : base + (os_.tick ? "" : " Напоминания без компьютера заработают, когда на сервере включат расписание (tg.php?tick раз в минуту)."); }
  $("#tg-px-on").textContent = t.proxy ? "· включён" : "";
  if (document.activeElement !== $("#tg-proxy")) $("#tg-proxy").value = t.proxy || "";
  const r = $("#tg-res");
  if (t.problem) { r.className = "res bad"; r.textContent = "Telegram: " + t.problem; }
  // ждём, пока владелец нажмёт «Запустить» у бота: спрашиваем ядро раз в 2 с, пока не привяжется
  clearInterval(tgTimer); tgTimer = null;
  if (t.connected && !t.paired) tgTimer = setInterval(() => core.call("tg_get").then(x => { if (x.paired) tgFill(x); }).catch(() => {}), 2000);
}
function tgSharedVis() {
  $("#tg-shared").style.display = "";                 // аккаунт не нужен — бот Dewiar по ключу этого компьютера
  $("#tg-shared-info").style.display = "none";
  $("#tg-own-sum").textContent = "Дополнительно: свой бот (создаётся у @BotFather)";
}
$("#tg-shared-go").onclick = async (ev) => {
  const r = $("#tg-res"); ev.target.disabled = true; r.className = "res"; r.textContent = "подключаю…";
  try { const t = await core.call("tg_connect_shared"); r.textContent = ""; tgFill(t); }
  catch (e) { r.className = "res bad"; r.textContent = e.message; } finally { ev.target.disabled = false; }
};
$("#tg-connect").onclick = async (ev) => {
  const r = $("#tg-res"); ev.target.disabled = true; r.className = "res"; r.textContent = "проверяю токен…";
  try { const t = await core.call("tg_connect", { token: $("#tg-token").value.trim(), api: $("#tg-api").value.trim() });
        $("#tg-token").value = ""; r.textContent = ""; tgFill(t); }
  catch (e) { r.className = "res bad"; r.textContent = e.message; } finally { ev.target.disabled = false; }
};
$("#tg-token").onkeydown = (e) => { if (e.key === "Enter") $("#tg-connect").click(); };
$("#tg-proxy-save").onclick = async (ev) => {
  const r = $("#tg-res"), v = $("#tg-proxy").value.trim(); ev.target.disabled = true; r.className = "res"; r.textContent = v ? "проверяю прокси…" : "отключаю прокси…";
  // ядро отдаёт прокси со скрытым паролем («•••») — такую строку сохранять нельзя
  try { if (v.includes("•••")) throw new Error("впишите прокси заново, вместе с паролем");
        const t = await core.call("tg_proxy", { proxy: v }); tgFill(t); r.className = "res ok"; r.textContent = v ? "Прокси работает — Telegram ходит через него." : "Прокси выключен."; }
  catch (e) { r.className = "res bad"; r.textContent = e.message; } finally { ev.target.disabled = false; }
};
$("#tg-proxy").onkeydown = (e) => { if (e.key === "Enter") $("#tg-proxy-save").click(); };
$("#tg-copy").onclick = () => { navigator.clipboard && navigator.clipboard.writeText($("#tg-open").href).then(() => toast("Ссылка скопирована")).catch(() => {}); };
function tgQr(url) {
  const box = $("#tg-qr");
  if (!url || typeof qrcode !== "function") { box.innerHTML = ""; box.style.display = "none"; return; }
  if (box.dataset.u === url) return;
  box.innerHTML = qrPretty(url, "M"); box.dataset.u = url; box.style.display = "";
}
$("#tg-notify").onchange = (e) => core.call("tg_set", { patch: { notify: e.target.checked } }).then(tgFill).catch(x => toast(x.message));
$("#tg-vreply").onchange = (e) => core.call("tg_set", { patch: { voice_reply: e.target.checked } }).then(tgFill).catch(x => toast(x.message));
$("#tg-offline").onchange = (e) => core.call("tg_set", { patch: { offline: e.target.checked } }).then(tgFill).catch(x => toast(x.message));
$("#tg-voice").onchange = (e) => core.call("tg_set", { patch: { voice_home: e.target.checked } }).then(tgFill).catch(x => toast(x.message));
$("#tg-test").onclick = async (ev) => { const r = $("#tg-res"); ev.target.disabled = true; r.className = "res"; r.textContent = "отправляю…";
  try { await core.call("tg_test"); r.className = "res ok"; r.textContent = "Сообщение отправлено — посмотрите в Telegram."; }
  catch (e) { r.className = "res bad"; r.textContent = e.message; } finally { ev.target.disabled = false; } };
$("#tg-recode").onclick = () => core.call("tg_new_code").then(t => { tgFill(t); $("#tg-res").className = "res"; $("#tg-res").textContent = "Прежний владелец отвязан — новый владелец открывает ссылку и жмёт «Запустить»."; }).catch(e => toast(e.message));
$("#tg-off").onclick = () => { const own = tgMode === "own";
  core.call("tg_forget").then(t => { tgWas = null; tgFill(t); $("#tg-res").className = "res";
    $("#tg-res").textContent = own ? "Telegram отключён. Бота можно удалить в @BotFather (/deletebot)." : "Telegram отключён — бот вам больше не пишет."; }).catch(e => toast(e.message)); };
// виджет дважды не загрузился — ui/app.py запускается без окна (ui.widget_fail2 ≥ 2); сброс счётчика включает окно снова
$("#wf-on").onclick = () => core.call("settings_save", { patch: { ui: { widget_fail2: 0 } } })
  .then(() => toast("Готово — перезапустите Dewiar (значок в трее → «Выход», затем снова из меню «Пуск»)")).catch(e => toast(e.message));
core.on("telegram", e => tgFill(e));
/* ---------- серверы ----------
   Вход по ключу SSH: пароль нужен один раз — ядро ставит ключ на сервер и пароль не хранит. ask — когда спрашивать
   разрешение на команды: на каждую или только на меняющие что-то. */
let svData = null;
function svFill(d) {
  if (!d) return; svData = d;
  const box = $("#sv-list"); box.innerHTML = "";
  const no = $("#sv-nossh");
  if (!d.ssh) { no.style.display = ""; no.innerHTML = '<b>Нет программы ssh.</b> <span class="hint">' + (navigator.userAgent.includes("Windows") ?
      "Windows: Параметры → Приложения → Дополнительные компоненты → «Клиент OpenSSH» → Установить." : "Linux: sudo apt install openssh-client") + "</span>"; }
  else no.style.display = "none";
  if (!d.servers.length) box.innerHTML = '<div class="rempty">Серверов пока нет — добавьте ниже. Понадобятся адрес, пользователь и (один раз) пароль.</div>';
  d.servers.forEach(x => {
    const el = document.createElement("div"); el.className = "ritem sv-item";
    el.innerHTML = `<div class="ico">${SVG(ICONS.servers)}</div><div class="rbody"><div class="rtext"></div><div class="rmeta"></div></div>
      <select title="Когда спрашивать"><option value="all">спрашивать каждую команду</option><option value="changes">спрашивать только изменения</option></select>
      <div class="ract"><button data-c="chk" title="Проверить вход">${SVG('<path d="M20 6 9 17l-5-5"/>')}</button><button data-c="del" title="Удалить">${SVG(RI.del)}</button></div>`;
    $(".rtext", el).textContent = x.name;
    const m = $(".rmeta", el);
    const add = (t, cls) => { const sp = document.createElement(cls === "code" ? "code" : "span"); sp.textContent = t; m.appendChild(sp); };
    add(`${x.user}@${x.host}${x.port !== 22 ? ":" + x.port : ""}`); if (x.system) add(x.system); if (x.fingerprint) add(x.fingerprint.slice(0, 22) + "…", "code");
    if ((x.aliases || []).length) add("ещё: " + x.aliases.join(", "));
    const sel = $("select", el); sel.value = x.ask || "all";
    sel.onchange = () => core.call("server_update", { id: x.id, patch: { ask: sel.value } }).then(svFill)
      .then(() => toast(sel.value === "changes" ? "Команды «только посмотреть» — без вопроса" : "Каждая команда — с вопросом")).catch(e => toast(e.message));
    $("[data-c=chk]", el).onclick = async (ev) => { const btn = ev.currentTarget; btn.disabled = true; toast("Проверяю вход…");   // после await currentTarget уже null
      try { const r = await core.call("server_check", { id: x.id }); svFill(r); toast(`«${x.name}»: вход есть · ${r.info.system || ""} · ${r.info.uptime || ""}`); }
      catch (e) { toast(e.message); } finally { btn.disabled = false; } };
    $("[data-c=del]", el).onclick = () => { if (confirm(`Удалить сервер «${x.name}» из Dewiar? Ключ на самом сервере останется — его можно убрать из ~/.ssh/authorized_keys.`))
      core.call("server_remove", { id: x.id }).then(svFill).catch(e => toast(e.message)); };
    box.appendChild(el);
  });
  $("#sv-key").textContent = d.key || "ключ появится после первого сервера (или нажмите «Создать ключ»)";
  $("#sv-key-make").style.display = d.key ? "none" : "";
}
function svLoad() { core.call("server_list").then(svFill).catch(e => { $("#sv-list").textContent = e.message; }); }
$("#sv-add").onclick = async (ev) => {
  const r = $("#ssh-res"); const host = $("#ssh-host").value.trim(), user = $("#sv-user").value.trim();
  if (!host || !user) { r.className = "res bad"; r.textContent = "Нужны адрес и пользователь."; return; }
  ev.target.disabled = true; r.className = "res"; r.textContent = $("#sv-pass").value ? "ставлю ключ и проверяю вход… (до минуты)" : "проверяю вход по ключу…";
  try {
    const d = await core.call("server_add", { name: $("#sv-name").value.trim(), host, user, port: +$("#ssh-port").value || 22, password: $("#sv-pass").value,
      keyfile: $("#sv-keyfile").value.trim(), aliases: $("#sv-alias").value.split(",").map(x => x.trim()).filter(Boolean) });
    $("#sv-pass").value = ""; ["#sv-name", "#ssh-host", "#sv-user", "#sv-alias", "#sv-keyfile"].forEach(i => $(i).value = ""); $("#ssh-port").value = 22;
    svFill(d); const x = d.servers[d.servers.length - 1]; r.className = "res ok";
    r.textContent = `Готово: «${x.name}» — ${x.system || "вход есть"}. Скажите: «проверь место на сервере ${x.name}».`;
  } catch (e) { r.className = "res bad"; r.textContent = e.message; $("#sv-pass").value = ""; } finally { ev.target.disabled = false; }
};
$("#sv-key-copy").onclick = () => { if (svData && svData.key) navigator.clipboard.writeText(svData.key).then(() => toast("Ключ скопирован")); else toast("Сначала создайте ключ"); };
$("#sv-cmd-copy").onclick = () => {
  if (!(svData && svData.key)) return toast("Сначала создайте ключ");
  const host = $("#ssh-host").value.trim() || "АДРЕС", user = $("#sv-user").value.trim() || "ПОЛЬЗОВАТЕЛЬ", port = +$("#ssh-port").value || 22;
  // для тех, кто не хочет давать пароль Dewiar: та же установка ключа, но руками в терминале
  const cmd = `ssh ${port !== 22 ? "-p " + port + " " : ""}${user}@${host} "mkdir -p ~/.ssh && echo '${svData.key}' >> ~/.ssh/authorized_keys"`;
  navigator.clipboard.writeText(cmd).then(() => toast("Команда скопирована — вставьте её в терминал (PowerShell) и введите пароль сервера"));
};
$("#sv-key-make").onclick = () => core.call("server_key").then(d => { svFill(d); toast("Ключ создан"); }).catch(e => toast(e.message));

/* ---------- MAX ---------- (устроен как Telegram: свой бот или общий бот Dewiar, привязка владельца по коду /start) */
let mxTimer = null, mxWas = null;
function mxFill(t) {
  if (!t) return;
  if (mxWas === false && t.paired) { $("#mx-res").className = "res ok"; $("#mx-res").textContent = "Готово! Напишите боту в MAX что-нибудь — ответит ассистент."; }
  mxWas = !!t.paired;
  $("#mx-setup").style.display = t.connected ? "none" : "";
  $("#mx-pair").style.display = t.connected && !t.paired ? "" : "none";
  $("#mx-on").style.display = t.paired ? "" : "none";
  const link = t.link || (t.bot ? `https://max.ru/${t.bot}` + (t.code ? `?start=${t.code}` : "") : "");
  $("#mx-link").textContent = t.bot || "бот"; $("#mx-link").href = link; $("#mx-open").href = link;
  const box = $("#mx-qr");
  if (t.connected && !t.paired && link && typeof qrcode === "function") {
    if (box.dataset.u !== link) { box.innerHTML = qrPretty(link, "M"); box.dataset.u = link; }
    box.style.display = "";
  } else { box.innerHTML = ""; box.style.display = "none"; }
  $("#mx-code").textContent = "/start " + (t.code || "");
  $("#mx-state").textContent = t.paired ? `Подключён${t.mode === "dewiar" ? " через бота Dewiar" : ""}: ${t.bot_name || t.bot} · владелец ${t.owner || "вы"}` : "";
  $("#mx-notify").checked = t.notify !== false; $("#mx-voice").checked = !!t.voice_home; $("#mx-vreply").checked = t.voice_reply !== false;
  if (t.problem) { $("#mx-res").className = "res bad"; $("#mx-res").textContent = "MAX: " + t.problem; }
  clearInterval(mxTimer); mxTimer = null;
  if (t.connected && !t.paired) mxTimer = setInterval(() => core.call("max_get").then(x => { if (x.paired) mxFill(x); }).catch(() => {}), 2000);
}
async function mxDo(ev, cmd, args, wait) {
  const r = $("#mx-res"); if (ev) ev.target.disabled = true; r.className = "res"; r.textContent = wait || "";
  try { const t = await core.call(cmd, args || {}); r.textContent = ""; mxFill(t); return t; }
  catch (e) { r.className = "res bad"; r.textContent = e.message; } finally { if (ev) ev.target.disabled = false; }
}
$("#mx-shared-go").onclick = (ev) => mxDo(ev, "max_connect_shared", {}, "подключаю…");
$("#mx-connect").onclick = (ev) => mxDo(ev, "max_connect", { token: $("#mx-token").value.trim() }, "проверяю токен…").then(t => { if (t) $("#mx-token").value = ""; });
$("#mx-token").onkeydown = (e) => { if (e.key === "Enter") $("#mx-connect").click(); };
$("#mx-copy").onclick = () => { navigator.clipboard && navigator.clipboard.writeText($("#mx-open").href).then(() => toast("Ссылка скопирована")).catch(() => {}); };
$("#mx-notify").onchange = (e) => core.call("max_set", { patch: { notify: e.target.checked } }).then(mxFill).catch(x => toast(x.message));
$("#mx-vreply").onchange = (e) => core.call("max_set", { patch: { voice_reply: e.target.checked } }).then(mxFill).catch(x => toast(x.message));
$("#mx-voice").onchange = (e) => core.call("max_set", { patch: { voice_home: e.target.checked } }).then(mxFill).catch(x => toast(x.message));
$("#mx-test").onclick = async (ev) => { const t = await mxDo(ev, "max_test", {}, "отправляю…"); if (t) { $("#mx-res").className = "res ok"; $("#mx-res").textContent = "Сообщение отправлено — посмотрите в MAX."; } };
$("#mx-recode").onclick = async () => { const t = await mxDo(null, "max_new_code"); if (t) $("#mx-res").textContent = "Прежний владелец отвязан — новый владелец открывает ссылку и жмёт «Начать»."; };
$("#mx-off").onclick = async () => { const t = await mxDo(null, "max_forget"); if (t) { mxWas = null; $("#mx-res").textContent = "MAX отключён — бот вам больше не пишет."; } };
core.on("max", e => mxFill(e));


/* ---------- Obsidian ---------- */
/* Внешняя ссылка (в т. ч. obsidian://) — через окно: внутри pywebview window.open не откроет другую программу */
function openExt(url) { const a = api(); if (a && a.open_url) a.open_url(url); else window.open(url, "_blank"); }
let obLast = null;
function obFill(o) {
  if (!o) return; obLast = o;
  $("#ob-setup").style.display = o.connected ? "none" : "";
  $("#ob-on").style.display = o.connected ? "" : "none";
  const sel = $("#ob-vault"), cur = sel.value;
  const opts = (o.vaults || []).map(v => [v.path, `${v.name} — ${v.path}`]);
  if (cur && !opts.some(x => x[0] === cur)) opts.unshift([cur, cur]);
  sel.innerHTML = opts.length ? opts.map(([p, t]) => `<option value="${escH(p)}">${escH(t)}</option>`).join("")
                              : `<option value="">Obsidian не найден — выберите папку хранилища</option>`;
  if (cur) sel.value = cur;
  const st = o.stats || {}, moved = (st.to_vault || 0) + (st.from_vault || 0);
  $("#ob-state").textContent = o.connected ? `Хранилище «${o.name}» · папка ${o.folder} · ${o.synced} файлов` +
    (o.last ? ` · сверено в ${new Date(o.last * 1000).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })}` : "") : "";
  $("#ob-search").checked = o.search !== false;
  $("#ob-all").checked = !!o.sync_all;
  const r = $("#ob-res");
  if (o.missing) { r.className = "res bad"; r.textContent = `Папка хранилища не найдена: ${o.vault}. Подключите заново.`;
                   $("#ob-setup").style.display = ""; }
  else if (o.error) { r.className = "res bad"; r.textContent = o.error; }
  else if (st.conflicts) { r.className = "res"; r.textContent = `Заметку правили и в Obsidian, и здесь — сохранены обе версии (${st.conflicts}).`; }
}
$("#ob-pick").onclick = async () => { const a = api(); if (!a) return toast("Выбор папки доступен в окне студии");
  const p = await a.pick_folder(); if (!p) return;
  const sel = $("#ob-vault"); if (![...sel.options].some(o => o.value === p)) sel.insertAdjacentHTML("afterbegin", `<option value="${escH(p)}">${escH(p)}</option>`);
  sel.value = p; };
$("#ob-go").onclick = async (ev) => {
  const r = $("#ob-res"), p = $("#ob-vault").value; if (!p) return $("#ob-pick").click();
  ev.target.disabled = true; r.className = "res"; r.textContent = "подключаю и переношу заметки…";
  try { const o = await core.call("obsidian_connect", { path: p }); obFill(o); r.className = "res ok";
        r.textContent = `Готово: заметки ассистента — в папке «${o.folder}» хранилища «${o.name}».`; }
  catch (e) { r.className = "res bad"; r.textContent = e.message; } finally { ev.target.disabled = false; }
};
$("#ob-search").onchange = (e) => core.call("obsidian_set", { patch: { search: e.target.checked } }).then(obFill).catch(x => toast(x.message));
$("#ob-all").onchange = (e) => core.call("obsidian_set", { patch: { sync_all: e.target.checked } }).then(o => { obFill(o); toast(e.target.checked ? "Хранилище синхронизируется — первая отправка может занять пару минут" : "Синхронизация всего хранилища выключена"); core.call("sync_now").catch(() => {}); }).catch(x => toast(x.message));
$("#ob-sync").onclick = async (ev) => { const r = $("#ob-res"); ev.target.disabled = true;
  try { const o = await core.call("obsidian_sync"); obFill(o); const s = o.stats || {};
        r.className = "res ok"; r.textContent = `Сверено: в Obsidian — ${s.to_vault || 0}, оттуда — ${s.from_vault || 0}.`; }
  catch (e) { r.className = "res bad"; r.textContent = e.message; } finally { ev.target.disabled = false; } };
$("#ob-open").onclick = () => obLast && obLast.open && openExt(obLast.open);
$("#ob-off").onclick = () => core.call("obsidian_forget").then(o => { obFill(o); $("#ob-res").className = "res";
  $("#ob-res").textContent = "Obsidian отключён. Папка Dewiar в хранилище осталась — это ваши заметки."; }).catch(e => toast(e.message));
core.on("obsidian", e => obFill(e));

/* ---------- аккаунт сайта ----------
   Распознавание и голос «с сервера Dewiar» доступны после входа (a.services). Включает и выключает их ядро
   (account_stt/account_tts); локальная правка S — только чтобы кнопка сменилась сразу, точные настройки придут
   событием "settings". */
function renderSrvStt() {
  const a = lastAccount, on = S && S.stt && S.stt.engine === "remote" && S.stt.remote && S.stt.remote.from_account;
  $("#srv-stt").style.display = a && a.logged_in && a.services && a.services.stt ? "" : "none";
  $("#srv-stt-go").textContent = on ? "Выключить" : "Включить";
  $("#srv-stt-go").className = on ? "btn" : "btn primary";
  $("#srv-stt-res").className = on ? "res ok" : "res"; $("#srv-stt-res").textContent = on ? "Включено: распознаёт сервер" : "";
}
$("#srv-stt-go").onclick = async (ev) => {
  const on = !(S.stt.engine === "remote" && S.stt.remote && S.stt.remote.from_account);
  ev.target.disabled = true;
  try { await core.call("account_stt", { on }); S.stt.engine = on ? "remote" : "gigaam"; S.stt.remote = Object.assign({}, S.stt.remote, { from_account: on }); renderSrvStt(); toast(on ? "Распознавание — на сервере" : "Распознавание — на этом компьютере"); }
  catch (e) { toast(e.message); } finally { ev.target.disabled = false; }
};
function renderSrvTts() {
  const a = lastAccount, on = S && S.tts && S.tts.engine === "remote" && S.tts.remote && S.tts.remote.from_account;
  $("#srv-tts").style.display = a && a.logged_in && a.services && a.services.tts ? "" : "none";
  $("#srv-tts-go").textContent = on ? "Выключить" : "Включить";
  $("#srv-tts-go").className = on ? "btn" : "btn primary";
  $("#srv-tts-res").className = on ? "res ok" : "res"; $("#srv-tts-res").textContent = on ? "Включено: говорит сервер" : "";
}
$("#srv-tts-go").onclick = async (ev) => {
  const on = !(S.tts.engine === "remote" && S.tts.remote && S.tts.remote.from_account);
  ev.target.disabled = true;
  try { await core.call("account_tts", { on }); S.tts.engine = on ? "remote" : "vosk"; S.tts.remote = Object.assign({}, S.tts.remote, { from_account: on }); renderSrvTts(); toast(on ? "Голос — с сервера" : "Голос — этого компьютера"); }
  catch (e) { toast(e.message); } finally { ev.target.disabled = false; }
};
function renderAccount(a) {
  if (!a) return;
  lastAccount = a;
  setTimeout(renderSrvStt, 0); setTimeout(renderSrvTts, 0); setTimeout(tgSharedVis, 0);
  $("#acc-out").style.display = a.logged_in ? "none" : ""; $("#acc-in").style.display = a.logged_in ? "" : "none";
  if (!$("#acc-server").value && a.server) $("#acc-server").placeholder = a.server;
  if (!a.logged_in && a.login && !$("#acc-login").value) $("#acc-login").value = a.login;
  const host = (a.server || "").replace(/^https?:\/\//, "");
  $("#acc-who").innerHTML = a.logged_in ? `Вы вошли как <b>${escH(a.user && a.user.login || a.login)}</b> · ${escH(host)}` : "";
  $("#acc-res").textContent = a.problem || "";
}
$("#acc-go").onclick = async () => {
  const login = $("#acc-login").value.trim(), password = $("#acc-pass").value;
  if (!login || !password) return ($("#acc-res").textContent = "Введите логин и пароль");
  $("#acc-go").disabled = true; $("#acc-res").textContent = "Вхожу…";
  try { const a = await core.call("account_login", { server: $("#acc-server").value.trim(), login, password }); $("#acc-pass").value = ""; renderAccount(a); toast("Вход выполнен"); }
  catch (e) { $("#acc-res").textContent = e.message; } finally { $("#acc-go").disabled = false; }
};
$("#acc-pass").onkeydown = (e) => { if (e.key === "Enter") $("#acc-go").click(); };
$("#acc-out-btn").onclick = () => core.call("account_logout").then(renderAccount).then(() => ($("#acc-answer").textContent = "")).catch(e => toast(e.message));
$("#acc-ask").onclick = async () => {
  const q = $("#acc-q").value.trim(); if (!q) return;
  $("#acc-ask").disabled = true; $("#acc-answer").textContent = "Ищу в Знаниях…";
  try { const r = await core.call("account_ask", { question: q }); $("#acc-answer").textContent = r.answer + (r.sources.length ? "\n\nИсточники: " + r.sources.join("; ") : ""); }
  catch (e) { $("#acc-answer").textContent = e.message; } finally { $("#acc-ask").disabled = false; }
};
$("#acc-q").onkeydown = (e) => { if (e.key === "Enter") $("#acc-ask").click(); };
core.on("account", e => renderAccount(e.account));

/* ---------- «Сообщить о проблеме» (core/health.py): complaint_send — слова, снимок экрана (bug_shot снимает экран; из виджета —
   до открытия студии, событие bug_shot или bug_state при открытии), подпись для «Помощников проекта»; complaints — мои
   жалобы с ответами разработчика и помощники проекта; report — только сохранить отчёт файлом; report_offer — ядро
   заметило сбой и предлагает отправлять такие отчёты самому ---------- */
let bugPreview = "";
function bugShow(preview) {
  bugPreview = preview || "";
  const img = $("#bug-img"); img.hidden = !bugPreview; if (bugPreview) img.src = bugPreview;
  $("#bug-empty").hidden = !!bugPreview; $("#bug-use").checked = !!bugPreview; $("#bug-use").disabled = !bugPreview;
  $("#bug-shot").classList.remove("off");
}
function bugFocus(preview) {                                       // из виджета: на «О программе», к форме, снимок — сразу виден
  const b = $('nav button[data-p="about"]'); if (b && !b.classList.contains("on")) b.click();
  if (preview) bugShow(preview);
  setTimeout(() => { $("#bug").scrollIntoView({ behavior: "smooth", block: "start" }); $("#bug").classList.add("flash"); $("#rep-note").focus(); }, 120);
  setTimeout(() => $("#bug").classList.remove("flash"), 1800);
}
const BUG_ST = { new: "отправлена", seen: "прочитана", work: "в работе", fixed: "исправлено", no: "не ошибка" };
function bugRender(v) {
  if (!v) return;
  if (v.who !== undefined && !$("#bug-who").value) $("#bug-who").value = v.who || "";
  const mine = (v.mine || []).slice(0, 8);
  $("#bug-mine").innerHTML = mine.length ? '<div class="bugh">Мои жалобы</div>' + mine.map(c =>
    `<div class="bugc"><span class="n">№${c.id}</span><span class="t">${escH(c.note || "")}</span><span class="st"><span class="chip ${c.status}">${BUG_ST[c.status] || c.status}`
    + `${c.status === "fixed" && c.fixed ? " в " + escH(c.fixed) : ""}</span>${new Date(c.ts * 1000).toLocaleDateString("ru")}${c.shot ? " · со снимком" : ""}`
    + `${c.reward ? ` · спасибо ${c.reward} тал.` : ""}</span>${c.reply ? `<span class="reply">${escH(c.reply)}</span>` : ""}</div>`).join("") : "";
  const th = v.thanks || [];
  $("#bug-thanks").innerHTML = th.length ? '<div class="bugh">Помощники проекта — их жалобы сделали Dewiar лучше</div><div class="thx">'
    + th.map(p => `<span title="подтверждено: ${p.n}, исправлено: ${p.fixed}">${escH(p.name)}<b>${p.n}</b></span>`).join("") + "</div>" : "";
}
$("#bug-img").onclick = (e) => e.target.classList.toggle("zoom");
$("#bug-use").onchange = (e) => $("#bug-shot").classList.toggle("off", !e.target.checked);
$("#bug-snap").onclick = guardBtn(async () => {
  const r = $("#rep-res"); r.className = "res"; r.textContent = "снимаю экран…";
  try { const x = await core.call("bug_shot"); if (x.ok) { bugShow(x.preview); r.textContent = ""; } else { r.className = "res bad"; r.textContent = "Не снялся: " + (x.error || ""); } }
  catch (e) { r.className = "res bad"; r.textContent = e.message; }
});
$("#bug-send").onclick = guardBtn(async () => {
  const r = $("#rep-res"), note = $("#rep-note").value.trim();
  if (note.length < 3) { r.className = "res bad"; r.textContent = "Напишите хотя бы пару слов — что пошло не так"; $("#rep-note").focus(); return; }
  r.className = "res"; r.textContent = "собираю и отправляю…";
  try {
    const x = await core.call("complaint_send", { note, who: $("#bug-who").value.trim(), shot: !!bugPreview && $("#bug-use").checked });
    r.className = "res ok"; r.textContent = `Жалоба №${x.id} у разработчика — спасибо! Ответ придёт сюда.`;
    $("#rep-note").value = ""; bugShow("");
    core.call("complaints").then(bugRender).catch(() => {});
  } catch (e) { r.className = "res bad"; r.textContent = e.message; }
});
function guardBtn(fn) { return async (ev) => { const b = ev.currentTarget; if (b.disabled) return; b.disabled = true; try { await fn(ev); } finally { b.disabled = false; } }; }
core.on("bug_shot", e => bugFocus(e.preview));
core.on("complaints", bugRender);
$('nav button[data-p="about"]') && $('nav button[data-p="about"]').addEventListener("click", () => core.call("complaints").then(bugRender).catch(() => {}));
core.on("hello", () => core.call("bug_state").then(x => { if (x && x.preview) bugFocus(x.preview); }).catch(() => {}));
core.on("report_offer", e => { $("#rep-offer-t").textContent = e.summary ? `(${e.summary.slice(0, 160)})` : ""; $("#rep-offer").hidden = false; });
const repAuto = (on) => core.call("report_auto", { on }).then(() => { $("#rep-offer").hidden = true; const cb = document.querySelector('[data-k="report.auto"]'); if (cb) cb.checked = on; toast(on ? "При сбое отчёт уйдёт сам" : "Хорошо, не отправляю"); });
$("#rep-yes").onclick = () => repAuto(true);
$("#rep-no").onclick = () => repAuto(false);
$("#rep-go").onclick = async (ev) => {
  ev.target.disabled = true; const r = $("#rep-res"); r.className = "res"; r.textContent = "собираю…";
  try { const path = await core.call("report"); r.className = "res ok"; r.textContent = "Сохранено: " + path; }
  catch (e) { r.className = "res bad"; r.textContent = e.message; } finally { ev.target.disabled = false; }
};
$("#up-check").onclick = () => { $("#up-state").textContent = "Проверяю…"; core.call("update_check").then(renderUpdate).catch(e => toast(e.message)); };
core.on("update", e => renderUpdate(e.update));

/* ---------- суфлёр (core/prompter.py): открыть окно и итоги прошлых встреч (папка «Встречи») ---------- */
$("#pr-open").onclick = () => { const a = api(); if (a && a.open_prompter) a.open_prompter(); else core.call("prompter_open").catch(e => toast(e.message)); };
function loadMeetings() {
  core.call("prompter_meetings").then(l => {
    $("#pr-list").innerHTML = l.length ? l.map(m => `<button class="pr-it" data-p="${escH(m.path)}"><b>${escH(m.name.replace(/^(\d{4})-(\d\d)-(\d\d) (\d\d)(\d\d) /, "$3.$2.$1 $4:$5 — "))}</b><span>Открыть итог</span></button>`).join("")
      : `<p class="hint">Пока встреч не было. Итог каждой появится здесь.</p>`;
    $$("#pr-list .pr-it").forEach(b => b.onclick = () => core.call("ws_open", { path: b.dataset.p }).catch(e => toast(e.message)));
  }).catch(() => {});
}

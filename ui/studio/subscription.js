/* Отдельный профиль подписки и явные разрешения контекста.
   Отрисовка не запрашивает аккаунты и модели: только нажатия пользователя. */
function renderSubscriptionProfile(box, id, p) {
  const codex = p.subscription_transport === 'codex';
  const title = codex ? 'Codex по подписке — отдельный режим' : 'ChatGPT SIWC — отдельный режим';
  const el = document.createElement('div');
  el.className = 'prof' + (S.llm.active === id ? ' on' : '') + (openProf === id ? ' open' : '');
  el.innerHTML = `<div class="head"><input type="radio" name="act" title="Сделать активной"><div class="t"><b>${title}</b><small></small></div><span class="res"></span><button class="btn small">Настроить</button></div>
  <div class="body"><p class="hint">Личный локальный прототип. Обработка — в OpenAI, не на этом ПК. По умолчанию отправляется только текущий текст. Дополнительные данные Codex — только по галочкам ниже. Hermes / Human / семантическая память автоматически не подключаются. Другие аккаунты Windows имеют отдельное хранилище; профили одного пользователя Windows не являются границей защиты от этого пользователя.</p>
  <label class="f">Способ подключения<select data-field="transport"><option value="codex">Codex — официальный app-server, собственный вход</option><option value="siwc">SIWC — отдельное разрешение приложения (SDK устанавливается отдельно)</option></select></label>
  <p class="hint">${codex ? 'Отдельный профиль Codex в защищённом хранилище Windows. Токены из Hermes и основного Codex не копируются. Используется установленный проверенный CLI; правила организации сохраняются.' : 'SIWC требует отдельного допуска аккаунта и приложения. Ошибка 3p_delegated_access_policy_denied не исправляется сменой имени агента.'} Переключение режима сбросит выбор аккаунта, модели и подтверждения, но не удалит вход.</p>
  <div class="actions"><button class="btn" data-op="profiles">Аккаунты: обновить локально</button><button class="btn" data-op="login-new">Войти в новый аккаунт ChatGPT</button><button class="btn" data-op="login">Переподключить выбранный</button></div>
  <div class="row"><label class="f">Аккаунт<select data-field="account"></select></label><label class="f">Модель<select data-field="model"></select></label></div>
  <div class="actions"><button class="btn" data-op="models">Получить модели аккаунта</button><button class="btn" data-op="health">Проверить установку без сети</button><button class="btn danger" data-op="disconnect">Отключить аккаунт</button></div>
  <p><label><input type="checkbox" data-field="export"> Разрешаю отправлять текущий текст в OpenAI.</label></p>
  <p><label><input type="checkbox" data-field="usage"> Я проверил ${codex ? 'доступ к Codex, лимиты и расход кредитов рабочего пространства' : 'разрешения приложения, лимит и использование кредитов в ChatGPT Usage'}.</label> <a href="https://chatgpt.com/settings/usage" target="_blank" rel="noopener noreferrer">ChatGPT Usage</a></p>
  <fieldset ${codex ? '' : 'hidden'}><legend>Дополнительные разрешения Codex — выключены по умолчанию</legend>
  <p><label><input type="checkbox" data-field="history"> Отправлять короткую историю этого профиля за текущий сеанс (до 3 пар сообщений).</label></p>
  <p><label><input type="checkbox" data-field="memory_read"> Читать и отправлять память Dewiar «Обо мне» (до 2500 символов).</label></p>
  <p><label><input type="checkbox" data-field="memory_write"> Предлагать запись в память «Обо мне» — каждый факт с отдельным подтверждением.</label></p>
  <p><label><input type="checkbox" data-field="tasks"> Разрешить фоновые задачи Codex. Каждый запуск требует подтверждения; лимит сохраняется при продолжении.</label></p>
  <p><label><input type="checkbox" data-field="project_read"> В задачах читать текстовые исходники выбранного человеком проекта и отправлять фрагменты в OpenAI.</label></p>
  <p><label><input type="checkbox" data-field="task_review"> Самопроверка итога задачи отдельным запросом, в общем лимите. Это не независимая приёмка.</label></p>
  <p><label><input type="checkbox" data-field="task_learning"> Черновик урока из текущей задачи отдельным запросом, в общем лимите. Сохраняется рядом с итогом, не применяется к общей памяти автоматически.</label></p>
  <p><label><input type="checkbox" data-field="auxiliary"> Служебные текстовые функции: черновики навыков и оценка сценариев. Разрешаю отправлять подготовленные инструкции, сценарий, разговор и память, переданные этой функции.</label></p>
  <p><label><input type="checkbox" data-field="meeting"> Встречи и суфлёр: отправлять расшифровку, материалы и выбранные знания, получать подсказки и итоги. Каждый вызов расходует лимит; автоматические подсказки управляются настройками встречи.</label></p>
  <p><label><input type="checkbox" data-field="diary"> Дневник: отправлять дневной материал, память и подсказку персонажа по расписанию дневника. Запись дневника и души выполняет обычный модуль Dewiar.</label></p>
  <label class="f">Максимум запросов на одну задачу (1–20)<input type="number" min="1" max="20" step="1" data-field="task_limit" value="5"></label>
  <div class="actions"><button class="btn" data-op="use-tasks">Выбрать этот профиль для задач</button></div>
  <p class="hint">Контекст ограничивается локально. Нет команд оболочки, записи в проект, MCP, скачивания, подзадач и автоматических повторов. Изменение аккаунта или разрешений останавливает текущий запрос; для ранее привязанной задачи создайте новую. Известные секретные пути исключены, но не выбирайте проект с конфиденциальными данными.</p></fieldset>
  <p class="hint">Нет API-ключа, автоматического переключения режима и повтора после ошибки. Вход не гарантирует отсутствие расхода кредитов. ${codex ? 'Режим только для локального клиента. Нативные инструменты Codex отключены; ограниченные действия выполняет Dewiar после своих проверок.' : 'Для бизнеса нужна отдельная проверка лицензии DevKit. SIWC остаётся только текстовым.'}</p>
  <div class="actions"><button class="btn danger" data-op="remove">Удалить профиль Dewiar (не отзывает доступ)</button></div></div>`;
  const res = $('.res', el), account = $('[data-field="account"]', el), model = $('[data-field="model"]', el);
  const option = (select, value, label) => { const o = document.createElement('option'); o.value = value; o.textContent = label; select.appendChild(o); };
  option(account, '', 'Выберите аккаунт после локального обновления');
  if (p.subscription_profile_id) option(account, p.subscription_profile_id, p.subscription_label || p.subscription_profile_id);
  account.value = p.subscription_profile_id || '';
  option(model, '', 'Получите список и выберите модель');
  if (p.model) option(model, p.model, p.model);
  model.value = p.model || '';
  $('small', el).textContent = `${p.subscription_label || 'Аккаунт не выбран'} · ${p.model || 'модель не выбрана'} · ${codex ? 'разрешения ниже' : 'только текущий текст'}`;
  const persist = () => {
    if (!S.llm.profiles[id]) return Promise.reject(new Error('Профиль уже удалён.'));
    S.llm.profiles[id] = p;
    return save({llm: {profiles: S.llm.profiles}}, true);
  };
  const capabilities = ['history', 'memory_read', 'memory_write', 'tasks', 'project_read', 'task_review', 'task_learning', 'auxiliary', 'meeting', 'diary'];
  const changedScope = () => { p.subscription_scope_revision = uid() + '-' + Date.now(); };
  const clearConsent = () => {
    p.subscription_export = false; p.subscription_usage_reviewed = false;
    capabilities.forEach(k => { p['subscription_' + k] = false; }); changedScope();
  };
  const syncChecks = () => {
    $('[data-field="export"]', el).checked = p.subscription_export === true;
    $('[data-field="usage"]', el).checked = p.subscription_usage_reviewed === true;
    capabilities.forEach(k => { $('[data-field="' + k + '"]', el).checked = p['subscription_' + k] === true; });
  };
  syncChecks();
  $('[data-field="task_limit"]', el).value = p.subscription_task_limit ?? 5;
  $('[data-field="task_limit"]', el).onchange = async ev => {
    const n = Number(ev.target.value);
    if (!Number.isInteger(n) || n < 1 || n > 20) { ev.target.value = p.subscription_task_limit ?? 5; toast('Лимит: целое число от 1 до 20.'); return; }
    p.subscription_task_limit = n; changedScope(); await persist();
  };
  capabilities.forEach(k => {
    $('[data-field="' + k + '"]', el).onchange = async ev => {
      if (p.subscription_transport !== 'codex') { ev.target.checked = false; return; }
      p['subscription_' + k] = ev.target.checked === true; changedScope(); await persist();
    };
  });
  $('[data-field="transport"]', el).value = codex ? 'codex' : 'siwc';
  $('[data-field="transport"]', el).onchange = async ev => {
    if (!['codex', 'siwc'].includes(ev.target.value)) return;
    p.subscription_transport = ev.target.value;
    p.name = ev.target.value === 'codex' ? 'Codex по подписке' : 'ChatGPT SIWC';
    p.subscription_profile_id = ''; p.subscription_label = ''; p.model = '';
    clearConsent(); await persist(); renderProfiles();
  };
  $('.head input', el).checked = S.llm.active === id;
  $('.head input', el).onclick = async ev => {
    ev.stopPropagation();
    if (!p.subscription_profile_id || !p.model || !p.subscription_export || !p.subscription_usage_reviewed) {
      ev.target.checked = false; toast('Сначала выберите аккаунт, модель и подтвердите передачу текста/Usage.'); return;
    }
    await save({llm: {active: id}}); renderProfiles();
  };
  $('.head .btn', el).onclick = ev => { ev.stopPropagation(); openProf = openProf === id ? null : id; renderProfiles(); };
  account.onchange = async () => {
    p.subscription_profile_id = account.value;
    p.subscription_label = account.options[account.selectedIndex].textContent;
    p.model = ''; clearConsent(); await persist(); renderProfiles();
  };
  model.onchange = async () => { p.model = model.value; changedScope(); await persist(); };
  $('[data-field="export"]', el).onchange = async ev => { p.subscription_export = ev.target.checked; changedScope(); await persist(); };
  $('[data-field="usage"]', el).onchange = async ev => { p.subscription_usage_reviewed = ev.target.checked; changedScope(); await persist(); };
  $$('[data-op]', el).forEach(button => button.onclick = async () => {
    const op = button.dataset.op;
    if (op === 'use-tasks') {
      if (p.subscription_transport !== 'codex' || !p.model || !p.subscription_profile_id || p.subscription_tasks !== true || !p.subscription_export || !p.subscription_usage_reviewed) {
        toast('Выберите аккаунт, модель, подтверждения текста/Usage и галочку фоновых задач.'); return;
      }
      await save({tasks: {llm: id}}); toast('Профиль назначен для задач. Существующие задачи не запускались.'); return;
    }
    if (op === 'remove') {
      delete S.llm.profiles[id];
      const patch = {llm: {profiles: S.llm.profiles}};
      if (S.llm.active === id) patch.llm.active = '';
      await save(patch); renderProfiles(); return;
    }
    if (['models', 'login', 'disconnect'].includes(op) && !p.subscription_profile_id) { toast('Сначала выберите аккаунт.'); return; }
    if (op === 'disconnect' && !confirm(codex ? 'Выйти только из выбранного локального профиля Codex? Основной Codex и Hermes не изменятся.' : 'Отозвать доступ выбранного аккаунта для этого локального приложения?')) return;
    $$('[data-op]', el).forEach(b => { b.disabled = true; });
    res.textContent = op.startsWith('login') ? 'Завершите вход в открывшемся браузере…' : 'Выполняю…';
    try {
      const requestedAccount = p.subscription_profile_id;
      const requestedTransport = p.subscription_transport || 'siwc';
      const args = {transport: requestedTransport, ...(op === 'login-new' || ['health', 'profiles'].includes(op) ? {} : {profile: p.subscription_profile_id})};
      const r = await core.call('subscription_' + (op === 'login-new' ? 'login' : op), args);
      if (!S.llm.profiles[id] || requestedTransport !== (p.subscription_transport || 'siwc') || (op !== 'login-new' && requestedAccount !== p.subscription_profile_id)) throw new Error('Профиль изменился. Результат старой операции не применён.');
      if (!r.ok) throw new Error(r.error || 'Операция не завершена');
      const d = r.data;
      if (op === 'profiles') {
        account.innerHTML = ''; option(account, '', 'Выберите аккаунт');
        d.profiles.forEach(a => option(account, a.id, `${a.label} · ${a.status}${codex ? ' · сохранённый статус, не live-проверка' : (a.sharing ? ' · план разрешён' : ' · без плана')}`));
        account.value = p.subscription_profile_id || '';
        res.textContent = `Локальных аккаунтов: ${d.profiles.length}. Сеть не использовалась.`;
      } else if (op.startsWith('login')) {
        if (!d.profile) throw new Error('Вход не завершён');
        p.subscription_profile_id = d.profile; p.subscription_label = d.profile; p.model = ''; clearConsent();
        await persist(); renderProfiles(); toast(d.sharing ? 'Аккаунт подключён. Получите модели и проверьте Usage.' : 'Вход выполнен, но использование плана не разрешено.');
      } else if (op === 'models') {
        model.innerHTML = ''; option(model, '', 'Выберите модель');
        d.models.forEach(m => option(model, m.id, m.label || m.id));
        model.value = d.models.some(m => m.id === p.model) ? p.model : '';
        if (!model.value) { p.model = ''; await persist(); }
        res.textContent = `Моделей: ${d.models.length}. Генерация не запускалась.`;
      } else if (op === 'disconnect') {
        clearConsent(); await persist(); syncChecks(); res.textContent = codex ? 'Выход из отдельного профиля Codex выполнен.' : 'Доступ отозван. Профиль сохранён без активной сессии.';
      } else {
        res.textContent = d.dependency_ready ? 'Локальная установка готова. Вход и inference не проверялись.' : 'Не найдена среда выполнения.';
      }
    } catch (e) { res.textContent = e.message || 'Операция не завершена'; }
    finally { $$('[data-op]', el).forEach(b => { b.disabled = false; }); }
  });
  box.appendChild(el);
}

$('#subscription-add').onclick = () => {
  const id = uid();
  S.llm.profiles[id] = {name: 'Codex по подписке', kind: 'chatgpt_subscription', subscription_transport: 'codex', base_url: '',
    model: '', subscription_profile_id: '', subscription_export: false, subscription_usage_reviewed: false};
  openProf = id;
  save({llm: {profiles: S.llm.profiles}}, true).then(renderProfiles);
};
$('#subscription-add').textContent = 'Добавить Codex по подписке (отдельный локальный режим)';

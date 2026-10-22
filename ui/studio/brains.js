/* Именованные мозги по контурам и локальный heartbeat. Обновляем только метаданные ядра.
   Поллинг не вызывает модель; текст журнала и имена вставляются через textContent. */
const BRAIN_ROLES = {tasks: 'Задачи', auxiliary: 'Черновики навыков', meeting: 'Встречи и суфлёр', diary: 'Дневник'};
const BRAIN_STATES = {running: 'выполняется', completed: 'ответ завершён', failed: 'ошибка', interrupted: 'прервано',
  no_fresh_signal: 'нет свежего сигнала — исход неизвестен', outcome_unknown: 'предыдущая сессия — исход неизвестен',
  queued: 'в очереди', waiting: 'ждёт человека', paused: 'на паузе', sleeping: 'ожидает', done: 'завершена', stopped: 'остановлена'};
function renderBrainRoutes() {
  if (!S) return;
  const box = $('#brain-routes'), profiles = S.llm.profiles || {};
  if (box.contains(document.activeElement)) return;
  $('#brains-count').textContent = `Подключённые мозги · ${Object.keys(profiles).length}`;
  box.replaceChildren();
  for (const [role, label] of Object.entries(BRAIN_ROLES)) {
    const field = document.createElement('label'); field.className = 'f'; field.textContent = label;
    const select = document.createElement('select'); select.dataset.role = role;
    const add = (id, text) => { const option = document.createElement('option'); option.value = id; option.textContent = text; select.appendChild(option); };
    add('', 'По основному мозгу');
    Object.entries(profiles).forEach(([id, p]) => add(id, `${p.name || 'Без названия'}${p.model ? ' · ' + p.model : ''}`));
    const chosen = (role === 'tasks' ? S.tasks?.llm : S.llm.routes?.[role]) || '';
    if (chosen && !profiles[chosen]) add(chosen, 'Профиль удалён — контур заблокирован');
    select.value = chosen; field.appendChild(select); box.appendChild(field);
  }
  $('#brain-journal').checked = S.brain_watch?.journal !== false;
  $('#brain-stale').value = S.brain_watch?.stale_seconds || 90;
}
$('#brain-routes-save').onclick = async () => {
  const routes = Object.fromEntries($$('#brain-routes select').map(el => [el.dataset.role, el.value]));
  try { S = await core.call('brain_routes_set', {routes}); renderBrainRoutes(); toast('Назначения сохранены. Модели и задачи не запускались.'); }
  catch (e) { toast(e.message); }
};
$('#brain-watch-save').onclick = async () => {
  try {
    S = await core.call('brain_watch_set', {journal: $('#brain-journal').checked, stale_seconds: Number($('#brain-stale').value)});
    renderBrainRoutes(); await refreshBrainWatch();
  } catch (e) { toast(e.message); }
};
let brainReading = false;
async function refreshBrainWatch() {
  if (brainReading || !S) return;
  brainReading = true;
  try {
    const s = await core.call('brain_watch_status');
    const when = t => t == null ? '—' : new Date(t * 1000).toLocaleString('ru-RU');
    $('#brain-watch-state').textContent = s.storage_error ? 'Журнал недоступен: покрытие неполное. Работа моделей не перезапускается.'
      : `Наблюдатель ответил: ${when(s.observed_at)}. Журнал ${s.journal ? 'включён' : 'выключен'}. Показаны до 100 последних вызовов; задачи: ${(s.tasks || []).length}. Состояние сервера без вызова неизвестно.`;
    const box = $('#brain-runs'); box.replaceChildren();
    for (const run of s.runs || []) {
      const row = document.createElement('div'); row.className = 'prof';
      row.textContent = `${s.profiles?.[run.profile] || 'Удалённый / неназначенный мозг'} · ${BRAIN_ROLES[run.role] || run.role} · ${BRAIN_STATES[run.state] || 'неизвестно'} · ${Math.round(run.elapsed_s)} с · последний сигнал: ${when(run.last_signal)}`;
      box.appendChild(row);
    }
    for (const task of s.tasks || []) {
      const row = document.createElement('div'); row.className = 'hint';
      row.textContent = `Задача ${task.ref}: ${BRAIN_STATES[task.state] || 'неизвестно'}`; box.appendChild(row);
    }
    $('#brain-events').textContent = (s.events || []).map(e => `${when(e.at)} · ${e.kind} · ${e.ref}${e.state ? ' · ' + (BRAIN_STATES[e.state] || 'неизвестно') : ''}`).join('\n') || 'Событий ещё нет.';
  } catch (_) { $('#brain-watch-state').textContent = 'Нет свежего ответа ядра. Состояние моделей неизвестно.'; }
  finally { brainReading = false; }
}
$('#brain-watch-refresh').onclick = refreshBrainWatch;
$('nav button[data-p="brain"]').addEventListener('click', () => { renderBrainRoutes(); refreshBrainWatch(); });
core.on('settings', e => { S = e.settings; renderBrainRoutes(); });
setInterval(() => { if (!document.hidden && $('#p-brain').classList.contains('cur')) refreshBrainWatch(); }, 5000);

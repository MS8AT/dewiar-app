/* Чистая проекция безопасного состояния квоты в одно действие интерфейса.
   Никаких запросов к модели и автоматического продолжения задачи здесь нет. */
function taskQuotaAction(task) {
  const quota = task && task.subscription_quota;
  if (!quota || quota.valid !== true || quota.exhausted !== true) return null;
  if (quota.can_grant === true && Number.isInteger(quota.grant_default) && quota.grant_default >= 1 && quota.grant_default <= 20) {
    return {kind: "grant", count: quota.grant_default, label: `Выдать ещё ${quota.grant_default} запросов`};
  }
  return {kind: "blocked", label: `Достигнут общий лимит Codex (${quota.max_limit || 100})`};
}

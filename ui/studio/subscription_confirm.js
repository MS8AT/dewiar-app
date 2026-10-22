/* Локальные подтверждения Codex видны и в студии, а не только в виджете.
   После перезагрузки читаем текущий вопрос; nonce исключает ответ на чужой/старый вопрос. */
(() => {
  let active = null, revision = 0;
  const close = () => { if (active) active.box.remove(); active = null; };
  const show = data => {
    if (!data || !data.id) { close(); return; }
    if (active && active.id === data.id) return;
    close();
    const box = document.createElement('div'); box.className = 'prof';
    box.setAttribute('role', 'dialog'); box.setAttribute('aria-label', 'Подтверждение Codex');
    box.style.cssText = 'position:fixed;z-index:20000;top:16px;left:50%;transform:translateX(-50%);width:min(640px,92vw);max-height:85vh;overflow:auto;padding:20px;background:var(--bg,#dbe6f2);box-shadow:0 12px 40px #0005;';
    const text = document.createElement('p'); text.textContent = data.text; text.style.whiteSpace = 'pre-wrap'; box.appendChild(text);
    const id = data.id;
    for (const [label, ok] of [['Разрешить', true], ['Отказать', false]]) {
      const button = document.createElement('button'); button.className = 'btn'; button.textContent = label;
      button.onclick = async () => {
        button.disabled = true;
        try {
          const r = await core.call('subscription_confirm_answer', {id, ok});
          if (!r.ok) throw new Error(r.error || 'Подтверждение не принято');
          if (active && active.id === id) { revision++; close(); }
        } catch (e) { button.disabled = false; toast(e.message); }
      };
      box.appendChild(button);
    }
    document.body.appendChild(box); active = {id, box};
  };
  let reading = false;
  const sync = async () => {
    if (reading) return;
    reading = true;
    const before = revision;
    try { const r = await core.call('subscription_confirm_get'); if (r.ok && before === revision) show(r.data); } catch (_) { }
    finally { reading = false; }
  };
  core.on('confirm', e => { if (e.source === 'subscription') { revision++; show(e); } });
  core.on('confirm_done', e => { if (active && active.id === e.id) { revision++; close(); } });
  window.addEventListener('focus', sync);
  setInterval(sync, 2500); sync(); // Только локальное состояние вопроса, без аккаунтов/моделей/сети OpenAI.
})();

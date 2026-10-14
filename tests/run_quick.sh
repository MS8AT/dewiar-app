#!/bin/bash
# Быстрые проверки (~3 минуты): без звука, моделей распознавания и PostgreSQL — то, что гоняет GitHub на каждую запись.
# Полный набор — tests/run_all.sh. Использование: tests/run_quick.sh [python]
# Те же правила, что в run_all.sh: проверка пройдена, только если нет ❌ И код выхода 0.
TMPROOT=$(mktemp -d); export TMPDIR="$TMPROOT"; trap 'rm -rf "$TMPROOT"' EXIT
PY=${1:-python3}; T="$(cd "$(dirname "$0")" && pwd)"; ROOT="$(dirname "$T")"
export DEWIAR_PY=${DEWIAR_PY:-$PY} DEWIAR_FAKE_RAM_GB=${DEWIAR_FAKE_RAM_GB:-16} DEWIAR_FAKE_CORES=${DEWIAR_FAKE_CORES:-8}
FAIL=0
gh_error() {   # в GitHub Actions — ещё и пометка с причиной: журнал целиком там видно не всем, пометки — всем
  [ -n "$GITHUB_ACTIONS" ] || return 0
  local m=$2; m=${m//'%'/'%25'}; m=${m//$'\n'/'%0A'}; echo "::error title=$1::$m"
  printf '### ❌ %s\n```\n%s\n```\n' "$1" "$2" >> "${GITHUB_STEP_SUMMARY:-/dev/null}"; }
run() { local name=$1; shift; local out; local ws; ws=$(mktemp -d)
  out=$(DEWIAR_WORKSPACE_DIR=$ws timeout 300 "$@" 2>&1 | tr -d "\r"; echo "RC=${PIPESTATUS[0]}"); local rc=${out##*RC=}; out=${out%RC=*}
  local ok=$(grep -c "✅" <<<"$out"); local bad=$(grep "❌" <<<"$out")
  if [ -z "$bad" ] && [ "$rc" = 0 ] && { [ "$ok" -gt 0 ] || grep -qE "ALL OK|^OK$" <<<"$out"; }; then printf "✅ %-34s %s\n" "$name" "$ok"
  else printf "❌ %-34s (код %s)\n%s\n" "$name" "$rc" "$bad$(tail -5 <<<"$out")"; FAIL=1; gh_error "$name" "$bad
$(tail -15 <<<"$out")"; fi; }

echo "== Синтаксис"
if $PY -m compileall -q -x '/(vendor|node_modules)/' "$ROOT/core" "$ROOT/ui" "$ROOT/tools" "$ROOT/server" "$ROOT/tests" "$ROOT/packaging/dewiar-server" >/dev/null; then
  echo "✅ Python"; else echo "❌ Python"; FAIL=1; gh_error Python "$($PY -m compileall -q "$ROOT/core" "$ROOT/ui" 2>&1 | tail -5)"; fi
if command -v node >/dev/null; then
  bad=$(for f in "$ROOT"/android/assets/www/*.js "$ROOT"/ui/studio/*.js; do node --check "$f" 2>/dev/null || echo "$f"; done)
  [ -z "$bad" ] && echo "✅ JavaScript" || { echo "❌ JavaScript: $bad"; FAIL=1; gh_error JavaScript "$bad"; }
fi

echo "== Ядро"
run "текст, имена"                  $PY "$T/unit_test.py"
run "версия: окно читает верно"     $PY "$T/version_read_test.py"
run "мозг: форматы серверов"        $PY "$T/llm_compat_test.py"
run "размышления и код не в ответе" $PY "$T/reasoning_test.py"
run "руки: модули"                  $PY "$T/tools_unit_test.py"
run "руки без флагов на сервере"    $PY "$T/prompt_tools_test.py"
run "подключение, навыки, MCP"      $PY "$T/stage5_unit_test.py"
run "папка ассистента"              $PY "$T/workspace_test.py"
run "задачи и режим кода"           $PY "$T/tasks_test.py"
run "задачи: части одновременно"    $PY "$T/task_parts_test.py"
run "задачи: вызовы голым JSON"     $PY "$T/bare_calls_test.py"
run "голоса в отдельном процессе"    $PY "$T/tts_proc_test.py"
run "голос своим ключом: ElevenLabs" $PY "$T/tts_eleven_test.py"
run "что голос не читает вслух"     $PY "$T/speak_text_test.py"
run "уроки из поправок в разговоре"  $PY "$T/lessons_talk_test.py"
run "сам замечает, что вернулись"     $PY "$T/welcome_test.py"
run "знакомство при первом запуске"   $PY "$T/intro_test.py"
run "пауза конца фразы под манеру речи" $PY "$T/pause_learn_test.py"
run "голос: следующая фраза готовится заранее" $PY "$T/speak_prefetch_test.py"
run "границы: грубость в адрес помощника, отказы" $PY "$T/boundaries_test.py"
run "персонажи: Лира и Патрик, остальные — шаблоны" $PY "$T/personas_templates_test.py"
run "ночной обход: сбои, повтор задач, утренняя фраза" $PY "$T/night_test.py"
run "нехватка памяти — подсказка"     $PY "$T/memory_pressure_test.py"
run "потолки памяти Dewiar"         $PY "$T/memcap_test.py"
run "сигнал «ваша очередь»"         $PY "$T/turn_cue_test.py"
run "телефон: подключение, фото, ответ в рамке" $PY "$T/android_attach_test.py"
run "виджет: картинка из буфера обмена"   $PY "$T/hud_paste_test.py"
run "виджет: тесно — ответ виден, ничего не наезжает" $PY "$T/hud_tight_test.py"
run "сложная просьба — модель думает"  $PY "$T/think_auto_test.py"
run "оформление: темы и анимация голоса" $PY "$T/look_test.py"
run "телефон: звук напоминаний" $PY "$T/android_sound_test.py"
run "«Близкие»: шифрование (Python и JS)" $PY "$T/close_crypto_test.py"
run "«Близкие»: чужие данные и брошенный звонок" $PY "$T/close_robust_test.py"
run "телефон: чужой код и чужие ссылки" $PY "$T/android_safety_test.py"
run "голос с сервера: клиент" $PY "$T/tts_client_test.py"
run "«Рефералы»: созвездие, ссылка, «Позвать в Близкие»" $PY "$T/refs_section_test.py"
run "голос телефона: наперёд и запомненные фразы" $PY "$T/voice_cache_test.py"
run "суфлёр: «Закончить встречу?» внутри окна" $PY "$T/prompter_end_test.py"
run "телефон на планшете: облик, ответ и панель в одной полосе" $PY "$T/android_tablet_test.py"
run "студия: суфлёр на нескольких мониторах, пополнение, плитки «Мозга»" $PY "$T/studio_polish_test.py"
run "ядро: данные не затирают методы" $PY "$T/engine_names_test.py"
run "телефон: длинная диктовка" $PY "$T/android_dictation_test.py"
run "персонажи не отвечают друг за друга" $PY "$T/team_window_test.py"
run "маршрут на карте: координаты, адрес, Яндекс и Google" $PY "$T/route_test.py"
run "персонажи: живые характеры и правило разговора" $PY "$T/personas_talk_test.py"
run "«Что нового» после обновления: студия, приветствие, телефон" $PY "$T/news_test.py"
run "честное «готово» у фоновых задач" $PY "$T/task_honest_test.py"
run "радио: «играет», а звука нет" $PY "$T/radio_silent_test.py"
run "служба голосов Qwen3-TTS: фразы, персонажи, свои голоса, поток" $PY "$T/voices_service_test.py"
run "телефон: голос сервера не ответил — говорит голосом телефона" $PY "$T/android_voice_fallback_test.py"
run "телефон: календарь — что у меня завтра, запись после «да»" $PY "$T/android_calendar_test.py"
run "лицо говорит губами только под звук: голос с сервера ещё не пришёл — рот закрыт" $PY "$T/lipsync_test.py"
run "диктовка удержанием на компьютере: держите облик или пробел — сколько угодно, отпустили — ушло" $PY "$T/hold_dictation_test.py"
run "телефон: первая фраза ответа — в голос по запятой, раньше" $PY "$T/android_first_phrase_test.py"
run "студия: «Чат» — вся переписка, писать текстом; в виджете вместо «Памяти»" $PY "$T/studio_chat_test.py"
run "телефон: микрофон Bluetooth-наушников (SCO) на время слушания" $PY "$T/android_btmic_test.py"
run "экзамен 14.10: память на день недели, длинные и пустые страницы, число минут таймера" $PY "$T/exam1014_test.py"
run "масштаб интерфейса и текста (Ctrl + / Ctrl −), окна под масштаб" $PY "$T/zoom_test.py"
run "экзамен 13.10: заметки, близкие, правдивые советы" $PY "$T/exam1013_test.py"
run "телефон: заметки, фото и файлы" $PY "$T/android_notes_test.py"
run "студия: заметки и поиск" $PY "$T/studio_notes_test.py"
run "короткие фразы: спасибо, ослышанное имя" $PY "$T/voice_short_test.py"
run "сервер: dewiar-server setup"   $PY "$T/server_setup_test.py"
run "персонажи: переименование"     $PY "$T/personas_rename_test.py"
run "род речи"                      $PY "$T/gender_test.py"
run "экспорт настроек"              $PY "$T/export_test.py"
run "отчёт: только новое с прошлого"   $PY "$T/report_fresh_test.py"
echo "== Сайт и телефон"
run "сервер речи"                   $PY "$T/speech_server_test.py"
run "телефон: руки"                 $PY "$T/android_hands_test.py"
run "телефон: журнал разговора"     $PY "$T/android_log_test.py"
exit $FAIL

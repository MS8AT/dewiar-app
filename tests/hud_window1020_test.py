"""20.10, 21:36, Ubuntu, 0.38.95: «Лира висит без глаз, не перетягивается, перезагрузил — не работает; настройки тоже
висят». Ядро при этом работало (журнал: запуск за 2 с, нажатия виджета доходили). Сломала правка тёмной рамки
clear_window_bg: CSS «прозрачно» окну виджета и всему внутри (и странице WebKit) + своя отрисовка окна
(set_app_paintable + draw). Откат на 0.38.94 у человека помог. На Xvfb и Mutter без видеокарты поломка не
воспроизводится, поэтому окно виджета возвращено к 0.38.94 и проверяется, что его фон и отрисовку снова не трогают."""
import os, re, sys
from pathlib import Path
ROOT = Path(os.environ.get("DEWIAR_ROOT") or Path(__file__).resolve().parent.parent)
fails = []


def ok(c, m):
    print(("✅ " if c else "❌ ") + m)
    if not c:
        fails.append(m)


src = (ROOT / "ui/app.py").read_text(encoding="utf-8")
code = re.sub(r"(?m)^\s*#.*$", "", src)
ok("set_app_paintable" not in code and 'connect("draw"' not in code, "окна виджета не рисуют кадр сами (без app_paintable и своего draw)")
ok("clear_window_bg" not in code and "STYLE_PROVIDER_PRIORITY_USER" not in code, "фон прозрачного окна и страницы WebKit не трогаем — как в 0.38.94")
ok('background_color="#0b0b0e", js_api=api' in src, "окно виджета создаётся как в 0.38.94")
print("\nИТОГ:", "всё прошло" if not fails else f"провалов {len(fails)}")
sys.exit(1 if fails else 0)
